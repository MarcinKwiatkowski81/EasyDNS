"""
Główny resolver: łączy strefy lokalne, cache i resolver rekurencyjny.

Kolejność rozwiązywania:
  1. ACL — czy klient ma uprawnienie 'read'?
  2. Cache — czy mamy świeżą odpowiedź?
  3. Strefy lokalne — czy jesteśmy autorytatywni?
     a. Wykryj delegację (zone cut) → referral lub zone forwarder
     b. Znana nazwa, znany typ  → ANSWER
     c. Znana nazwa, brak typu  → NOERROR + SOA w AUTHORITY
     d. Nieznana nazwa w strefie → NXDOMAIN + SOA w AUTHORITY
     e. CNAME → rozwiń łańcuch (możliwe wyjście poza strefę)
  4. Conditional zone forwarder — zapytania o delegowane subdomeny
  5. Resolver rekurencyjny / forwarder
  6. Zapisz wynik w cache

Delegacja (zone cut):
  Jeśli strefa lokalna zawiera rekordy NS dla podstrefy, a zapytanie trafia
  do tej podstrefy, resolver zwraca referral (NOERROR, NS w AUTHORITY,
  glue A/AAAA w ADDITIONAL) lub — jeśli skonfigurowany forward_zones —
  odpytuje konkretny serwer i zwraca pełną odpowiedź.

Conditional forwarding (forward_zones):
  Pozwala skierować zapytania o konkretną strefę do wskazanych serwerów
  zamiast do ogólnych forwarderów. Niezbędne w architekturze hierarchicznej,
  gdzie każda lokalizacja jest autorytatywna dla swojej subdomeny.

Budowanie odpowiedzi DNS opiera się na dnslib.
"""
import asyncio
import logging
from typing import List, Optional, Tuple

try:
    from dnslib import (
        DNSRecord, DNSHeader, RR, QTYPE, RCODE,
        A, AAAA, CNAME, MX, NS, PTR, TXT, SOA, SRV,
        DNSLabel,
    )
    from dnslib.dns import CAA as dnsCAA
except ImportError:
    raise ImportError("Zainstaluj: pip install dnslib")

from .zone import Zone, ZoneStore, ResourceRecord
from .cache import Cache
from .acl import Acl
from .recursive import RecursiveResolver

logger = logging.getLogger(__name__)

MAX_CNAME_DEPTH = 8


def _build_rdata(rr: ResourceRecord):
    """Konwertuje ResourceRecord.rdata na obiekt dnslib."""
    t = rr.rtype
    d = rr.rdata
    if t == "A":
        return A(d["value"])
    if t == "AAAA":
        return AAAA(d["value"])
    if t == "CNAME":
        return CNAME(d["value"])
    if t == "NS":
        return NS(d["value"])
    if t == "PTR":
        return PTR(d["value"])
    if t == "MX":
        return MX(DNSLabel(d["value"]), d.get("priority", 10))
    if t == "TXT":
        val = d["value"]
        return TXT(val.encode() if isinstance(val, str) else val)
    if t == "SOA":
        return SOA(
            mname=d["mname"], rname=d["rname"],
            times=(
                d.get("serial",  2024010101),
                d.get("refresh", 3600),
                d.get("retry",   900),
                d.get("expire",  604800),
                d.get("minimum", 300),
            ),
        )
    if t == "SRV":
        return SRV(
            priority=d.get("priority", 0),
            weight=d.get("weight", 0),
            port=d["port"],
            target=d["value"],
        )
    if t == "CAA":
        return dnsCAA(
            flags=d.get("flags", 0),
            tag=d.get("tag", "issue"),
            value=d.get("value", ""),
        )
    raise ValueError(f"Nieobsługiwany typ rekordu: {t}")


def _rr_to_dnslib(rr: ResourceRecord, zone_name: str) -> Optional[RR]:
    """Buduje dnslib.RR z ResourceRecord."""
    try:
        name = rr.name
        if name == "":
            fqdn = zone_name
        else:
            fqdn = f"{name}.{zone_name}"
        return RR(
            rname=DNSLabel(fqdn),
            rtype=getattr(QTYPE, rr.rtype),
            ttl=rr.ttl,
            rdata=_build_rdata(rr),
        )
    except Exception as exc:
        logger.warning("Nie można zbudować RR dla %s/%s: %s",
                       rr.name, rr.rtype, exc)
        return None


