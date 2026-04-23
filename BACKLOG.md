# God's Eye — Backlog

Deferred tasks and ideas. Not prioritised — pick whatever's useful next.

Each item lists **rough scope** so it's easy to pick one that fits the time you have.

---

## Tidy-ups from the Atlas removal (2026-04-19)

The Atlas proof-of-concept (`api/`, `ingesters/`, `frontend/`, `db/`, `nginx/`, `ops/`, Docker compose files, `sources.yaml`) was removed. Leftover housekeeping:

- [ ] **Prune `.env.example`** — still has `HTTP_PORT=8080`, Postgres/Redis/API/Vite sections, and ingester creds (`OPENSKY_USER`, `TFNSW_API_KEY`, `PTV_*`, `TRANSLINK_*`, `OPENAUSTRALIA_*`, `BOM_USER_AGENT`, `YAHOO_USER_AGENT`) that no longer apply. Keep only the five God's Eye keys (`GOOGLE_MAPS_BROWSER_KEY`, `MAPTILER_KEY`, `TOMTOM_KEY`, `NSW_TRAFFIC_API_KEY`, `NSW_FUEL_*`). **Scope:** ~10 min.
- [ ] **Delete `.dockerignore`** — no Docker in the repo any more. **Scope:** 1 min.
- [ ] **CHANGELOG "Project overview" section** (end of file) — describes the removed Atlas architecture ("two independent dashboards", port 8080, ingesters/api/frontend table). Should be God's-Eye-only or deleted. **Scope:** ~5 min.
- [ ] **Audit `CHANGELOG.md` for Atlas-only entries** — most pre-2026-04-18 audit entries are about Atlas ingesters. Either archive them under a `## Atlas (retired)` heading or delete. **Scope:** ~20 min.
- [ ] **CLAUDE.md review** — if it references Atlas-specific conventions (milestones, ingester structure), prune. **Scope:** ~5 min.

---

## Speed cameras (added 2026-04-19)

`/proxy/speed-cameras` aggregates NSW + QLD + ACT (6,413 sites, ~1,535 mappable). Remaining work:

- [ ] **VIC speed cameras** — data.gov.au publishes only a 2023 XLSX snapshot. Revisit if they release CSV/JSON. Would add ~200 fixed cameras. **Scope:** ~30 min once a format exists.
- [ ] **SA speed cameras** — no open-data API. Locations are listed on `speedcameras.sa.gov.au` as HTML tables. HTML-scrape option, ~100 fixed cameras. **Scope:** ~1.5 hours (scraper + structure flex).
- [ ] **NSW mobile + QLD camera coordinates** — both feeds return descriptors only (road/suburb for NSW mobile; site number + primary descriptor for QLD). Geocode via Nominatim (free, 1 req/s) to get lat/lng and add to the map. Cache indefinitely since sites rarely move. **Scope:** ~2 hours; adds ~4,000 points.
- [ ] **Clustering on `src-speedcams`** — at zoom 4 with 1,500+ points the map is crowded. Follow the incidents/weather cluster pattern: `cluster: true`, `clusterMaxZoom: 9`, `clusterRadius: 50`. Needs the type-coloured core layer to gain an `['!', ['has', 'point_count']]` filter. **Scope:** ~30 min.
- [ ] **Data-freshness chip** — popup currently shows type/state/suburb. Add a "Last updated" footer sourced from the upstream CSV/CKAN/Socrata metadata where available. **Scope:** ~45 min.
- [ ] **Legend/colour key** in the data layers panel — right now the three speed-camera types (fixed=pink, red-light=red, mobile=amber) are undocumented in the UI. **Scope:** ~20 min.

---

## Traffic incidents — more coverage

Current `/proxy/traffic-incidents` endpoint covers **NSW only** via TfNSW OpenData (`NSW_TRAFFIC_API_KEY` in `.env`). Other states have public feeds with varying auth requirements:

