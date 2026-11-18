# 📖 Indeks dokumentacji REST API EasyDNS

## Szybki dostęp do dokumentacji

### 🚀 Chcę szybko zacząć

1. Czytaj: [API_SETUP_GUIDE.md](./API_SETUP_GUIDE.md) - Instalacja i konfiguracja
2. Kod: [config.yaml](./config.yaml) - Linia 29-33 (sekcja `api:`)
3. Test: `python3 test_api.py` - Przetestuj API

### 📚 Potrzebuję pełnej dokumentacji

1. Czytaj: [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) - Wszystkie endpointy
2. Czytaj: [ARCHITECTURE.md](./ARCHITECTURE.md) - Jak API działa
3. Kod: [dns_server/api.py](./dns_server/api.py) - Implementacja

### 💻 Chcę pisać kod

Przykłady w [API_DOCUMENTATION.md](./API_DOCUMENTATION.md):
- **Python**: Sekcja "Python + requests" (kopiuj kod)
- **bash/curl**: Sekcja "bash + curl" (kopiuj komendy)
- **JavaScript**: Sekcja "JavaScript/Node.js" (kopiuj kod)

Plik test'owy: [test_api.py](./test_api.py) - Kompletne przykłady

### 🔧 Mam problem

1. Sprawdź: [API_SETUP_GUIDE.md](./API_SETUP_GUIDE.md) - Troubleshooting
2. Sprawdź: [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) - Troubleshooting
3. Uruchom: `python3 test_api.py` - Diagnostyka

### 📋 Coś się zmienił

Czytaj: [CHANGELOG_API.md](./CHANGELOG_API.md) - Co się zmieniło

### ✅ Checklist

Czytaj: [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md) - Podsumowanie

---

## 📁 Struktura dokumentacji

```
EasyDNS/
├── 📄 README.md                      # Główny README (zawiera sekcję API)
├── 📄 API_DOCUMENTATION.md           # ⭐ Pełna dokumentacja API
├── 📄 API_SETUP_GUIDE.md             # ⭐ Przewodnik instalacji
├── 📄 ARCHITECTURE.md                # Diagram architektury
├── 📄 CHANGELOG_API.md               # Historia zmian
├── 📄 IMPLEMENTATION_SUMMARY.md       # Podsumowanie implementacji
├── 📄 API_INDEX.md                   # (ten plik) Indeks
│
├── 🐍 test_api.py                    # Skrypt testowy
│
├── dns_server/
│   ├── api.py                        # ⭐ Implementacja REST API
│   ├── acl.py                        # ACL z permisją 'api'
│   ├── zone.py                       # Zone z add_record/delete_record
│   ├── __main__.py                   # Inicjalizacja API
│   └── requirements.txt               # Zależności (aiohttp)
│
└── config.yaml                       # Konfiguracja (sekcja api:)
```

---

## 🔗 Mapowanie dokumentów

### API_DOCUMENTATION.md
Zakres: **Wszystkie operacje na API**

Zawiera:
- Przegląd API
- Autentykacja (ACL, HTTPS)
- Wszystkie 7 endpointów (get/create/update/delete)
- Formaty request/response
- Kody statusu HTTP
- Kompleksowe przykłady (3 języki)
- Rate limiting
- Generowanie certyfikatów
- Best practices
- Troubleshooting

Użyj gdy: Szukasz informacji o konkretnym endpoincie

### API_SETUP_GUIDE.md
Zakres: **Instalacja, konfiguracja, uruchomienie, testy**

Zawiera:
- Wymagania systemowe
- Instalacja zależności
- Konfiguracja (HTTP/HTTPS)
- Konfiguracja ACL
- Uruchomienie (manual/systemd)
- Wszystkie scenariusze testowe
- Test suite (Python)
- Troubleshooting (10 problemów)

Użyj gdy: Stawiasz API po raz pierwszy

### ARCHITECTURE.md
Zakres: **Jak API działa wewnętrznie**

Zawiera:
- ASCII art diagramy
- Warstwy architektury
- Middleware'y (ACL, rate limiting)
- Endpointy i operacje
- Modele bezpieczeństwa
- Model współbieżności (asyncio)
- Cache + invalidation

Użyj gdy: Chcesz zrozumieć design

### CHANGELOG_API.md
Zakres: **Co się zmieniło w wersji 1.1.0**

Zawiera:
- Lista wszystkich zmian
- Nowe endpointy
- Nowe pliki
- Nowe metody
- Zmiany w konfiguracji
- Migracja

Użyj gdy: Aktualizujesz z poprzedniej wersji

### IMPLEMENTATION_SUMMARY.md
Zakres: **Podsumowanie całej implementacji**

Zawiera:
- Co zostało dodane
- Wszystkie zmiany w kodzie
- Checklist funkcji
- Status produkcji
- Pliki zmienione/dodane
- Następne kroki

Użyj gdy: Chcesz widzieć big picture

### test_api.py
Zakres: **Testowanie API**

Zawiera:
- 9 testów (health, zones, records, crud, stats, rate limit)
- Uruchamianie testów
- Diagnostyka

Uruchom: `python3 test_api.py`

---

## 🎯 Typowe scenariusze

### Scenario 1: "Chcę włączyć API"

