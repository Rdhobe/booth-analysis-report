# CHANGELOG

All notable changes to this project. Newest first.
Rule (see `brain/RULES.md`): every code change updates this file **and**
the relevant `brain/` doc in the same sitting.

## 2026-10-20 - Booth dashboard: party picker (the booth pages are no longer the BJP's view only)

- **What changed for the user.** `/booths`, `/zone/[zone]` and `/ac/[ac]` are seen from the party chosen with the buttons in the header (BJP, BSP, INC, SP, listed alphabetically; **none is preselected**, the page asks first; `?party=SP` is a shareable link). Shares, the strongest opponent, differences, zones, seat and booth counts, the trajectory chart and the past-results columns are all that party's. The same booths can be looked at from the other side with one click.
- **Server.** `party=` (default BJP for API callers) on `/api/overview|trend|booths|booth|zones|ac/{ac}/past`; unknown party is a 400 that lists the choices. New table `booth_party` built by `Scripts/serve/booth_party.py` from the store's own booth votes (`build_servedb.py` calls it; `Scripts/serve/add_booth_party.py` adds it to a finished store in about a minute). A store without the table still serves the BJP from the workbook columns and refuses other parties with the fix named. The old `party=` filter on `/api/booths` (opponent code) is now `opponent=`. `/api/trend` returns `share`/`seats`, `/api/ac/{ac}/past` returns `party_votes`/`party_share` (were `bjp_*`).
- **Rule changes against the old workbook (documented in `server/DASHBOARD_LOGIC.md` section 12).** A party counts only in seats and elections where it stood, meaning at least 1% of the seat's votes (no more 0% for allies' seats, and a few stray votes under a label do not count); one election is not an average; the opponent is never IND, blank or unmapped, and where the usual opponent did not stand in an election (an ally took the seat) the strongest other party in that election is used, shown by name in the booth table; a seat in an election is left out when more than a quarter of its votes sit under IND, blank or unmapped labels (73 seats in 2017, 24 in 2019, 22 in 2022, 9 in 2024: a party column that failed to read); a booth in an election is unusable when it has under 20 voters, fewer voters than valid votes, or a share above 100% (this removed a 3,940% booth). Against the workbook's BJP columns: the BJP share agrees in all 332,036 booth-election cells where both exist; the reference opponent differs in 73 of 403 seats (38 are spelling variants of the same party such as "S.P", "B.S.P.", "SUHELDEV..."; 26 are seats where the old opponent was "IND"; 2 where it was the BJP itself spelled "B.J.P."; the rest stray characters); 73% of booth zones are unchanged (124,114 of 169,460) and most of the rest moved because the party or its opponent did not stand in an election, the opponent changed, or a turnout figure could not be right.
- **Seat counts.** The same label guard now applies to the seat table: the 2017 table no longer shows independents winning 30 seats; the unreadable seats are left out and the page says how many. The BJP's 2017 share is 38.9% (official 39.7%); its seat count here is 248 of 330 counted seats (published: 312 of 403), so these seat counts are lower than the official results: use Insights for official seats.
- **Making the store buildable again.** The scripts in `Scripts/report` and `Scripts/serve` had been moved into subfolders without updating their repo-root path (they looked in `Scripts/`); fixed. `build_state_report.py` gained `--ac24-dir` and `--ac24-verified-json` (2024 booth results only for the 142 seats whose Form 20 workbook equals the official totals; read-only on `data/2024`). Full rebuild on this machine: report 17 minutes (94 MB workbook, now git-ignored), store 7 minutes (1.1 GB): 169,460 booths, 5.15 million booth-level vote rows. Usage in `server/README.md`.
- **Also fixed.** `/api/booths` bound the search text and the constituency number in the wrong order when both were given.
- **Tests.** `server/test_booth_party.py` (26 tests, synthetic two-to-four-seat store); live check on the real store 33 of 33; browser test of the picker 21 of 21; Insights browser test 21 of 21; site check 38 of 38; all unit tests 110 pass.
- **Setup guide and a safeguard found while testing it.** `SETUP_GUIDE.md` (repository root; also Word and PDF) explains how to run the whole platform. Its commands were run on a clean copy of the repository (committed files plus these changes) in a fresh Python environment: the full booth database built in 12.5 minutes, the model commands reproduced the shipped Insights results, 111 tests passed, browser smoke test 11 of 11. The test showed that the 2024 booth results depend on which Form 20 workbooks a copy holds: only 23 of the 142 verified workbooks were still identical to the committed versions. `Scripts/ml/models_extra.py` now records a SHA-256 fingerprint of each verified workbook (`booth_segments.json` meta `source_sha256`) and `build_state_report.select_verified_2024` skips any workbook that no longer matches. Four tests that assumed at least 100 booth seats or particular excluded seats no longer do.
- **Follow-up (same day).** The 119 verified Form 20 workbooks that were missing or older in the repository were committed (3af126a, 3.8 MB; only those). A copy made from GitHub now keeps all 142 verified seats (`142 verified workbooks kept, 0 skipped`), so `SETUP_GUIDE.md` no longer needs the model commands before the booth build unless workbooks are edited. The branch was pushed to GitHub.
- **Open.** Booth names in some seats are stored in an old Hindi font encoding and read as gibberish (e.g. seat 88), so English search does not find them there; per-booth trends depend on booth serial numbers matching across elections (fails in Agra, T2.4); 2022 booth data covers 218 of 403 seats (Hindi `.xlsx` duplicates not read); party labels of the remaining seats still have no check beyond the 25% rule.

## 2026-10-19 - Additional models: watch score, expected turnout, alliance transfer, what-if simulator, booth segments

- **New code.** `Scripts/ml/models_extra.py`, `Scripts/ml/build_extra.py`, `Scripts/ml/test_extra.py` (14 tests); settings in the new `extra` section of `configs/ml_config.json`; draft region list `configs/regions_up.json`.
  Outputs in `output/ml/` (`extra_insights.json`, `simulator_inputs.json`, `booth_segments.json`, `extra_model_card.json`), exported to `server/insights_data/` with `--export-server`.
- **API.** `server/insights_extra.py` (pure Python, mounted on the `/api/insights` router): `/watchlist`, `/turnout`, `/alliances`, `/simulator/setup`, `POST /simulate`, `/booths`, `/booths/{ac}`, `/extra/meta`;
  `/ac/{ac}` gains an `extra` block and `/card` gains `extra_models`. Compliance Mode hides the watch score, the watch list and the simulator. 17 API tests in `server/test_insights_extra.py`, including a check that the server simulator equals the numpy reference.
  The Next.js proxy accepts POST for `insights/simulate` only. The Dockerfile copies the new file.
- **Website.** New tabs Battlegrounds, What-if, Turnout, Alliances (`web/components/insights_extra.jsx`); the seat page gains Watch score, Turnout against expected and 2024 Booths (with a CSV download); the Method tab lists the new checks. Neutral palette kept (INC gets its own purple).
- **What the backtests said (reported in the UI, not hidden):** the learned battleground model did **not** beat ranking by margin (the fixed rule is used); expected turnout beats its baseline (1.36 vs 1.61 and 1.80 vs 2.31 pts);
  alliance transfer 65% to 81% with wide intervals; the simulator, given the true regional swing, calls 76% of 2022 seats right (repeating the previous winner: 73%), and adding random noise made seat counts worse, so it shows the most likely leader, toss-up seats and counts with a range instead of probabilities.
