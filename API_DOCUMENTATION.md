# EasyDNS REST API - Dokumentacja

## Spis treści
1. [Przegląd](#przegląd)
2. [Autentykacja i bezpieczeństwo](#autentykacja-i-bezpieczeństwo)
3. [Endpointy](#endpointy)
4. [Format żądań i odpowiedzi](#format-żądań-i-odpowiedzi)
5. [Kody statusu HTTP](#kody-statusu-http)
6. [Przykłady użycia](#przykłady-użycia)
7. [Rate limiting](#rate-limiting)
8. [Generowanie certyfikatów HTTPS](#generowanie-certyfikatów-https)

---

## Przegląd

EasyDNS REST API umożliwia programowe zarządzanie serwerem DNS, w tym:
- Odczyt i modyfikację rekordów DNS
- Zarządzanie strefami
- Monitorowanie statystyk serwera
- Health check'i

**Wersja API:** `v1`  
**Bazowy URL:** `http://[host]:[port]/api/v1`

### Cechy bezpieczeństwa

- ✅ **HTTPS** - opcjonalna obsługa SSL/TLS
- ✅ **ACL-based** - kontrola dostępu oparta na ACL (uprawnienie `api`)
- ✅ **Rate limiting** - 10 żądań na 60 sekund per IP
- ✅ **Slowloris protection** - timeout na body żądania (10s)
- ✅ **Asyncio** - nieblokująca obsługa żądań

---

## Autentykacja i bezpieczeństwo

### Wielowarstwowe zabezpieczenie

API wykorzystuje trzy warstwy bezpieczeństwa w poniższej kolejności:

1. **API-Key** (opcjonalne) - Autentykacja aplikacji za pomocą klucza
2. **ACL** (wymagane) - Autoryzacja oparta na IP klienta i uprawnieniach
3. **Rate Limiting** (wbudowane) - Ochrona przed nadużyciem

#### Kolejność sprawdzania

```
Żądanie
  ↓
[1] API-Key middleware (401 Unauthorized jeśli brakuje/nieprawidłowy klucz)
  ↓
[2] ACL middleware (403 Forbidden jeśli IP/uprawnienia niedostateczne)
  ↓
[3] Rate Limit middleware (429 Too Many Requests jeśli limit przekroczony)
  ↓
[4] Handler
```

### API-Key (Autentykacja aplikacji)

API-Key zapewnia dodatkową warstwę bezpieczeństwa oprócz ACL.

#### Konfiguracja w `config.yaml`:

```yaml
api:
  enabled: true
  listen: "0.0.0.0"
  port: 8443
  keys:
    - "sk-prod-1234567890abcdef"       # Production
    - "sk-staging-fedcba0987654321"    # Staging
```

#### Wysyłanie API-Key w żądaniach

**Metoda 1: Nagłówek X-API-Key (zalecane)**
```bash
curl -H "X-API-Key: sk-prod-1234567890abcdef" \
  https://api.example.com:8443/api/v1/zones
```

**Metoda 2: Nagłówek Authorization (Bearer)**
```bash
curl -H "Authorization: Bearer sk-prod-1234567890abcdef" \
  https://api.example.com:8443/api/v1/zones
```

**Metoda 3: Nagłówek Authorization (bezpośredni)**
```bash
curl -H "Authorization: sk-prod-1234567890abcdef" \
  https://api.example.com:8443/api/v1/zones
```

#### Python

```python
import requests

headers = {"X-API-Key": "sk-prod-1234567890abcdef"}
response = requests.get(
    "https://api.example.com:8443/api/v1/zones",
    headers=headers
)
```

#### JavaScript

```javascript
const apiKey = "sk-prod-1234567890abcdef";
fetch("https://api.example.com:8443/api/v1/zones", {
  headers: { "X-API-Key": apiKey }
})
.then(r => r.json())
.then(data => console.log(data));
```

**Uwaga:** Jeśli `api.keys` nie jest zdefiniowany w konfiguracji, sprawdzanie API-Key jest pomijane.

### Kontrola dostępu (ACL)

API jest chronione przez system ACL. Klient musi mieć uprawnienie `api` w dopasowanej regule ACL.

#### Przykładowa konfiguracja ACL w `config.yaml`:

```yaml
acl:
  - name: "admin-local"
    match: ["127.0.0.1/32", "::1/128"]
    allow: ["read", "write", "peer", "api"]    # pełny dostęp z localhost

  - name: "management-network"
    match: ["192.168.1.0/24"]                  # sieć zarządzania
    allow: ["api"]                              # tylko API

  - name: "default-deny"
    match: ["0.0.0.0/0", "::/0"]
    allow: []                                   # odmów wszystkim
```

**Uwaga:** ACL jest zawsze wymagane, niezależnie od API-Key.

### HTTPS/SSL

API obsługuje HTTPS. Aby włączyć, wymagane są certyfikat i klucz prywatny.

#### Konfiguracja w `config.yaml`:

```yaml
api:
  enabled: true
  listen: "0.0.0.0"
  port: 8443
  cert_file: "/etc/easydns/cert.pem"          # pełna ścieżka
  key_file: "/etc/easydns/key.pem"            # pełna ścieżka
```

### X-Forwarded-For

API obsługuje header `X-Forwarded-For` dla poprawnej identyfikacji IP klienta za proxy.

```bash
curl -H "X-Forwarded-For: 192.168.1.100" https://dns.example.com:8443/api/v1/stats
```

---

## Endpointy

### 1. Lista stref

**Endpoint:** `GET /api/v1/zones`

Pobiera listę wszystkich stref DNS na serwerze.

**Autoryzacja:** Wymaga uprawnienia `api`

**Parametry:** Brak

**Odpowiedź (200 OK):**
```json
{
  "zones": [
    {
      "name": "example.com.",
      "records_count": 42,
      "max_seq": 15
    },
    {
      "name": "example.org.",
      "records_count": 8,
      "max_seq": 3
    }
  ]
}
```

**Przykład:**
```bash
curl https://dns.example.com:8443/api/v1/zones
```

---

### 2. Zarządzanie strefami

**Dodawanie:** `POST /api/v1/zones`

```json
{"name": "example.net"}
```

Zwraca `201 Created` i nazwę strefy z końcową kropką. Nie można dodać już
istniejącej strefy (`409 Conflict`).

**Zmiana nazwy:** `PUT /api/v1/zones/{zone}`

```json
{"name": "new-example.net"}
```

Zachowuje rekordy strefy pod nową nazwą; zwraca `404 Not Found`, jeśli strefa
źródłowa nie istnieje, lub `409 Conflict`, jeśli nazwa docelowa jest zajęta.

**Usuwanie:** `DELETE /api/v1/zones/{zone}`

Zwraca `200 OK`. Usunięcie strefy usuwa również jej rekordy i jest zapamiętane
w pliku stanu, także dla stref zdefiniowanych w konfiguracji.

Zmiany stref i rekordów są zapisywane natychmiast do `state_file`. Domyślna
ścieżka to `/var/lib/easydns/state.yaml`, poza katalogiem cache.

---

### 3. Rekordy w strefie

**Endpoint:** `GET /api/v1/zones/{zone}/records`

Pobiera wszystkie rekordy w konkretnej strefie.

**Autoryzacja:** Wymaga uprawnienia `api`

**Parametry zapytania (query string):**
- `name` (opcjonalnie) - filtr po nazwie rekordu (prefiksowe dopasowanie)
- `type` (opcjonalnie) - filtr po typie (np. A, AAAA, MX, TXT)

**Odpowiedź (200 OK):**
```json
{
  "zone": "example.com.",
  "records": [
    {
      "uid": "550e8400-e29b-41d4-a716-446655440000",
      "name": "www",
      "type": "A",
      "ttl": 300,
      "rdata": {
        "value": "192.0.2.1"
      },
      "seq": 1,
      "timestamp": 1704067200.5
    },
    {
      "uid": "550e8400-e29b-41d4-a716-446655440001",
      "name": "",
      "type": "MX",
      "ttl": 3600,
      "rdata": {
        "priority": 10,
        "value": "mail.example.com."
      },
      "seq": 2,
      "timestamp": 1704067300.0
    }
  ]
}
```

**Przykłady:**
```bash
# Wszystkie rekordy
curl https://dns.example.com:8443/api/v1/zones/example.com/records

# Filtr po typie
curl "https://dns.example.com:8443/api/v1/zones/example.com/records?type=A"

# Filtr po nazwie
curl "https://dns.example.com:8443/api/v1/zones/example.com/records?name=www"

# Kombinacja
curl "https://dns.example.com:8443/api/v1/zones/example.com/records?name=www&type=A"
```

---

### 4. Dodaj rekord

**Endpoint:** `POST /api/v1/zones/{zone}/records`

Dodaje nowy rekord DNS do strefy. Jeśli rekord o tej samej nazwie, typie,
TTL i danych już istnieje, API zwraca go z `200 OK` zamiast tworzyć duplikat.

**Autoryzacja:** Wymaga uprawnienia `api`

**Nagłówek Content-Type:** `application/json`

**Żądanie (body):**
```json
{
  "name": "www",
  "type": "A",
  "ttl": 300,
  "rdata": {
    "value": "192.0.2.1"
  }
}
```

**Parametry:**
- `name` (string, wymagane) - nazwa rekordu względem strefy (np. "www", "mail", "@" = apex)
- `type` (string, wymagane) - typ rekordu (A, AAAA, CNAME, MX, TXT, NS, SOA, PTR, SRV, CAA, itp.)
- `ttl` (integer, wymagane) - Time To Live w sekundach (domyślnie: 300)
- `rdata` (object, wymagane) - dane rekordu specyficzne dla typu

**Odpowiedź (201 Created):**
```json
{
  "uid": "550e8400-e29b-41d4-a716-446655440000",
  "name": "www",
  "type": "A",
  "ttl": 300,
  "rdata": {
    "value": "192.0.2.1"
  }
}
```

**Możliwe błędy:**
- `400 Bad Request` - brakuje wymaganych pól lub nieprawidłowe dane
- `404 Not Found` - strefa nie istnieje
- `408 Request Timeout` - timeout na body żądania
- `429 Too Many Requests` - przekroczony rate limit

**Przykłady:**
```bash
# Rekord A
curl -X POST https://dns.example.com:8443/api/v1/zones/example.com/records \
  -H "Content-Type: application/json" \
  -d '{
    "name": "www",
    "type": "A",
    "ttl": 300,
    "rdata": {"value": "192.0.2.1"}
  }'

# Rekord MX
curl -X POST https://dns.example.com:8443/api/v1/zones/example.com/records \
  -H "Content-Type: application/json" \
  -d '{
    "name": "",
    "type": "MX",
    "ttl": 3600,
    "rdata": {
      "priority": 10,
      "value": "mail.example.com."
    }
  }'

# Rekord TXT (SPF)
curl -X POST https://dns.example.com:8443/api/v1/zones/example.com/records \
  -H "Content-Type: application/json" \
  -d '{
    "name": "",
    "type": "TXT",
    "ttl": 3600,
    "rdata": {"value": "v=spf1 include:_spf.example.com ~all"}
  }'

# Rekord SRV
curl -X POST https://dns.example.com:8443/api/v1/zones/example.com/records \
  -H "Content-Type: application/json" \
  -d '{
    "name": "_sip._tcp",
    "type": "SRV",
    "ttl": 3600,
    "rdata": {
      "priority": 10,
      "weight": 100,
      "port": 5060,
      "value": "sip.example.com."
    }
  }'

# Rekord CAA
curl -X POST https://dns.example.com:8443/api/v1/zones/example.com/records \
  -H "Content-Type: application/json" \
  -d '{
    "name": "",
    "type": "CAA",
    "ttl": 3600,
    "rdata": {
      "flags": 0,
      "tag": "issue",
      "value": "letsencrypt.org"
    }
  }'
```

---

### 5. Modyfikuj rekord

**Endpoint:** `PUT /api/v1/zones/{zone}/records`

Aktualizuje istniejący rekord DNS.

**Autoryzacja:** Wymaga uprawnienia `api`

**Nagłówek Content-Type:** `application/json`

**Żądanie (body):**
```json
{
  "uid": "550e8400-e29b-41d4-a716-446655440000",
  "name": "www",
  "type": "A",
  "ttl": 600,
  "rdata": {
    "value": "192.0.2.2"
  }
}
```

**Parametry:**
- `uid` (string, wymagane) - unikalny identyfikator rekordu (pobierz z GET)
- `name` (string, wymagane) - nowa nazwa
- `type` (string, wymagane) - nowy typ
- `ttl` (integer, wymagane) - nowy TTL
- `rdata` (object, wymagane) - nowe dane rekordu

**Odpowiedź (200 OK):**
```json
{
  "uid": "550e8400-e29b-41d4-a716-446655440000",
  "name": "www",
  "type": "A",
  "ttl": 600,
  "rdata": {
    "value": "192.0.2.2"
  }
}
```

**Przykład:**
```bash
curl -X PUT https://dns.example.com:8443/api/v1/zones/example.com/records \
  -H "Content-Type: application/json" \
  -d '{
    "uid": "550e8400-e29b-41d4-a716-446655440000",
    "name": "www",
    "type": "A",
    "ttl": 600,
    "rdata": {"value": "192.0.2.2"}
  }'
```

---

### 6. Usuń rekord

**Endpoint:** `DELETE /api/v1/zones/{zone}/records`

Usuwa rekord DNS ze strefy (soft-delete - oznaczenie jako deleted).

**Autoryzacja:** Wymaga uprawnienia `api`

**Nagłówek Content-Type:** `application/json`

**Żądanie (body):**
```json
{
  "uid": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Parametry:**
- `uid` (string, wymagane) - unikalny identyfikator rekordu

**Odpowiedź (200 OK):**
```json
{
  "uid": "550e8400-e29b-41d4-a716-446655440000",
  "deleted": true
}
```

**Możliwe błędy:**
- `400 Bad Request` - brak UID
- `404 Not Found` - rekord nie istnieje
- `408 Request Timeout` - timeout na body żądania

**Przykład:**
```bash
curl -X DELETE https://dns.example.com:8443/api/v1/zones/example.com/records \
  -H "Content-Type: application/json" \
  -d '{
    "uid": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

---

### 7. Statystyki serwera

**Endpoint:** `GET /api/v1/stats`

Pobiera bieżące statystyki serwera DNS.

**Autoryzacja:** Wymaga uprawnienia `api`

**Parametry:** Brak

**Odpowiedź (200 OK):**
```json
{
  "cache": {
    "hits": 1234,
    "misses": 567,
    "hit_rate": 0.685
  },
  "zones_count": 5,
  "total_records": 128
}
```

**Pola:**
- `cache.hits` (integer) - liczba trafionych zapytań w cache'u
- `cache.misses` (integer) - liczba chybionych zapytań
- `cache.hit_rate` (float) - procent trafionych zapytań (0.0-1.0)
- `zones_count` (integer) - liczba stref na serwerze
- `total_records` (integer) - całkowita liczba rekordów

**Przykład:**
```bash
curl https://dns.example.com:8443/api/v1/stats
```

---

### 8. Health check

**Endpoint:** `GET /api/v1/health`

Prosta kontrola dostępności serwera API. Nie wymaga ACL.

**Autoryzacja:** Brak (dostępne dla wszystkich)

**Parametry:** Brak

**Odpowiedź (200 OK):**
```json
{
  "status": "ok"
}
```

**Przykład:**
```bash
curl https://dns.example.com:8443/api/v1/health
```

---

## Format żądań i odpowiedzi

### Content-Type

Wszystkie żądania i odpowiedzi używają formatu JSON.

**Żądania:**
```
Content-Type: application/json
```

**Odpowiedzi:**
```
Content-Type: application/json; charset=utf-8
```

### Struktura błędu

Gdy żądanie nie powiedzie się, serwer zwraca odpowiedź JSON z pełnym opisem:

```json
{
  "error": "Bad Request",
  "message": "Missing or invalid: name, type, rdata"
}
```

**Pola:**
- `error` (string) - kategoria błędu (Bad Request, Forbidden, Not Found, itp.)
- `message` (string) - szczegółowy opis problemu

---

## Kody statusu HTTP

| Kod | Znaczenie | Opis |
|-----|-----------|------|
| **200 OK** | Sukces | Operacja wykonana pomyślnie (GET, PUT, DELETE) |
| **201 Created** | Utworzono | Nowy rekord został dodany (POST) |
| **400 Bad Request** | Błąd żądania | Brakuje wymaganych pól lub są nieprawidłowe |
| **401 Unauthorized** | Nieautoryzowany | Brakuje, nieprawidłowy lub wygasły API-Key |
| **403 Forbidden** | Dostęp zakazany | IP klienta nie ma uprawnienia `api` w ACL |
| **404 Not Found** | Nie znaleziono | Strefa lub rekord nie istnieje |
| **409 Conflict** | Konflikt | Strefa o podanej nazwie już istnieje |
| **408 Request Timeout** | Timeout | Timeout na body żądania (slowloris protection) |
| **429 Too Many Requests** | Za wiele żądań | Przekroczony rate limit na IP |
| **500 Internal Server Error** | Błąd serwera | Nieoczekiwany błąd aplikacji |

**Uwaga:** Sprawdzanie odbywa się w kolejności: API-Key (401) → ACL (403) → Rate Limit (429)

---

## Przykłady użycia

### Python + requests

```python
import requests
import json

BASE_URL = "https://dns.example.com:8443/api/v1"
ZONE = "example.com"

# Wyłącz weryfikację SSL (tylko dla testów!)
# verify=False

# 1. Pobierz wszystkie strefy
response = requests.get(f"{BASE_URL}/zones")
zones = response.json()
print("Strefy:", zones)

# 2. Pobierz rekordy
response = requests.get(f"{BASE_URL}/zones/{ZONE}/records")
records = response.json()
print("Rekordy:", records)

# 3. Dodaj nowy rekord A
new_record = {
    "name": "web",
    "type": "A",
    "ttl": 300,
    "rdata": {"value": "192.0.2.100"}
}
response = requests.post(
    f"{BASE_URL}/zones/{ZONE}/records",
    json=new_record
)
if response.status_code == 201:
    record = response.json()
    print(f"Rekord utworzony: {record['uid']}")
else:
    print(f"Błąd: {response.status_code}", response.json())

# 4. Modyfikuj rekord
uid = record['uid']
update_data = {
    "uid": uid,
    "name": "web",
    "type": "A",
    "ttl": 600,
    "rdata": {"value": "192.0.2.101"}
}
response = requests.put(
    f"{BASE_URL}/zones/{ZONE}/records",
    json=update_data
)
print("Rekord zaktualizowany:", response.json())

# 5. Usuń rekord
delete_data = {"uid": uid}
response = requests.delete(
    f"{BASE_URL}/zones/{ZONE}/records",
    json=delete_data
)
print("Rekord usunięty:", response.json())

# 6. Pobierz statystyki
response = requests.get(f"{BASE_URL}/stats")
stats = response.json()
print("Statystyki:", stats)

# 7. Health check
response = requests.get(f"{BASE_URL}/health")
print("Status:", response.json()['status'])
```

### bash + curl

```bash
#!/bin/bash

API="https://dns.example.com:8443/api/v1"
ZONE="example.com"

# 1. Health check
echo "=== Health check ==="
curl -s "$API/health" | jq .

# 2. Lista stref
echo "=== Strefy ==="
curl -s "$API/zones" | jq .zones

# 3. Rekordy A
echo "=== Rekordy A ==="
curl -s "$API/zones/$ZONE/records?type=A" | jq .records

# 4. Dodaj rekord
echo "=== Dodaj rekord ==="
NEW_RECORD=$(curl -s -X POST "$API/zones/$ZONE/records" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "api-test",
    "type": "A",
    "ttl": 300,
    "rdata": {"value": "192.0.2.200"}
  }')
echo "$NEW_RECORD" | jq .
UID=$(echo "$NEW_RECORD" | jq -r '.uid')

# 5. Modyfikuj rekord
echo "=== Modyfikuj rekord ==="
curl -s -X PUT "$API/zones/$ZONE/records" \
  -H "Content-Type: application/json" \
  -d "{
    \"uid\": \"$UID\",
    \"name\": \"api-test\",
    \"type\": \"A\",
    \"ttl\": 600,
    \"rdata\": {\"value\": \"192.0.2.201\"}
  }" | jq .

# 6. Statystyki
echo "=== Statystyki ==="
curl -s "$API/stats" | jq .

# 7. Usuń rekord
echo "=== Usuń rekord ==="
curl -s -X DELETE "$API/zones/$ZONE/records" \
  -H "Content-Type: application/json" \
  -d "{\"uid\": \"$UID\"}" | jq .
```

### JavaScript/Node.js

```javascript
const fetch = require('node-fetch');

const API = "https://dns.example.com:8443/api/v1";
const ZONE = "example.com";

async function dnsApiDemo() {
  // 1. Health check
  let response = await fetch(`${API}/health`);
  console.log("Health:", await response.json());

  // 2. List zones
  response = await fetch(`${API}/zones`);
  console.log("Zones:", await response.json());

  // 3. Get records
  response = await fetch(`${API}/zones/${ZONE}/records`);
  console.log("Records:", await response.json());

  // 4. Add record
  response = await fetch(`${API}/zones/${ZONE}/records`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: 'nodejs-test',
      type: 'A',
      ttl: 300,
      rdata: { value: '192.0.2.150' }
    })
  });
  const newRecord = await response.json();
  console.log("Added:", newRecord);

  // 5. Update record
  response = await fetch(`${API}/zones/${ZONE}/records`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      uid: newRecord.uid,
      name: 'nodejs-test',
      type: 'A',
      ttl: 600,
      rdata: { value: '192.0.2.151' }
    })
  });
  console.log("Updated:", await response.json());

  // 6. Delete record
  response = await fetch(`${API}/zones/${ZONE}/records`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uid: newRecord.uid })
  });
  console.log("Deleted:", await response.json());

  // 7. Stats
  response = await fetch(`${API}/stats`);
  console.log("Stats:", await response.json());
}

dnsApiDemo().catch(console.error);
```

---

## Rate limiting

API implementuje rate limiting: **10 żądań na 60 sekund per IP**.

### Response headers

Każda odpowiedź zawiera nagłówki informujące o stanie rate limitera:

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
```

Gdzie:
- `X-RateLimit-Limit` - maksimum żądań w oknie czasowym
- `X-RateLimit-Remaining` - pozostałe żądania

### Przekroczenie limitu

Gdy limit zostanie przekroczony, serwer zwraca:

```
HTTP/1.1 429 Too Many Requests
Content-Type: application/json

{
  "error": "Too Many Requests",
  "message": "Rate limit exceeded"
}
```

### Zakres IP

Rate limiting dotyczy rzeczywistego adresu IP klienta. Jeśli klient łączy się przez proxy, użyj nagłówka `X-Forwarded-For`:

```bash
curl -H "X-Forwarded-For: 192.168.1.100" https://dns.example.com:8443/api/v1/stats
```

---

## Generowanie certyfikatów HTTPS

### Certyfikat Self-Signed (testowanie)

Dla testów lokalnych:

```bash
# Generuj klucz prywatny (RSA 2048 bit)
openssl genrsa -out key.pem 2048

# Generuj certyfikat (ważny 365 dni)
openssl req -new -x509 -key key.pem -out cert.pem -days 365 \
  -subj "/CN=dns.example.com/O=EasyDNS/C=PL"

# Sprawdzenie certyfikatu
openssl x509 -in cert.pem -text -noout

# Użyj w konfiguracji:
# cert_file: "/path/to/cert.pem"
# key_file: "/path/to/key.pem"
```

### Certyfikat Let's Encrypt (produkcja)

```bash
# Zainstaluj certbot
sudo apt-get install certbot

# Uzyski certyfikat dla domeny
sudo certbot certonly --standalone -d dns.example.com

# Certyfikat będzie w:
# /etc/letsencrypt/live/dns.example.com/fullchain.pem
# /etc/letsencrypt/live/dns.example.com/privkey.pem

# Użyj w konfiguracji:
# cert_file: "/etc/letsencrypt/live/dns.example.com/fullchain.pem"
# key_file: "/etc/letsencrypt/live/dns.example.com/privkey.pem"

# Auto-renewal (cron)
# 0 3 * * * /usr/bin/certbot renew --quiet
```

### Testowanie certyfikatu (curl)

```bash
# Z weryfikacją SSL
curl https://dns.example.com:8443/api/v1/health

# Bez weryfikacji (test self-signed)
curl -k https://dns.example.com:8443/api/v1/health
# lub
curl --insecure https://dns.example.com:8443/api/v1/health
```

---

## Tryb debugowania

### Logi API

Aby włączyć szczegółowe logi, ustaw level logging'u w konfiguracji:

```yaml
logging:
  level: "DEBUG"
  file: "/var/log/easydns/dns_server.log"
```

### Monitorowanie żądań

Użyj tcpdump/Wireshark:

```bash
# Przechwytuj HTTPS na porcie 8443
sudo tcpdump -i any -n port 8443

# Lub zainstaluj mitmproxy do analizy traffic'u
mitmproxy --mode reverse:https://localhost:8443 --listen-host 0.0.0.0 --listen-port 8080
```

---

## Uwagi bezpieczeństwa

### Best Practices

1. **Zawsze używaj HTTPS** w produkcji
2. **Skonfiguruj ACL** - ograicz dostęp do API do zaufanych sieci
3. **Monitoruj logi** - szukaj nieautoryzowanych prób dostępu
4. **Regularnie rotuj klucze** - zmień hasła dostępu
5. **Rate limiting** - domyślnie włączony, nie wyłączaj
6. **Firewall** - zablokuj port API na firewall'u dla klientów niezaufanych

### Ochrona przed atakami

- **Slowloris**: Timeout na body żądania (10 sekund)
- **DDoS**: Rate limiting per IP
- **Brute-force**: ACL + reverse DNS blokowanie podejrzanych IP
- **CSRF**: API jest stateless, natywnie bezpieczne

---

## Troubleshooting

### "Forbidden" (403)

```
Przyczyna: IP klienta nie ma uprawnienia 'api' w ACL
Rozwiązanie: Dodaj IP do reguły ACL z allow: ["api"]
```

### "Rate limit exceeded" (429)

```
Przyczyna: Przekroczono limit 10 żądań/60 sekund
Rozwiązanie: Czekaj lub zwiększ interwał między żądaniami
```

### "Request Timeout" (408)

```
Przyczyna: Zbyt długo wysyłałeś body żądania (>10 sekund)
Rozwiązanie: Pośpiesz się lub zwiększ size JSON'a
```

### "Zone not found" (404)

```
Przyczyna: Strefa nie istnieje na serwerze
Rozwiązanie: Upewnij się, że nazwa strefy jest poprawna (np. "example.com.")
```

### "Internal Server Error" (500)

```
Przyczyna: Nieoczekiwany błąd aplikacji
Rozwiązanie: Sprawdź logi serwera, zgłoś issue
```

---

## Wsparcie

Problemy, pytania lub sugestie? Otwórz issue na GitHub:  
https://github.com/MarcinKwiatkowski81/EasyDNS/issues

Pełna dokumentacja projektu:  
https://github.com/MarcinKwiatkowski81/EasyDNS
