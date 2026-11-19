# EasyDNS Panel

Panel webowy do zarządzania wieloma niezależnymi serwerami DNS przez REST API EasyDNS.
Napisany w Lua 5.4 (`.lhtml` — Lua osadzony w HTML) dla serwera HTTPD.

## Struktura

```
Panel/
├── data/              # baza SQLite (panel.db — tworzona automatycznie)
├── lib/
│   ├── db.lua         # warstwa SQLite (lsqlite3)
│   ├── auth.lua       # autentykacja, sesje, audit
│   ├── api.lua        # klient REST EasyDNS API (luasocket lub curl)
│   ├── servers.lua    # lista i konfiguracja serwerów DNS
│   └── layout.lua     # wspólny layout HTML + helpers
├── login.lhtml        # logowanie
├── logout.lhtml       # wylogowanie
├── index.lhtml        # dashboard (statystyki i strefy)
├── zones.lhtml        # zarządzanie strefami i rekordami
├── settings.lhtml     # zarządzanie serwerami i połączeniami API (tylko admin)
├── users.lhtml        # zarządzanie kontami (tylko admin)
└── audit.lhtml        # dziennik zdarzeń z filtrowaniem i paginacją
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
3. Przejdź do **Ustawienia** i skonfiguruj pierwszy serwer EasyDNS; kolejne dodaj przez **Dodaj serwer DNS**
4. Wybierz serwer na dashboardzie lub w zakładce **Strefy**; tam możesz zarządzać strefami i rekordami

> **Zmień hasło admina** po pierwszym logowaniu (zakładka Użytkownicy).

## Wiele serwerów DNS

- Lista serwerów jest wspólna dla wszystkich użytkowników panelu (bez podziału na tenantów).
- Tylko administratorzy mogą dodawać, zmieniać i usuwać konfiguracje serwerów oraz przeglądać ich klucze API.
- Każdy serwer ma własną nazwę, host, port, schemat HTTP/HTTPS, klucz API i ustawienie weryfikacji SSL.
- Dashboard i strefy dotyczą wyłącznie wybranego serwera. Panel nie replikuje zmian między serwerami.
- Wybór serwera jest przekazywany w URL (`server`) i formularzach, niezależnie dla każdej karty przeglądarki.
  Wejście bez identyfikatora wybiera pierwszy serwer według ID; nieistniejący identyfikator lub
  formularz zmiany rekordu bez serwera jest odrzucany zamiast kierowania operacji na inny serwer.
- Przy pierwszym uruchomieniu po aktualizacji dotychczasowe ustawienia API są automatycznie
  przenoszone do serwera **EasyDNS**. Użytkownicy i historia zdarzeń pozostają bez zmian.
- Usunięcie serwera usuwa tylko konfigurację w panelu, nie dane DNS. Można usunąć wszystkie serwery,
  a następnie dodać nowe w ustawieniach.
- Dziennik zdarzeń pozostaje wspólny dla panelu. Nowe wpisy zmian rekordów i konfiguracji zawierają ID,
  nazwę i adres docelowego serwera (bez klucza API).

## Role użytkowników

| Rola     | Opis                            |
|----------|---------------------------------|
| `viewer` | Tylko odczyt (dashboard, strefy) |
| `editor` | Odczyt + dodawanie/edycja rekordów |
| `admin`  | Pełny dostęp + zarządzanie kontami i serwerami |

## Bezpieczeństwo

- Hasła przechowywane jako **SHA-256** (bez soli — do użytku wewnętrznego)
- Sesje po stronie serwera (`httpd.session_*`)
- Cookie `DNSSID`: `HttpOnly`, `SameSite=Lax`, TTL 8h
- Historia działań jest dostępna wyłącznie w zakładce **Dziennik zdarzeń**
- Połączenie z API opcjonalnie przez HTTPS z weryfikacją certyfikatu

## Testy panelu

Z katalogu `Panel/` uruchom `lua tests/multi_server.lua` (wymaga `lsqlite3`).
Testy używają baz SQLite w pamięci i atrap API/HTTPD, bez połączeń z serwerami DNS.
