# BRAIN.md: Project Memory

## 1. Mission
Build an end-to-end electoral intelligence engine for **Uttar Pradesh** that works down to the **polling-booth level**. It blends:
1. Historical booth results (Form 20)
2. Geographic boundaries (booth/AC/district)
3. Modeled micro-demographics (from electoral rolls + Census)
4. Live sentiment streams

It surfaces behavioral shifts and statistical anomalies on an interactive map.

## 2. Scale facts (verify before relying)
- 403 Assembly Constituencies (ACs), 80 Lok Sabha seats (PCs), ~1.7 lakh polling stations. Check the latest count on the CEO UP site.
- Electoral roll PDFs are published per part (booth) per AC, mostly in Hindi.

## 3. Pillars
1. **Retrospective:** booth-level results, swing, turnout, margin, NOTA, volatility.
2. **Geospatial:** every booth is a point (and where possible a polygon) with a stable ID.
3. **Demographic (modeled):** aggregated, uncertainty-aware estimates only.
4. **Sentiment (live):** multilingual NLP, target-aware, normalized to a baseline.
5. **Anomaly:** robust statistical outlier detection relative to the local trend.
6. **Dashboard:** Streamlit + Folium/Plotly.

## 4. Key decisions (ADR log)
| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | Canonical key is `booth_uid` from a **crosswalk**, not raw part number | Booths are split, merged and renumbered between elections; naive joins give wrong swings |
| D2 | Booth polygons are **approximated** (Voronoi/Thiessen from geocoded points, clipped to AC) unless official polygons are obtained | No public statewide booth-boundary dataset exists |
| D3 | Caste composition is a **modeled estimate** with confidence bands, aggregated per booth, never stored per individual | ECI rolls carry no caste; ethics and legal exposure |
| D4 | Live sentiment is aggregated at **AC/block/ward tier by default**; booth tier only where geotag density allows | Geotagged posts are ~1-2% of volume, so booth-level sentiment is mostly sparse noise |
| D5 | Sentiment = **stance toward a target (party/candidate/issue)**, not generic polarity | Generic polarity does not equal vote intent |
| D6 | Anomaly output is called **"statistical outlier"**, never "fraud/rigging" | Outliers have many benign causes (migration, caste-cluster voting, small N) |
| D7 | Anomaly features are **residualized against AC-level trend** and **shrunk for small booths** | Otherwise IsolationForest just flags small or extreme-region booths |
| D8 | Parse names in memory, store only aggregates | Privacy; see SECURITY.md |

## 5. Corrections to the original assumptions
- **`naampy` infers gender from Indian names. It does not infer caste.** Caste estimation needs a custom surname-to-category lexicon (see MODELS.md). Gender is already in the rolls, so naampy is only a validation tool (e.g. checking OCR/parse quality).
- **Lok Dhaba (TCPD) is constituency-level**, not booth-level. Booth-level data comes from Form 20 PDFs (CEO UP / ECI) or community-digitized archives. Lok Dhaba supplies candidate metadata and AC-level validation totals.
- **ECI roll PDFs are often image-scanned or use legacy fonts.** `pdfplumber` alone may return garbage, so plan for OCR (Tesseract with `hin+eng`, or a cloud OCR) and a verification pass.
- **Census 2011 SC/ST data is at village/ward level**, not booth level, so booth-to-village mapping is a spatial/fuzzy-name join with its own error.

## 6. Open questions
- Q1: Which elections are in scope first? (Suggest 2017, 2022 UP-VS; 2019, 2024 LS)
- Q2: Is any official booth lat/long (e.g. BLO app, ECI "polling station locator") accessible for scraping under the terms of use?
- Q3: Which live sources? X/Twitter API (paid), Facebook (restricted), YouTube comments, news RSS, Telegram public channels, field-agent app?
- Q4: Internal tool or public-facing? (Changes the legal posture; see SECURITY.md)
- Q5: Compute budget for transformer inference (GPU vs CPU batch).

## 7. Conventions
- Python 3.11+, type hints, `ruff` + `black`, `pytest`.
- CRS: store EPSG:4326; compute distances/areas in EPSG:32644 (UTM 44N, covers most of UP; use 32643 for the far west if needed).
- All swings in **percentage points** of valid votes; document denominators.
