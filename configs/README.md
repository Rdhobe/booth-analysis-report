# configs

Versioned mappings and schemas (inputs to the pipelines, never outputs).

| File | Purpose |
|---|---|
| `ac_format.json` | All 403 UP assembly constituencies: `ac_no`, `ac_name`, `district`, `reserved_for`. Used by OCR/title parsing (`--ac`) and segment checks. |
| `data_format.json` | Master booth schema (`BoothIntelligenceMasterSchema`): booth_id, metadata, geospatial, demographics_estimated, historical_elections, real_time_sentiment, anomaly_flag. Target contract for future work. |
| `output_format.json` | Report workbook spec derived from `mahad report-abc.xlsx`: sheets, columns, formulas, zone rule, denominators, known unknowns. Implemented by `Scripts/output_booth_report.py`. |
| `agra_party_map_2024.csv` | Manual 2024 LS candidate→party map for Agra (`election_id,ac_no,candidate_name,party`; `*` = all ACs). Only BJP rows verified; rest `UNMAPPED` + `TODO(verify)` — needs ECI affiliate data before party-level 2024 swings widen. |
| `data_files.json` | File map of the whole `data/` tree by district + AC (built by `Scripts/build_filemap.py`): every PDF/xls source with its `.xlsx` sidecar or `"xlsx": "NOT FOUND"`, statuses (`converted`, `missing_xlsx`, `review`, `source-excel`), AC from title blocks (null + note when undecodable), `missing_districts` (`*Data not found*` folders). |
| `data_file_format.json` | Per-Excel-file structure map (built by `Scripts/build_formatmap.py`; PDFs untouched): layout (`eci-triplet` / `form20-xlsx`), per sheet dims + header/data rows, per column `{index, name, dtype}` where dtype is `text` (names/labels/parties) or `numbers` (counts/votes). 1,432 files; 1 unreadable (password-locked `2017/Farrukhabad/192.xls`). |

Rules: mappings are data — changes here go through the same changelog discipline (`brain/CHANGELOG.md`). Never guess affiliations; mark `TODO(verify)`.
