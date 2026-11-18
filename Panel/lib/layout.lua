-- Panel/lib/layout.lua
-- Pomocnik: wspólny layout HTML panelu.

local M = {}

function M.head(title, extra_css)
    extra_css = extra_css or ""
    return string.format([[<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>%s — DNS Panel</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--bg2:#161b22;--bg3:#1c2128;--brd:#30363d;--brd2:#484f58;
  --text:#c9d1d9;--text2:#8b949e;--text3:#6e7681;
  --acc:#388bfd;--grn:#3fb950;--red:#f85149;--yel:#d29922;
  --mono:'JetBrains Mono','Fira Code',Consolas,monospace;
  --sans:'Segoe UI',system-ui,-apple-system,sans-serif;
}
html,body{height:100%%;font-family:var(--sans);background:var(--bg);color:var(--text);font-size:14px;line-height:1.5}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
code{font-family:var(--mono);font-size:.85em}
/* NAV */
.topnav{display:flex;align-items:center;gap:1rem;height:52px;padding:0 1.25rem;
  background:var(--bg2);border-bottom:1px solid var(--brd);position:sticky;top:0;z-index:50}
.topnav .brand{font-weight:700;font-size:1rem;color:var(--text);display:flex;align-items:center;gap:.5rem;white-space:nowrap}
.topnav .brand .dot{width:8px;height:8px;border-radius:50%%;background:var(--grn)}
.topnav .brand .dot.red{background:var(--red)}
.topnav nav{display:flex;gap:.25rem;flex:1}
.topnav nav a{padding:.35rem .75rem;border-radius:6px;font-size:.875rem;color:var(--text2);transition:.12s}
.topnav nav a:hover,.topnav nav a.active{background:rgba(56,139,253,.12);color:var(--acc);text-decoration:none}
.topnav .user{margin-left:auto;font-size:.8rem;color:var(--text3);display:flex;align-items:center;gap:.75rem}
.topnav .user a{color:var(--text2)}
/* LAYOUT */
.wrap{max-width:1200px;margin:0 auto;padding:1.5rem 1.25rem}
.page-title{font-size:1.25rem;font-weight:700;margin-bottom:1.25rem;display:flex;align-items:center;gap:.625rem}
.page-title small{font-size:.8rem;font-weight:400;color:var(--text3)}
/* CARDS */
.card{background:var(--bg2);border:1px solid var(--brd);border-radius:8px;overflow:hidden;margin-bottom:1.25rem}
.card-head{padding:.75rem 1rem;border-bottom:1px solid var(--brd);display:flex;align-items:center;gap:.625rem;font-size:.875rem;font-weight:600}
.card-body{padding:1rem}
/* TABLES */
.tbl{width:100%%;border-collapse:collapse;font-size:.875rem}
.tbl th{text-align:left;padding:.5rem .75rem;background:var(--bg3);color:var(--text2);font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--brd)}
.tbl td{padding:.5rem .75rem;border-bottom:1px solid rgba(48,54,61,.6);vertical-align:middle}
.tbl tr:last-child td{border-bottom:none}
.tbl tr:hover td{background:rgba(255,255,255,.02)}
.tbl .mono{font-family:var(--mono);font-size:.8rem}
/* BADGES */
.badge{display:inline-flex;align-items:center;padding:.1rem .45rem;border-radius:4px;font-family:var(--mono);font-size:.7rem;font-weight:700;letter-spacing:.04em}
.badge-a{background:rgba(63,185,80,.18);color:#3fb950}
.badge-aaaa{background:rgba(56,139,253,.18);color:#79c0ff}
.badge-mx{background:rgba(210,153,34,.18);color:#e3b341}
.badge-txt{background:rgba(161,113,243,.18);color:#c9acff}
.badge-cname{background:rgba(248,81,73,.18);color:#ff7b72}
.badge-ns{background:rgba(255,255,255,.1);color:#8b949e}
.badge-srv{background:rgba(63,185,80,.12);color:#56d364}
.badge-ptr{background:rgba(56,139,253,.12);color:#58a6ff}
.badge-caa{background:rgba(210,153,34,.1);color:#d29922}
.badge-soa{background:rgba(255,255,255,.07);color:#6e7681}
.badge-other{background:rgba(255,255,255,.07);color:#6e7681}
/* FORMS */
.form-row{display:flex;flex-direction:column;gap:.3rem;margin-bottom:.875rem}
.form-row label{font-size:.8rem;color:var(--text2);font-weight:500}
.form-row input,.form-row select,.form-row textarea{
  background:var(--bg3);border:1px solid var(--brd);border-radius:6px;
  color:var(--text);padding:.5rem .75rem;font-size:.875rem;font-family:inherit;width:100%%;
  transition:border-color .12s;outline:none}
.form-row input:focus,.form-row select:focus,.form-row textarea:focus{border-color:var(--acc);box-shadow:0 0 0 3px rgba(56,139,253,.15)}
.form-row textarea{resize:vertical;min-height:70px}
.form-hint{font-size:.75rem;color:var(--text3);margin-top:.2rem}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 1rem}
.form-grid .span2{grid-column:1/-1}
/* BUTTONS */
.btn{display:inline-flex;align-items:center;gap:.4rem;padding:.45rem .9rem;border-radius:6px;border:none;font-size:.85rem;font-weight:600;cursor:pointer;transition:.12s;text-decoration:none;white-space:nowrap}
.btn:hover{opacity:.88;text-decoration:none}
.btn-primary{background:var(--acc);color:#fff}
.btn-success{background:#238636;color:#fff}
.btn-danger{background:#b62324;color:#fff}
.btn-ghost{background:transparent;color:var(--text2);border:1px solid var(--brd)}
.btn-ghost:hover{background:var(--bg3);color:var(--text)}
.btn-sm{padding:.3rem .65rem;font-size:.78rem}
.btn-group{display:flex;gap:.5rem;flex-wrap:wrap}
/* ALERTS */
.alert{padding:.75rem 1rem;border-radius:6px;font-size:.875rem;margin-bottom:1rem;display:flex;align-items:flex-start;gap:.5rem}
.alert-err{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.4);color:#ffa198}
.alert-ok{background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.35);color:#56d364}
.alert-info{background:rgba(56,139,253,.1);border:1px solid rgba(56,139,253,.35);color:#79c0ff}
/* STAT CARDS */
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:1rem;margin-bottom:1.25rem}
.stat-card{background:var(--bg2);border:1px solid var(--brd);border-radius:8px;padding:1rem}
.stat-card .label{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--text3);margin-bottom:.4rem}
.stat-card .value{font-family:var(--mono);font-size:1.6rem;font-weight:700;color:var(--text)}
.stat-card .value.grn{color:var(--grn)}.stat-card .value.yel{color:var(--yel)}.stat-card .value.red{color:var(--red)}
/* ZONE SELECTOR */
.zone-tabs{display:flex;gap:.375rem;flex-wrap:wrap;margin-bottom:1.25rem}
.zone-tabs a{padding:.35rem .9rem;border-radius:6px;border:1px solid var(--brd);font-size:.82rem;color:var(--text2);transition:.12s}
.zone-tabs a:hover{border-color:var(--brd2);color:var(--text);text-decoration:none}
.zone-tabs a.active{background:rgba(56,139,253,.15);border-color:var(--acc);color:var(--acc)}
/* MODAL */
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;align-items:center;justify-content:center}
.modal-backdrop.open{display:flex}
.modal{background:var(--bg2);border:1px solid var(--brd);border-radius:10px;width:100%%;max-width:540px;max-height:90vh;overflow-y:auto;padding:1.5rem}
.modal h3{font-size:1rem;margin-bottom:1.25rem;display:flex;align-items:center;gap:.5rem}
.modal-close{margin-left:auto;background:none;border:none;color:var(--text3);cursor:pointer;font-size:1.1rem;padding:.2rem}
.modal-close:hover{color:var(--text)}
/* RDATA editor */
.rdata-fields{display:flex;flex-direction:column;gap:.6rem}
.rdata-fields .rf-row{display:flex;align-items:center;gap:.5rem}
.rdata-fields .rf-row label{width:90px;font-size:.78rem;color:var(--text2);flex-shrink:0}
.rdata-fields .rf-row input{flex:1;background:var(--bg3);border:1px solid var(--brd);border-radius:5px;color:var(--text);padding:.4rem .65rem;font-family:var(--mono);font-size:.82rem;outline:none}
.rdata-fields .rf-row input:focus{border-color:var(--acc)}
/* FILTER BAR */
.filter-bar{display:flex;gap:.625rem;align-items:center;margin-bottom:.875rem;flex-wrap:wrap}
.filter-bar input,.filter-bar select{background:var(--bg3);border:1px solid var(--brd);border-radius:6px;color:var(--text);padding:.4rem .65rem;font-size:.82rem;outline:none}
.filter-bar input:focus,.filter-bar select:focus{border-color:var(--acc)}
/* RESPONSIVE */
@media(max-width:680px){
  .form-grid{grid-template-columns:1fr}
  .tbl .hide-sm{display:none}
  .stats-grid{grid-template-columns:1fr 1fr}
}
%s
</style>
</head>
<body>
]], httpd.escape_html(title), extra_css)
end

function M.nav(active, user, api_ok)
    local dot_cls = api_ok and "dot" or "dot red"
    local pages = {
        { href = "/panel/", label = "Dashboard", id = "dashboard" },
        { href = "/panel/zones.lhtml", label = "Strefy", id = "zones" },
        { href = "/panel/settings.lhtml", label = "Ustawienia", id = "settings" },
        { href = "/panel/users.lhtml", label = "Użytkownicy", id = "users" },
        { href = "/panel/audit.lhtml", label = "Audit", id = "audit" },
    }
    local links = {}
    for _, p in ipairs(pages) do
        local cls = (active == p.id) and ' class="active"' or ""
        links[#links+1] = string.format('<a href="%s"%s>%s</a>',
            p.href, cls, p.label)
    end
    return string.format([[
<nav class="topnav">
  <div class="brand"><span class="dns-icon">📡</span> DNS Panel <span class="%s"></span></div>
  <nav>%s</nav>
  <div class="user"><span>%s</span> <a href="/panel/logout.lhtml">Wyloguj</a></div>
</nav>
]], dot_cls, table.concat(links, "\n    "),
    httpd.escape_html(user or ""))
end

function M.foot()
    return "\n</body>\n</html>\n"
end

-- typ rekordu → klasa badge CSS
function M.rtype_badge(rtype)
    local t = (rtype or ""):lower()
    local cls = "badge-" .. t
    -- sprawdź czy znana klasa
    local known = { a=1, aaaa=1, mx=1, txt=1, cname=1, ns=1, srv=1, ptr=1, caa=1, soa=1 }
    if not known[t] then cls = "badge-other" end
    return string.format('<span class="badge %s">%s</span>', cls, httpd.escape_html(rtype or ""))
end

-- formatuje rdata (table → string)
function M.rdata_str(rdata)
    if type(rdata) ~= "table" then return tostring(rdata or "") end
    local parts = {}
    -- priorytet wyświetlania
    local order = { "value", "priority", "weight", "port", "flags", "tag" }
    local seen = {}
    for _, k in ipairs(order) do
        if rdata[k] ~= nil then
            parts[#parts+1] = tostring(rdata[k])
            seen[k] = true
        end
    end
    for k, v in pairs(rdata) do
        if not seen[k] then
            parts[#parts+1] = k .. "=" .. tostring(v)
        end
    end
    return table.concat(parts, " ")
end

return M