1. Przeczytaj: [API_SETUP_GUIDE.md](./API_SETUP_GUIDE.md) - sekcja "Konfiguracja"
2. Edytuj: [config.yaml](./config.yaml) - zmień `api.enabled: true`
3. Uruchom: `python3 -m dns_server -c config.yaml`
4. Test: `curl http://localhost:8080/api/v1/health`

### Scenario 2: "Chcę dodać rekord przez API"

1. Przeczytaj: [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) - sekcja "Dodaj rekord"
2. Kopiuj: Przykład POST w sekcji "Przykłady użycia"
3. Dostosuj: Zmień zone, name, type, rdata
4. Wyślij: `curl -X POST ...`

### Scenario 3: "Muszę HTTPS"

1. Przeczytaj: [API_SETUP_GUIDE.md](./API_SETUP_GUIDE.md) - sekcja "(Opcjonalnie) Włącz HTTPS"
2. Generuj: Certyfikat (self-signed lub Let's Encrypt)
3. Edytuj: [config.yaml](./config.yaml) - dodaj cert_file, key_file
4. Uruchom: Serwer z HTTPS

### Scenario 4: "Dostaję 403 Forbidden"

1. Przeczytaj: [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) - sekcja "Autentykacja"
2. Sprawdź: [config.yaml](./config.yaml) - ACL zawiera twój IP?
3. Dodaj: `api` do permisji w ACL
4. Restart: Serwer

### Scenario 5: "Chcę zintegrować z Python'em"

1. Przeczytaj: [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) - sekcja "Python + requests"
2. Zainstaluj: `pip install requests`
3. Kopiuj: Kod z dokumentacji
4. Dostosuj: Zmień API_BASE, ZONE
5. Uruchom: Python script

### Scenario 6: "Uruchamiam testy"

1. Zainstaluj: `pip install requests`
2. Uruchom: `python3 test_api.py`
3. Czytaj: Output diagnostyki

### Scenario 7: "Chcę rate limiting zmienić"

1. Czytaj: [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) - sekcja "Rate limiting"
2. Edytuj: [dns_server/api.py](./dns_server/api.py) - linie 30-31
3. Zmień: RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW
4. Restart: Serwer

---

## 📊 Statystyka dokumentacji

| Plik | LOC | Typ | Opis |
|------|-----|-----|------|
| API_DOCUMENTATION.md | 500 | Referencyjna | Pełna dokumentacja |
| API_SETUP_GUIDE.md | 300 | Przewodnik | Instalacja i konfiguracja |
| ARCHITECTURE.md | 250 | Referencyjna | Diagram + design |
| CHANGELOG_API.md | 200 | Referencyjna | Historia zmian |
| IMPLEMENTATION_SUMMARY.md | 250 | Podsumowanie | Checklist + status |
| API_INDEX.md | 150 | Nawigacja | (ten plik) |
| test_api.py | 400 | Kod | Test suite |
| dns_server/api.py | 400 | Kod | Implementacja |

**Łącznie:** 2,450 linii dokumentacji + testy + implementacja

---

## 🚀 Quick Links

| Co chcesz zrobić | Przejdź do |
|-----------------|-----------|
| Włączyć API | [Konfiguracja](./API_SETUP_GUIDE.md#1-edytuj-configyaml) |
| Zobaczyć endpointy | [Dokumentacja](./API_DOCUMENTATION.md#endpointy) |
| Napisać skrypt | [Przykłady](./API_DOCUMENTATION.md#przykłady-użycia) |
| Uruchomić testy | [test_api.py](./test_api.py) |
| Zrozumieć design | [Architektura](./ARCHITECTURE.md) |
| Skonfigurować HTTPS | [Certyfikaty](./API_SETUP_GUIDE.md#4-opcjonalnie-włącz-https) |
| Rozwiązać problem | [Troubleshooting](./API_SETUP_GUIDE.md#troubleshooting) |
| Zobaczyć zmiany | [Changelog](./CHANGELOG_API.md) |
| ACL + Rate limiting | [Bezpieczeństwo](./API_DOCUMENTATION.md#rate-limiting) |

---

## 📞 Support

Problemy?

1. Sprawdzić dokumentację (index powyżej)
2. Uruchomić `python3 test_api.py` (diagnostyka)
3. Przeczytać Troubleshooting (każdy dokument ma sekcję)
4. Sprawdzić logi: `sudo journalctl -u easydns -f`
5. Otwórz GitHub issue: https://github.com/MarcinKwiatkowski81/EasyDNS/issues

---

## ✅ Verification Checklist

Po włączeniu API sprawdzić:

```bash
# 1. API dostępne?
curl http://localhost:8080/api/v1/health
# ✓ {"status": "ok"}

# 2. ACL działa?
# Z innego IP:
curl http://localhost:8080/api/v1/zones
# ✗ {"error": "Forbidden", "message": "No API access"}

# 3. Strefy dostępne?
curl http://localhost:8080/api/v1/zones
# ✓ {"zones": [...]}

# 4. Rekordy dostępne?
curl http://localhost:8080/api/v1/zones/example.com/records
# ✓ {"zone": "example.com.", "records": [...]}

# 5. Rate limiting działa?
for i in {1..15}; do curl http://localhost:8080/api/v1/health; done
# ✓ 10x 200 OK, 5x 429 Too Many Requests

# 6. HTTPS dostępne (jeśli włączony)?
curl -k https://localhost:8443/api/v1/health
# ✓ {"status": "ok"}
```
