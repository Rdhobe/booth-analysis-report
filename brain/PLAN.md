# PLAN.md: Web Server + Dashboard

Single source of truth for the serving track. Status: Phase A in build.

## 0. Goal

Serve the UP booth-intelligence dataset (`up_booth_report.xlsx` +
`data/processed/state_*.csv`) through a fast server with a dashboard
frontend. Operations on ~162k booth rows / ~3.4M vote records must feel
instant (< 1 s views, < 500 ms search).

## 1. Decisions (user-confirmed, 2026-10-06)

- **Database: SQLite** (single file, zero cost/ops; static snapshots,
  read-heavy). Supabase/MongoDB rejected — billing + latency for no
  gain. Postgres migration path kept open.
- **Deploy anywhere:** Dockerized FastAPI, stateless (Render / Railway /
  Fly.io / AWS identical).
- **Dashboard scope:** everything in `up_booth_report.xlsx` — 94-col
  `All_ACs`, `Booth_Votes`, `Zone_Counts`, `Methods_Zones` — with charts.
- **Geo follows `brain/`:** AC polygons (DataMeet/SHRUG, vintage-matched)
  → booth geocoding with confidence (T2.1) → Voronoi clipped to AC in
  EPSG:32644, `geom_source='voronoi'`, dashed/"approximate" (D2,
  ARCHITECTURE §5, DESIGN §2). Schematic tile-grid until then.
- **Report rule (RULES.md):** new data extends existing sheets as
  columns, never new sheets.

## 2. Architecture

```
data/processed/state_*.csv ─▶ build_servedb.py ─▶ servedb.sqlite
                                                        ├─▶ FastAPI (/api/*)
                                                        └─▶ static frontend (/)
Docker image, read-only DB, GZip, ETag caching.
```

Rationale: the 272 MB fact CSV and 59 MB xlsx can never be
scanned/parsed per request — one offline build → indexed store →
millisecond queries.

## 3. Data layer (`servedb.sqlite`)

Builder `Scripts/build_servedb.py` (extends `build_store.py` pattern;
reads `state_*.csv` + `configs/ac_format.json`):

| Table | Grain | Contents |
|---|---|---|
| `booth_row` | (AC, PS) ≈ 162k | All_ACs display row: serials, zone, diffs, Party B, shares, E/M/F/O/T/TO%, 2024 AC electors, 36 demo cols |
| `booth_election` | booth×election ≈ 385k | electors, M/F/O/T, polled, valid, nota, src |
| `vote` | booth×party ≈ 3.4M | candidate, party, votes |
| `ac_summary` | AC×election | booth count, electors, polled, turnout%, party totals, zone counts |
| `coverage` | rows | SEG-CHECK / DEMO-CHECK / HINDI_XLSX_SKIP / NO-TRIPLET |
| `geo` (phase 2) | booth | lat/lon, geom_source, confidence, Voronoi GeoJSON per AC |

Indexes: `(ac_no)`, `(ac_no, election)`, `(zone)`, FTS5 on
`(ps_name, ac_name)`. WAL + read-only at serve. ~250–350 MB.

## 4. API (FastAPI, 7 endpoints)

`GET /api/meta` (boot payload) · `GET /api/acs?district=` ·
`GET /api/booths?ac=&zone=&q=&party=&sort=&page=&ps=` (paginated
100/page, always scoped — never full-table) ·
`GET /api/booth/{ac}/{ps}` (drill-down) ·
`GET /api/ac/{ac}/votes?election=` ·
`GET /api/zones` · `GET /api/coverage`.
orjson + GZip + immutable caching, `limit<=500` cap,
`EXPLAIN QUERY PLAN` per endpoint.

## 5. Frontend (offline-safe, no CDN, no build step)

Vanilla HTML/CSS/JS via FastAPI `StaticFiles`. Header KPIs ·
district tile-grid (reuse `GRID_POS`) → AC drill · zone donut +
party/turnout-M/F SVG charts · virtualized booth grid, server-side
search/sort/filter, 94 cols in groups (Results | Turnout |
2017 demographics) · booth drawer (shares, M/F/O, `(modeled)` demo
block + calibration warning, SEG-CHECK) · coverage page + verbatim
Methods (honesty rules: modeled tags, grey-outs, no fraud language,
Compliance-Mode banner hook).

## 6. Geo phase (per brain/, post-v1)

Vendor polygons → geocode with confidence → Voronoi/32644/clip →
`geo` table → `GET /api/geo/ac/{ac}` → vendored-Leaflet rendering.
Acceptance: ≥90% points in correct AC, cells tile without overlap.

## 7. Deploy & hardening (SECURITY.md)

`Dockerfile` (3.12-slim, fastapi/uvicorn/orjson), `render.yaml` /
`fly.toml`, `/api/meta` healthcheck, OIDC/RBAC if public + legal
review (§8), aggregates-only export with audit log. Rebuild = rerun
report → rerun servedb → redeploy.

## 8. Phases & acceptance

- **A (v1, no geo):** servedb + API + frontend + Docker. AC view < 1 s,
  search < 500 ms. [CODE WRITTEN 2026-10-06 — NOT YET BUILT/RUN: needs
  `pip install -r server/requirements.txt`, `build_servedb.py` full
  build, endpoint smoke tests, deploy; run externally]
- **B (geo):** per §6. [TODO]
- **C:** compliance schedule, export audit, auth. [TODO]

## 9. Open questions

1. Charts: [hand-rolled SVG] vs vendored ECharts?
2. [LAN/localhost first] vs public now?
3. Booth_Votes view in v1 or [All_ACs + drill-down only]?

(End of file)
