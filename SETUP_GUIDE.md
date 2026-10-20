# UPBI Setup Guide: run the whole platform on your computer

UP Booth Intelligence: Uttar Pradesh election insights

- **Date:** 20 October 2026
- **For:** Anyone who has to run the UPBI platform on their own computer. No programming needed: you copy and paste the commands
- **Tested on:** Windows 11, Python 3.13.5, Node.js 20.20.2, in a fresh Python environment on a clean copy of the repository
- **Status:** Working draft. macOS and Linux commands are included but were not tested

**This guide covers**

- Three ways to run it (Insights only: about 10 minutes; a small booth-dashboard slice: 10 to 15; the whole platform: 30 to 45) and which one to choose
- Step-by-step setup with what you should see after each step
- How to build the booth database and start the booth dashboard
- Checks that everything works, everyday use, and a troubleshooting table

## 1. Choose your path

UPBI (UP Booth Intelligence) has two parts. **Insights** puts all parties side by side for all 403 assembly seats and needs only precomputed result files. The **Booth dashboard** shows every polling booth from one party's side at a time (a party picker) and needs a 1.1 GB booth database that you build once from the raw booth sheets. Pick the path that matches what you need to see.

| Path | What you get | What you need | Time | Choose it when |
|---|---|---|---|---|
| **A. Insights from the zip** | The Insights website: nine tabs, a page for every seat, the what-if calculator. The booth dashboard link says its database is not included | `UPBI_local_package.zip`, Python, Node.js | About 10 minutes | You only want to look at Insights, or want the fastest start |
| **B. Everything from the repository** | Insights **and** the booth dashboard with the party picker, built from the raw booth sheets (169,460 booths) | The repository, Python, Node.js, Git; about 6 GB of disk; 8 GB of free memory for one step | About 30 to 45 minutes (12 to 25 of them an unattended build) | You want the whole platform |
| **C. Booth dashboard on a small slice** | Everything in B, but the booth database holds only Agra's nine constituencies | Same as B | About 10 to 15 minutes | You want to try the booth dashboard quickly before the long build |

> **Note:** Paths B and C use the repository on GitHub (branch `form20-extraction`). If you cannot reach it, use path A.

## 2. Before you start

| Tool | Version | Get it | Needed for |
|---|---|---|---|
| Python | 3.10 or newer (tested with 3.13.5) | https://www.python.org/downloads/ (tick "Add python.exe to PATH"), or `winget install Python.Python.3.13` | All paths |
| Node.js | 20 LTS or newer (tested with 20.20.2) | https://nodejs.org/ (LTS), or `winget install OpenJS.NodeJS.LTS` | All paths |
| Git | Any recent version | https://git-scm.com/downloads | Paths B and C |
| A browser | Chrome, Edge or Firefox | Already installed on most computers | All paths |

| Resource | Path A | Paths B and C | Why |
|---|---|---|---|
| Disk | About 0.5 GB | About 6 GB free (the repository with its raw sheets is about 2 GB; the booth database 1.1 GB; packages about 1 GB) | The raw election sheets are part of the repository |
| Memory | 2 GB | 8 GB free for the booth workbook step (it peaked at about 6 GB); 2 GB otherwise | Saving a 94 MB workbook with 429,000 booth rows |
| Internet | For the first install only | For the first install and the clone only | Packages and code are downloaded once |