- **Tests:** 84 pass in total. Browser test of the new screens: 21 of 21.
- **Open:** the six-region list needs sign-off; booth segments cover 142 of 403 seats; no current-mood (poll or news) model.

## 2026-10-18 - Handoff report and local setup package

- **New (untracked) in `output/handoff/`:** `UPBI_Phase1_Models_and_Setup_Guide.docx` and `.pdf` (28 pages: the three models with inputs, algorithms,
  outputs, quality and annotated screenshots; how the output is generated; data and tools; a setup guide; pending work) and `UPBI_local_package.zip`
  (website, API, precomputed model results, model code, the two input CSVs, `README_SETUP.md`, `run_api`/`run_web` scripts for Windows and bash; no logos,
  no secrets, no node_modules).
- **Verified in a clean copy** (extracted into an empty folder, new Python 3.13 environment, pinned packages, `npm ci`, build, both scripts started on spare
  ports): pages show the expected content, 24 tests pass, a rebuild reproduces the model numbers. This found three problems, now fixed: the server crashed without
  `server/assets/` (mount is now optional), `httpx` was missing from the test instructions (`requirements_models.txt` in the package), and the seat page crashed
  when the planted-shift test was absent (`--quick` build).
- **Gap found:** the source and licence of `data/Uttar_Pradesh.csv` are not recorded anywhere in the repository (the columns do not match the Lok Dhaba format); the
  report lists it as pending.
- Not tested: macOS, Linux, Python 3.10 to 3.12, Docker.

## 2026-10-18 - Neutral UI: no party or organisation branding, all-parties landing page

- **Removed** from the Next.js app: the BJP logo, the "Namaskar ... Ji" greeting, the two leader portraits in the header and on the home page,
  the slogan banner, and the party icons next to party names in bar lists (`PartyIcon`, `partyIcon`, `API_IMG`). The header now shows only the product's
  plain-text name and navigation.
- **Theme** changed from saffron-and-cream to neutral greys (`web/app/globals.css`; variables renamed `--saf` to `--accent`). The old religion colours
  (Hindu saffron, Muslim green) are gone: religion, gender and turnout bars use one neutral colour so colour never encodes a community or party.
- **Routes.** `/` now redirects to `/insights` (all parties side by side). The old single-party booth dashboard moved to `/booths`; it and `/ac/[ac]` and
  `/zone/[zone]` carry a "Single-party view" banner because their shares, zones and "Party B" comparison are the BJP's (`server/DASHBOARD_LOGIC.md`).
  Navigation: "Insights (all parties)" and "Booth dashboard".
- **Insights Overview.** The tile "BJP-led front seats" now reads "Seats won by front" and lists every front equally (web page and `Scripts/ml/templates/insights_demo.html`;
  `output/ml/insights_demo.html` regenerated). The Districts table now shows BJP-led, SP/INC and BSP shares for both 2022 and Lok Sabha 2024 (it showed BSP for neither).
- **Robustness.** The seat page no longer crashes when the planted-shift test is missing from the results file (what `build_insights.py --quick` produces); it shows a short note instead (web page and demo template).
- **Server.** `server/app.py` now mounts `/assets` only if `server/assets/` exists, so a copy of the server without the old logo and portrait files starts normally.
- **Not changed:** `server/assets/` still holds the old logo and portrait files; nothing in the UI loads them. The booth dashboard's analysis is still BJP-centred; making it
  party-selectable needs server changes (zones are computed for one party).

## 2026-10-17 - Data gaps cleaned: more booth sheets read, turnout and coverage shown

