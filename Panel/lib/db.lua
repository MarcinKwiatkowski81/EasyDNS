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

    -- Domyślne ustawienia API
    db:exec([[
        INSERT OR IGNORE INTO settings(key,value) VALUES
            ('api_host',    'localhost'),
            ('api_port',    '8443'),
            ('api_scheme',  'http'),
            ('api_key',     ''),
            ('verify_ssl',  '0');
    ]])

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