**On Windows** use PowerShell and run the commands exactly as written. **On macOS or Linux** the commands are the same, except: write `.venv/bin/python` instead of `.\.venv\Scripts\python.exe`, use `./run_api.sh` and `./run_web.sh` instead of the `powershell ... run_api.ps1` lines (run `chmod +x run_api.sh run_web.sh` once), and use `/` instead of `\` in paths. Everything stays on your computer; no account or secret key is needed.

## 3. Get the code

### 3.1 Path A: unzip

Unzip `UPBI_local_package.zip` to a short folder such as `C:\UPBI` (avoid very long paths). Open PowerShell in that folder and go to Section 5. Skip Section 4: the start script installs what the API needs. The package also contains `README_SETUP.md`, a one-page version of Path A.

### 3.2 Paths B and C: clone the repository

```
git clone https://github.com/Rdhobe/booth-analysis-report.git
cd booth-analysis-report
git checkout form20-extraction
```

The clone is large (about 2 GB) because the raw election sheets are in it. `form20-extraction` is the branch that holds this platform; if you were told it has been merged, stay on `main`. The folder `Shakkti_Form20_Extraction` and the loose scripts and images in the top folder belong to a separate data-conversion project and can be ignored.

Check that the result files the website reads are there. Every path in this list must exist:

```
server/insights_data/ac_insights.json         server/insights_data/model_card.json
server/insights_data/extra_insights.json      server/insights_data/extra_model_card.json
server/insights_data/simulator_inputs.json    server/insights_data/booth_segments.json
output/ml/booth_segments.json                 configs/regions_up.json
```

If one is missing, the matching part of the website says it is unavailable; Section 9 rebuilds them.

## 4. Install the packages (paths B and C)

From the top folder of the repository:

```
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt -r requirements_models.txt
```

This creates a private Python environment in `.venv` and installs about 60 packages (FastAPI, pandas, scikit-learn and others). It took 84 seconds on the test machine. Check it:

```
.\.venv\Scripts\python.exe -c "import fastapi, sklearn, openpyxl, xlrd; print('ok')"
```

It should print `ok`.

> **Note:** Do **not** install the repository's top-level `requirements.txt`. It is for the PDF and OCR work (it includes PyTorch and EasyOCR, several GB) and nothing here needs it.

## 5. Start the API and the website

Open **two** PowerShell windows in the top folder (the folder that contains `run_api.ps1`). The first run of each script installs what it needs, so it takes longer.

#### Window 1: the API

```
powershell -ExecutionPolicy Bypass -File .\run_api.ps1
```

It ends with a line like `Uvicorn running on http://127.0.0.1:8000`. Leave the window open. Until the booth database exists (Section 6) it also prints "warmup skipped (store not built yet?)": that is normal. Check it in a browser: `http://127.0.0.1:8000/api/insights/meta` shows a block of text starting `{"data_version":`.

#### Window 2: the website

```
powershell -ExecutionPolicy Bypass -File .\run_web.ps1
```

The first run installs the website's packages and builds it (one to three minutes). It ends with `Ready`. Leave the window open. Then open **http://localhost:3000**: it goes straight to the Insights page.

#### What you should see (Insights)

| Address | What you should see |
|---|---|
| `http://localhost:3000/insights` | Overview: "9.2 Cr" votes polled, "403 seats", "56.8%" turnout, then the share-of-votes bars |
| `.../insights?tab=ac&ac=86` | Etmadpur, badge "Type 1: BJP-led stronghold", "Within the usual spread", five look-alikes starting with Hathras |
| `.../insights?tab=whatif` | "What if the vote moved?". With every slider at zero the first table row shows **273** BJP-led seats. Move "Whole state, BJP-led (NDA)" to +5 and "Whole state, SP-led" to -5: the BJP-led count rises to about 361 |
| `.../insights?tab=watch` | Four band cards (Highest 41, High 60, Moderate 101, Lower 201) and a ranked list of seats |
| `.../insights?tab=turnout`, `?tab=alliances` | A chart of 403 dots; four alliance estimates with intervals |
| `.../insights?tab=types`, `?tab=surprises`, `?tab=method` | Four type cards (100, 116, 157, 30 seats); 20 flagged seats; data checks and test results |

Path A ends here. The "Booth dashboard" link in the header shows a plain message that the booth database is not available; that is expected.

## 6. Build the booth database (paths B and C)

### 6.1 What this step does

The booth dashboard reads one file, `output/servedb.sqlite`, that holds every booth's results. It is built from the raw sheets in `data/2017`, `data/2019` and `data/2022`, the 2024 Form 20 workbooks in `data/2024/converted`, and a few CSV files. It is built in two steps, then a third small step computes each booth's share, opponent and zone for BJP, SP, BSP and INC (the party picker). All commands run from the top folder, and the raw files are only read.

### 6.2 Path B: the full database

> **Info:** The build keeps the 2024 booth results of the 142 seats whose Form 20 workbook was verified against the official totals and has not changed since (Section 6.6). If you edit or replace any workbook in `data/2024/converted`, run the four model commands in Section 9 first (about 5 minutes): they re-check the workbooks in your copy.

```
.\.venv\Scripts\python.exe -m Scripts.report.build_state_report --ac24-dir data/2024/converted --ac24-verified-json output/ml/booth_segments.json
.\.venv\Scripts\python.exe -m Scripts.serve.build_servedb
```

| Command | Time (test machine) | What it writes |
|---|---|---|
| `build_state_report` | 9 to 17 minutes; peak memory about 6 GB | `data/processed/state_*.csv` (the booths and their votes) and `output/up_booth_report.xlsx` (94 MB). Both are generated and git-ignored |
| `build_servedb` | 4 to 7 minutes | `output/servedb.sqlite` (1.1 GB), including the party table (about one minute of it) |

