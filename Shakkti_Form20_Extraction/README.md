# Shakkti Form 20 Extraction

Turns scanned **Form 20 "Final Result Sheet"** PDFs (polling-station-wise election results,
English or Hindi/Devanagari) into a clean **Excel workbook** - one row per polling station,
one column per candidate - and tells you which rows, if any, a person still has to look at.

```
PDF  ->  upright, de-skewed page images  ->  table grid  ->  cell-by-cell digit OCR
     ->  arithmetic validation + repair  ->  Excel (+ review queue with scan crops)
```

Nothing is typed in by hand and no figure is invented: every number comes from the scan, and
the sheet's own arithmetic is used to catch and repair OCR slips.

## Results on the three sample sheets

| Sheet | Segment | Language | Pages | Rows | Read exactly (`OK`) | Repaired by arithmetic (`AUTO_CORRECTED`) | Odd source row (`UNUSUAL`) | Need review (`REVIEW`) | Column totals match printed totals |
|---|---|---|---|---|---|---|---|---|---|
| `1Eng.pdf` | 1-Behat | English | 16 | 397 | 364 | 32 | 1 | **0** | yes, all 15 columns |
| `3Eng.pdf` | 3-Saharanpur Nagar | English | 18 | 454 | 418 | 34 | 2 | **0** | yes, all 15 columns |
| `8Hin.pdf` | 2-Kairana (LS 8) | Hindi | 10 | 324 | 311 | 12 | 1 | **0** | yes, all 19 columns |
| **Total** | | | 44 | **1,175** | 1,093 | 78 | 4 | **0** | |

Independent checks:

* The Hindi PDF carries its own (partial) text layer. **All 1,393 numbers in it that fall inside the
  table are identical to the extracted workbook (100%)** - `python eval/text_layer_check.py data/input/8Hin.pdf data/output/8Hin_Form20.xlsx`.
* The English PDFs are plain scans (no text layer); for them the independent evidence is that every
  row satisfies both identities and every column sum equals the printed totals row.
* No hand-corrected "answer sheet" exists for these PDFs yet. When one is available,
  `eval/compare.py` reports the exact cell/row accuracy.

Speed: about 8-9 s per page on a laptop CPU (44 pages in ~7 minutes). The `UNUSUAL` rows are genuine
oddities in the scans (e.g. one polling station with `5 5 5 5 5 5` votes for six candidates); the
numbers are read correctly but are worth a human glance.

"Column totals match" means the sum of every extracted column equals the *printed* "Total EVM
votes" row of the sheet - an independent check that the whole file was read correctly.

## How it works

