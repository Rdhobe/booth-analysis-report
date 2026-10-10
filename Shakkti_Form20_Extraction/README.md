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

* **Layouts supported:** English sheets with two id columns (serial, polling station) and Hindi
  sheets with one, 10 or more candidates, the five standard total columns. A different layout
  (extra columns, a different order) needs a small change in `pipeline.py` (`id_cols`) and, for the
  title block, `header.py`.
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

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Layout

```
run_form20.py        launcher
src/form20/          imaging, grid, header, ocr, validate, pipeline, export, __main__
config/candidates.csv
tessdata/            Tesseract models (English, Hindi, orientation)
data/input/          the three sample PDFs
data/output/         generated workbooks (+ review crops)
eval/compare.py      accuracy against a correct Excel
eval/text_layer_check.py  independent check against a PDF's embedded text layer
tests/               unit tests (synthetic data, no PDFs needed)
```
