"""
Punkt wejścia: python -m dns_server [-c config.yaml]

Kolejność inicjalizacji:
  1. Wczytaj konfigurację YAML
  2. Zbuduj ZoneStore (strefy lokalne)
  3. Wczytaj state_file (journal P2P z poprzedniej sesji)
  4. Zbuduj Cache, ACL, RecursiveResolver, Resolver
  5. Uruchom PeerManager (P2P)
  6. Uruchom serwer DNS (UDP + TCP)
  7. Pętla główna — sygnały SIGINT/SIGTERM → graceful shutdown
  8. Zapisz state_file
"""
import argparse
import asyncio
import logging
import os
import signal
import sys

import yaml

from .acl import Acl
from .cache import Cache
from .peer import PeerManager
from .recursive import RecursiveResolver
from .resolver import Resolver
from .server import DnsServer
from .zone import ZoneStore


# ── konfiguracja logowania ─────────────────────────────────────────────────────

def setup_logging(cfg: dict) -> None:
    level = getattr(logging, cfg.get("level", "INFO").upper(), logging.INFO)
    handlers = [logging.StreamHandler(sys.stdout)]
    logfile = cfg.get("file", "")
    if logfile:
        os.makedirs(os.path.dirname(logfile), exist_ok=True)
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


# ── główna funkcja async ───────────────────────────────────────────────────────

async def run(config_path: str) -> None:
    # 1. Wczytaj konfigurację
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    setup_logging(cfg.get("logging", {}))
    logger = logging.getLogger("dns_server")
    logger.info("Startuję serwer DNS, konfiguracja: %s", config_path)

    server_id  = cfg["server"].get("id", "node")
    state_file = cfg.get("state_file", "state.yaml")

    # 2 + 3. Strefy lokalne i persystencja
    zones = ZoneStore(server_id)
    zones.load_from_config(cfg.get("zones", []))
    zones.load_state(state_file)

    # 4. Komponenty
    cache_cfg = cfg.get("cache", {})
    cache = Cache(
        max_size=int(cache_cfg.get("max_size", 10_000)),
        min_ttl=int(cache_cfg.get("min_ttl", 30)),
    ) if cache_cfg.get("enabled", True) else Cache(max_size=0)

    acl = Acl.from_config(cfg.get("acl", []))

    recursive = RecursiveResolver(
        forwarders=[str(h) for h in cfg.get("forwarders", [])]
    )

    resolver = Resolver(zones=zones, cache=cache, acl=acl, recursive=recursive)

    # 5. P2P
    peers_cfg     = cfg.get("peers", [])
    peer_listen   = cfg.get("peer_listen", {})
    peer_host     = peer_listen.get("host", "0.0.0.0")
    peer_port     = int(peer_listen.get("port", 5353))

    peer_mgr = PeerManager(
        server_id=server_id,
        zones=zones,
        cache=cache,
        peers_cfg=peers_cfg,
        listen_host=peer_host,
        listen_port=peer_port if peers_cfg or peer_port else 0,
    )
    await peer_mgr.start()

    # 6. Serwer DNS
    srv_cfg = cfg["server"]
    dns_srv = DnsServer(
        host=srv_cfg.get("listen", "0.0.0.0"),
        port=int(srv_cfg.get("port", 53)),
        resolver=resolver,
        enable_udp=bool(srv_cfg.get("udp", True)),
        enable_tcp=bool(srv_cfg.get("tcp", True)),
    )
    await dns_srv.start()

    # 7. Graceful shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Otrzymano sygnał zatrzymania")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows nie obsługuje add_signal_handler
            pass

    logger.info("Serwer gotowy. Ctrl+C aby zatrzymać.")
    await stop_event.wait()

    # 8. Sprzątanie
    logger.info("Zatrzymuję…")
    peer_mgr.stop()
    await dns_srv.stop()
    zones.save_state(state_file)
    logger.info("Stan zapisany. Do widzenia.")


# ── entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lekki serwer DNS z P2P sync"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Ścieżka do pliku konfiguracyjnego (domyślnie: config.yaml)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.config):
        # Podpowiedź: jeśli istnieje config.example, zaproponuj skopiowanie
        example = os.path.splitext(args.config)[0] + ".example"
        hint = ""
        if os.path.exists(example):
            hint = f"\n  Skopiuj przykładową konfigurację:\n  cp {example} {args.config}"
        print(
            f"Błąd: plik konfiguracyjny '{args.config}' nie istnieje.{hint}",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
