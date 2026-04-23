# CLAUDE.md — Project context

Orientation for future Claude sessions. Start here before diving in.

## What this repo is

Two independent Australian-data dashboards:

1. **God's Eye** (`gods-eye/`, port 8777) — **actively developed.** Single-file MapLibre dashboard, Python proxy server. Has 10+ data overlays (flights, weather, fires, earthquakes, fuel stations, etc.) plus the features added in the 2026-04-18 session (directions, POI overlay, traffic flow, incidents).
2. **Atlas** (`api/` + `frontend/`, port 8080, Docker) — **frozen.** Proof-of-concept dashboard the user explicitly said "we won't touch again." Don't modify unless explicitly asked.

## Run it

```bash
# God's Eye only (the active project):
python gods-eye/server.py
# Then open http://localhost:8777
```

No build step. Server reads `index.html` on each `GET /` and substitutes template placeholders (`{{...}}`) with env values from `.env`.

## Where things live

### `gods-eye/index.html` (~6000 lines, all inline)

Keep this file grep-friendly. Section comments use `═══` or `───` banners. Major sections in order:

| Section | Approx lines | What's there |
|---|---|---|
| `<head>` | 1–600 | CSS, basemap loader, font imports |
| `<body>` HTML | 600–700 | Topbar (cog button), settings panel, route panel, tiles, map container, modals |
| `<script>` state declarations | 1200–1300 | `flightData`, `weatherData`, `_flightMarkers`, `_builtinPOIHandlers`, etc. |
| Data fetch + normalise | 1300–2000 | `fetchFlights/Weather/Fires/Earthquakes/Fuel/...` |
| Map helpers (basemap / projection / accent / terrain / overlays) | 2300–2700 | `_performBasemapSwap`, `_enhanceBasemap`, `_apply3DTerrain`, `_addTrafficFlowLayer`, `_applyPlacesPoi`, `_applyIncidents`, etc. |
| Settings panel wire-up | 2800–2900 | `wireMapSettingsPanel`, overlay toggle handlers |
| Google Maps lazy loader + Directions + Places | 2500–2700 | `_ensureGoogleMaps`, `routeTo`, `googlePlacesPredict`, `googlePlaceDetailsRich`, rich POI popup renderer |
| `initMap()` | ~3550 | Map construction, data fetches, add*Layer calls, enhancements |
| Data layers (`addCitiesLayer`, `addWeatherLayer`, `addFireLayer`, etc.) | 3800–4900 | Each has its own source + layers + click handler |
| Search (Nominatim + Places augment) | 2100–2200 | `searchPlace`, `showSearchResults`, `flyToGooglePlace` |
| Fuel station flow | 4400–4700 | Modal, search, list rendering (with DIRECTIONS buttons) |
| Flight detail modal | 4000–4400 | Rich flight detail panel |

### `gods-eye/server.py`

FastAPI, single file. Key structures:

- `_HTML_PLACEHOLDERS` — tuple of env var names substituted into `index.html` at serve time.
- `serve_dashboard()` — the `GET /` route that reads + substitutes + returns.
- Proxy endpoints: `/proxy/flights`, `/proxy/weather`, `/proxy/fires`, `/proxy/earthquakes`, `/proxy/fuel`, `/proxy/traffic-incidents`, plus various helper routes.
- `_INCIDENT_SOURCES` — list of state-feed configs for the incidents normaliser. Currently just NSW.
- `_extract_incident_props(dict) -> dict` — schema normaliser for state hazards data (handles both flat and GeoJSON Feature shapes, strips HTML, title-cases category).

### `.env` (gitignored) + `.env.example` (tracked)

Required env vars:
- `GOOGLE_MAPS_BROWSER_KEY` — for Directions, Places Autocomplete, Places Nearby, Place Details.
- `MAPTILER_KEY` — basemap tiles.
- `TOMTOM_KEY` — traffic flow raster tiles.
- `NSW_TRAFFIC_API_KEY` — server-side only, never reaches browser.
- `NSW_FUEL_*` — pre-existing, for fuel stations.

### `BACKLOG.md`

Deferred tasks with scope estimates. Read this before starting a new feature — the user may have pointed you here.

### `SECURITY.md`

Per-key rotation procedures + pre-commit scanner setup (`gitleaks`). Reference when adding new keys or preparing for a public `git push`.

### `CHANGELOG.md`

Chronological log of major changes. Read the most recent entry for context before a session that extends prior work.