- **What was wrong (the repo notes had two causes wrong).**
  1. `find_vote_header` in the shared `Scripts/report/agra_pipeline.py` matched only the literal "Votes Secured". The ECI
     sheets also spell it "Voters Secured", "Voter Secured", "Votes  Secured" (two spaces), "Votes Se cured" and
     "Votes Se-cured". Fixed with `VOTES_SECURED_RE`. **This is a change to shared code:** a rebuild with
     `build_state_report.py` / `build_store.py` will now read those files too. Regression check: 852 of the 854
     constituencies read before are identical; the other 2 (2017 AC 277 and 315) now capture all candidate columns (AC 277
     valid votes 83,068 -> 230,763 against 232,990 polled).
  2. The 176 "Hindi" 2022 `.xlsx` files are **not Hindi**: they are the same English ECI layout, saved as `.xlsx`, which the
     parser (xlrd) cannot open. `Scripts/ml/ac_booth_totals.py` now opens them through an openpyxl adapter.
  3. About 90 further sheets are the same table with shifted columns (a blank leading column, electors split over four
     columns, the party written in the header row, the polling-station number inside the name, "voter turn out" / "voters yurn
     out" / "voter cast men/women" labels, repeated booth numbers such as 4 and 4A). New fallback reader
     `Scripts/ml/booth_sheets_generic.py` finds columns by label. It is used when the standard parser finds no table, and when
     the standard result fails basic checks and the label-based one passes for more constituencies.
  4. Form 20 sheets state the constituency's total electors in the preamble; `form20_preamble_electors` reads it (5 ACs in 2022).
- **Result (of 403 constituencies, first run -> now).** Read: 2017 328 -> 387, 2019 321 -> 395, 2022 205 -> 401. Turnout that
  passes its checks: 300 -> 362, 298 -> 393, 175 -> 390. 2017 turnout exists for all 403 (booth sheet where it passes, otherwise
  official votes over the 2017 roll file). Lok Sabha 2019 party shares are used only where the parliamentary seat matches the
  official EVM votes: 188 -> 318 constituencies. Statewide turnout from the cleaned data is 61.0% / 59.1% / 60.8% / 56.8%
  (2017 / 2019 / 2022 / 2024), in line with the published figures.
- **Checks.** Booth vote totals vs official: 2017 369 of 375 within 4% (median 99.1%), 2022 387 of 394 (median 98.9%). The upper
  bound of the reconcile gate moved from 1.005 to 1.02: booth sheets also count NOTA and tendered votes, official totals include
  postal ballots, so a few percent either way is normal. LS 2019 party names are now resolved from the official candidate list of
  the seat first (82% of votes), then from the sheet's party text (5.7% disagree, 0.9% unreadable).
- **Still unread (reason checked from the file, not assumed).** 2017: 7 Form 20 sheets (162-167, 317), 4 counting-round sheets
  (31, 32, 33, 111), 1 password-protected (192), 1 postal-vote sheet (259), 1 legacy-Hindi layout (108). 2019: 5 Form 20 sheets
  (34-38). 2022: 9 Form 20 sheets (87-94 Agra, 167). They hold no per-booth electors.
- **Effect on the backtest.** The forward test is unchanged (it does not use these features). In the district-grouped check inside
  2022, the constituency-level extras now lower the average miss by 0.14 (ridge, 4.20 -> 4.06) and 0.25 points (gradient
  boosting, 4.34 -> 4.09); this is not a forward test.
- **UI.** The insights outputs carry turnout and electors per constituency (`turnout_block`), statewide turnout per election
  (`overview.turnout`) and a `data_coverage` section in the model card. The demo page and the Next.js page show a
  "Turnout by election" card, turnout chips on each constituency, and "Data cleaning" cards in Method and checks.
- **Tests.** 53 in total (`test_booth_sheets_generic.py` 15, `test_features_ext.py` 17, `test_ml.py` 11, `server/test_insights.py` 10).

## 2026-10-17 - Prediction groundwork: booth sheets to AC level, extra features, extended backtest

- **`Scripts/ml/ac_booth_totals.py` (new):** sums the ECI booth `.xls` sheets (2017, 2019, 2022: 1,026 files, about
  1 minute with 4 workers) to constituency level with the repo's own `ingest_eci`. Writes
  `data/processed/ac_booth_{sums,party_votes,coverage}.csv`. Needs `xlrd==2.0.2` (pinned in `requirements.txt`,
  installed here). Repairs AC numbers the sheet parser gets wrong: in files such as `2017/170.xls` and `312.xls`
  every booth serial was read as an AC number (95 phantom ACs before the fix). Coverage: 2017 = 328 ACs,
  2019 = 321, 2022 = 205 (the 176 Hindi 2022 `.xlsx` are still not parsed).
- **`Scripts/ml/features_ext.py` (new):** gated constituency features, written to
  `data/processed/ac_features_ext.csv` (403 ACs x 67 columns) and `output/ml/features_ext_report.json`.
  Booth votes reconcile to the official AC totals at a median 99% (the gap is postal ballots); ACs outside
  0.96-1.005, with turnout outside 0.30-0.95, or with electors missing on over 10% of booths are set to missing,
  never guessed. Trusted AC-level turnout: 2017 = 300, 2019 = 298, 2022 = 175; 2017 is filled for all 403 from
  `uprolls2017.csv` and 2024 comes from the segment file. 2019 front shares from booth sheets: 252 ACs, of which
  188 sit in parliamentary seats that match official `parliament.csv` EVM votes (46 of 49 complete seats match
  on total votes, 37 on BJP votes; the 12 failing seats are set to missing). Party names on the sheets are messy
  (`B.J.P.`, `S.P.`, `,,`, legacy-font text) so `canon_party` maps only what it can read and drops the rest.
  New: official Lok Sabha shares per parliamentary seat for 2009, 2014, 2019, 2024 copied to each AC (all 403
  covered), and incumbency features from candidate names (59% of 2012 winners stood again in 2017, 36 of the 2022
  recontesting incumbents changed party).
- **`Scripts/ml/backtest_ext.py` (new):** like-for-like forward test, fixed in advance and not tuned on the test:
  train on assembly 2012 + Lok Sabha 2009/2014 -> assembly 2017, test on assembly 2017 + Lok Sabha 2014/2019 ->
  assembly 2022 (399 ACs). Result (average miss per AC, points): "same as last assembly election" 8.8 is still the
  best simple rule; Lok Sabha swing added to it is much worse (14.7); the best learned model (gradient boosting, history +
  Lok Sabha) reaches 8.1 but is better only for BSP (6.2 vs 9.8) and worse for the BJP-led front (6.3 vs 4.9), so it is
  not promoted. **With the true statewide swing the error would be 5.2**, so about 3.6 of the 8.8 points is the unknown
  statewide swing, which needs polls or news, not a better constituency model. District-grouped CV inside 2022 gives
  about 4.2 and shows turnout/electors/2019 booth fronts add at most 0.14 points (this check is not a forward test).
  Report: `output/ml/backtest_ext_report.{json,md}`.
- **Tests:** `Scripts/ml/test_features_ext.py` (13: party-name mapping, name matching, AC-number repair, seat-level
  shares, no feature depends on the target election, baselines in range).
- **Not done:** parse the 176 Hindi 2022 `.xlsx` sheets (turnout for the rest of 2022); 2017 files with a non-triplet layout
  (73 files unread); recover party names behind `,,` and single letters on some 2019 sheets; the swing model itself
  (needs a current-mood signal: polls or news).

## 2026-10-17 - Insights wired into the server and the Next.js app

- **Server:** new `server/insights.py` (FastAPI router) mounted in `server/app.py`:
  `GET /api/insights/meta|overview|types|acs|ac/{ac}|surprises|card`. It serves static JSON written
  by `Scripts/ml/build_insights.py` (`server/insights_data/`, or `INSIGHTS_DIR`, or `output/ml/`), so it
  needs no database. Same `X-API-Key` middleware as the rest of `/api/*`. `COMPLIANCE_MODE=on` removes
  the forward-looking `expected` range from every AC response on the server, so the switch holds even if
  a client ignores it. `python Scripts/ml/build_insights.py --export-server` refreshes
  `server/insights_data/`; the Dockerfile copies `insights.py` and that folder.
- **Web:** new `/insights` page (Overview, Constituency, Types, Unusual results, Method and checks),
  `web/components/insights.jsx` (hand-rolled SVG charts, validated colour-blind-safe palette),
  `.ins-*` styles in `globals.css`, and an Insights link in `Header.jsx` (`hideSelectors` prop hides the
  election selectors on pages where they do not apply). The existing `/api/*` proxy route already attaches
  the API key, so no proxy change was needed.
- **Tests:** `server/test_insights.py` (10 tests: shapes, 404, filters, API key, Compliance Mode, 503 when
  data is missing): `python -m pytest server/test_insights.py -q`. The React page was compiled with Babel and
  run in headless Chrome against the live API: all five tabs render with no console errors, and tab switching,
  the picker, member lists and district sort/filter work.
- **Not verified:** `npm install` / `next build` were not run (Node is not installed on this machine). Run
  `cd web && npm install && npm run dev` and open `/insights`.
- **Known gap:** `server/entrypoint.sh` still refuses to start without the main store (`STORE_URL` / `DB_PATH`),
  even though the insights endpoints do not use it.

## 2026-10-17 - Phase 1 AC-level models + Insights demo (new `Scripts/ml/`)

- New `Scripts/ml/`: `features.py` (AC x election table), `models.py` (typology, surprise,
  baseline range, learned-vs-baseline gate), `build_insights.py` (writes `output/ml/`),
  `build_demo_page.py` + `templates/insights_demo.html` (single-file UI, data inlined),
  `test_ml.py` (11 tests, pass). Config in `configs/ml_config.json` (seed, thresholds, party
  fronts). Dependencies in `requirements_ml.txt`. Run: `python Scripts/ml/build_insights.py`
  then `python Scripts/ml/build_demo_page.py`.
- Scope is constituency level only (403 ACs): VS 2012/2017/2022 from `data/Uttar_Pradesh.csv`
  and LS 2024 by assembly segment from the ECI segment file. No booth data, news or demographics.
- **Party fronts** (`configs/ml_config.json`): allied party codes are summed per election, so an
  Apna Dal (S) / Nishad / SBSP seat is not shown as "BJP 0%" (27 ACs in 2022, 19 in 2017).
  Seat counts by front reproduce the published results (2012 SP 224/BSP 80/BJP 47;
  2017 NDA 325/SP+INC 54/BSP 19; 2022 NDA 273/SP alliance 125). The models use SP+INC combined
  (OPP) because INC is inside the SP alliance in 2017 and 2024 but alone in 2012 and 2022.
  Memberships of small allies are TODO(verify); unlisted ones fall into Others.
- **Data findings:** AC 73, 269, 343, 374 have incomplete 2012 rows (45-55% of votes polled) and
  are kept out of fitting. Gotcha: matching the 2024 file's state with `contains("Uttar")` also
  pulls in Uttarakhand, whose AC numbers 1-70 collide with UP; the loader uses an exact match
  (4,288 UP candidate rows) and a test guards it.
- **Models (Phase 1):** typology = standardise 16 share columns, PCA(3), k-means; k chosen by
  silhouette + bootstrap stability (chosen k=4, silhouette 0.272, stability 0.62: modest, ACs
  form a continuum). Surprise = 2017->2022 change vs the 25 ACs most similar on 2012+2017,
  modified z (flag 3.5) with Isolation Forest agreement, or z >= 5 alone: 20 of 399 flagged (5.0%).
  Injected-anomaly test (T4.5) finds 11% / 21% / 39% of artificial 10 / 15 / 20 pt shifts, so the
  AC-level detector only catches large departures and misses the 80% recall / 2% FPR target.
  Baseline = "same as last election" with the 80% error band of the 2017->2022 transition
  (BJP-led +/-7.4, SP/INC +/-16.5, BSP +/-14.8 pts); the pooled 2012->2017 band (BJP-led +/-29.7)
  is shown as a stress range. Ridge / gradient boosting do not beat the baseline on every front
  (better for BSP, worse for BJP-led), so the baseline stays.
- Reproducible: seeded; two fresh builds give identical `ac_insights.json`.
- **Not done / next:** rebuild `data/processed/` + `servedb.sqlite` (missing on this machine);
  `GET /api/insights/*` in `server/app.py` and an Insights tab in `web/`; booth-level models are
  blocked until the booth crosswalk passes a check (Agra pilot: same-booth BJP share correlates
  only 0.06-0.30 across elections).

## 2026-10-07 - OCR manual gate + rotation/verify hardening

- New `Scripts/ocr/manual_check.py`: interactive per-PDF questionnaire
  (rotation 0/90/180/270, language english/hindi/marathi/mixed/other,
  readable, layout, action convert/hindi/skip, notes) → `data/2024/manual_check.csv`
  (137 rows: 47 convert, 90 hindi). 90° = CCW/left, 270° = CW/right.
- `Scripts/ocr/ocr_english.py`: manual gates first (hindi→HINDI_SKIP,
  skip→MANUAL_SKIP, convert→force-English + manual rotation wins; notes
  rotation hints like "need rotation 90" override the column + backfilled
  3 rows); classify tries all grid-passing angles, HINDI only on strong
  signal (frac>0.40, ≥40 tokens, ≥100 letters), weak→UNCERTAIN→convert;
  per-page angle scoring; new `verify_workbook()` cell-by-cell proof before
  OK (else `.OCR_REVIEW.xlsx`); `--force-english`; `ROOT` fixed for
  `Scripts/ocr/` layout (fixes AC-MAP 0).
- `Scripts/ocr/ocr_form20.py`: `ROOT` fixed, double page-append bug fixed.
- Docs: `Scripts/ocr/*.logic.md` rewritten; `DATA_SOURCES.md` SCANNED flow
  now manual-gated (see TASKS T1.2).

## 2026-10-06 - serving track Phase A (code; build + verify pending)

New `brain/PLAN.md` (serving plan, user decisions: SQLite over cloud
DBs, Docker-anywhere, full-workbook dashboard, brain-sanctioned geo).
- `Scripts/build_servedb.py`: state CSVs + `up_booth_report.xlsx`
  (All_ACs read positionally = display truth) → `servedb.sqlite`
  (`booth_row` 162k incl. 36 demo REAL cols, `booth_election`,
  `vote` 3.4M, `ac_summary`/`ac_party`/`ac_zones` pre-aggregated,
  `coverage`, `meta`, FTS5 search; indexes after bulk load).
- `server/`: FastAPI `app.py` (7 scoped endpoints, GZip, read-only
  connections, never full-table) + vanilla-JS `frontend/` (KPIs,
  district browser, AC view with SVG charts + virtualized booth grid
  in Results/Turnout/Demographics groups, booth drill-down, coverage,
  methods; no CDN) + `Dockerfile`/`render.yaml`/`fly.toml` +
  `requirements.txt` + README. `.gitignore` covers `servedb.sqlite`.
- NOT yet run: `pip install -r server/requirements.txt`,
  `build_servedb.py` full build (~5 min), endpoint smoke tests
  (EXPLAIN QUERY PLAN per endpoint), deploy. Run externally.
- Pilot-slice semantics made explicit: `--districts` filters only
  AC-scoped tables (`booth_row`, `booth_election`, `vote`,
  `ac_summary`, `ac_party`, `ac_zones`); `coverage` + Methods/
  Zone_Counts stay statewide. Sources are still fully parsed, so the
  flag shrinks the DB, not the runtime. Unknown district names now
  exit 2 instead of building an empty store; `meta.scope`/`meta.slice`
  surface as a red UI banner + Methods caveat, and the AC KPI is read
  from the store instead of hardcoded 403.
- `seg2024`/`seg2024_ac` tables from the ECI assembly-segment CSV
  (official 2024 totals, all 403 ACs, verified: 4,288 candidate rows);
  `/api/ac/{ac}/votes` falls back to them when 2024 booth conversion
  is missing, with a `source` label shown under each chart. REQUIRES
  REBUILD of servedb.sqlite.
- Static offline `/docs` API reference (real verified example
  responses) for the Next.js frontend; Swagger moved to `/swagger`;
  CORS enabled for cross-origin GET (`ALLOWED_ORIGINS`, default `*`).
- Builder progress logging (scan/insert counts) + `BUILD COMPLETE`
  marker; `/api/meta.store_ok` + red dashboard banner detect
  interrupted builds. DIAGNOSIS 2026-10-06: the live
  `server/servedb.sqlite` was half-built (booth_row full, vote/
  summary/coverage/meta empty) — build killed during the silent vote
  phase. Full rebuild required.
- API-key auth: `X-API-Key` required on `/api/*` when `API_KEY` is
  set; unset = open dev mode with a startup warning. Docs pages stay
  public. Temp dashboard prompts for and stores the key in
  sessionStorage. `/docs` documents the header, 401s, and Next.js
  server-side guidance.
- Render deploy path: slim image (no baked DB) + `entrypoint.sh`
  (one-time store download from `STORE_URL` to `/data`) +
  `.dockerignore` + `render.yaml` with 1 GB disk + secrets
  (`STORE_URL`, `API_KEY`, `ALLOWED_ORIGINS`). `/api/meta` exempt
  from auth for health checks. `fly.toml` gets the same `/data`
  volume layout. Steps in `server/README.md`.
- `GET /api/overview?election=&vs=`: homepage rollup (seats with
  party-alias normalization + NOTA/MIN_VOTES-2000 gates, avg share,
  AC zones by booth-cutoff means, booth zones + verified top booths,
  voter fallback, electors-weighted religion means, coverage notes).
  Verified live: LS2024 BJP 162 leads / 41.37%, VS2017 BJP 292.
- Temp dashboard restyled to the approved mockup (cream/saffron,
  KPIs + gauge, zone cards, voter + religion panels, zone→AC table,
  AC tabs incl. Past Elections, Map placeholder). Formula contract
  in `server/DASHBOARD_LOGIC.md`.
- `web/` Next.js 14 frontend (App Router, no UI/chart deps):
  home/zone/AC pages porting the mockup, hand-rolled SVG charts,
  catch-all `app/api/*` proxy attaching `X-API-Key` server-side,
  images from FastAPI `/assets`. Run: `npm install && npm run dev`
  (user-side; needs `.env.local` + running FastAPI).
- API Docs link removed from Next.js header (still on FastAPI).
- M/F turnout redesigned as pie + percentages + counts (both UIs).
- Speed: in-memory response cache for static endpoints (overview
  1.4s → 0.10s warm; store is immutable so cache lives until
  restart) + client fetch-dedup in Next.js (no refetch on tab
  switches). For real speed use `npm run build && npm start`
  (dev server compiles on demand).
- Temp static dashboard DELETED (`server/frontend/index.html`,
  `app.js`, `styles.css`) — Next.js in `web/` is the only UI.
  FastAPI is now API-only (`/` returns a pointer JSON; `/assets`
  and `/docs` stay). Dockerfile drops the frontend copy.
- M/F turnout shows percentages only (counts removed); all bar
  charts rebuilt on proper flex tracks (bar % now measured against
  remaining space, values in fixed tabular slots) — fixes page
  overflow/misalignment in both UIs.
- AC religion graph: new cached `/api/ac/{ac}/religion`
  (electors-weighted booth means + booth coverage counts),
  rendered as the home-style bars on the AC Overview tab
  (Next.js). Verified AC 387: 372/461 booths.
- Speed round 2 (profiled: vote-rollup join was 0.84s ×2/call):
  per-election rollup cache + startup warmup of all 4 elections
  (first overview 1.4s → 0.50s, repeats 0.10s), `(zone, aYYYY)`
  composite indexes via new `Scripts/add_zone_share_indexes.py`
  (applied live in 1s; mirrored in builder for rebuilds).
- Next.js home round 2: BJP trajectory chart 2017–2024 (share
  line + seats/leads labels), turnout-trend bars (from acs sums),
  Find-a-Constituency search + district accordion, voter donut,
  store freshness in footer, sticky header, card hover, global
  delta styles. No new endpoints.
- Everything-via-endpoint: new cached `GET /api/trend`
  (statewide share+seats+turnout), `/api/ac/{ac}/past` (shares,
  winner/runner-up, margins, source), `/api/ac/{ac}/ages`
  (electors-weighted modeled means overall + per religion),
  `/api/ac/{ac}/averages` (per-booth M/F means + totals).
  Next.js trend/past/ages/averages sections now read these only —
  zero client-side aggregation. Verified live (AC 88).
- `GET /api/margins?election=&order=&limit=&ac=` for the live
  third-party frontend (per-booth winner/runner-up/margins,
  histogram; asc=closest, desc=landslides). Verified VS2017:
  114,399 booths, brackets sum exactly. `/docs` gains a widget→
  endpoint integration map for that frontend.
- `server/assets/`: `parties/` (logos as `bjp.png`, `ind.png`,
  `nota.png`, `other.png` fallback) + `portraits/` (candidate
  name-slug `.jpg`), served at `/assets/*`, baked into the image.
- Male–female turnout: new `/api/ac/{ac}/sexratio` (booth M/F sums
  per election + F-per-1000-M), paired ♂/♀ bar chart on the AC view,
  documented in `/docs`.

## 2026-10-06 - state report: 2017 modeled demographics folded into All_ACs

`data/uprolls2017.csv` (146,638 modeled booth rows, 2017 vintage:
religion shares, age avgs/stddevs overall + per religion, women%,
revision/missing percents) mapped into trailing `All_ACs` columns
(36 data cols, each header-tagged `(modeled)`; 58→94 cols). Joined by
(AC, zero-stripped PS) on the 2017 booth, shown on every row of that
booth; join rate logged as a `DEMO-CHECK` coverage row.
- Honesty treatment (measured before mapping): statewide means show
  parsi 4.4% / christian 5.6% / jain 4.1% / sikh 3.0% (all inflated
  vs Census), women% mean 66.5% (implausible), age_avg max 3.4e22
  (unparsed leaks). So: modeled cells blanked where electors_17 < 200
  (RULES R5), age avgs kept only in [15,100] and stddevs in [0,50],
  `missing_percent_17` kept as the quality signal, Methods + headers
  carry the MODELED-ESTIMATE warning. Admin cols (electors, missing,
  revision) exempt from suppression.
- Full statewide rebuild still required (run externally).

## 2026-10-06 - state report: turnout folded into All_ACs + 2024 segment file

User rulings: (1) no new sheets for new data — turnout moves from the
`Turnout` sheet into trailing `All_ACs` columns (E/M/F/O/T/TO% per
election + `2024 AC Electors`); the sheet is no longer written.
(2) ingest the missing 2024 source
`data/assembly-segment-level-voting-data-for-all-constituencies-2024.csv`
(ECI, title row + header + one row per AC×candidate; 4,288 UP rows,
all 403 ACs, 809 unambiguous candidate→party after dropping 15
cross-AC name conflicts).
- `Scripts/build_state_report.py`: 2024 party priority is now Agra
  exact map > segment file (official) > LS-results unambiguous names;
  `SEG-CHECK` coverage compares per-AC booth polled sums against
  segment valid+NOTA (0.5% gate) with a summary row; All_ACs grows
  33→58 cols (O = Other gender, ~always 0 — NOT the opposition;
  opposition stays Party B / B V.%); `Booth_Votes` rows keep
  `E/M/F/O/T`. Segment loader verified: AC86 electors 466,585 =
  the converted Form20 title block.
- Standing rule added to `brain/RULES.md`: new data extends existing
  sheets as columns, never new sheets. Full statewide rebuild still
  required (run externally).

## 2026-10-05 - state report: gender-split turnout + ingest fixes

Audit of `output/up_booth_report.xlsx` found the report was NOT perfect:
(1) Male/Female/Other turnout dropped (sources carry Voters Turnout
M/F/O/T + EPIC + Tendered); (2) no-Name 2017 geometry mis-parsed
(ps_name=electors, electors=Male, polled=EPIC=0); (3) column-index
helper rows ingested as phantom booths (AC = column number, parties
'11','14',... - e.g. fake VS2022-AC1 rows from `AC288.xls`, which also
corrupted Party B to '50'); (4) 176x `INGEST-FAIL` noise from 2022
`.xlsx` Hindi duplicates (xlrd-only path); (5) files with zero triplet
sheets left no coverage trace.
- `Scripts/agra_pipeline.py` `ingest_eci`: per-sheet with-Name /
  no-Name booth-block auto-detect; captures male/female/other/epic/
  tendered per booth; helper rows skipped via numeric triplet-party
  cells (plus numeric-party guard); files with no usable triplet
  sheets get a `NO-TRIPLET-SHEETS` coverage row. `agra_booth.csv`
  gains the five columns (2024 = None - Form20 has no gender split).
- `Scripts/build_state_report.py`: `state_booth.csv` gains
  male/female/other/epic/tendered; new `Turnout` workbook sheet
  (per-election Electors + M/F/O/T + TO%); `Booth_Votes` rows carry
  `E/M/F/O/T`; 2022 globs `*.xls` only with `.xlsx` Hindi duplicates
  counted once as `HINDI_XLSX_SKIP` (VS2022 covers the 225 English
  .xls ACs); Methods rewritten (Party B = VS2022 top non-BJP, 2024
  M/F/O blank). Verified on pilot `--districts Agra Saharanpur` →
  `output/up_pilot_mfo.xlsx` (AC1-PS1 2017: 1049/431/307/0/738 =
  source; Party B BSP, shares recompute).
- Known gaps (not fixed): VS2022 ~176 ACs exist only as Hindi `.xlsx`
  (needs openpyxl Hindi parser); 2024 thin (150/392 PDFs converted);
  some 2017 files (3, 4, 101, ...) use a non-triplet layout
  (NO-TRIPLET-SHEETS, needs parser); 2017 no-Name sheets carry no
  booth names. Full statewide rebuild still required (pilot
  overwrote `data/processed/state_*.csv` with the 16-AC subset).

## 2026-10-05 - booth report: single sheet + 4 zones

`Scripts/output_booth_report.py`: the 9 per-AC sheets are replaced by
one `All_ACs` sheet (3896 booth rows; new AC column first + per-row
Party B column since B varies by AC; auto-filter for per-AC views).
Zones renamed per user: Safe (avg>+0.10 & latest>0, 2338),
Favorable (avg>0 & latest>0, 160), Battlefield (otherwise contested,
790), Difficult (340), Data Not sufficient kept (268; old Swing 950 =
160+790). `configs/output_format.json` spec updated (columns A-AE,
zone_rule, Party B). Regenerated `output/agra_booth_report.xlsx`
(old timestamped variants in output/ left untouched).

## 2026-10-05 - renamed 2024 converted xlsx to <AC>.xlsx

New `Scripts/rename_converted.py` (`--apply`): the 150 converted
2024 workbooks now follow the 2017 pattern (`data/2017/Agra/86.xls`),
named by Assembly number (e.g. `data/2024/Agra/86.xlsx` … `94.xlsx`,
plus Jalesar segment `106.xlsx`). PDFs untouched (raw immutable).
124 renamed; 26 converted files have null AC (unreadable mirrored
title blocks) and keep original names - listed in
`data/2024/rename_report.md`. References updated in the same run:
`configs/data_files.json` xlsx fields (byte-surgical, 124 refs) and
`data/2024/bulk_convert_report.csv` (140 rows incl. duplicate-folder
entries, matched by PDF basename). Caveat: bulk `--skip-existing`
keys off `<pdf-stem>.xlsx`, so a future bulk rerun would reconvert
renamed files instead of skipping them.

## 2026-10-05 - ocr_english.py (English-only SCANNED converter, user-run)

New `Scripts/ocr_english.py` for the 137 SCANNED files (see
`data/2024/convert_report.md` list): Phase A classifies each file by
Devanagari-vs-Latin ratio on a data page (English headers/names
suffice; Hindi files → `HINDI_SKIP`, listed in
`data/2024/ocr_hindi_files.md`, never converted). Phase B OCRs
English files only with per-page rotation auto-detect (0/90/180/270
+ per-page fallback), reusing the `ocr_form20` grid + crop-retry
machinery and row-sum/grand-total validation (PASS → same-folder
`.xlsx`, FAIL → `.OCR_REVIEW.xlsx` quarantine). Progress in
`data/2024/ocr_english_report.csv`: finished rows skipped on resume,
`--retry-failed` reruns only FAILED/OCR_REVIEW, `--only` slices,
`--classify-only` for the language split first. Per-file/per-page
  try/except so one bad file never kills the batch. Script written but
  NOT executed (user runs it).

  2026-10-05 pm: speed + resume fix (classify was ~3 min/file: 5 full
  OCR passes per file, and progress was only written at the end, so an
  abort lost everything). Orientation is now a ruling-grid pre-check at
  4 angles (OpenCV, seconds) + OCR once, twice max on the 0/180 flip.
  Report + Hindi list are saved after EVERY file (Ctrl+C safe), and
  `--classify-only` resumes past already-classified rows.

## 2026-10-05 - REVIEW47 pass (read-only review of the 47 quarantined files)

No PDF, XLSX or report CSV was modified (no bulk re-run). New
`Scripts/review47.py` replays the 47 REVIEW files one by one with
diagnosis + safe-fix ladder: S1 base re-extract, S2 vote-None→0
(≤2/row) / text-None→Unknown, S3 trailing-empty-candidate trim, S4
trim + Total/NOTA trailer-order variant; blank rows never filled.
`--dry-run --md data/2024/review47.md` produced the per-file review
(audit table + notes, no writes). Outcome: 27/47 have a verified
retry path (25 S1 footer recovery, 1 S2 Azamgarh-1370, 1 S4
Deoria-1712); 20 stay manual (4 EVM-shortfall-with-gaps, 2 multi-AC
Kheri, 1 blank-row GBN-1334, 2 small-diff, 1 merged-serial
Moradabad-1386, 10 Deoria/GBN/Siddharthnagar trailer-geometry).
`bulk_convert_form20.py`: footer repair extended to `<n> Page <p>`
(Bijnor) / `<n> Pag` (Lucknow) labels and the `serial e p` + fused-pair
shatter (Lucknow `260 e 1` / `19 0`); validation now records missing
serial rows, multi-AC segments and EVM-row-absent as Validation-sheet
NOTEs (never fail currently-OK files: 25/26 OK files have no EVM row).

## 2026-10-04 - Statewide store + offline dashboard (user runs heavy steps)

New Scripts/build_store.py merges every convertible Excel file into
output/booth_data.db (SQLite: booth/vote/file_coverage; resumable;
district spellings canonicalized; null-AC booths filename-keyed so PS
1..N of different files never collide). New Scripts/build_dashboard.py
writes output/dashboard_data.json + self-contained output/dashboard.html
(inlined data, no CDN/server, double-click to open): KPIs, schematic
tile-grid map (declared not-to-scale), SVG charts, Agra booth explorer,
methods. Full-name party aliases added (BHARATIYA JANATA PARTY->BJP,
SAMAJWADI PARTY->SP, ...); all-caps DevLys codes kept verbatim, never
guessed. Trends carry mapped_pct with an under-90% warning banner.

## 2026-10-04 - Reference-verified name fixes (fix_names_reference.py)

New script cross-checks every converted 2024 xlsx candidate name against
data/lok-sabha-elections-2024-results.csv (ECI, all UP PCs): exact match
kept (1,458 cells), full-reverse match replaced (56 mirrored), token-set
match reordered (51 word-order). Result: GBN NARAVEDASHVAR/NARESH NAUTIYAL,
Phulpur KUSHWAHA spelling kept as reference, Sitapur MO. KASHIF ANSARI,
Kannauj YADVENDRA KISHOR. Left untouched (would destroy data): 13 Amethi
name+party hybrids, 2 Gorakhpur legacy codes. Row math untouched (names
only). Idempotent (re-run: 0 fixable).

## 2026-10-04 - Corrupt-name reconversion approved; bulk gets --only

User rulings: (1) never delete data files (PDFs, sources, generated
sidecars; stale quarantines only leave via fresh runs — added to
RULES.md; everything remains recoverable from git); (2) reconverting
files with corrupted names is approved.
- `bulk_convert_form20.py`: new `--only` include-filter (both
  separators) + merge-safe report rewrite (targeted runs no longer
  drop other files' rows) + unmirror vocabulary (`jila jeet
  bharatiy`) so mirrored names like `YITRAHB TEEJ ALIJ` restore.
- `agra_pipeline.py` ingest_2024: dynamic lead detection (serial-only
  sheets like Pryagraj/Sambhal where col 2 is already a candidate).

New Scripts/build_filemap.py per user spec (per-file, Excel-only,
name+dtype, PDFs untouched): 1,432 Excel files mapped - 1,031
eci-triplet (booth block cols 0-9 + [name :: S.No|Party|Votes]
triplets + Total/NOTA trailers) and 400 form20-xlsx (serial/PS +
candidate vote cols + 5 trailers); 1 unreadable (password-locked
2017/Farrukhabad/192.xls, honestly recorded). Spot-verified both
layouts against known structures.

## 2026-10-04 - Per-file format map (configs/data_file_format.json)

## 2026-10-04 — District×AC file map (configs/data_files.json)

New `Scripts/build_filemap.py`: scans `data/2017|2019|2022|2024`,
maps every file by district + AC number into `configs/data_files.json`
(1,424 entries). 2024 ACs come from sidecar title blocks, else raw PDF
text. Statuses: `converted` 150 (26 with unreadable title blocks from
mirrored PDFs — numbers verified, AC flagged null + note), `review` 49
(REVIEW sidecars matched, 39 with AC), `missing_xlsx` 193 (`"xlsx":
"NOT FOUND"; 136 scans for OCR, 51 legacy-font, 6 AC-known from PDF
text), `source-excel` 1,032 (2017–2022 need no conversion).
`missing_districts`: 6 (`*Data not found*` folders). Nested batches
caught via rglob (e.g. `data/2024/Banda/Barabanki/`).

### Added
- Conditional formatting in `Scripts/output_booth_report.py`
  (`style_report_workbook`, applied on save): header/title styling;
  zone fills (Safe green / Swing amber / Difficult red /
  Data-Not-sufficient grey + bold colored text); Voting.Diff and
  avg/latest green(>+0.10)/red(<-0.10) cell rules; blue data bars on
  share columns; Zone_Counts + header styling everywhere. Verified in
  file (14 rules on AC86, fills present). Excel-lock fallback: if the
  main file is open, saves `agra_booth_report_YYYYMMDD-HHMM.xlsx`.
- READMEs: root (`README.md`, replaces 102-byte stub), `Scripts/`,
  `configs/`, `data/`, `output/`; refreshed `brain/README.md`
  (CHANGELOG row). RULES.md gains README-upkeep rule.
- Current output: `output/agra_booth_report.xlsx` (+ timestamped
  variant from the locked-save) with zones Safe 2338 / Swing 950 /
  Difficult 340 / Data Not sufficient 268.

User supplied `configs/mahad report-abc.xlsx` as the look target and
`configs/ac_format.json` (403 ACs) + `configs/data_format.json` (master
schema) as reference. Workspace was also reorganized (sources moved to
`data/20xx/`); script default paths updated (`--root data/2024`,
retry report, pipeline inputs).

### Added
- `configs/output_format.json`: formal spec of the workbook derived
  from the Mahad example (AC sheets, Booth_Votes, Zone_Counts,
  Methods_Zones; column letters, sources, formulas, zone rule). Records
  what could NOT be recovered from the example (its Average-Diff col G
  and exact zone thresholds) — both defined explicitly instead.
- `Scripts/output_booth_report.py` (renamed from output_mahad.py —
  Mahad was format-only; this builds AGRA): one sheet per AC 86→94,
  booth rows with serials per election, BJP vs per-AC top-opponent
  shares + Voting.Diff, zones Safe/Swing/Difficult/Data Not sufficient
  with gap pp AND votes needed. Output: `output/agra_booth_report.xlsx`
  (`output/`, never `data/`).
- Zones: 2338 Safe / 950 Swing / 340 Difficult / 268 Data Not sufficient
  (3896 booth rows). Verified by hand on AC86-PS1 (shares, gaps,
  votes-needed, zone all recompute exactly).
- `Scripts/agra_compare.py` + `data/processed/agra_comparison.xlsx`
  superseded by the above (kept on disk, history in git).

### OCR status: PAUSED per user (scripts kept, no deletion)
- Benchmarked on Bulandshahr Shikarpur scan (2024091311 p1, landscape,
  must rotate 90): Surya 0.22 unusable here (needs llamacpp server
  binary); EasyOCR hi+en works after rotation (220 items, headers read
  correctly). Grid via OpenCV morphology + CLAHE recovers full 21x14
  ruling grid. Digit accuracy 85% (dropped digits, faint zeros) —
  below bar; crop-retry path scaffolded in `Scripts/ocr_form20.py`.
  Remaining OCR deps installed (easyocr, torch, opencv) + Pillow 12.3
  (pdfplumber-compatible; surya pin ignored with warning).

New `Scripts/agra_pipeline.py` + `configs/agra_party_map_2024.csv`.
Covers T1.6/T2.4/T4.1/T4.2/T4.4 for Agra (details in TASKS.md).

### Scope
Only `2022/Agra`, `2019/agra`, `2017/Agra`, `2024/Agra` Excel files
(no PDFs). Agra district = ACs 86–94; 2024 Jalesar-106 segment
(Etah district) excluded with note.

### Formats handled
- 2024: our Form20 xlsx (title r5 → AC; names r8; trailers last 5).
- 2017/2019/2022: ECI triplet sheets `[S.No|Party|Votes]` with merged
  candidate names (merge-origin lookup), auto header-row detect (most
  `Votes Secured` hits — a trailing `Total Votes Secured` cell must not
  win), trailing Total/NOTA zone cut, explicit NOTA/total cols,
  column-index + blank row skips, AC carry-forward for blank AC cells
  (2022-94), per-sheet candidate-name row depth (hr-1/hr-2) with `N-`
  serial-prefix strip.
- 2022 English master (`AC86.xls`, sheets 86–94) used; Hindi pswise
  duplicates used only for cross-validation, not ingestion.

### Results (data/processed/agra_*.csv + agra_analysis.xlsx)
- 14,777 booths, 174,755 facts, 36/36 AC totals reconcile (±0.5%).
- 2022 master cross-checked vs Hindi duplicates: 7/8 ACs exact;
  AC94 differs by booth 375 (blank in duplicate; master authoritative,
  candidate data confirmed).
- Crosswalk 1:1 links: 90.3% / 96.9% / 100% (PRD ≥90% ✓); conf 0.85
  base on exact part-no (names missing/legacy in places), swings only
  conf≥0.8.
- 7,842 swing rows (pp of polled votes; parties fielded both sides
  only; IND kept as bloc with caveat; 2024 needs party-map expansion —
  only BJP verified, rest UNMAPPED TODO(verify)).
- 584 statistical_outlier flags (MAD robust-z on AC-residualized,
  EB-shrunk features; small-booth under-flagging verified within gate).
- Bugs caught by verification and fixed: trailer off-by-one
  (denominators), party-from-header-row, fake `Total Votes Secured`
  candidate, zero-MAD z-explosion, UNMAPPED fake swings, turnout
  gating (4 VS2022-89 booths with valid>turnout, candidates confirmed
  via duplicate).
- Known limits: no electors in 2024 → no turnout features touching
  2024; no IsolationForest (no sklearn) — z-only, documented;
  legacy booth names kept raw + flagged (no DevLys decoder yet).

## 2026-10-04 — Styled report workbook + folder READMEs

## 2026-10-03 — Agra comparison workbook (AC sheets + zones, as asked)

New `Scripts/agra_compare.py` reading the pipeline CSVs (no re-parse).
Per user answers: all 4 years; one workbook, one sheet per AC 86→94;
booths matched by AC+PS number (+name shown, min link conf shown;
PS-less fallback noted, unused — no such booths in data); zones per
major party with gap-to-win pp AND votes needed:
SAFE (led all ≥3 mapped) / LEADING (leads latest) / CRITICAL (gap≤5pp)
 / UPHILL (5–15) / NOT_POSSIBLE (>15); reference = latest mapped
election (2024 non-BJP unmapped TODO(verify)); plus AC_Summary and
Methods_Zones sheets. Output: `data/processed/agra_comparison.xlsx`.
Verified by hand on AC86-PS1/PS2 (shares, gaps, votes-needed, zones all
recompute exactly). Deliberately NOT merged: SAP ≠ SP (different
candidates in same AC/year).

## 2026-10-03 — Retry-only script + final lists (no reconversion)

User call: stop iterating, ship lists. State after log3 (374 run) plus
targeted fixes already in the script (garbled-OCR probe, scanned alpha
rule, ruling-less catch-all → manual bucket, SCANNED/COMPLEX counts in
summary, `--only` separator fix in retry script).

### Added
- `Scripts/retry_pending.py`: reprocesses ONLY `REVIEW`/`FAILED` rows
  from `2024/bulk_convert_report.csv` (default), merges results back
  into the same CSV, sweeps stale `.REVIEW.xlsx` on success. Never
  touches OK/SKIPPED/LEGACY_SKIP/SCANNED/COMPLEX_SKIP. `--status`,
  `--only` filters.
- `2024/convert_report.md`: full audit — 150 CONVERTED (61,524 booth
  rows) with per-file booth counts, and 242 REMAINING grouped by
  action: 47 REVIEW (reconcile by eye), 51 Hindi legacy font (needs
  DevLys decoder/manual), 137 scanned (needs OCR), 7 complex/manual.
  Built from report CSV + on-disk `.xlsx` audit (also catches the 18
  excluded-but-converted files the bulk report rewrite drops).
- Regenerated `2024/Amethi/2024091318.xlsx` (mirrored names now stored
  correct, not mirrored).

### Result
- Converted 150/392. Remaining 242 all classified with reasons; zero
  FAILED left (all routed to a named bucket).
- Known behaviour (untouched per user call): bulk report rewrite omits
  `--exclude`d files — the md audit compensates via disk scan.

## 2026-10-02 — Bulk converter round 2: log2 triage (lead-1, mirrored text, footers, scanned)

User's full run (`bulk_convert_log2.txt`: 374 files → 92 OK, 34 legacy,
81 REVIEW, 162 FAILED) triaged into root causes, all addressed.

