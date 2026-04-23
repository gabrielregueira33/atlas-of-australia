# God's Eye — Changelog

---

## 2026-04-19 — Speed cameras layer + Atlas removal

**Scope:** Added a new `/proxy/speed-cameras` endpoint aggregating three state open-data portals, wired a toggleable map layer in the dashboard, and deleted the Atlas proof-of-concept app.

### Speed cameras (new)

- **`/proxy/speed-cameras`** — new endpoint in `gods-eye/server.py`, 24 h in-memory cache. Aggregates:
  - **NSW** — TfNSW open-data CSVs for fixed, red-light, and mobile speed cameras. Fixed + red-light carry lat/lng; mobile is road + suburb only.
  - **QLD** — `data.qld.gov.au` CKAN `datastore_search` for active mobile sites. Site number + primary descriptor only (no coordinates).
  - **ACT** — `data.act.gov.au` Socrata JSON for fixed + mobile. Full lat/lng.
  - VIC deliberately skipped (only a 2023 XLSX snapshot — not worth an Excel dependency for stale data).
  - SA has no open-data API (see BACKLOG for HTML-scrape option).
  - Returns a GeoJSON FeatureCollection. Features without geometry are included (for counts) but filtered out by the client before rendering.
- **Initial load:** 6,413 sites total, ~1,535 mappable. Breakdown: NSW 1,492 · QLD 3,686 · ACT 1,235. By type: fixed 143 · red-light 217 · mobile 6,053.
- **Layer in `index.html`** — new `speedcams` entry in the `LAYERS` array (default: off). `fetchSpeedCameras()` + `addSpeedCamerasLayer()` follow the existing fire-layer pattern: GeoJSON source, a `circle` core layer colour-coded by type (fixed=pink, red-light=red, mobile=amber), a `📷` symbol label, click popup with type/state/suburb, and mouse-cursor hints. Included in the style-swap re-add path so it survives basemap switches.

### Atlas removal

The Atlas proof-of-concept — a Docker-composed ingester/API/React panel dashboard on port 8080 — was deleted. It was superseded by God's Eye's map-first architecture. Removed:

- `api/`, `contracts/`, `db/`, `frontend/`, `ingesters/`, `nginx/`, `ops/` directories
- `sources.yaml`, `docker-compose.yml`, `docker-compose.prod.yml`
- Obsolete Atlas architecture doc `BUILD.md` (635 lines)

Kept: `gods-eye/`, reference data (`Australian_Free_APIs_*`), all top-level docs (`README`, `BACKLOG`, `CHANGELOG`, `SECURITY`, `CLAUDE`).

Remaining tidy-ups (prune `.env.example` of Atlas sections, delete `.dockerignore`, archive Atlas-era changelog entries, refresh "Project overview") are tracked in [BACKLOG.md](BACKLOG.md).

### Known quirks

- **Preview-sandbox tile rendering** — the preview tool's sandboxed Chrome doesn't finish loading MapTiler tiles, so `isStyleLoaded()` stays false and `queryRenderedFeatures` returns 0 for *every* layer (fires, weather, flights, cities, speed cameras). The layer wiring is verifiable via `src._data.features.length` and `LAYERS[].count`; visual rendering needs a real browser. Same issue pre-dates the speed-camera work.
- **README.md** rewritten from the Atlas summary to a God's-Eye-only quick-start.

---

## 2026-04-18 — God's Eye: hybrid renderer + premium features

**Scope:** Keep MapLibre as the renderer, layer Google/MapTiler/TomTom/TfNSW data APIs on top. Net result: globe projection, satellite hybrid, 3D terrain + buildings, live-traffic routing, Places POI with rich popups, NSW traffic incidents, clustering, per-basemap theming — all without sacrificing MapLibre's GPU perf.

**Context:** Earlier in the session I briefly attempted a full-Google-Maps rewrite of the renderer (replacing MapLibre entirely). Reverted after perf regression with ~100 flight markers + 767 weather markers. Final architecture: **MapLibre for rendering, Google/MapTiler/TomTom/TfNSW for data**. All 14 revert edits preserved in git history (when repo is initialised).

