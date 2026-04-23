#!/usr/bin/env python3
"""
Atlas of Australia — God's Eye Proxy Server
Standalone FastAPI server that proxies CORS-blocked Australian data APIs
and serves the gods-eye.html dashboard.

Run:  pip install fastapi uvicorn httpx  &&  python gods-eye-server.py
Then open:  http://localhost:8777
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import math
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("gods-eye")

# ─── Lightweight .env loader (no python-dotenv dep) ─────────────
def _load_env_file(p: Path) -> None:
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass

# Try .env in this directory first, then the parent (the repo root, where .env
# normally lives). This covers both running from gods-eye/ and from the repo root.
_load_env_file(Path(__file__).parent / ".env")
_load_env_file(Path(__file__).parent.parent / ".env")
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response

# ═══════════════════════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(application: FastAPI):
    # ── Startup ──
    asyncio.create_task(_flight_refresh_loop())
    await _ensure_au_places()
    asyncio.create_task(_bom_master_background())
    yield
    # ── Shutdown: close all httpx clients ──
    global _client, _om_http_client, _bom_http_client, _rv_http_client
    for c in (_client, _om_http_client, _bom_http_client, _rv_http_client):
        if c is not None:
            await c.aclose()
    _client = _om_http_client = _bom_http_client = _rv_http_client = None
    log.info("All httpx clients closed")


app = FastAPI(title="God's Eye Proxy", version="1.0.0", docs_url="/docs",
              lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════
# CACHE + HTTP CLIENT
# ═══════════════════════════════════════════════════════════════

_cache: dict[str, dict[str, Any]] = {}
_client: httpx.AsyncClient | None = None
_HEADERS = {"User-Agent": "AtlasOfAustralia/1.0 (github.com/atlas-of-australia)"}


async def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
    return _client


def cache_get(key: str, ttl: int) -> dict | None:
    e = _cache.get(key)
    if e and (time.time() - e["ts"]) < ttl:
        return e
    return None


_CACHE_MAX = 500


def cache_set(key: str, data: Any, error: str | None = None):
    if len(_cache) >= _CACHE_MAX and key not in _cache:
        # Evict oldest entries to make room
        oldest_keys = sorted(_cache, key=lambda k: _cache[k]["ts"])[:len(_cache) - _CACHE_MAX + 1]
        for k in oldest_keys:
            _cache.pop(k, None)
    _cache[key] = {"data": data, "error": error, "ts": time.time()}


def respond(source: str, data: Any, cached: bool, error: str | None = None) -> dict:
    return {
        "source": source,
        "cached": cached,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": data,  # keep stale data even when there's an error
        "error": error,
    }


async def proxy_fetch(key: str, url: str, source: str, ttl: int, **kwargs) -> dict:
    """Generic fetch-with-cache helper."""
    c = cache_get(key, ttl)
    if c and c["data"] is not None:
        return respond(source, c["data"], cached=True)

    http = await client()
    try:
        r = await http.get(url, headers={**_HEADERS, **kwargs.get("headers", {})})
        r.raise_for_status()
        data = r.json()
        cache_set(key, data)
        return respond(source, data, cached=False)
    except Exception as e:
        err = str(e)
        # return stale cache if available
        if key in _cache and _cache[key]["data"]:
            return respond(source, _cache[key]["data"], cached=True, error=err)
        return respond(source, None, cached=False, error=err)


# ═══════════════════════════════════════════════════════════════
# SERVE THE DASHBOARD
# ═══════════════════════════════════════════════════════════════

_HTML_PLACEHOLDERS = (
    "GOOGLE_MAPS_BROWSER_KEY",  # Places autocomplete, Directions, POI Nearby Search
    "MAPTILER_KEY",             # Dark-streets basemap tiles
    "TOMTOM_KEY",               # Live traffic flow raster tiles
)


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the God's Eye dashboard from index.html in this directory.

    Substitutes `{{VAR}}` placeholders with values from the environment so
    browser-safe keys (notably the Google Maps JS key) can live in `.env`
    instead of being hard-coded into the tracked HTML.
    """
    html_path = Path(__file__).parent / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>index.html not found</h1>", status_code=404)
    html = html_path.read_text(encoding="utf-8")
    for name in _HTML_PLACEHOLDERS:
        value = os.environ.get(name, "")
        if not value:
            log.warning("Env var %s not set; %s placeholder will be empty.", name, name)
        html = html.replace("{{" + name + "}}", value)
    return HTMLResponse(html)


# ═══════════════════════════════════════════════════════════════
# PROXY ENDPOINTS
# ═══════════════════════════════════════════════════════════════

# ─── TRAFFIC INCIDENTS (TfNSW Live Traffic Hazards API) ────────
# The public NSW hazards feed at hazards.transport.nsw.gov.au/* no longer
# resolves — it's been replaced by TfNSW's OpenData API, which requires a
# free developer key (sign up at https://opendata.transport.nsw.gov.au/).
# Set NSW_TRAFFIC_API_KEY in .env to enable this source; without it, the
# endpoint returns an empty FeatureCollection instead of erroring so the
# rest of the dashboard keeps working.
_INCIDENT_SOURCES = [
    {
        "name": "tfnsw-opendata",
        "url": "https://api.transport.nsw.gov.au/v1/live/hazards/incident/open",
        "env_key": "NSW_TRAFFIC_API_KEY",        # Authorization: apikey <val>
        "auth_header_fmt": "apikey {val}",
    },
]

def _fmt_ts_ms(v) -> str:
    """Format an ms-epoch timestamp as '22 Nov 2026, 14:30' (local Sydney time).
    NSW returns realistic end-dates for active hazards (hours/days out) but
    also multi-decade placeholder values (e.g. year 2058) for 'indefinite'
    roadworks. Callers decide whether to include the `ends` field based on how
    far in the future it is."""
    if v is None:
        return ""
    try:
        ts = float(v) / 1000.0
        from datetime import datetime, timezone, timedelta
        # Sydney is UTC+10 (no DST handling — close enough for display).
        tz = timezone(timedelta(hours=10))
        # %-d (no-leading-zero day) is Unix-only; strip manually for Windows.
        s = datetime.fromtimestamp(ts, tz=tz).strftime("%d %b %Y, %H:%M")
        return s.lstrip("0") if s else ""
    except Exception:
        return ""


def _extract_incident_props(item: dict) -> dict:
    """Normalise NSW hazards fields into a common display shape.

    Works on both the flat-dict form and the inner `.properties` of a GeoJSON
    Feature from TfNSW's Live Traffic Hazards API. The front-end popup renderer
    reads a core set (title / subtitle / category / severity / status /
    description) plus optional rich fields (started / lastUpdated / ends /
    delay / advice / attending / diversions / webLinkUrl / webLinkText / queue).
    Optional fields are empty strings when absent so the renderer can use
    simple truthy checks.
    """
    # Title — prefer the specific incident name (from webLinks.linkText), then
    # displayName, then fall back. displayName is often CATEGORY + name which
    # duplicates with the category chip, so webLinks wins when available.
    web_links = item.get("webLinks") or []
    title = None
    if web_links and isinstance(web_links[0], dict):
        title = web_links[0].get("linkText")
    title = title or item.get("displayName") or item.get("name") or item.get("headline") or "Incident"

    # Subtitle — first road's mainStreet + suburb (most informative).
    roads = item.get("roads") or []
    subtitle = ""
    if roads and isinstance(roads[0], dict):
        r = roads[0]
        parts = []
        if r.get("mainStreet"): parts.append(str(r["mainStreet"]))
        if r.get("suburb"): parts.append(str(r["suburb"]))
        elif r.get("region"): parts.append(str(r["region"]))
        subtitle = " \u00b7 ".join(parts)
    elif item.get("suburbs"):
        subtitle = str(item["suburbs"])
    elif item.get("region"):
        subtitle = str(item["region"])

    # Category — title-case "CHANGED TRAFFIC CONDITIONS" → "Changed Traffic Conditions".
    main_cat = item.get("mainCategory")
    if isinstance(main_cat, dict):
        main_cat = main_cat.get("name", "")
    category_raw = main_cat or item.get("incidentKind") or item.get("hazardType") or ""
    category = str(category_raw).title() if category_raw else ""

    # Severity — isMajor bool wins, then explicit impact/severity fields.
    severity = ""
    if item.get("isMajor"):
        severity = "Major"
    elif item.get("impact"):
        severity = str(item["impact"])
    elif item.get("severity"):
        severity = str(item["severity"])

    # Status — ended / planned / active (default).
    if item.get("ended"):
        status = "Ended"
    elif item.get("incidentKind") == "Planned":
        status = "Planned"
    elif item.get("incidentStatus"):
        status = str(item["incidentStatus"])
    elif item.get("status"):
        status = str(item["status"])
    else:
        status = "Active"

    # Description — otherAdvice (HTML-stripped) then description. Fall back to
    # the short adviceA/B fields if the main body is empty.
    description = str(
        item.get("otherAdvice")
        or item.get("description")
        or item.get("additionalInformation")
        or ""
    )
    description = re.sub(r"<[^>]+>", " ", description)
    description = re.sub(r"\s+", " ", description).strip()
    if not description:
        advice_a = str(item.get("adviceA") or "").strip()
        advice_b = str(item.get("adviceB") or "").strip()
        description = " \u00b7 ".join(filter(None, [advice_a, advice_b]))
    if len(description) > 400:
        description = description[:397] + "…"

    # ── Rich optional fields ──────────────────────────────────
    # Only include values that are genuinely present (not placeholder -1 or
    # distant-future "indefinite" dates). Empty string means "skip this field"
    # to the client.
    started = _fmt_ts_ms(item.get("start") or item.get("created"))
    last_updated = _fmt_ts_ms(item.get("lastUpdated"))
    # Only include end time if it's within ~14 days — anything further is
    # likely the 2058-style placeholder NSW uses for indefinite hazards.
    ends = ""
    end_raw = item.get("end")
    if end_raw:
        try:
            import time
            end_secs = float(end_raw) / 1000.0
            if end_secs - time.time() < 14 * 24 * 3600:
                ends = _fmt_ts_ms(end_raw)
        except Exception:
            pass

    # Expected delay in minutes (NSW uses -1 for unknown).
    delay = ""
    try:
        d = int(item.get("expectedDelay", -1))
        if d > 0:
            delay = f"{d} min"
    except Exception:
        pass

    # Combine short advices (NSW often splits into A/B/C).
    advice_parts = [
        str(item.get(k) or "").strip()
        for k in ("adviceA", "adviceB", "adviceC")
    ]
    advice = " \u00b7 ".join(a for a in advice_parts if a and a.lower() not in ("null", "none"))

    # Attending emergency groups (police, fire, ambulance, etc.).
    attending = ""
    ag = item.get("attendingGroups")
    if isinstance(ag, list):
        attending = ", ".join(str(g) for g in ag if g)
    elif isinstance(ag, str):
        attending = ag

    # Diversions (HTML blob in NSW data).
    diversions = str(item.get("diversions") or "")
    diversions = re.sub(r"<[^>]+>", " ", diversions)
    diversions = re.sub(r"\s+", " ", diversions).strip()
    if len(diversions) > 300:
        diversions = diversions[:297] + "…"

    # External info link (usually TfNSW project page).
    web_link_url = ""
    web_link_text = ""
    if web_links and isinstance(web_links[0], dict):
        web_link_url = str(web_links[0].get("linkURL") or "")
        web_link_text = str(web_links[0].get("linkText") or "")

    # Queue length (metres) from first road entry.
    queue = ""
    if roads and isinstance(roads[0], dict):
        try:
            q = int(roads[0].get("queueLength", 0))
            if q > 0:
                queue = f"{q:,} m" if q < 10000 else f"{q / 1000:.1f} km"
        except Exception:
            pass

    return {
        # Core fields.
        "title": str(title),
        "subtitle": subtitle,
        "severity": severity,
        "category": category,
        "status": status,
        "description": description,
        "source": "NSW Live Traffic",
        # Rich optional fields.
        "started": started,
        "lastUpdated": last_updated,
        "ends": ends,
        "delay": delay,
        "advice": advice,
        "attending": attending,
        "diversions": diversions,
        "webLinkUrl": web_link_url,
        "webLinkText": web_link_text,
        "queue": queue,
    }


def _normalise_nsw_incident(item: dict) -> dict | None:
    """Flat-dict fallback — build a GeoJSON Point from a top-level lat/lng."""
    lat = item.get("latitude") or item.get("lat")
    lng = item.get("longitude") or item.get("lng")
    if (lat is None or lng is None) and isinstance(item.get("location"), dict):
        loc = item["location"]
        lat = lat or loc.get("lat") or loc.get("latitude")
        lng = lng or loc.get("lng") or loc.get("longitude")
    if lat is None or lng is None:
        return None
    try:
        lat = float(lat); lng = float(lng)
    except (TypeError, ValueError):
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": _extract_incident_props(item),
    }


