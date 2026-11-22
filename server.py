#!/usr/bin/env python3
"""Depot EV server: serves the pages and stores/retrieves session history in SQLite.

Run:  python3 server.py [port]        (default 8000)  ->  http://localhost:8000

Sign-in:
  Set DEPOT_TOKEN to any secret string before starting.  Every /api/ request must
  include the header  Authorization: Bearer <token>  (or query param ?token=<token>
  for browser GET requests from the pages).
  Without DEPOT_TOKEN the server runs open — suitable for localhost dev only.

Optional real watsonx.ai (Granite) generation, set before starting:
  WATSONX_API_KEY, WATSONX_PROJECT_ID, [WATSONX_URL], [WATSONX_MODEL]
Without them /api/summarize and /api/granite answer 503 and the pages fall back
to their built-in template text.

Public data feeds (optional keys):
  OPENEI_API_KEY  utility tariffs from OpenEI URDB (defaults to the rate-limited DEMO_KEY)
  SF511_API_KEY   live traffic incidents from 511 SF Bay (free token: https://511.org/open-data/token)
  NREL_API_KEY    solar production from NREL PVWatts (defaults to the rate-limited DEMO_KEY)
  Weather comes from Open-Meteo (no key); the page falls back to a typical curve if it is blocked.

Storage (container deploy):
  DB_PATH  absolute path for data.db (default: alongside server.py).
           Set to the mount path of a persistent volume in IBM Cloud Code Engine,
           e.g. DB_PATH=/data/data.db

Copy .env.example to .env and fill in real keys before deploying.
"""
import datetime
import json
import os
import re
import sqlite3
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# DB_PATH env var lets a container point data.db at a persistent volume mount.
# Falls back to the repo root for local development.
DB = Path(os.getenv("DB_PATH", str(ROOT / "data.db")))
STATIC_TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript",
                ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".pdf": "application/pdf"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, started_at REAL, ended_at REAL, meta TEXT);
