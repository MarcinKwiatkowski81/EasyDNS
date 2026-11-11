"""
LRU cache z TTL dla odpowiedzi DNS.
Klucz: (qname_lower, qtype_str).  Wartość: lista dnslib.RR.
"""
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Optional, Tuple


class Cache:
    def __init__(self, max_size: int = 10_000, min_ttl: int = 30):
        self._store: OrderedDict[Tuple[str, str], Tuple[Any, float]] = OrderedDict()
        self._max = max_size
        self._min_ttl = min_ttl
        self._lock = Lock()
        self.hits = 0
        self.misses = 0

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _k(name: str, qtype: str) -> Tuple[str, str]:
        return (name.lower().rstrip("."), qtype.upper())

    def _evict_expired(self) -> None:  # noqa: unused — available for manual sweep
        now = time.monotonic()
        for k in list(self._store.keys()):
            if self._store[k][1] < now:
                del self._store[k]

    # ── public API ───────────────────────────────────────────────────────────

    def get(self, name: str, qtype: str) -> Optional[Any]:
        k = self._k(name, qtype)
        with self._lock:
            entry = self._store.get(k)
            if entry is None:
                self.misses += 1
                return None
            value, expires = entry
            if time.monotonic() > expires:
                del self._store[k]
                self.misses += 1
                return None
            self._store.move_to_end(k)
            self.hits += 1
            return value

    def set(self, name: str, qtype: str, value: Any, ttl: int) -> None:
        ttl = max(ttl, self._min_ttl)
        k = self._k(name, qtype)
        with self._lock:
            self._store[k] = (value, time.monotonic() + ttl)
            self._store.move_to_end(k)
            # LRU eviction
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def invalidate(self, name: str, qtype: Optional[str] = None) -> None:
        """Usuń wpisy dla danej nazwy (i opcjonalnie typu)."""
        with self._lock:
            if qtype:
                self._store.pop(self._k(name, qtype), None)
            else:
                prefix = name.lower().rstrip(".")
                for k in [k for k in self._store if k[0] == prefix]:
                    del self._store[k]

    def flush(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        return {
            "size": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
        }
