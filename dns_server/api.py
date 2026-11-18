"""
REST API do zarządzania serwerem DNS.

Endpointy:
  GET    /api/v1/zones                   – lista stref
  GET    /api/v1/zones/<name>/records    – rekordy w strefie
  POST   /api/v1/zones/<name>/records    – dodaj rekord
  PUT    /api/v1/zones/<name>/records    – zmień rekord
  DELETE /api/v1/zones/<name>/records    – usuń rekord
  GET    /api/v1/stats                   – statystyki serwera

Zabezpieczenia:
  - HTTPS (opcjonalnie)
  - API-Key (w nagłówku Authorization lub X-API-Key)
  - ACL z permisją 'api'
  - Rate limiting (10 req/60s per IP)
  - Ochrona przed slowloris (timeout na zapisy)
  - JSON request/response
"""
import asyncio
import logging
import json
import ssl
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Any, List
from pathlib import Path

import aiohttp
from aiohttp import web

from .acl import Acl
from .cache import Cache
from .zone import Zone, ZoneStore
from .resolver import Resolver

logger = logging.getLogger(__name__)

# Timeout dla klienta wysyłającego dane (ochrona przed slowloris)
BODY_TIMEOUT = 10.0
# Limit zapytań per IP per okno czasu
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW = 60.0  # sekund

# Nagłówki do sprawdzenia API-Key
API_KEY_HEADERS = ["Authorization", "X-API-Key"]


@dataclass
class RateLimitEntry:
    """Wpis rate limitera."""
    count: int = 0
    window_start: float = 0.0

    def is_expired(self) -> bool:
        return time.time() - self.window_start > RATE_LIMIT_WINDOW

    def reset(self) -> None:
        self.count = 1
        self.window_start = time.time()

    def increment(self) -> bool:
        """Zwraca True jeśli jest miejsce, False jeśli limit przekroczony."""
        if self.is_expired():
            self.reset()
        else:
            if self.count >= RATE_LIMIT_REQUESTS:
                return False
            self.count += 1
        return True


