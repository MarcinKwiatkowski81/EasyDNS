-- Panel/lib/auth.lua
-- Autentykacja i autoryzacja panelu.

local M = {}

-- SHA-256 przez openssl (stdlib nie ma SHA-256)
function M.sha256(s)
    local h = io.popen("printf '%s' " .. string.format("%q", s) .. " | sha256sum 2>/dev/null")
    if not h then return nil end
    local out = h:read("*l"); h:close()
    return out and out:match("^%x+")
end

-- ── Sprawdzenie sesji ──────────────────────────────────────────────────────
-- Zwraca username lub nil
function M.current_user()
    local sid = httpd.get_cookie("DNSSID")
    if not sid or sid == "" then return nil end
    return httpd.session_get(sid)
end

-- Przekierowanie na login jeśli nie zalogowany; opcjonalnie sprawdza rolę
function M.require_login(role)
    local user = M.current_user()
    if not user then
        httpd.redirect("/panel/login.lhtml")
        return nil
    end
    -- sprawdzenie roli odbywa się przez wywołującego
    return user
end

-- ── Login ──────────────────────────────────────────────────────────────────
function M.login(db, dbm, username, password)
    local hash = M.sha256(password)
    if not hash then return nil, "Błąd hasła" end
    local rows = dbm.query(db,
        "SELECT username, role FROM users WHERE username=? AND password_hash=?",
        { username, hash })
    if #rows == 0 then return nil, "Nieprawidłowy login lub hasło" end
    dbm.exec(db,
        "UPDATE users SET last_login=strftime('%s','now') WHERE username=?",
        { username })
    return rows[1], nil
end

-- ── Pobranie roli ─────────────────────────────────────────────────────────
function M.get_role(db, dbm, username)
    return dbm.scalar(db,
        "SELECT role FROM users WHERE username=?", { username }) or "viewer"
end

-- ── Audit log ─────────────────────────────────────────────────────────────
function M.audit(db, dbm, username, action, detail)
    local ok, err = pcall(function()
        dbm.exec(db,
            "INSERT INTO audit_log(username,action,detail) VALUES(?,?,?)",
            { username or "?", action, detail or "" })
    end)
    if not ok then
        httpd.log("warn", "audit log error: " .. tostring(err))
    end
end

return M