### Fixed (`Scripts/bulk_convert_form20.py`, single-file script untouched)
- **New layout: single-serial sheets (`lead=1`, e.g. Azamgarh).**
  Candidate block anchored at first non-empty cell instead of hardcoded
  col 2.
- **Mirrored-English text restored** (`maybe_unmirror`: per-cell
  forward-vs-reversed English scoring, numbers/Devanagari untouched).
  Covers fully-mirrored headers (Sitapur `.oN laireS` → Serial No.) and
  mirrored candidate rows (Kannauj `hselihkA vadaY` → Akhilesh Yadav).
- **Page-footers fused into last booth row of each page** repaired
  (proven by EVM math): `24 Page` / `24 1` form (Ambedkar, was −4%
  shortfall) and shattered `P 54` / `ag 54` / `e 1 17` form
  (Pratapgarh, was −1-2%).
- **Column-index rows** also in `1,1,2,3…` duplicate-serial form.
- **Trailer detection** widened (`Total No. of valid votes`,
  `No. of Rejected Votes`, …).
- **Candidate-capture plausibility guard** (`names_look_plausible`):
  header labels can never become candidate names (had caught Ambedkar
  1310 silently taking `No of Valid Votes…` as candidate 1).
- **New terminal statuses:** `SCANNED` (zero extractable tables/text,
  e.g. all Ayodhya — needs OCR, future work), `LEGACY_SKIP` fallback
  probe for capture failures (Hindi 2-row headers, e.g. Azamgarh 1366).
