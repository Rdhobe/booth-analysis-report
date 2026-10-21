# MODELS.md

## 1. Swing and turnout metrics
- `vote_share_p = votes_p / valid_votes`
- `swing_p = share_p(t) − share_p(t−1)` in pp, computed only for crosswalk links with confidence ≥ 0.8 (1:1) or using area/elector-weighted splits and merges.
- Party continuity: handle alliances/splits (e.g. map SP+allies, BJP+allies) via a `party_group` lookup per election. Document it.
- `turnout = votes_polled / electors`; also track NOTA share and rejected-vote share.

## 2. Demographic estimation (modeled, aggregate-only)
**Inputs:** parsed roll rows (name, relative name, age, gender), Census 2011 SC/ST shares for the booth's village/ward.
**Method (v1, transparent):**
1. Normalize names (Devanagari-to-Latin transliteration, remove honorifics, fuzzy-merge variants).
2. Extract surname token (fallback: relative's surname; fall back to unknown).
3. Look up a **curated surname to category-probability lexicon** (versioned CSV: `surname, P(category)`; sources: published research, domain experts; each row has a provenance field).
4. Sum probabilities over the booth (expected counts, not hard labels), giving `category_mix`.
5. **Calibrate** against Census SC/ST shares at village/ward level (iterative proportional fitting or a Bayesian prior), so SC estimate aligns with known totals.
6. Uncertainty: bootstrap over name-level probabilities, then report 80% intervals.
7. Output only if `electors >= 200` and `parse_quality >= 0.9`, else `NULL`.
**Caveats to surface in the UI:** surnames are ambiguous (shared across categories), OBC/General sub-splits are weak, women who changed surnames, migrants. Label as **"modeled estimate"**.
**Use `naampy` only** for gender-from-name QA of parsing, not for caste.

## 3. Sentiment engine
- **Models (starting points):** `cardiffnlp/twitter-xlm-roberta-base-sentiment` (multilingual baseline), Hindi/Hinglish-tuned encoders (L3Cube HingBERT/HindBERT, IndicBERT) fine-tuned on a hand-labelled UP set. Verify model cards and licenses before use.
- **Pipeline:** language ID (fastText/lingua) → normalization (emoji map, Roman-Hindi transliteration) → target detection (party/candidate/issue lexicon + NER) → stance/polarity classifier → score = `P(pos) − P(neg)` ∈ [−1, 1] → confidence gating (drop < 0.55).
- **Spam/bot handling:** dedupe by `text_hash`, near-duplicate clustering (MinHash), account-age and burst heuristics (where API data allows), and cap per-source weight.
- **Aggregation:** exponentially weighted mean per `(tier, geo_id, target, window)`; Wilson/Bayesian CI; require `n >= n_min` (default 30) to display.
- **Divergence vs baseline:** `div = z( sentiment_now − expected )`, where *expected* is a model of historical vote share or a rolling prior-window mean, scaled to [−1, 1] for color. Document the choice of baseline in the UI tooltip.
- **Evaluation:** stratified labelled set (n≥1500: Hindi, Hinglish, Urdu-script, English), macro-F1, calibration (ECE), drift monitoring.

## 4. Anomaly engine
**Goal:** find booths whose behavioral change deviates from their local trend.
**Features per booth, per cycle pair:** `swing_pp` for top-k party groups, `turnout_delta`, `margin_delta`, `NOTA_delta`, `rejected_share_delta`, `turnout_vs_AC` (booth − AC turnout).
**Steps:**
1. **Residualize:** subtract the AC (or AC×urban/rural) median from each feature. This removes regional waves.
2. **Small-N shrinkage:** empirical-Bayes shrink swing toward the AC mean, with weight ∝ `valid_votes`. Otherwise small booths dominate the flags.
3. **Scale:** `RobustScaler`.
4. **Model:** `IsolationForest(n_estimators=300, contamination=0.01–0.02, random_state=42)`, fit **per region cluster or per AC group** (not one global fit), with a **robust-z (MAD)** ensemble. A booth is flagged if both agree or if either is extreme (|z|>4).
5. **Explain:** per-feature robust-z contribution, so the table shows *why* flagged ("turnout +28pp vs AC, BJP −22pp").
6. **Stability:** rerun with bootstrap seeds. Flag only booths flagged in ≥70% of runs.
7. **Language:** output name is `statistical_outlier`. Include "benign explanations" checklist: booth merge/split, new colony, migration, caste-cluster voting, candidate switch, boundary shift.
**Validation:** inject synthetic anomalies into history, then measure recall and false-positive rate, and review sample flags manually.

## 5. Phase 1 implementation at AC level (2026-10-17)
Implemented in `Scripts/ml/` (config `configs/ml_config.json`); differs from the plan above as follows:
- **Level:** constituency (403 ACs), not booth. Booth versions wait for a crosswalk that passes a check.
- **Fronts:** vote shares are per front (BJP-led, SP/INC, BSP, others), with allied codes summed per election.
- **Typology:** PCA(3) + k-means (not described above); k by silhouette + bootstrap stability.
- **Surprise:** peers = 25 ACs most similar on 2012+2017; modified z + Isolation Forest agreement (or z >= 5). Peer expectation replaces the AC-median residualisation; small-N shrinkage is not needed at AC level.
- **Baseline:** "same as last election" with the 80% error band of 2017->2022, stress band pooled with 2012->2017. A learned forecaster must beat it on every front before it is shown (it did not).
- Outputs and checks: `output/ml/model_card.json`.

## 6. Additional seat-level models (2026-10-19)
Implemented in `Scripts/ml/models_extra.py` (run `Scripts/ml/build_extra.py`; settings in the `extra` section of `configs/ml_config.json`). Each has a backtest and, where a learned model competes with a rule, a promotion gate.
- **Seat watch score** (which seats may change hands). Fixed rule: 75% closeness of the 2022 margin + 25% how far the 2024 Lok Sabha vote (parliamentary seat) moved against the side that led (percentile ranks, nothing fitted). A learned logistic regression (8 features) was trained on one assembly change and tested on the other, in both directions, and did **not** beat margin-only by the 5-point gate, so it is reported but not used. Evidence: 2017->2022 AUC 0.80, observed flip rate 61% / 52% / 30% / 9% in the Highest / High / Moderate / Lower bands; 2012->2017 (wave) 100% / 87% / 85% / 69%. A score is a ranking, not a probability: the flip rate moved from 79% to 26% between the two changes.
- **Expected turnout.** Ridge regression on earlier turnouts, size, elector growth, women's share of voters and reserved status; scored out of fold with whole districts held out. Average miss 1.36 pts for 2022 (rule 1.61) and 1.80 pts for Lok Sabha 2024 (rule 2.31); gradient boosting was worse. Gap = actual - expected; "well below" = more than 1.5 SD below (24 seats for 2024). Women's share is the share of voters who were women (electors by sex are not in the files), not a turnout rate.
- **Alliance transfer.** Bounded (0..1) least squares of the alliance candidate's share on each earlier bloc's share across 80 parliamentary seats, bootstrap 80% intervals, leave-one-out error against two naive rules. 2019 SP-BSP-RLD: BSP->SP 66% [45, 84], SP->BSP 65% [48, 89]; 2024 SP-INC: INC->SP 76% [51, 100], SP->INC 81% [64, 92]. Used as default transfer rates in alliance scenarios.
- **What-if simulator.** Base = 2022 shares of five fronts (NDA, SP-led, INC, BSP, others), which reproduce the actual 2022 winners in 403 of 403 seats. The user sets a swing (percentage points) for NDA, SP-led and BSP by region (six regions in `configs/regions_up.json`, a DRAFT list) and an optional SP+INC or SP+BSP alliance with a transfer rate; INC and others absorb the opposite change; the leader is the front with the highest share. **No random noise:** simulations that add seat-level noise (additive, proportional, or margin-error banks) gave worse seat counts in hindcasts than counting the predicted leaders. Hindcast with the TRUE regional swing: 76.4% of 2022 seats called right (repeating the previous winner: 73.4%), 66.5% of 2017 seats (previous winner: 20.3%). Seats led by under 6 points were right 47% to 52% of the time, so they are shown as toss-ups with historical hit rates, and seat counts come with a range (every toss-up against, then for, a front).
- **Booth segments (2024).** Rules, not a learned model: booth leader front and margin from the Form 20 workbooks whose candidate columns all equal the official totals (142 seats, 56,701 booths; 296, 301, 314, 346, 375 excluded). Stronghold >= 25 pts, Lean 10 to 25, Competitive < 10. No turnout per booth (no electors in Form 20) and no trend (booth crosswalk still fails its check).
- **Compliance.** Watch scores, the simulator and its setup are forward-looking and are hidden by `COMPLIANCE_MODE`; turnout, alliance estimates and booth results look backwards and stay.
- **Not built:** current-mood swing model (needs polls/news), news classifier (needs ~1,500 labelled texts), demographic estimates, unusual-result v2.