CREATE TABLE IF NOT EXISTS samples(session_id INTEGER, t REAL, bldg REAL, ch_kw REAL, un_kw REAL, limit_kw REAL);
CREATE INDEX IF NOT EXISTS ix_samples ON samples(session_id);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, created REAL, sim_t REAL, source TEXT, type TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS ix_events ON events(session_id);
CREATE TABLE IF NOT EXISTS briefs(session_id INTEGER PRIMARY KEY, text TEXT, source TEXT, payload TEXT, created REAL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, created REAL, vehicle TEXT, customer TEXT, stop_id TEXT, kind TEXT, message TEXT, eta TEXT);
"""


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


# ---- watsonx.ai (Granite) -------------------------------------------------
_tok = {"v": None, "exp": 0}


def granite_configured():
    return bool(os.getenv("WATSONX_API_KEY") and os.getenv("WATSONX_PROJECT_ID"))


def iam_token():
    if _tok["v"] and time.time() < _tok["exp"] - 60:
        return _tok["v"]
    data = urllib.parse.urlencode({"grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                                   "apikey": os.environ["WATSONX_API_KEY"]}).encode()
    req = urllib.request.Request("https://iam.cloud.ibm.com/identity/token", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20, context=ssl_ctx()) as r:
        j = json.load(r)
    _tok["v"], _tok["exp"] = j["access_token"], time.time() + int(j.get("expires_in", 3600))
    return _tok["v"]


def granite(prompt, max_tokens=350):
    base = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com").rstrip("/")
    body = {"model_id": os.getenv("WATSONX_MODEL", "ibm/granite-3-8b-instruct"),
            "project_id": os.environ["WATSONX_PROJECT_ID"], "input": prompt,
            "parameters": {"decoding_method": "greedy", "max_new_tokens": max_tokens}}
    req = urllib.request.Request(f"{base}/ml/v1/text/generation?version=2023-05-29",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "Authorization": f"Bearer {iam_token()}"})
    with urllib.request.urlopen(req, timeout=60, context=ssl_ctx()) as r:
        return json.load(r)["results"][0]["generated_text"].strip()


# ---- public data feeds ------------------------------------------------------
_cache = {}


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    out = fn()
    _cache[key] = (time.time(), out)
    return out


_ssl = {}


def ssl_ctx():
    """Default CA store plus, on macOS, the keychain roots (python.org builds ship without a CA
    bundle, and corporate TLS proxies install their root in the keychain)."""
    if "ctx" not in _ssl:
        ctx = ssl.create_default_context(cafile=os.getenv("SSL_CERT_FILE") or None)
        if sys.platform == "darwin":
            keychains = ["/Library/Keychains/System.keychain", "/System/Library/Keychains/SystemRootCertificates.keychain",
                         str(Path.home() / "Library/Keychains/login.keychain-db")]
            try:
                pem = subprocess.run(["security", "find-certificate", "-a", "-p", *keychains],
                                     capture_output=True, text=True, timeout=30).stdout
                if pem:
                    ctx.load_verify_locations(cadata=pem)
            except Exception:
                pass
        _ssl["ctx"] = ctx
    return _ssl["ctx"]


def http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "depot-ev-mvp/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx()) as r:
        return json.loads(r.read().decode("utf-8-sig"))  # 511 prefixes a BOM


def _max_rate(structure):
    return max((t.get("rate", 0) + t.get("adj", 0) for period in structure or [] for t in period), default=0)


def tariffs(lat, lon, kw):
    """Commercial tariffs near a location from the OpenEI Utility Rate Database (URDB)."""
    q = urllib.parse.urlencode({"version": 8, "format": "json", "api_key": os.getenv("OPENEI_API_KEY", "DEMO_KEY"),
                                "lat": lat, "lon": lon, "sector": "Commercial", "detail": "full", "approved": "true",
                                "limit": 100, "orderby": "startdate", "direction": "desc"})
    d = http_json("https://api.openei.org/utility_rates?" + q)
    if "error" in d:
        raise RuntimeError(d["error"].get("message", str(d["error"])))
    out, seen = [], set()
    for r in d.get("items", []):
        facility, tou = _max_rate(r.get("flatdemandstructure")), _max_rate(r.get("demandratestructure"))
        if (facility <= 0 and tou <= 0) or r.get("name") in seen or "agricultur" in (r.get("name") or "").lower():
            continue  # no demand charge, an older revision already listed, or a farm-only rate
        seen.add(r.get("name"))
        energy = [t.get("rate", 0) + t.get("adj", 0) for p in r.get("energyratestructure") or [] for t in p]
        lo, hi = r.get("peakkwcapacitymin"), r.get("peakkwcapacitymax")
        out.append({"label": r.get("label"), "utility": r.get("utility"), "name": r.get("name"),
                    "startdate": r.get("startdate"), "uri": r.get("uri"),
                    "facility_demand_per_kw": round(facility, 2), "tou_demand_per_kw": round(tou, 2),
                    "energy_min_per_kwh": round(min(energy), 5) if energy else None,
                    "energy_max_per_kwh": round(max(energy), 5) if energy else None,
                    "kw_min": lo, "kw_max": hi,
                    "applies": (lo is None or kw >= lo) and (hi is None or kw <= hi)})
    out.sort(key=lambda t: (not t["applies"], t["utility"] or "", t["name"] or ""))
    return out


def incidents():
    """Active traffic events from 511 SF Bay (needs a free token in SF511_API_KEY)."""
    key = os.getenv("SF511_API_KEY")
    if not key:
        return {"configured": False, "events": []}

    def fetch():
        q = urllib.parse.urlencode({"api_key": key, "format": "json"})
        url = "https://api.511.org/traffic/events?" + q
        req = urllib.request.Request(url, headers={"User-Agent": "depot-ev-mvp/1.0", "Accept": "*/*",
                                                    "Accept-Encoding": "gzip, deflate"})
        with urllib.request.urlopen(req, timeout=30, context=ssl_ctx()) as r:
            raw = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":
                import gzip; raw = gzip.decompress(raw)
            elif enc == "deflate":
                import zlib; raw = zlib.decompress(raw)
            d = json.loads(raw.decode("utf-8-sig"))
        events = []
        for e in d.get("events", []):
            g = e.get("geography") or {}
            c = g.get("coordinates") or []
            if g.get("type") == "Point" and len(c) >= 2:
                lon, lat = c[0], c[1]
            elif g.get("type") == "LineString" and c:
                lon, lat = c[0][0], c[0][1]
            elif g.get("type") == "MultiLineString" and c and c[0]:
                lon, lat = c[0][0][0], c[0][0][1]
            else:
                continue
            events.append({"id": e.get("id"), "headline": e.get("headline", ""), "type": e.get("event_type", ""),
                           "subtypes": e.get("event_subtypes") or [], "severity": e.get("severity", ""),
                           "lat": lat, "lon": lon, "updated": e.get("updated", ""),
                           "roads": ", ".join(r.get("name", "") for r in e.get("roads") or [])})
        return events

    return {"configured": True, "events": cached("511", 90, fetch)}  # 511 allows 60 requests/hour


def solar(lat, lon, month):
    """Average hourly AC output (kW per kW of panels) for a month, from NREL PVWatts v8 (typical-year weather)."""
    q = urllib.parse.urlencode({"api_key": os.getenv("NREL_API_KEY", "DEMO_KEY"), "lat": lat, "lon": lon,
                                "system_capacity": 1, "azimuth": 180, "tilt": 10, "array_type": 0,
                                "module_type": 0, "losses": 14, "timeframe": "hourly"})
    d = http_json("https://developer.nrel.gov/api/pvwatts/v8.json?" + q, timeout=30)
    if d.get("errors"):
        raise RuntimeError("; ".join(d["errors"]))
    ac = d["outputs"]["ac"]  # 8760 hourly values in W for a 1 kW array
    sums, counts = [0.0] * 24, [0] * 24
    start = datetime.datetime(2023, 1, 1)  # PVWatts uses a non-leap typical year
    for i, w in enumerate(ac):
        t = start + datetime.timedelta(hours=i)
        if t.month == month:
            sums[t.hour] += w / 1000
            counts[t.hour] += 1
    return {"month": month, "profile": [round(s / c, 4) if c else 0 for s, c in zip(sums, counts)],
            "annual_kwh_per_kwp": round(d["outputs"]["ac_annual"], 1), "source": "NREL PVWatts v8"}


def weather(lat, lon):
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "hourly": "temperature_2m",
                                "forecast_days": 2, "timezone": "auto"})
    d = http_json("https://api.open-meteo.com/v1/forecast?" + q, timeout=15)
    return {"times": d["hourly"]["time"], "temps": d["hourly"]["temperature_2m"], "source": "Open-Meteo"}


def depot_prompt(p):
    return ("You are an operations assistant for an EV delivery Corporate Office. Write a short morning readiness "
            "brief (under 150 words) for the Corporate Office manager from this JSON. State how many vehicles met "
            "their delivery requirement, the peak demand versus the site limit, how load balancing "
            "helped, and anything needing attention.\n\n" + json.dumps(p))


# ---- sign-in + input validation constants ----------------------------------
# _DEPOT_TOKEN is read lazily in _check_auth so that _load_dotenv() (called in main())
# has a chance to populate os.environ before the first request is handled.
_SESSION_KINDS = {"depot", "dispatch"}
_NOTIF_KINDS   = {"delay", "reassigned", "reschedule"}
_MAX_PROMPT    = 32_000   # cap Granite prompt length
_MAX_TEXT      = 4_000    # event / brief text
_MAX_KW        = 10_000.0


def _check_auth(headers, query):
    tok = os.getenv("DEPOT_TOKEN", "")  # read after _load_dotenv() has run
    if not tok:
        return True
    bearer = headers.get("Authorization", "")
    if bearer.startswith("Bearer ") and bearer[7:] == tok:
        return True
    if query.get("token", [""])[0] == tok:
        return True
    return False


def _clamp(v, max_len):
    return str(v or "")[:max_len]


# ---- request handler ------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = min(int(self.headers.get("Content-Length") or 0), 2_097_152)
        return json.loads(self.rfile.read(n) or b"null")

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_DELETE(self): self.route("DELETE")

    def route(self, method):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        # /api/config is always public — it only returns boolean feature flags, no secrets.
        if u.path.startswith("/api/") and u.path != "/api/config" and not _check_auth(self.headers, q):
            return self.reply(401, {"error": "unauthorized"})
        try:
            if u.path.startswith("/api/"):
                self.api(method, u.path, q)
            elif method == "GET":
                self.static(u.path)
            else:
                self.reply(405, {"error": "method not allowed"})
        except Exception as e:  # keep the demo server alive
            self.reply(500, {"error": str(e)})

    def static(self, path):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (ROOT / name).resolve()
        if ROOT not in f.parents or f.suffix not in STATIC_TYPES or not f.is_file():
            return self.reply(404, {"error": "not found"})
        data = f.read_bytes()
        self.send_response(200)
        ctype = STATIC_TYPES[f.suffix]
        self.send_header("Content-Type", ctype if ctype == "application/pdf" or ctype.startswith("image/") else ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def api(self, m, p, q):
        # /api/config — reports whether keys are configured; never reveals key values
        if p == "/api/config" and m == "GET":
            return self.reply(200, {"granite": granite_configured(),
                                    "carto_key": os.getenv("CARTO_API_KEY", "")})

        if p in ("/api/tariffs", "/api/incidents", "/api/weather", "/api/solar") and m == "GET":
            arg = lambda k, d: q.get(k, [d])[0]
            try:
                if p == "/api/solar":
                    lat   = max(-90.0,  min(90.0,   float(arg("lat",   37.751))))
                    lon   = max(-180.0, min(180.0,  float(arg("lon",   -122.199))))
                    month = max(1,      min(12,      int(arg("month",  datetime.date.today().month))))
                    return self.reply(200, cached(f"pv:{lat:.2f}:{lon:.2f}:{month}", 86400, lambda: solar(lat, lon, month)))
                if p == "/api/tariffs":
                    lat = max(-90.0,  min(90.0,      float(arg("lat", 37.751))))
                    lon = max(-180.0, min(180.0,     float(arg("lon", -122.199))))
                    kw  = max(0.0,   min(_MAX_KW,    float(arg("kw",  50))))
                    items = cached(f"urdb:{lat:.3f}:{lon:.3f}:{kw:.0f}", 86400, lambda: tariffs(lat, lon, kw))
                    return self.reply(200, {"source": "OpenEI Utility Rate Database", "items": items})
                if p == "/api/incidents":
                    return self.reply(200, incidents())
                lat = max(-90.0,  min(90.0,  float(arg("lat", 37.751))))
                lon = max(-180.0, min(180.0, float(arg("lon", -122.199))))
                return self.reply(200, cached(f"wx:{lat:.2f}:{lon:.2f}", 1800, lambda: weather(lat, lon)))
            except Exception as e:  # upstream blocked, rate-limited or down: let the page fall back
                return self.reply(502, {"error": f"{type(e).__name__}: {e}"})

        if p in ("/api/granite", "/api/summarize") and m == "POST":
            if not granite_configured():
                return self.reply(503, {"error": "watsonx not configured"})
            b = self.body()
            if not isinstance(b, dict):
                return self.reply(400, {"error": "body must be a JSON object"})
            if p == "/api/granite":
                prompt = b.get("prompt")
                if not isinstance(prompt, str) or not prompt.strip():
                    return self.reply(400, {"error": "prompt is required and must be a non-empty string"})
                prompt = prompt[:_MAX_PROMPT]
            else:
                prompt = depot_prompt(b)
            return self.reply(200, {"text": granite(prompt), "source": "watsonx-granite"})

        if p == "/api/sessions":
            with db() as c:
                if m == "GET":
                    cur = c.execute("""SELECT s.*,
                        (SELECT COUNT(*) FROM samples WHERE session_id=s.id) n_samples,
                        (SELECT COUNT(*) FROM events WHERE session_id=s.id) n_events,
                        (SELECT COUNT(*) FROM notifications WHERE session_id=s.id) n_notifs,
                        EXISTS(SELECT 1 FROM briefs WHERE session_id=s.id) has_brief
                        FROM sessions s ORDER BY id DESC LIMIT 100""")
                    out = rows(cur)
                    for r in out:
                        r["meta"] = json.loads(r["meta"] or "{}")
                    return self.reply(200, out)
                if m == "POST":
                    b = self.body() or {}
                    if not isinstance(b, dict):
                        return self.reply(400, {"error": "body must be a JSON object"})
                    kind = b.get("kind", "depot")
                    if kind not in _SESSION_KINDS:
                        return self.reply(400, {"error": f"kind must be one of {sorted(_SESSION_KINDS)}"})
                    cur = c.execute("INSERT INTO sessions(kind,started_at,meta) VALUES(?,?,?)",
                                    (kind, time.time(), json.dumps(b.get("meta", {}))))
                    return self.reply(200, {"id": cur.lastrowid})

        m_ = re.fullmatch(r"/api/sessions/(\d+)(?:/(samples|events|brief|end))?", p)
        if m_:
            sid, sub = int(m_.group(1)), m_.group(2)
            with db() as c:
                if sub is None and m == "GET":
                    s = c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
                    if not s:
                        return self.reply(404, {"error": "no such session"})
                    out = dict(s)
                    out["meta"] = json.loads(out["meta"] or "{}")
                    out["samples"] = rows(c.execute("SELECT t,bldg,ch_kw,un_kw,limit_kw,grid_kw,solar_kw,batt_pct,price FROM samples WHERE session_id=? ORDER BY rowid", (sid,)))
                    out["events"] = rows(c.execute("SELECT created,sim_t,source,type,text FROM events WHERE session_id=? ORDER BY id", (sid,)))
                    out["notifications"] = rows(c.execute("SELECT * FROM notifications WHERE session_id=? ORDER BY id", (sid,)))
                    b = c.execute("SELECT text,source,payload FROM briefs WHERE session_id=?", (sid,)).fetchone()
                    out["brief"] = dict(b) if b else None
                    return self.reply(200, out)
                if sub is None and m == "DELETE":
                    for t in ("samples", "events", "briefs", "notifications"):
                        c.execute(f"DELETE FROM {t} WHERE session_id=?", (sid,))
                    c.execute("DELETE FROM sessions WHERE id=?", (sid,))
                    return self.reply(200, {"ok": True})
                if sub == "samples" and m == "POST":
                    raw = self.body()
                    if not isinstance(raw, list):
                        return self.reply(400, {"error": "samples must be a JSON array"})
                    validated = []
                    for s in raw:
                        try:
                            validated.append((
                                sid,
                                float(s["t"]), float(s["bldg"]), float(s["ch_kw"]),
                                float(s["un_kw"]), float(s["limit"]),
                                float(s["grid"])  if s.get("grid")  is not None else None,
                                float(s["solar"]) if s.get("solar") is not None else None,
                                float(s["batt"])  if s.get("batt")  is not None else None,
                                float(s["price"]) if s.get("price") is not None else None,
                            ))
                        except (KeyError, TypeError, ValueError):
                            return self.reply(400, {"error": "each sample must have numeric t, bldg, ch_kw, un_kw, limit"})
                    c.executemany("INSERT INTO samples(session_id,t,bldg,ch_kw,un_kw,limit_kw,grid_kw,solar_kw,batt_pct,price) VALUES(?,?,?,?,?,?,?,?,?,?)", validated)
                    return self.reply(200, {"ok": True})
                if sub == "events" and m == "POST":
                    b = self.body()
                    b = b if isinstance(b, list) else [b]
                    c.executemany("INSERT INTO events(session_id,created,sim_t,source,type,text) VALUES(?,?,?,?,?,?)",
                                  [(sid, time.time(),
                                    float(e["ts"]) if e.get("ts") is not None else None,
                                    _clamp(e.get("source"), 64),
                                    _clamp(e.get("type"),   64),
                                    _clamp(e.get("text"),   _MAX_TEXT)) for e in b])
                    return self.reply(200, {"ok": True})
                if sub == "brief" and m == "POST":
                    b = self.body()
                    if not isinstance(b, dict) or not isinstance(b.get("text"), str):
                        return self.reply(400, {"error": "brief must have a text string"})
                    c.execute("INSERT OR REPLACE INTO briefs VALUES(?,?,?,?,?)",
                              (sid,
                               _clamp(b["text"],        _MAX_TEXT * 2),
                               _clamp(b.get("source"),  64),
                               json.dumps(b.get("payload", {})),
                               time.time()))
                    return self.reply(200, {"ok": True})
                if sub == "end" and m == "POST":
                    s = c.execute("SELECT meta FROM sessions WHERE id=?", (sid,)).fetchone()
                    meta = json.loads((s["meta"] if s else None) or "{}")
                    meta.update(self.body() or {})
                    c.execute("UPDATE sessions SET ended_at=?, meta=? WHERE id=?", (time.time(), json.dumps(meta), sid))
                    return self.reply(200, {"ok": True})

        if p == "/api/notifications":
            with db() as c:
                if m == "POST":
                    b = self.body()
                    if not isinstance(b, dict):
                        return self.reply(400, {"error": "body must be a JSON object"})
                    kind = b.get("kind")
                    if kind not in _NOTIF_KINDS:
                        return self.reply(400, {"error": f"kind must be one of {sorted(_NOTIF_KINDS)}"})
                    cur = c.execute("INSERT INTO notifications(session_id,created,vehicle,customer,stop_id,kind,message,eta) VALUES(?,?,?,?,?,?,?,?)",
                                    (b.get("session_id"), time.time(),
                                     _clamp(b.get("vehicle"),  64),
                                     _clamp(b.get("customer"), 128),
                                     _clamp(b.get("stop_id"),  64),
                                     kind,
                                     _clamp(b.get("message"),  _MAX_TEXT),
                                     _clamp(b.get("eta"),      32)))
                    return self.reply(200, {"id": cur.lastrowid})
                if m == "GET":
                    after = max(0, int(q.get("after", ["0"])[0]))
                    limit = min(max(1, int(q.get("limit", ["300"])[0])), 1000)
                    cur = c.execute("SELECT * FROM notifications WHERE id>? ORDER BY id DESC LIMIT ?", (after, limit))
                    return self.reply(200, rows(cur))

        self.reply(404, {"error": "unknown endpoint"})


def _load_dotenv():
    """Load .env file from the repo root into os.environ (no external packages needed)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if k and k not in os.environ:   # don't override values already set in the environment
            os.environ[k] = v


def main():
    _load_dotenv()
    with db() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("PRAGMA table_info(samples)")}
        for col in ("grid_kw", "solar_kw", "batt_pct", "price"):  # added with solar + battery
            if col not in have:
                c.execute(f"ALTER TABLE samples ADD COLUMN {col} REAL")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Depot EV server on http://localhost:{port}  (db: {DB.name}, watsonx: {'on' if granite_configured() else 'off - template text'})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
