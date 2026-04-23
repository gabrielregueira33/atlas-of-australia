# Security

## Where secrets live

All secrets are stored in `.env` at the repo root. `.env` is gitignored; never commit it.
The template `.env.example` documents every required variable with empty values — that file
**is** committed.

## Google Maps API key (`GOOGLE_MAPS_BROWSER_KEY`)

This is a **browser** key. It is visible to anyone who opens the running page's DevTools
(Network tab shows the `maps.googleapis.com/maps/api/js?key=...` request). That is unavoidable
for Maps JS — it's how the protocol works. The key is **not** protected by secrecy.

What protects the key:

1. **HTTP referrer restrictions** set in Google Cloud Console. The key will only work from
   approved origins (`http://localhost:8777/*`, `http://127.0.0.1:8777/*`, plus any production
   domain). A scraped key from the public repo or a user's DevTools is useless from any other origin.
2. **API restrictions** — the key can only call Maps JS, Places, Directions, Geocoding.
3. **Billing budget alert** at $5/month. Email fires if anything spikes.
4. **The key is injected server-side from `.env` at serve time** — `gods-eye/index.html` in git
   contains only the placeholder `{{GOOGLE_MAPS_BROWSER_KEY}}`. The real value is never in a
   tracked file.

## Before the first push to GitHub

1. **Verify `.gitignore` blocks `.env`:** `git check-ignore .env` should print `.env`.
2. **Install a secret scanner locally.** Options:
   - [`gitleaks`](https://github.com/gitleaks/gitleaks) — fastest, single binary.
     ```
     # Scan the working tree before pushing:
     gitleaks detect --source . --no-banner
     # Optional pre-commit hook:
     gitleaks install --hook=pre-commit
     ```
   - [`trufflehog`](https://github.com/trufflesecurity/trufflehog) — deeper heuristics.
3. **Audit the staged diff once manually** before the first push. `git diff --cached | grep -iE 'key|secret|token|password'`.
4. **Enable GitHub secret scanning** on the repo (Settings → Code security → Secret scanning).
   Free for public repos. If a key slips through, GitHub will notify Google and the key is
   auto-revoked within minutes.

## Key rotation procedure

If a key is exposed (committed, posted, leaked):

1. Go to Google Cloud Console → APIs & Services → Credentials.
2. **Create a new key** with the same restrictions as the compromised one.
3. Update `.env` with the new value. Restart the God's Eye server.
4. **Delete** the old key (not just disable — delete).
5. If the leak was in git history, the key is considered compromised forever even after the
   commit is rewritten. Rotation is mandatory; history rewrites are not sufficient.

## MapTiler key (`MAPTILER_KEY`)

Browser-visible by nature — the style URL (`?key=...`) appears in Network tab.
Protected by **Allowed Origins** restriction in the MapTiler dashboard
(https://cloud.maptiler.com/account/keys/). Set to `http://localhost:8777` plus any
production domain. Free tier: 100k tile requests/month; rotate by creating a new key,
updating `.env`, restarting the server, then deleting the old key.

## TomTom key (`TOMTOM_KEY`)

Browser-visible (appears in traffic tile URLs). Protected by allowed origins in the TomTom
Developer Portal. Free tier: 2,500 requests/day — hard cap, not a soft quota. Rotate
procedure identical to MapTiler: new key → `.env` → restart → delete old.

## TfNSW OpenData key (`NSW_TRAFFIC_API_KEY`)

Server-side only — used by `server.py`'s `/proxy/traffic-incidents` endpoint. Never reaches
the browser (the browser only sees already-normalised GeoJSON). Free tier, unlimited reads,
no hard cap. Sign up at https://opendata.transport.nsw.gov.au/ and tick "Live Traffic — Hazards"
when creating an app. Rotate via the same "My Apps" dashboard. Because this key is server-side,
it has no referrer/origin restrictions — rotate it if you ever suspect it leaked.

## Other credentials in `.env`

NSW FuelCheck (`NSW_FUEL_API_KEY`, `NSW_FUEL_SECRET`, `NSW_FUEL_BASIC_AUTH`) are server-side
credentials used by `gods-eye/server.py`. They never reach the browser. Same `.env` storage,
same rotation procedure (contact NSW FuelCheck support to rotate). If they ever appear in git
history, assume they are leaked and request new credentials.