Run them in this order, one after the other. While they run you will see a long stream of `INFO:` lines. **In PowerShell these lines appear in red with the words `NativeCommandError`. That is only how PowerShell shows messages from Python; it is not an error.** Success looks like this:

```
wrote ...\output\up_booth_report.xlsx zones={...} save=... total=...
...
INFO: BUILD COMPLETE counts={'booth_row': ..., 'booth_election': ..., 'vote': ..., ... 'booth_party': ...} total=...
```

### 6.3 Path C: the small slice (Agra only)

```
.\.venv\Scripts\python.exe -m Scripts.report.build_state_report --districts Agra --ac24-dir data/2024/converted --ac24-verified-json output/ml/booth_segments.json
.\.venv\Scripts\python.exe -m Scripts.serve.build_servedb --districts Agra
```

This takes about 20 seconds and writes a 26 MB database with Agra's nine constituencies (numbers 86 to 94) and 3,896 booths. Use it to try the booth dashboard; run Section 6.2 later for the whole state. A slice can be replaced by the full build at any time: the second command deletes and rewrites `output/servedb.sqlite`.

### 6.4 Restart the API

The API reads the database when it starts. Press Ctrl+C in Window 1 and run the `run_api.ps1` line again. It takes about 30 seconds to start with the full database because it prepares the seat counts. Check it:

```
http://127.0.0.1:8000/api/meta
```

It should show `"party_view": true`, `"parties": ["BJP", "SP", "BSP", "INC"]` and, under `counts`, `"booth_row"` of about 168,000 to 169,500 (the exact number depends on how many 2024 workbooks your copy holds) for the full build (3,896 for the slice).

### 6.5 What you should see (booth dashboard)

| Address | What you should see |
|---|---|
| `http://localhost:3000/booths` | "Choose a party" with four equal buttons: BJP, BSP, INC, SP. No party is preselected and no numbers are shown yet |
| Click **SP** | The address becomes `/booths?party=SP`. Cards for "SP AC Leads in UP" and the SP's average vote share, five seat zones and five booth zones, a trajectory chart. Click **BJP** in the header: every party-dependent number changes |
| `.../ac/199?party=SP` (full build) | Jaswantnagar (Etawah): Overview, Booths, Past Elections. In Booths, one row per booth with SP%, Opp%, differences and a zone. Switch to BJP: the same booths are mostly Difficult instead of Safe |
| `.../ac/88?party=SP` (works in the slice too) | Agra South: the Booths tab with the party's columns, and "BJP" as the opponent |
| `.../zone/Safe?party=BJP` | The constituencies in the Safe zone for the BJP, with the share and change |

### 6.6 About the 2024 booth results

The 2024 booth figures come from the Form 20 workbooks (PDF-to-Excel conversions). Only seats whose workbook was **verified against the official totals** are used, and only if the workbook is **unchanged since it was verified** (each one is fingerprinted in `output/ml/booth_segments.json`). A workbook that has been replaced or edited is skipped, never trusted. The build prints a line such as `2024 booths: N verified workbooks kept, M skipped`; on a copy made from the repository as it stands, it reads `142 verified workbooks kept, 0 skipped`: the repository holds exactly the 142 verified workbooks and each matches its recorded fingerprint. Seats without 2024 booth results still show their official 2024 seat totals; their booth rows simply have no 2024 figure.

## 7. Check that everything works

The automated tests need no running servers:

```
.\.venv\Scripts\python.exe -m pytest server Scripts\ml -q
```

Expected: **no failures**. On a fresh copy where the models and the booth database have been built, all **111 tests pass, none skipped**. Before anything is built, some tests are skipped on purpose because they need generated files (15 in our test); none fail.

With both servers running, open the addresses in Sections 5 and 6.5. If you want a single quick check of the whole platform, the list below is enough:

1. `http://127.0.0.1:8000/api/insights/meta` shows a data version.
2. `http://localhost:3000/insights?tab=whatif` shows 273 BJP-led seats with the sliders at zero.
3. `http://localhost:3000/booths` asks for a party; after choosing SP it shows "SP AC Leads in UP".
4. Opening `http://localhost:3000/booths?party=XYZ` (a party that does not exist) goes back to the party choice instead of showing an error.

## 8. Everyday use

