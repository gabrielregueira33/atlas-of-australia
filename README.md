# God's Eye — Atlas of Australia

A single-page situational-awareness dashboard for Australia: live flights, fires,
earthquakes, weather stations, fuel, markets, road traffic, speed cameras,
NSW live traffic webcams, and more — rendered on a MapLibre globe with
toggleable data layers organised by domain card.

One Python server, one HTML file. No build step.

```bash
# Local
cp .env.example .env                   # then fill in any keys you have
pip install -r requirements.txt
python gods-eye/server.py              # http://localhost:8777
```

## Deploy

The repo ships with `Dockerfile`, `requirements.txt`, `render.yaml`, and `fly.toml`
so the same image runs on Render, Fly.io, Railway, Koyeb, or any Docker host.
`server.py` reads `PORT` from env, so most platforms work with zero config.

### Render.com (recommended — free, no credit card)

1. Push the repo to GitHub.
2. Sign in at [render.com](https://render.com) with GitHub.
3. **New + → Blueprint** → pick this repo. Render reads `render.yaml` and offers
   to apply it — click **Apply**.
4. In the new Web Service's **Environment** tab, paste real values for the
   API keys you want to use (each key is optional; missing ones just disable
   that layer).
5. Once Render shows the live URL (e.g. `https://gods-eye.onrender.com`), set
   the `GODS_EYE_ALLOWED_ORIGINS` env var to include it, and add the same URL
   to the origin restrictions on your Google Cloud / MapTiler / TomTom keys.

The free tier sleeps after 15 minutes of inactivity (~30 s cold start). To keep
it always-on for public use, change `plan: free` → `plan: starter` in the
dashboard ($7/mo). No code changes required.

### Fly.io (alternative — credit card required, ~$5/mo minimum)

```bash
flyctl auth login
fly launch --copy-config --no-deploy   # accepts fly.toml as-is
flyctl secrets set MAPTILER_KEY=... GOOGLE_MAPS_BROWSER_KEY=... TOMTOM_KEY=... \
                   NSW_TRAFFIC_API_KEY=... NSW_FUEL_API_KEY=... NSW_FUEL_SECRET=... \
                   NSW_FUEL_BASIC_AUTH=...
fly deploy
```

The `syd` region (Sydney) gives the lowest latency to AU data sources.
Fly's auto-stop config in `fly.toml` keeps idle cost low, but Hobby plan
billing has a $5/month minimum — pick this only if you want always-on with
no cold starts.

### Local Docker

```bash
docker build -t gods-eye . && docker run --rm -p 8777:8777 --env-file .env gods-eye
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
