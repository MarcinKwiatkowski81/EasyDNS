-- Panel/lib/db.lua
-- SQLite helper: otwiera (lub tworzy) bazę, inicjuje schemat, zwraca db.
-- Użycie: local db = require("lib.db")

local sqlite3 = require("lsqlite3")
local M = {}

-- Ścieżka do bazy względem katalogu skryptu
local function db_path()
    local dir = httpd.script_dir()
    -- script_dir() wskazuje na katalog bieżącego .lhtml / .lua
    -- baza leży w Panel/data/panel.db
    return dir .. "../data/panel.db"
end

-- Jednorazowa inicjalizacja schematu
local function init_schema(db)
    db:exec([[
        PRAGMA journal_mode = WAL;
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    NOT NULL UNIQUE,
            password_hash TEXT  NOT NULL,          -- SHA-256 hex
            role        TEXT    NOT NULL DEFAULT 'viewer',
            created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            last_login  INTEGER
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            username   TEXT,
            action     TEXT NOT NULL,
            detail     TEXT
        );
    ]])

    local rc = db:exec([[
        BEGIN IMMEDIATE;
        INSERT OR IGNORE INTO settings(key,value) VALUES
            ('api_host',    'localhost'),
            ('api_port',    '8443'),
            ('api_scheme',  'http'),
            ('api_key',     ''),
            ('verify_ssl',  '0');
        CREATE TABLE IF NOT EXISTS dns_servers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            host       TEXT NOT NULL,
            port       INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
            scheme     TEXT NOT NULL CHECK(scheme IN ('http','https')),
            api_key    TEXT NOT NULL DEFAULT '',
            verify_ssl INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO dns_servers(name,host,port,scheme,api_key,verify_ssl)
        SELECT 'EasyDNS', host.value, CAST(port.value AS INTEGER),
               scheme.value, api_key.value, CAST(verify_ssl.value AS INTEGER)
        FROM settings host, settings port, settings scheme,
             settings api_key, settings verify_ssl
        WHERE host.key='api_host' AND port.key='api_port'
          AND scheme.key='api_scheme' AND api_key.key='api_key'
          AND verify_ssl.key='verify_ssl'
          AND NOT EXISTS (SELECT 1 FROM settings WHERE key='dns_servers_migrated');
        INSERT OR IGNORE INTO settings(key,value) VALUES('dns_servers_migrated','1');
        DELETE FROM settings WHERE key IN
            ('api_host','api_port','api_scheme','api_key','verify_ssl');
        COMMIT;
    ]])
    if rc ~= sqlite3.OK then
        local err = db:errmsg()
        db:exec("ROLLBACK")
        error("DNS server migration error: " .. tostring(err))
    end

    -- Domyślny administrator (hasło: admin — SHA-256)
    -- echo -n "admin" | sha256sum → 8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918
    db:exec([[
        INSERT OR IGNORE INTO users(username, password_hash, role)
        VALUES ('admin',
                '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918',
                'admin');
    ]])
end

local _db_cache = nil

function M.open()
    if _db_cache and _db_cache:isopen() then
        return _db_cache
    end
    local path = db_path()
    -- upewnij się, że katalog istnieje
    os.execute("mkdir -p " .. path:match("(.+)/[^/]+$"))
    local db, err = sqlite3.open(path)
    if not db then
        error("Nie można otworzyć bazy SQLite: " .. tostring(err))
    end
    init_schema(db)
    _db_cache = db
    return db
end

-- Pomocnik: exec z parametrami (stmt)
function M.exec(db, sql, params)
    local stmt = db:prepare(sql)
    if not stmt then
        error("SQL prepare error: " .. tostring(db:errmsg()) .. "\nSQL: " .. sql)
    end
    if params then
        for i, v in ipairs(params) do
            stmt:bind(i, v)
        end
    end
    local rc = stmt:step()
    stmt:finalize()
    if rc ~= sqlite3.DONE and rc ~= sqlite3.ROW then
        error("SQL exec error: " .. tostring(db:errmsg()))
    end
end

-- Pomocnik: SELECT → array of rows (jako tables)
function M.query(db, sql, params)
    local stmt = db:prepare(sql)
    if not stmt then
        error("SQL prepare error: " .. tostring(db:errmsg()))
    end
    if params then
        for i, v in ipairs(params) do
            stmt:bind(i, v)
        end
    end
    local rows = {}
    for row in stmt:nrows() do
        rows[#rows + 1] = row
    end
    stmt:finalize()
    return rows
end

-- Pomocnik: SELECT → pierwsza kolumna pierwszego wiersza (lub nil)
function M.scalar(db, sql, params)
    local stmt = db:prepare(sql)
    if not stmt then return nil end
    if params then
        for i, v in ipairs(params) do stmt:bind(i, v) end
    end
    local val = nil
    if stmt:step() == sqlite3.ROW then
        val = stmt:get_value(0)
    end
    stmt:finalize()
    return val
end

return M
