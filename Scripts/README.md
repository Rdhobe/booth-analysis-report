# Scripts

All Python code lives here (nothing outside this folder).

| Script | Job | Input | Output |
|---|---|---|---|
| `convert_form20.py` | Single-file Form-20 PDF → same-folder `.xlsx` (text extraction, not OCR) | one PDF | same-folder `.xlsx` |
| `bulk_convert_form20.py` | Batch converter: table extraction, dynamic candidate counts, row-sum + EVM validation, post-save check, `REVIEW` quarantine, `LEGACY_SKIP` (Hindi legacy fonts), `SCANNED` (image PDFs), `COMPLEX_SKIP` | `--root data/2024` | same-folder `.xlsx` + `bulk_convert_report.csv` |
| `retry_pending.py` | Reprocesses ONLY `REVIEW`/`FAILED` rows from the report; merges back; never touches finished files | report CSV | updated report CSV |
| `review47.py` | One-by-one diagnosis + safe retry of the 47 REVIEW files (S1 base, S2 None→0/Unknown, S3 trim, S4 trailer-order variant); blank rows never filled; `--dry-run --md data/2024/review47.md` for read-only review | report CSV (REVIEW rows) | fixed `.xlsx` + `data/2024/review47.md` |
| `build_store.py` | Merges every convertible Excel file into `output/booth_data.db` (SQLite: booth/vote/file_coverage). Resumable via progress file; district spellings canonicalized; null-AC booths filename-keyed | `configs/data_files.json` + sources | `output/booth_data.db` |
| `build_dashboard.py` | Bundle + single-file `output/dashboard.html` (data inlined, no CDN/server): KPIs, schematic tile-grid map, SVG charts, Agra booth explorer, methods | `output/booth_data.db` | `output/dashboard_data.json` + `output/dashboard.html` |
| `fix_names_reference.py` | Fixes mirrored/word-order candidate names against `data/lok-sabha-elections-2024-results.csv` (exact + full-reverse + token-set match; `--apply` writes, default dry-run). Untouched: hybrids with party fragments, legacy codes | converted xlsx | corrected xlsx + report |
| `agra_pipeline.py` | Agra 4-election booth pipeline (Excel only): ingest → crosswalk → swings → MAD-z anomalies | `data/20xx/Agra*` + `configs/agra_party_map_2024.csv` | `data/processed/agra_*.csv` + `agra_analysis.xlsx` |
| `agra_compare.py` | SUPERSEDED by `output_booth_report.py` (kept for history) | — | `data/processed/agra_comparison.xlsx` |
| `ocr_form20.py` | PAUSED: scanned Hindi Form-20 → xlsx via EasyOCR (EasyOCR benchmarked OK post-rotation; digit accuracy work pending) | scanned PDF + `--ac` (see `configs/ac_format.json`) | same-folder `.xlsx` |
| `ocr_english.py` | English-only SCANNED batch: language classify (Hindi → separate list, never converted), per-page rotation auto-detect, grid OCR + validation; resume via `data/2024/ocr_english_report.csv`, `--retry-failed` reruns only failures | SCANNED rows of bulk report | same-folder `.xlsx` / `.OCR_REVIEW.xlsx` + `ocr_hindi_files.md` |
| `rename_converted.py` | Renames converted 2024 `.xlsx` to `<AC>.xlsx` (2017 pattern); PDFs untouched; updates `data_files.json` + bulk report refs; `--apply` executes, `--csv-only` refreshes CSV | `configs/data_files.json` (converted + known AC) | renamed `.xlsx` + `data/2024/rename_report.md` |
| `output_booth_report.py` | Maps pipeline CSVs into the Mahad-format workbook
(`configs/output_format.json`): single All_ACs sheet (AC + Party B cols), zones Safe/Favorable/Battlefield/Difficult, conditional formatting | `data/processed/agra_*.csv` |
`output/agra_booth_report.xlsx` |
| `build_state_report.py` | Statewide 403-AC booth workbook: ECI ingest (both geometries, M/F/O turnout) + 2024 segment parties/electors/SEG-CHECK + uprolls2017 modeled demographics; trailing All_ACs columns, zones, sheets never added | `data/20xx` + segment CSV + `uprolls2017.csv` | `data/processed/state_*.csv` + `output/up_booth_report.xlsx` |
| `build_servedb.py` | Serving store: state CSVs + report workbook + ECI 2024 segment file → ONE indexed SQLite (`booth_row`, `booth_election`, `vote`, `ac_summary`, `ac_party`, `ac_zones`, `seg2024` official 2024 totals, `coverage`, FTS). FastAPI reads it read-only; `--districts` pilot slice | state CSVs + segment CSV + `output/up_booth_report.xlsx` | `output/servedb.sqlite` (or `--db`) |
| `add_zone_share_indexes.py` | One-off migration: adds `(zone, aYYYY)` indexes to an existing `servedb.sqlite` (no rebuild; re-runnable) | existing DB | same DB, faster top-booth queries |

Conventions: Python 3.11+, type hints, no secrets in code, `logging` (no `print` in library code), seeded/deterministic runs. One-off probe scripts are deleted after use — only the files above are kept.
