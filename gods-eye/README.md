# God's Eye — standalone dashboard

This is a **separate sub-project** from the main Atlas of Australia dashboard.
It predates the Redis/FastAPI/React architecture described in the top-level
[`BUILD.md`](../BUILD.md) and runs entirely on its own:

- `server.py` — a single-file FastAPI CORS proxy for the same Australian data
  sources the main Atlas ingesters target (OpenSky, RFS, AEMO, ABS, RBA, etc).
- `index.html` — a self-contained MapLibre GL dashboard that fetches from
  `server.py`'s `/proxy/*` endpoints.
- `start.bat` — Windows launcher (double-click to run `py server.py`).

## Running

```bash
pip install fastapi uvicorn httpx
python server.py
# → open http://localhost:8777/
```

## Relationship to Atlas

Atlas (the `api/` + `ingesters/` + `frontend/` stack at the repo root) does
**not** use any of these files. The shared `api/src/routes/proxy.py` module
that used to re-export a subset of these endpoints has been removed, because
the Atlas frontend never called it.

Keep this folder if you still use the HTML dashboard; delete the folder
entirely if you don't.
