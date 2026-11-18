# API-Key Authentication Guide

## Przegląd

API-Key zapewnia dodatkową warstwę bezpieczeństwa oprócz ACL. Pozwala na:

✅ **Autentykację aplikacji** - Każda aplikacja ma własny klucz  
✅ **Revocable access** - Można wyłączyć klucz bez zmian w ACL  
✅ **Audit trail** - Wiedzieć, która aplikacja do czego dostępiła  
✅ **Multi-environment** - Różne klucze dla dev/staging/prod  

---

## Konfiguracja API-Key

### 1. Zdefiniuj klucze w `config.yaml`

```yaml
api:
  enabled: true
  listen: "0.0.0.0"
  port: 8080
  keys:
    - "sk-prod-1234567890abcdef"       # Production
    - "sk-dev-fedcba0987654321"        # Development
    - "sk-staging-abcdef1234567890"    # Staging
```

### 2. Generowanie bezpiecznych kluczy

**Opcja 1: Python**
```python
import secrets
key = "sk-" + secrets.token_hex(16)  # sk-xxxxxxxxxxxxxxxxxxxxxxxx
print(key)
```

**Opcja 2: OpenSSL**
```bash
openssl rand -hex 16 | sed 's/^/sk-/'
# sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

**Opcja 3: uuid**
```bash
python3 -c "import uuid; print('sk-' + str(uuid.uuid4()).replace('-', ''))"
# sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

### 3. Bezpieczne przechowywanie

**Zalecenia:**
- ✅ Przechowuj klucze w pliku konfiguracyjnym (z uprawnieniami 0640)
- ✅ Nie commituj klucze do Git'a
- ✅ Używaj zmiennych środowiskowych w produkcji
- ✅ Regularnie rotuj klucze
- ✅ Loguj dostęp do API

**Plik .gitignore:**
```
config.yaml
*.key
*.pem
.env
```

---

## Klient: Wysyłanie API-Key

### Nagłówek Authorization

**Format 1: Bearer token**
```bash
curl -H "Authorization: Bearer sk-prod-1234567890abcdef" \
  https://api.example.com:8443/api/v1/zones
```

**Format 2: Bezpośredni klucz**
```bash
curl -H "Authorization: sk-prod-1234567890abcdef" \
  https://api.example.com:8443/api/v1/zones
```

### Nagłówek X-API-Key (zalecane)

```bash
curl -H "X-API-Key: sk-prod-1234567890abcdef" \
  https://api.example.com:8443/api/v1/zones
```

### Python + requests

```python
import requests

API_KEY = "sk-prod-1234567890abcdef"

# Metoda 1: Ustaw w sesji
session = requests.Session()
session.headers.update({"X-API-Key": API_KEY})
response = session.get("https://api.example.com:8443/api/v1/zones")

# Metoda 2: Wyślij w żądaniu
headers = {"X-API-Key": API_KEY}
response = requests.get(
    "https://api.example.com:8443/api/v1/zones",
    headers=headers
)

print(response.json())
```

### JavaScript/Node.js

```javascript
const API_KEY = "sk-prod-1234567890abcdef";

fetch("https://api.example.com:8443/api/v1/zones", {
  headers: {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
  }
})
.then(r => r.json())
.then(data => console.log(data))
.catch(err => console.error(err));
```

### bash + curl + Authorization header

```bash
#!/bin/bash

API_KEY="sk-prod-1234567890abcdef"
API_URL="https://api.example.com:8443/api/v1"

# Listy strefy
curl -H "X-API-Key: $API_KEY" "$API_URL/zones" | jq .

# Dodaj rekord
curl -X POST "$API_URL/zones/example.com/records" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "www",
    "type": "A",
    "ttl": 300,
    "rdata": {"value": "192.0.2.1"}
  }' | jq .
```

---

## Obsługiwane nagłówki

| Nagłówek | Format | Przykład | Priorytet |
|----------|--------|----------|-----------|
| `X-API-Key` | Bezpośredni klucz | `X-API-Key: sk-...` | 1 (najwyższy) |
| `Authorization: Bearer` | Bearer token | `Authorization: Bearer sk-...` | 2 |
| `Authorization` | Bezpośredni klucz | `Authorization: sk-...` | 3 |

**Uwaga:** Jeśli nagłówek zawiera `Bearer ` prefix, zostaje on usunięty.

---

## Kod błędu: 401 Unauthorized

Gdy API-Key jest wymagany ale nieobecny/nieprawidłowy:

```
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{
  "error": "Unauthorized",
  "message": "Invalid or missing API key"
}
```

**Przyczyny:**
- Brak nagłówka API-Key
- Klucz nie znajduje się w `api.keys`
- Klucz wygasł (jeśli implementowano expirary)
- Zły format nagłówka

---

## Best Practices

### 1. Rotacja kluczy