class Resolver:
    def __init__(self,
                 zones: ZoneStore,
                 cache: Cache,
                 acl: Acl,
                 recursive: RecursiveResolver,
                 forward_zones: Optional[dict] = None):
        self.zones = zones
        self.cache = cache
        self.acl = acl
        self.recursive = recursive
        # forward_zones: {"bb.mkw.": ["192.168.32.16"], ...}
        # Klucze zawsze normalizowane (lowercase, kropka na końcu).
        self._fwd_zones: dict = {}
        for zone_name, servers in (forward_zones or {}).items():
            norm = zone_name.lower().rstrip(".") + "."
            self._fwd_zones[norm] = [
                (s.split(":")[0], int(s.split(":")[1]) if ":" in s else 53)
                for s in (servers or [])
            ]

    # ── publiczne API ────────────────────────────────────────────────────────

    async def handle(self, data: bytes, client_ip: str) -> bytes:
        """
        Przetwarza surowe bajty zapytania DNS.
        Zwraca bajty odpowiedzi gotowe do wysłania.
        """
        try:
            request = DNSRecord.parse(data)
        except Exception as exc:
            logger.warning("Błąd parsowania zapytania DNS od %s: %s",
                           client_ip, exc)
            return b""

        reply = await self._resolve(request, client_ip)
        return reply.pack()

    # ── wewnętrzne ────────────────────────────────────────────────────────────

    async def _resolve(self, request: DNSRecord, client_ip: str) -> DNSRecord:
        reply = request.reply()

        # 1. ACL
        if not self.acl.can_read(client_ip):
            logger.info("ACL DENY read %s od %s", str(request.q.qname), client_ip)
            reply.header.rcode = RCODE.REFUSED
            return reply

        qname = str(request.q.qname)
        qtype = QTYPE[request.q.qtype]  # np. 'A', 'MX', …

        logger.debug("QUERY %s %s od %s", qname, qtype, client_ip)

        # 2. Cache
        cached = self.cache.get(qname, qtype)
        if cached is not None:
            logger.debug("CACHE HIT %s %s", qname, qtype)
            reply.rr = cached
            return reply

        # 3. Strefy lokalne
        zone = self.zones.get_zone(qname)
        if zone is not None:
            # 3a. Wykryj zone cut (delegację do podstrefy)
            delegation = self._find_delegation(zone, qname)
            if delegation is not None:
                ns_recs, glue_recs = delegation
                # Jeśli mamy zone forwarder — użyj go (pełna odpowiedź)
                fwd = self._zone_forwarder(qname)
                if fwd:
                    upstream = await self.recursive.forward_to(request, fwd)
                    if upstream is not None:
                        self._copy_upstream(reply, upstream)
                        self._cache_if_ok(qname, qtype, upstream)
                        return reply
                # Brak zone forwardera → standardowy referral DNS
                reply.header.aa = 0
                self._add_records(reply.auth, ns_recs, zone)
                self._add_records(reply.ar,   glue_recs, zone)
                logger.debug("REFERRAL %s → %s",
                             qname, [r.rdata.get("value") for r in ns_recs])
                return reply

            # 3b. Odpowiedź autorytatywna ze strefy lokalnej
            answered = self._answer_from_zone(reply, zone, qname, qtype)
            if answered and reply.rr:
                min_ttl = min((r.ttl for r in reply.rr), default=60)
                self.cache.set(qname, qtype, list(reply.rr), min_ttl)
            return reply

        # 4. Conditional zone forwarder (nazwa spoza stref lokalnych)
        fwd = self._zone_forwarder(qname)
        if fwd:
            upstream = await self.recursive.forward_to(request, fwd)
            if upstream is not None:
                self._copy_upstream(reply, upstream)
                self._cache_if_ok(qname, qtype, upstream)
                return reply

        # 5. Ogólny resolver rekurencyjny / forwarder
        try:
            upstream = await self.recursive.resolve(qname, qtype)
            if upstream is not None:
                self._copy_upstream(reply, upstream)
                self._cache_if_ok(qname, qtype, upstream)
                return reply
        except Exception as exc:
            logger.error("Recursive resolver error dla %s: %s", qname, exc)

        reply.header.rcode = RCODE.SERVFAIL
        return reply

    def _answer_from_zone(self, reply: DNSRecord, zone: Zone,
                          qname: str, qtype: str) -> bool:
        """
        Wypełnia reply na podstawie lokalnej strefy.
        Zwraca True (przetworzono autorytatywnie — nawet jeśli NXDOMAIN).
        """
        reply.header.aa = 1   # autorytatywna odpowiedź

        # Sprawdź CNAME (poza SOA/ANY)
        if qtype not in ("CNAME", "ANY", "*"):
            cnames = zone.query(qname, "CNAME")
            if cnames:
                self._add_records(reply.rr, cnames, zone)
                # Podążaj łańcuchem CNAME (w strefie)
                target = cnames[0].rdata.get("value", "")
                for _ in range(MAX_CNAME_DEPTH):
                    recs = zone.query(target, qtype)
                    if recs:
                        self._add_records(reply.rr, recs, zone)
                        return True
                    cnames2 = zone.query(target, "CNAME")
                    if not cnames2:
                        break
                    self._add_records(reply.rr, cnames2, zone)
                    target = cnames2[0].rdata.get("value", "")
                # CNAME prowadzi poza strefę — zwróć sam CNAME, klient powtórzy
                return True

        # Odpowiedź na zapytanie
        recs = zone.query(qname, qtype)
        if recs:
            self._add_records(reply.rr, recs, zone)
            return True

        # Nazwa istnieje, ale brak rekordów żądanego typu (NOERROR, brak RR)
        if zone.has_name(qname):
            self._add_soa_to_authority(reply, zone)
            return True

        # NXDOMAIN
        reply.header.rcode = RCODE.NXDOMAIN
        self._add_soa_to_authority(reply, zone)
        return True

    # ── delegacja i conditional forwarding ──────────────────────────────────────

    def _find_delegation(self, zone: Zone,
                         qname: str) -> Optional[Tuple[List, List]]:
        """
        Wykryj zone cut: czy qname leży pod delegowaną podstrefą?

        Algorytm:
          Dla qname = "dsk0.bb.mkw." w strefie "mkw.":
            rel = "dsk0.bb"
            Sprawdź od strony apeksu: "bb" → czy są rekordy NS?
            Jeśli tak → delegacja do bb.mkw., zwróć (ns_recs, glue).

        Nie wykrywa delegacji dla samego apeksu podstrefy
        (qname=="bb.mkw." → odpowiada strefa nadrzędna, nie referral).
        """
        rel = zone._to_relative(qname)
        if rel is None or rel == "":
            return None  # apex strefy — brak delegacji

        parts = rel.split(".")
        # Iteruj od strony apeksu strefy (najpłytszy zone cut pierwszy):
        # dla parts=['dsk0','bb']: sprawdza 'bb', potem 'dsk0.bb' (pomijamy pełną nazwę)
        for depth in range(len(parts) - 1, 0, -1):
            candidate_rel  = ".".join(parts[depth:])
            candidate_fqdn = zone._to_fqdn(candidate_rel)
            ns_recs = zone.query(candidate_fqdn, "NS")
            if not ns_recs:
                continue
            # Zbierz glue records (A/AAAA dla serwerów NS w naszej strefie)
            glue: List[ResourceRecord] = []
            for ns_rr in ns_recs:
                ns_target = ns_rr.rdata.get("value", "")
                glue.extend(zone.query(ns_target, "A"))
                glue.extend(zone.query(ns_target, "AAAA"))
            return ns_recs, glue
        return None

    def _zone_forwarder(self, qname: str) -> Optional[List[Tuple[str, int]]]:
        """
        Znajdź najbardziej szczegółowy zone forwarder dla qname.
        Np. dla qname="dsk0.bb.mkw." zwraca serwery z "bb.mkw." (jeśli skonfigurowane).
        """
        name = qname.lower().rstrip(".") + "."
        best_len, best = 0, None
        for zone_key, servers in self._fwd_zones.items():
            if name == zone_key or name.endswith("." + zone_key):
                if len(zone_key) > best_len:
                    best_len = len(zone_key)
                    best = servers
        return best

    # ── pomocnicze ────────────────────────────────────────────────────────────

    @staticmethod
    def _copy_upstream(reply: DNSRecord, upstream: DNSRecord) -> None:
        reply.rr   = upstream.rr
        reply.auth = upstream.auth
        reply.ar   = upstream.ar
        reply.header.rcode = upstream.header.rcode

    def _cache_if_ok(self, qname: str, qtype: str,
                     upstream: DNSRecord) -> None:
        if upstream.rr:
            min_ttl = min((r.ttl for r in upstream.rr), default=60)
            self.cache.set(qname, qtype, list(upstream.rr), min_ttl)

    @staticmethod
    def _add_records(target: list, recs: List[ResourceRecord],
                     zone: Zone) -> None:
        for rr in recs:
            dlib_rr = _rr_to_dnslib(rr, zone.origin)
            if dlib_rr:
                target.append(dlib_rr)

    @staticmethod
    def _add_soa_to_authority(reply: DNSRecord, zone: Zone) -> None:
        soa = zone.find_soa()
        if soa:
            dlib_rr = _rr_to_dnslib(soa, zone.origin)
            if dlib_rr:
                reply.auth.append(dlib_rr)
