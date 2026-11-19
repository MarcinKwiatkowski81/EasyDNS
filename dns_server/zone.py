"""
Zarządzanie strefami DNS i rekordami.

Każdy rekord ma:
  - uid       – UUID, klucz do deduplikacji między węzłami P2P
  - seq       – monotonicznie rosnący numer sekwencji (lokalny)
  - ts        – znacznik czasu (float, epoch) — do rozwiązywania konfliktów (LWW)
  - deleted   – flaga nagrobkowa (tombstone), umożliwia propagowanie usunięć P2P
  - origin    – identyfikator węzła, który jako pierwszy wytworzył rekord

Synchronizacja P2P:
  Każdy węzeł udostępnia journal(since_seq) — listę zmian od danego numeru
  sekwencji. Peer żąda zmian, scala je (last-write-wins wg ts, origin jako
  tiebreaker) i aktualizuje swój lokalny stan.
"""
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ResourceRecord:
    name: str           # etykieta względem strefy; '' oznacza apex (zamiast '@')
    rtype: str          # 'A', 'AAAA', 'MX', …  — zawsze uppercase
    ttl: int
    rdata: dict         # dane specyficzne dla typu (patrz _rdata_from_cfg)

    # metadane synchronizacji P2P
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    seq: int = 0
    ts: float = field(default_factory=time.time)
    deleted: bool = False
    origin: str = ""    # server_id węzła źródłowego

    def to_dict(self) -> dict:
        return {
            "uid": self.uid, "name": self.name, "rtype": self.rtype,
            "ttl": self.ttl, "rdata": self.rdata, "seq": self.seq,
            "ts": self.ts, "deleted": self.deleted, "origin": self.origin,
        }

    @staticmethod
    def from_dict(d: dict) -> "ResourceRecord":
        return ResourceRecord(
            name=d["name"], rtype=d["rtype"], ttl=d["ttl"], rdata=d["rdata"],
            uid=d["uid"], seq=d["seq"], ts=d["ts"],
            deleted=d.get("deleted", False), origin=d.get("origin", ""),
        )


# ── Strefa ────────────────────────────────────────────────────────────────────

