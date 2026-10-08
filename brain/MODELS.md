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