| To do this | Do this |
|---|---|
| Stop | Press Ctrl+C in each window |
| Start again | Run the same two `run_api.ps1` and `run_web.ps1` lines; the second time they start in seconds (the full booth database adds about 30 seconds to the API's start) |
| Use other ports (8000 or 3000 is taken) | `powershell -ExecutionPolicy Bypass -File .\run_api.ps1 -Port 8001` and `powershell -ExecutionPolicy Bypass -File .\run_web.ps1 -Port 3001 -ApiPort 8001` (the two must match) |
| Update to a newer version | `git pull`; if files under `web/` changed, delete the folder `web\.next` before running `run_web.ps1` so it rebuilds; if `Scripts/serve` changed, run Section 6 again |
| Hide forward-looking numbers (restriction periods) | Set `COMPLIANCE_MODE=on` before starting the API (PowerShell: `$env:COMPLIANCE_MODE = "on"`). The expected ranges, battleground list, watch score and what-if page are then removed on the server |
| Keep the site private | The scripts bind to `127.0.0.1`, so only your computer can open it. Do not put it on the internet without the upgrades in Section 11 |

| Setting | Meaning |
|---|---|
| `COMPLIANCE_MODE=on` | Removes forward-looking outputs on the server |
| `DB_PATH` | Path of the booth database if it is not `output/servedb.sqlite` |
| `API_KEY` | When set, every `/api` request needs it as the `X-API-Key` header. Unset means open local use |
| `UPBI_API_BASE` | Where the website finds the API (default `http://127.0.0.1:8000`; `run_web.ps1 -ApiPort` sets it) |
| `INSIGHTS_DIR` | A different folder of Insights result files |

## 9. Optional: rebuild the analysis models

You only need this if a result file listed in Section 3.2 is missing, or after new data is added. The models read the same raw sheets and CSV files. Run these in order from the top folder; each step needs the one before it:

```
.\.venv\Scripts\python.exe Scripts\ml\ac_booth_totals.py
.\.venv\Scripts\python.exe Scripts\ml\features_ext.py
.\.venv\Scripts\python.exe Scripts\ml\build_insights.py --export-server
.\.venv\Scripts\python.exe Scripts\ml\build_extra.py --export-server
```

| Step | Time | What it does |
|---|---|---|
| `ac_booth_totals.py` | About 4 minutes | Adds up the booth sheets to constituency level (turnout, electors); writes `data/processed/ac_booth_*.csv` |
| `features_ext.py` | About 5 seconds | Builds the extra features (turnout, Lok Sabha, candidates); writes `data/processed/ac_features_ext.csv` |
| `build_insights.py --export-server` | About 30 seconds | The three original models; writes `output/ml/` and copies the results into `server/insights_data/` |
| `build_extra.py --export-server` | About 10 seconds (up to 1.5 minutes with more 2024 workbooks) | The five additional models and the verified-booth list; writes `output/ml/` and `server/insights_data/` |

Restart the API afterwards. The models use a fixed random seed, so the same data gives the same numbers: in our clean-copy test the rebuilt results matched the shipped ones exactly; only the `data_version` fingerprint differed, because it also depends on the exact bytes of the input files. Never run `build_extra.py` with `--no-booths` together with `--export-server`: it would replace the booth results with an empty file.

## 10. Troubleshooting

| What you see | What to do |
|---|---|
| "python is not recognized" or "node is not recognized" | Install it, tick "Add python.exe to PATH" for Python, then open a **new** PowerShell window |
| "running scripts is disabled on this system" | Use the `powershell -ExecutionPolicy Bypass -File ...` form exactly as written |
| Red `NativeCommandError` text while a build runs | Normal: PowerShell shows Python's progress messages that way. Wait for `BUILD COMPLETE` or `wrote ...xlsx` |
| `No module named 'Scripts'` or `ModuleNotFoundError` | Run from the **top folder** of the repository and use the `-m Scripts.report...` form shown in Section 6; do not run those two scripts by double-clicking or from inside `Scripts` |
| The booth workbook step stops with a memory error, or the computer slows to a crawl | Close other programs (it needs about 6 GB free), or use Path C (the Agra slice) first |
| `pip install` fails or is very slow | Check the internet connection or company proxy; both pip and npm honour the usual proxy settings. Install the two files named in Section 4, not the top-level `requirements.txt` |
| The page says "API unreachable" | The API window is not running, or its port differs from the website's `-ApiPort`. Test `http://127.0.0.1:8000/api/insights/meta` |
| The booth pages say "The booth database is not available on this server" | `output/servedb.sqlite` does not exist yet (Section 6), or the API was not restarted after building it (Section 6.4) |
| `party must be one of ['BJP']` (the API refuses another party) | The database was built before the party picker existed. Run `.\.venv\Scripts\python.exe Scripts\serve\add_booth_party.py` (about a minute; stop the API first), then restart it |
| "Port already in use" | Close the other program, or use other ports (Section 8) |
| `npm ci` fails with an engine or version message | Install Node.js 20 LTS or newer |
| `npm` warns that Next.js 14.2.5 has a security vulnerability | Known. It matters only if the site is put on the internet; keep it on `127.0.0.1` (Section 11) |
| A warning about "wmic" or physical cores while a model builds | Harmless on Windows 11 |
| Booth names look like `,p vkj b0dk0 fou;` in some seats | Not a setup fault: those sheets store names in an old Hindi font encoding. English search does not find them there |
| A seat or two is missing from an older election's booth pages | Expected: seats whose party names could not be read in that election are left out, and the page says how many (Complete Guide, Section 5.3) |

## 11. What this setup does not include

- **Official seat counts in the booth dashboard.** It counts seats from converted booth sheets, which gives lower numbers than the official results for some elections (for 2017 it shows the BJP leading 248 of 330 counted seats, against 312 of 403 officially). Use Insights for official seat counts. The reasons are explained in the Complete Guide.
- **Complete booth coverage.** Booth results are read for 403 seats (2017), 376 (2019), 218 (2022) and, for 2024, only seats with a verified Form 20 workbook.
- **A map, login, Hindi labels, exports.** Not built yet.
- **Predictions.** None of the tools forecasts an election; they describe past results and let you try scenarios.
- **Internet use.** The setup is for your own computer. Before any public use: upgrade Next.js (version 14.2.5 has a published security advisory), set `API_KEY`, replace the API key that is written in the repository's top-level README, get a legal review (Section 126A of the Representation of the People Act), and move the 1.1 GB booth database to the server as a file.

The **UPBI Complete Guide** (PDF) describes every screen, every analysis tool and the data rules in detail.

## Appendix A. All the commands on one page

Windows PowerShell, from the top folder of the repository.

```
# once
git clone https://github.com/Rdhobe/booth-analysis-report.git
cd booth-analysis-report
git checkout form20-extraction
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt -r requirements_models.txt

# window 1                                                              # window 2
powershell -ExecutionPolicy Bypass -File .\run_api.ps1                  powershell -ExecutionPolicy Bypass -File .\run_web.ps1

# (only if you changed workbooks in data/2024/converted: first the four model commands of Section 9, about 5 minutes)

# booth database: full (12 to 25 minutes) ...
.\.venv\Scripts\python.exe -m Scripts.report.build_state_report --ac24-dir data/2024/converted --ac24-verified-json output/ml/booth_segments.json
.\.venv\Scripts\python.exe -m Scripts.serve.build_servedb
# ... or the Agra slice (about 20 seconds)
.\.venv\Scripts\python.exe -m Scripts.report.build_state_report --districts Agra --ac24-dir data/2024/converted --ac24-verified-json output/ml/booth_segments.json
.\.venv\Scripts\python.exe -m Scripts.serve.build_servedb --districts Agra
# then restart window 1

# tests
.\.venv\Scripts\python.exe -m pytest server Scripts\ml -q

# open
http://localhost:3000            (Insights)         http://localhost:3000/booths   (booth dashboard)
```

## Appendix B. Folder map

| Folder or file | What it is |
|---|---|
| `web/` | The website (Next.js): `app/insights` (Insights), `app/booths`, `app/zone`, `app/ac` (booth dashboard), `components/PartyPicker.jsx` (the party picker) |
| `server/` | The API (FastAPI): `app.py` (booth endpoints), `insights.py` and `insights_extra.py` (Insights), `insights_data/` (the result files), the API tests |
| `Scripts/ml/` | The analysis models and their build scripts |
| `Scripts/report/`, `Scripts/serve/` | Reading the booth sheets, building the booth database and the party table |
| `data/` | The raw election files (booth sheets, official results, voter-roll estimates); `data/processed/` is generated |
| `output/` | Generated files: `ml/` (model results), `servedb.sqlite` (booth database), `up_booth_report.xlsx` (booth workbook) |
| `configs/` | Model settings, constituency names, the draft region list |
| `brain/`, `server/DASHBOARD_LOGIC.md` | Project notes: model descriptions, change log, task list, the formula contract for every dashboard number |
| `run_api.ps1`, `run_web.ps1` (and `.sh`) | One-command start scripts |

