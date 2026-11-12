"""
Rekurencyjny (iteracyjny) resolver DNS.

Algorytm:
  1. Zacznij od root-hints (lub skonfigurowanych forwarderów).
  2. Wyślij zapytanie do bieżącego serwera NS.
  3. Jeśli odpowiedź autorytatywna — zwróć.
  4. Jeśli referral (sekcja AUTHORITY z NS) — przejdź do nowych NS.
  5. Powtarzaj max MAX_DEPTH razy.

Forwarder mode (uproszczony, domyślny):
  Gdy skonfigurowane są forwarders[], zapytanie wysyłane jest wprost do nich
  zamiast do root-hints. Szybsze i prostsze dla sieci wewnętrznych.
"""
import asyncio
import logging
import socket
from typing import List, Optional, Tuple

try:
    from dnslib import DNSRecord, QTYPE, RR, DNSLabel
    from dnslib.dns import DNSError
except ImportError:
    raise ImportError("Zainstaluj: pip install dnslib")

logger = logging.getLogger(__name__)

MAX_DEPTH   = 10        # maksymalna głębokość iteracji
TIMEOUT     = 3.0       # s — czas oczekiwania na odpowiedź UDP
UDP_RETRIES = 2

# Root hints (uproszczone — tylko kilka z 13-tki)
ROOT_HINTS: List[Tuple[str, int]] = [
    ("198.41.0.4",   53),   # a.root-servers.net
    ("199.9.14.201", 53),   # b.root-servers.net
    ("192.112.36.4", 53),   # g.root-servers.net
]


async def _udp_query(host: str, port: int, request: DNSRecord,
                     timeout: float = TIMEOUT) -> Optional[DNSRecord]:
    """Pojedyncze zapytanie UDP z timeoutem."""
    data = request.pack()
    loop = asyncio.get_event_loop()
    for attempt in range(UDP_RETRIES):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            await loop.sock_connect(sock, (host, port))
            await asyncio.wait_for(loop.sock_sendall(sock, data), timeout)
            resp_data = await asyncio.wait_for(
                loop.sock_recv(sock, 4096), timeout
            )
            sock.close()
            reply = DNSRecord.parse(resp_data)
            if reply.header.id == request.header.id:
                return reply
        except (asyncio.TimeoutError, OSError, DNSError) as exc:
            logger.debug("UDP query %s:%d attempt %d failed: %s",
                         host, port, attempt + 1, exc)
            try:
                sock.close()
            except Exception:
                pass
    return None


class RecursiveResolver:
    """
    Resolver iteracyjny / forwarder.

    Gdy forwarders jest niepusta — działa jako forwarder (prosto do upstream).
    Gdy pusta — wykonuje pełną iterację od root-hints.
    """

    def __init__(self, forwarders: List[str] = None):
        self._fwd: List[Tuple[str, int]] = [
            (h, 53) for h in (forwarders or [])
        ]

    # ── publiczne API ────────────────────────────────────────────────────────

    async def resolve(self, qname: str, qtype: str) -> Optional[DNSRecord]:
        """
        Zwraca pełny DNSRecord (odpowiedź) albo None gdy nie udało się rozwiązać.
        """
        qt = getattr(QTYPE, qtype.upper(), QTYPE.A)
        request = DNSRecord.question(qname, qtype.upper())

        if self._fwd:
            return await self._forward(request)
        return await self._iterate(request, qt, ROOT_HINTS, 0)

    async def forward_to(self, request: DNSRecord,
                         servers: List[Tuple[str, int]]) -> Optional[DNSRecord]:
        """Przekaż zapytanie do konkretnej listy serwerów (zone forwarder)."""
        for host, port in servers:
            reply = await _udp_query(host, port, request)
            if reply is not None:
                logger.debug("Zone-forward %s → %s:%d OK (rcode=%s)",
                             str(request.q.qname), host, port,
                             reply.header.rcode)
                return reply
        logger.warning("Wszystkie serwery zone-forwarder nieosiągalne dla %s",
                       str(request.q.qname))
        return None

    # ── forwarder ────────────────────────────────────────────────────────────

    async def _forward(self, request: DNSRecord) -> Optional[DNSRecord]:
        for host, port in self._fwd:
            reply = await _udp_query(host, port, request)
            if reply is not None:
                logger.debug("Forward %s → %s:%d OK (rcode=%s)",
                             str(request.q.qname), host, port,
                             reply.header.rcode)
                return reply
        logger.warning("Wszystkie forwardery nieosiągalne dla %s",
                       str(request.q.qname))
        return None

    # ── pełna iteracja ───────────────────────────────────────────────────────

    async def _iterate(self, request: DNSRecord, qt: int,
                       servers: List[Tuple[str, int]],
                       depth: int) -> Optional[DNSRecord]:
        if depth >= MAX_DEPTH:
            logger.warning("Osiągnięto MAX_DEPTH=%d dla %s",
                           MAX_DEPTH, str(request.q.qname))
            return None

        for host, port in servers:
            reply = await _udp_query(host, port, request)
            if reply is None:
                continue

            # Odpowiedź autorytatywna z rekordami — sukces
            if reply.header.aa and reply.rr:
                return reply

            # NXDOMAIN autorytatywne
            if reply.header.aa and reply.header.rcode == 3:
                return reply

            # Referral — sekcja AUTHORITY zawiera NS dla delegacji
            ns_names = self._extract_ns(reply)
            if not ns_names:
                # Brak NS — możliwe, że to odpowiedź z CNAME lub podobna
                if reply.rr:
                    return reply
                continue

            # Spróbuj skorzystać z glue records (sekcja ADDITIONAL)
            glue = self._extract_glue(reply, ns_names)
            if glue:
                result = await self._iterate(request, qt, glue, depth + 1)
                if result is not None:
                    return result
            else:
                # Brak glue — musimy rozwiązać adresy NS osobno
                ns_servers = await self._resolve_ns_ips(ns_names, depth)
                if ns_servers:
                    result = await self._iterate(
                        request, qt, ns_servers, depth + 1
                    )
                    if result is not None:
                        return result

        return None

    # ── pomocnicze ───────────────────────────────────────────────────────────

    @staticmethod
    def _extract_ns(reply: DNSRecord) -> List[str]:
        return [
            str(rr.rdata.label)
            for rr in reply.auth
            if rr.rtype == QTYPE.NS
        ]

    @staticmethod
    def _extract_glue(reply: DNSRecord,
                      ns_names: List[str]) -> List[Tuple[str, int]]:
        ns_set = {n.lower().rstrip(".") for n in ns_names}
        result = []
        for rr in reply.ar:
            if rr.rtype == QTYPE.A:
                name = str(rr.rname).lower().rstrip(".")
                if name in ns_set:
                    result.append((str(rr.rdata), 53))
        return result

    async def _resolve_ns_ips(self, ns_names: List[str],
                              depth: int) -> List[Tuple[str, int]]:
        ips: List[Tuple[str, int]] = []
        for ns in ns_names[:3]:  # limit: max 3 NS do sprawdzenia
            req = DNSRecord.question(ns, "A")
            reply = await self._iterate(req, QTYPE.A, ROOT_HINTS, depth + 1)
            if reply:
                for rr in reply.rr:
                    if rr.rtype == QTYPE.A:
                        ips.append((str(rr.rdata), 53))
        return ips
