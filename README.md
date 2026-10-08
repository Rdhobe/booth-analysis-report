# Booth Analysis Report (UPBI working repo)

Booth-level election analysis for Uttar Pradesh. Start with `brain/`
(single source of truth — read it before changing anything).

## Folder map
| Folder | What lives here | Rule |
|---|---|---|
| `brain/` | Project docs: mission, PRD, architecture, models, tasks, changelog | read first; update with every change |
| `configs/` | `ac_format.json` (403 ACs), `data_format.json` (master schema), `output_format.json` (report spec), `agra_party_map_2024.csv` | versioned mappings; `TODO(verify)` where uncertain |
| `data/` | **INPUTS ONLY** — `2017/2019/2022/2024/` source PDFs + converted xlsx (same folder), reference CSVs, `processed/` pipeline CSVs | never write reports here |
| `output/` | **GENERATED REPORTS ONLY** — e.g. `agra_booth_report.xlsx` | never inputs; safe to delete + regenerate |
| `Scripts/` | All pipeline code (converters, Agra pipeline, report builders, OCR) | all `.py` lives here, nowhere else |
| `*.txt` (root) | Run logs (`bulk_convert_log*.txt`, `agra_run1.txt`) | append-only history |

## Main workflows
```powershell
# 0. First time only: dependencies (CPU-only; torch is ~2GB, needed for OCR)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 1. Convert 2024 Form-20 PDFs -> same-folder .xlsx (text extraction)
.\.venv\Scripts\python.exe Scripts\bulk_convert_form20.py --root "data/2024"
# 2. Retry only REVIEW/FAILED rows from the report (never reconverts done files)
.\.venv\Scripts\python.exe Scripts\retry_pending.py
# 3. Agra 4-election booth pipeline (Excel only) -> data/processed/agra_*.csv
.\.venv\Scripts\python.exe Scripts\agra_pipeline.py
# 4. Mahad-format Agra workbook -> output/agra_booth_report.xlsx
.\.venv\Scripts\python.exe Scripts\output_booth_report.py
```

## Conventions
- Booth key: `booth_uid = {election}-{ac:03d}-{ps:04d}{suffix}`; never join elections without `agra_crosswalk.csv`.
- Swings in percentage points; anomalies are `statistical_outlier` (never fraud); modeled values carry uncertainty.
- Name rule: Hindi/legacy-font names are kept as-is and flagged, never rewritten into corrupt text.
- Every change updates `brain/CHANGELOG.md` + relevant `brain/` docs + the affected folder README (see `brain/RULES.md`).


$env:API_KEY = "078fe56c8175c4e70c50e50ffa6fb941ecdec53771dfc42bc2038efd96098ae3"
.\.venv\Scripts\python.exe -m uvicorn server.app:app --app-dir . --port 8000
cloudflared tunnel --url http://localhost:8000