- `legacy_probe` hardened: ignores mixed-font Devanagari-fragment
  cells and header vocabulary; forward-English rescue (≥3 distinct
  words) protects genuine English layouts.
- Scan rule hardened: `SCANNED` only when tables absent AND text
  < 500 chars (a digital PDF without ruling lines must not count).

### Verified this round
- Ambedkar 5/5, Azamgarh 1 OK + 8 LEGACY_SKIP (+1 honest 2-cell
  REVIEW), Kannauj 3/3, Sitapur 6/6, Pratapgarh 5/5, Ayodhya 5/5
  SCANNED. 13 superseded `.REVIEW.xlsx` swept.

### Known limitations / next
- ~133 scanned-image PDFs need an OCR path — `SCANNED`-skipped.
- Legacy-font files still need a DevLys-010 decoder + `lead=1` geometry.
- Azamgarh 1370: 2 booth rows with one unparsed cell each → REVIEW.

## 2026-10-02 — Bulk converter: legacy-Hindi skip, layout fixes, crash fixes

### Fixed
- `Scripts/bulk_convert_form20.py`
  - **Legacy-encoded Hindi PDFs are now detected and SKIPPED
    (`LEGACY_SKIP`), never converted with corrupt names.** Files with
    DevLys010/Kruti-era fonts (Amroha, Auraiya, Maharajganj batches;
    e.g. `2024/Amroha/2024091314.pdf` showing `dqjoj nkfu'k vyh`
    instead of `कंवर सिंह तंवर`) are left untouched and listed in the
    end-of-run summary plus `bulk_convert_report.csv`.
  - Assembly-format Form 20 supported (3 leading cols, single-row
    header, e.g. Amethi). Previously 4 files FAILED.
  - Column-index helper rows recognised in all shapes; never counted
    as booth data.
  - Last-page summary rows with merged leading cols realigned.
  - Postal-zero rows no longer mistaken for the EVM-total row.
  - Control characters stripped (fixes `IllegalCharacterError` crash).
  - Stdout/stderr forced to UTF-8 (fixes `UnicodeEncodeError` crash
    that killed the batch at file 32/391).
  - Dynamic candidate counts (7–26) with `lead`/`trailer` geometry.
