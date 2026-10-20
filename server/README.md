# server — UPBI web serving track (PLAN: `brain/PLAN.md`)

FastAPI (read-only SQLite) API + assets. API-only: the dashboard is
the Next.js app in `../web/`, which proxies this API.

| File | Purpose |
|---|---|
| `app.py` | API: `/api/meta|acs|booths|booth/{ac}/{ps}|ac/{ac}/votes|ac/{ac}/sexratio|ac/{ac}/religion|ac/{ac}/ages|ac/{ac}/averages|ac/{ac}/past|overview|trend|margins|zones|coverage|methods` + `/` (pointer JSON) + `/assets` + `/docs` |
| `insights.py` | Router for `/api/insights/meta|overview|types|acs|ac/{ac}|surprises|card`: serves the Phase 1 model output (types, unusual results, expected ranges). Reads static JSON, no database. `COMPLIANCE_MODE=on` removes the expected range server-side |
| `insights_extra.py` | Mounted on the same router: `/api/insights/watchlist`, `/turnout`, `/alliances`, `/simulator/setup`, `POST /simulate`, `/booths`, `/booths/{ac}`, `/extra/meta`; also adds an `extra` block to `/ac/{ac}` and `extra_models` to `/card`. Pure Python, reads static JSON |
| `insights_data/` | `ac_insights.json` + `model_card.json` (`python Scripts/ml/build_insights.py --export-server`) and `extra_insights.json`, `simulator_inputs.json`, `booth_segments.json`, `extra_model_card.json` (`python Scripts/ml/build_extra.py --export-server`); baked into the image |
| `test_insights.py`, `test_insights_extra.py` | API tests: `python -m pytest server/test_insights.py server/test_insights_extra.py -q` |
| `frontend/docs.html` | Static offline API reference (Next.js contract companion) |
| `DASHBOARD_LOGIC.md` | Formula contract for every dashboard number (seats, shares, zones, voter, religion) — the Next.js source of truth |
| `assets/parties/` | Party logos (`<code>.png`, lowercase) → `/assets/parties/bjp.png` |
| `assets/portraits/` | Candidate portraits (name-slug `.jpg`) → `/assets/portraits/…` |
| `requirements.txt` | fastapi + uvicorn + orjson (separate from root pipeline deps) |
| `Dockerfile`, `render.yaml`, `fly.toml` | Deploy anywhere |
| `servedb.sqlite` | Built artifact (git-ignored): `python Scripts/serve/build_servedb.py --db output/servedb.sqlite` (see "Booth store" below) |
| `test_booth_party.py` | Tests of the party-selectable booth endpoints on a tiny synthetic store: `python -m pytest server/test_booth_party.py -q` |

## Local run (external terminal)

```
.\.venv\Scripts\python.exe -m pip install -r server/requirements.txt
python Scripts/serve/build_servedb.py --districts Agra Saharanpur --db server/servedb.sqlite   # pilot slice
.\.venv\Scripts\python.exe -m uvicorn server.app:app --reload
```

Open http://127.0.0.1:8000 — try `#/ac/1`, `#/booth/1/1`, `#/coverage`.

Full build: `python Scripts/serve/build_servedb.py --db server/servedb.sqlite`
(~5 min) or `--db output/servedb.sqlite` with `DB_PATH` env override.

## Booth store and the party picker

The booth endpoints (`/api/overview|trend|booths|booth|zones|ac/{ac}/past`) take `party=` (default `BJP`): the shares, the strongest opponent, the
differences and the zones are then that party's. They read the `booth_party` table, which `Scripts/serve/booth_party.py` computes from the store's own
booth votes for BJP, SP, BSP and INC (`/api/meta` lists them under `parties`). A store built before the table existed still serves the BJP from the
workbook columns and refuses other parties with a 400 that names the fix; add the table without a rebuild:

```
python Scripts/serve/add_booth_party.py --db output/servedb.sqlite     # stop the API first, restart after
```

Rebuilding the store from the raw sheets (paths fixed 2026-10-20, run from the repo root):

```
python -m Scripts.report.build_state_report --ac24-dir data/2024/converted --ac24-verified-json output/ml/booth_segments.json   # ~10 min + workbook save
python Scripts/serve/build_servedb.py --db output/servedb.sqlite                                                               # ~5 min
```

`--ac24-verified-json` keeps 2024 booth results only for seats whose Form 20 workbook equals the official totals and is unchanged since it was checked (each verified workbook is fingerprinted in `booth_segments.json`; re-run `Scripts/ml/build_extra.py` to re-check the workbooks in your copy). Step-by-step setup: `SETUP_GUIDE.md` at the repository root. Rules for the party view are in
`DASHBOARD_LOGIC.md` section 12.

## Rules

- API is read-only (`mode=ro` connections); never full-table (booths endpoint requires `ac` or `q`).
- Responses for static endpoints (`meta/acs/overview/sexratio/zones/coverage/methods`) are cached in-memory (store is immutable; restart picks up rebuilds).
- Auth: set `API_KEY` (any shared/public deploy); clients send `X-API-Key`. Unset = open dev mode. `/api/meta` stays open for health checks.
- CORS: `ALLOWED_ORIGINS` (default `*`); tighten for public deploys alongside the Next.js origin.
- Frontend never loads raw tables: paginated display rows (≤500), pre-aggregated charts.
- `(modeled)` tags + calibration warning stay on every demo surface; anomaly language stays `statistical_outlier`.
- `COMPLIANCE_MODE=on` hides opinion layers (banner hook; wire schedule before any public release).

## Deploy to Render (monorepo)

The store (`servedb.sqlite`, ~300MB+) is git-ignored, so Render
downloads it once from a GitHub Release onto a persistent disk.

1. Full build locally (wait for `BUILD COMPLETE`):
   `python Scripts/serve/build_servedb.py --db server/servedb.sqlite`
2. GitHub repo → Releases → Draft new release (e.g. `store-2026-10-06)
   → attach `server/servedb.sqlite` → copy the asset URL.
3. Push the repo (code + `render.yaml` + `Dockerfile`; the DB stays
   out of git by `.gitignore`).
4. Render dashboard → New → Blueprint → pick the repo. Fill secrets:
   `STORE_URL` (asset URL from step 2), `API_KEY` (long random
   string), `ALLOWED_ORIGINS` (your Next.js URL). Create.
5. First boot downloads the store to `/data` (~1 min), later boots
   reuse it. Verify: `https://&lt;you&gt;.onrender.com/api/meta`
   shows `"store_ok": true`.
6. Frontend (Next.js): `NEXT_PUBLIC_UPBI=https://&lt;you&gt;.onrender.com`,
   key in a server-only env var, sent as `X-API-Key` (see `/docs`).

Free tier has no disks: delete the `disk:` block and it re-downloads
on every boot (slow). A paid instance + 1 GB disk is the sane setup.
Fly.io: same image; `fly volumes create upbi_data`, `fly secrets set
STORE_URL=… API_KEY=…` (see `fly.toml`).
