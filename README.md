# Serwer DNS z synchronizacją P2P

Lekki serwer DNS przeznaczony do sieci wewnętrznych. Obsługuje pełny zestaw
typów rekordów, iteracyjne rozwiązywanie hierarchiczne, synchronizację P2P
między węzłami (bez relacji master–slave) oraz konfigurowalne ACL.

---

## Wymagania

```
Python >= 3.11
pip install -r requirements.txt
```

Zależności (`requirements.txt`):
- **dnslib** ≥ 0.9.19 — kodowanie/dekodowanie pakietów DNS
- **PyYAML** ≥ 6.0 — konfiguracja i persystencja
- **cryptography** ≥ 41.0 — HMAC-SHA256 dla protokołu P2P

---

## Uruchomienie

```bash
# Z domyślnym config.yaml w bieżącym katalogu
sudo python -m dns_server

# Z innym plikiem konfiguracyjnym
sudo python -m dns_server -c /etc/mydns/config.yaml
```

Port 53 wymaga uprawnień root (lub `CAP_NET_BIND_SERVICE`).  
Bez roota: ustaw `port: 5300` i przekieruj ruch przez iptables:

```bash
sudo iptables -t nat -A PREROUTING -p udp --dport 53 -j REDIRECT --to-port 5300
sudo iptables -t nat -A PREROUTING -p tcp --dport 53 -j REDIRECT --to-port 5300
```

---

## Architektura

```
Klient DNS
    │  UDP/TCP :53
    ▼
┌─────────────────────────────────────────────────┐
│  server.py  (DnsServer)                         │
│  DnsUdpProtocol / DnsTcpHandler                 │
└────────────────────┬────────────────────────────┘
                     │ bytes
                     ▼
┌─────────────────────────────────────────────────┐
│  resolver.py  (Resolver)                        │
│                                                 │
│  1. ACL (acl.py)         → REFUSED jeśli brak  │
│  2. Cache (cache.py)     → odpowiedź z cache    │
│  3. ZoneStore (zone.py)  → autorytatywna strefa │
│  4. RecursiveResolver    → upstream / root      │
│     (recursive.py)                              │
└──────────┬──────────────────────┬───────────────┘
           │                      │
           ▼                      ▼
     zone.py                recursive.py
     ZoneStore               forwarders / root-hints
     Zone                    iteracyjne odpytywanie NS
     ResourceRecord
           │
           ▼
     peer.py
     PeerManager
     PeerConnection   ◄──TCP P2P──►  inne węzły DNS
     PeerServer
```

### Przepływ zapytania

1. Pakiet UDP/TCP trafia do `DnsServer`.
2. `Resolver.handle()` sprawdza **ACL** — brak uprawnienia `read` → `REFUSED`.
3. Sprawdza **cache** — trafienie → natychmiastowa odpowiedź.
4. Szuka **lokalnej strefy** w `ZoneStore`:
   - Znalazł rekordy → odpowiedź autorytatywna (AA=1).
   - Znał nazwę, ale nie ten typ → `NOERROR` + SOA w AUTHORITY.
   - Nieznana nazwa w strefie → `NXDOMAIN` + SOA.
   - `CNAME` → rozwijany łańcuch (w strefie, do 8 kroków).
5. Brak lokalnej strefy → **resolver rekurencyjny/forwarder**.
6. Wynik trafia do **cache**.

---

## Konfiguracja

Plik `config.yaml` (schemat opisany w komentarzach):

### `server`
| Klucz   | Opis                              | Domyślnie    |
|---------|-----------------------------------|--------------|
| `id`    | Unikalny identyfikator węzła      | `"node"`     |
| `listen`| Adres nasłuchu DNS                | `"0.0.0.0"`  |
| `port`  | Port DNS                          | `53`         |
| `udp`   | Włącz UDP                         | `true`       |
| `tcp`   | Włącz TCP                         | `true`       |

### `peer_listen`
Adres i port nasłuchu dla protokołu P2P między węzłami.

### `peers`
Lista węzłów partnerskich:
```yaml
peers:
  - host: "192.168.1.2"
    port: 5353
    key: "losowy-klucz-hmac-sha256"
```
Klucz HMAC musi być **identyczny** na obu węzłach danej pary.

### `forwarders`
Serwery DNS używane gdy zapytanie nie trafia do żadnej lokalnej strefy.  
Pusta lista = pełna rekursja od root-hints (wymaga dostępu do internetu).

### `acl`
```yaml
acl:
  - name: "localhost"
    match: ["127.0.0.0/8", "::1/128"]
    allow: ["read", "write", "peer"]
  - name: "default"
    match: ["0.0.0.0/0"]
    allow: []
```
Uprawnienia:
- `read` — odpowiadanie na zapytania DNS
- `write` — modyfikacja rekordów (przyszłe API HTTP)
- `peer` — synchronizacja P2P (sprawdzana po stronie serwera P2P)

### `zones` — typy rekordów

