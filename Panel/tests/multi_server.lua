local sqlite3 = require("lsqlite3")
local api = require("lib.api")
local servers = require("lib.servers")
local layout = require("lib.layout")

local function equal(actual, expected)
    assert(actual == expected, string.format("expected %s, got %s", tostring(expected), tostring(actual)))
end

local function contains(text, expected)
    assert(text:find(expected, 1, true), "missing: " .. expected)
end

local function escape(value)
    return (tostring(value):gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;")
        :gsub('"', "&quot;"):gsub("'", "&#39;"))
end

httpd = { script_dir = function() return "/unused/lib/" end }

local function initialize(db)
    local original_open, original_execute = sqlite3.open, os.execute
    local original_script_dir = httpd.script_dir
    httpd.script_dir = function() return "/unused/lib/" end
    sqlite3.open = function() return db end
    os.execute = function() return true end
    package.loaded["lib.db"] = nil
    local dbm = require("lib.db")
    local ok, err = pcall(dbm.open)
    sqlite3.open, os.execute = original_open, original_execute
    httpd.script_dir = original_script_dir
    assert(ok, err)
    return dbm
end

local db = sqlite3.open_memory()
assert(db:exec([[
    CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    INSERT INTO settings VALUES ('api_host','legacy.example'),('api_port','9443'),
        ('api_scheme','https'),('api_key','legacy-key'),('verify_ssl','1');
]]) == sqlite3.OK)
local dbm = initialize(db)
local first = assert(api.config(db, dbm))
equal(first.host, "legacy.example")
equal(first.port, 9443)
equal(first.scheme, "https")
equal(first.api_key, "legacy-key")
equal(first.verify_ssl, true)
equal(dbm.scalar(db, "SELECT COUNT(*) FROM settings WHERE key='api_key'"), 0)
dbm.exec(db, "INSERT INTO audit_log(username,action,detail) VALUES('admin','legacy_event','retained')")
dbm = initialize(db)
equal(#servers.list(db, dbm), 1)
equal(dbm.scalar(db, "SELECT detail FROM audit_log WHERE action='legacy_event'"), "retained")

local other_db = sqlite3.open_memory()
local other_dbm = initialize(other_db)
local fresh = assert(api.config(other_db, other_dbm))
equal(fresh.host, "localhost")
equal(fresh.port, 8443)
equal(fresh.verify_ssl, false)
other_db:close()
package.loaded["lib.db"] = dbm

local second_id = assert(servers.save(db, dbm, {
    name = "Secondary <DNS>", api_host = "second.example", api_port = "8081",
    api_scheme = "http", api_key = "second-key",
}))
local second = assert(api.config(db, dbm, tostring(second_id)))
equal(second.api_key, "second-key")
equal(second.verify_ssl, false)
for _, id in ipairs({ "", "abc", "0", "-1", "1.5", "999" }) do
    local cfg, err = api.config(db, dbm, id)
    equal(cfg, nil)
    assert(err)
end
equal(api.config(db, dbm, nil, true), nil)
for _, changes in ipairs({
    { api_port = "65536" }, { api_port = "1.5" }, { api_scheme = "ftp" },
    { api_host = "http://bad.example" }, { name = "" },
}) do
    local form = { name = "Invalid", api_host = "host", api_port = "80", api_scheme = "http" }
    for k, v in pairs(changes) do form[k] = v end
    local id, err = servers.save(db, dbm, form)
    equal(id, nil)
    assert(err)
end
equal(#servers.list(db, dbm), 2)

local function compile(path)
    local file = assert(io.open(path))
    local source = file:read("*a")
    file:close()
    local parts, pos = {}, 1
    while true do
        local start = source:find("<%", pos, true)
        if not start then
            parts[#parts+1] = "httpd.write(" .. string.format("%q", source:sub(pos)) .. ")"
            break
        end
        parts[#parts+1] = "httpd.write(" .. string.format("%q", source:sub(pos, start-1)) .. ")"
        local stop = assert(source:find("%>", start+2, true))
        local code = source:sub(start+2, stop-1)
        if code:sub(1,2) == "--" then
            -- LHTML comments do not generate output.
        elseif code:sub(1,1) == "=" then
            parts[#parts+1] = "httpd.write(httpd.escape_html(" .. code:sub(2) .. "))"
        elseif code:sub(1,1) == "!" then
            parts[#parts+1] = "httpd.write(" .. code:sub(2) .. ")"
        else
            parts[#parts+1] = code
        end
        pos = stop+2
    end
    return assert(load(table.concat(parts, "\n"), "@" .. path))
end

local pages = {}
for _, page in ipairs({ "index", "zones", "settings", "audit", "users", "login", "logout" }) do
    pages[page] = compile(page .. ".lhtml")
end

local requests = {}
local function request(cfg, method, path)
    requests[#requests+1] = { id = cfg.id, host = cfg.host, key = cfg.api_key, method = method, path = path }
    local body = "{}"
    if path == "/api/v1/zones" then
        body = '{"zones":[{"name":"shared.example","records_count":1}]}'
    elseif path:find("/records", 1, true) then
        body = '{"records":[{"uid":"same-uid","name":"www","type":"A","ttl":300,"rdata":{"value":"192.0.2.1"}}]}'
    end
    return { status = 200, body = body }
end

-- Keep real API methods/JSON decoding, substituting only the HTTP transport.
local original_curl = api._curl_request
api._curl_request = request
local original_socket, original_https = package.loaded["socket.http"], package.loaded["ssl.https"]
package.loaded["socket.http"], package.loaded["ssl.https"] = nil, nil
package.preload["socket.http"] = function() error("test transport") end
package.preload["ssl.https"] = function() error("test transport") end

local function render(page, query, form, username)
    query = query or {}
    local output, status, redirect = {}, 200, nil
    requests = {}
    httpd = {
        get_cookie = function() return "test-session" end,
        session_get = function() return username or "admin" end,
        method = function() return form and "POST" or "GET" end,
        get_param = function(key) return query[key] end,
        body = function() return "" end,
        parse_form = function() return form end,
        escape_html = escape,
        urlencode = function(s) return (s:gsub("([^%w_.~-])", function(c) return string.format("%%%02X", c:byte()) end)) end,
        json_encode = function() return "{}" end,
        status = function(code) status = code end,
        redirect = function(url) redirect = url end,
        write = function(text) output[#output+1] = tostring(text) end,
        log = function(_, msg) error(msg) end,
    }
    pages[page]()
    return table.concat(output), status, redirect
end

for _, id in ipairs({ first.id, second.id, first.id }) do
    local html = render("index", { server = tostring(id) })
    contains(html, "/panel/zones.lhtml?server=" .. id .. "&amp;zone=shared.example")
    for _, req in ipairs(requests) do equal(req.id, id) end
end
api._curl_request = function(cfg, method, path)
    if cfg.id == second.id then
        requests[#requests+1] = { id = cfg.id }
        return nil, "selected server offline"
    end
    return request(cfg, method, path)
end
contains(render("index", { server = tostring(second.id) }), "selected server offline")
equal(#requests, 1)
equal(requests[1].id, second.id)
api._curl_request = request
local html = render("zones", { server = tostring(second.id), zone = "shared.example", q = "www", type = "A" })
contains(html, 'name="server" value="' .. second.id .. '"')
local _, target_fields = html:gsub('name="server" value="' .. second.id .. '"', "")
equal(target_fields, 3)
contains(html, "Secondary &lt;DNS&gt;")
for _, req in ipairs(requests) do
    equal(req.id, second.id)
    equal(req.host, "second.example")
    equal(req.key, "second-key")
end
contains(requests[2].path, "name=www&type=A")
for _, action in ipairs({ "add", "update", "delete" }) do
    render("zones", {}, { server = tostring(second.id), action = action,
        zone = "shared.example", uid = "same-uid", name = "www", rtype = "A", rdata_value = "192.0.2.2" })
    equal(requests[1].id, second.id)
    equal(requests[1].method, ({ add = "POST", update = "PUT", delete = "DELETE" })[action])
    local detail = dbm.scalar(db, "SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1")
    contains(detail, "server_id=" .. second.id)
    assert(not detail:find("second-key", 1, true))
end
for _, case in ipairs({
    { query = {}, form = { action = "delete", zone = "shared.example", uid = "same-uid" } },
    { query = { server = tostring(first.id) }, form = { server = tostring(second.id), action = "delete" } },
    { query = { server = "999" } },
}) do
    local _, status = render("zones", case.query, case.form)
    equal(status, 400)
    equal(#requests, 0)
end

dbm.exec(db, "INSERT INTO users(username,password_hash,role) VALUES('reader','unused','viewer')")
for _, form in ipairs({
    { action = "add_server", name = "Unauthorized" },
    { action = "delete_server", server = tostring(second.id) },
    { action = "save_server", server = tostring(second.id) },
}) do
    local body, status = render("settings", {}, form, "reader")
    equal(status, 403)
    equal(#requests, 0)
    assert(not body:find("second-key", 1, true))
end
equal(select(2, render("settings", {}, nil, "reader")), 403)
equal(#servers.list(db, dbm), 2)

for _, form in ipairs({
    { action = "save_server" },
    { action = "delete_server", server = "999" },
    { action = "save_server", server = tostring(second.id) },
}) do
    local _, status = render("settings", { server = tostring(first.id) }, form)
    equal(status, 400)
    equal(#requests, 0)
end

local _, _, redirect = render("settings", {}, {
    action = "save_server", server = tostring(second.id), name = "Renamed",
    api_host = "renamed.example", api_port = "9444", api_scheme = "https",
    api_key = "new-key", verify_ssl = "on",
})
equal(redirect, nil)
second = assert(api.config(db, dbm, second.id))
equal(second.host, "renamed.example")
equal(second.verify_ssl, true)
equal(assert(api.config(db, dbm, first.id)).host, "legacy.example")

render("settings", {}, { action = "delete_server", server = tostring(second.id) })
local _, status = render("zones", {}, {
    action = "delete", server = tostring(second.id), zone = "shared.example", uid = "same-uid",
})
equal(status, 400)
equal(#requests, 0)
render("settings", {}, { action = "delete_server", server = tostring(first.id) })
dbm = initialize(db)
equal(#servers.list(db, dbm), 0)
package.loaded["lib.db"] = dbm
html = render("settings")
contains(html, "Dodaj serwer DNS")
equal(#requests, 0)
equal(select(2, render("index")), 400)
render("audit")
render("users")

local _, _, added_redirect = render("settings", {}, {
    action = "add_server", name = "New", api_host = "new.example",
    api_port = "8080", api_scheme = "http",
})
assert(added_redirect:match("^/panel/settings%.lhtml%?server=%d+$"))
equal(#servers.list(db, dbm), 1)
for _, page in ipairs({ "audit", "users" }) do
    html = render(page, { server = tostring(servers.list(db, dbm)[1].id) })
    contains(html, "?server=")
end
contains(layout.server_selector({ { id = 1, name = "<DNS>", host = "host", port = 80 } }, nil, "/panel/"), "&lt;DNS&gt;")

api._curl_request = original_curl
package.loaded["socket.http"], package.loaded["ssl.https"] = original_socket, original_https
package.preload["socket.http"], package.preload["ssl.https"] = nil, nil
db:close()
print("OK: migration, CRUD, routing, tab isolation, authorization, stale targets and LHTML templates")
