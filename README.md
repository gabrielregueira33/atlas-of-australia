# God's Eye — Atlas of Australia

A single-page situational-awareness dashboard for Australia: live flights, fires,
earthquakes, weather stations, fuel, markets, road traffic, speed cameras, and
more — rendered on a MapLibre globe with toggleable data layers.

One Python server, one HTML file. No Docker.

```bash
cd gods-eye
python server.py    # http://localhost:8777
```

## Configuration

Copy `.env.example` to `.env` and fill in the keys you want. Every layer
degrades gracefully if its key is missing — you can start with zero keys and
still get flights, fires, earthquakes, BoM weather, and speed cameras.

| Key | Purpose | Required? |
|---|---|---|
| `GOOGLE_MAPS_BROWSER_KEY` | Directions, Places autocomplete, POI overlay | optional |
| `MAPTILER_KEY` | Vector basemap (streets-dark / streets / satellite hybrid) | recommended |
| `TOMTOM_KEY` | Live traffic-flow raster overlay | optional |
| `NSW_TRAFFIC_API_KEY` | NSW traffic incidents (`/proxy/traffic-incidents`) | optional |
| `NSW_FUEL_API_KEY` / `_SECRET` / `_BASIC_AUTH` | NSW FuelCheck fuel prices | optional |

See [SECURITY.md](SECURITY.md) for rotation, restriction, and leak-response
procedures for every key.

## Layout

```
gods-eye/
├── server.py       FastAPI proxy + cache + flight WebSocket
├── index.html      Dashboard (MapLibre + inline JS)
├── au_places.json  Offline gazetteer for the search box
├── start.bat       Windows launcher
└── README.md

Australian_Free_APIs_*    Reference inventory of free AU gov APIs
BACKLOG.md               Deferred tasks, tidy-ups, ideas
CHANGELOG.md             Session-by-session change log
SECURITY.md              Per-key rotation procedures
```

## Docs

- **[BACKLOG.md](BACKLOG.md)** — what's deferred, loose ends, follow-ups
- **[CHANGELOG.md](CHANGELOG.md)** — what changed when
- **[SECURITY.md](SECURITY.md)** — secret handling, key rotation
- **[Australian_Free_APIs_Reference.md](Australian_Free_APIs_Reference.md)** — catalogue of free AU government APIs
