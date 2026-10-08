# output — GENERATED REPORTS ONLY

Finished, human-readable workbooks built from `data/` by the Scripts.
Nothing here is an input to any pipeline.

| File | Built by | Contents |
|---|---|---|
| `agra_booth_report.xlsx` (+ dated variants if the main file was open in Excel) | `Scripts/output_booth_report.py` | Mahad-format Agra workbook: AC86–AC94 sheets (booth rows, shares, Voting.Diff, zones, conditional formatting), Booth_Votes, Zone_Counts, Methods_Zones |
| `booth_data.db` | `Scripts/build_store.py` | Merged SQLite store: `booth` (379k rows), `vote` (4.7M rows), `file_coverage`. Schema doubles as dashboard contract |
| `dashboard_data.json` | `Scripts/build_dashboard.py` | Compact bundle (districts, trends, Agra booths, grid) inlined into the HTML |
| `dashboard.html` | `Scripts/build_dashboard.py` | Self-contained analytics dashboard (no internet, no server — double-click to open): KPIs, schematic district map, SVG charts, Agra booth explorer, methods |

Rules: safe to delete everything here and regenerate. Never store inputs here. If Excel locks the main file during a rebuild, the builder saves a timestamped variant instead of crashing — pick up the newest.