## Key code patterns worth knowing

### Template substitution

`server.py` does `.replace("{{VAR}}", os.environ.get(VAR, ""))` on each `GET /`. Add new browser-safe keys by appending to `_HTML_PLACEHOLDERS`. Server-side keys (like `NSW_TRAFFIC_API_KEY`) should NOT be added to this tuple — access them via `os.environ` in backend code only.

### Basemap swap dance (`_performBasemapSwap`)

MapLibre `setStyle` drops all custom sources/layers. After the new style loads we re-add everything from module state (`weatherData`, `flightData`, etc.). Critical gotchas:
- Use `{ diff: false }` — diff algorithm fails on paint-modified styles.
- Poll `isStyleLoaded()` every 500ms; don't use a flat timeout. Rebuild takes 3–8s sometimes.
- Re-attach terrain + overlays after data layers (order matters).

### Google Maps JS lazy loader (`_ensureGoogleMaps`)

Single-shot promise. Only loads the library on first API use (first search keystroke or first directions click). Loads `libraries=places,routes` — gives us `DirectionsService`, `places.AutocompleteService`, `places.PlacesService`. **Does not create a `new google.maps.Map()` anywhere** — that's what avoids the $7/1000 Dynamic Maps charge.

### Clustering

Both incidents and weather use MapLibre native clustering. Pattern:

```js
map.addSource(id, {
  type: 'geojson', data: ...,
  cluster: true, clusterRadius: 50, clusterMaxZoom: ..., clusterMinPoints: ...,
});
// Cluster circle layer filtered by ['has', 'point_count']
// Cluster count label layer same filter
// Individual feature layer filtered by ['!', ['has', 'point_count']]
// Click cluster → src.getClusterExpansionZoom() → map.easeTo({zoom})
```

Both clusters use `clusterMinPoints` to keep isolated features visible.

### MapTiler built-in POI clicks

MapTiler's `poi_z*` layers carry OpenStreetMap POI data free. Click handlers registered on each layer, tracked in `_builtinPOIHandlers` and removed before re-registering to avoid accumulation across basemap swaps. Popup shows name + class/subclass; provides DIRECTIONS button + Google Maps deep-link for users who want photos/reviews/hours.

### Rich Places POI popup (Google Places)

Two-phase popup:
1. Click fires immediate popup with `nearbySearch` snapshot data (instant UX).
2. `getDetails` fetches photo/reviews/hours/phone/website (~300ms); popup's HTML is swapped when result arrives.

Details cached per place_id per session (`_poiDetailsCache`) to avoid double-billing on repeat opens.

## Gotchas / things that have bitten us

1. **MapLibre v5 `style.load` event doesn't fire.** Use `styledata` + `isStyleLoaded()` check, or poll.
2. **MapLibre v5 `idle` event can fire before `load`.** Don't rely on idle for initial-load gating.
3. **Windows Python default source encoding** can be cp1252, not UTF-8. Use `\uXXXX` escapes for non-ASCII characters in string literals (we hit this with the `·` separator).
4. **Preview sandbox** (Claude Code's headless Chrome) blocks some external tile CDNs (Esri satellite tiles, sometimes MapTiler hybrid). Real browsers are fine. Don't over-engineer workarounds for sandbox-only issues — just note them.
5. **Listener accumulation on basemap swap** — `map.on('click', layerId, fn)` persists across setStyle. If you register handlers in a function that re-runs on swap, track + `off()` first.
6. **`google.maps.Marker` is officially deprecated** but still works. `AdvancedMarkerElement` is the replacement — noted for a future migration pass.

## Stylistic conventions in this repo

- Big state globals at the top of `<script>`, grouped with banner comments.
- Helper functions prefixed with underscore (`_enhanceBasemap`, `_getSavedAccent`, `_poiQueryTimer`).
- LocalStorage keys follow `gods-eye-<feature>` naming.
- CSS classes for popups follow `poi-*` and `popup-*` namespaces.
- Comments explain WHY, not WHAT. Prefer one good paragraph over many line-comments.

## When starting a new session

1. Skim the most recent entry in `CHANGELOG.md` for context.
2. Check `BACKLOG.md` — the user may point you there.
3. Confirm `.env` has the expected keys (`grep -c '^KEY_NAME=..' .env`).
4. `python gods-eye/server.py` to run.
5. When making changes: prefer minimal surgical edits. The file is big but section-commented; grep is your friend.