@app.get("/proxy/traffic-incidents")
async def proxy_traffic_incidents():
    """Public traffic incidents (NSW hazards feed), normalised to GeoJSON.

    Cached for 90 seconds. On upstream failure, returns the last cached copy
    (if any) with an `error` field, or an empty FeatureCollection otherwise —
    so the client always gets a well-formed response.
    """
    cache_key = "traffic_incidents"
    cached = cache_get(cache_key, ttl=90)
    if cached and cached["data"] is not None:
        return respond("traffic_incidents", cached["data"], cached=True)

    features: list[dict] = []
    last_error: str | None = None
    http = await client()
    for src in _INCIDENT_SOURCES:
        # Skip sources that require a key we don't have — silently, so no
        # noisy 401s show up for users who haven't signed up yet.
        env_key = src.get("env_key")
        auth_header = None
        if env_key:
            val = os.environ.get(env_key, "").strip()
            if not val:
                last_error = f"{src['name']}: {env_key} not set in .env (free signup at opendata.transport.nsw.gov.au)"
                continue
            auth_header = src["auth_header_fmt"].format(val=val)
        try:
            hdrs = dict(_HEADERS)
            if auth_header:
                hdrs["Authorization"] = auth_header
            r = await http.get(src["url"], headers=hdrs)
            r.raise_for_status()
            raw = r.json()
            # NSW feed can be: {"hazards":[...]} / {"features":[...]} / a bare list.
            if isinstance(raw, dict):
                items = raw.get("hazards") or raw.get("features") or raw.get("data") or []
            elif isinstance(raw, list):
                items = raw
            else:
                items = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                # TfNSW returns GeoJSON Features — preserve geometry, swap the
                # (noisy, verbose) raw properties for our normalised subset so
                # the front-end popup renderer finds the fields it expects.
                if it.get("type") == "Feature" and isinstance(it.get("geometry"), dict):
                    geom = it["geometry"]
                    # Only Point geometries render on the client circle layer.
                    # For non-Point, synthesise a Point at a representative
                    # coordinate (LineString midpoint, Polygon first vertex).
                    gtype = geom.get("type")
                    coords = geom.get("coordinates") or []
                    if gtype == "Point" and len(coords) == 2:
                        pass  # use as-is
                    elif gtype in ("LineString", "MultiLineString") and coords:
                        line = coords[0] if gtype == "MultiLineString" else coords
                        if not (line and isinstance(line[0], (list, tuple))):
                            continue
                        geom = {"type": "Point", "coordinates": line[len(line) // 2]}
                    elif gtype in ("Polygon", "MultiPolygon") and coords:
                        poly = coords[0][0] if gtype == "MultiPolygon" else coords[0]
                        if not (poly and isinstance(poly[0], (list, tuple))):
                            continue
                        geom = {"type": "Point", "coordinates": poly[0]}
                    else:
                        continue
                    features.append({
                        "type": "Feature",
                        "geometry": geom,
                        "properties": _extract_incident_props(it.get("properties") or {}),
                    })
                    continue
                f = _normalise_nsw_incident(it)
                if f:
                    features.append(f)
        except Exception as e:
            last_error = f"{src['name']}: {e}"
            log.warning("incident source %s failed: %s", src["name"], e)

    data = {"type": "FeatureCollection", "features": features}
    cache_set(cache_key, data, error=last_error)
    return respond("traffic_incidents", data, cached=False, error=last_error)


# ─── FLIGHTS (airplanes.live primary, OpenSky fallback) ──────
# Background loop refreshes the adsb.one feed every ~1s in parallel across
# all coverage points, so client polls always hit a warm cache instantly.
_flight_backoff_until: float = 0.0
_FLIGHT_POINTS = [
    (-25, 134),   # Central Australia
    (-33, 151),   # Sydney / east coast
    (-37, 145),   # Melbourne / SE
    (-27, 153),   # Brisbane / QLD
    (-31, 116),   # Perth / WA
    (-12, 131),   # Darwin / NT
]

# Multiple ADS-B aggregators — each has a slightly different feeder subset,
# so merging gives the smallest possible "seen_pos" (freshest real report)
# per aircraft. All are free and share the ADS-B Exchange v2 response format.
_AGGREGATORS = [
    "https://api.adsb.one/v2/point",
    "https://api.airplanes.live/v2/point",
    "https://api.adsb.lol/v2/point",
]

async def _fetch_adsb_point(http: httpx.AsyncClient, base: str, lat: float, lon: float):
    try:
        r = await http.get(
            f"{base}/{lat}/{lon}/250",
            headers=_HEADERS, timeout=5.0,
        )
        if r.status_code == 200:
            out = r.json().get("ac", []) or []
            # Tag each record with its source so we can debug/trace
            src = base.split("//", 1)[-1].split("/", 1)[0]
            for ac in out:
                ac["_src"] = src
            return out
    except Exception as exc:
        log.debug("ADS-B point fetch failed (%s): %s", base, exc)
    return []

# ── WebSocket connection registry for push updates ──────────
_flight_ws_clients: set[WebSocket] = set()
_flight_ws_lock = asyncio.Lock()

async def _broadcast_flights(payload: dict):
    """Send latest flight payload to all connected WebSocket clients.
    Each client may have its own viewport bbox — filter before sending."""
    if not _flight_ws_clients:
        return
    async with _flight_ws_lock:
        dead = []
        for ws in list(_flight_ws_clients):
            try:
                # Per-client viewport filter (stored on the WS state)
                bbox = getattr(ws.state, "bbox", None)
                if bbox:
                    lo_lat, lo_lng, hi_lat, hi_lng = bbox
                    filtered = [a for a in payload["aircraft"]
                                if lo_lat <= a.get("lat", 0) <= hi_lat
                                and lo_lng <= a.get("lon", 0) <= hi_lng]
                    out = {**payload, "aircraft": filtered, "total": len(filtered)}
                else:
                    out = payload
                await ws.send_json({"type": "flights", **out})
            except Exception as exc:
                log.debug("WebSocket send failed, removing client: %s", exc)
                dead.append(ws)
        for ws in dead:
            _flight_ws_clients.discard(ws)

async def _refresh_flights_once():
    """Fetch every aggregator × coverage point in parallel, merge by
    freshest seen_pos per aircraft, and update the cache."""
    http = await client()
    tasks = []
    for base in _AGGREGATORS:
        for (lat, lon) in _FLIGHT_POINTS:
            tasks.append(_fetch_adsb_point(http, base, lat, lon))
    results = await asyncio.gather(*tasks)

    # Merge: keep the record with the smallest seen_pos per aircraft.
    # seen_pos = seconds since last real position report (lower = fresher).
    best: dict[str, dict] = {}
    for ac_list in results:
        for ac in ac_list:
            hex_id = ac.get("hex", "")
            if not hex_id or ac.get("lat") is None or ac.get("lon") is None:
                continue
            sp = ac.get("seen_pos", 999.0)
            if not isinstance(sp, (int, float)):
                sp = 999.0
            existing = best.get(hex_id)
            existing_sp = (existing.get("seen_pos", 999.0)
                           if existing else float("inf"))
            if not isinstance(existing_sp, (int, float)):
                existing_sp = 999.0
            if sp < existing_sp:
                best[hex_id] = ac

    if best:
        aircraft = list(best.values())
        # Diagnostic: track how many came from which source and the
        # distribution of seen_pos freshness. Logged once every ~10s.
        global _last_flight_diag
        now_s = time.time()
        if now_s - _last_flight_diag > 10:
            _last_flight_diag = now_s
            src_counts: dict[str, int] = {}
            sp_vals = []
            for a in aircraft:
                src_counts[a.get("_src", "?")] = src_counts.get(a.get("_src", "?"), 0) + 1
                v = a.get("seen_pos")
                if isinstance(v, (int, float)):
                    sp_vals.append(v)
            if sp_vals:
                sp_vals.sort()
                p50 = sp_vals[len(sp_vals)//2]
                p95 = sp_vals[int(len(sp_vals)*0.95)]
                print(f"[flights] {len(aircraft)} aircraft | sources={src_counts} "
                      f"| seen_pos p50={p50:.1f}s p95={p95:.1f}s max={sp_vals[-1]:.1f}s",
                      flush=True)

        data = {
            "aircraft": aircraft,
            "total": len(aircraft),
            "source": "adsb-merged",
            "ts": time.time(),
        }
        cache_set("flights", data)
        await _broadcast_flights(data)

_last_flight_diag: float = 0.0

async def _flight_refresh_loop():
    """Keep the flight cache warm — target ~1s refresh cadence."""
    # Small startup delay so the HTTP client is ready
    await asyncio.sleep(0.5)
    while True:
        t0 = time.time()
        try:
            await _refresh_flights_once()
        except Exception as exc:
            log.warning("Flight refresh failed: %s", exc)
        # Sleep just enough to maintain ~1s cadence
        elapsed = time.time() - t0
        await asyncio.sleep(max(0.0, 1.0 - elapsed))

@app.get("/proxy/flights")
async def proxy_flights():
    global _flight_backoff_until

    # With the background loop running, the cache should always be fresh.
    # Accept up to 5s stale so a brief network hiccup doesn't blank the map.
    c = cache_get("flights", 5)
    if c and c["data"]:
        return respond("ADS-B", c["data"], cached=True)

    # Cold start — do one inline fetch while the loop spins up
    errors = []
    try:
        await _refresh_flights_once()
    except Exception as e:
        errors.append(f"adsb.one: {e}")
    c = cache_get("flights", 5)
    if c and c["data"]:
        return respond("ADS-B", c["data"], cached=False,
                       error="; ".join(errors) if errors else None)
    http = await client()

    # ── FALLBACK: OpenSky (rate-limited) ─────────────────────
    if time.time() >= _flight_backoff_until:
        try:
            r = await http.get(
                "https://opensky-network.org/api/states/all?lamin=-45&lamax=-10&lomin=110&lomax=155",
                headers=_HEADERS, timeout=20.0,
            )
            if r.status_code == 429:
                _flight_backoff_until = time.time() + 600
                errors.append("OpenSky: 429 rate limited")
            elif r.status_code == 200:
                raw = r.json()
                _flight_backoff_until = 0.0
                # Convert OpenSky states to aircraft format
                aircraft = []
                for s in (raw.get("states") or []):
                    if s[5] is not None and s[6] is not None:
                        aircraft.append({
                            "hex": s[0] or "",
                            "flight": (s[1] or "").strip(),
                            "lon": s[5],
                            "lat": s[6],
                            "alt_baro": int(s[7] * 3.281) if s[7] else 0,  # m → ft
                            "gs": int(s[9] * 1.944) if s[9] else 0,        # m/s → knots
                            "track": s[10] or 0,
                            "baro_rate": 0,
                            "on_ground": s[8],
                        })
                aircraft = [a for a in aircraft if not a.get("on_ground")]
                data = {"aircraft": aircraft, "total": len(aircraft), "source": "OpenSky"}
                cache_set("flights", data)
                return respond("OpenSky Network", data, cached=False)
        except Exception as e:
            errors.append(f"OpenSky: {e}")

    # All failed
    err_msg = "; ".join(errors) if errors else "All flight feeds failed"
    if "flights" in _cache and _cache["flights"]["data"]:
        return respond("ADS-B", _cache["flights"]["data"], cached=True, error=err_msg)
    return respond("ADS-B (adsb.one)", None, cached=False, error=err_msg)


# ─── WebSocket: /ws/flights — push live flight updates ──────
# Client opens WS, receives initial snapshot + broadcast updates ~1/s.
# Client can send {"bbox":[lo_lat,lo_lng,hi_lat,hi_lng]} to viewport-filter.
@app.websocket("/ws/flights")
async def ws_flights(ws: WebSocket):
    await ws.accept()
    ws.state.bbox = None
    _flight_ws_clients.add(ws)
    try:
        # Send the current cache immediately so the map isn't blank
        if "flights" in _cache and _cache["flights"]["data"]:
            snap = _cache["flights"]["data"]
            await ws.send_json({"type": "flights", **snap})
        # Listen for viewport bbox updates from this client
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "bbox":
                b = msg.get("bbox")
                if (isinstance(b, list) and len(b) == 4
                        and all(isinstance(x, (int, float)) for x in b)):
                    ws.state.bbox = tuple(b)
                else:
                    ws.state.bbox = None
    except WebSocketDisconnect:
        pass  # normal close
    except Exception as exc:
        log.debug("WebSocket /ws/flights error: %s", exc)
    finally:
        _flight_ws_clients.discard(ws)


# ─── Flight enrichment: route (callsign → origin/destination) ───────
# Primary source: adsbdb.com (free, no auth, includes airport + airline
# details in one call). Fallback: hexdb.io callsign-route. Cache 1hr.
_route_cache: dict[str, dict] = {}
_ROUTE_CACHE_MAX = 500


def _as_num(v):
    try:
        if v is None: return None
        return float(v)
    except Exception:
        return None


async def _fetch_adsbdb_callsign(http, cs: str) -> dict | None:
    """Query adsbdb.com v0/callsign/{CALLSIGN}. Returns flattened dict or None."""
    try:
        r = await http.get(
            f"https://api.adsbdb.com/v0/callsign/{cs}",
            headers=_HEADERS, timeout=6.0,
        )
        if r.status_code != 200:
            return None
        j = r.json() or {}
        fr = (j.get("response") or {}).get("flightroute") or {}
        if not fr:
            return None
        al = fr.get("airline") or {}
        og = fr.get("origin") or {}
        de = fr.get("destination") or {}
        data = {
            "callsign": fr.get("callsign") or cs,
            "callsign_iata": fr.get("callsign_iata"),
            "airline_name": al.get("name"),
            "airline_iata": al.get("iata"),
            "airline_icao": al.get("icao"),
            "airline_country": al.get("country"),
            "origin": og.get("icao_code"),
            "origin_iata": og.get("iata_code"),
            "origin_name": og.get("name"),
            "origin_city": og.get("municipality"),
            "origin_country": og.get("country_iso_name") or og.get("country_name"),
            "origin_lat": _as_num(og.get("latitude")),
            "origin_lng": _as_num(og.get("longitude")),
            "destination": de.get("icao_code"),
            "destination_iata": de.get("iata_code"),
            "destination_name": de.get("name"),
            "destination_city": de.get("municipality"),
            "destination_country": de.get("country_iso_name") or de.get("country_name"),
            "destination_lat": _as_num(de.get("latitude")),
            "destination_lng": _as_num(de.get("longitude")),
            "source": "adsbdb",
        }
        return data
    except Exception:
        return None


async def _fetch_hexdb_route(http, cs: str) -> dict | None:
    try:
        r = await http.get(
            f"https://hexdb.io/callsign-route?callsign={cs}",
            headers=_HEADERS, timeout=5.0,
        )
        if r.status_code == 200:
            txt = r.text.strip()
            if txt and "-" in txt and not txt.lower().startswith("unknown"):
                parts = [p.strip().upper() for p in txt.split("-") if p.strip()]
                return {
                    "origin": parts[0] if len(parts) >= 1 else None,
                    "destination": parts[-1] if len(parts) >= 2 else None,
                    "via": parts[1:-1] if len(parts) > 2 else [],
                    "raw": txt,
                    "source": "hexdb",
                }
    except Exception as exc:
        log.debug("hexdb route lookup failed for %s: %s", cs, exc)
    return None


@app.get("/proxy/flight-route")
async def proxy_flight_route(callsign: str):
    cs = (callsign or "").strip().upper().replace(" ", "")
    if not cs:
        return {"ok": False, "error": "no callsign"}
    rec = _route_cache.get(cs)
    if rec and time.time() - rec["ts"] < 3600:
        return {"ok": True, "cached": True, **rec["data"]}
    http = await client()
    # Try adsbdb first (richer data), fall back to hexdb
    data = await _fetch_adsbdb_callsign(http, cs)
    if not data:
        fallback = await _fetch_hexdb_route(http, cs)
        if fallback:
            data = fallback
    if data and (data.get("origin") or data.get("destination")):
        if len(_route_cache) >= _ROUTE_CACHE_MAX and cs not in _route_cache:
            oldest = min(_route_cache, key=lambda k: _route_cache[k]["ts"])
            _route_cache.pop(oldest, None)
        _route_cache[cs] = {"data": data, "ts": time.time()}
        return {"ok": True, "cached": False, **data}
    if len(_route_cache) >= _ROUTE_CACHE_MAX and cs not in _route_cache:
        oldest = min(_route_cache, key=lambda k: _route_cache[k]["ts"])
        _route_cache.pop(oldest, None)
    _route_cache[cs] = {"data": {"origin": None, "destination": None, "source": "none"}, "ts": time.time()}
    return {"ok": False, "error": "no route data"}


# ─── Flight schedule: actual dep/arr times from OpenSky Network ─────
# OpenSky publishes community-observed ADS-B landings and takeoffs at
# every major airport. Free, no auth (400 req/day unauth). Data lags
# ~1-2h but is authoritative — it's when the aircraft was actually
# observed leaving the origin or touching down at the destination.
# We cache per airport per kind for 5 minutes to minimise quota use.
_opensky_board_cache: dict[tuple, dict] = {}
# ICAO codes for the major Australian airports we'll probe. Keep this
# list tight — each airport is 2 requests (dep + arr) per refresh.
_AUS_AIRPORTS_BY_IATA = {
    "SYD": "YSSY", "MEL": "YMML", "BNE": "YBBN", "PER": "YPPH",
    "ADL": "YPAD", "OOL": "YBCG", "CNS": "YBCS", "HBA": "YMHB",
    "DRW": "YPDN", "CBR": "YSCB", "AVV": "YMAV",
}
_AUS_AIRPORT_ICAOS = set(_AUS_AIRPORTS_BY_IATA.values())


async def _fetch_opensky_board(http, icao: str, kind: str, window_hours: int = 12):
    """kind ∈ {'departure','arrival'}. Returns list of raw OpenSky records."""
    key = (icao, kind)
    rec = _opensky_board_cache.get(key)
    if rec and time.time() - rec["ts"] < 300:
        return rec["data"]
    now = int(time.time())
    begin = now - window_hours * 3600
    try:
        r = await http.get(
            f"https://opensky-network.org/api/flights/{kind}",
            params={"airport": icao, "begin": begin, "end": now},
            headers=_HEADERS, timeout=10.0,
        )
        if r.status_code == 200:
            data = r.json() or []
            _opensky_board_cache[key] = {"data": data, "ts": time.time()}
            return data
        # Rate-limited or server error → short negative cache so we back off
    except Exception as exc:
        log.debug("OpenSky board fetch failed (%s %s): %s", icao, kind, exc)
    _opensky_board_cache[key] = {"data": [], "ts": time.time()}
    return []


@app.get("/proxy/flight-schedule")
async def proxy_flight_schedule(callsign: str, origin: str | None = None, destination: str | None = None):
    """
    Find actual dep/arr records for a callsign by scanning OpenSky's
    flight boards for Australian airports. If origin/destination ICAOs
    are provided we only scan those two; otherwise we scan the full
    Aus airport set (more requests but broader match).
    """
    cs = (callsign or "").strip().upper().replace(" ", "")
    if not cs:
        return {"ok": False, "error": "no callsign"}

    http = await client()

    # Decide which airports to scan
    scan_airports: list[str] = []
    if origin and origin.upper() in _AUS_AIRPORT_ICAOS:
        scan_airports.append(origin.upper())
    if destination and destination.upper() in _AUS_AIRPORT_ICAOS and destination.upper() not in scan_airports:
        scan_airports.append(destination.upper())
    # If no match in Aus, scan all Aus airports (useful for inbound intl)
    if not scan_airports:
        scan_airports = list(_AUS_AIRPORT_ICAOS)

    # Fetch boards in parallel
    fetches = []
    for icao in scan_airports:
        fetches.append(_fetch_opensky_board(http, icao, "departure"))
        fetches.append(_fetch_opensky_board(http, icao, "arrival"))
    results_raw = await asyncio.gather(*fetches, return_exceptions=True)

    departure_rec = None
    arrival_rec = None
    idx = 0
    for icao in scan_airports:
        dep = results_raw[idx] if not isinstance(results_raw[idx], Exception) else []
        arr = results_raw[idx + 1] if not isinstance(results_raw[idx + 1], Exception) else []
        idx += 2
        for rec in (dep or []):
            rc = (rec.get("callsign") or "").strip().upper()
            if rc == cs:
                # Use the most recent match (highest firstSeen)
                if not departure_rec or (rec.get("firstSeen") or 0) > (departure_rec.get("firstSeen") or 0):
                    departure_rec = {**rec, "_airport": icao}
        for rec in (arr or []):
            rc = (rec.get("callsign") or "").strip().upper()
            if rc == cs:
                if not arrival_rec or (rec.get("lastSeen") or 0) > (arrival_rec.get("lastSeen") or 0):
                    arrival_rec = {**rec, "_airport": icao}

    def _shape(rec):
        if not rec: return None
        return {
            "airport": rec.get("_airport"),
            "first_seen": rec.get("firstSeen"),        # unix epoch
            "last_seen": rec.get("lastSeen"),          # unix epoch
            "est_dep_airport": rec.get("estDepartureAirport"),
            "est_arr_airport": rec.get("estArrivalAirport"),
            "departure_airport_candidates_count": rec.get("departureAirportCandidatesCount"),
            "arrival_airport_candidates_count": rec.get("arrivalAirportCandidatesCount"),
        }

    return {
        "ok": bool(departure_rec or arrival_rec),
        "source": "opensky",
        "note": "Actual times from community ADS-B observations; typically lags ~1-2h. Scheduled forecast times are not available from free feeds.",
        "departure": _shape(departure_rec),
        "arrival": _shape(arrival_rec),
        "scanned_airports": scan_airports,
    }


# ─── Airport details (ICAO → city/country/name) ─────────────
# Source: hexdb.io — airport details by ICAO code. Cache for a day.
_airport_cache: dict[str, dict] = {}

@app.get("/proxy/airport")
async def proxy_airport(icao: str):
    code = (icao or "").strip().upper()
    if not code:
        return {"ok": False}
    rec = _airport_cache.get(code)
    if rec and time.time() - rec["ts"] < 86400:
        return {"ok": True, "cached": True, **rec["data"]}
    http = await client()
    try:
        r = await http.get(
            f"https://hexdb.io/airport-info?icao={code}",
            headers=_HEADERS, timeout=5.0,
        )
        if r.status_code == 200:
            j = r.json()
            data = {
                "icao": code,
                "iata": j.get("iata"),
                "name": j.get("airport"),
                "city": j.get("region_name"),
                "country": j.get("country_code"),
                "lat": j.get("latitude"),
                "lng": j.get("longitude"),
            }
            _airport_cache[code] = {"data": data, "ts": time.time()}
            return {"ok": True, "cached": False, **data}
    except Exception as exc:
        log.debug("Airport lookup failed for %s: %s", code, exc)
    _airport_cache[code] = {"data": {"icao": code}, "ts": time.time()}
    return {"ok": False, "icao": code}


# ─── Aircraft details (hex → operator, manufacturer, type) ──
# Source: hexdb.io — aircraft registration DB. Very cacheable: a frame's
# registration rarely changes once it's flying. 7 day cache.
_aircraft_cache: dict[str, dict] = {}

@app.get("/proxy/aircraft-info")
async def proxy_aircraft_info(hex: str):
    h = (hex or "").strip().lower()
    if not h:
        return {"ok": False}
    rec = _aircraft_cache.get(h)
    if rec and time.time() - rec["ts"] < 7 * 86400:
        return {"ok": True, "cached": True, **rec["data"]}
    http = await client()
    try:
        r = await http.get(
            f"https://hexdb.io/api/v1/aircraft/{h.upper()}",
            headers=_HEADERS, timeout=5.0,
        )
        if r.status_code == 200:
            j = r.json()
            data = {
                "hex": h,
                "registration": j.get("Registration"),
                "type": j.get("Type"),
                "icao_type": j.get("ICAOTypeCode"),
                "manufacturer": j.get("Manufacturer"),
                "operator": j.get("RegisteredOwners"),
                "owner": j.get("OperatorFlagCode"),
            }
            _aircraft_cache[h] = {"data": data, "ts": time.time()}
            return {"ok": True, "cached": False, **data}
    except Exception as exc:
        log.debug("Aircraft info lookup failed for %s: %s", h, exc)
    _aircraft_cache[h] = {"data": {"hex": h}, "ts": time.time()}
    return {"ok": False, "hex": h}


# ─── FIRES (multiple sources) — 120s cache ──────────────────
@app.get("/proxy/fires")
async def proxy_fires():
    c = cache_get("fires", 120)
    if c and c["data"]:
        return respond("Fire Services", c["data"], cached=True)

    http = await client()
    errors = []

    # Source 1: NSW RFS Major Incidents (well-maintained GeoJSON feed)
    try:
        r = await http.get(
            "https://www.rfs.nsw.gov.au/feeds/majorIncidents.json",
            headers=_HEADERS,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("features"):
            cache_set("fires", data)
            return respond("NSW RFS", data, cached=False)
    except Exception as e:
        errors.append(f"NSW RFS major: {e}")

    # Source 2: NSW RFS all incidents
    try:
        r = await http.get(
            "https://www.rfs.nsw.gov.au/feeds/majorIncidents.json",
            headers={**_HEADERS, "Accept": "application/geo+json"},
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("features"):
                cache_set("fires", data)
                return respond("NSW RFS", data, cached=False)
    except Exception as e:
        errors.append(f"NSW RFS alt: {e}")

    # Source 3: GA Sentinel Hotspots (last 72 hours — bigger window for coverage)
    try:
        r = await http.get(
            "https://hotspots.dea.ga.gov.au/geoserver/public/wfs"
            "?service=WFS&version=2.0.0&request=GetFeature"
            "&typeNames=public:hotspots_last_72hrs"
            "&outputFormat=application/json"
            "&count=500",
            headers=_HEADERS,
            timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("features"):
            cache_set("fires", data)
            return respond("GA Hotspots", data, cached=False)
    except Exception as e:
        errors.append(f"GA Hotspots: {e}")

    # Source 4: Emergency Victoria (CFA) incidents
    try:
        r = await http.get(
            "https://data.emergency.vic.gov.au/Show?pageId=getIncidentJSON",
            headers=_HEADERS,
        )
        r.raise_for_status()
        raw = r.json()
        # Convert to GeoJSON
        features = []
        for item in raw.get("results", raw if isinstance(raw, list) else []):
            if isinstance(item, dict) and item.get("lat") and item.get("lon"):
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(item["lon"]), float(item["lat"])]},
                    "properties": {
                        "title": item.get("feedType", "") + " - " + item.get("category1", ""),
                        "status": item.get("status", ""),
                        "type": item.get("feedType", ""),
                    }
                })
        if features:
            data = {"type": "FeatureCollection", "features": features}
            cache_set("fires", data)
            return respond("Emergency Vic", data, cached=False)
    except Exception as e:
        errors.append(f"Emergency Vic: {e}")

    # Source 5: NASA FIRMS (no key needed for CSV, but let's try the open GeoJSON)
    try:
        r = await http.get(
            "https://firms.modaps.eosdis.nasa.gov/api/country/csv/VIIRS_SNPP_NRT/AUS/1",
            headers=_HEADERS,
            timeout=20.0,
        )
        if r.status_code == 200 and r.text.strip():
            import csv
            import io
            reader = csv.DictReader(io.StringIO(r.text))
            features = []
            for row in reader:
                try:
                    lat, lon = float(row.get("latitude", 0)), float(row.get("longitude", 0))
                    if lat and lon:
                        features.append({
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [lon, lat]},
                            "properties": {
                                "title": f"VIIRS Hotspot ({row.get('confidence', 'n')})",
                                "brightness": row.get("bright_ti4", ""),
                                "frp": row.get("frp", ""),
                                "acq_date": row.get("acq_date", ""),
                            }
                        })
                except (ValueError, TypeError):
                    continue
            if features:
                data = {"type": "FeatureCollection", "features": features}
                cache_set("fires", data)
                return respond("NASA FIRMS", data, cached=False)
    except Exception as e:
        errors.append(f"NASA FIRMS: {e}")

    # All failed
    all_errors = "; ".join(errors) if errors else "All fire feeds failed"
    if "fires" in _cache and _cache["fires"]["data"]:
        return respond("Fire Services", _cache["fires"]["data"], cached=True, error=all_errors)

    # Return empty GeoJSON so frontend doesn't break
    empty = {"type": "FeatureCollection", "features": []}
    return respond("Fire Services", empty, cached=False, error=all_errors)


# ─── ASX 200 (Yahoo Finance) — 60s cache ────────────────────
@app.get("/proxy/asx")
async def proxy_asx():
    c = cache_get("asx", 60)
    if c and c["data"]:
        return respond("Yahoo Finance", c["data"], cached=True)

    http = await client()
    # Try Yahoo Finance v8
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EAXJO?range=1d&interval=5m"
    try:
        r = await http.get(url, headers=_HEADERS)
        r.raise_for_status()
        raw = r.json()
        result = raw.get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])

        data = {
            "symbol": "^AXJO",
            "name": "S&P/ASX 200",
            "price": meta.get("regularMarketPrice"),
            "previousClose": meta.get("chartPreviousClose") or meta.get("previousClose"),
            "change": None,
            "changePercent": None,
            "currency": meta.get("currency", "AUD"),
            "marketState": meta.get("currentTradingPeriod", {}).get("regular", {}).get("timezone", ""),
            "sparkline": [c for c in closes[-48:] if c is not None],  # last 4 hours of 5min bars
        }
        if data["price"] and data["previousClose"]:
            data["change"] = round(data["price"] - data["previousClose"], 2)
            data["changePercent"] = round((data["change"] / data["previousClose"]) * 100, 2)

        cache_set("asx", data)
        return respond("Yahoo Finance", data, cached=False)
    except Exception as e:
        if "asx" in _cache and _cache["asx"]["data"]:
            return respond("Yahoo Finance", _cache["asx"]["data"], cached=True, error=str(e))
        return respond("Yahoo Finance", None, cached=False, error=str(e))