### Rendering stack

37. **MapLibre 4.7.1 → 5.6.0** — required for `setProjection({ type: 'globe' })` and improved terrain rendering. All 3 CDN fallback URLs updated.
38. **Basemap provider: Carto → MapTiler.** `streets-dark` for dark, `streets-v2` for light, `hybrid` for satellite. Denser labels + built-in POI data vs. Carto's minimalist dark-matter. Free tier (100k tiles/month) covers expected usage easily.
39. **Globe projection toggle** (MapLibre v5 native). Persists under `gods-eye-projection`. Smooth transition — data layers render correctly on both projections without rewrites.
40. **3D Terrain mode** — `map.setTerrain({ source: 'terrain-dem', exaggeration: 1.2 })` using AWS Terrain RGB tiles (free, no key). Persists under `gods-eye-terrain`.
41. **3D buildings** — `fill-extrusion` layer using MapTiler's `openmaptiles` vector source, `building` source-layer. Zoom 14+ only (perf gate). Inserted below first symbol layer so labels stay on top.
42. **Accent color presets** (5 swatches: sky / emerald / amber / rose / violet) — propagate through CSS variable `--accent` at runtime; re-applied to map border colors on change via `_enhanceBasemap`. Persists under `gods-eye-accent`.

### Settings panel

