# ARCHITECTURE.md

## 1. Pipeline overview
```
 Form 20 PDFs/CSV ─┐
 Lok Dhaba (AC)   ─┤→ [ingest.results] → fact_result_booth ─┐
 Roll PDFs (OCR)  ─→ [ingest.rolls] → [demog.estimate] → agg_electors_booth ─┤
 Booth locations  ─→ [geo.build] → dim_booth(+geom) ─→ [geo.crosswalk] ───────┤
 Census 2011      ─→ [geo.census_join] ──────────────────────────────────────┤
                                                                              ├→ feat_swing → [anomaly] → flag_anomaly
 Live text feeds  ─→ [sentiment.collect] → [nlp.score] → [geo.assign] → agg_sentiment ─┤
                                                                              └→ Streamlit dashboard
```

## 2. Repo layout
```
upbi/
├─ brain/                      # this folder
├─ configs/                    # YAML: paths, thresholds, model names, ACs in scope
├─ data/
│  ├─ raw/                     # immutable downloads (git-ignored, DVC optional)
│  ├─ interim/                 # OCR text, parsed tables
│  └─ processed/               # parquet + geoparquet
├─ src/upbi/
│  ├─ ingest/    results.py  rolls.py  lokdhaba.py  ocr.py
│  ├─ geo/       booths.py  voronoi.py  crosswalk.py  census.py
│  ├─ demog/     lexicon.py  estimate.py  aggregate.py
│  ├─ sentiment/ collect.py  score.py  assign.py  aggregate.py
│  ├─ anomaly/   features.py  shrink.py  model.py  explain.py
│  ├─ serve/     queries.py  layers.py
│  └─ common/    ids.py  schemas.py  logging.py  config.py
├─ app/streamlit_app.py
├─ tests/
├─ notebooks/                  # exploration only; never imported
└─ pyproject.toml
```

### Actual repo map (2026-10-04; converged from the plan above)
```
./
├─ brain/        # this folder (+ CHANGELOG.md lives here, not root)
├─ configs/      # ac_format.json (403 ACs), data_format.json (master schema),
│                # output_format.json (report workbook spec), agra_party_map_2024.csv
├─ data/         # INPUT STORAGE ONLY (immutable sources; nothing generated here)
│  ├─ 2017/ 2019/ 2022/ 2024/   # per-district PDFs + converted xlsx (same folder)
│  ├─ *.csv / *.xlsx            # reference datasets (LS 2024 etc.)
│  └─ processed/                # pipeline CSVs (agra_*.csv)
├─ output/       # GENERATED REPORTS ONLY (never inputs): agra_booth_report.xlsx
├─ Scripts/      # convert_form20.py, bulk_convert_form20.py, retry_pending.py,
│                # agra_pipeline.py, agra_compare.py (superseded), ocr_form20.py (paused),
│                # output_booth_report.py (Mahad-format builder)
└─ *.txt         # run logs (bulk_convert_log*.txt, agra_run1.txt)
```
Rule (2026-10-04): generated reports go to `output/`, never `data/`.

## 3. Data model (Parquet/GeoParquet; optional PostGIS later)
**dim_booth**: `booth_uid` PK, `election_id`, `ac_no`, `ps_no`, `ps_suffix`, `ps_name`, `lat`, `lon`, `geom_point`, `geom_cell` (nullable), `geom_source` {official|voronoi|none}, `district`, `urban_rural`.
**booth_crosswalk**: `booth_uid_prev`, `booth_uid_curr`, `link_type` {1:1|split|merge|new}, `confidence` 0-1, `method`.
**fact_result_booth**: `booth_uid`, `election_id`, `party`, `candidate_id`, `votes`, plus `electors`, `votes_polled`, `nota`, `rejected`, `valid_votes`.
**agg_electors_booth**: `booth_uid`, `electors`, `female_share`, `age_bands`, `category_mix` (JSON dict -> share), `category_ci_low/high`, `n_parsed`, `parse_quality`.
**fact_sentiment_event** (ephemeral, TTL 30d): `event_id`, `ts`, `source`, `lang`, `target`, `polarity`, `stance`, `conf`, `geo_tier`, `geo_id`, `text_hash` (no raw text beyond TTL, no usernames).
**agg_sentiment**: `geo_tier`, `geo_id`, `window_start`, `target`, `mean_polarity`, `n`, `ci_low`, `ci_high`.
**feat_swing**: `booth_uid`, `cycle_pair`, `swing_pp[party]`, `turnout_delta`, residualized and shrunk variants.
**flag_anomaly**: `booth_uid`, `cycle_pair`, `score`, `rank_in_ac`, `top_features`, `n_votes_bin`.

## 4. ID scheme
`booth_uid = {election_id}-{ac:03d}-{ps:04d}{suffix}` for the per-election id; cross-election lineage kept via `booth_crosswalk` and a stable `lineage_id`.

## 5. Geospatial specifics
- Store 4326; project to **EPSG:32644** for Voronoi, buffering and distance work.
- Voronoi: generate cells from booth points per AC, clip to AC polygon (`shapely.ops.voronoi_diagram` + `gpd.clip`). Mark `geom_source='voronoi'` and show in the UI as approximate.
- Point-in-polygon: `gpd.sjoin(points, cells, predicate="within")`. Fallback: nearest booth (`sjoin_nearest`, max distance cap, e.g. 3 km).
- Use spatial index (R-tree, default in geopandas). Batch sentiment joins per micro-window.

## 6. Sentiment tiers
| Tier | Condition | Used for |
|------|-----------|----------|
| booth | geotag within booth cell and n >= n_min | rare; ground reports |
| ward/block | geotag or place-name resolves | main granular layer |
| AC | text mentions AC/place, or user-region | default |
| district/state | fallback | context |

## 7. Tech stack
pandas, numpy, pyarrow, geopandas, shapely, pyproj, rtree; pdfplumber + pytesseract/ocrmypdf for PDFs; regex, rapidfuzz (name matching); scikit-learn; transformers + torch (HF); streamlit, streamlit-folium, folium, plotly; pydantic for schemas; pytest; DVC/Prefect optional for orchestration.

## 8. Deployment
Dev: local. Prod: containerized (Docker), Streamlit behind reverse proxy with auth (OIDC/basic), Parquet on object storage or Postgres+PostGIS, scheduled micro-batch worker (cron/Prefect) for sentiment. Secrets via env/secret manager.

## 9. Performance notes
- Render booth layers as clustered markers/choropleth by tier, and simplify geometries (`simplify(tolerance)`) per zoom.
- Pre-aggregate in Parquet, and use `@st.cache_data` with explicit keys.
- Transformer inference batched (size 32-64), quantized/ONNX if CPU-only.