# ─── FOREX (Yahoo Finance) — 60s cache ──────────────────────
@app.get("/proxy/forex")
async def proxy_forex():
    c = cache_get("forex", 60)
    if c and c["data"]:
        return respond("Yahoo Finance", c["data"], cached=True)

    http = await client()
    pairs = {
        "AUDUSD=X": "USD",
        "AUDEUR=X": "EUR",
        "AUDGBP=X": "GBP",
        "AUDJPY=X": "JPY",
    }
    results = {}
    errors = []

    for ticker, label in pairs.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=5m"
        try:
            r = await http.get(url, headers=_HEADERS)
            r.raise_for_status()
            raw = r.json()
            meta = raw.get("chart", {}).get("result", [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            change = round(price - prev, 4) if price and prev else None
            pct = round((change / prev) * 100, 2) if change and prev else None
            results[label] = {
                "rate": price,
                "previousClose": prev,
                "change": change,
                "changePercent": pct,
            }
        except Exception as e:
            errors.append(f"{label}: {e}")

    if results:
        cache_set("forex", results)
        return respond("Yahoo Finance", results, cached=False,
                       error="; ".join(errors) if errors else None)

    if "forex" in _cache and _cache["forex"]["data"]:
        return respond("Yahoo Finance", _cache["forex"]["data"], cached=True,
                       error="; ".join(errors))
    return respond("Yahoo Finance", None, cached=False, error="; ".join(errors))


# ─── ENERGY (AEMO) — 5min cache ─────────────────────────────
@app.get("/proxy/energy")
async def proxy_energy():
    c = cache_get("energy", 300)
    if c and c["data"]:
        return respond("AEMO", c["data"], cached=True)

    http = await client()
    errors = []

    # Try AEMO visualisations API (the working one as of 2025+)
    aemo_urls = [
        "https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY",
        "https://aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY",
        "https://www.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY",
    ]

    for url in aemo_urls:
        try:
            r = await http.get(url, headers=_HEADERS, timeout=15.0)
            r.raise_for_status()
            raw = r.json()

            # Parse AEMO response — can be array of region objects or nested
            regions = raw if isinstance(raw, list) else raw.get("ELEC_NEM_SUMMARY", raw.get("data", []))
            if isinstance(regions, list) and regions:
                total_demand = sum(float(r.get("TOTALDEMAND", r.get("totaldemand", 0))) for r in regions)
                # Build fuel mix from regions
                fuel_types = {}
                for region in regions:
                    for key, val in region.items():
                        k = key.upper()
                        if any(fuel in k for fuel in ["COAL", "GAS", "HYDRO", "WIND", "SOLAR", "BATTERY", "BIOMASS"]):
                            fuel_types[k] = fuel_types.get(k, 0) + float(val or 0)

                data = {
                    "totalDemand": round(total_demand, 1),
                    "regions": regions,
                    "fuelMix": fuel_types,
                }
                cache_set("energy", data)
                return respond("AEMO", data, cached=False)
        except Exception as e:
            errors.append(f"{url}: {e}")

    # Fallback: scrape AEMO NEM widget page for current demand figure
    try:
        r = await http.get(
            "https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/data-dashboard-nem",
            headers=_HEADERS, timeout=15.0
        )
        if r.status_code == 200:
            # Try to extract demand from page content
            text = r.text
            # Look for demand figures in page (usually in script tags or data attrs)
            demand_match = re.search(r'totalDemand["\s:]+(\d[\d,.]+)', text)
            if demand_match:
                demand_val = float(demand_match.group(1).replace(",", ""))
                data = {"totalDemand": demand_val, "regions": [], "fuelMix": {}}
                cache_set("energy", data)
                return respond("AEMO (scraped)", data, cached=False)
    except Exception as e:
        errors.append(f"AEMO scrape: {e}")

    err_msg = "; ".join(errors) if errors else "AEMO feeds unavailable"
    if "energy" in _cache and _cache["energy"]["data"]:
        return respond("AEMO", _cache["energy"]["data"], cached=True, error=err_msg)
    return respond("AEMO", None, cached=False, error=err_msg)


# ─── BOM WEATHER OBSERVATIONS — 5min cache ──────────────────
@app.get("/proxy/bom-observations")
async def proxy_bom_observations():
    """Fetch BOM weather observations for major cities (JSON feeds)."""
    c = cache_get("bom", 300)
    if c and c["data"]:
        return respond("Bureau of Meteorology", c["data"], cached=True)

    http = await client()
    # BOM observation product IDs for major cities
    stations = {
        "Sydney": "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94768.json",
        "Melbourne": "http://www.bom.gov.au/fwo/IDV60901/IDV60901.95936.json",
        "Brisbane": "http://www.bom.gov.au/fwo/IDQ60901/IDQ60901.94576.json",
        "Perth": "http://www.bom.gov.au/fwo/IDW60901/IDW60901.94610.json",
        "Adelaide": "http://www.bom.gov.au/fwo/IDS60901/IDS60901.94672.json",
        "Hobart": "http://www.bom.gov.au/fwo/IDT60901/IDT60901.94970.json",
        "Darwin": "http://www.bom.gov.au/fwo/IDD60901/IDD60901.94120.json",
        "Canberra": "http://www.bom.gov.au/fwo/IDN60901/IDN60901.94926.json",
    }
    results = {}
    for city, url in stations.items():
        try:
            r = await http.get(url, headers=_HEADERS)
            r.raise_for_status()
            obs = r.json()
            latest = obs.get("observations", {}).get("data", [{}])[0]
            results[city] = {
                "temp": latest.get("air_temp"),
                "feels_like": latest.get("apparent_t"),
                "humidity": latest.get("rel_hum"),
                "wind_spd_kmh": latest.get("wind_spd_kmh"),
                "wind_dir": latest.get("wind_dir"),
                "rain_since_9am": latest.get("rain_trace"),
                "pressure": latest.get("press"),
                "cloud": latest.get("cloud"),
                "local_date_time": latest.get("local_date_time_full"),
            }
        except Exception as exc:
            log.debug("BOM observation fetch failed for %s: %s", city, exc)

    if results:
        cache_set("bom", results)
        return respond("Bureau of Meteorology", results, cached=False)

    if "bom" in _cache and _cache["bom"]["data"]:
        return respond("Bureau of Meteorology", _cache["bom"]["data"], cached=True, error="BOM feeds unavailable")
    return respond("Bureau of Meteorology", None, cached=False, error="BOM feeds unavailable")


# ─── PARLIAMENT — 1h cache ───────────────────────────────────
@app.get("/proxy/parliament")
async def proxy_parliament():
    c = cache_get("parliament", 3600)
    if c and c["data"]:
        return respond("APH", c["data"], cached=True)

    http = await client()
    errors = []

    # Try multiple APH URLs (they reorganise often)
    aph_urls = [
        "https://www.aph.gov.au/live",
        "https://www.aph.gov.au/Parliamentary_Business/Chamber_documents/Live_Broadcast",
        "https://parlview.aph.gov.au/",
    ]

    for url in aph_urls:
        try:
            r = await http.get(url, headers=_HEADERS, timeout=15.0)
            if r.status_code == 200:
                html = r.text.lower()
                data = {
                    "house_sitting": ("house of representatives" in html or "house live" in html)
                                     and ("live" in html or "broadcasting" in html or "on air" in html),
                    "senate_sitting": ("senate" in html)
                                      and ("live" in html or "broadcasting" in html or "on air" in html),
                }
                data["sitting"] = data["house_sitting"] or data["senate_sitting"]
                cache_set("parliament", data)
                return respond("APH", data, cached=False)
        except Exception as e:
            errors.append(f"{url}: {e}")

    # Try to determine sitting days from the parliamentary calendar
    try:
        r = await http.get(
            "https://www.aph.gov.au/Parliamentary_Business/Sitting_Calendar",
            headers=_HEADERS, timeout=15.0,
        )
        if r.status_code == 200:
            html = r.text.lower()
            today_str = datetime.now().strftime("%-d %B %Y").lower()
            # Very rough check — if today's date appears with "sitting" nearby
            is_sitting_day = today_str in html or "sitting" in html
            data = {
                "house_sitting": False,
                "senate_sitting": False,
                "sitting": False,
                "note": "Calendar-based estimate" if is_sitting_day else "Non-sitting period",
            }
            cache_set("parliament", data)
            return respond("APH (calendar)", data, cached=False)
    except Exception as e:
        errors.append(f"Calendar: {e}")

    err_msg = "; ".join(errors) if errors else "APH unavailable"
    if "parliament" in _cache and _cache["parliament"]["data"]:
        return respond("APH", _cache["parliament"]["data"], cached=True, error=err_msg)
    return respond("APH", {"sitting": False, "house_sitting": False, "senate_sitting": False,
                           "note": "Unable to determine"}, cached=False, error=err_msg)


# ─── ABS Economic Data — 24h cache ──────────────────────────

def _extract_sdmx_last_value(raw: dict) -> float | None:
    """Extract the last observation value from SDMX JSON response."""
    obs = raw.get("dataSets", [{}])[0].get("observations", {})
    if not obs:
        # Try series-level structure
        series = raw.get("dataSets", [{}])[0].get("series", {})
        for s_key in series:
            obs = series[s_key].get("observations", {})
            if obs:
                break
    if obs:
        last_key = sorted(obs.keys())[-1]
        val = obs[last_key]
        return val[0] if isinstance(val, list) and val else val
    return None


async def _try_abs_query(http, urls: list[str], headers: dict) -> float | None:
    """Try multiple ABS URL variants, return first successful value."""
    for url in urls:
        try:
            r = await http.get(url, headers=headers, timeout=20.0)
            if r.status_code == 200:
                val = _extract_sdmx_last_value(r.json())
                if val is not None:
                    return float(val)
        except Exception:
            continue
    return None


@app.get("/proxy/abs")
async def proxy_abs():
    c = cache_get("abs", 86400)
    if c and c["data"]:
        return respond("ABS", c["data"], cached=True)

    http = await client()
    data = {}
    errors = []

    abs_base = "https://data.api.abs.gov.au/rest/data"
    abs_headers = {**_HEADERS, "Accept": "application/vnd.sdmx.data+json"}

    # CPI — try multiple query formats (dimension order varies by version)
    cpi_urls = [
        f"{abs_base}/ABS,CPI,1.1.0/1+2+3.10001.10.50.Q?startPeriod=2024-Q1",
        f"{abs_base}/ABS,CPI,1.1.0/1.10001.10.50.Q?startPeriod=2024-Q1",
        f"{abs_base}/CPI/1.10001.10.50.Q?startPeriod=2024-Q1",
    ]
    val = await _try_abs_query(http, cpi_urls, abs_headers)
    if val is not None:
        data["cpi_yoy"] = val
    else:
        errors.append("CPI: all query formats failed")

    # Unemployment — try multiple dataflow IDs
    unemp_urls = [
        f"{abs_base}/ABS,LF,1.0.0/1.14.3.1599.20.M?startPeriod=2024-01",
        f"{abs_base}/ABS,LF,1.1.0/1.14.3.1599.20.M?startPeriod=2024-01",
        f"{abs_base}/LF/1.14.3.1599.20.M?startPeriod=2024-01",
        # Simpler key: total unemployed rate, seasonally adjusted, Australia
        f"{abs_base}/ABS,LF,1.0.0/M13.3.1599.20.M?startPeriod=2024-01",
    ]
    val = await _try_abs_query(http, unemp_urls, abs_headers)
    if val is not None:
        data["unemployment_rate"] = val
    else:
        errors.append("Unemployment: all query formats failed")

    # Population — the ABS SDMX API dimension keys change frequently and
    # return 422 on most queries. The most reliable source is the ABS
    # population clock page which always shows the current estimate.
    pop_scraped = False
    try:
        r = await http.get(
            "https://www.abs.gov.au/statistics/people/population/population-clock-pyramid",
            headers=_HEADERS, timeout=15.0,
        )
        if r.status_code == 200:
            for m in re.finditer(r'(\d{2,3}[,. ]\d{3}[,. ]\d{3})', r.text[:50000]):
                num = int(re.sub(r'[,. ]', '', m.group(1)))
                if 20_000_000 < num < 40_000_000:
                    data["population"] = num
                    pop_scraped = True
                    break
    except Exception:
        pass
    if not pop_scraped:
        # Fallback: try SDMX (often 422 due to changing dimension keys)
        pop_urls = [
            f"{abs_base}/ABS,ERP_Q/1.1.AUS.Q?startPeriod=2024-Q1",
            f"{abs_base}/ABS,ERP_Q,1.0.0/1.1.AUS.Q?startPeriod=2024-Q1",
            f"{abs_base}/ABS,NRP,1.0.0/1.AUS.ERP.A?startPeriod=2023",
        ]
        val = await _try_abs_query(http, pop_urls, abs_headers)
        if val is not None:
            if val < 100_000:
                val = val * 1000
            data["population"] = val
        else:
            errors.append("Population: all sources failed")

    # GDP growth
    gdp_urls = [
        f"{abs_base}/ABS,NAQ,1.0.0/1.GDP.10.50.Q?startPeriod=2024-Q1",
        f"{abs_base}/ABS,ANA,1.0.0/1.GDP.10.50.Q?startPeriod=2024-Q1",
        f"{abs_base}/NAQ/1.GDP.10.50.Q?startPeriod=2024-Q1",
    ]
    val = await _try_abs_query(http, gdp_urls, abs_headers)
    if val is not None:
        data["gdp_growth"] = val
    else:
        errors.append("GDP: all query formats failed")

    # Fallback: scrape ABS homepage for headline indicators
    if not data:
        try:
            r = await http.get("https://www.abs.gov.au/", headers=_HEADERS, timeout=15.0)
            if r.status_code == 200:
                text = r.text
                # CPI
                m = re.search(r'(?:CPI|consumer price).*?(\d+\.\d+)\s*(?:per cent|%)', text, re.I)
                if m:
                    data["cpi_yoy"] = float(m.group(1))
                # Unemployment
                m = re.search(r'(?:unemployment|jobless).*?(\d+\.\d+)\s*(?:per cent|%)', text, re.I)
                if m:
                    data["unemployment_rate"] = float(m.group(1))
                # Population — validate scraped value is plausible
                m = re.search(r'(?:population).*?([\d,]+(?:\.\d+)?)\s*(?:million)?', text, re.I)
                if m:
                    pop_str = m.group(1).replace(",", "")
                    pop = float(pop_str)
                    if 20 <= pop <= 30:
                        # Reported in millions (e.g. "27.1 million")
                        pop = pop * 1_000_000
                    elif 20_000 <= pop <= 35_000:
                        # Reported in thousands
                        pop = pop * 1_000
                    elif 20_000_000 <= pop <= 35_000_000:
                        pass  # Already in persons
                    else:
                        pop = None  # Implausible value, discard
                    if pop is not None:
                        data["population"] = pop
        except Exception as e:
            errors.append(f"ABS scrape: {e}")

    if data:
        cache_set("abs", data)
        return respond("ABS", data, cached=False,
                       error="; ".join(errors) if errors else None)

    err_msg = "; ".join(errors) if errors else "ABS API unavailable"
    if "abs" in _cache and _cache["abs"]["data"]:
        return respond("ABS", _cache["abs"]["data"], cached=True, error=err_msg)
    return respond("ABS", None, cached=False, error=err_msg)


# ─── FUEL PRICES — NSW FuelCheck (OAuth, station-level) ────────
#
# NSW FuelCheck via api.onegov.nsw.gov.au. Free, requires OAuth2
# client-credentials flow — credentials live in the .env file
# (NSW_FUEL_API_KEY / NSW_FUEL_BASIC_AUTH).
#
# Flow:
#   1. POST /oauth/client_credential/accesstoken?grant_type=client_credentials
#      with Authorization: Basic <base64(key:secret)>  → access_token (~12h)
#   2. GET /FuelPriceCheck/v1/fuel/prices with headers:
#        Authorization: Bearer <token>
#        apikey: <key>
#        transactionid: <uuid>
#        requesttimestamp: DD/MM/YYYY HH:MM:SS AM|PM
#
# Response has `stations[]` and `prices[]` which we zip on stationcode.
# NSW fuel codes → our internal product keys:
_NSW_FUEL_CODE_MAP = {
    "U91": "ULP", "E10": "E10", "P95": "P95", "P98": "P98",
    "DL": "DIESEL", "PDL": "DIESEL", "LPG": "LPG",
}

_nsw_token: dict[str, Any] = {"token": None, "exp": 0.0}
_nsw_stations_cache: dict[str, Any] = {"data": None, "ts": 0.0}


async def _nsw_get_token(http: httpx.AsyncClient) -> str | None:
    """Client-credentials token with a 10-min safety margin."""
    now = time.time()
    if _nsw_token["token"] and now < _nsw_token["exp"] - 600:
        return _nsw_token["token"]
    basic = os.environ.get("NSW_FUEL_BASIC_AUTH", "").strip()
    if not basic:
        return None
    try:
        r = await http.get(
            "https://api.onegov.nsw.gov.au/oauth/client_credential/accesstoken",
            params={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}"},
            timeout=15.0,
        )
        if r.status_code != 200:
            return None
        j = r.json()
        tok = j.get("access_token")
        ttl = int(j.get("expires_in", 43200))
        if not tok:
            return None
        _nsw_token["token"] = tok
        _nsw_token["exp"] = now + ttl
        return tok
    except Exception:
        return None


async def _nsw_fetch_all(http: httpx.AsyncClient) -> dict | None:
    """Return {stations: [...], prices: [...]} or None."""
    # Cache 30 min — NSW data doesn't move faster than that
    rec = _nsw_stations_cache
    if rec["data"] and time.time() - rec["ts"] < 1800:
        return rec["data"]
    token = await _nsw_get_token(http)
    api_key = os.environ.get("NSW_FUEL_API_KEY", "").strip()
    if not token or not api_key:
        return None
    # Timestamp format NSW expects: DD/MM/YYYY HH:MM:SS AM|PM (UTC).
    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y %I:%M:%S %p")
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": api_key,
        "transactionid": uuid.uuid4().hex,
        "requesttimestamp": ts,
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    for path in ("/FuelPriceCheck/v1/fuel/prices",
                 "/FuelPriceCheck/v2/fuel/prices"):
        try:
            r = await http.get(
                f"https://api.onegov.nsw.gov.au{path}",
                headers=headers, timeout=20.0,
            )
            if r.status_code == 200:
                j = r.json()
                stations = j.get("stations") or []
                prices = j.get("prices") or []
                if stations and prices:
                    data = {"stations": stations, "prices": prices}
                    _nsw_stations_cache["data"] = data
                    _nsw_stations_cache["ts"] = time.time()
                    return data
        except Exception:
            continue
    return None


def _nsw_build_station_list(raw: dict, product_key: str) -> list[dict]:
    """Return our standard station dict shape filtered to one product."""
    if not raw:
        return []
    # Map product_key ("ULP", "DIESEL"…) to accepted NSW fueltype codes
    nsw_codes = {c for c, k in _NSW_FUEL_CODE_MAP.items() if k == product_key}
    by_code: dict[str, dict] = {}
    for s in raw.get("stations", []):
        code = str(s.get("code") or s.get("stationcode") or "")
        if code:
            by_code[code] = s
    out: list[dict] = []
    for p in raw.get("prices", []):
        ft = str(p.get("fueltype") or "").upper()
        if ft not in nsw_codes:
            continue
        code = str(p.get("stationcode") or "")
        s = by_code.get(code)
        if not s:
            continue
        loc = s.get("location") or {}
        try:
            lat = float(loc.get("latitude"))
            lng = float(loc.get("longitude"))
            price = float(p.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0 or (lat == 0 and lng == 0):
            continue
        out.append({
            "name": s.get("name") or s.get("brand") or "Station",
            "brand": s.get("brand") or "",
            "address": s.get("address") or "",
            "suburb": s.get("suburb") or s.get("state") or "NSW",
            "price": round(price, 1),
            "lat": lat,
            "lng": lng,
            "product": ft,
            "date": p.get("lastupdated") or "",
            "state": "NSW",
        })
    return out


# ─── FUEL PRICES — FuelWatch WA (station-level + averages) ──
#
# Coverage: Western Australia only. FuelWatch is a WA government
# service that publishes every station's daily regulated price at no
# cost and without API keys. Other states (NSW FuelCheck, QLD FPRS,
# SA RealTimePrice) have free APIs too but all require registration
# for an API key — which the user would have to apply for.
#
# FuelWatch product codes (Product= query param):
#   1 = ULP 91,  2 = Premium 95,  5 = Premium 98
#   3 = Diesel,  12 = E10,  4 = LPG
# FuelWatch region codes (Region= query param, optional — omit for Perth):
#   Numeric IDs 25-52 cover regional WA. Omitting gives Perth metro.
FUELWATCH_PRODUCTS = {
    "ULP":    1,
    "P95":    2,
    "P98":    5,
    "DIESEL": 3,
    "E10":    12,
    "LPG":    4,
}
# Full WA region set (Perth = default when Region is omitted; others 25-52)
FUELWATCH_REGIONS: list[int | None] = [None] + list(range(25, 53))

import xml.etree.ElementTree as ET

_fuel_stations_cache: dict[str, dict] = {}


async def _fetch_fuelwatch_rss(http: httpx.AsyncClient, product_code: int, region: int | None) -> list[dict]:
    """Fetch one product × one region from FuelWatch and parse to a list of
    station dicts. Returns [] on any failure — the caller merges results."""
    params: dict[str, Any] = {"Product": product_code}
    if region is not None:
        params["Region"] = region
    try:
        r = await http.get(
            "https://www.fuelwatch.wa.gov.au/fuelwatch/fuelWatchRSS",
            params=params, headers=_HEADERS, timeout=15.0,
        )
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.text)
    except Exception:
        return []

    out: list[dict] = []
    # Namespace used in FuelWatch RSS
    ns = {"fw": "http://www.fuelwatch.wa.gov.au"}
    for item in root.iter("item"):
        def _get(tag_local: str) -> str | None:
            # Try with namespace first, then without (RSS often mixes these)
            el = item.find(f"fw:{tag_local}", ns)
            if el is None:
                el = item.find(tag_local)
            return el.text.strip() if (el is not None and el.text) else None
        try:
            price_txt = _get("price")
            lat_txt = _get("latitude")
            lng_txt = _get("longitude")
            if not price_txt or not lat_txt or not lng_txt:
                continue
            price = float(price_txt)
            lat = float(lat_txt)
            lng = float(lng_txt)
            if price <= 0 or (lat == 0 and lng == 0):
                continue
            out.append({
                "name": _get("trading-name") or _get("title") or "Station",
                "brand": _get("brand") or "",
                "address": _get("address") or "",
                "suburb": _get("location") or "",
                "price": round(price, 1),
                "lat": lat,
                "lng": lng,
                "product": _get("product") or "",
                "date": _get("date") or "",
            })
        except Exception:
            continue
    return out


async def _load_all_wa_stations(http: httpx.AsyncClient, product_code: int) -> list[dict]:
    """Fetch Perth metro + all regional regions in parallel, dedup."""
    fetches = [_fetch_fuelwatch_rss(http, product_code, r) for r in FUELWATCH_REGIONS]
    results = await asyncio.gather(*fetches, return_exceptions=True)
    merged: list[dict] = []
    seen: set = set()
    for res in results:
        if isinstance(res, Exception) or not res:
            continue
        for s in res:
            key = (round(s["lat"], 4), round(s["lng"], 4), s.get("brand", ""))
            if key in seen:
                continue
            seen.add(key)
            merged.append(s)
    return merged


def _summarise(prices_list: list[float]) -> dict | None:
    prices = sorted(p for p in prices_list if p and p > 0)
    n = len(prices)
    if n == 0:
        return None
    return {
        "min": prices[0],
        "max": prices[-1],
        "median": prices[n // 2],
        "avg": round(sum(prices) / n, 1),
        "count": n,
    }


@app.get("/proxy/fuel")
async def proxy_fuel():
    """
    Dashboard tile summary — combines NSW FuelCheck (entire state) and
    FuelWatch WA (Perth metro) for ULP / Diesel / E10.

    Response shape (backward-compatible):
      {
        state: "AU (NSW + WA)",
        scope: "NSW statewide + Perth metro",
        products: {ULP: {min, max, median, avg, count}, ...},
        byState:  {NSW: {ULP: {...}, ...}, WA: {...}},
        ulp/diesel/e10: median (flat fields),
      }
    """
    c = cache_get("fuel", 1800)
    if c and c["data"]:
        return respond("FuelCheck + FuelWatch", c["data"], cached=True)

    http = await client()
    products_wa = [("ULP", 1), ("DIESEL", 3), ("E10", 12)]
    wa_task = asyncio.gather(
        *[_fetch_fuelwatch_rss(http, code, None) for _, code in products_wa],
        return_exceptions=True,
    )
    nsw_task = _nsw_fetch_all(http)
    wa_results, nsw_raw = await asyncio.gather(wa_task, nsw_task)

    by_state: dict[str, dict] = {"NSW": {}, "WA": {}}
    all_prices: dict[str, list[float]] = {"ULP": [], "DIESEL": [], "E10": []}

    for (key, _code), res in zip(products_wa, wa_results):
        if isinstance(res, Exception) or not res:
            continue
        prices = [s["price"] for s in res]
        summary = _summarise(prices)
        if summary:
            by_state["WA"][key] = summary
            all_prices[key].extend(prices)

    if nsw_raw:
        for key in ("ULP", "DIESEL", "E10"):
            stations = _nsw_build_station_list(nsw_raw, key)
            prices = [s["price"] for s in stations]
            summary = _summarise(prices)
            if summary:
                by_state["NSW"][key] = summary
                all_prices[key].extend(prices)

    covered = [st for st, v in by_state.items() if v]
    out: dict[str, Any] = {
        "state": "AU (" + " + ".join(covered) + ")" if covered else "AU",
        "scope": ", ".join(f"{s} {'statewide' if s == 'NSW' else 'metro'}" for s in covered),
        "products": {},
        "byState": by_state,
        "coverage": covered,
    }
    for key, plist in all_prices.items():
        s = _summarise(plist)
        if s:
            out["products"][key] = s
            out[key.lower()] = s["median"]

    if not out["products"]:
        if "fuel" in _cache and _cache["fuel"]["data"]:
            return respond("FuelCheck + FuelWatch", _cache["fuel"]["data"], cached=True,
                           error="Upstream fuel sources unavailable — serving stale data")
        return respond("FuelCheck + FuelWatch", None, cached=False,
                       error="Upstream fuel sources unavailable")
    cache_set("fuel", out)
    return respond("FuelCheck + FuelWatch", out, cached=False)


@app.get("/proxy/fuel-stations")
async def proxy_fuel_stations(product: str = "ULP", state: str = "ALL"):
    """
    Every station currently selling the given product, across supported
    states (NSW via FuelCheck, WA via FuelWatch). `state` may be
    "ALL" (default), "NSW", or "WA".
    """
    key = product.upper()
    state_filter = (state or "ALL").upper()
    product_code = FUELWATCH_PRODUCTS.get(key, 1)
    cache_key = f"stations_{product_code}_{state_filter}"
    rec = _fuel_stations_cache.get(cache_key)
    if rec and time.time() - rec["ts"] < 3600:
        return {
            "ok": True, "cached": True,
            "product": key, "coverage": rec.get("coverage", []),
            "count": len(rec["stations"]),
            "stations": rec["stations"],
        }

    http = await client()
    stations: list[dict] = []
    coverage: list[str] = []

    wa_task = _load_all_wa_stations(http, product_code) if state_filter in ("ALL", "WA") else None
    nsw_task = _nsw_fetch_all(http) if state_filter in ("ALL", "NSW") else None

    wa_res, nsw_res = await asyncio.gather(
        wa_task if wa_task else asyncio.sleep(0, result=None),
        nsw_task if nsw_task else asyncio.sleep(0, result=None),
    )

    if wa_res:
        for s in wa_res:
            s["state"] = "WA"
        stations.extend(wa_res)
        coverage.append("WA")
    if nsw_res:
        nsw_stations = _nsw_build_station_list(nsw_res, key)
        stations.extend(nsw_stations)
        if nsw_stations:
            coverage.append("NSW")

    _fuel_stations_cache[cache_key] = {
        "stations": stations, "ts": time.time(), "coverage": coverage,
    }
    return {
        "ok": True, "cached": False,
        "product": key, "coverage": coverage,
        "count": len(stations),
        "stations": stations,
        "note": ("Coverage: " + ", ".join(coverage) +
                 ". Other states (QLD, SA, VIC, NT, TAS) have free APIs but require separate keys."),
    }


# Postcode → lat/lng via Nominatim (OpenStreetMap). Free, no auth.
_postcode_cache: dict[str, dict] = {}

@app.get("/proxy/postcode")
async def proxy_postcode(code: str):
    pc = (code or "").strip()
    if not pc.isdigit() or not (3 <= len(pc) <= 4):
        return {"ok": False, "error": "Postcode must be 3 or 4 digits"}
    rec = _postcode_cache.get(pc)
    if rec and time.time() - rec["ts"] < 7 * 86400:
        return {"ok": True, "cached": True, **rec["data"]}
    # Zero-pad NT postcodes (800 → 0800) for OSM
    q = pc.zfill(4)
    http = await client()
    try:
        r = await http.get(
            "https://nominatim.openstreetmap.org/search",
            params={"postalcode": q, "countrycodes": "au", "format": "json", "limit": 1},
            headers={"User-Agent": "AtlasOfAustralia/1.0 (github.com/atlas-of-australia)"},
            timeout=10.0,
        )
        if r.status_code == 200:
            j = r.json() or []
            if j:
                top = j[0]
                data = {
                    "postcode": pc,
                    "lat": float(top["lat"]),
                    "lng": float(top["lon"]),
                    "display_name": top.get("display_name") or "",
                }
                _postcode_cache[pc] = {"data": data, "ts": time.time()}
                return {"ok": True, "cached": False, **data}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Postcode not found"}


# ─── RBA CASH RATE — 24h cache ──────────────────────────────
@app.get("/proxy/rba")
async def proxy_rba():
    c = cache_get("rba", 86400)
    if c and c["data"]:
        return respond("RBA", c["data"], cached=True)

    http = await client()
    errors = []

    # Primary: try RBA F1 historical CSV (cash rate target is last column)
    csv_urls = [
        "https://www.rba.gov.au/statistics/tables/xls/f01hist.csv",
        "https://www.rba.gov.au/statistics/tables/csv/f01hist.csv",
    ]
    for csv_url in csv_urls:
        try:
            r = await http.get(csv_url, headers=_HEADERS, timeout=15.0)
            if r.status_code == 200:
                lines = r.text.strip().splitlines()
                # Find the header row and the last data row
                # The CSV has a header row with "Cash Rate Target" or similar
                # and data rows with dates and rates
                header_idx = None
                target_col = None
                for i, line in enumerate(lines):
                    if "cash rate" in line.lower() or "target" in line.lower():
                        header_idx = i
                        cols = line.split(",")
                        for j, col in enumerate(cols):
                            if "target" in col.lower() or "cash rate" in col.lower():
                                target_col = j
                                break
                        break
                if header_idx is not None and target_col is not None:
                    # Read last non-empty data row
                    for line in reversed(lines[header_idx + 1:]):
                        parts = line.split(",")
                        if len(parts) > target_col and parts[target_col].strip():
                            try:
                                rate = float(parts[target_col].strip())
                                if 0.0 <= rate <= 15.0:
                                    data = {"cash_rate": rate, "source": "RBA CSV"}
                                    cache_set("rba", data)
                                    return respond("RBA", data, cached=False)
                            except ValueError:
                                continue
        except Exception as e:
            errors.append(f"{csv_url}: {e}")

    # Fallback: scrape multiple RBA HTML pages for cash rate
    rba_urls = [
        "https://www.rba.gov.au/statistics/cash-rate/",
        "https://www.rba.gov.au/monetary-policy/cash-rate-target/",
        "https://www.rba.gov.au/",
    ]

    # Match "4.10 per cent" or "4.10%" or rate in <td> elements.
    # The RBA cash-rate page puts the rate in a plain <td> without units.
    rate_patterns = [
        r'(\d+\.?\d*)\s*per\s*cent',        # "4.10 per cent"
        r'(\d+\.?\d*)\s*%',                  # "4.10%"
        r'<td[^>]*>\s*(\d+\.\d+)\s*</td>',  # "<td>4.10</td>" (RBA table)
        r'cash\s*rate.*?(\d+\.?\d+)',        # "cash rate ... 4.10"
        r'target.*?(\d+\.?\d+)',             # "target ... 4.10"
    ]

    for url in rba_urls:
        try:
            r = await http.get(url, headers=_HEADERS, timeout=15.0)
            if r.status_code == 200:
                text = r.text
                for pattern in rate_patterns:
                    matches = re.findall(pattern, text, re.I)
                    for m in matches:
                        rate = float(m)
                        # Cash rate should be between 0.1 and 15.0
                        if 0.1 <= rate <= 15.0:
                            data = {"cash_rate": rate, "source": "RBA"}
                            cache_set("rba", data)
                            return respond("RBA", data, cached=False)
        except Exception as e:
            errors.append(f"{url}: {e}")

    # Fallback: try RBA media releases RSS for most recent rate decision
    try:
        r = await http.get(
            "https://www.rba.gov.au/rss/rss-cb-monetary-policy-changes.xml",
            headers=_HEADERS, timeout=15.0,
        )
        if r.status_code == 200:
            for pattern in rate_patterns:
                matches = re.findall(pattern, r.text, re.I)
                for m in matches:
                    rate = float(m)
                    if 0.1 <= rate <= 15.0:
                        data = {"cash_rate": rate, "source": "RBA RSS"}
                        cache_set("rba", data)
                        return respond("RBA", data, cached=False)
    except Exception as e:
        errors.append(f"RBA RSS: {e}")

    err_msg = "; ".join(errors) if errors else "RBA unavailable"
    if "rba" in _cache and _cache["rba"]["data"]:
        return respond("RBA", _cache["rba"]["data"], cached=True, error=err_msg)
    return respond("RBA", None, cached=False, error=err_msg)


# ═══════════════════════════════════════════════════════════════
# STATUS / HEALTH
# ═══════════════════════════════════════════════════════════════

# ─── Open-Meteo proxy with caching + stale fallback ───────────────
# Open-Meteo bills per *location*, not per HTTP call. With ~250 stations
# and a 5-min refresh that's ~70k calls/day vs the 10k/day free quota.
# This proxy collapses all clients onto a single shared cache and serves
# the last good payload when upstream rate-limits (HTTP 429) or fails.
_om_http_client: "httpx.AsyncClient | None" = None
_om_forecast_ttl = 55 * 60        # 55 min — frontend polls hourly, slight slack
_om_detail_ttl = 30 * 60          # 30 min — per-station detail (modal click)
_om_detail_cache: dict = {}
_OM_DETAIL_CACHE_MAX = 500

def _get_om_client() -> httpx.AsyncClient:
    global _om_http_client
    if _om_http_client is None:
        _om_http_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            headers=_HEADERS,
        )
    return _om_http_client

@app.get("/proxy/openmeteo")
async def proxy_openmeteo(
    latitude: str,
    longitude: str,
    current: str = "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,weather_code,apparent_temperature,precipitation",
    timezone_param: str = "auto",
):
    """Cached batch forecast for the weather panel. Returns last-known
    payload (with stale=true) when Open-Meteo 429s or fails."""
    key = f"openmeteo:{latitude}:{longitude}:{current}"
    now = time.time()
    entry = _cache.get(key)
    if entry and entry["data"] is not None and (now - entry["ts"]) < _om_forecast_ttl:
        return {"data": entry["data"], "stale": False, "cached_at": entry["ts"]}

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        f"&current={current}&timezone={timezone_param}"
    )
    upstream_err = None
    upstream_status = None
    try:
        http = _get_om_client()
        r = await http.get(url)
        if r.status_code == 200:
            data = r.json()
            cache_set(key, data)
            return {"data": data, "stale": False, "cached_at": time.time(),
                    "source": "open-meteo"}
        upstream_status = r.status_code
        upstream_err = f"Open-Meteo returned {r.status_code}"
    except Exception as e:
        upstream_err = str(e)

    # Open-Meteo failed. Try cached payload first (full coverage).
    if entry and entry["data"] is not None:
        return {"data": entry["data"], "stale": True, "source": "open-meteo",
                "cached_at": entry["ts"], "upstream_status": upstream_status,
                "error": upstream_err}

    # No cache — try BOM as a partial fallback. Returns fewer stations
    # (only the ~44 in BOM_STATION_MAP) but the panel won't go blank.
    try:
        bom_payload = await _bom_batch_fallback(latitude, longitude)
        if bom_payload and any(item.get("current") for item in bom_payload):
            return {"data": bom_payload, "stale": True, "source": "bom",
                    "upstream_status": upstream_status,
                    "error": f"{upstream_err} — falling back to BOM observations"}
    except Exception as bom_e:
        upstream_err = f"{upstream_err}; BOM fallback failed: {bom_e}"

    return {"data": None, "stale": True, "upstream_status": upstream_status,
            "error": upstream_err}


@app.get("/proxy/openmeteo/detail")
async def proxy_openmeteo_detail(latitude: float, longitude: float, force: int = 0):
    """Per-station detail for the weather modal (current + hourly + 7-day).
       Pass force=1 to bypass cache (used by the 'refresh' button)."""
    key = f"{round(latitude, 2)},{round(longitude, 2)}"
    now = time.time()
    cached = _om_detail_cache.get(key)
    if not force and cached and (now - cached["ts"]) < _om_detail_ttl:
        return {"data": cached["data"], "stale": False, "cached_at": cached["ts"]}

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,"
        "weather_code,wind_speed_10m,wind_direction_10m,pressure_msl,uv_index,is_day"
        "&hourly=temperature_2m,apparent_temperature,precipitation_probability,precipitation,"
        "weather_code,wind_speed_10m,relative_humidity_2m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "precipitation_probability_max,wind_speed_10m_max,sunrise,sunset,uv_index_max"
        "&timezone=auto&forecast_days=7"
    )
    try:
        http = _get_om_client()
        r = await http.get(url)
        if r.status_code == 200:
            data = r.json()
            if len(_om_detail_cache) > _OM_DETAIL_CACHE_MAX:
                oldest = min(_om_detail_cache.items(), key=lambda kv: kv[1]["ts"])[0]
                _om_detail_cache.pop(oldest, None)
            _om_detail_cache[key] = {"data": data, "ts": now}
            return {"data": data, "stale": False, "cached_at": now}
        if cached:
            return {"data": cached["data"], "stale": True,
                    "cached_at": cached["ts"], "upstream_status": r.status_code}
        return {"data": None, "stale": True, "upstream_status": r.status_code}
    except Exception as e:
        if cached:
            return {"data": cached["data"], "stale": True,
                    "cached_at": cached["ts"], "error": str(e)}
        return {"data": None, "stale": True, "error": str(e)}


