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
# Z domyślnym /etc/easydns/easydns.yaml
sudo python -m dns_server

# Z lokalną konfiguracją w repozytorium
sudo python3 -m dns_server -c config.yaml
```

Port 53 wymaga uprawnień root (lub `CAP_NET_BIND_SERVICE`).  
Bez roota: ustaw `port: 5300` i przekieruj ruch przez iptables:

```bash
sudo iptables -t nat -A PREROUTING -p udp --dport 53 -j REDIRECT --to-port 5300
sudo iptables -t nat -A PREROUTING -p tcp --dport 53 -j REDIRECT --to-port 5300
```

---

## Pakiet Debian/Ubuntu

Pakiet wymaga systemowego Pythona co najmniej 3.11 (np. Debian 12+
lub Ubuntu 24.04+). Zależności runtime są instalowane przez APT:
`python3`, `python3-dnslib`, `python3-yaml` oraz narzędzia obsługi usługi.
Peering używa HMAC z biblioteki standardowej; pakiet nie wymaga pip.

Budowanie w katalogu repozytorium:

```bash
sudo apt install build-essential dpkg-dev debhelper dh-python \
  python3 python3-dnslib python3-yaml
dpkg-buildpackage -us -uc -b
sudo apt install ../easydns_0.1.0_all.deb
```

Pakiet instaluje i włącza `easydns.service`, a przy instalacji próbuje go
uruchomić. Przed instalacją zatrzymaj poprzednią instancję DNS zajmującą
port 53. Nie wyłączaj innych usług DNS bez sprawdzenia, czy są potrzebne.
Domyślna konfiguracja pakietu jest konfiguracją huba dla `mkw.`.

| Ścieżka | Zawartość |
|---------|-----------|
| `/usr/sbin/easydns` | Polecenie uruchamiające aplikację |
| `/usr/lib/easydns/dns_server/` | Moduły Pythona |
| `/etc/easydns/easydns.yaml` | Domyślna konfiguracja, chroniona przy aktualizacji przez dpkg |
| `/var/cache/easydns/state.yaml` | Domyślny plik stanu |
| `/usr/share/doc/easydns/` | Dokumentacja i changelog |
| `/usr/share/doc/easydns/examples/` | Konfiguracje huba, gałęzi i natywnego peeringu |

Usługa działa jako użytkownik `easydns`, a nie root. Ma wyłącznie
capability `CAP_NET_BIND_SERVICE` do portu 53. Katalog konfiguracji jest
czytelny dla grupy `easydns`; plik konfiguracji ma prawa `0640`, co chroni
również klucze peeringu. Używając własnego pliku konfiguracji, zachowaj
właściciela `root:easydns` i te same prawa.

Przełączenie na konfigurację BB:

```bash
sudo systemctl stop easydns
sudo install -o root -g easydns -m 0640 \
  /usr/share/doc/easydns/examples/config-bb.example /etc/easydns/easydns.yaml
sudo systemctl start easydns
sudo systemctl status easydns
```

Przykłady hierarchiczne mają względne nazwy stanu, np. `state-bb.yaml`.
Usługa ma `WorkingDirectory=/var/cache/easydns`, więc zapisuje je w tym
katalogu. Przy uruchomieniu ręcznym ustaw bezwzględne `state_file` pod
`/var/cache/easydns`. Bez podania tego klucza aplikacja używa
`/var/cache/easydns/state.yaml`. Stan jest zapisywany przy prawidłowym
zatrzymaniu; cache DNS pozostaje w pamięci. Zgodnie z żądaną lokalizacją
stan jest w katalogu cache, który administrator może wyczyścić.

Logowanie domyślnie używa syslog (`logging.syslog: true`, `/dev/log`),
a gdy socket syslog nie istnieje, stdout przechwytywanego przez journald:

```bash
journalctl -u easydns -f
```

Aby dodatkowo zapisywać log do pliku, ustaw `logging.file` na
`/var/log/easydns.log`. Pakiet przygotowuje ten plik z prawami do zapisu
dla usługi i instaluje konfigurację logrotate. Katalog `/etc/easydns` jest
dla usługi tylko do odczytu; plik stanu musi pozostać w katalogu cache.

Opcjonalny przykład `config-peer.example` pokazuje natywny peering
HUB–BB na TCP 5353. To osobny wariant, nie rozszerzenie hierarchii mkw:
replikowane są wszystkie jego strefy. Przed włączeniem wygeneruj własny
wspólny klucz, ustaw różne `server.id`, wzajemne adresy partnerów i ACL
zgodne z rzeczywistymi adresami źródłowymi VPN. Nie uruchamiaj go z kluczem
zastępczym. Zapewnij łączność TCP 5353 w obu kierunkach.

Testy lokalne: `python3 -m unittest discover -s tests -v`.
Projekt jest udostępniany na licencji Apache-2.0. Informacje o prawach
autorskich i pełny tekst licencji znajdują się w plikach [LICENSE](LICENSE)
i [debian/copyright](debian/copyright).

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

### Hierarchia sieci mkw

Hub jest root-ns dla prywatnej domeny `mkw.`, nie dla internetowej strefy `.`.

| Węzeł | Sieć | DNS | Konfiguracja |
|-------|------|-----|--------------|
| Hub | `192.168.10.0/24` | `192.168.10.1` | `config-hub.example` |
| Kraków | `192.168.16.0/20` | `192.168.16.16` | `config-krk.example` |
| Bielsko | `192.168.32.0/20` | `192.168.32.16` | `config-bb.example` |

Ze względu na ograniczenia routingu Kraków odpytuje hub pod `192.168.10.1`,
a Bielsko pod `192.168.10.5` (interfejs huba od strony tunelu Bielska).
Dotyczy to forwardera ogólnego oraz conditional forwarding domen i reverse DNS.
Oba adresy należą do tego samego huba; główny rekord `ns0.hub.mkw`
pozostaje ustawiony na `192.168.10.1`.

`config.yaml` oraz `config-mkw.example` zawierają konfigurację huba.
Na każdym węźle użyj odpowiadającego mu pliku, np.:

```bash
sudo python3 -m dns_server -c config-krk.example
```

Hub utrzymuje `mkw.`, `hub.mkw.` i reverse sieci VPN. Deleguje `krk.mkw.`
i `bb.mkw.` do właściwych gałęzi, a dzięki conditional forwarding zwraca
klientowi pełną odpowiedź. Przekazuje też reverse całych sieci `/20`
(po 16 stref `/24`) do odpowiednich serwerów.

Gałęzie utrzymują wyłącznie własną domenę i reverse własnego `/20`.
Pozostałe zapytania, w tym do drugiej gałęzi i internetu, wysyłają wyłącznie
do huba. Nie mają bezpośrednich forwarderów do siebie, publicznego
fallbacku ani P2P (`peers: []`, `peer_listen.port: 0`). Przykładowa ścieżka:
`KRK → HUB → BB`; przy awarii huba lokalne strefy nadal działają,
ale zapytania poza nimi nie mają alternatywnej drogi.

ACL pozwalają na zapytania z `10.0.0.0/8`, `172.16.0.0/12`
i `192.168.0.0/16`, bez prawa zapisu. Nie jest to blokada ruchu sieciowego
KRK–BB: taką izolację należy wymusić na firewallu VPN.

Przy migracji z P2P zatrzymaj serwery i zarchiwizuj dotychczasowe pliki
stanu, jeśli zawierają replikowane strefy. Loader wczytuje stan po
konfiguracji, więc stary journal może przywrócić nieaktualne strefy i rekordy.

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
# EasyDNS
