# EasyDNS Panel

Panel webowy do zarządzania serwerem DNS przez REST API EasyDNS.
Napisany w Lua 5.4 (`.lhtml` — Lua osadzony w HTML) dla serwera HTTPD.

## Struktura

```
Panel/
├── data/              # baza SQLite (panel.db — tworzona automatycznie)
├── lib/
│   ├── db.lua         # warstwa SQLite (lsqlite3)
│   ├── auth.lua       # autentykacja, sesje, audit
│   ├── api.lua        # klient REST EasyDNS API (luasocket lub curl)
│   └── layout.lua     # wspólny layout HTML + helpers
├── login.lhtml        # logowanie
├── logout.lhtml       # wylogowanie
├── index.lhtml        # dashboard (statystyki, strefy, audit)
├── zones.lhtml        # zarządzanie strefami i rekordami
├── settings.lhtml     # ustawienia połączenia z API
├── users.lhtml        # zarządzanie kontami (tylko admin)
└── audit.lhtml        # pełny audit log z filtrowaniem i paginacją
```

## Wymagania

- serwer **HTTPD** z modułem Lua 5.4
- Lua: `lsqlite3` (lub `luarocks install lsqlite3`)
- Lua: `luasocket` + `luasec` (lub fallback na `curl` w PATH)

## Konfiguracja HTTPD

Ustaw `document_root` lub alias tak, żeby `/panel/` wskazywał na katalog `Panel/`:

```
# httpd.conf (przykład)
route /panel   /home/mkwiatkowski/Projects/EasyDNS/Panel
```

lub umieść katalog w `www/panel/` serwera.

## Pierwsze uruchomienie

1. Otwórz `http://localhost:<port>/panel/`
2. Zaloguj się: **admin** / **admin**
3. Przejdź do **Ustawienia** i skonfiguruj połączenie z API EasyDNS
4. Zarządzaj strefami w zakładce **Strefy**

> **Zmień hasło admina** po pierwszym logowaniu (zakładka Użytkownicy).

## Role użytkowników

| Rola     | Opis                            |
|----------|---------------------------------|
| `viewer` | Tylko odczyt (dashboard, strefy) |
| `editor` | Odczyt + dodawanie/edycja rekordów |
| `admin`  | Pełny dostęp + zarządzanie kontami |

## Bezpieczeństwo

- Hasła przechowywane jako **SHA-256** (bez soli — do użytku wewnętrznego)
- Sesje po stronie serwera (`httpd.session_*`)
- Cookie `DNSSID`: `HttpOnly`, `SameSite=Lax`, TTL 8h
- Wszystkie akcje zapisywane w **audit logu**
- Połączenie z API opcjonalnie przez HTTPS z weryfikacją certyfikatu