- [ ] **VIC — VicRoads** — requires developer signup at https://developer.vicroads.vic.gov.au/. Add `VIC_TRAFFIC_API_KEY` to `.env`, add source entry to `_INCIDENT_SOURCES` in `server.py`. **Scope:** ~1 hour.
- [ ] **QLD — QLD Traffic** — docs at https://qldtraffic.qld.gov.au/opendata. Historically needed a key via data.qld.gov.au. **Scope:** ~1 hour.
- [ ] **SA — DIT (Dept of Infrastructure & Transport)** — open data portal at data.sa.gov.au. **Scope:** ~1 hour.
- [ ] **WA — Main Roads WA** — https://www.mainroads.wa.gov.au/technical-commercial/trafficmap/. Feed may be XML. **Scope:** ~1–2 hours (XML parse).
- [ ] **TAS — Transport Services Tasmania** — RSS-ish. **Scope:** ~1 hour.

Each state adds a dict to `_INCIDENT_SOURCES` with its URL + auth header format. The existing `_extract_incident_props` can be extended with per-source property mapping if schemas differ wildly; the current shape is tuned to NSW.

---

## Settings panel — more knobs

- [ ] **Traffic flow opacity slider** — currently a fixed constant (`TRAFFIC_FLOW_OPACITY = 0.65` in `index.html`). Expose an HTML `<input type="range">` in the OVERLAYS section; persist under `localStorage['gods-eye-traffic-opacity']`; apply via `map.setPaintProperty(TRAFFIC_FLOW_LAYER, 'raster-opacity', value)`. **Scope:** ~30 min.
- [ ] **Hillshade exaggeration slider** — similar idea for terrain intensity. Default 0.5; range 0–1.5. Apply via `map.setTerrain({source, exaggeration})` and on hillshade layer's `hillshade-exaggeration`. **Scope:** ~30 min.
- [ ] **POI density slider for Google Places overlay** — currently `maxResultCount: 20` (API cap). We could lower the practical count by filtering results by rating. **Scope:** ~30 min.

---

## Map rendering

- [ ] **POI clustering for Google Places overlay** — incidents now use `cluster: true`. Apply the same pattern to `src-places-poi` if dense areas feel crowded. Note: Places source data refreshes on `idle` so clustering should work transparently. **Scope:** ~30 min.
- [ ] **Incidents severity filter** — data layer panel entry with a "Show Major only" toggle. NSW feed's `isMajor` field is the driver. **Scope:** ~30 min.
- [ ] **Hybrid basemap dark-themed labels** — the `hybrid` style uses light-themed labels that can read poorly on bright imagery. Consider overriding label colours via `_enhanceTextLabels` to a lighter halo. **Scope:** ~30 min.
- [ ] **Incidents cluster expand animation** — current behaviour: `easeTo(zoom)`. MapLibre also supports splaying a cluster into a spider when maxZoom is reached. **Scope:** ~1 hour (with maplibre-spiderifier lib).

---

## Data sources

- [ ] **Waze alerts as an alternative traffic-incident feed** — requires Waze CCP (Connected Citizens Program) partnership. Overkill for hobby use; noting as a "if you ever want it" option.
- [ ] **Google Roads API for snap-to-road + speed limit display** — distinct from Places. **Scope:** ~2 hours; paid per call.
- [ ] **AQI / air quality data layer** — the `layer-panel` already lists "Air Quality" as a placeholder. Hook to a free feed like OpenAQ or Air Quality Open Data Platform. **Scope:** ~2 hours.

---

## Performance / robustness

- [ ] **Basemap-swap race still has edge cases in preview sandbox** — when MapTiler's satellite tiles are blocked, the `isStyleLoaded()` check stays false and the 10s poll cap forces an empty re-add. Consider a "partial re-add with retry" pattern that adds each layer individually and retries failed ones. **Scope:** ~1 hour.
- [ ] **Flight marker rate-limiting already in place** — monitor in production if flight counts get big. **Scope:** monitoring only.

---

## Security / deploy

- [ ] **Pre-commit hook with `gitleaks`** — scan for accidental secret commits before `git push`. One-time setup. **Scope:** ~15 min (install + config).
- [ ] **Public-repo readiness checklist** — verify `.gitignore` still blocks all `.env*`, review SECURITY.md, add key rotation schedule. **Scope:** ~30 min.
