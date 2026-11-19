-- Panel/lib/api.lua
-- Klient REST dla EasyDNS API.
-- Używa tylko stdlib: socket (luasocket) + http.

local M = {}

-- ── Pobranie konfiguracji API z bazy ──────────────────────────────────────
function M.config(db, dbm, server_id, required)
    if server_id == nil and not required then
        server_id = dbm.scalar(db, "SELECT id FROM dns_servers ORDER BY id LIMIT 1")
        if not server_id then return nil, "Brak serwerów DNS. Dodaj serwer w ustawieniach." end
    end
    local id = tonumber(server_id)
    if not id or id < 1 or id % 1 ~= 0 then
        return nil, "Nieprawidłowy identyfikator serwera DNS."
    end
    local cfg = dbm.query(db, "SELECT * FROM dns_servers WHERE id=?", { id })[1]
    if not cfg then return nil, "Serwer DNS nie istnieje. Wybierz serwer ponownie." end
    cfg.verify_ssl = tonumber(cfg.verify_ssl) == 1
    return cfg
end

-- ── Niskopoziomowe HTTP przez luasocket ───────────────────────────────────
local function http_request(cfg, method, path, body)
    local ok, http
    if cfg.scheme == "https" then
        ok, http = pcall(require, "ssl.https")
        if not ok then
            -- fallback: curl
            return M._curl_request(cfg, method, path, body)
        end
    else
        ok, http = pcall(require, "socket.http")
        if not ok then
            return M._curl_request(cfg, method, path, body)
        end
    end

    local ltn12 = require("ltn12")
    local url = string.format("%s://%s:%d%s",
        cfg.scheme, cfg.host, cfg.port, path)

    local req_headers = {
        ["Content-Type"]  = "application/json",
        ["Accept"]        = "application/json",
    }
    if cfg.api_key and cfg.api_key ~= "" then
        req_headers["X-API-Key"] = cfg.api_key
    end

    local body_src = nil
    local body_len = 0
    if body and body ~= "" then
        body_src = ltn12.source.string(body)
        body_len = #body
        req_headers["Content-Length"] = tostring(body_len)
    end

    local resp_body = {}
    local resp, status, resp_headers
    if cfg.scheme == "https" then
        resp, status, resp_headers = http.request {
            url     = url,
            method  = method,
            headers = req_headers,
            source  = body_src,
            sink    = ltn12.sink.table(resp_body),
            verify  = cfg.verify_ssl and "peer" or "none",
        }
    else
        resp, status, resp_headers = http.request {
            url     = url,
            method  = method,
            headers = req_headers,
            source  = body_src,
            sink    = ltn12.sink.table(resp_body),
        }
    end

    if not resp and type(status) == "string" then
        return nil, status
    end

    local text = table.concat(resp_body)
    return { status = status, body = text }, nil
end