class Zone:
    """Pojedyncza strefa DNS."""

    def __init__(self, name: str, server_id: str):
        # Nazwa strefy zawsze zakończona kropką
        self.origin: str = name.lower().rstrip(".") + "."
        self._sid = server_id
        self._records: Dict[str, ResourceRecord] = {}   # uid → RR
        self._config_uids: set[str] = set()
        self._seq: int = 0
        self._lock = threading.RLock()
        # Callback wywoływany po każdej zmianie: fn(zone, record)
        self.on_change: Optional[Callable[["Zone", ResourceRecord], None]] = None

    # ── sekwencja ────────────────────────────────────────────────────────────

    def _bump(self) -> int:
        self._seq += 1
        return self._seq

    @property
    def max_seq(self) -> int:
        with self._lock:
            if not self._records:
                return self._seq
            return max(r.seq for r in self._records.values())

    # ── normalisation ────────────────────────────────────────────────────────

    def _to_relative(self, name: str) -> Optional[str]:
        """Zwraca etykietę względną (lub ''), albo None gdy poza strefą."""
        name = name.lower().rstrip(".") + "."
        if name == self.origin:
            return ""
        suffix = "." + self.origin
        if name.endswith(suffix):
            return name[: -len(suffix)]
        return None

    def _to_fqdn(self, rel: str) -> str:
        return self.origin if rel == "" else f"{rel}.{self.origin}"

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def _apply(self, rr: ResourceRecord) -> bool:
        """
        Scal rekord z lokalnym stanem (last-write-wins).
        Zwraca True jeśli rekord faktycznie zmienił stan.
        """
        existing = self._records.get(rr.uid)
        if existing is not None:
            # Conflict resolution: wyższy timestamp wygrywa;
            # przy równym — leksykograficznie większy origin.
            if rr.ts < existing.ts:
                return False
            if rr.ts == existing.ts and rr.origin <= existing.origin:
                return False
        if rr.seq == 0:
            rr.seq = self._bump()
        else:
            self._seq = max(self._seq, rr.seq)
        self._records[rr.uid] = rr
        return True

    def add(self, name: str, rtype: str, ttl: int, rdata: dict,
            uid: str = None, seq: int = 0, ts: float = 0.0,
            origin: str = "") -> ResourceRecord:
        rel = self._to_relative(name)
        if rel is None:
            # Przyjmujemy jako etykietę względną podaną bezpośrednio
            rel = name.lower()
        rr = ResourceRecord(
            name=rel, rtype=rtype.upper(), ttl=ttl, rdata=dict(rdata),
            uid=uid or str(uuid.uuid4()),
            seq=seq, ts=ts or time.time(),
            origin=origin or self._sid,
        )
        with self._lock:
            changed = self._apply(rr)
        if changed and self.on_change:
            self.on_change(self, rr)
        return rr

    def delete_uid(self, uid: str, ts: float = 0.0) -> bool:
        with self._lock:
            rr = self._records.get(uid)
            if rr is None:
                return False
            rr.deleted = True
            rr.ts = ts or time.time()
            rr.seq = self._bump()
        if self.on_change:
            self.on_change(self, rr)
        return True

    def add_record(self, name: str, rtype: str, ttl: int, rdata: dict,
                   uid: str = None) -> ResourceRecord:
        """API helper: dodaj lub zaktualizuj rekord (UID generowany dla nowych)."""
        return self.add(name, rtype, ttl, rdata, uid=uid, origin=self._sid)

    def find_record(self, name: str, rtype: str, ttl: int,
                    rdata: dict) -> Optional[ResourceRecord]:
        """Znajdź aktywny rekord o identycznej treści."""
        rel = self._to_relative(name)
        if rel is None:
            rel = name.lower().rstrip(".")
        with self._lock:
            return next(
                (
                    rr for rr in self._records.values()
                    if not rr.deleted
                    and rr.name == rel
                    and rr.rtype == rtype.upper()
                    and rr.ttl == ttl
                    and rr.rdata == rdata
                ),
                None,
            )

    def delete_record(self, uid: str) -> bool:
        """API helper: oznacz rekord jako usunięty."""
        return self.delete_uid(uid)

    def apply_remote(self, rr: ResourceRecord) -> bool:
        """Scal rekord nadchodzący od peera."""
        with self._lock:
            changed = self._apply(rr)
        return changed

    # ── zapytania ────────────────────────────────────────────────────────────

    def query(self, qname: str, qtype: str) -> List[ResourceRecord]:
        rel = self._to_relative(qname)
        if rel is None:
            return []
        qtype = qtype.upper()
        with self._lock:
            return [
                r for r in self._records.values()
                if not r.deleted
                and r.name == rel
                and (qtype in ("ANY", "*") or r.rtype == qtype)
            ]

    def has_name(self, qname: str) -> bool:
        """Czy strefa zna tę nazwę (istnieje choć jeden nieusunięty rekord)?"""
        rel = self._to_relative(qname)
        if rel is None:
            return False
        with self._lock:
            return any(
                not r.deleted and r.name == rel
                for r in self._records.values()
            )

    def find_soa(self) -> Optional[ResourceRecord]:
        with self._lock:
            for r in self._records.values():
                if not r.deleted and r.rtype == "SOA" and r.name == "":
                    return r
        return None

    def all_active(self) -> List[ResourceRecord]:
        with self._lock:
            return [r for r in self._records.values() if not r.deleted]

    # ── journal P2P ──────────────────────────────────────────────────────────

    def journal(self, since_seq: int = 0) -> List[ResourceRecord]:
        """Wszystkie rekordy (w tym nagrobki) z seq > since_seq."""
        with self._lock:
            return [r for r in self._records.values() if r.seq > since_seq]

    # ── serializacja ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "zone": self.origin,
                "records": [r.to_dict() for r in self._records.values()],
            }

    def load_dict(self, data: dict) -> None:
        for d in data.get("records", []):
            rr = ResourceRecord.from_dict(d)
            with self._lock:
                config_match = rr.uid if rr.uid in self._config_uids else None
                if config_match is None:
                    config_match = next(
                        (
                            existing_uid
                            for existing_uid in self._config_uids
                            if self._same_record(self._records[existing_uid], rr)
                        ),
                        None,
                    )
                if config_match is None:
                    same_owner_type = [
                        existing_uid
                        for existing_uid in self._config_uids
                        if self._records[existing_uid].name == rr.name
                        and self._records[existing_uid].rtype == rr.rtype
                    ]
                    if len(same_owner_type) == 1:
                        config_match = same_owner_type[0]
                if config_match is not None:
                    del self._records[config_match]
                    self._config_uids.discard(config_match)
                else:
                    duplicate_uid = next(
                        (
                            existing_uid
                            for existing_uid, existing in self._records.items()
                            if existing_uid != rr.uid
                            and self._same_record(existing, rr)
                        ),
                        None,
                    )
                    if duplicate_uid is not None:
                        del self._records[duplicate_uid]
                self._records[rr.uid] = rr
                self._seq = max(self._seq, rr.seq)

    @staticmethod
    def _same_record(left: ResourceRecord, right: ResourceRecord) -> bool:
        return (
            left.name == right.name
            and left.rtype == right.rtype
            and left.ttl == right.ttl
            and left.rdata == right.rdata
        )


