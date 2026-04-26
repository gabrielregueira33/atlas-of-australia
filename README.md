# God's Eye — Atlas of Australia

A single-page situational-awareness dashboard for Australia: live flights, fires,
earthquakes, weather stations, fuel, markets, road traffic, speed cameras,
NSW live traffic webcams, and more — rendered on a MapLibre globe with
toggleable data layers organised by domain card.

One Python server, one HTML file. Run locally with Python or anywhere with Docker.

```bash
# Local Python
cd gods-eye && python server.py    # http://localhost:8777

# Or Docker (from repo root)
docker build -t gods-eye . && docker run --rm -p 8777:8777 --env-file .env gods-eye
```

## Deploy

The repo includes `Dockerfile`, `requirements.txt`, and `fly.toml` for one-command
deployment to [Fly.io](https://fly.io). The server reads `PORT` from env, so the
same image runs cleanly on Render, Railway, or your own Docker host.

```bash
flyctl auth login
fly launch --copy-config --no-deploy   # accepts fly.toml as-is; pick an app name + region
flyctl secrets set MAPTILER_KEY=... GOOGLE_MAPS_BROWSER_KEY=... TOMTOM_KEY=... \
                   NSW_TRAFFIC_API_KEY=... NSW_FUEL_API_KEY=... NSW_FUEL_AUTH_HEADER=...
fly deploy
```

The free Fly tier (256 MB, shared CPU, syd region) is plenty for this app.
WebSocket-based flight push works natively — no polling fallback needed.

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