-- ── Fallback przez curl (jeśli brak luasocket) ────────────────────────────
function M._curl_request(cfg, method, path, body)
    local url = string.format("%s://%s:%d%s",
        cfg.scheme, cfg.host, cfg.port, path)

    local args = { "curl", "-s", "-w", "\n__STATUS__%{http_code}" }
    args[#args+1] = "-X"; args[#args+1] = method
    args[#args+1] = "-H"; args[#args+1] = "Content-Type: application/json"
    args[#args+1] = "-H"; args[#args+1] = "Accept: application/json"
    if cfg.api_key and cfg.api_key ~= "" then
        args[#args+1] = "-H"
        args[#args+1] = "X-API-Key: " .. cfg.api_key
    end
    if not cfg.verify_ssl then
        args[#args+1] = "-k"
    end
    if body and body ~= "" then
        args[#args+1] = "-d"
        args[#args+1] = body
    end
    args[#args+1] = url

    -- zbuduj polecenie (escapuj każdy arg)
    local parts = {}
    for _, a in ipairs(args) do
        parts[#parts+1] = string.format("%q", a)
    end
    local cmd = table.concat(parts, " ")

    local h = io.popen(cmd .. " 2>/dev/null")
    if not h then return nil, "curl unavailable" end
    local out = h:read("*a"); h:close()

    local body_part, status_str = out:match("^(.-)%s*__STATUS__(%d+)%s*$")
    local status = tonumber(status_str) or 0
    return { status = status, body = body_part or "" }, nil
end

-- ── JSON: prosty dekoder (obsługuje zagnieżdżone obiekty i tablice) ────────
local json = {}

local function skip_ws(s, i)
    while i <= #s and s:sub(i,i):match("%s") do i = i + 1 end
    return i
end

local function parse_value(s, i)
    i = skip_ws(s, i)
    local c = s:sub(i,i)
    if c == '"' then
        local j = i + 1
        local buf = {}
        while j <= #s do
            local ch = s:sub(j,j)
            if ch == '"' then
                return table.concat(buf), j + 1
            elseif ch == '\\' then
                j = j + 1
                local esc = s:sub(j,j)
                local map = { n="\n", t="\t", r="\r", ['"']='"', ['\\']='\\', ['/']='/' }
                buf[#buf+1] = map[esc] or esc
            else
                buf[#buf+1] = ch
            end
            j = j + 1
        end
        return table.concat(buf), j
    elseif c == '{' then
        local obj = {}; local j = i + 1
        j = skip_ws(s, j)
        if s:sub(j,j) == '}' then return obj, j+1 end
        while j <= #s do
            j = skip_ws(s, j)
            local key; key, j = parse_value(s, j)
            j = skip_ws(s, j)
            j = j + 1  -- ':'
            local val; val, j = parse_value(s, j)
            obj[key] = val
            j = skip_ws(s, j)
            local sep = s:sub(j,j); j = j + 1
            if sep == '}' then return obj, j end
        end
        return obj, j
    elseif c == '[' then
        local arr = {}; local j = i + 1
        j = skip_ws(s, j)
        if s:sub(j,j) == ']' then return arr, j+1 end
        while j <= #s do
            local val; val, j = parse_value(s, j)
            arr[#arr+1] = val
            j = skip_ws(s, j)
            local sep = s:sub(j,j); j = j + 1
            if sep == ']' then return arr, j end
        end
        return arr, j
    elseif s:sub(i, i+3) == 'true'  then return true,  i+4
    elseif s:sub(i, i+4) == 'false' then return false, i+5
    elseif s:sub(i, i+3) == 'null'  then return nil,   i+4
    else
        local num_str = s:match("^-?%d+%.?%d*[eE]?[+-]?%d*", i)
        if num_str then return tonumber(num_str), i + #num_str end
        return nil, i + 1
    end
end

function json.decode(s)
    if not s or s == "" then return nil end
    local ok, val = pcall(function()
        local v, _ = parse_value(s, 1)
        return v
    end)
    if ok then return val end
    return nil
end

function json.encode(v, indent)
    return httpd.json_encode(v)
end

M.json = json

-- ── Publiczne metody API ───────────────────────────────────────────────────

local function api_call(cfg, method, path, payload)
    local body = nil
    if payload then
        body = json.encode(payload)
    end
    local resp, err = http_request(cfg, method, path, body)
    if err then
        return nil, err
    end
    local data = json.decode(resp.body)
    return { status = resp.status, data = data, raw = resp.body }, nil
end

function M.health(cfg)
    return api_call(cfg, "GET", "/api/v1/health", nil)
end

function M.zones(cfg)
    return api_call(cfg, "GET", "/api/v1/zones", nil)
end

function M.add_zone(cfg, name)
    return api_call(cfg, "POST", "/api/v1/zones", { name = name })
end

function M.update_zone(cfg, old_name, new_name)
    local path = "/api/v1/zones/" .. httpd.urlencode(old_name)
    return api_call(cfg, "PUT", path, { name = new_name })
end

function M.delete_zone(cfg, name)
    local path = "/api/v1/zones/" .. httpd.urlencode(name)
    return api_call(cfg, "DELETE", path, nil)
end

function M.records(cfg, zone, filter_name, filter_type)
    local path = "/api/v1/zones/" .. httpd.urlencode(zone) .. "/records"
    local qs = {}
    if filter_name and filter_name ~= "" then
        qs[#qs+1] = "name=" .. httpd.urlencode(filter_name)
    end
    if filter_type and filter_type ~= "" then
        qs[#qs+1] = "type=" .. httpd.urlencode(filter_type)
    end
    if #qs > 0 then path = path .. "?" .. table.concat(qs, "&") end
    return api_call(cfg, "GET", path, nil)
end

function M.add_record(cfg, zone, name, rtype, ttl, rdata)
    local path = "/api/v1/zones/" .. httpd.urlencode(zone) .. "/records"
    return api_call(cfg, "POST", path, {
        name  = name,
        type  = rtype,
        ttl   = tonumber(ttl) or 300,
        rdata = rdata,
    })
end

function M.update_record(cfg, zone, uid, name, rtype, ttl, rdata)
    local path = "/api/v1/zones/" .. httpd.urlencode(zone) .. "/records"
    return api_call(cfg, "PUT", path, {
        uid   = uid,
        name  = name,
        type  = rtype,
        ttl   = tonumber(ttl) or 300,
        rdata = rdata,
    })
end

function M.delete_record(cfg, zone, uid)
    local path = "/api/v1/zones/" .. httpd.urlencode(zone) .. "/records"
    return api_call(cfg, "DELETE", path, { uid = uid })
end

function M.stats(cfg)
    return api_call(cfg, "GET", "/api/v1/stats", nil)
end

return M
