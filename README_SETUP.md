# UPBI Insights: run it on your own computer

This folder lets you run the UPBI Insights website locally and look at the three Phase 1 models. It contains the website (`web/`),
the API (`server/`), the model results already computed (`server/insights_data/`), and the code to rebuild the models (`Scripts/ml/`).
The full report (models, outputs, pending work, detailed setup and troubleshooting) is the Word/PDF file that came with this folder.

Everything stays on your computer. The site is deliberately free of party, leader and company logos.

## What you need (once)

| Tool | Version | Get it |
|---|---|---|
| Python | 3.10 or newer (tested with 3.13) | https://www.python.org/downloads/ (tick "Add python.exe to PATH") |
| Node.js | 20 LTS or newer (tested with 20.20) | https://nodejs.org/ |
| A browser | Chrome, Edge or Firefox | |

About 500 MB of free disk space and an internet connection for the first install only.

## Run it (Windows)

Unzip the folder somewhere short, for example `C:\UPBI`. Open **two** PowerShell windows in that folder.

Window 1 (the API):

```
powershell -ExecutionPolicy Bypass -File .\run_api.ps1
```

Window 2 (the website; the first run takes about 2 minutes):

```
powershell -ExecutionPolicy Bypass -File .\run_web.ps1
```

Open **http://localhost:3000**. It opens the Insights page. Stop each window with Ctrl+C.

## Run it (macOS / Linux, not tested by us)

```
chmod +x run_api.sh run_web.sh
./run_api.sh          # window 1
./run_web.sh          # window 2
```

## Check that it works

- http://127.0.0.1:8000/api/insights/meta shows a block of JSON that starts with `{"data_version":...`.
- http://localhost:3000/insights?tab=ac&ac=86 shows **Etmadpur** with the badge "Type 1: BJP-led stronghold".
- http://localhost:3000/insights?tab=ac&ac=176 shows **Mohanlalganj** with a red "Strong outlier" badge.
- The Overview tab shows "9.2 Cr" votes polled, "403 seats" and "56.8%" turnout.

## Optional: rebuild the models and run the tests

```
.venv\Scripts\python.exe -m pip install -r requirements_models.txt
.venv\Scripts\python.exe Scripts\ml\build_insights.py            (about 25 seconds)
.venv\Scripts\python.exe -m pytest server\test_insights.py Scripts\ml\test_ml.py -q      (expect: 24 passed)
```

This reproduces the model numbers (4 types, 20 flagged seats, ranges) from the two CSV files in `data/`. It writes to `output/ml/`.
Do not use `--export-server` or `--quick` for the website's data: the rebuilt file has no turnout or data-cleaning sections
(those need the booth-sheet files, which are not in this folder), and some server tests expect them.

## If something goes wrong

| What you see | What to do |
|---|---|
| "python is not recognized" | Install Python and tick "Add python.exe to PATH", then open a new PowerShell window |
| "node is not recognized" | Install Node.js LTS, then open a new PowerShell window |
| Script is blocked from running | Use the `powershell -ExecutionPolicy Bypass -File ...` form shown above |
| Page says "API unreachable" | The API window is not running, or it uses a different port: `run_web.ps1 -ApiPort 8001` must match `run_api.ps1 -Port 8001` |
| "Port already in use" | Close the other program, or use other ports: `run_api.ps1 -Port 8001` and `run_web.ps1 -Port 3001 -ApiPort 8001` |
| "Booth dashboard" link shows "API unreachable ... store not found" | Expected. The booth database is not part of this folder; only the Insights pages work |
| `npm` warns that Next.js 14.2.5 has a security vulnerability | Known. It only matters if the site is put on the internet; keep it on localhost |
| A joblib "wmic" warning while rebuilding | Harmless on Windows 11 |
