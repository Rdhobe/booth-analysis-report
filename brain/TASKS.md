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
- [~] **T1.5** Party-group mapping per election. *AC: reviewed lookup file.* — AC-level fronts in `configs/ml_config.json` (2026-10-17; seat counts match published results; small allies TODO(verify), needs review).
- [ ] **T1.6** Extend to second election, then statewide. *AC: coverage report.* — Agra done 2026-10-03 (VS2017+LS2019+VS2022+LS2024, 14,777 booths, 36/36 totals reconcile; see `data/processed/agra_*`, CHANGELOG).

- [~] **T1.7** Constituency electors / turnout / Lok Sabha 2019 from the ECI booth sheets, with gates. *AC: booth sums reconcile to official totals within 0.5-4%; failures become missing.* — done 2026-10-17: read 2017 387 / 2019 395 / 2022 401 ACs, turnout passing the checks 362 / 393 / 390 (2017 filled to all 403 from the roll file). 28 files stay unread by design (Form 20, counting rounds, postal, one password-protected).
- [~] **T1.8** Forward backtest with Lok Sabha + candidate features. *AC: learned model beats the best rule on every front.* — run 2026-10-17: not met (best learned 8.1 vs rule 8.8 average miss, worse for the BJP-led front). The unknown statewide swing accounts for about 3.6 points of the error.

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
- [~] **T4.3** IsolationForest + robust-z ensemble + stability filter. *AC: seeded, deterministic.* — Agra partial: MAD robust-z only (no sklearn); deterministic ✓; IF pending. AC level done 2026-10-17 (`Scripts/ml/models.py`, seeded, repeatable).
- [ ] **T4.4** Explanations table. *AC: top-3 contributing features per flag.* — Agra done 2026-10-03 (top-2 + benign checklist; `agra_anomaly.csv`).
- [x] **T4.6** Seat watch score. *AC: beats margin-only by 5 pts of precision in the top 50, else ship the rule and say so.* — built 2026-10-19 (`models_extra.watch_*`): the learned model failed the gate, the fixed rule is used; bands separate 61% to 9% flip rate in 2022.
- [x] **T4.7** Expected turnout. *AC: beats "same as last time plus the statewide change" by 0.2 pts with districts held out.* — ridge, 1.36 vs 1.61 (2022) and 1.80 vs 2.31 (LS 2024).
- [x] **T4.8** Alliance transfer estimates with intervals. — 2019 and 2024, four estimates; wide intervals (17 to 62 seats).
- [~] **T4.9** What-if simulator. *AC: true 2022 regional swing must land inside the shown range.* — built; hindcast calls 76% of seats right and noise made counts worse, so no probabilities are shown; the six-region list is a DRAFT needing sign-off.
- [~] **T4.10** Booth segments (2024). — rules on 142 verified seats (56,701 booths); trends wait for the booth crosswalk (T2.4) and the other constituencies for Form 20 conversion.
- [~] **T4.5** Synthetic-anomaly validation. *AC: recall ≥0.8 at FPR ≤2% on injected shifts.* — AC level measured 2026-10-17: 11% / 21% / 39% found for 10 / 15 / 20 pt shifts at about 3-4% other flags (target not met).

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
- [~] **T6.8** Battlegrounds, What-if, Turnout and Alliances tabs, seat-page panels and booth view in the Next.js app. *AC: served from `/api/insights/*`; Compliance Mode honoured by the server.* — built 2026-10-19 (`web/components/insights_extra.jsx`, `server/insights_extra.py`); browser-tested (21 checks).
- [x] **T6.9** Party-selectable booth dashboard. *AC: any listed party can be the point of view on `/booths`, `/zone`, `/ac`; no party preselected; the BJP view agrees with the old workbook where the rules are the same.* — built 2026-10-20 (`Scripts/serve/booth_party.py`, `server/app.py`, `web/components/PartyPicker.jsx`); BJP share agrees in all compared cells; browser-tested (21 checks), 26 unit tests, live check 33.
- [~] **T2.7** Party labels in the booth sheets. *AC: no seat-election with more than 25% of votes under IND/blank.* — 73 / 24 / 22 / 9 seat-elections (2017/2019/2022/2024) are left out of the booth views today; fix the ingest (party column) rather than hide them.
- [~] **T6.7** Insights tab in the Next.js app (types, unusual results, expected range). *AC: served from `/api/insights/*`; Compliance Mode honoured by the server.* — built 2026-10-17 (`web/app/insights`, `server/insights.py`); needs a real `npm run build` check.

## Phase 7: Hardening & release
- [ ] **T7.1** Docker, CI/CD, monitoring (feed volume, model drift).
- [ ] **T7.2** Pen-test / dependency audit. 
- [ ] **T7.3** Ethics checklist sign-off (SECURITY.md §8).
- [ ] **T7.4** v1.0 release notes + user guide.

## Suggested first sprint (2 weeks)
T0.1, T0.2, T0.3, T1.1, T1.2, T1.3, T2.1 on **one district, one election**.
