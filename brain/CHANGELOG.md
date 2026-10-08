# CHANGELOG

All notable changes to this project. Newest first.
Rule (see `brain/RULES.md`): every code change updates this file **and**
the relevant `brain/` doc in the same sitting.

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
