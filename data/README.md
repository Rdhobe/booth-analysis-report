# data — INPUT STORAGE ONLY

Nothing in this folder is generated. Sources + pipeline intermediates:

- `2017/`, `2019/`, `2022/`, `2024/` — per-district source PDFs **and** their converted `.xlsx` sidecars (same folder, same basename). Status per file: `2024/convert_report.md` + `2024/bulk_convert_report.csv`.
- `processed/` — pipeline CSVs (`agra_*.csv`): facts, booths, crosswalk, swings, anomalies, coverage. Rebuilt by `Scripts/agra_pipeline.py`.
- Top-level `*.csv` / `*.xlsx` / `*.twbx` — reference datasets (LS-2024 results etc.), read-only inputs.

Rules: never write reports here (they go to `output/`); raw files are immutable — transforms write beside them (xlsx sidecar) or to `processed/`. Do not redistribute raw roll data (see `brain/SECURITY.md`).
