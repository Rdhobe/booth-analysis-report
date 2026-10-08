# Dashboard logic — what every number means

Source of truth: `GET /api/overview?election=<E>&vs=<V>` in
`server/app.py`. Elections: `VS2017, LS2019, VS2022, LS2024`.
This file is the contract the Next.js frontend reimplements.

## 0. Global rules

- **Party names are normalized** before any aggregation:
  strip non-alphanumerics, uppercase, then aliases
  (`BHARATIYA JANATA*→BJP`, `SAMAJWADI*→SP`,
  `BAHUJAN SAMAJ*→BSP`, `APNA DAL*→ADAL`,
  `SUHELDEV*/SBSP→SBSP`, `RASHTRIYA LOK DAL/RLD→RLD`).
  Display uses the most-voted original spelling (majors show the
  canonical code). Raw files contain variants (`B.J.P.`,
  `BHARATIYA JANATA PAR`, `,,`, candidate names in party fields).
- **NOTA** is counted in vote totals but can never "win" a seat.
- **MIN_VOTES = 2000**: ACs with fewer counted votes are kept in
  totals but excluded from winners and best/worst picks (they are
  single-file fragments or corrupted rows).
- **Workbook zeros**: `up_booth_report.xlsx` writes `0`, not NULL,
  for missing elections. Any vs-share is nulled unless real vs rows
  exist for that booth (`booth_election` check).
- **Value scales**: shares/margins/turnout are fractions 0–1
  (display ×100); religion `*_percent_17` are already 0–100;
  `age_*` are years; `e/m/f/o/t` are headcounts.

## 1. Seats / leads KPI

- VS years: per-AC plurality winner over booth sums
  (`vote ⋈ booth_election`, normalized parties). ACs with no
  usable votes are gaps, reported in `notes`, never seats.
- LS2024: same plurality over `seg2024` (official ECI segment
  totals, all 403 ACs). These are **assembly-segment leads**,
  labeled as such — a Lok Sabha "lead" is not a seat won.
- Gauge = BJP seats ÷ ACs counted.
- Coverage honesty: VS2017 403/403, LS2019 ~318, VS2022 ~205
  (booth conversion is thin there — counts carry a
  `seats/shares counted in N of 403` note).

## 2. Average vote share KPI

- `Σ BJP votes ÷ Σ all votes (incl. NOTA)` over the same source
  as seats (booth sums, or `seg2024`+NOTA for 2024).
- Delta = share(E) − share(Vs) in percentage points.
- Thin-coverage years skew (e.g. VS2017 35.7% vs ECI 39.7%)
  because the converted subset is not a random sample.

## 3. AC categorisation (177 / 49 / 98 / 79 pattern)

- AC zone = the booth zone rule applied to the AC's means:
  `avg = AVG(booth avg_diff)`, `latest = AVG(booth latest_diff)`;
  Safe if avg>+0.10 & latest>0; Difficult if avg<−0.10 &
  latest<0; Favorable if avg>0 & latest>0; else Battlefield;
  Data Not sufficient if the AC has no margins. Same ±0.10
  cutoffs as booth zones (`SAFE_UP, DIFF_DOWN` in
  `Scripts/build_state_report.py`). Stable across elections.
- Best / Least per zone = max / min BJP share among zone ACs
  passing MIN_VOTES, each with its Vs-election share
  (`—` when the AC has no Vs rows).

## 4. Booth categorisation

- Counts straight from `booth_row.zone` (workbook zones).
- Top booth per zone = highest BJP share (`a<E>` column) among
  booths **with real booth rows in E** (excludes workbook
  zero-constants), with Vs share or `—`.

## 5. Voter profile

- Statewide `Σmale / Σfemale` shares + `Σpolled/Σelectors`
  turnout for E; falls back to VS2022 with a `(2022)` tag when E
  has no sex splits (2024 segment totals carry none).
- Male share rises as coverage thins (55.0 → 56.7 → 57.2%),
  so thin-coverage years read male-heavy: a coverage artifact,
  not a finding. M/F come from ECI files; O (other) is ~0.

## 6. Religion-wise (Estimated)

- Electors-weighted statewide means of the 36 modeled 2017-roll
  columns; `others = max(0, 100 − Σ)`.
- Religion shares are **name-model inferences, not counts**
  (rolls record age/sex, never religion) with measured
  miscalibration (e.g. Christian ≈5.5%, Parsi ≈3.4% vs Census
  ≈0.2%/≈0% — see `brain/DATA_SOURCES.md`). Always tagged
  Estimated; never quote without the Methods caveat.

## 7. Zone → AC table; AC detail tabs

- Table rows = zone members × `ac_shares` (BJP% in E and Vs,
  change in pp); search + sort by change.
- AC Overview tab: static AC zone badge + `/api/ac/{ac}/sexratio`
  + `/api/ac/{ac}/religion` + `/api/ac/{ac}/ages` +
  `/api/ac/{ac}/averages` + `/api/ac/{ac}/votes` ×4 elections
  (source-labeled).
- Booths tab: paginated `/api/booths` (never full-table).
- Past Elections: everything from `/api/ac/{ac}/past` (no
  client-side math).
- Map tab: placeholder until the geo phase.

## 8. Trend (`/api/trend`)

- One row per election: BJP share + BJP seats (same rollup code
  as overview, shared cache), top-6 seat board, turnout
  (booth sums; LS2024 from segment electors/valid/NOTA).
- Home trend + turnout charts read this only — never N
  overview fetches or client-side sums.

## 9. Past sheet (`/api/ac/{ac}/past`)

- Per election: full normalized party list with shares,
  winner/runner-up, `margin_votes`, `margin_pp` (of counted
  votes), turnout block, booth count, source string.
- LS2024 turnout comes from `seg2024_ac`; earlier years from
  `ac_summary` (converted-booth sums, thin where noted).

## 10. Ages (`/api/ac/{ac}/ages`)

- Overall: electors-weighted mean/SD of `age_avg_17` /
  `age_stddev_17` over the AC's booths.
- Per religion: weighted by that religion's modeled electors
  (`rel% ÷ 100 × electors_17`), with the resulting base shown.
- Modeled estimates (name-model religion × roll ages) with the
  same calibration caveats as §6.

## 11. Averages (`/api/ac/{ac}/averages`)

- Per election: booth count, mean electors / male / female /
  polled per booth, plus the underlying totals.
- Means are over converted booths only — thin-coverage years
  describe the subset, not the AC.