# ─── Bureau of Meteorology proxy ────────────────────────────────
# BOM is the official Australian source. Three useful endpoints:
#   1. Per-station observations JSON (last 72h, updates every 30 min)
#   2. Per-state warnings (Atom XML — storms, flood, fire, wind, etc.)
#   3. Per-state forecast (XML)
# BOM blocks scrapers without a real-looking User-Agent. We use one and
# cache aggressively so we're a good citizen.
_BOM_HEADERS = {
    # BOM's WAF blocks anything containing "bot", "compatible", or a contact
    # URL in the User-Agent. A plain browser UA passes through.
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/xml, text/html, */*",
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": "http://www.bom.gov.au/",
}
_bom_http_client: "httpx.AsyncClient | None" = None
_bom_obs_cache: dict = {}      # key: "{product_id}:{wmo}" → {data, ts}
_bom_warn_cache: dict = {}     # key: state code (lowercase) → {data, ts}
_BOM_OBS_TTL = 25 * 60          # 25 min — BOM obs update every 30 min
_BOM_WARN_TTL = 5 * 60          # 5 min — warnings can move fast
_BOM_OBS_CACHE_MAX = 500

def _get_bom_client() -> httpx.AsyncClient:
    global _bom_http_client
    if _bom_http_client is None:
        _bom_http_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            headers=_BOM_HEADERS,
            follow_redirects=True,
        )
    return _bom_http_client

@app.get("/proxy/bom/observation")
async def proxy_bom_observation(product: str, wmo: int):
    """Latest observation for a single BOM weather station.
       e.g. /proxy/bom/observation?product=IDN60901&wmo=94768  (Sydney)"""
    # Whitelist product IDs to avoid open proxy abuse
    if not re.match(r"^ID[A-Z]\d{5}$", product):
        return Response(status_code=400, content=b"invalid product id")
    key = f"{product}:{wmo}"
    now = time.time()
    cached = _bom_obs_cache.get(key)
    if cached and (now - cached["ts"]) < _BOM_OBS_TTL:
        return {"data": cached["data"], "stale": False, "cached_at": cached["ts"]}

    url = f"http://www.bom.gov.au/fwo/{product}/{product}.{wmo}.json"
    try:
        http = _get_bom_client()
        r = await http.get(url)
        if r.status_code == 200:
            data = r.json()
            # Trim to just the most recent observation to keep cache small
            obs = (((data.get("observations") or {}).get("data")) or [])
            header = (((data.get("observations") or {}).get("header")) or [{}])[0]
            trimmed = {
                "header": header,
                "latest": obs[0] if obs else None,
                "history_24h": obs[:24] if obs else [],
            }
            if len(_bom_obs_cache) > _BOM_OBS_CACHE_MAX:
                oldest = min(_bom_obs_cache.items(), key=lambda kv: kv[1]["ts"])[0]
                _bom_obs_cache.pop(oldest, None)
            _bom_obs_cache[key] = {"data": trimmed, "ts": now}
            return {"data": trimmed, "stale": False, "cached_at": now}
        if cached:
            return {"data": cached["data"], "stale": True,
                    "cached_at": cached["ts"], "upstream_status": r.status_code}
        return {"data": None, "stale": True, "upstream_status": r.status_code}
    except Exception as e:
        if cached:
            return {"data": cached["data"], "stale": True,
                    "cached_at": cached["ts"], "error": str(e)}
        return {"data": None, "stale": True, "error": str(e)}


# State → warnings product ID. From BOM's IDZ00056 family (national index).
# These are Atom feeds with all current warnings of any type for the state.
_BOM_WARNINGS = {
    "nsw": "IDZ00054",
    "act": "IDZ00056",
    "nt":  "IDZ00057",
    "qld": "IDZ00058",
    "sa":  "IDZ00060",
    "tas": "IDZ00064",
    "vic": "IDZ00061",
    "wa":  "IDZ00065",
}

@app.get("/proxy/bom/warnings")
async def proxy_bom_warnings(state: str):
    """Active BOM warnings for a state (severe storm, flood, fire, wind, etc.)."""
    state = state.lower().strip()
    product = _BOM_WARNINGS.get(state)
    if not product:
        return Response(status_code=400, content=b"unknown state")
    now = time.time()
    cached = _bom_warn_cache.get(state)
    if cached and (now - cached["ts"]) < _BOM_WARN_TTL:
        return {"data": cached["data"], "stale": False, "cached_at": cached["ts"]}

    # The state warning summary page lists all current warning products
    url = f"http://www.bom.gov.au/fwo/{product}.warnings_{state}.xml"
    try:
        http = _get_bom_client()
        r = await http.get(url)
        if r.status_code == 200:
            warnings = _parse_bom_warnings_xml(r.text)
            payload = {"state": state.upper(), "warnings": warnings,
                       "count": len(warnings)}
            _bom_warn_cache[state] = {"data": payload, "ts": now}
            return {"data": payload, "stale": False, "cached_at": now}
        if cached:
            return {"data": cached["data"], "stale": True,
                    "cached_at": cached["ts"], "upstream_status": r.status_code}
        return {"data": {"state": state.upper(), "warnings": [], "count": 0},
                "stale": True, "upstream_status": r.status_code}
    except Exception as e:
        if cached:
            return {"data": cached["data"], "stale": True,
                    "cached_at": cached["ts"], "error": str(e)}
        return {"data": {"state": state.upper(), "warnings": [], "count": 0},
                "stale": True, "error": str(e)}


def _parse_bom_warnings_xml(xml_text: str) -> list[dict]:
    """Parse BOM warning summary Atom/RSS into a list of warnings.
    BOM uses a few different XML shapes — we extract whatever <entry>
    or <item> elements we can find and pull out title/summary/link/issued."""
    import xml.etree.ElementTree as ET
    out: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    # Strip XML namespaces for easier matching
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    for entry in list(root.iter("entry")) + list(root.iter("item")):
        title = (entry.findtext("title") or "").strip()
        summary = (entry.findtext("summary") or entry.findtext("description") or "").strip()
        link_el = entry.find("link")
        link = (link_el.get("href") if link_el is not None and link_el.get("href")
                else (entry.findtext("link") or "")).strip()
        issued = (entry.findtext("updated") or entry.findtext("published")
                  or entry.findtext("pubDate") or "").strip()
        # Classify severity from title keywords
        t = title.lower()
        if any(k in t for k in ["severe", "emergency", "major"]):
            severity = "severe"
        elif any(k in t for k in ["warning"]):
            severity = "warning"
        elif any(k in t for k in ["watch", "advice"]):
            severity = "watch"
        else:
            severity = "info"
        # Type from keywords
        kind = "general"
        for k in ["thunderstorm", "storm", "flood", "fire", "wind",
                  "cyclone", "marine", "tsunami", "frost", "heat", "snow"]:
            if k in t:
                kind = k
                break
        out.append({
            "title": title, "summary": summary, "link": link,
            "issued": issued, "severity": severity, "kind": kind,
        })
    return out


# Curated map of WEATHER_STATIONS name → BOM (product, WMO, state).
# Only major cities have reliable BOM stations near the centre of town;
# regional towns can be added as you discover their WMO numbers.
# Source: BOM product pages (e.g. www.bom.gov.au/products/IDN60901.shtml).
BOM_STATION_MAP: dict[str, dict] = {
    "Sydney":          {"product": "IDN60901", "wmo": 94768, "state": "nsw", "lat": -33.87, "lng": 151.21},
    "Newcastle":       {"product": "IDN60901", "wmo": 94774, "state": "nsw", "lat": -32.93, "lng": 151.78},
    "Wollongong":      {"product": "IDN60901", "wmo": 94776, "state": "nsw", "lat": -34.42, "lng": 150.89},
    "Canberra":        {"product": "IDN60903", "wmo": 94926, "state": "act", "lat": -35.28, "lng": 149.13},
    "Wagga Wagga":     {"product": "IDN60901", "wmo": 95625, "state": "nsw", "lat": -35.12, "lng": 147.37},
    "Dubbo":           {"product": "IDN60901", "wmo": 95719, "state": "nsw", "lat": -32.24, "lng": 148.60},
    "Tamworth":        {"product": "IDN60901", "wmo": 95773, "state": "nsw", "lat": -31.09, "lng": 150.93},
    "Coffs Harbour":   {"product": "IDN60901", "wmo": 94778, "state": "nsw", "lat": -30.30, "lng": 153.12},
    "Broken Hill":     {"product": "IDN60901", "wmo": 95677, "state": "nsw", "lat": -31.96, "lng": 141.46},
    "Melbourne":       {"product": "IDV60901", "wmo": 95936, "state": "vic", "lat": -37.81, "lng": 144.96},
    "Geelong":         {"product": "IDV60901", "wmo": 87184, "state": "vic", "lat": -38.15, "lng": 144.36},
    "Ballarat":        {"product": "IDV60901", "wmo": 94852, "state": "vic", "lat": -37.56, "lng": 143.85},
    "Bendigo":         {"product": "IDV60901", "wmo": 95872, "state": "vic", "lat": -36.76, "lng": 144.28},
    "Mildura":         {"product": "IDV60901", "wmo": 95693, "state": "vic", "lat": -34.21, "lng": 142.14},
    "Brisbane":        {"product": "IDQ60901", "wmo": 94576, "state": "qld", "lat": -27.47, "lng": 153.03},
    "Gold Coast":      {"product": "IDQ60901", "wmo": 94595, "state": "qld", "lat": -28.00, "lng": 153.43},
    "Sunshine Coast":  {"product": "IDQ60901", "wmo": 94569, "state": "qld", "lat": -26.65, "lng": 153.07},
    "Toowoomba":       {"product": "IDQ60901", "wmo": 94568, "state": "qld", "lat": -27.56, "lng": 151.95},
    "Cairns":          {"product": "IDQ60901", "wmo": 94287, "state": "qld", "lat": -16.92, "lng": 145.78},
    "Townsville":      {"product": "IDQ60901", "wmo": 94294, "state": "qld", "lat": -19.26, "lng": 146.79},
    "Mackay":          {"product": "IDQ60901", "wmo": 94367, "state": "qld", "lat": -21.14, "lng": 149.19},
    "Rockhampton":     {"product": "IDQ60901", "wmo": 94374, "state": "qld", "lat": -23.38, "lng": 150.51},
    "Mount Isa":       {"product": "IDQ60901", "wmo": 94332, "state": "qld", "lat": -20.73, "lng": 139.49},
    "Perth":           {"product": "IDW60901", "wmo": 94610, "state": "wa",  "lat": -31.95, "lng": 115.86},
    "Bunbury":         {"product": "IDW60901", "wmo": 95603, "state": "wa",  "lat": -33.33, "lng": 115.64},
    "Albany":          {"product": "IDW60901", "wmo": 94802, "state": "wa",  "lat": -35.02, "lng": 117.88},
    "Geraldton":       {"product": "IDW60901", "wmo": 94403, "state": "wa",  "lat": -28.77, "lng": 114.62},
    "Kalgoorlie":      {"product": "IDW60901", "wmo": 94637, "state": "wa",  "lat": -30.75, "lng": 121.47},
    "Broome":          {"product": "IDW60901", "wmo": 94203, "state": "wa",  "lat": -17.96, "lng": 122.24},
    "Port Hedland":    {"product": "IDW60901", "wmo": 94312, "state": "wa",  "lat": -20.31, "lng": 118.58},
    "Karratha":        {"product": "IDW60901", "wmo": 94310, "state": "wa",  "lat": -20.74, "lng": 116.85},
    "Adelaide":        {"product": "IDS60901", "wmo": 94648, "state": "sa",  "lat": -34.93, "lng": 138.60},
    "Whyalla":         {"product": "IDS60901", "wmo": 95659, "state": "sa",  "lat": -33.03, "lng": 137.58},
    "Mount Gambier":   {"product": "IDS60901", "wmo": 94821, "state": "sa",  "lat": -37.83, "lng": 140.78},
    "Port Augusta":    {"product": "IDS60901", "wmo": 94659, "state": "sa",  "lat": -32.49, "lng": 137.78},
    "Ceduna":          {"product": "IDS60901", "wmo": 94516, "state": "sa",  "lat": -32.13, "lng": 133.68},
    "Hobart":          {"product": "IDT60901", "wmo": 94970, "state": "tas", "lat": -42.88, "lng": 147.33},
    "Launceston":      {"product": "IDT60901", "wmo": 94965, "state": "tas", "lat": -41.44, "lng": 147.14},
    "Devonport":       {"product": "IDT60901", "wmo": 94954, "state": "tas", "lat": -41.18, "lng": 146.35},
    "Burnie":          {"product": "IDT60901", "wmo": 94957, "state": "tas", "lat": -41.06, "lng": 145.91},
    "Darwin":          {"product": "IDD60901", "wmo": 94120, "state": "nt",  "lat": -12.46, "lng": 130.85},
    "Alice Springs":   {"product": "IDD60901", "wmo": 94326, "state": "nt",  "lat": -23.70, "lng": 133.88},
    "Katherine":       {"product": "IDD60901", "wmo": 94150, "state": "nt",  "lat": -14.47, "lng": 132.27},
    "Tennant Creek":   {"product": "IDD60901", "wmo": 94238, "state": "nt",  "lat": -19.65, "lng": 134.19},
}

# ─── BOM → Open-Meteo shape conversion (used by fallback path) ───
# 16-point compass to bearing (degrees clockwise from N)
_WIND_DIR_DEG = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
    "CALM": None,
}

def _bom_to_om_current(bom_latest: dict | None) -> dict | None:
    """Convert a BOM observation row to Open-Meteo's `current` shape."""
    if not bom_latest:
        return None
    rain = bom_latest.get("rain_trace")
    try:
        rain = float(rain) if rain not in (None, "-") else 0.0
    except (TypeError, ValueError):
        rain = 0.0
    return {
        "temperature_2m": bom_latest.get("air_temp"),
        "relative_humidity_2m": bom_latest.get("rel_hum"),
        "wind_speed_10m": bom_latest.get("wind_spd_kmh"),
        "wind_direction_10m": _WIND_DIR_DEG.get((bom_latest.get("wind_dir") or "").upper()),
        "weather_code": 0,  # BOM has no WMO code, gives `weather` text instead
        "apparent_temperature": bom_latest.get("apparent_t"),
        "precipitation": rain,
        "time": bom_latest.get("local_date_time_full"),
    }

def _find_bom_station(lat: float, lng: float, tol: float = 0.05) -> dict | None:
    """Find a BOM station within ~5km of the requested coord."""
    for station in BOM_STATION_MAP.values():
        if abs(station["lat"] - lat) < tol and abs(station["lng"] - lng) < tol:
            return station
    return None

async def _fetch_bom_obs_for_station(station: dict) -> dict | None:
    """Internal: fetch a single BOM station obs (uses cache, returns latest row)."""
    key = f"{station['product']}:{station['wmo']}"
    now = time.time()
    cached = _bom_obs_cache.get(key)
    if cached and (now - cached["ts"]) < _BOM_OBS_TTL:
        return cached["data"].get("latest")
    url = f"http://www.bom.gov.au/fwo/{station['product']}/{station['product']}.{station['wmo']}.json"
    try:
        http = _get_bom_client()
        r = await http.get(url)
        if r.status_code != 200:
            return cached["data"].get("latest") if cached else None
        data = r.json()
        obs = (((data.get("observations") or {}).get("data")) or [])
        header = (((data.get("observations") or {}).get("header")) or [{}])[0]
        trimmed = {"header": header, "latest": obs[0] if obs else None,
                   "history_24h": obs[:24] if obs else []}
        if len(_bom_obs_cache) > _BOM_OBS_CACHE_MAX:
            oldest = min(_bom_obs_cache.items(), key=lambda kv: kv[1]["ts"])[0]
            _bom_obs_cache.pop(oldest, None)
        _bom_obs_cache[key] = {"data": trimmed, "ts": now}
        return trimmed.get("latest")
    except Exception:
        return cached["data"].get("latest") if cached else None

async def _bom_batch_fallback(latitude_csv: str, longitude_csv: str) -> list[dict] | None:
    """Build an Open-Meteo-shaped batch response from BOM obs.
    Returns None if no requested coords match any BOM station."""
    try:
        lats = [float(x) for x in latitude_csv.split(",")]
        lngs = [float(x) for x in longitude_csv.split(",")]
    except ValueError:
        return None
    if len(lats) != len(lngs):
        return None
    # Build task list — None for coords with no nearby BOM station
    tasks = []
    for lat, lng in zip(lats, lngs):
        station = _find_bom_station(lat, lng)
        tasks.append(_fetch_bom_obs_for_station(station) if station else None)
    # Resolve in parallel (skip Nones)
    coros = [t for t in tasks if t is not None]
    if not coros:
        return None
    results = await asyncio.gather(*coros, return_exceptions=True)
    # Re-align with original order
    out = []
    ri = 0
    for t in tasks:
        if t is None:
            out.append({"current": None})
        else:
            r = results[ri]; ri += 1
            obs = None if isinstance(r, Exception) else r
            out.append({"current": _bom_to_om_current(obs)})
    return out

@app.get("/proxy/bom/stations")
async def proxy_bom_stations():
    """Return the curated mapping of city name → BOM station so the
    frontend knows which towns have a BOM ground observation available."""
    return {"stations": BOM_STATION_MAP}


# ─── BOM state-wide bulk observation feeds ────────────────────────
# Each state has an XML file listing every AWS station with its latest
# observation in one shot. Refreshed every ~20 min by a background task.
# This is the authoritative source for "all BOM stations with data now".
_BOM_STATE_FEEDS = {
    "nsw": "IDN60920",
    "act": "IDN60920",     # ACT is bundled with NSW in this feed
    "vic": "IDV60920",
    "qld": "IDQ60920",
    "wa":  "IDW60920",
    "sa":  "IDS60920",
    "tas": "IDT60920",
    "nt":  "IDD60920",
}
_BOM_MASTER_TTL = 20 * 60
_bom_master: dict = {"stations": [], "ts": 0.0, "errors": {}}
_bom_master_lock = asyncio.Lock()

# ─── GeoNames-backed station tiering ──────────────────────────────
# Download AU populated-places dump once, cache to disk. Each BOM station
# gets a tier 0/1/2 based on the highest-population place near it. This is
# what drives the zoom-based label decluttering on the frontend.
_AU_PLACES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "au_places.json")
_AU_PLACES_URL  = "https://download.geonames.org/export/dump/AU.zip"
_au_places: list = []   # [{name, lat, lng, pop}]
_au_places_lock = asyncio.Lock()

async def _ensure_au_places() -> list:
    """Load AU places from disk, downloading + filtering GeoNames dump if missing."""
    global _au_places
    async with _au_places_lock:
        if _au_places:
            return _au_places
        # Try disk cache first
        if os.path.exists(_AU_PLACES_FILE):
            try:
                with open(_AU_PLACES_FILE, "r", encoding="utf-8") as fp:
                    _au_places = json.load(fp)
                print(f"[places] loaded {len(_au_places)} AU populated places from cache")
                return _au_places
            except Exception as e:
                print(f"[places] cache read failed, re-downloading: {e}")
        # Download and build
        try:
            import zipfile, io, csv
            print(f"[places] downloading GeoNames AU dump (~7MB, one-time)…")
            async with httpx.AsyncClient(timeout=60.0) as c:
                r = await c.get(_AU_PLACES_URL, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            txt = zf.read("AU.txt").decode("utf-8", errors="ignore")
            places: list = []
            for row in csv.reader(io.StringIO(txt), delimiter="\t"):
                if len(row) < 15:
                    continue
                # fields per geonames README: 1 name, 4 lat, 5 lng, 6 feature_class, 14 population
                feat_class = row[6]
                if feat_class != "P":
                    continue
                try:
                    pop = int(row[14] or 0)
                    lat = float(row[4]); lng = float(row[5])
                except ValueError:
                    continue
                if pop < 500:
                    continue
                places.append({"name": row[1], "lat": lat, "lng": lng, "pop": pop})
            _au_places = places
            with open(_AU_PLACES_FILE, "w", encoding="utf-8") as fp:
                json.dump(places, fp)
            print(f"[places] downloaded and cached {len(places)} AU populated places")
        except Exception as e:
            print(f"[places] download failed, tiering disabled: {e}")
            _au_places = []
        return _au_places


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    import math
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lng2 - lng1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _station_tier(lat: float, lng: float) -> int:
    """Tier 0 = major city (≥300k pop within 30km),
       Tier 1 = regional hub (≥20k pop within 20km),
       Tier 2 = everything else."""
    if not _au_places or lat is None or lng is None:
        return 2
    # Cheap bbox prefilter — 30km ≈ 0.27 deg lat, ~0.32 deg lng at AU mid-latitudes
    best_pop = 0
    best_dist = 9999.0
    for p in _au_places:
        if abs(p["lat"] - lat) > 0.35 or abs(p["lng"] - lng) > 0.45:
            continue
        d = _haversine_km(lat, lng, p["lat"], p["lng"])
        if d > 30.0:
            continue
        # Prefer higher population over closer (so Sydney Airport ranks as Sydney,
        # not as tiny "Mascot" suburb 2km away)
        if p["pop"] > best_pop:
            best_pop = p["pop"]
            best_dist = d
    if best_pop >= 300_000 and best_dist <= 30.0:
        return 0
    if best_pop >= 20_000 and best_dist <= 20.0:
        return 1
    return 2


def _tier_stations(stations: list) -> list:
    """Attach a `tier` field to every station. Mutates in place."""
    for s in stations:
        s["tier"] = _station_tier(s.get("lat"), s.get("lng"))
    return stations

def _parse_bom_state_xml(xml_text: str, state: str) -> list[dict]:
    """Parse a BOM state-wide observation XML into a list of stations.
    Each station includes its latest observation fields, shaped like a
    BOM per-station JSON `data[0]` entry so the existing conversion
    helpers work unchanged."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    # Strip namespaces
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    out: list[dict] = []
    # Element types we care about, mapped to BOM JSON field names used by
    # _bom_to_om_current() and the modal renderer.
    elem_map = {
        "air_temperature": "air_temp",
        "apparent_temp": "apparent_t",
        "rel-humidity": "rel_hum",
        "wind_spd_kmh": "wind_spd_kmh",
        "wind_dir": "wind_dir",
        "wind_dir_deg": "wind_dir_deg",
        "gust_kmh": "gust_kmh",
        "pres": "press_msl",
        "msl_pres": "press_msl",
        "rain_ten": "rain_trace",
        "rainfall": "rain_trace",
        "rainfall_24hr": "rain_24hr",
        "dew_point": "dewpt",
        "maximum_air_temperature": "max_temp",
        "minimum_air_temperature": "min_temp",
    }
    # Product ID for this document — used when the frontend later wants
    # richer per-station data via /proxy/bom/observation
    product_id = ""
    amoc = root.find("amoc")
    if amoc is not None:
        pid = amoc.find("product-id")
        if pid is not None and pid.text:
            product_id = pid.text.strip()

    for station in root.iter("station"):
        try:
            lat = float(station.get("lat", ""))
            lng = float(station.get("lon", ""))
        except ValueError:
            continue
        wmo = station.get("wmo-id") or station.get("bom-id") or ""
        name = station.get("stn-name") or station.get("description") or ""
        if not name or not wmo:
            continue
        # Pull the most recent period's elements
        obs: dict = {"name": name, "wmo": int(wmo) if wmo.isdigit() else wmo,
                     "lat": lat, "lon": lng}
        period = station.find("period")
        if period is not None:
            obs["local_date_time_full"] = period.get("time-local", "")
            obs["local_date_time"] = period.get("time-local", "")[-8:] if period.get("time-local") else ""
            level = period.find("level")
            container = level if level is not None else period
            for elem in container.findall("element"):
                etype = elem.get("type", "")
                key = elem_map.get(etype)
                if not key:
                    continue
                txt = (elem.text or "").strip()
                if not txt or txt in ("-", "NaN"):
                    continue
                try:
                    obs[key] = float(txt) if key not in ("wind_dir",) else txt.upper()
                except ValueError:
                    obs[key] = txt
        out.append({
            "product": product_id,
            "wmo": obs["wmo"],
            "name": name,
            "state": state,
            "lat": lat,
            "lng": lng,
            "obs": obs,
        })
    return out


async def _fetch_one_state_feed(state: str, product: str) -> tuple[str, list[dict], str | None]:
    url = f"http://www.bom.gov.au/fwo/{product}.xml"
    try:
        http = _get_bom_client()
        r = await http.get(url)
        if r.status_code != 200:
            return state, [], f"HTTP {r.status_code}"
        return state, _parse_bom_state_xml(r.text, state), None
    except Exception as e:
        return state, [], str(e)


async def _refresh_bom_master(force: bool = False) -> dict:
    """Fetch all state feeds in parallel, build master station list."""
    async with _bom_master_lock:
        now = time.time()
        if not force and _bom_master["stations"] and (now - _bom_master["ts"]) < _BOM_MASTER_TTL:
            return _bom_master
        # ACT shares IDN60920 with NSW — de-dup by fetching unique products
        unique = {}
        for state, product in _BOM_STATE_FEEDS.items():
            unique.setdefault(product, state)  # remember first state for this product
        tasks = [_fetch_one_state_feed(state, product) for product, state in unique.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged: list[dict] = []
        errors: dict[str, str] = {}
        seen_wmo = set()
        for r in results:
            if isinstance(r, Exception):
                continue
            state, stations, err = r
            if err:
                errors[state] = err
            for s in stations:
                if s["wmo"] in seen_wmo:
                    continue
                seen_wmo.add(s["wmo"])
                merged.append(s)
        if merged:
            _tier_stations(merged)
            _bom_master["stations"] = merged
            _bom_master["ts"] = now
            _bom_master["errors"] = errors
        else:
            # keep old data if present, just record the errors
            _bom_master["errors"] = errors
        return _bom_master


async def _bom_master_background():
    """Refresh the master catalogue every _BOM_MASTER_TTL seconds."""
    while True:
        try:
            await _refresh_bom_master(force=True)
        except Exception as exc:
            log.warning("BOM master refresh failed: %s", exc)
        await asyncio.sleep(_BOM_MASTER_TTL)


@app.get("/proxy/bom/all")
async def proxy_bom_all():
    """Return every BOM AWS station with its latest observation.
    This is the primary weather data source — updates every ~20 min,
    no quota. Empty list on first request until initial fetch completes."""
    # Trigger a fetch if cache is empty (startup race)
    if not _bom_master["stations"]:
        await _refresh_bom_master()
    return {
        "stations": _bom_master["stations"],
        "count": len(_bom_master["stations"]),
        "fetched_at": _bom_master["ts"],
        "age_seconds": round(time.time() - _bom_master["ts"], 1) if _bom_master["ts"] else None,
        "errors": _bom_master.get("errors", {}),
    }


# ─── RainViewer tile proxy (needed because tilecache.rainviewer.com
#     does not send CORS headers and MapLibre requires CORS for raster
#     tiles) ──────────────────────────────────────────────────────────
_rv_tile_cache: dict = {}
_RV_TILE_CACHE_MAX = 2000  # 13 frames × ~100 tiles headroom for pan/zoom

# Shared httpx client with connection pooling. Creating a fresh client
# per request (full TCP+TLS handshake) was the main bottleneck when
# preloading ~500 tiles at once.
_rv_http_client: "httpx.AsyncClient | None" = None

def _get_rv_client() -> httpx.AsyncClient:
    global _rv_http_client
    if _rv_http_client is None:
        _rv_http_client = httpx.AsyncClient(
            timeout=10,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            http2=False,
        )
    return _rv_http_client

# Browser-cacheable response headers — once a tile is in the browser
# HTTP cache, MapLibre's subsequent fetches never hit our proxy.
_RV_TILE_HEADERS = {
    "Cache-Control": "public, max-age=600",
    "Access-Control-Allow-Origin": "*",
}

_RV_PATH_RE = re.compile(r"^[a-zA-Z0-9/_]+\.png$")


@app.get("/proxy/rainviewer/{path:path}")
async def proxy_rainviewer_tile(path: str):
    """Pass-through proxy for rainviewer tile PNGs, adds CORS headers."""
    if not _RV_PATH_RE.match(path):
        return Response(status_code=400,
                        content=b"invalid tile path: only digits, slashes, and .png allowed")
    url = f"https://tilecache.rainviewer.com/{path}"
    cached = _rv_tile_cache.get(url)
    now = time.time()
    if cached and now - cached["ts"] < 600:
        return Response(content=cached["data"], media_type="image/png",
                        headers=_RV_TILE_HEADERS)
    try:
        http = _get_rv_client()
        r = await http.get(url)
        if r.status_code != 200:
            return Response(status_code=r.status_code)
        data = r.content
        if len(_rv_tile_cache) > _RV_TILE_CACHE_MAX:
            # crude eviction: drop oldest
            oldest = min(_rv_tile_cache.items(), key=lambda kv: kv[1]["ts"])[0]
            _rv_tile_cache.pop(oldest, None)
        _rv_tile_cache[url] = {"data": data, "ts": now}
        return Response(content=data, media_type="image/png",
                        headers=_RV_TILE_HEADERS)
    except Exception as e:
        return Response(status_code=502, content=str(e).encode())


# ─── SPEED CAMERAS — NSW + QLD + ACT, 24h cache ─────────────
# Aggregates fixed / red-light / mobile speed camera sites from three
# state open-data portals into a single GeoJSON FeatureCollection.
# NSW fixed + red-light and ACT all have lat/lon; NSW mobile and QLD
# expose only suburb/road descriptors and are returned without geometry
# (frontend filters those out when rendering map points).
@app.get("/proxy/speed-cameras")
async def proxy_speed_cameras():
    c = cache_get("speed_cameras", 24 * 60 * 60)
    if c and c["data"]:
        return respond("Speed Cameras", c["data"], cached=True)

    import csv as _csv
    import io as _io
    http = await client()
    features: list[dict] = []
    errors: list[str] = []

    def _f(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    # ── NSW (three CSVs: fixed / red-light / mobile) ──────────
    nsw_sources = [
        ("fixed", "https://opendata.transport.nsw.gov.au/data/dataset/"
                  "fb34bd89-443a-448c-a4a5-7c8caab70c44/resource/"
                  "bcf2f6f4-ecfb-40e1-a807-0d5eb5f51507/download/"
                  "fixed-speed-cameras_1.csv"),
        ("red_light", "https://opendata.transport.nsw.gov.au/data/dataset/"
                      "fb34bd89-443a-448c-a4a5-7c8caab70c44/resource/"
                      "debd70a9-f9f4-471c-81ae-c84098576ea6/download/"
                      "red-light-speed-cameras_1.csv"),
        ("mobile", "https://opendata.transport.nsw.gov.au/data/dataset/"
                   "fb34bd89-443a-448c-a4a5-7c8caab70c44/resource/"
                   "b4e0c74e-10a6-48e8-8421-2cd0294af6ae/download/"
                   "mobile-speed-camera-locations-january-2022.csv"),
    ]
    for kind, url in nsw_sources:
        try:
            r = await http.get(url, headers=_HEADERS, timeout=20.0)
            r.raise_for_status()
            reader = _csv.DictReader(_io.StringIO(r.text))
            for i, row in enumerate(reader):
                suburb = (row.get("SUBURB/TOWN") or row.get("Suburb") or "").strip()
                road = (row.get("ROAD/S") or row.get("Road") or "").strip()
                lat = _f(row.get("Lat(1)") or row.get("Latitude"))
                lng = _f(row.get("Long(1)") or row.get("Longitude"))
                props = {
                    "id": f"nsw_{kind}_{i}",
                    "state": "NSW",
                    "type": kind,
                    "road": road or None,
                    "suburb": suburb or None,
                    "title": road or suburb or "Speed camera",
                }
                if lat is not None and lng is not None:
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lng, lat]},
                        "properties": props,
                    })
                else:
                    features.append({
                        "type": "Feature",
                        "geometry": None,
                        "properties": props,
                    })
        except Exception as e:
            errors.append(f"NSW {kind}: {e}")

    # ── QLD active mobile sites (CKAN datastore, no coords) ───
    try:
        r = await http.get(
            "https://www.data.qld.gov.au/api/3/action/datastore_search"
            "?resource_id=f6b5c37e-de9d-4041-8c18-f4d4b6c593a8&limit=5000",
            headers=_HEADERS, timeout=20.0,
        )
        r.raise_for_status()
        for rec in ((r.json().get("result") or {}).get("records") or []):
            descriptor = (rec.get("Primary Descriptor") or "").strip()
            features.append({
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "id": f"qld_{rec.get('Site Number') or rec.get('_id')}",
                    "state": "QLD",
                    "type": "mobile",
                    "title": descriptor or "Mobile speed camera",
                    "description": descriptor or None,
                },
            })
    except Exception as e:
        errors.append(f"QLD: {e}")

    # ── ACT fixed + mobile (Socrata, has lat/lon) ─────────────
    try:
        r = await http.get(
            "https://www.data.act.gov.au/resource/426s-vdu4.json?$limit=5000",
            headers=_HEADERS, timeout=20.0,
        )
        r.raise_for_status()
        for i, rec in enumerate(r.json()):
            ctype_raw = (rec.get("camera_type") or "").lower()
            ctype = "mobile" if "mobile" in ctype_raw else (
                "red_light" if "red" in ctype_raw else "fixed"
            )
            code = rec.get("camera_location_code") or rec.get("location_code") or i
            lat = _f(rec.get("latitude"))
            lng = _f(rec.get("longitude"))
            props = {
                "id": f"act_{code}",
                "state": "ACT",
                "type": ctype,
                "title": rec.get("location_description") or "Speed camera",
                "description": rec.get("location_description"),
            }
            geom = (
                {"type": "Point", "coordinates": [lng, lat]}
                if (lat is not None and lng is not None) else None
            )
            features.append({"type": "Feature", "geometry": geom, "properties": props})
    except Exception as e:
        errors.append(f"ACT: {e}")

    data = {"type": "FeatureCollection", "features": features}
    if features:
        cache_set("speed_cameras", data, error="; ".join(errors) or None)
        return respond(
            "Speed Cameras",
            data,
            cached=False,
            error="; ".join(errors) or None,
        )

    # Everything failed — serve stale cache if any, else empty
    if "speed_cameras" in _cache and _cache["speed_cameras"]["data"]:
        return respond(
            "Speed Cameras",
            _cache["speed_cameras"]["data"],
            cached=True,
            error="; ".join(errors),
        )
    return respond(
        "Speed Cameras",
        {"type": "FeatureCollection", "features": []},
        cached=False,
        error="; ".join(errors) or "all sources failed",
    )


# ─── ELEVATION GRID (viewshed support) ──────────────────────────
# Stitches AWS Terrarium terrain tiles into a cropped 256×256 elevation
# grid for the client-side viewshed analysis tool.
# Requires Pillow: pip install Pillow
# Terrarium encoding: elev_m = R * 256 + G + B / 256 − 32768
_TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
_ELEVATION_GRID_SIZE = 256


def _ll_to_tile(lat: float, lng: float, zoom: int) -> tuple[int, int]:
    n = 1 << zoom
    x = int((lng + 180.0) / 360.0 * n)
    sin_lat = math.sin(math.radians(lat))
    y_frac = (1.0 - math.log((1 + sin_lat) / (1 - sin_lat)) / (2 * math.pi)) / 2.0
    y = int(max(0.0, y_frac) * n)
    return x, y


def _tile_nw_corner(tx: int, ty: int, zoom: int) -> tuple[float, float]:
    n = 1 << zoom
    lng = tx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    return lat, lng


def _mercator_y_frac(lat: float) -> float:
    sin_lat = math.sin(math.radians(lat))
    return (1.0 - math.log((1 + sin_lat) / (1 - sin_lat)) / (2 * math.pi)) / 2.0


@app.get("/proxy/elevation-grid")
async def proxy_elevation_grid(lat: float, lng: float, radius_km: float = 2.0):
    """
    Return a cropped 256x256 elevation grid (metres) centred on (lat, lng)
    covering ±radius_km.  Source: AWS Terrain Tiles (Terrarium, global SRTM).
    Requires Pillow: pip install Pillow
    """
    try:
        from PIL import Image as _Image
    except ImportError:
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(
            status_code=501,
            detail="Pillow not installed — run: pip install Pillow",
        )

    radius_km = max(0.5, min(10.0, radius_km))

    # Choose tile zoom so the bbox spans roughly 2-4 tiles per axis.
    if radius_km <= 2:
        zoom = 13
    elif radius_km <= 5:
        zoom = 12
    else:
        zoom = 11

    lat_delta = radius_km / 111.0
    lng_delta = radius_km / max(0.01, 111.0 * math.cos(math.radians(lat)))
    min_lat, max_lat = lat - lat_delta, lat + lat_delta
    min_lng, max_lng = lng - lng_delta, lng + lng_delta

    # y increases south so max_lat → min_tile_y, min_lat → max_tile_y
    min_tx, min_ty = _ll_to_tile(max_lat, min_lng, zoom)
    max_tx, max_ty = _ll_to_tile(min_lat, max_lng, zoom)

    if (max_tx - min_tx + 1) * (max_ty - min_ty + 1) > 16:
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(status_code=400, detail="Radius too large; reduce radius_km and retry")

    # Fetch all required tiles in parallel
    http = await client()
    tile_bytes: dict[tuple[int, int], bytes] = {}

    async def _fetch_tile(tx: int, ty: int) -> None:
        url = _TERRARIUM_URL.format(z=zoom, x=tx, y=ty)
        try:
            r = await http.get(url, headers=_HEADERS, timeout=10.0)
            if r.status_code == 200:
                tile_bytes[(tx, ty)] = r.content
        except Exception as exc:
            log.warning("elevation tile %s/%s/%s failed: %s", zoom, tx, ty, exc)

    await asyncio.gather(*[
        _fetch_tile(tx, ty)
        for tx in range(min_tx, max_tx + 1)
        for ty in range(min_ty, max_ty + 1)
    ])

    if not tile_bytes:
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(status_code=503, detail="Could not fetch elevation tiles — check connectivity")

    # Stitch tiles into one RGB image (sentinel (128,0,0) ≈ sea-level)
    tile_cols = max_tx - min_tx + 1
    tile_rows = max_ty - min_ty + 1
    stitched = _Image.new("RGB", (tile_cols * 256, tile_rows * 256), (128, 0, 0))
    for (tx, ty), data in tile_bytes.items():
        try:
            tile_img = _Image.open(io.BytesIO(data)).convert("RGB")
            stitched.paste(tile_img, ((tx - min_tx) * 256, (ty - min_ty) * 256))
        except Exception as exc:
            log.warning("tile decode (%s,%s) failed: %s", tx, ty, exc)

    img_w, img_h = stitched.size

    # Convert bbox corners to pixel coordinates using Mercator projection.
    nw_lat, nw_lng = _tile_nw_corner(min_tx, min_ty, zoom)
    se_lat, se_lng = _tile_nw_corner(max_tx + 1, max_ty + 1, zoom)
    img_y_north = _mercator_y_frac(nw_lat)
    img_y_south = _mercator_y_frac(se_lat)

    def _to_px(qlat: float, qlng: float) -> tuple[float, float]:
        px = (qlng - nw_lng) / (se_lng - nw_lng) * img_w
        py = (_mercator_y_frac(qlat) - img_y_north) / (img_y_south - img_y_north) * img_h
        return px, py

    crop_left, crop_top     = _to_px(max_lat, min_lng)
    crop_right, crop_bottom = _to_px(min_lat, max_lng)
    crop_box = (
        max(0, int(crop_left)),
        max(0, int(crop_top)),
        min(img_w, int(crop_right) + 1),
        min(img_h, int(crop_bottom) + 1),
    )
    cropped = stitched.crop(crop_box)

    # Resize to output grid and decode Terrarium elevation values
    out_n = _ELEVATION_GRID_SIZE
    resized = cropped.resize((out_n, out_n), _Image.BILINEAR)
    px_access = resized.load()

    grid: list[list[int]] = []
    for row in range(out_n):
        grid_row: list[int] = []
        for col in range(out_n):
            r_val, g_val, b_val = px_access[col, row]
            elev = round(r_val * 256 + g_val + b_val / 256 - 32768)
            grid_row.append(elev)
        grid.append(grid_row)

    return {
        "grid": grid,
        "width": out_n,
        "height": out_n,
        "bounds": {
            "minLng": min_lng,
            "maxLng": max_lng,
            "minLat": min_lat,
            "maxLat": max_lat,
        },
        "zoom": zoom,
        "radius_km": radius_km,
    }


@app.get("/proxy/status")
async def proxy_status():
    """Show what's cached and whether each source is reachable."""
    status = {}
    for key, entry in _cache.items():
        status[key] = {
            "has_data": entry["data"] is not None,
            "cached_at": datetime.fromtimestamp(entry["ts"], timezone.utc).isoformat(),
            "age_seconds": round(time.time() - entry["ts"], 1),
            "error": entry.get("error"),
        }
    return {"cache": status}


# ═══════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys, io
    # Force UTF-8 stdout so box-drawing chars don't crash on Windows cp1252
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("+-------------------------------------------------+")
    print("|  Atlas of Australia -- God's Eye Proxy Server    |")
    print("|  Open http://localhost:8777 in your browser      |")
    print("|  API docs: http://localhost:8777/docs            |")
    print("+-------------------------------------------------+")
    uvicorn.run(app, host="0.0.0.0", port=8777)
