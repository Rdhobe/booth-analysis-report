# web — UPBI Next.js frontend

Next.js 14 (App Router) dashboard. Same data contract as the temp
static UI, defined in `server/DASHBOARD_LOGIC.md`.

## Setup (external terminal — downloads ~300MB once)

```
cd web
cp .env.example .env.local   # then fill UPBI_API_KEY if the API sets one
npm install
npm run dev
```

Open http://localhost:3000 (it opens the all-parties Insights page). The FastAPI server must be running
(`server/README.md`) — pages proxy through `app/api/*`, which
attaches `X-API-Key` server-side from `UPBI_API_KEY`. The key never
reaches the browser. The UI shows no logos, portraits or other images (see Notes).

## Pages

| Route | Content |
|---|---|
| `/` | Redirects to `/insights` (the neutral, all-parties view) |
| `/booths` | Single-party (BJP) booth dashboard: seats/share KPIs, AC + booth zone cards, voter profile, religion panel (all from `/api/overview`). Needs the booth store (`servedb.sqlite`) |
| `/zone/[zone]` | AC table with search + change-sort (`?e=&vs=` preserved from the `/booths` links) |
| `/ac/[ac]` | Tabs: Overview (sexratio + top parties), Booths (filters, Results/Turnout/Religion-wise, drill-down drawer), Past Elections, Map placeholder |
| `/insights` | Phase 1 models: Overview (shares, seats, top constituencies, districts), Constituency (history, turnout and electors, type, look-alikes, unusual-result reading, expected range), Types, Unusual results, Method and checks (including the data-cleaning coverage). The Overview also shows turnout by election. Data from `/api/insights/*`; `?tab=ac&ac=86` is shareable |

## Deploy (Vercel)

Push `web/` (or the repo with Root Directory = `web`), then set env:
`UPBI_API_BASE` (e.g. `https://<you>.onrender.com`),
`UPBI_API_KEY`.

## Notes

- No component library, no chart dependency — hand-rolled SVG/divs.
- **Neutral by design.** No party, leader, company or other logos, portraits, slogans or greetings anywhere in the UI; the only name shown is the
  product's own plain-text title (`components/Header.jsx`). Chrome colours are neutral greys, chart colours (blue, orange, aqua) are an
  accessible palette and are not party colours, and religion and gender bars use one neutral colour so colour never encodes a community.
  Party names appear only as data labels. `server/assets/` still holds old logo and portrait files, but nothing in the UI loads them.
- The `/booths`, `/ac/[ac]` and `/zone/[zone]` pages are single-party (BJP) views and say so in a banner.
- Value scales: shares/margins/turnout arrive as fractions (×100 to
  display); religion `*_percent_17` arrive 0–100; `null` = suppressed.
