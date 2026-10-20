# output — GENERATED REPORTS ONLY

Finished, human-readable workbooks built from `data/` by the Scripts.
Nothing here is an input to any pipeline.

| File | Built by | Contents |
|---|---|---|
| `agra_booth_report.xlsx` (+ dated variants if the main file was open in Excel) | `Scripts/output_booth_report.py` | Mahad-format Agra workbook: AC86–AC94 sheets (booth rows, shares, Voting.Diff, zones, conditional formatting), Booth_Votes, Zone_Counts, Methods_Zones |
| `booth_data.db` | `Scripts/build_store.py` | Merged SQLite store: `booth` (379k rows), `vote` (4.7M rows), `file_coverage`. Schema doubles as dashboard contract |
| `dashboard_data.json` | `Scripts/build_dashboard.py` | Compact bundle (districts, trends, Agra booths, grid) inlined into the HTML |
| `dashboard.html` | `Scripts/build_dashboard.py` | Self-contained analytics dashboard (no internet, no server — double-click to open): KPIs, schematic district map, SVG charts, Agra booth explorer, methods |
| `ml/ac_insights.json` | `Scripts/ml/build_insights.py` | Per-AC types, look-alikes, surprise reading, expected range, history; statewide overview and district table |
| `ml/model_card.json` | `Scripts/ml/build_insights.py` | Input file hashes, data checks, k selection, injected-anomaly test, error bands, learned-vs-baseline, limits |
| `ml/extra_insights.json` | `Scripts/ml/build_extra.py` | Per seat: watch score, expected turnout and gap, booth availability; watch-score backtest; alliance estimates |
| `ml/simulator_inputs.json` | `Scripts/ml/build_extra.py` | What-if simulator: 2022 shares per seat, regions, presets, hindcast evidence |
| `ml/booth_segments.json` | `Scripts/ml/build_extra.py` | 2024 booth segments for seats whose Form 20 workbook matches the official totals |
| `ml/extra_model_card.json` | `Scripts/ml/build_extra.py` | Settings, backtests and limits of the additional models |
| `ml/ac_typology.joblib` | `Scripts/ml/build_insights.py` | Fitted scaler + PCA + k-means (a few KB) |
| `ml/insights_demo.html` | `Scripts/ml/build_demo_page.py` | Single-file Insights UI (data inlined; double-click to open) |
| `ml/features_ext_report.json` | `Scripts/ml/features_ext.py` | Coverage and checks for the extra AC features (turnout, 2019 fronts vs official seat totals, incumbency) |
| `ml/backtest_ext_report.json`, `.md` | `Scripts/ml/backtest_ext.py` | Forward test of simple rules vs learned models, and the cross-section check |

Rules: safe to delete everything here and regenerate. Never store inputs here. If Excel locks the main file during a rebuild, the builder saves a timestamped variant instead of crashing — pick up the newest.