Rotuj klucze co 90 dni:

```bash
# 1. Generuj nowy klucz
NEW_KEY=$(openssl rand -hex 16 | sed 's/^/sk-/')
echo "Nowy klucz: $NEW_KEY"

# 2. Dodaj do config.yaml
nano config.yaml

# 3. Restart API
sudo systemctl restart easydns

# 4. Poczekaj, aż klienci się zmienią
# 5. Usuń stary klucz z konfiguracji
# 6. Restart API
```

### 2. Klucze per środowisko

```yaml
api:
  keys:
    - "sk-prod-xxxxxxxxxxxxxxxx"       # Production
    - "sk-staging-yyyyyyyyyyyyyyyy"    # Staging
    # - "sk-dev-zzzzzzzzzzzzzzzz"      # Development (jeśli wyłączony)
```

### 3. Klucze per aplikacja

```yaml
api:
  keys:
    - "sk-app-terraform-xxxx"          # Terraform provisioning
    - "sk-app-nagios-yyyy"             # Monitoring
    - "sk-app-web-portal-zzzz"         # Web UI
    - "sk-app-automation-aaaa"         # Automation scripts
```

### 4. Logowanie dostępu

Monitoruj logi:

```bash
# Szukaj błędnych prób
sudo journalctl -u easydns | grep "Unauthorized"

# Szukaj poprawnych dostępów
sudo journalctl -u easydns | grep "api_key_valid"
```

### 5. Rate limiting per klucz

(Przyszła funkcjonalność) Różne limity dla różnych kluczy:

```yaml
api:
  keys:
    - key: "sk-prod-xxxxxxxxxxxxxxxx"
      rate_limit: 1000  # 1000 req/min
    - key: "sk-dev-yyyyyyyyyyyyyyyy"
      rate_limit: 100   # 100 req/min
```

---

## Wyłączenie API-Key (opcjonalnie)

Jeśli nie chcesz wymagać API-Key, nie definiuj `keys` w konfiguracji:

```yaml
api:
  enabled: true
  listen: "0.0.0.0"
  port: 8080
  # keys: []  # Brak - API-Key nie wymagany
```

API będzie wtedy zabezpieczone tylko ACL + rate limiting.

---

## Migracja z ACL-only na API-Key

### Faza 1: Dodaj API-Key do konfiguracji

```yaml
api:
  keys:
    - "sk-prod-1234567890abcdef"
```

### Faza 2: Poinformuj klientów

Wyślij komunikat do zespołu:
- Klucz API jest teraz wymagany
- Każde żądanie musi zawierać nagłówek `X-API-Key`
- Deadline: 1 tydzień

### Faza 3: Restart API

```bash
sudo systemctl restart easydns
```

### Faza 4: Monitoruj

```bash
sudo journalctl -u easydns -f | grep -i "unauthorized"
```

---

## Troubleshooting

### "Invalid or missing API key" (401)

**Problem:** Klucz nie jest wysyłany lub jest nieprawidłowy

**Rozwiązanie:**
1. Sprawdzić czy klucz jest zdefiniowany w `config.yaml`
2. Sprawdzić czy nagłówek jest wysłany:
   ```bash
   curl -v -H "X-API-Key: sk-..." https://...
   ```
3. Sprawdzić logi:
   ```bash
   sudo journalctl -u easydns | grep "Unauthorized"
   ```

### "Forbidden" (403) mimo prawidłowego API-Key

**Problem:** API-Key jest poprawny, ale ACL odmawia dostępu

**Rozwiązanie:**
1. Sprawdzić ACL w konfiguracji
2. Upewnić się, że IP ma permisję `api`
3. Sprawdzić X-Forwarded-For jeśli za proxy

---

## Zaawansowane: Custom API-Key middleware

Aby implementować custom logikę (np. rate limiting per klucz), rozszerz `_api_key_middleware`:

```python
async def _api_key_middleware(self, request, handler):
    # ... istniejący kod ...
    
    if api_key in self._api_keys:
        # Custom logika
        request["api_key"] = api_key
        request["api_key_app"] = "terraform"  # np. identyfikacja aplikacji
    
    return await handler(request)
```

Następnie w handlerach:
```python
async def _handle_list_zones(self, request):
    app = request.get("api_key_app", "unknown")
    logger.info(f"Zones listed by {app}")
    # ...
```

---

## Podsumowanie

| Aspekt | Status |
|--------|--------|
| **API-Key Support** | ✅ Implementowana |
| **Nagłówki** | ✅ Authorization, X-API-Key |
| **Bezpieczeństwo** | ✅ HashSet lookup O(1) |
| **Logowanie** | ✅ W dziennikach systemowych |
| **Optymalizacja** | ✅ HashSet zamiast listy |
| **Dokumentacja** | ✅ Pełna |
| **Testowanie** | ✅ W test_api.py |