class ApiServer:
    """REST API serwer z asyncio (aiohttp)."""

    def __init__(
        self,
        host: str,
        port: int,
        resolver: Resolver,
        zones: ZoneStore,
        acl: Acl,
        cache: Cache,
        cert_file: Optional[str] = None,
        key_file: Optional[str] = None,
        api_keys: Optional[List[str]] = None,
    ):
        self._host = host
        self._port = port
        self._resolver = resolver
        self._zones = zones
        self._acl = acl
        self._cache = cache
        self._cert_file = cert_file
        self._key_file = key_file
        self._api_keys = set(api_keys or [])  # Szybki lookup

        self._app = web.Application()
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

        # Rate limiting
        self._rate_limits: Dict[str, RateLimitEntry] = {}

        # Middleware
        self._app.middlewares.append(self._api_key_middleware)
        self._app.middlewares.append(self._auth_middleware)
        self._app.middlewares.append(self._rate_limit_middleware)

        # Routes
        self._setup_routes()

    # ── konfiguracja tras ───────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        """Rejestruje wszystkie endpointy."""
        self._app.router.add_get("/api/v1/zones", self._handle_list_zones)
        self._app.router.add_get(
            "/api/v1/zones/{zone}/records", self._handle_get_records
        )
        self._app.router.add_post(
            "/api/v1/zones/{zone}/records", self._handle_add_record
        )
        self._app.router.add_put(
            "/api/v1/zones/{zone}/records", self._handle_update_record
        )
        self._app.router.add_delete(
            "/api/v1/zones/{zone}/records", self._handle_delete_record
        )
        self._app.router.add_get("/api/v1/stats", self._handle_stats)
        self._app.router.add_get("/api/v1/health", self._handle_health)

    # ── middleware ──────────────────────────────────────────────────────────

    @web.middleware
    async def _api_key_middleware(
        self, request: web.Request, handler
    ) -> web.Response:
        """Sprawdza API-Key jeśli zdefiniowane."""
        # Health check bez API-Key
        if request.path == "/api/v1/health":
            return await handler(request)

        # Jeśli nie ma API-Key w konfiguracji, skip
        if not self._api_keys:
            return await handler(request)

        # Pobierz API-Key z nagłówków
        api_key = None
        for header in API_KEY_HEADERS:
            value = request.headers.get(header, "")
            if value:
                # Authorization: Bearer <key> or Authorization: <key>
                if header == "Authorization" and value.startswith("Bearer "):
                    api_key = value[7:].strip()
                else:
                    api_key = value.strip()
                break

        if not api_key or api_key not in self._api_keys:
            client_ip = self._get_client_ip(request)
            logger.warning("API: nieprawidłowy API-Key od %s", client_ip)
            return web.json_response(
                {"error": "Unauthorized", "message": "Invalid or missing API key"},
                status=401,
            )

        request["api_key_valid"] = True
        return await handler(request)

    @web.middleware
    async def _auth_middleware(
        self, request: web.Request, handler
    ) -> web.Response:
        """Sprawdza uprawnienia ACL."""
        client_ip = self._get_client_ip(request)
        
        # Health check bez ACL
        if request.path == "/api/v1/health":
            return await handler(request)

        if not self._acl.can_api(client_ip):
            logger.warning("API: brak uprawnień dla %s", client_ip)
            return web.json_response(
                {"error": "Forbidden", "message": "No API access"},
                status=403,
            )

        # Zapisz IP w request dla logger'ów
        request["client_ip"] = client_ip
        return await handler(request)

    @web.middleware
    async def _rate_limit_middleware(
        self, request: web.Request, handler
    ) -> web.Response:
        """Rate limiting per IP."""
        client_ip = self._get_client_ip(request)

        # Health check bez rate limitingu
        if request.path == "/api/v1/health":
            return await handler(request)

        entry = self._rate_limits.get(client_ip)
        if entry is None:
            entry = RateLimitEntry()
            self._rate_limits[client_ip] = entry

        if not entry.increment():
            logger.warning("API: rate limit przekroczony dla %s", client_ip)
            return web.json_response(
                {"error": "Too Many Requests", "message": "Rate limit exceeded"},
                status=429,
            )

        response = await handler(request)

        # Wyślij rate limit headers
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(
            RATE_LIMIT_REQUESTS - entry.count
        )

        return response

    @staticmethod
    def _get_client_ip(request: web.Request) -> str:
        """Pobiera rzeczywisty IP klienta (obsługa X-Forwarded-For)."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        peername = request.transport.get_extra_info("peername")
        if peername:
            return peername[0]
        return "0.0.0.0"

    # ── handlery ────────────────────────────────────────────────────────────

    async def _handle_list_zones(self, request: web.Request) -> web.Response:
        """GET /api/v1/zones – lista wszystkich stref."""
        try:
            zones = []
            for zone in self._zones.zones.values():
                zones.append({
                    "name": zone.origin,
                    "records_count": len(zone._records),
                    "max_seq": zone.max_seq,
                })
            return web.json_response({"zones": zones})
        except Exception as e:
            logger.error("API list_zones error: %s", e)
            return web.json_response(
                {"error": "Internal Server Error", "message": str(e)},
                status=500,
            )

    async def _handle_get_records(self, request: web.Request) -> web.Response:
        """GET /api/v1/zones/{zone}/records – rekordy w strefie."""
        zone_name = request.match_info.get("zone")
        if not zone_name:
            return web.json_response(
                {"error": "Bad Request", "message": "Missing zone name"},
                status=400,
            )

        try:
            # Zapewni, że nazwa jest zakończona kropką
            zone_name = zone_name.lower().rstrip(".") + "."

            zone = self._zones.zones.get(zone_name)
            if not zone:
                return web.json_response(
                    {"error": "Not Found", "message": f"Zone {zone_name} not found"},
                    status=404,
                )

            # Opcjonalne filtrowanie po nazwie lub typie
            filter_name = request.query.get("name", "").lower()
            filter_type = request.query.get("type", "").upper()

            records = []
            for uid, rr in zone._records.items():
                if rr.deleted:
                    continue
                if filter_name and not rr.name.lower().startswith(filter_name):
                    continue
                if filter_type and rr.rtype != filter_type:
                    continue

                records.append({
                    "uid": rr.uid,
                    "name": rr.name,
                    "type": rr.rtype,
                    "ttl": rr.ttl,
                    "rdata": rr.rdata,
                    "seq": rr.seq,
                    "timestamp": rr.ts,
                })

            return web.json_response({"zone": zone_name, "records": records})
        except Exception as e:
            logger.error("API get_records error: %s", e)
            return web.json_response(
                {"error": "Internal Server Error", "message": str(e)},
                status=500,
            )

    async def _handle_add_record(self, request: web.Request) -> web.Response:
        """POST /api/v1/zones/{zone}/records – dodaj rekord."""
        zone_name = request.match_info.get("zone")
        if not zone_name:
            return web.json_response(
                {"error": "Bad Request", "message": "Missing zone name"},
                status=400,
            )

        try:
            zone_name = zone_name.lower().rstrip(".") + "."
            zone = self._zones.zones.get(zone_name)
            if not zone:
                return web.json_response(
                    {"error": "Not Found", "message": f"Zone {zone_name} not found"},
                    status=404,
                )

            # Czytaj JSON z limitem timeout'u (ochrona slowloris)
            try:
                data = await asyncio.wait_for(request.json(), timeout=BODY_TIMEOUT)
            except asyncio.TimeoutError:
                return web.json_response(
                    {"error": "Request Timeout", "message": "Request body timeout"},
                    status=408,
                )

            # Walidacja
            name = data.get("name", "").strip()
            rtype = data.get("type", "").upper()
            ttl = data.get("ttl", 300)
            rdata = data.get("rdata", {})

            if not name or not rtype or not isinstance(rdata, dict):
                return web.json_response(
                    {
                        "error": "Bad Request",
                        "message": "Missing or invalid: name, type, rdata",
                    },
                    status=400,
                )

            # Dodaj rekord
            rr = zone.add_record(name=name, rtype=rtype, ttl=ttl, rdata=rdata)
            
            # Invalidate cache
            self._cache.invalidate(f"{name}.{zone_name}", rtype)

            return web.json_response(
                {
                    "uid": rr.uid,
                    "name": rr.name,
                    "type": rr.rtype,
                    "ttl": rr.ttl,
                    "rdata": rr.rdata,
                },
                status=201,
            )
        except Exception as e:
            logger.error("API add_record error: %s", e)
            return web.json_response(
                {"error": "Internal Server Error", "message": str(e)},
                status=500,
            )

    async def _handle_update_record(self, request: web.Request) -> web.Response:
        """PUT /api/v1/zones/{zone}/records – zmień rekord."""
        zone_name = request.match_info.get("zone")
        if not zone_name:
            return web.json_response(
                {"error": "Bad Request", "message": "Missing zone name"},
                status=400,
            )

        try:
            zone_name = zone_name.lower().rstrip(".") + "."
            zone = self._zones.zones.get(zone_name)
            if not zone:
                return web.json_response(
                    {"error": "Not Found", "message": f"Zone {zone_name} not found"},
                    status=404,
                )

            # Czytaj JSON
            try:
                data = await asyncio.wait_for(request.json(), timeout=BODY_TIMEOUT)
            except asyncio.TimeoutError:
                return web.json_response(
                    {"error": "Request Timeout", "message": "Request body timeout"},
                    status=408,
                )

            uid = data.get("uid")
            name = data.get("name", "").strip()
            rtype = data.get("type", "").upper()
            ttl = data.get("ttl", 300)
            rdata = data.get("rdata", {})

            if not uid or not name or not rtype:
                return web.json_response(
                    {"error": "Bad Request", "message": "Missing uid, name, or type"},
                    status=400,
                )

            # Usuń stary rekord
            if uid in zone._records:
                old_rr = zone._records[uid]
                zone.delete_record(uid)
                self._cache.invalidate(f"{old_rr.name}.{zone_name}", old_rr.rtype)

            # Dodaj nowy
            rr = zone.add_record(name=name, rtype=rtype, ttl=ttl, rdata=rdata, uid=uid)
            self._cache.invalidate(f"{name}.{zone_name}", rtype)

            return web.json_response(
                {
                    "uid": rr.uid,
                    "name": rr.name,
                    "type": rr.rtype,
                    "ttl": rr.ttl,
                    "rdata": rr.rdata,
                }
            )
        except Exception as e:
            logger.error("API update_record error: %s", e)
            return web.json_response(
                {"error": "Internal Server Error", "message": str(e)},
                status=500,
            )

    async def _handle_delete_record(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/zones/{zone}/records – usuń rekord."""
        zone_name = request.match_info.get("zone")
        if not zone_name:
            return web.json_response(
                {"error": "Bad Request", "message": "Missing zone name"},
                status=400,
            )

        try:
            zone_name = zone_name.lower().rstrip(".") + "."
            zone = self._zones.zones.get(zone_name)
            if not zone:
                return web.json_response(
                    {"error": "Not Found", "message": f"Zone {zone_name} not found"},
                    status=404,
                )

            # Czytaj JSON
            try:
                data = await asyncio.wait_for(request.json(), timeout=BODY_TIMEOUT)
            except asyncio.TimeoutError:
                return web.json_response(
                    {"error": "Request Timeout", "message": "Request body timeout"},
                    status=408,
                )

            uid = data.get("uid")
            if not uid:
                return web.json_response(
                    {"error": "Bad Request", "message": "Missing uid"},
                    status=400,
                )

            if uid not in zone._records:
                return web.json_response(
                    {"error": "Not Found", "message": f"Record {uid} not found"},
                    status=404,
                )

            rr = zone._records[uid]
            zone.delete_record(uid)
            self._cache.invalidate(f"{rr.name}.{zone_name}", rr.rtype)

            return web.json_response({"uid": uid, "deleted": True})
        except Exception as e:
            logger.error("API delete_record error: %s", e)
            return web.json_response(
                {"error": "Internal Server Error", "message": str(e)},
                status=500,
            )

    async def _handle_stats(self, request: web.Request) -> web.Response:
        """GET /api/v1/stats – statystyki serwera."""
        try:
            return web.json_response({
                "cache": {
                    "hits": self._cache.hits,
                    "misses": self._cache.misses,
                    "hit_rate": (
                        self._cache.hits / (self._cache.hits + self._cache.misses)
                        if self._cache.hits + self._cache.misses > 0
                        else 0
                    ),
                },
                "zones_count": len(self._zones.zones),
                "total_records": sum(
                    len(z._records) for z in self._zones.zones.values()
                ),
            })
        except Exception as e:
            logger.error("API stats error: %s", e)
            return web.json_response(
                {"error": "Internal Server Error", "message": str(e)},
                status=500,
            )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /api/v1/health – health check."""
        return web.json_response({"status": "ok"})

    # ── start/stop ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Uruchomi serwer API."""
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        # Opcjonalne HTTPS
        ssl_context = None
        if self._cert_file and self._key_file:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(self._cert_file, self._key_file)
            logger.info("API HTTPS włączony (cert: %s, key: %s)",
                       self._cert_file, self._key_file)
        else:
            logger.warning("API: HTTPS wyłączony (brak cert/key)")

        self._site = web.TCPSite(self._runner, self._host, self._port,
                                ssl_context=ssl_context)
        await self._site.start()
        logger.info("REST API serwer uruchomiony: %s:%d %s",
                   self._host, self._port,
                   "(HTTPS)" if ssl_context else "(HTTP)")

    async def stop(self) -> None:
        """Zatrzyma serwer API."""
        if self._runner:
            await self._runner.cleanup()
            logger.info("REST API serwer zatrzymany")