- Removed corrupt/stale outputs from earlier runs.

### Verified
- Amethi 5/5 OK (was 1 OK + 4 FAILED). Agra 9/9 OK (unchanged).
- Amroha 5/5, Auraiya 1/1, Maharajganj 5/5 → `LEGACY_SKIP`, no xlsx.

### Docs
- `brain/DATA_SOURCES.md`: Form 20 layout variants + quirks.
- `brain/TASKS.md`: T1.1/T1.2/T1.3 progress for the 2024 batch.
- `brain/RULES.md`: changelog discipline recorded.

### Known limitations / next (superseded by round 2 above where noted)
- Legacy-font files need a DevLys-010 decoder (mapping verified on
  samples: `daoj→कंवर`, `raoj→तंवर`) — out of scope per user call.

## 2026-10-02 — Bulk converter v1 (dynamic candidates, verification)

- Added `Scripts/bulk_convert_form20.py`: recursive `2024/` batch,
  per-file progress prints, row-sum + EVM validation, post-save reload
  check, `REVIEW` quarantine, `--skip-existing`, `--exclude`, CSV
  report. Single-file `Scripts/convert_form20.py` left untouched.

## 2026-10-02 — Single-file pilot (Agra Fatehpur Sikri)

- Added `Scripts/convert_form20.py`: `2024/Agra/2024091321.pdf` (16 pp,
  9 candidates, 398 booths) → same-folder `.xlsx`, 6368/6368 cells
  verified against PDF, row-sums + EVM totals pass.
