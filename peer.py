"""
Synchronizacja P2P między węzłami DNS.

Protokół (JSON over TCP, 4-bajtowy prefiks długości, big-endian):

  HELLO   → {"t":"HELLO",    "id":"node-id", "zones":["z1.","z2."]}
  SYNC_REQ→ {"t":"SYNC_REQ", "zone":"z.", "since":42}
  SYNC_RESP→{"t":"SYNC_RESP","zone":"z.", "records":[...], "max_seq":99}
  UPDATE  → {"t":"UPDATE",   "zone":"z.", "record":{...}}
  PING    → {"t":"PING"}
  PONG    → {"t":"PONG"}
  ERROR   → {"t":"ERROR",    "msg":"..."}

Bezpieczeństwo:
  Każda wiadomość zawiera pole "sig": HMAC-SHA256(payload_bez_sig, shared_key).
  Klucz wspólny jest konfigurowany per-peer.
  Połączenie bez ważnego podpisu jest odrzucane.

Zasada synchronizacji (last-write-wins):
  Patrz zone.Zone._apply() — decyduje timestamp + origin jako tiebreaker.
  Węzeł nie re-broadcastuje odebranych aktualizacji (pętle niemożliwe).
"""
import asyncio
import hashlib
import hmac
import json
import logging
import struct
import time
from typing import Callable, Dict, List, Optional, Set

from .zone import ZoneStore, ResourceRecord

logger = logging.getLogger(__name__)

FRAME_MAX   = 16 * 1024 * 1024    # 16 MB — maksymalny rozmiar ramki
PING_EVERY  = 30                   # s
RECONNECT   = 10                   # s — czas oczekiwania przed ponownym połączeniem


# ── kodowanie ramek ────────────────────────────────────────────────────────────

def _sign(msg: dict, key: str) -> dict:
    payload = json.dumps(
        {k: v for k, v in msg.items() if k != "sig"},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    sig = hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()
    return {**msg, "sig": sig}


def _verify(msg: dict, key: str) -> bool:
    if "sig" not in msg:
        return False
    sig_recv = msg["sig"]
    payload = json.dumps(
        {k: v for k, v in msg.items() if k != "sig"},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    expected = hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig_recv, expected)


def _pack(msg: dict, key: str) -> bytes:
    signed = _sign(msg, key)
    data = json.dumps(signed, ensure_ascii=False).encode()
    return struct.pack(">I", len(data)) + data


async def _read_msg(reader: asyncio.StreamReader) -> Optional[dict]:
    try:
        header = await reader.readexactly(4)
        length = struct.unpack(">I", header)[0]
        if length == 0 or length > FRAME_MAX:
            logger.warning("Nieprawidłowa długość ramki: %d", length)
            return None
        payload = await reader.readexactly(length)
        return json.loads(payload)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, json.JSONDecodeError):
        return None


# ── połączenie z pojedynczym peerem ───────────────────────────────────────────

