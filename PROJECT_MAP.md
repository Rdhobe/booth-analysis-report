# Project map

One page: what is where. For setup, see [SETUP_GUIDE.md](SETUP_GUIDE.md).

## Start here

| I want to | Open |
|---|---|
| Run the platform on my computer | [SETUP_GUIDE.md](SETUP_GUIDE.md) (three paths, every command, troubleshooting) |
| Understand what a dashboard number means | `server/DASHBOARD_LOGIC.md` (the formula behind every number) |
| Understand the analysis models | `brain/MODELS.md` |
| See what changed and what is open | `brain/CHANGELOG.md` and `brain/TASKS.md` |

## Folders

| Folder | What it holds |
|---|---|
| `web/` | **The dashboards' website (Next.js).** Insights (all parties): `app/insights`, `components/insights*.jsx`. Booth dashboard with the party picker: `app/booths`, `app/zone`, `app/ac`, `components/PartyPicker.jsx`. Shared: `components/`, `lib/` |
| `server/` | **The API (FastAPI).** `app.py` (booth endpoints), `insights.py` and `insights_extra.py` (Insights), `insights_data/` (precomputed Insights results), the API tests |
| `Scripts/ml/` | **The analysis models** and their build scripts: types, unusual results, expected range (`models.py`), watch score, turnout, alliances, what-if, booth segments (`models_extra.py`) |
| `Scripts/report/`, `Scripts/serve/` | **The booth database:** reading the booth sheets (`build_state_report.py`), building the database (`build_servedb.py`) and the party table (`booth_party.py`, `add_booth_party.py`) |
| `Scripts/ingest/` | Helpers for converting the 2024 Form 20 PDFs to Excel |
| `configs/` | Model settings (`ml_config.json`), constituency names and districts, the draft region list |
| `data/` | Raw election files: booth sheets 2017, 2019, 2022, official results, 2024 Form 20 (`PDF`, `EXCEL`, `converted`). `data/processed/` is generated |
| `output/` | Generated files: `ml/` (model results), `servedb.sqlite` (booth database), `up_booth_report.xlsx`, and the Word/PDF documents in `handoff/` and `status/` |
| `brain/` | Project notes: requirements, architecture, models, data sources, rules, change log, task list |
| `Shakkti_Form20_Extraction/` | **A separate project:** converting Form 20 PDFs to Excel. `src`, `batch`, `tests` are maintained; `scratch_archive/` holds old debugging scripts and images |
| `VoterEroll_Extractor_temp/` | A separate small project (voter-roll extractor) with its own git history |

## Files in the top folder

| File | What it is |
|---|---|
| `SETUP_GUIDE.md`, `README_SETUP.md` | How to run the platform; `README_SETUP.md` is the one-page version that ships in the Insights-only zip |
| `run_api.ps1`, `run_web.ps1` (and `.sh`) | One-command start scripts for the API and the website |
| `requirements_models.txt`, `requirements_ml.txt` | Python packages for the models, the booth database build and the tests |
| `requirements.txt` | Python packages for the PDF and OCR work (large: PyTorch, EasyOCR); not needed to run the platform |
| `requirements_election_extractor.txt` | A short package list (PyMuPDF, pytesseract, Pillow) for a separate PDF extractor tool |
| `README.md` | The original project readme |

## Generated, not committed

`data/processed/`, `output/servedb.sqlite`, `output/up_booth_report.xlsx` and the documents in `output/handoff/` and `output/status/` are
rebuilt from the raw data (commands in `SETUP_GUIDE.md`). They are git-ignored or left untracked on purpose.

## Conventions

- Keep the top folder clean. Scratch scripts and images go in `Shakkti_Form20_Extraction/scratch_archive/`, not in the top folder.
- Do not rename `web/`, `server/`, `Scripts/` or `configs/`: the run scripts, the Dockerfile, the tests and the guides use those paths.

## Known leftovers

- `server/assets/` still holds old party logos and portraits. No page loads them; the website is neutral by design.
- The top-level `README.md` contains an API key that was committed long ago. Replace that key before the repository is shared further.