```yaml
# A
- {name: "host",   type: A,     ttl: 3600, value: "192.168.1.5"}

# AAAA
- {name: "host",   type: AAAA,  ttl: 3600, value: "fd00::5"}

# CNAME
- {name: "www",    type: CNAME, ttl: 3600, value: "host.internal.lan"}

# MX
- {name: "@",      type: MX,    ttl: 3600, priority: 10, value: "mail.internal.lan"}

# NS
- {name: "@",      type: NS,    ttl: 3600, value: "ns1.internal.lan"}

# PTR (strefa rewers)
- {name: "5",      type: PTR,   ttl: 3600, value: "host.internal.lan"}

# TXT
- {name: "@",      type: TXT,   ttl: 3600, value: "v=spf1 mx -all"}

# SOA
- {name: "@", type: SOA, ttl: 3600,
   mname: "ns1.internal.lan", rname: "admin.internal.lan",
   serial: 2024010101, refresh: 3600, retry: 900, expire: 604800, minimum: 300}

# SRV
- {name: "_ldap._tcp", type: SRV, ttl: 3600,
   priority: 0, weight: 100, port: 389, value: "gateway.internal.lan"}

# CAA
- {name: "@", type: CAA, ttl: 3600, flags: 0, tag: "issue", value: "letsencrypt.org"}
```

---

## Synchronizacja P2P

Każdy węzeł równocześnie:
- **nasłuchuje** połączeń przychodzących (serwer P2P),
- **inicjuje** połączenia do skonfigurowanych peerów (klient P2P).

### Protokół (JSON over TCP, big-endian 4-bajtowy prefiks długości)

```
HELLO    → wymiana listy stref
SYNC_REQ → poproś o journal od sekwencji N
SYNC_RESP→ odpowiedź z listą rekordów
UPDATE   → propagacja pojedynczej zmiany
PING/PONG→ heartbeat co 30 s
```

Każda wiadomość zawiera pole `sig`: **HMAC-SHA256** treści z kluczem wspólnym.  
Wiadomości z nieprawidłowym podpisem są ignorowane.

### Rozwiązywanie konfliktów

**Last-write-wins** na podstawie pola `ts` (Unix timestamp float).  
Przy identycznym `ts` wygrywa leksykograficznie większy `origin` (ID węzła).  
Usunięcia propagowane są jako **nagrobki** (`deleted: true`) — rekord zostaje
w journalu, żeby węzły, które były offline, mogły odebrać informację o usunięciu.

### Persystencja

Stan (journal) zapisywany jest do `state_file` przy zatrzymaniu serwera
i wczytywany przy starcie. Zapewnia to ciągłość numerów sekwencji po restarcie.

---

## Bezpieczeństwo

| Aspekt | Implementacja |
|--------|---------------|
| Autentykacja P2P | HMAC-SHA256 per-peer |
| ACL DNS | CIDR-based, per-uprawnienie |
| Brak AXFR | Brak publicznej transferu stref (tylko własny protokół P2P) |
| Limit rozmiaru ramki P2P | 16 MB max |
| Limit głębokości rekursji | `MAX_DEPTH = 10` |
| Limit łańcucha CNAME | 8 kroków |
| Timeout UDP | 3 s, 2 próby |
| Timeout TCP sesji | 30 s |

**Zalecenia produkcyjne:**
- Dodaj TLS do P2P (opcja `ssl=` w `asyncio.open_connection`).
- Uruchamiaj jako dedykowany użytkownik systemowy, nie root.
- Użyj `CAP_NET_BIND_SERVICE` zamiast uruchamiania jako root.
- Generuj klucze HMAC: `python3 -c "import secrets; print(secrets.token_hex(32))"`.

---

## Testowanie

```bash
# Zapytanie A do lokalnego serwera (port 5300 dla testów bez roota)
dig @127.0.0.1 -p 5300 gateway.internal.lan A

# Zapytanie PTR
dig @127.0.0.1 -p 5300 -x 192.168.1.1

# Zapytanie MX
dig @127.0.0.1 -p 5300 internal.lan MX

# Zapytanie SRV
dig @127.0.0.1 -p 5300 _ldap._tcp.internal.lan SRV

# Sprawdzenie NXDOMAIN
dig @127.0.0.1 -p 5300 nieistniejacy.internal.lan A

# Rekursja zewnętrzna (przez forwarder)
dig @127.0.0.1 -p 5300 google.com A
```

---

## Struktura plików

```
dns_server/
├── __main__.py     Punkt wejścia, inicjalizacja komponentów
├── server.py       Serwer UDP i TCP (asyncio)
├── resolver.py     Główna logika rozwiązywania zapytań
├── zone.py         ZoneStore, Zone, ResourceRecord, journal P2P
├── recursive.py    Iteracyjny resolver / forwarder
├── acl.py          ACL oparta na CIDR
├── cache.py        LRU cache z TTL
├── peer.py         Synchronizacja P2P (klient + serwer)
├── requirements.txt
├── README.md
└── config.yaml     Przykładowa konfiguracja
```

---

## Możliwe rozszerzenia

- **API HTTP** (FastAPI) do zarządzania rekordami w czasie rzeczywistym
- **TLS dla P2P** (`ssl.create_default_context()` w asyncio)
- **EDNS0** — obsługa większych odpowiedzi UDP (do 4096 B)
- **DNS-over-TLS (DoT)** — port 853
- **Metryki** — Prometheus endpoint ze statystykami cache, zapytań, peerów
- **Dynamiczne aktualizacje** — RFC 2136 (TSIG-signed UPDATE)
