"""
REST API do zarządzania serwerem DNS (oparte wyłącznie na standardowej bibliotece).

Endpointy:
  GET    /api/v1/zones                   – lista stref
  GET    /api/v1/zones/<name>/records    – rekordy w strefie
  POST   /api/v1/zones/<name>/records    – dodaj rekord
  PUT    /api/v1/zones/<name>/records    – zmień rekord
  DELETE /api/v1/zones/<name>/records    – usuń rekord
  GET    /api/v1/stats                   – statystyki serwera
  GET    /api/v1/health                  – health check
"""
import asyncio
import hmac
import json
import logging
import re
import ssl
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from .acl import Acl
from .cache import Cache
from .resolver import Resolver
from .zone import Zone, ZoneStore

logger = logging.getLogger(__name__)

# Limity i timeouty (ochrona przed Slowloris i dużymi payloadami)
HEADER_TIMEOUT = 10.0
BODY_TIMEOUT = 10.0
MAX_HEADER_BYTES = 16 * 1024       # 16 KB
MAX_BODY_BYTES = 1024 * 1024       # 1 MB

# Domyślny rate limiting
DEFAULT_RATE_LIMIT_REQUESTS = 60
DEFAULT_RATE_LIMIT_WINDOW = 60.0   # sekundy

# Mapowanie metod HTTP na granularne uprawnienia ACL
METHOD_PERMISSIONS = {
    "GET": "api_read",
    "POST": "add",
    "PUT": "update",
    "DELETE": "delete",
}


@dataclass
class RateLimitEntry:
    """Wpis rate limitera per IP."""
    count: int = 0
    window_start: float = 0.0

    def is_expired(self, now: float, window: float) -> bool:
        return (now - self.window_start) > window

    def increment(self, now: float, limit: int, window: float) -> bool:
        """Zwraca True jeśli jest miejsce, False jeśli limit przekroczony."""
        if self.is_expired(now, window):
            self.count = 1
            self.window_start = now
            return True
        if self.count >= limit:
            return False
        self.count += 1
        return True


