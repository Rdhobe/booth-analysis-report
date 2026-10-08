# DESIGN.md: Dashboard & UX

## 1. Layout (Streamlit)
- **Sidebar:** election cycle(s), party group, AC / district, metric (swing, turnout Δ, sentiment divergence, anomaly score, modeled composition), time window (live), geography tier, **Compliance Mode** indicator.
- **Main (tabs):** `Map` | `Booth detail` | `AC trends` | `Anomalies` | `Methods & caveats`
- **Header strip:** KPIs (booths loaded, % validated, last sentiment update, n events).

## 2. Map (Folium via streamlit-folium; Plotly for charts)
- Base: light neutral tiles (CartoDB positron) so colors read well.
- Layers (toggle): booth cells (choropleth), booth points (cluster), AC boundaries, anomaly markers.
- **Zoom behavior:** state → AC choropleth; AC → booth cells; hover shows tooltip; click opens drill-down.
- **Approximate geometry** (Voronoi) drawn with dashed outline and labeled "approximate".

### Color encoding
| Metric | Scale | Notes |
|---|---|---|
| Sentiment divergence | Diverging (blue ↔ white ↔ red), centered at 0, symmetric [−1,1] | Colorblind-safe pair; grey = n < n_min (insufficient data) |
| Swing (pp) | Diverging by party-group hue only when a single party selected | Legend states pp |
| Turnout Δ | Sequential | |
| Anomaly score | Sequential amber to dark red + marker for flagged | Label "statistical outlier" |
| Composition | Sequential, with hatch overlay when CI wide | Label "modeled estimate" |

Never use party colors for the sentiment-divergence scale (avoid implying partisanship in the scale itself).

## 3. Booth detail panel
- Header: AC, part no., name, geometry source, crosswalk confidence.
- Charts (Plotly): vote-share bars across cycles; turnout trend; sentiment sparkline with CI.
- Table: electors, female share, age bands, modeled composition with intervals.
- Anomaly card: score, rank in AC, top contributing features, "benign explanation" checklist.

## 4. Uncertainty & honesty principles
1. Every modeled number shows a CI or "modeled" tag.
2. Grey out when data insufficient. Never interpolate silently.
3. A "Methods & caveats" tab is one click away; tooltips link to it.
4. No language implying fraud, bias, or individual targeting.

## 5. Accessibility & performance
- WCAG AA contrast, colorblind-safe palettes, text alternatives for map KPIs (summary table).
- Lazy-load layers by zoom; simplify geometries; cache queries; paginate tables.
- Mobile: single-column, map-first, filters in expander.

## 6. Compliance Mode (UI)
When ON: hide live sentiment/opinion layers and any forward-looking numbers, show a banner "Opinion layers disabled during statutory restriction period". Controlled by a config schedule plus manual override (admin only).
