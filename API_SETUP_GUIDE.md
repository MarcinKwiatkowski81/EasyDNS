# Przewodnik instalacji i konfiguracji REST API EasyDNS

## Spis treści

1. [Wymagania](#wymagania)
2. [Instalacja](#instalacja)
3. [Konfiguracja](#konfiguracja)
4. [Uruchomienie](#uruchomienie)
5. [Testy](#testy)
6. [Troubleshooting](#troubleshooting)

---

## Wymagania

### Zależności Python

- Python 3.9+
- aiohttp >= 3.9.0 (HTTP server)
- PyYAML >= 6.0 (konfiguracja)
- dnslib >= 0.9.19 (parsowanie DNS)
- cryptography >= 41.0 (SSL/TLS)

### System

- Linux (lub macOS/Windows z WSL2)
- Port dostępny (domyślnie 8080 dla HTTP, 8443 dla HTTPS)
- Certyfikat SSL/TLS (opcjonalnie dla HTTPS)

---

## Instalacja

### 1. Zainstaluj zależności

```bash
# Zaktualizuj pip
pip install --upgrade pip

# Zainstaluj wymagane pakiety
cd /home/mkwiatkowski/Projects/EasyDNS
pip install -r dns_server/requirements.txt
```

Sprawdzenie:

```bash
python3 -c "import aiohttp; print(f'✓ aiohttp {aiohttp.__version__}')"
python3 -c "import yaml; print('✓ PyYAML')"
python3 -c "import dnslib; print('✓ dnslib')"
python3 -c "import cryptography; print('✓ cryptography')"
```

### 2. Sprawdź instalację

```bash
# Spróbuj zaimportować moduł API
python3 -c "from dns_server.api import ApiServer; print('✓ API module loaded')"
```

---

## Konfiguracja

### 1. Edytuj config.yaml

Otwórz plik konfiguracyjny:

```bash
nano config.yaml
```

### 2. Włącz API

Lokalizuj sekcję `api:` i zmień:

```yaml
api:
  enabled: false              # <- zmień na true
  listen: "0.0.0.0"          # IP nasłuchiwania
  port: 8080                 # Port (HTTP)
  # cert_file: "/path/to/cert.pem"
  # key_file: "/path/to/key.pem"
```

### 3. Skonfiguruj ACL

Dodaj uprawnienie `api` do odpowiednich reguł ACL:

```yaml
acl:
  - name: "localhost"
    match: ["127.0.0.0/8", "::1/128"]
    allow: ["read", "write", "peer", "api"]    # <- dodaj "api"

  - name: "admin-network"
    match: ["192.168.1.0/24"]                  # Twoja sieć
    allow: ["api"]                              # Tylko API

  - name: "default-deny"
    match: ["0.0.0.0/0", "::/0"]
    allow: []
```

### 4. (Opcjonalnie) Włącz HTTPS

#### Generuj certyfikat self-signed:

```bash
# Klucz prywatny
openssl genrsa -out /tmp/key.pem 2048

# Certyfikat
openssl req -new -x509 -key /tmp/key.pem -out /tmp/cert.pem -days 365 \
  -subj "/CN=localhost/O=EasyDNS/C=PL"

# Przenieś do /etc (jeśli uruchamiasz jako root)
sudo mkdir -p /etc/easydns
sudo mv /tmp/cert.pem /etc/easydns/cert.pem
sudo mv /tmp/key.pem /etc/easydns/key.pem
sudo chmod 600 /etc/easydns/key.pem
```

#### W config.yaml:

```yaml
api:
  enabled: true
  listen: "0.0.0.0"
  port: 8443                                      # <- zmień na 8443
  cert_file: "/etc/easydns/cert.pem"
  key_file: "/etc/easydns/key.pem"
```

### 4b. (Zalecane) Skonfiguruj API-Key

API-Key zapewnia dodatkową warstwę bezpieczeństwa oprócz ACL. Każda aplikacja otrzymuje swój klucz.

#### Generuj bezpieczne klucze

**Opcja 1: Python**
```bash
python3 -c "import secrets; print('sk-' + secrets.token_hex(16))"
# sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

**Opcja 2: OpenSSL**
```bash
openssl rand -hex 16 | sed 's/^/sk-/'
# sk-fedcba9876543210fedcba9876543210
```

#### W config.yaml:

```yaml
api:
  enabled: true
  listen: "0.0.0.0"
  port: 8443
  cert_file: "/etc/easydns/cert.pem"
  key_file: "/etc/easydns/key.pem"
  keys:                                           # <- dodaj
    - "sk-prod-1234567890abcdef"       # Production
    - "sk-staging-fedcba0987654321"    # Staging
    # - "sk-dev-abcdef1234567890"      # Development
```

**Uwaga:** 
- Klucze są opcjonalne. Jeśli nie zdefiniujesz `keys`, sprawdzanie API-Key zostanie pominięte.
- Klucz musi być przesłany w każdym żądaniu (nagłówek `X-API-Key` lub `Authorization`).
- ACL jest zawsze wymagane, niezależnie od API-Key.

#### Użycie w klientach

```bash
# curl
curl -H "X-API-Key: sk-prod-1234567890abcdef" \
  https://api.example.com:8443/api/v1/zones

# Python
import requests
headers = {"X-API-Key": "sk-prod-1234567890abcdef"}
requests.get("https://api.example.com:8443/api/v1/zones", headers=headers)
```

Więcej: zobacz [API_KEY_GUIDE.md](API_KEY_GUIDE.md)

### 5. Pełny przykład konfiguracji

```yaml
# ... reszta konfiguracji DNS ...

cache:
  enabled: true
  max_size: 10000
  min_ttl: 30

# ── REST API
api:
  enabled: true                              # Włącz API
  listen: "0.0.0.0"                          # Nasłuchuj na wszystkich interfejsach
  port: 8443                                 # Port 8443 dla HTTPS
  cert_file: "/etc/easydns/cert.pem"         # Certyfikat SSL
  key_file: "/etc/easydns/key.pem"           # Klucz prywatny
  keys:                                      # API-Key (zalecane)
    - "sk-prod-xxxxxxxxxxxxxxxx"
    - "sk-staging-yyyyyyyyyyyyyyyy"

state_file: "state.yaml"

acl:
  - name: "localhost"
    match: ["127.0.0.0/8", "::1/128"]
    allow: ["read", "write", "peer", "api"]

  - name: "private-networks"
    match: ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
    allow: ["read"]

  - name: "default"
    match: ["0.0.0.0/0", "::/0"]
    allow: []

zones:
  - name: "example.com"
    records:
      - name: "@"
        type: SOA
        ttl: 3600
        mname: "ns.example.com"
        rname: "admin.example.com"
        serial: 2024010101
        refresh: 3600
        retry: 900
        expire: 604800
        minimum: 300

logging:
  level: "INFO"
  file: ""
```

---

## Uruchomienie

### 1. Testowanie (bez HTTPS)

```bash
# Z lokalnej ścieżki
cd /home/mkwiatkowski/Projects/EasyDNS
python3 -m dns_server -c config.yaml
```

Wyjście powinno zawierać:

```
2026-11-18 10:30:00 INFO     dns_server: REST API serwer uruchomiony: 0.0.0.0:8080 (HTTP)
2026-11-18 10:30:00 INFO     dns_server: Serwer gotowy. Ctrl+C aby zatrzymać.
```

### 2. Sprawdzenie health check'u

W innym terminalu:

```bash
curl http://localhost:8080/api/v1/health
# Odpowiedź: {"status": "ok"}
```

### 3. Uruchomienie jako systemd service (opcjonalnie)

Plik `/etc/systemd/system/easydns-api.service`:

```ini
[Unit]
Description=EasyDNS Server with REST API
After=network.target

[Service]
Type=simple
User=dns
Group=dns
WorkingDirectory=/etc/easydns
ExecStart=/usr/bin/python3 -m dns_server -c /etc/easydns/config.yaml
Restart=on-failure
RestartSec=10

# Bezpieczeństwo
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/cache/easydns /var/log/easydns

[Install]
WantedBy=multi-user.target
```

Uruchomienie:

```bash
sudo systemctl daemon-reload
sudo systemctl enable easydns
sudo systemctl start easydns
sudo systemctl status easydns
```

---

## Testy

### 1. Test health check

```bash
curl http://localhost:8080/api/v1/health
```

### 2. Test listy stref (z API-Key)

```bash
curl -H "X-API-Key: sk-prod-xxxxxxxxxxxxxxxx" \
  http://localhost:8080/api/v1/zones | jq .
```

### 3. Test dodawania rekordu (z API-Key)

```bash
curl -X POST http://localhost:8080/api/v1/zones/example.com/records \
  -H "X-API-Key: sk-prod-xxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test",
    "type": "A",
    "ttl": 300,
    "rdata": {"value": "192.0.2.1"}
  }' | jq .
```

### 4. Test HTTPS (jeśli włączony)

```bash
# Bez weryfikacji certyfikatu + API-Key
curl -k -H "X-API-Key: sk-prod-xxxxxxxxxxxxxxxx" \
  https://localhost:8443/api/v1/health
```

### 5. Test API-Key (401 Unauthorized)

```bash
# Brakuje API-Key
curl http://localhost:8080/api/v1/zones
# Odpowiedź: 401 Unauthorized

# Zły API-Key
curl -H "X-API-Key: sk-invalid-key" \
  http://localhost:8080/api/v1/zones
# Odpowiedź: 401 Unauthorized
```

### 6. Test ACL (403 Forbidden)

```bash
# Zrób żądanie z IP spoza ACL (np. z innego hosta)
# Powinno zwrócić 403, nawet z poprawnym API-Key
# (jeśli IP nie ma uprawnienia 'api' w ACL)
```

### 7. Test rate limiting (429)

```bash
# Zrób >10 żądań w 60 sekund z API-Key
for i in {1..15}; do
  curl -H "X-API-Key: sk-prod-xxxxxxxxxxxxxxxx" \
    http://localhost:8080/api/v1/health
  echo ""
done

# Żądania 11-15 powinny zwrócić 429 Too Many Requests
```

### 8. Test timeout (slowloris protection)

```bash
# Wyśli gigantyczne body
(echo -n '{"name":"test","type":"A","ttl":300,"rdata":{"value":"192.0.2.1"}'; sleep 15) | \
  curl -X POST http://localhost:8080/api/v1/zones/example.com/records \
    -H "X-API-Key: sk-prod-xxxxxxxxxxxxxxxx" \
    -H "Content-Type: application/json" \
    --data-binary @- -v

# Powinno zwrócić 408 Timeout
```

### Test za pomocą Python skryptu

Plik `test_api.py`:

```python
#!/usr/bin/env python3
import requests
import json
import sys

API_URL = "http://localhost:8080/api/v1"
ZONE = "example.com"
API_KEY = "sk-prod-xxxxxxxxxxxxxxxx"  # <- ustaw swój klucz

HEADERS = {"X-API-Key": API_KEY}  # Nagłówek do każdego żądania

def test_health():
    print("TEST: Health check...", end=" ")
    try:
        resp = requests.get(f"{API_URL}/health", timeout=5)
        assert resp.status_code == 200
        assert resp.json()['status'] == 'ok'
        print("✓")
    except Exception as e:
        print(f"✗ {e}")
        return False
    return True

def test_zones():
    print("TEST: List zones...", end=" ")
    try:
        resp = requests.get(f"{API_URL}/zones", headers=HEADERS, timeout=5)
        assert resp.status_code == 200
        assert 'zones' in resp.json()
        print("✓")
    except Exception as e:
        print(f"✗ {e}")
        return False
    return True

def test_records():
    print("TEST: Get records...", end=" ")
    try:
        resp = requests.get(f"{API_URL}/zones/{ZONE}/records", headers=HEADERS, timeout=5)
        if resp.status_code == 404:
            print("⊗ (zone not found, skipping)")
            return True
        assert resp.status_code == 200
        assert 'records' in resp.json()
        print("✓")
    except Exception as e:
        print(f"✗ {e}")
        return False
    return True

def test_add_record():
    print("TEST: Add record...", end=" ")
    try:
        payload = {
            "name": "test-api",
            "type": "A",
            "ttl": 300,
            "rdata": {"value": "192.0.2.123"}
        }
        resp = requests.post(
            f"{API_URL}/zones/{ZONE}/records",
            json=payload,
            timeout=5
        )
        if resp.status_code == 404:
            print("⊗ (zone not found, skipping)")
            return True
        assert resp.status_code == 201
        data = resp.json()
        assert 'uid' in data
        print(f"✓ (uid: {data['uid'][:8]}...)")
        return data['uid']
    except Exception as e:
        print(f"✗ {e}")
        return False

def test_stats():
    print("TEST: Get stats...", end=" ")
    try:
        resp = requests.get(f"{API_URL}/stats", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert 'cache' in data
        print(f"✓ (hit_rate: {data['cache']['hit_rate']:.1%})")
    except Exception as e:
        print(f"✗ {e}")
        return False
    return True

if __name__ == "__main__":
    print("=" * 50)
    print("EasyDNS REST API Test Suite")
    print("=" * 50)
    
    tests = [
        test_health,
        test_zones,
        test_records,
        test_stats,
    ]
    
    results = []
    for test in tests:
        result = test()
        results.append(result)
    
    # Test dodawania (opcjonalnie)
    uid = test_add_record()
    
    print("=" * 50)
    passed = sum(1 for r in results if r)
    print(f"Wyniki: {passed}/{len(results)} testów przeszło ✓")
    print("=" * 50)
```

Uruchamianie:

```bash
chmod +x test_api.py
python3 test_api.py
```

---

## Troubleshooting

### "Module not found: aiohttp"

```bash
# Zainstaluj aiohttp
pip install aiohttp>=3.9.0
```

### "Port already in use"

```bash
# Sprawdź co używa portu
lsof -i :8080

# Lub zmień port w config.yaml
api:
  port: 9000  # inny port
```

### "Permission denied" (port <1024)

```bash
# Porty <1024 wymagają root'a
sudo python3 -m dns_server -c config.yaml

# Lub użyj portu >1024
api:
  port: 8080
```

### "SSL certificate verification failed"

```bash
# Do testów, wyłącz weryfikację
curl -k https://localhost:8443/api/v1/health

# Lub zainstal certyfikat do systemowego truststore
sudo cp /etc/easydns/cert.pem /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

### "Forbidden (403)" od poprawnego IP

Sprawdzić ACL:

```bash
# 1. Sprawdź IP w logach
sudo journalctl -u easydns -f

# 2. Upewnij się, że reguła ACL zawiera "api"
# 3. Sprawdzić format CIDR (np. "192.168.1.0/24" a nie "192.168.1.1")

# 4. Test z localhost (jeśli dodałeś "api" do localhost)
curl http://127.0.0.1:8080/api/v1/health
```

### Timeout na body żądania (408)

```bash
# Problem: Zbyt duży payload lub wolne wysyłanie
# Rozwiązanie: Zmniejsz rozmiar JSON lub zwiększ timeout w api.py

# Lub test z curl:
timeout 15 curl -X POST http://localhost:8080/api/v1/zones/example.com/records \
  -H "Content-Type: application/json" \
  -d '{"name":"test","type":"A","ttl":300,"rdata":{"value":"192.0.2.1"}}'
```

### "Rate limit exceeded" (429)

```bash
# Normalnie - czekaj 60 sekund
# Lub do testów, zmodyfikuj w api.py:
RATE_LIMIT_REQUESTS = 100  # zamiast 10
RATE_LIMIT_WINDOW = 60.0   # sekund
```

---

## Następne kroki

1. ✅ Zainstalowałeś API
2. ✅ Skonfigurowałeś ACL
3. ✅ Przetestowałeś health check

Teraz:

- Przeczytaj [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) aby poznać wszystkie endpointy
- Zintegruj API z Twoją aplikacją
- Skonfiguruj HTTPS z certyfikatem Let's Encrypt dla produkcji
- Ustaw monitoring i alerting
