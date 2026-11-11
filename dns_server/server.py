"""
Serwer DNS: UDP i TCP na porcie 53.

UDP: asyncio DatagramProtocol — każde zapytanie obsługiwane niezależnie.
TCP: asyncio StreamReader/Writer — obsługa wielu zapytań w jednym połączeniu
     (pipelining zgodnie z RFC 7766), z 2-bajtowym prefiksem długości.
"""
import asyncio
import logging
import struct
from typing import Optional

from .resolver import Resolver

logger = logging.getLogger(__name__)

# Maksymalny rozmiar pakietu UDP DNS (bez EDNS0 rozszerzenia)
UDP_MAX = 512
# Limit długości sesji TCP — ochrona przed slow-read
TCP_TIMEOUT = 30.0


# ── UDP ───────────────────────────────────────────────────────────────────────

class DnsUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, resolver: Resolver):
        self._resolver = resolver
        self._transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.ensure_future(self._handle(data, addr))

    async def _handle(self, data: bytes, addr) -> None:
        client_ip = addr[0]
        try:
            response = await self._resolver.handle(data, client_ip)
            if response:
                # Obetnij do 512 bajtów jeśli klient nie zgłosił EDNS0
                # (dnslib sam ustawi TC-bit gdy odpowiedź za duża)
                if self._transport:
                    self._transport.sendto(response, addr)
        except Exception as exc:
            logger.error("UDP handler error od %s: %s", client_ip, exc)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UDP error: %s", exc)


# ── TCP ───────────────────────────────────────────────────────────────────────

class DnsTcpHandler:
    """Obsługuje jedno połączenie TCP — może zawierać wiele zapytań."""

    def __init__(self, resolver: Resolver,
                 reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter):
        self._resolver = resolver
        self._reader = reader
        self._writer = writer

    async def run(self) -> None:
        peer = self._writer.get_extra_info("peername", ("?", 0))
        client_ip = peer[0]
        try:
            while True:
                # RFC 1035 §4.2.2: 2-bajtowy big-endian prefiks długości
                try:
                    header = await asyncio.wait_for(
                        self._reader.readexactly(2), TCP_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    break
                length = struct.unpack("!H", header)[0]
                if length == 0:
                    break
                try:
                    data = await asyncio.wait_for(
                        self._reader.readexactly(length), TCP_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    break

                response = await self._resolver.handle(data, client_ip)
                if response:
                    self._writer.write(struct.pack("!H", len(response)) + response)
                    await self._writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception as exc:
            logger.debug("TCP handler error od %s: %s", client_ip, exc)
        finally:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass


# ── główna klasa serwera ──────────────────────────────────────────────────────

class DnsServer:
    def __init__(self, host: str, port: int, resolver: Resolver,
                 enable_udp: bool = True, enable_tcp: bool = True):
        self._host = host
        self._port = port
        self._resolver = resolver
        self._enable_udp = enable_udp
        self._enable_tcp = enable_tcp
        self._udp_transport = None
        self._tcp_server = None

    async def start(self) -> None:
        loop = asyncio.get_event_loop()

        if self._enable_udp:
            self._udp_transport, _ = await loop.create_datagram_endpoint(
                lambda: DnsUdpProtocol(self._resolver),
                local_addr=(self._host, self._port),
            )
            logger.info("DNS UDP nasłuchuje na %s:%d", self._host, self._port)

        if self._enable_tcp:
            self._tcp_server = await asyncio.start_server(
                self._tcp_client_handler,
                self._host, self._port,
            )
            logger.info("DNS TCP nasłuchuje na %s:%d", self._host, self._port)

    async def _tcp_client_handler(self, reader: asyncio.StreamReader,
                                   writer: asyncio.StreamWriter) -> None:
        handler = DnsTcpHandler(self._resolver, reader, writer)
        await handler.run()

    async def stop(self) -> None:
        if self._udp_transport:
            self._udp_transport.close()
        if self._tcp_server:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
