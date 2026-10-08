# RULES.md

## Hard project rules (never break)
1. **No individual-level inference stored.** Parse names in memory, keep aggregates only.
2. **No fraud claims.** Anomalies are "statistical outliers".
3. **Every modeled value carries uncertainty or a "modeled" tag.**
4. **Never join booths across elections without the crosswalk.**
5. **Never publish booth-level demographic estimates when electors < 200 or parse quality < 0.9.**
6. **Respect source ToS, robots.txt, and API limits.** No login-wall scraping, no CAPTCHA bypass.
7. **Raw data is immutable.** Transformations write to `interim/` or `processed/`.
8. **No secrets in code or git.** Use env vars/secret manager.
9. **Compliance Mode must be honored** by every public-facing output.
10. **Reproducibility:** seeded randomness, pinned dependencies, config-driven thresholds.

## Coding standards
- Python 3.11+, type hints on public functions, docstrings (numpy style).
- Formatting: `black` + `ruff`; imports sorted; max function length ~60 lines.
- Pure functions for transforms; I/O at the edges. No global state.
- Validate with `pandera`/`pydantic` schemas at every module boundary.
- Logging via `logging` (structured); no `print` in library code.
- Geo: always check `gdf.crs`; reproject explicitly; never compute area/distance in EPSG:4326.
- Pandas: no chained assignment, use `.loc`; prefer vectorized ops; parquet over CSV.
- Tests: `pytest`; unit tests on parsers using small fixture PDFs; property tests for crosswalk invariants (sum of splits ≈ 1); golden tests for swing math.
- Commits: conventional commits; PRs need passing tests and updated docs.

## Data-quality gates (CI)
- Totals reconcile (see DATA_SOURCES.md).
- Schema checks pass.
- No booth centroid outside AC polygon without a flag.
- Anomaly model rerun with the same seed gives identical flags.

## Naming
- Tables: `snake_case`; columns: `snake_case`; party groups in `UPPER_SNAKE`.
- Config keys flat, documented in `configs/README.md`.

## AI assistant rules
- Read `brain/` first. Propose changes to docs when changing design.
- When uncertain about a data fact (booth counts, URLs, delimitation), say so and mark `TODO(verify)`.
- Do not generate code that scrapes protected endpoints or evades access controls.
- **Report rule:** new data extends existing workbook sheets as new columns — never add a new sheet for new/extra data.
- **Changelog discipline:** every code/data change updates `brain/CHANGELOG.md` (newest first) **and** the relevant `brain/` file(s) in the same sitting (e.g. parser fix → `DATA_SOURCES.md` + `TASKS.md`).
- **README upkeep:** root + every folder README (`README.md` at root, `Scripts/`, `configs/`, `data/`, `output/`) describe current contents and rules. Update the affected README whenever files move, new outputs appear, or folder rules change.
- **No corrupt names:** never write an `.xlsx` whose candidate/booth names are legacy-font gibberish — skip (`LEGACY_SKIP`) and report instead. Mirrored-English names ARE fixable (unmirror) — reconverting those files is approved.
- **Never delete data files:** PDFs, `.xls`/`.xlsx` sources and generated sidecars are never deleted by scripts or cleanup. Stale quarantines (`.REVIEW.xlsx`) may only go away by being replaced through a fresh run. Git history is the safety net, not an excuse.
