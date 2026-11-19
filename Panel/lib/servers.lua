local M = {}

function M.list(db, dbm)
    return dbm.query(db, "SELECT id, name, host, port, scheme FROM dns_servers ORDER BY id")
end

function M.save(db, dbm, form, id)
    local name = (form.name or ""):match("^%s*(.-)%s*$")
    local host = (form.api_host or ""):match("^%s*(.-)%s*$")
    local port = tonumber(form.api_port)
    local scheme = form.api_scheme
    if name == "" or host == "" or host:find("[%s/%?#@]") then
        return nil, "Podaj nazwę serwera i poprawny host (bez schematu i ścieżki)."
    end
    if not port or port % 1 ~= 0 or port < 1 or port > 65535 then
        return nil, "Port musi być liczbą całkowitą od 1 do 65535."
    end
    if scheme ~= "http" and scheme ~= "https" then
        return nil, "Wybierz schemat HTTP lub HTTPS."
    end
    local params = { name, host, port, scheme, form.api_key or "", form.verify_ssl and 1 or 0 }
    if id then
        params[#params+1] = id
        dbm.exec(db, [[UPDATE dns_servers
            SET name=?,host=?,port=?,scheme=?,api_key=?,verify_ssl=? WHERE id=?]], params)
    else
        dbm.exec(db, [[INSERT INTO dns_servers(name,host,port,scheme,api_key,verify_ssl)
            VALUES(?,?,?,?,?,?)]], params)
        id = db:last_insert_rowid()
    end
    return id
end

function M.detail(cfg)
    return "server_id=" .. tostring(cfg.id) .. " server=" .. cfg.name ..
        " host=" .. cfg.host .. ":" .. tostring(cfg.port)
end

return M