# ── Rejestr stref ─────────────────────────────────────────────────────────────

def _rdata_from_cfg(rtype: str, cfg: dict) -> dict:
    """Konwersja wpisu YAML na słownik rdata."""
    t = rtype.upper()
    if t in ("A", "AAAA", "NS", "CNAME", "PTR"):
        return {"value": cfg["value"]}
    if t == "MX":
        return {"priority": int(cfg.get("priority", 10)), "value": cfg["value"]}
    if t == "TXT":
        return {"value": cfg["value"]}
    if t == "SOA":
        return {
            "mname":   cfg["mname"],
            "rname":   cfg["rname"],
            "serial":  int(cfg.get("serial",  2024010101)),
            "refresh": int(cfg.get("refresh", 3600)),
            "retry":   int(cfg.get("retry",   900)),
            "expire":  int(cfg.get("expire",  604800)),
            "minimum": int(cfg.get("minimum", 300)),
        }
    if t == "SRV":
        return {
            "priority": int(cfg.get("priority", 0)),
            "weight":   int(cfg.get("weight",   0)),
            "port":     int(cfg["port"]),
            "value":    cfg["value"],
        }
    if t == "CAA":
        return {
            "flags": int(cfg.get("flags", 0)),
            "tag":   cfg["tag"],
            "value": cfg["value"],
        }
    logger.warning("Nieznany typ rekordu w konfiguracji: %s", rtype)
    return dict(cfg)