class ApiError(Exception):
    """Kontrolowany błąd HTTP zwracany jako JSON."""
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class ApiServer:
    """Lekki serwer REST API oparty na czystym asyncio."""

    def __init__(
        self,
        host: str,
        port: int,
        resolver: Resolver,
        zones: ZoneStore,
        acl: Acl,
        cache: Cache,
        peer_manager: Optional[Any] = None,
        cert_file: Optional[str] = None,
        key_file: Optional[str] = None,
        api_keys: Optional[List[str]] = None,
        trusted_proxies: Optional[List[str]] = None,
        rate_limit_requests: int = DEFAULT_RATE_LIMIT_REQUESTS,
        rate_limit_window: float = DEFAULT_RATE_LIMIT_WINDOW,
        state_file: Optional[str] = None,
    ):
        self._host = host
        self._port = port
        self._resolver = resolver
        self._zones = zones
        self._acl = acl
        self._cache = cache
        self._peer_manager = peer_manager
        self._cert_file = cert_file
        self._key_file = key_file
        self._api_keys: List[str] = list(api_keys or [])
        self._trusted_proxies: Set[str] = set(trusted_proxies or [])
        self._rate_limit_requests = rate_limit_requests
        self._rate_limit_window = rate_limit_window
        self._state_file = state_file

        self._server: Optional[asyncio.AbstractServer] = None
        self._rate_limits: Dict[str, RateLimitEntry] = {}
        self._last_gc: float = time.monotonic()

    # ── start / stop ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Uruchamia serwer API (HTTP lub HTTPS)."""
        ssl_context = None
        if self._cert_file and self._key_file:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(self._cert_file, self._key_file)
            logger.info(
                "API HTTPS włączony (cert: %s, key: %s)",
                self._cert_file,
                self._key_file,
            )
        else:
            logger.warning("API: HTTPS wyłączony (brak cert_file / key_file)")

        self._server = await asyncio.start_server(
            self._handle_connection,
            self._host,
            self._port,
            ssl=ssl_context,
        )
        logger.info(
            "REST API serwer uruchomiony: %s:%d %s",
            self._host,
            self._port,
            "(HTTPS)" if ssl_context else "(HTTP)",
        )

    async def stop(self) -> None:
        """Zatrzymuje serwer API."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("REST API serwer zatrzymany")

    # ── obsługa połączenia TCP i parsowanie HTTP/1.1 ────────────────────────

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peername = writer.get_extra_info("peername")
        peer_ip = peername[0] if peername else "0.0.0.0"

        try:
            method, path, query, headers, body = await self._read_http_request(reader)
            client_ip = self._resolve_client_ip(peer_ip, headers)

            # 1. Health check bez autoryzacji i limitów
            if method == "GET" and path == "/api/v1/health":
                await self._send_json(writer, 200, {"status": "ok"})
                return

            # 2. Warstwa sieciowa: ACL (CIDR + granularne uprawnienia)
            self._check_acl(client_ip, method)

            # 3. Ochrona przed nadużyciem: Rate Limit
            rl_headers = self._check_rate_limit(client_ip)

            # 4. Warstwa aplikacji: API-Key (stałoczasowe porównanie)
            self._check_api_key(client_ip, headers)

            # 5. Routing i wykonanie handlera
            status, payload = self._dispatch(method, path, query, body)
            await self._send_json(writer, status, payload, extra_headers=rl_headers)

        except ApiError as e:
            await self._send_json(
                writer,
                e.status,
                {"error": HTTPStatus(e.status).phrase, "message": e.message},
            )
        except asyncio.TimeoutError:
            await self._send_json(
                writer,
                408,
                {"error": "Request Timeout", "message": "Client read timeout"},
            )
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception:
            logger.exception("Nieoczekiwany błąd podczas obsługi żądania API od %s", peer_ip)
            await self._send_json(
                writer,
                500,
                {"error": "Internal Server Error", "message": "Internal server error"},
            )
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _read_http_request(
        self, reader: asyncio.StreamReader
    ) -> Tuple[str, str, Dict[str, List[str]], Dict[str, str], bytes]:
        """Odczytuje i parsuje pojedyncze żądanie HTTP/1.1 z limitami."""
        raw_head = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"), timeout=HEADER_TIMEOUT
        )
        if len(raw_head) > MAX_HEADER_BYTES:
            raise ApiError(431, "Request header fields too large")

        lines = raw_head.decode("latin-1").split("\r\n")
        request_line = lines[0].strip()
        parts = request_line.split(" ")
        if len(parts) != 3:
            raise ApiError(400, "Malformed HTTP request line")

        method, raw_target, version = parts
        method = method.upper()
        if not version.startswith("HTTP/1."):
            raise ApiError(505, "HTTP Version Not Supported")

        headers: Dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                continue
            if ":" not in line:
                raise ApiError(400, "Malformed HTTP header")
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()

        parsed = urlparse(raw_target)
        path = unquote(parsed.path).rstrip("/") or "/"
        query = parse_qs(parsed.query)

        body = b""
        content_length_str = headers.get("content-length")
        if content_length_str is not None:
            try:
                content_length = int(content_length_str)
            except ValueError:
                raise ApiError(400, "Invalid Content-Length header")

            if content_length < 0 or content_length > MAX_BODY_BYTES:
                raise ApiError(413, "Payload too large")

            if content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=BODY_TIMEOUT
                )

        return method, path, query, headers, body

    async def _send_json(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        payload: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Serializuje dict do JSON i wysyła kompletną odpowiedź HTTP/1.1."""
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        phrase = HTTPStatus(status).phrase

        response_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body_bytes)),
            "Connection": "close",
        }
        if extra_headers:
            response_headers.update(extra_headers)

        head = f"HTTP/1.1 {status} {phrase}\r\n" + "".join(
            f"{k}: {v}\r\n" for k, v in response_headers.items()
        ) + "\r\n"

        writer.write(head.encode("latin-1") + body_bytes)
        await writer.drain()

    # ── warstwy bezpieczeństwa ──────────────────────────────────────────────
    def _resolve_client_ip(self, peer_ip: str, headers: Dict[str, str]) -> str:
        """Honoruje X-Forwarded-For wyłącznie od zaufanych proxy."""
        if peer_ip in self._trusted_proxies:
            forwarded = headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return peer_ip

    def _check_acl(self, client_ip: str, method: str) -> None:
        """Sprawdza uprawnienia w module ACL."""
        required_perm = METHOD_PERMISSIONS.get(method)
        if not required_perm:
            raise ApiError(405, f"Method {method} not allowed")

        if hasattr(self._acl, "is_allowed"):
            allowed = self._acl.is_allowed(client_ip, required_perm) or self._acl.is_allowed(
                client_ip, "api"
            )
        else:
            allowed = self._acl.can_api(client_ip)

        if not allowed:
            logger.warning("API: brak uprawnień (%s) dla %s", required_perm, client_ip)
            raise ApiError(403, "Forbidden by ACL")

    def _check_rate_limit(self, client_ip: str) -> Dict[str, str]:
        """Weryfikuje limit żądań per IP i zwraca nagłówki X-RateLimit-*."""
        now = time.monotonic()

        if (now - self._last_gc) > self._rate_limit_window:
            self._rate_limits = {
                ip: entry
                for ip, entry in self._rate_limits.items()
                if not entry.is_expired(now, self._rate_limit_window)
            }
            self._last_gc = now

        entry = self._rate_limits.get(client_ip)
        if entry is None:
            entry = RateLimitEntry()
            self._rate_limits[client_ip] = entry

        if not entry.increment(now, self._rate_limit_requests, self._rate_limit_window):
            logger.warning("API: rate limit przekroczony dla %s", client_ip)
            raise ApiError(429, "Rate limit exceeded")

        remaining = max(0, self._rate_limit_requests - entry.count)
        return {
            "X-RateLimit-Limit": str(self._rate_limit_requests),
            "X-RateLimit-Remaining": str(remaining),
        }

    def _check_api_key(self, client_ip: str, headers: Dict[str, str]) -> None:
        """Weryfikuje API-Key z użyciem hmac.compare_digest."""
        if not self._api_keys:
            return

        provided_key = headers.get("x-api-key", "")
        if not provided_key:
            auth = headers.get("authorization", "")
            if auth.startswith("Bearer "):
                provided_key = auth[7:].strip()
            else:
                provided_key = auth.strip()

        if not provided_key or not any(
            hmac.compare_digest(provided_key, valid) for valid in self._api_keys
        ):
            logger.warning("API: nieprawidłowy API-Key od %s", client_ip)
            raise ApiError(401, "Invalid or missing API key")

    # ── routing i logika domenowa ───────────────────────────────────────────

    def _dispatch(
        self,
        method: str,
        path: str,
        query: Dict[str, List[str]],
        body: bytes,
    ) -> Tuple[int, Dict[str, Any]]:
        if path == "/api/v1/zones":
            if method == "GET":
                return self._handle_list_zones()
            if method == "POST":
                return self._handle_add_zone(self._parse_json(body))
            raise ApiError(405, "Method not allowed")

        if path == "/api/v1/stats":
            if method != "GET":
                raise ApiError(405, "Method not allowed")
            return self._handle_stats()

        segments = path.strip("/").split("/")
        if (
            len(segments) == 4
            and segments[0] == "api"
            and segments[1] == "v1"
            and segments[2] == "zones"
        ):
            zone_name = segments[3]
            if method == "PUT":
                return self._handle_rename_zone(
                    zone_name, self._parse_json(body)
                )
            if method == "DELETE":
                return self._handle_delete_zone(zone_name)
            raise ApiError(405, "Method not allowed")

        if (
            len(segments) == 5
            and segments[0] == "api"
            and segments[1] == "v1"
            and segments[2] == "zones"
            and segments[4] == "records"
        ):
            zone_name = segments[3]
            if method == "GET":
                return self._handle_get_records(zone_name, query)
            if method == "POST":
                return self._handle_add_record(zone_name, self._parse_json(body))
            if method == "PUT":
                return self._handle_update_record(zone_name, self._parse_json(body))
            if method == "DELETE":
                return self._handle_delete_record(zone_name, self._parse_json(body))
            raise ApiError(405, "Method not allowed")

        raise ApiError(404, "Endpoint not found")

    @staticmethod
    def _parse_json(body: bytes) -> Dict[str, Any]:
        if not body:
            raise ApiError(400, "Empty request body")
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Invalid JSON payload")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON payload must be an object")
        return data

    def _get_zone(self, raw_zone: str) -> Zone:
        zone_name = raw_zone.strip().lower().rstrip(".") + "."
        zone = self._zones.zones.get(zone_name)
        if not zone:
            raise ApiError(404, f"Zone {zone_name} not found")
        return zone

    @staticmethod
    def _normalize_zone_name(raw_name: Any) -> str:
        if not isinstance(raw_name, str):
            raise ApiError(400, "Field 'name' must be a string")
        name = raw_name.strip().lower().rstrip(".")
        labels = name.split(".")
        if (
            not name
            or len(name) > 253
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            )
        ):
            raise ApiError(400, "Field 'name' must be a valid DNS zone name")
        return name + "."

    def _persist_state(self) -> None:
        if not self._state_file:
            return
        try:
            self._zones.save_state(self._state_file)
        except Exception as exc:
            logger.exception("Nie można zapisać stanu DNS do %s", self._state_file)
            raise ApiError(500, "DNS state could not be saved") from exc

    @staticmethod
    def _normalize_record_name(raw_name: Any) -> str:
        """Normalizuje nazwę rekordu; '' oraz '@' reprezentują apex strefy."""
        if not isinstance(raw_name, str):
            raise ApiError(400, "Field 'name' must be a string")
        name = raw_name.strip()
        return "" if name in ("", "@") else name

    def _invalidate_record_cache(self, name: str, zone_origin: str, rtype: str) -> None:
        fqdn = zone_origin if name == "" else f"{name}.{zone_origin}"
        self._cache.invalidate(fqdn, rtype)

    def _notify_peers(self, zone: Zone, rr: Any) -> None:
        """Propaguje zmianę do peerów P2P, jeśli PeerManager jest aktywny."""
        if self._peer_manager and hasattr(self._peer_manager, "broadcast_update"):
            self._peer_manager.broadcast_update(zone.origin, rr)

    # ── handlery endpointów ─────────────────────────────────────────────────

    def _handle_add_zone(
        self, data: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        name = self._normalize_zone_name(data.get("name"))
        try:
            zone = self._zones.add_zone(name)
        except ValueError as exc:
            raise ApiError(409, str(exc)) from exc
        self._persist_state()
        return 201, {"name": zone.origin}

    def _handle_rename_zone(
        self, raw_zone: str, data: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        old_name = self._normalize_zone_name(raw_zone)
        new_name = self._normalize_zone_name(data.get("name"))
        try:
            zone = self._zones.rename_zone(old_name, new_name)
        except KeyError as exc:
            raise ApiError(404, f"Zone {old_name} not found") from exc
        except ValueError as exc:
            raise ApiError(409, str(exc)) from exc
        self._persist_state()
        return 200, {"old_name": old_name, "name": zone.origin}

    def _handle_delete_zone(
        self, raw_zone: str
    ) -> Tuple[int, Dict[str, Any]]:
        name = self._normalize_zone_name(raw_zone)
        try:
            self._zones.delete_zone(name)
        except KeyError as exc:
            raise ApiError(404, f"Zone {name} not found") from exc
        self._persist_state()
        return 200, {"name": name, "deleted": True}

    def _handle_list_zones(self) -> Tuple[int, Dict[str, Any]]:
        zones = [
            {
                "name": zone.origin,
                "records_count": sum(
                    1 for rr in zone._records.values() if not rr.deleted
                ),
                "max_seq": zone.max_seq,
            }
            for zone in self._zones.zones.values()
        ]
        return 200, {"zones": zones}

    def _handle_get_records(
        self, raw_zone: str, query: Dict[str, List[str]]
    ) -> Tuple[int, Dict[str, Any]]:
        zone = self._get_zone(raw_zone)
        filter_name = query.get("name", [""])[0].lower()
        filter_type = query.get("type", [""])[0].upper()

        records = []
        for rr in zone._records.values():
            if rr.deleted:
                continue
            if filter_name and not rr.name.lower().startswith(filter_name):
                continue
            if filter_type and rr.rtype != filter_type:
                continue
            records.append(
                {
                    "uid": rr.uid,
                    "name": rr.name,
                    "type": rr.rtype,
                    "ttl": rr.ttl,
                    "rdata": rr.rdata,
                    "seq": rr.seq,
                    "timestamp": rr.ts,
                }
            )
        return 200, {"zone": zone.origin, "records": records}

    def _handle_add_record(
        self, raw_zone: str, data: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        zone = self._get_zone(raw_zone)

        if "name" not in data:
            raise ApiError(400, "Missing required field: name")
        name = self._normalize_record_name(data.get("name"))

        rtype = data.get("type", "")
        if not isinstance(rtype, str) or not rtype.strip():
            raise ApiError(400, "Missing or invalid field: type")
        rtype = rtype.strip().upper()

        ttl = data.get("ttl", 300)
        if not isinstance(ttl, int) or ttl < 0:
            raise ApiError(400, "Field 'ttl' must be a non-negative integer")

        rdata = data.get("rdata")
        if not isinstance(rdata, dict) or not rdata:
            raise ApiError(400, "Missing or invalid field: rdata")

        existing = zone.find_record(name, rtype, ttl, rdata)
        if existing is not None:
            return 200, {
                "uid": existing.uid,
                "name": existing.name,
                "type": existing.rtype,
                "ttl": existing.ttl,
                "rdata": existing.rdata,
            }

        rr = zone.add_record(name=name, rtype=rtype, ttl=ttl, rdata=rdata)
        self._invalidate_record_cache(name, zone.origin, rtype)
        self._persist_state()
        self._notify_peers(zone, rr)

        return 201, {
            "uid": rr.uid,
            "name": rr.name,
            "type": rr.rtype,
            "ttl": rr.ttl,
            "rdata": rr.rdata,
        }

    def _handle_update_record(
        self, raw_zone: str, data: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        zone = self._get_zone(raw_zone)

        uid = data.get("uid")
        if not isinstance(uid, str) or not uid.strip():
            raise ApiError(400, "Missing required field: uid")

        existing = zone._records.get(uid)
        if not existing or existing.deleted:
            raise ApiError(404, f"Record {uid} not found")

        if "name" not in data:
            raise ApiError(400, "Missing required field: name")
        name = self._normalize_record_name(data.get("name"))

        rtype = data.get("type", "")
        if not isinstance(rtype, str) or not rtype.strip():
            raise ApiError(400, "Missing or invalid field: type")
        rtype = rtype.strip().upper()

        ttl = data.get("ttl", 300)
        if not isinstance(ttl, int) or ttl < 0:
            raise ApiError(400, "Field 'ttl' must be a non-negative integer")

        rdata = data.get("rdata")
        if not isinstance(rdata, dict) or not rdata:
            raise ApiError(400, "Missing or invalid field: rdata")

        old_name, old_rtype = existing.name, existing.rtype
        zone.delete_record(uid)
        self._invalidate_record_cache(old_name, zone.origin, old_rtype)

        rr = zone.add_record(name=name, rtype=rtype, ttl=ttl, rdata=rdata, uid=uid)
        self._invalidate_record_cache(name, zone.origin, rtype)
        self._persist_state()
        self._notify_peers(zone, rr)

        return 200, {
            "uid": rr.uid,
            "name": rr.name,
            "type": rr.rtype,
            "ttl": rr.ttl,
            "rdata": rr.rdata,
        }

    def _handle_delete_record(
        self, raw_zone: str, data: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        zone = self._get_zone(raw_zone)

        uid = data.get("uid")
        if not isinstance(uid, str) or not uid.strip():
            raise ApiError(400, "Missing required field: uid")

        existing = zone._records.get(uid)
        if not existing or existing.deleted:
            raise ApiError(404, f"Record {uid} not found")

        zone.delete_record(uid)
        self._invalidate_record_cache(existing.name, zone.origin, existing.rtype)
        self._persist_state()
        self._notify_peers(zone, existing)

        return 200, {"uid": uid, "deleted": True}

    def _handle_stats(self) -> Tuple[int, Dict[str, Any]]:
        total_queries = self._cache.hits + self._cache.misses
        return 200, {
            "cache": {
                "hits": self._cache.hits,
                "misses": self._cache.misses,
                "hit_rate": (
                    self._cache.hits / total_queries if total_queries > 0 else 0.0
                ),
            },
            "zones_count": len(self._zones.zones),
            "total_records": sum(
                sum(1 for rr in z._records.values() if not rr.deleted)
                for z in self._zones.zones.values()
            ),
        }