43. **Cog icon replaces the old DARK/FLAT buttons** in the header. One panel with sections: BASEMAP / PROJECTION / TERRAIN / ACCENT / DATA TILES (show-hide side panels for full-map view) / OVERLAYS (3 togglable overlays). Auto-saves on every change. Z-index 200 (above tiles at 50, above header's natural stacking).
44. **Init-robustness:** always boot on dark basemap. If user's saved preference is light/satellite, swap AFTER data layers are in place (`_performBasemapSwap`). Prevents init hang when a tile CDN is slow or blocked.
45. **`setStyle(url, { diff: false })`** — the default diff algorithm chokes when we've paint-modified the current style (`_enhanceBasemap` changes halo/road/border paint). Forcing a clean rebuild avoids a race where the sprite request gets aborted mid-swap.
46. **Poll-until-loaded fallback** in `_performBasemapSwap` — polls `isStyleLoaded()` every 500ms for up to 10s before forcing re-add. Prevents "Style is not done loading" exceptions when a rebuild takes longer than a flat 1.5s timeout.

### Data features

47. **Directions** via `google.maps.DirectionsService` — lazy-loaded (`libraries=places,routes`), browser key only. Never calls `new google.maps.Map()` so no Dynamic Maps billing — just the $10/1000 Directions calls when user clicks. Route polyline rendered via MapLibre source; summary panel with distance + ETA + traffic-adjusted ETA. Origin resolver: browser geolocation (cached per session) with map-center fallback on denial.
48. **Places Autocomplete in header search** — augments (not replaces) the existing Nominatim AU-only search with Google Places predictions. Parallel queries; merged results in the dropdown with a "G" badge for Google entries. Session tokens reduce costs (one session = keystrokes → one selection).
49. **Fuel station → DIRECTIONS buttons**: added to (a) map popup, (b) fuel-search-result-clicked popup, (c) fuel search results list rows with `stopPropagation` to avoid firing the row's fly-to action.
50. **Places POI overlay** (toggleable) — viewport-bounded Nearby Search on `map.on('idle')`, 600ms debounce, zoom 12+ gate. Rich popup on click via `getDetails` (Basic + Contact + Atmosphere billing tiers): photo, rating, review count, price level, category, open/closed status + today's hours, address, phone (tel: link), website, latest review with author + relative time, Google Maps deep-link, DIRECTIONS button. Cache per place_id per session.
51. **TomTom traffic flow overlay** (toggleable) — raster tile layer from `api.tomtom.com/traffic/map/4/tile/flow/absolute/{z}/{x}/{y}.png`. Key via `TOMTOM_KEY`. Opacity 0.65 (const `TRAFFIC_FLOW_OPACITY`). Free tier: 2,500 req/day.
52. **NSW traffic incidents overlay** (toggleable) — new `/proxy/traffic-incidents` endpoint in `server.py` hits `api.transport.nsw.gov.au/v1/live/hazards/incident/open` using `NSW_TRAFFIC_API_KEY` with `Authorization: apikey <val>` header. `_extract_incident_props` normalizes the varied TfNSW field shapes (handles both flat-dict and Feature.properties forms) into common `title / subtitle / category / severity / status / description` schema. Strips HTML from `otherAdvice`. Server-side 90s cache. Client polls every 2 min.
53. **Clustering** — both incidents and weather stations. MapLibre native `cluster: true` on the source.
    - **Incidents:** `clusterMaxZoom: 13`, `clusterRadius: 50`. Color graded by count (rose → deep rose at 15+). Count badges. Click cluster → `easeTo` expansion zoom.
    - **Weather:** `clusterMaxZoom: 7`, `clusterRadius: 50`, **`clusterMinPoints: 4`** — isolated capitals (Perth, Darwin, Hobart, Alice Springs) stay visible as individual temp-coloured circles instead of being hidden inside 1-member "clusters". Existing tier-opacity layers get `['!', ['has', 'point_count']]` filter added so they only draw for unclustered points.
54. **MapTiler built-in POI clicks** — MapTiler's `poi_z14` / `poi_z15` / `poi_z16` / `poi_transit` layers now have click popups with name, class + subclass, DIRECTIONS button, and a Google Maps deep-link (search URL) for richer details on demand. Dark basemap's POI layers had minzoom lowered from 16 → 13 in `_enhanceDarkBuiltinPOIs` so dark mode matches light's POI density. Handlers tracked in `_builtinPOIHandlers` array and `map.off()`-ed before re-registering to avoid accumulation across basemap swaps.
55. **Weather halo colour adapts to basemap** — dark halo on dark, light halo on light/satellite. Halo-width clamped to 1.2px, blur 0, for crisp readability.

### Security + env

56. **New env vars** (gitignored via `.env`, documented in `.env.example`):
    - `GOOGLE_MAPS_BROWSER_KEY` — browser-safe, HTTP referrer restricted to `localhost:8777` + prod domain
    - `MAPTILER_KEY` — browser-safe, Allowed Origins restriction
    - `TOMTOM_KEY` — browser-safe
    - `NSW_TRAFFIC_API_KEY` — **server-side only**, never sent to browser
57. **`server.py` template substitution** — `_HTML_PLACEHOLDERS` tuple substitutes all 3 browser keys into `index.html` at serve time. Raw HTML in git contains only `{{PLACEHOLDER}}` strings; real values live in `.env`.
58. **`SECURITY.md`** (new) — per-key rotation procedures, pre-commit scanner setup (`gitleaks`), restriction guidance, rotation urgency by key type.
59. **`.gitignore` expanded** for public-repo safety — blocks `.env*` variants with explicit `!.env.example` unignore, `.claude/`, `*.lnk`.

### Files added / significantly modified

- **`gods-eye/index.html`** — ~2000 lines of additions: lazy Google loader, directions, places, settings panel, overlays, clustering, POI click handlers, terrain/buildings, route rendering, enhanced enhance helpers.
- **`gods-eye/server.py`** — `_HTML_PLACEHOLDERS` tuple, `serve_dashboard` template substitution, `/proxy/traffic-incidents` endpoint, `_extract_incident_props` normalizer.
- **`.env.example`** — 4 new env var entries with docs.
- **`.gitignore`** — expanded.
- **New files:** `SECURITY.md`, `BACKLOG.md`.

### Known quirks / preview-only issues

- **Preview-sandbox tile blocking:** MapTiler satellite and TomTom tiles sometimes fail to load in the preview tool's sandboxed Chrome, making `isStyleLoaded()` stuck at false. In the user's real browser these load normally. The poll-until-loaded fallback mitigates the worst case.
- **NSW-only incidents:** VIC/QLD/SA/WA/TAS feeds each need their own signup + source entry in `_INCIDENT_SOURCES`. Tracked in `BACKLOG.md`.
- **Traffic opacity is const, not user-adjustable** — slider in settings panel is in `BACKLOG.md`.

### Current feature state

All toggleable via the settings panel cog:
- **Basemap:** dark (MapTiler streets-dark) / light (streets-v2) / satellite (hybrid)
- **Projection:** flat (mercator) / globe
- **Terrain:** off / 3D
- **Accent:** 5 color presets (cyan default)
- **Data tiles:** shown / hidden (full-map view)
- **Overlays:** traffic flow / Places POI / traffic incidents (each independent)

Existing layers (unchanged in this session): flights + trails, weather stations (now clustered), earthquakes, fires, fuel stations (now with directions), major cities, route polyline.

---

## 2026-04-17 — Initial audit & fixes

**Scope:** Full audit of both applications, bug fixes, architectural improvements, data correctness fixes.

---

## Project overview

Single-file dashboard — one Python proxy, one HTML UI, no Docker.

| Layer | Tech | Location |
|-------|------|----------|
| Proxy server | FastAPI + httpx (in-memory cache, ~20 API proxies, flight WebSocket) | `gods-eye/server.py` |
| Dashboard | Single HTML file, MapLibre GL JS, all JS inline (~6600 lines) | `gods-eye/index.html` |

```bash
cd gods-eye && python server.py    # starts on port 8777
```

> **Note:** Entries below dated 2026-04-17 and earlier reference an Atlas-of-Australia
> proof-of-concept (Docker stack, ingesters, React panels) that was removed
> 2026-04-19. They're kept for history; see the 2026-04-19 entry above.

---

## Audit findings & fixes — Atlas (retired 2026-04-19)

### Critical fixes applied

1. **Secrets scrubbed from `.env`** — NSW FuelCheck API key, secret, and base64 auth were stored in plaintext. Removed and added rotation instructions. (Not a git repo, so no history leak.) Credentials were later restored at user's request since this is a local-only machine.

2. **Redis `decode_responses` mismatch fixed** — Ingesters used `decode_responses=False` (bytes), API used `True` (strings). WebSocket handler had `isinstance(data, bytes)` branches that would never fire. Both now use `decode_responses=True`.

3. **Dead proxy route removed** — `api/src/routes/proxy.py` was a CORS proxy for God's Eye endpoints. The Atlas frontend never called it. Deleted and unwired from `api/src/main.py`.

4. **Panel contract implemented per BUILD.md SS10** — Added `PanelProps<T> = { snapshot, history, isScrubbing }` to `frontend/src/panels/registry.ts`. Dock now passes props via a `PanelHost` wrapper. Existing panels still work (they read from the store internally).

5. **History ring buffer added to store** — `frontend/src/store/atlas.ts` rewritten: each slice now holds `latest` + `history` (capped at 240 entries). Unified `pushLive(panel, snap)` and `setFromSnapshot(panel, snap)` actions. Eliminated 10x copy-paste boilerplate with a factory pattern.

6. **Per-panel error boundaries** — `PanelErrorBoundary` class component in `Dock.tsx` catches render errors per-panel, shows a retry button instead of crashing the whole dashboard.

7. **WebSocket `onerror` now logs** — Was a silent no-op `() => {}`. Now logs to console.

### Map stack wired up

8. **Added MapLibre GL + deck.gl** — `maplibre-gl`, `@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/mapbox` added to `package.json`. `BaseMap.tsx` wired with Carto dark-matter basemap + MapboxOverlay. Mounted in `App.tsx` as the background hero layer.

### API improvements

9. **`/panels/{name}/history` implemented** — New endpoint in `api/src/routes/panel.py`. Returns time series via `XRANGE` from the panel's ring stream, clamped to 24h window, capped at 2000 points.

10. **`/snapshot?t=` clamped to 24h window** — Previously accepted any timestamp (future dates returned empty rings, looked like "panel offline"). Now clamps to `[now - 24h, now + 60s]` and returns `clamped: bool` in the response.

### Data correctness

11. **Parliament sitting logic fixed** — Was checking if `today in recent_division_dates` (wrong: sitting days without a division → false negative). Now checks per-chamber whether any division occurred in the last 24h, and whether either chamber divided in the last 7 days for session_active.

12. **Economic `direction` field now computed** — Was hardcoded to `"unchanged"` for all indicators. Now compares current vs previous observation from ABS SDMX (`startPeriod=-2`), and current vs previous row in RBA CSV.

### Ingester stubs documented

13. **11 empty stub files given explicit TODO headers** — `abs.py`, `aemo.py`, `aph.py`, `bom_radar.py`, `bom_warnings.py`, `cfa.py`, `emergency_wa.py`, `gtfs_rt.py`, `opensky.py`, `rba.py`, `rfs.py` each now explain they're intentional stubs, which aggregator ingester covers them, and the 3-step process to make them real.

### Frontend polish

14. **Glassmorphism toggle** — `BLUR ON`/`BLUR OFF` button in header. Persists via localStorage. Sets `html[data-glass="off"]` which disables `backdrop-blur-xl` via CSS. BUILD.md SS14 #9 warned about this.

15. **`tsconfig.json` updated** — Added `"types": ["vite/client"]` so `import.meta.env` resolves.

16. **Stream client deduped** — `PANEL_KEYS` and `PanelKey` now imported from the store instead of redeclared.

### Infrastructure

17. **Nginx Dockerfile uses build-arg** — `ARG NGINX_CONFIG=dev|prod` selects which config to bake in. `docker-compose.prod.yml` sets `NGINX_CONFIG: prod` automatically. No more manual `cp default.conf.prod default.conf`.

18. **`ops/DEPLOY.md` updated** — Removed manual file-swap instructions, added strong password + credential rotation guidance.

### File reorganisation

19. **God's Eye moved to `gods-eye/` subfolder** — `gods-eye-server.py` -> `gods-eye/server.py`, `gods-eye.html` -> `gods-eye/index.html`, `start-gods-eye.bat` -> `gods-eye/start.bat`. Internal path references updated. `gods-eye/README.md` added explaining it's a separate sub-project. Root `__pycache__/` deleted.

---

## Audit findings & fixes — God's Eye

### Server (`gods-eye/server.py`)

20. **httpx clients get closed on shutdown** — Converted two `@app.on_event("startup")` handlers to a single `lifespan` context manager. Shutdown side closes all 4 global `AsyncClient` instances.

21. **Caches bounded with LRU eviction** — `_cache` capped at 500 entries (evicts oldest on overflow). `_route_cache` capped at 500. `_bom_obs_cache` and `_om_detail_cache` already had bounds.

22. **Rainviewer proxy path validated** — Added regex: only allows `^[a-zA-Z0-9/_]+\.png$`. Returns 400 otherwise.

23. **Silent `except: pass` replaced with logging** — ~10 instances now use `log.debug()` or `log.warning()` via `logging.getLogger("gods-eye")`.

24. **`.env` path fixed** — After moving to `gods-eye/`, the server couldn't find `.env` in the parent directory. Now tries both `gods-eye/.env` and `../.env`.

25. **Startup banner fixed for Windows** — Unicode box-drawing characters crashed on cp1252 console. Replaced with ASCII.

### Dashboard (`gods-eye/index.html`)

26. **`response.ok` checks added to all 23 fetch sites** — Every `fetch()` now validates the HTTP status before calling `.json()`. Bad responses throw clear errors instead of cryptic JSON parse failures.

27. **Interval cleanup mechanism** — All 14 `setInterval()` calls tracked via `_trackInterval()`. `beforeunload` listener clears them all. Polling callbacks check `_running` flag.

28. **Flight trail memory capped** — `TRAIL_HARD_CAP = 200` prevents unbounded growth per aircraft.

29. **Flight detail modal crash guard** — `flightData.find()` returning undefined now shows "Aircraft no longer in view" instead of crashing on `.lat`/`.lng` access.

30. **Modal async race conditions guarded** — Weather and flight modals check `modal.classList.contains('hidden')` before writing innerHTML after async fetches.

31. **Flight search debounced** — 150ms debounce on input keystrokes.

### Data correctness (God's Eye)

32. **Flight tails now hide with toggle** — The `toggleLayer` function built prefix `layer-flights` but the trail layer was named `layer-flight-trails` (no 's'). Added explicit check to also toggle trail layer visibility.

33. **Antarctic stations filtered from weather extremes** — BOM feeds include Australian Antarctic bases (Mawson at -67S, Casey at -66S, etc.) tagged as Tasmania. Weather tile now filters `lat < -45` when computing hottest/coldest. Coldest went from -22.9C (Dumont d'Urville, Antarctica) to -0.5C (Mt Wellington, Tasmania).

34. **ABS population fixed** — SDMX API returns 422 on all query formats (ABS changed dimension keys). Added primary scraper for ABS population clock page, which reliably returns the current estimate (29,096,009). Fallback scraper now validates against plausible ranges (20M-35M).

35. **RBA cash rate fixed** — CSV URLs return 404 (moved). HTML scraper patterns didn't match the RBA page format (rate is in plain `<td>` without "per cent" suffix). Added `<td>(\d+\.\d+)</td>` pattern. Now correctly returns 4.1%.

36. **NSW Fuel API connected** — Was failing because `.env` wasn't found after the folder move (fix #24). Now shows NSW + WA coverage with ULP, Diesel, E10 across 2767+ stations.

---

## Known remaining issues

| Issue | Severity | Notes |
|-------|----------|-------|
| ABS CPI, Unemployment, GDP return null | Medium | ABS SDMX API changed dimension keys. Population was fixed via scraping; these could get similar scrapers but they're quarterly indicators. |
| 10 Atlas ingester sources are stubs | Low | Intentional — data flows through aggregator ingesters (emergencies, transit, economic, etc). Implementing individual sources is a milestone 6+ task. |
| Atlas panels don't yet use `history` or `isScrubbing` props | Low | Props are wired through from the Dock; panels still read from Zustand directly. Migration is per-panel work. |
| Atlas `BaseMap.tsx` has no data layers yet | Low | Map renders but no flights/quakes/weather overlays. These come with milestone 6-7 panel implementations. |
| God's Eye sparkline canvases not reused | Low | New canvas per update; minor memory churn. |
| No ARIA labels on God's Eye dynamic content | Low | Accessibility gap in the inline-JS dashboard. |

---

## File inventory

```
Atlas of Australia/
+-- BUILD.md                    # Original architecture & milestone plan
+-- CHANGELOG.md                # This file
+-- README.md                   # Minimal getting-started
+-- .env                        # Local credentials (gitignored)
+-- .env.example                # Template
+-- .gitignore
+-- docker-compose.yml          # Dev stack
+-- docker-compose.prod.yml     # Production overrides (resource limits, HTTPS, certbot)
+-- sources.yaml                # Ingester poll intervals & ring sizes
+-- api/                        # FastAPI service
+-- contracts/                  # Shared JSON schemas
+-- db/                         # Postgres init scripts
+-- frontend/                   # React/Vite SPA
+-- gods-eye/                   # Standalone dashboard (separate sub-project)
|   +-- README.md               # What it is, how to run
|   +-- server.py               # FastAPI proxy (~2550 lines)
|   +-- index.html              # MapLibre dashboard (~4700 lines)
|   +-- start.bat               # Windows launcher
+-- ingesters/                  # Python data ingesters
+-- nginx/                      # Reverse proxy configs (dev + prod)
+-- ops/                        # DEPLOY.md, backup.sh, healthcheck.sh
```