| Stage | Module | What it does |
|---|---|---|
| 1-2 | `imaging.py` | Renders each page (honouring the scan's rotation flag), de-skews it using the table's ruling lines. |
| 3 | `grid.py` | Finds the row lines and column lines. Scanned lines are broken, so row lines missing inside the table are re-inserted at the row pitch and the **column positions are voted over all pages of the file** and snapped to each page. |
| 4 | `header.py` | Reads the title block (electors, segment number/name, language) and the candidate-name row. |
| 3-5 (typed PDFs) | `textlayer.py` | When a PDF has a usable text layer (typed PDFs, searchable scans) the columns, rows and cells are taken from the numbers' positions on the page instead of by OCR: exact digits, about 100x faster. A partial layer, or one whose columns do not fit the official candidate count, is refused and the PDF is read by OCR as before. |
| 5a | `ocr.py` (`tracked_edges`), `grid.py` (`align_to_rules`) | On a tilted or curved scan the digits of the right-hand columns sit lower than the left-hand ones. Each column's rows follow its own digit ink, and a page whose table is narrower or wider than the template (a short last page) is slid onto its vertical rules, so cells no longer cut the digits. |
| 5b | `rescue.py` | Rows the line detector missed (faint or doubled lines, a shadow) are found from short pages and serial jumps and read from the extended grid; rows lost at the end of the last page are looked for until the official totals are made up. |
| 6a | `discover.py` | When none of the fixed column layouts (A/B/C) fits, the column structure is found by arithmetic: a block of candidate columns, a valid column equal to their sum (or none), and valid + rejected + NOTA = total. |
| 5 | `ocr.py` | Paints the ruling lines out, crops every cell tight to its digits and reads it with Tesseract (single-word mode, batched). Every cell is read twice with two different renderings. |
| 6 | `validate.py`, `pipeline.py` | For each row: `sum(candidates) = valid votes` and `valid + rejected + NOTA = total`. If the plain reading fails, the cheapest combination of alternative readings (the other rendering, a leading/trailing "1" that was really a ruling line, a blank solved from the equations) that satisfies both is used. Finally the printed totals row is used to settle ambiguous rows. |
| 7 | `export.py` | Writes the workbook, plus a cropped scan of each row that needs review. |

Serial numbers and polling-station numbers are narrow cells that OCR reads poorly; they are
instead derived from the sequence (1..N, continuous across pages) and only checked against the
reads (a real break in the sequence is flagged).

## What the status values mean

| Status | Meaning | Needs a person? |
|---|---|---|
| `OK` | The first reading already satisfies both identities. | No |
| `AUTO_CORRECTED` | The first reading did not add up; a nearby reading did. Changed cells are shaded yellow and listed in the `Auto_Corrections` sheet. | No (audit trail only) |
| `UNUSUAL` | Arithmetic is fine, but the printed row itself looks odd (the same value of 3 or more repeated in many candidate columns). Row shaded orange, crop of the scan in `Review_Queue`. | A glance |
| `REVIEW` | Could not be made consistent, or several readings are equally likely and the printed totals cannot settle it. Row shaded red, crop of the scan in `Review_Queue`. | **Yes** |

Source figures are never "fixed" to make a total balance: if the sheet is itself inconsistent
(for example, the printed totals do not equal the sum of its rows), this is reported in
`Totals_Check` / `Review_Queue` and the figures are kept as printed.

## Setup

1. **Python 3.10+** and the packages: `pip install -r requirements.txt`
2. **Tesseract 5** (the program itself):
   Windows installer from <https://github.com/UB-Mannheim/tesseract/wiki>; make sure `tesseract`
   is on `PATH` (`tesseract --version`).
   The English and Hindi models used (`tessdata_best`) are already in `./tessdata/` and are picked
   up automatically (the package sets `TESSDATA_PREFIX`), so nothing else needs installing.

## Run

```bash
python run_form20.py data/input                  # every PDF in a folder
python run_form20.py data/input/1Eng.pdf         # one file
python run_form20.py data/input --out data/output --no-crops
```

(or `PYTHONPATH=src python -m form20 ...`). Takes about **8-9 seconds per page** on a laptop CPU;
a 16-page sheet takes roughly 2 minutes.

For each PDF you get `data/output/<name>_Form20.xlsx`; for a folder also
`Form20_all_files_summary.csv`. Review crops are saved in `data/output/review_crops/<name>/`.

### The workbook

| Sheet | Content |
|---|---|
| `Form20` | The result table in the 2024 Form 20 layout (title block, candidates as columns, printed totals rows, and a live `SUM` row to compare with them). Extra columns from the older 2017 layout - *Total Electors (Polling Station)*, *Voters Turnout Male/Female/Other*, *Voters identified using EPIC* - are present but **blank**, because these PDFs do not contain them; a *Party* row sits under the candidate names. QC columns at the right: status, note, source page and row. |
| `Tidy` | The same data in long form (one row per polling station x candidate/total) - convenient for pivot tables or loading elsewhere. |
| `Review_Queue` | Rows needing a look, with the reason, what OCR plainly read, the values used and a picture of the scan. |
| `Auto_Corrections` | Every cell the arithmetic changed: plain reading vs value used. |
| `Totals_Check` | Printed "Total EVM votes" vs sum of the rows, per column. |
| `Run_Log` | Counts, language, time, where the candidate names came from, warnings. |

## Candidate names and parties (`config/candidates.csv`)

Candidate names in the header are small, rotated (Hindi) or printed in a serif face, and OCR
gets them only approximately right. They are therefore taken from a **reviewed mapping**:

```
file,position,name_native,name_en,party
8Hin.pdf,1,इकरा चौधरी,IQRA CHOUDHARY,
```

* `file` is the PDF's file name, `position` the column order on the sheet (1 = first candidate).
* `name_native` is what is printed; `name_en` the English spelling to use in the Excel header.
* `party` is optional - the sheets do not state parties; fill it in if you have them.

If a PDF is not in the file, the names are OCR'd and the Run_Log says
**"UNVERIFIED"**: add the file to `candidates.csv` and run again (takes the same time).
The entries shipped for the three sample PDFs were typed in from the scans / the supplied
reference Excel; please have someone confirm the spellings once.

## Checking accuracy against a correct Excel

```bash
python eval/compare.py data/output/3Eng_Form20.xlsx path/to/correct.xlsx --out diffs.csv
```

Rows are matched on the serial number, numeric columns by position; it prints the percentage of
rows and cells that are exactly right and writes every difference to the CSV.

## Limitations - read before relying on it

* **Layouts supported:** landscape sheets with a ruled table, one candidate per column and the five
  standard total columns. The number of leading identifier columns (serial / polling-station number /
  station name) is chosen per file: the first 16 rows are read with 1, 2 and 3 id columns and the choice
  whose rows already satisfy both vote identities wins (the language default is kept unless another choice
  is clearly better; a blank rejected/NOTA cell is tolerated, a blank candidate cell is not).
  **Not supported:** portrait "भाग-1" sheets, scans whose column lines are too faint to detect
  (the table then comes out with a handful of columns), and sheets whose rows have very different
  heights (station names wrapping onto two lines make the uniform row pitch miss rows). These show up as
  `FAILED` / `FLAGGED` in the batch ledger.
* **Polling-station numbers** on English sheets are assumed to run 1,2,3... with optional letter
  suffix rows (41, 41A, 42). A genuine gap in numbering would not be detected from the narrow cells.
* **Not on these PDFs, so blank in the Excel:** electors per polling station, male/female
  turnout, EPIC-identified voters, party names.
* **Postal-ballot rows** are read when the sheet carries them (the three sample sheets have none).
* **"Fully automatic"** here means every row whose arithmetic holds is accepted without a person.
  It cannot prove a row right if two independent misreads cancel exactly *and* the column totals
  also balance - extremely unlikely, but not impossible. Rows flagged `REVIEW` are the ones to look at.
* Only Tesseract is used. No other OCR engine and **no model training / fine-tuning was needed** for
  the sample sheets: the cell-by-cell reading plus the arithmetic checks already gave 0 review rows.
  If a future batch of poorer scans does need it, the auto-verified rows of earlier runs are ready-made
  labels (cell image + value) for fine-tuning a digit reader.
* Image quality matters: the English scans are only ~100 DPI. Much worse scans will produce more
  `AUTO_CORRECTED` and `REVIEW` rows.

## Batch conversion of the 2024 PDFs (`queue/` and `batch/`)

The 2024 Form 20 PDFs in `data/2024/PDF` that have no Excel yet are tracked in `queue/` and converted by `batch/`:

| Path | Job |
|---|---|
| `queue/to_convert.csv` | PDFs to OCR, in run order. Tier A = scanned, tier B = unusable text layer (legacy fonts / unmapped glyphs) |
| `queue/to_review.csv` | ACs that need a person's decision first: duplicate PDFs, quarantined `.REVIEW.xlsx`, mislabelled or unnamed files |
| `queue/ac_overrides.csv` | Hand-maintained: PDFs whose AC differs from their file name (e.g. `109Eng.pdf` is AC 190) |
| `queue/conversion_ledger.csv`, `queue/review_after_conversion.csv` | Written by the converter: per-PDF results, and the subset that needs a look |
| `batch/build_queue.py` | Regenerates `to_convert.csv`, `to_review.csv` and `queue/README.md` from the PDF/Excel folders |
| `batch/convert_queue.py` | Runs the extractor over `to_convert.csv`; resumable; writes to `data/output/2024/` |

```bash
python batch/build_queue.py                    # refresh the lists
python batch/convert_queue.py --dry-run        # what would run and how long
python batch/convert_queue.py --limit 3        # pilot
python batch/convert_queue.py                  # all of tier A (resumable; Ctrl-C is safe)
python batch/convert_queue.py --tier A,B       # include tier B
python batch/convert_queue.py --workers 4      # convert several PDFs at the same time
```

The converter reuses `process_pdf` / `export_workbook` unchanged, never touches `data/2024/PDF` or `EXCEL`, and
records per PDF the row statuses, whether the column totals match the printed totals, and (English sheets) whether
the AC printed on the page matches the expected AC. Candidate names are OCR'd and marked unverified unless the PDF
is listed in `config/candidates.csv`. The workbooks have more sheets and columns than the existing `data/2024/EXCEL`
files, so check the downstream loaders before filing them there.

### Reading from the text layer, and the row rules that go with it

`convert_queue.py` reads a PDF from its text layer when it has a usable one (`source` column of the ledger: `text layer`
or `ocr`) and falls back to OCR when that read is refused or fails the layout gate. Set `FORM20_TEXT_LAYER=off` to force OCR.
Rows that are not polling stations are removed before the column totals are settled:

| Rule | Removes |
|---|---|
| `drop_index_rows` | the header's column-number row (1 2 3 ... n, or running on from the identifier columns), once per page where the header repeats |
| `drop_impossible_rows` (text layer only) | rows with a vote count above `MAX_CELL_VOTES` (sheet totals; with exact digits that cannot be a misread) |
| `drop_subtotal_rows` | page or running sub-totals: a row equal, in every candidate column and valid, to the sum of the rows above it |
| `drop_duplicate_pages`, `drop_total_rows` | repeated pages; the grand total row(s) at the end |
| `drop_official_total_rows` | a row repeating four or more of the official column totals (total row whose big cells were unreadable) |
| `drop_excess_rows` | one stray row (or two unsure ones) that equals, in every candidate column and NOTA, exactly what the sheet holds above the official totals |

Verification against the official 2024 segment-level data and the work lists:

| Script | Job |
|---|---|
| `batch/verify_official.py` | `queue/official_check.csv`: FULL when every candidate column and NOTA equal the official totals |
| `batch/stage_verified.py` | copies FULL workbooks, in the `data/2024/EXCEL` layout, to `data/output/staged_excel/<AC>.xlsx` (never into `data/2024/EXCEL`) |
| `batch/split_multi_ac.py` | cuts PDFs that hold several constituencies (137Eng, 141Eng) into one workbook per AC |
| `batch/status.py`, `batch/priority_status.py` | `queue/status.md`, and the state of the 180 ACs of `excel_pdf_map.md` with a reason for each that is not done |
| `batch/status_report.py` | `queue/priority_180_report.md`: the plain-language report of done / not done and why |

### What is left: review packs and the converted folder

`data/2024/converted/` holds the workbooks that match the official totals (`batch/publish_converted.py` copies them from
`data/output/staged_excel/` and writes `MANIFEST.csv`: every priority AC, its input PDF, its output file, how it was produced and
why it is pending). Nothing goes into `data/2024/EXCEL` without a person's decision.

For converted ACs that do not match yet, `batch/review_pack.py` writes `data/2024/review/<AC>_review.xlsx` and `REVIEW_INDEX.csv`:

| Class | Meaning | Next step |
|---|---|---|
| `SOURCE DIFFERS` | typed PDF, exact digits, a few votes from the official data | decide whether to share it with a note |
| `NOTA COLUMN` | every candidate column exact, NOTA off | a column-assignment fix |
| `ROWS MISSING` / `EXTRA ROWS` | the shortfall (excess) is worth about N booths | re-read the blue-marked pages / remove the duplicate |
| `CHECK ROWS` | digits misread in a few rows | check the flagged rows against the scan |
| `NEEDS CODE FIX` | more than 10% off: rows, pages or columns wrong | a better reader first |

A pack is the converted workbook with an `Official_Gap` sheet in front (column totals against the official ones, where votes are probably
missing, the flagged rows with links) and blue serial cells where rows are missing. After correcting cells in its Form20 sheet,
`python batch/recheck_reviewed.py data/2024/review/<AC>_review.xlsx --accept` recomputes the totals from the booth rows and, when every
candidate column and NOTA match the official 2024 totals, files the workbook into `data/2024/converted/` and updates the manifest.

**Review page (faster than editing the workbook).** `python batch/review_page.py --ac 190` writes `data/2024/review/190_review.html`, one
self-contained file (the scan crops are embedded; nothing is uploaded): the rows the extractor flagged, most doubtful first, each
with its scan crop and editable cells, the plain OCR reading under any cell the solver changed, and a table at the top of every
candidate column and NOTA against the official total that updates as you type. Press *Download corrections*, then
`python batch/apply_review.py corrections_190.json --accept` applies them to a copy of the workbook, re-checks it against the official
totals and, if every column matches, files it into `data/2024/converted/`. The page needs the workbook to have been made by the
current converter (it saves each row's position in a hidden `Row_Boxes` sheet).

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Layout

```
run_form20.py        launcher
src/form20/          imaging, grid, header, ocr, reader, textlayer, discover, validate, pipeline, export, __main__
config/candidates.csv
queue/               2024 work lists: to_convert, to_review, overrides, conversion ledger
batch/               build_queue.py, convert_queue.py (batch runner over the queue), verify_official.py, stage_verified.py, status reports,
                     review_pack.py, review_page.py, apply_review.py, recheck_reviewed.py, publish_converted.py
tessdata/            Tesseract models (English, Hindi, orientation)
data/input/          the three sample PDFs
data/output/         generated workbooks (+ review crops)
eval/compare.py      accuracy against a correct Excel
eval/text_layer_check.py  independent check against a PDF's embedded text layer
tests/               unit tests (synthetic data, no PDFs needed)
```