class PeerConnection:
    def __init__(self, host: str, port: int, key: str,
                 server_id: str, zones: ZoneStore,
                 on_invalidate: Callable[[str], None]):
        self.host = host
        self.port = port
        self._key = key
        self._sid = server_id
        self._zones = zones
        self._on_invalidate = on_invalidate
        self._writer: Optional[asyncio.StreamWriter] = None
        self._last_seq: Dict[str, int] = {}   # zone_origin → last known seq
        self._connected = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def send_update(self, zone_origin: str, rr: ResourceRecord) -> None:
        """Wyślij UPDATE do peera (wywołane po lokalnej zmianie)."""
        if not self._connected or self._writer is None:
            return
        msg = {
            "t": "UPDATE",
            "zone": zone_origin,
            "record": rr.to_dict(),
        }
        try:
            self._writer.write(_pack(msg, self._key))
            await self._writer.drain()
        except Exception as exc:
            logger.debug("Błąd wysyłania UPDATE do %s:%d: %s",
                         self.host, self.port, exc)

    # ── wewnętrzne ────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        while True:
            try:
                await self._connect_and_sync()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.info("Peer %s:%d rozłączony (%s), ponawiam za %ds",
                            self.host, self.port, exc, RECONNECT)
            self._connected = False
            await asyncio.sleep(RECONNECT)

    async def _connect_and_sync(self) -> None:
        logger.info("Łączę z peerem %s:%d …", self.host, self.port)
        reader, writer = await asyncio.open_connection(self.host, self.port)
        self._writer = writer
        self._connected = True
        logger.info("Połączono z peerem %s:%d", self.host, self.port)

        # HELLO
        zones_list = [z.origin for z in self._zones.all_zones()]
        writer.write(_pack({"t": "HELLO", "id": self._sid, "zones": zones_list},
                           self._key))
        await writer.drain()

        # Zadaj synchronizację dla każdej wspólnej strefy
        ping_task = asyncio.create_task(self._ping_loop(writer))
        try:
            await self._message_loop(reader, writer)
        finally:
            ping_task.cancel()
            writer.close()
            self._connected = False

    async def _ping_loop(self, writer: asyncio.StreamWriter) -> None:
        while True:
            await asyncio.sleep(PING_EVERY)
            try:
                writer.write(_pack({"t": "PING"}, self._key))
                await writer.drain()
            except Exception:
                return

    async def _message_loop(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        while True:
            msg = await _read_msg(reader)
            if msg is None:
                raise ConnectionError("Peer zamknął połączenie")
            if not _verify(msg, self._key):
                logger.warning("Nieprawidłowy podpis od %s:%d",
                               self.host, self.port)
                continue
            await self._handle(msg, writer)

    async def _handle(self, msg: dict, writer: asyncio.StreamWriter) -> None:
        t = msg.get("t")

        if t == "HELLO":
            peer_zones: List[str] = msg.get("zones", [])
            my_zones = {z.origin for z in self._zones.all_zones()}
            for zo in peer_zones:
                if zo in my_zones:
                    since = self._last_seq.get(zo, 0)
                    writer.write(_pack(
                        {"t": "SYNC_REQ", "zone": zo, "since": since},
                        self._key,
                    ))
            await writer.drain()

        elif t == "SYNC_REQ":
            zo = msg.get("zone", "")
            since = int(msg.get("since", 0))
            zone = self._zones.get_zone(zo)
            if zone is None:
                return
            records = [r.to_dict() for r in zone.journal(since)]
            writer.write(_pack({
                "t": "SYNC_RESP", "zone": zo,
                "records": records, "max_seq": zone.max_seq,
            }, self._key))
            await writer.drain()

        elif t == "SYNC_RESP":
            zo = msg.get("zone", "")
            zone = self._zones.get_zone(zo)
            if zone is None:
                return
            for rd in msg.get("records", []):
                rr = ResourceRecord.from_dict(rd)
                changed = zone.apply_remote(rr)
                if changed:
                    self._on_invalidate(rr.name or zo)
            self._last_seq[zo] = int(msg.get("max_seq", 0))
            logger.debug("SYNC_RESP %s: %d rekordów, max_seq=%d",
                         zo, len(msg.get("records", [])),
                         self._last_seq[zo])

        elif t == "UPDATE":
            zo = msg.get("zone", "")
            zone = self._zones.get_zone(zo)
            if zone is None:
                return
            rr = ResourceRecord.from_dict(msg["record"])
            changed = zone.apply_remote(rr)
            if changed:
                self._on_invalidate(rr.name or zo)
                self._last_seq[zo] = max(
                    self._last_seq.get(zo, 0), rr.seq
                )

        elif t == "PING":
            writer.write(_pack({"t": "PONG"}, self._key))
            await writer.drain()

        elif t == "PONG":
            pass  # heartbeat OK

        else:
            logger.debug("Nieznany typ wiadomości P2P: %s", t)


# ── serwer nasłuchu P2P ────────────────────────────────────────────────────────

class PeerServer:
    """Nasłuchuje na połączenia przychodzące od innych węzłów."""

    def __init__(self, host: str, port: int,
                 server_id: str, zones: ZoneStore,
                 peer_keys: Dict[str, str],       # ip → key
                 on_invalidate: Callable[[str], None]):
        self.host = host
        self.port = port
        self._sid = server_id
        self._zones = zones
        self._peer_keys = peer_keys
        self._on_invalidate = on_invalidate
        self._server = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        logger.info("P2P serwer nasłuchuje na %s:%d", self.host, self.port)

    async def _handle_client(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter) -> None:
        peer_addr = writer.get_extra_info("peername", ("?", 0))
        peer_ip = peer_addr[0]
        logger.info("Nowe połączenie P2P od %s", peer_ip)

        # Wybierz klucz — sprawdzamy po IP, fallback na klucz wildcard "*"
        key = self._peer_keys.get(peer_ip) or self._peer_keys.get("*")
        if key is None:
            logger.warning("Brak klucza dla peera %s — odrzucam", peer_ip)
            writer.close()
            return

        # Obsługa symetryczna — serwer też wysyła HELLO
        zones_list = [z.origin for z in self._zones.all_zones()]
        writer.write(_pack({"t": "HELLO", "id": self._sid, "zones": zones_list}, key))
        await writer.drain()

        # Dalej — taka sama pętla jak w kliencie, ale nie robimy re-sync
        try:
            while True:
                msg = await _read_msg(reader)
                if msg is None:
                    break
                if not _verify(msg, key):
                    logger.warning("Nieprawidłowy podpis P2P od %s", peer_ip)
                    continue
                await self._dispatch(msg, writer, key)
        except Exception as exc:
            logger.debug("Peer %s rozłączony: %s", peer_ip, exc)
        finally:
            writer.close()

    async def _dispatch(self, msg: dict, writer: asyncio.StreamWriter,
                        key: str) -> None:
        t = msg.get("t")

        if t == "HELLO":
            # Peer asked for our zones — it will send SYNC_REQ after receiving our HELLO
            pass  # serwer już wysłał HELLO — peer sam wyśle SYNC_REQ

        elif t == "SYNC_REQ":
            zo = msg.get("zone", "")
            since = int(msg.get("since", 0))
            zone = self._zones.get_zone(zo)
            if zone is None:
                return
            records = [r.to_dict() for r in zone.journal(since)]
            writer.write(_pack({
                "t": "SYNC_RESP", "zone": zo,
                "records": records, "max_seq": zone.max_seq,
            }, key))
            await writer.drain()

        elif t == "SYNC_RESP":
            zo = msg.get("zone", "")
            zone = self._zones.get_zone(zo)
            if zone is None:
                return
            for rd in msg.get("records", []):
                rr = ResourceRecord.from_dict(rd)
                changed = zone.apply_remote(rr)
                if changed:
                    self._on_invalidate(rr.name or zo)

        elif t == "UPDATE":
            zo = msg.get("zone", "")
            zone = self._zones.get_zone(zo)
            if zone is None:
                return
            rr = ResourceRecord.from_dict(msg["record"])
            changed = zone.apply_remote(rr)
            if changed:
                self._on_invalidate(rr.name or zo)

        elif t == "PING":
            writer.write(_pack({"t": "PONG"}, key))
            await writer.drain()


# ── menedżer wszystkich połączeń ──────────────────────────────────────────────

class PeerManager:
    def __init__(self, server_id: str, zones: ZoneStore, cache,
                 peers_cfg: list, listen_host: str, listen_port: int):
        self._sid = server_id
        self._zones = zones
        self._cache = cache
        self._connections: List[PeerConnection] = []

        # Zbuduj mapę ip → klucz dla serwera
        peer_keys: Dict[str, str] = {}
        for p in peers_cfg:
            peer_keys[p["host"]] = p["key"]

        def invalidate(name: str) -> None:
            self._cache.invalidate(name)

        # Serwer P2P (nasłuch)
        if listen_port:
            self._server = PeerServer(
                listen_host, listen_port,
                server_id, zones, peer_keys, invalidate,
            )
        else:
            self._server = None

        # Połączenia wychodzące
        for p in peers_cfg:
            conn = PeerConnection(
                host=p["host"], port=int(p.get("port", 5353)),
                key=p["key"], server_id=server_id,
                zones=zones, on_invalidate=invalidate,
            )
            self._connections.append(conn)
            # Rejestruj callback na zmianę w strefie → broadcast
            for zone in zones.all_zones():
                orig_cb = zone.on_change

                def _make_cb(c: PeerConnection, prev):
                    def cb(z, rr: ResourceRecord):
                        if prev:
                            prev(z, rr)
                        asyncio.create_task(
                            c.send_update(z.origin, rr)
                        )
                    return cb

                zone.on_change = _make_cb(conn, orig_cb)

    async def start(self) -> None:
        if self._server:
            await self._server.start()
        for conn in self._connections:
            conn.start()

    def stop(self) -> None:
        for conn in self._connections:
            conn.stop()
