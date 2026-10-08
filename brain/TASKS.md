# TASKS.md

Legend: `[ ]` todo, `[~]` in progress, `[x]` done. Each task has acceptance criteria (AC).

## Phase 0: Foundations
- [ ] **T0.1** Repo scaffold, `pyproject.toml`, ruff/black/pytest, pre-commit (detect-secrets). *AC: CI green on empty tests.*
- [ ] **T0.2** Config system + `SOURCES_LOG.csv`. *AC: all paths/thresholds via YAML.*
- [ ] **T0.3** Resolve open questions Q1-Q5 in BRAIN.md. *AC: decisions logged.*
- [ ] **T0.4** Legal/ethics review kickoff. *AC: written go/no-go scope for audience & data.*

## Phase 1: Results ingestion (MVP core)
- [x] **T1.1** Download Form 20 for pilot district (1 election). *AC: raw files archived, hashes logged.* — 2024 batch (392 PDFs) present under `2024/`; Agra pilot done 2026-10-02.
- [~] **T1.2** PDF parser (pdfplumber) + OCR fallback. *AC: ≥98% of pages parsed or queued for review.* — `Scripts/convert_form20.py` (single) + `Scripts/bulk_convert_form20.py` (batch: dynamic 7–26 candidates; Parliament 2-col, Assembly 3-col, single-serial 1-col layouts; mirrored-text restore; footer-decontamination incl. `<n> Page <p>`, `<n> Pag`, `serial e p`+fused-pair variants since 2026-10-05). Two queues remain: Hindi legacy-font PDFs → `LEGACY_SKIP` (need DevLys decoder); scanned-image PDFs (~133, e.g. Ayodhya) → `SCANNED` (need OCR path). REVIEW triage: `Scripts/review47.py` + `data/2024/review47.md` (27/47 with verified retry path; 20 manual — see CHANGELOG 2026-10-05). See CHANGELOG 2026-10-02.
- [~] **T1.3** Schema + validators (`pandera`). *AC: AC totals reconcile within 0.5%.* — row-sum + EVM-total + post-save checks implemented in bulk script (no pandera yet); `bulk_convert_report.csv` per run.
- [ ] **T1.4** Load Lok Dhaba AC-level data + candidate/party metadata. *AC: join keys documented.*
- [ ] **T1.5** Party-group mapping per election. *AC: reviewed lookup file.*
- [ ] **T1.6** Extend to second election, then statewide. *AC: coverage report.* — Agra done 2026-10-03 (VS2017+LS2019+VS2022+LS2024, 14,777 booths, 36/36 totals reconcile; see `data/processed/agra_*`, CHANGELOG).

## Phase 2: Geospatial
- [ ] **T2.1** Booth list + geocoding with confidence. *AC: ≥90% points inside correct AC.*
- [ ] **T2.2** AC boundary vintage matching. *AC: correct polygons per election year.*
- [ ] **T2.3** Voronoi cells clipped to AC (EPSG:32644). *AC: cells tile AC, no overlaps, area check.*
- [ ] **T2.4** Booth crosswalk across elections (name fuzzy + spatial + part no.). *AC: ≥90% 1:1 links on pilot; confidence score stored.* — Agra done 2026-10-03 (90.3/96.9/100% per pair; `agra_crosswalk.csv`).
- [ ] **T2.5** Census village/ward join for SC/ST priors. *AC: join-rate report.*

## Phase 3: Demographics (aggregate-only)
- [ ] **T3.1** Roll PDF download (ToS-compliant, rate-limited) for pilot AC. 
- [ ] **T3.2** OCR + field extraction (name, relative, age, gender). *AC: field accuracy ≥95% on 300-row hand check.*
- [ ] **T3.3** Surname lexicon v1 with provenance. *AC: reviewed by domain expert.*
- [ ] **T3.4** Estimator + Census calibration + bootstrap CI. *AC: calibrated SC share within ±3pp of Census at village level on holdout.*
- [ ] **T3.5** Purge pipeline: confirm no name-level data persisted. *AC: automated test + audit.*

## Phase 4: Anomaly engine
- [ ] **T4.1** Feature builder (swing, turnout Δ, NOTA Δ, margin Δ). *AC: golden-test math.* — Agra done 2026-10-03 (hand-verified booth math; `agra_swing.csv`).
- [ ] **T4.2** Residualization + EB shrinkage. *AC: small-booth flag rate not > large-booth flag rate by >2×.* — Agra done 2026-10-03 (w=n/(n+200) on min side; small under-flagged, gate passes).
- [ ] **T4.3** IsolationForest + robust-z ensemble + stability filter. *AC: seeded, deterministic.* — Agra partial: MAD robust-z only (no sklearn); deterministic ✓; IF pending.
- [ ] **T4.4** Explanations table. *AC: top-3 contributing features per flag.* — Agra done 2026-10-03 (top-2 + benign checklist; `agra_anomaly.csv`).
- [ ] **T4.5** Synthetic-anomaly validation. *AC: recall ≥0.8 at FPR ≤2% on injected shifts.*

## Phase 5: Sentiment
- [ ] **T5.1** Choose sources + compliant collectors. *AC: ToS check per source.*
- [ ] **T5.2** Labelled dataset (≥1500, Hindi/Hinglish/English/Urdu-script). *AC: inter-annotator κ ≥ 0.7.*
- [ ] **T5.3** Fine-tune/evaluate models. *AC: macro-F1 ≥ 0.75, ECE reported.*
- [ ] **T5.4** Target/stance detection. 
- [ ] **T5.5** Geo assignment (sjoin + tiering + fallbacks). *AC: tier distribution report.*
- [ ] **T5.6** Windowed aggregation + baseline divergence. *AC: n_min gating works.*
- [ ] **T5.7** Bot/spam controls. *AC: duplicate rate and burst alerts.*

## Phase 6: Dashboard
- [ ] **T6.1** Streamlit skeleton + auth. 
- [ ] **T6.2** Map with AC → booth zoom, swing & turnout layers. *AC: 10k booths < 3 s.*
- [ ] **T6.3** Sentiment divergence layer + grey-out for low n.
- [ ] **T6.4** Anomaly tab + booth drill-down.
- [ ] **T6.5** Methods & caveats tab; Compliance Mode.
- [ ] **T6.6** Export (aggregates only) with audit log.

## Phase 7: Hardening & release
- [ ] **T7.1** Docker, CI/CD, monitoring (feed volume, model drift).
- [ ] **T7.2** Pen-test / dependency audit. 
- [ ] **T7.3** Ethics checklist sign-off (SECURITY.md §8).
- [ ] **T7.4** v1.0 release notes + user guide.

## Suggested first sprint (2 weeks)
T0.1, T0.2, T0.3, T1.1, T1.2, T1.3, T2.1 on **one district, one election**.
