"""
ACL oparta na adresach IP / sieciach CIDR.

Reguły są sprawdzane od góry — wygrywa pierwsza pasująca.
Uprawnienia:
  read   – odpowiadanie na zapytania DNS
  write  – modyfikacja rekordów przez wewnętrzne API
  peer   – synchronizacja P2P między węzłami
"""
import ipaddress
import logging
from dataclasses import dataclass, field
from typing import List, Set, Optional, Union

logger = logging.getLogger(__name__)

Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
Address = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

KNOWN_PERMISSIONS = {"read", "write", "peer"}


@dataclass
class AclRule:
    name: str
    networks: List[Network]
    allow: Set[str]


class Acl:
    def __init__(self, rules: List[AclRule]):
        self._rules = rules

    # ── konstruktor z konfiguracji ────────────────────────────────────────────

    @classmethod
    def from_config(cls, cfg: list) -> "Acl":
        rules: List[AclRule] = []
        for entry in cfg:
            nets: List[Network] = []
            for cidr in entry.get("match", []):
                try:
                    nets.append(ipaddress.ip_network(cidr, strict=False))
                except ValueError:
                    logger.warning("ACL: nieprawidłowy cidr %s w regule '%s'",
                                   cidr, entry.get("name", "?"))
            perms = set(entry.get("allow", []))
            unknown = perms - KNOWN_PERMISSIONS
            if unknown:
                logger.warning("ACL: nieznane uprawnienia %s w regule '%s'",
                               unknown, entry.get("name", "?"))
            rules.append(AclRule(name=entry["name"], networks=nets,
                                  allow=perms & KNOWN_PERMISSIONS))
        return cls(rules)

    # ── wewnętrzne ────────────────────────────────────────────────────────────

    def _lookup(self, ip_str: str) -> Optional[AclRule]:
        try:
            addr: Address = ipaddress.ip_address(ip_str)
        except ValueError:
            logger.debug("ACL: nie można przetworzyć adresu '%s'", ip_str)
            return None
        for rule in self._rules:
            if any(addr in net for net in rule.networks):
                return rule
        return None

    # ── publiczne ─────────────────────────────────────────────────────────────

    def can_read(self, ip: str) -> bool:
        rule = self._lookup(ip)
        return rule is not None and "read" in rule.allow

    def can_write(self, ip: str) -> bool:
        rule = self._lookup(ip)
        return rule is not None and "write" in rule.allow

    def can_peer(self, ip: str) -> bool:
        rule = self._lookup(ip)
        return rule is not None and "peer" in rule.allow

    def rule_name(self, ip: str) -> str:
        rule = self._lookup(ip)
        return rule.name if rule else "no-match"
