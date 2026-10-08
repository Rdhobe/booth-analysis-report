# PRD: UPBI

## 1. Problem
Analysts see UP elections at constituency level, which hides local dynamics. Booth-level data exists but is scattered across PDFs, unjoinable across elections, and never combined with demographic and live-sentiment context.

## 2. Users
| Persona | Need |
|---------|------|
| Political analyst / researcher | Booth-level swing, turnout, volatility across cycles |
| Campaign data team (internal) | Where sentiment is diverging from baseline, in near-real time |
| Journalist / civil-society observer | Statistical outliers worth ground verification |

## 3. Goals and success metrics
| Goal | Metric / target |
|------|-----------------|
| Booth coverage | >=95% of booths in scoped ACs ingested with validated totals |
| Result integrity | Booth sums match official AC totals within +/-0.5% (or discrepancy flagged) |
| Crosswalk quality | >=90% of booths linked across two consecutive elections |
| Geo coverage | 100% booths have a point; >=80% have polygon or Voronoi cell |
| Sentiment latency | Ingest to map update < 5 min (batch micro-window) |
| Sentiment quality | >=0.75 macro-F1 on a hand-labelled UP Hindi/Hinglish set (n>=1500) |
| Anomaly review value | Of top-50 flagged booths per AC-cycle, >=60% have a documentable explanation or a worthwhile verification lead |
| Dashboard perf | Map renders 10k+ booths < 3 s (vector/clustered layers) |

## 4. Functional requirements
**FR1 Ingestion:** download, parse, validate Form 20 PDFs/CSVs; load Lok Dhaba AC-level data for cross-checks.
**FR2 Crosswalk:** link booths across elections using AC, part number, name, location, and spatial proximity.
**FR3 Geo:** booth point table, polygons/Voronoi, joins to AC/district/Census units.
**FR4 Demographic model:** per-booth aggregate composition estimates (gender, age bands, category shares) with uncertainty; no individual data retained.
**FR5 Sentiment:** ingest text, detect language, score stance and polarity in [-1, +1], geolocate or assign tier, aggregate by time window.
**FR6 Anomaly:** compute swing/turnout features, residualize, shrink, run IsolationForest plus robust-z ensemble, give per-feature explanations.
**FR7 Dashboard:** map, filters (election, party, AC, metric), booth drill-down, sentiment divergence layer, anomaly layer, export (CSV/GeoJSON) of aggregates.
**FR8 Compliance mode:** a switch that hides live/opinion layers during legal blackout periods.

## 5. Non-goals
- No individual-level voter profiling or targeting.
- No prediction of how any named individual votes.
- No claim of electoral fraud from statistical outputs.
- No scraping behind logins or against platform terms.

## 6. Release plan
- **MVP (v0.1):** one district, one past election pair, results + geo + swing + dashboard map.
- **v0.5:** statewide historical, anomaly engine, demographic aggregates.
- **v1.0:** live sentiment, compliance mode, auth, hardened deployment.

## 7. Risks
| Risk | Mitigation |
|------|-----------|
| Booth renumbering breaks swings | Crosswalk + confidence score; exclude low-confidence links from swing |
| OCR errors in rolls/Form 20 | Totals-based validation; manual review queue |
| Sparse geotags | Tiered aggregation (D4) |
| Sentiment != vote | Target-aware stance; show as a signal, not a forecast |
| Legal/ethical exposure | SECURITY.md controls, legal review before any public release |