class ZoneStore:
    """Rejestr wszystkich lokalnych stref."""

    def __init__(self, server_id: str):
        self._sid = server_id
        self._zones: Dict[str, Zone] = {}   # origin → Zone
        self._deleted_zones: set[str] = set()
        self._replaced_zones: set[str] = set()
        self._lock = threading.RLock()

    def add_zone(self, name: str) -> Zone:
        z = Zone(name, self._sid)
        with self._lock:
            if z.origin in self._zones:
                raise ValueError(f"Zone {z.origin} already exists")
            if z.origin in self._deleted_zones:
                self._replaced_zones.add(z.origin)
            self._deleted_zones.discard(z.origin)
            self._zones[z.origin] = z
        return z

    def rename_zone(self, old_name: str, new_name: str) -> Zone:
        old_origin = old_name.lower().rstrip(".") + "."
        new_origin = new_name.lower().rstrip(".") + "."
        with self._lock:
            zone = self._zones.get(old_origin)
            if zone is None:
                raise KeyError(old_origin)
            if new_origin != old_origin and new_origin in self._zones:
                raise ValueError(f"Zone {new_origin} already exists")
            if new_origin == old_origin:
                return zone
            del self._zones[old_origin]
            with zone._lock:
                zone.origin = new_origin
            self._zones[new_origin] = zone
            self._deleted_zones.add(old_origin)
            if new_origin in self._deleted_zones:
                self._replaced_zones.add(new_origin)
            self._deleted_zones.discard(new_origin)
            return zone

    def delete_zone(self, name: str) -> Zone:
        origin = name.lower().rstrip(".") + "."
        with self._lock:
            zone = self._zones.pop(origin, None)
            if zone is None:
                raise KeyError(origin)
            self._deleted_zones.add(origin)
            self._replaced_zones.discard(origin)
            return zone

    @property
    def zones(self) -> Dict[str, Zone]:
        """Publiczny dostęp do rejestru stref (dla API)."""
        with self._lock:
            return dict(self._zones)

    def get_zone(self, qname: str) -> Optional[Zone]:
        """Najdokładniejsza strefa pasująca do qname."""
        name = qname.lower().rstrip(".") + "."
        with self._lock:
            best: Optional[Zone] = None
            for origin, zone in self._zones.items():
                if name == origin or name.endswith("." + origin):
                    if best is None or len(origin) > len(best.origin):
                        best = zone
            return best

    def all_zones(self) -> List[Zone]:
        with self._lock:
            return list(self._zones.values())

    # ── ładowanie z konfiguracji ─────────────────────────────────────────────

    def load_from_config(self, zones_cfg: list) -> None:
        for zcfg in zones_cfg:
            zone = self.add_zone(zcfg["name"])
            for record_index, rec in enumerate(zcfg.get("records", [])):
                rtype = rec["type"].upper()
                rdata = _rdata_from_cfg(rtype, rec)
                name = rec.get("name", "@").replace("@", zone.origin)
                ttl = int(rec.get("ttl", 300))
                if zone.find_record(name, rtype, ttl, rdata) is None:
                    uid = str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"easydns:{self._sid}:{zone.origin}:config:{record_index}",
                    ))
                    zone.add(
                        name=name,
                        rtype=rtype,
                        ttl=ttl,
                        rdata=rdata,
                        uid=uid,
                        origin=self._sid,
                    )
                    zone._config_uids.add(uid)
            logger.info("Załadowano strefę %s (%d rekordów)",
                        zone.origin, len(zone.all_active()))

    # ── persystencja (state_file) ─────────────────────────────────────────────

    def load_state(self, path: str) -> None:
        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ValueError("state file must contain a YAML object")
            deleted_names = data.get("deleted_zones", [])
            replaced_names = data.get("replaced_zones", [])
            if not isinstance(deleted_names, list) or not all(
                isinstance(name, str) for name in deleted_names
            ):
                raise ValueError("deleted_zones must be a list of strings")
            if not isinstance(replaced_names, list) or not all(
                isinstance(name, str) for name in replaced_names
            ):
                raise ValueError("replaced_zones must be a list of strings")
            deleted_zones = {
                name.lower().rstrip(".") + "." for name in deleted_names
            }
            replaced_zones = {
                name.lower().rstrip(".") + "." for name in replaced_names
            }
            with self._lock:
                self._deleted_zones.update(deleted_zones)
                self._replaced_zones.update(replaced_zones)
                for name in deleted_zones | replaced_zones:
                    self._zones.pop(name, None)
            for zdata in data.get("zones", []):
                name = zdata["zone"]
                origin = name.lower().rstrip(".") + "."
                if origin in deleted_zones:
                    continue
                zone = self._zones.get(origin)
                if zone is None:
                    zone = self.add_zone(name)
                zone.load_dict(zdata)
            logger.info("Wczytano stan z %s", path)
        except FileNotFoundError:
            logger.info("Brak pliku stanu %s — zaczynam od zera", path)
        except Exception as exc:
            raise RuntimeError(f"Błąd wczytywania stanu z {path}: {exc}") from exc

    def save_state(self, path: str) -> None:
        import yaml

        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = path + ".tmp"
        data = {
            "zones": [z.to_dict() for z in self.all_zones()],
            "deleted_zones": sorted(self._deleted_zones),
            "replaced_zones": sorted(self._replaced_zones),
        }
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
