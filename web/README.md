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

Open http://localhost:3000. The FastAPI server must be running
(`server/README.md`) — pages proxy through `app/api/*`, which
attaches `X-API-Key` server-side from `UPBI_API_KEY`. The key never
reaches the browser. Images load directly from
`NEXT_PUBLIC_UPBI_API/assets` (public, no key).

## Pages

| Route | Content |
|---|---|
| `/` | Hero, seats/share KPIs, AC + booth zone cards, voter profile, religion panel (all from `/api/overview`) |
| `/zone/[zone]` | AC table with search + change-sort (`?e=&vs=` preserved from home links) |
| `/ac/[ac]` | Tabs: Overview (sexratio + top parties), Booths (filters, Results/Turnout/Religion-wise, drill-down drawer), Past Elections, Map placeholder |

## Deploy (Vercel)

Push `web/` (or the repo with Root Directory = `web`), then set env:
`UPBI_API_BASE` (e.g. `https://<you>.onrender.com`),
`UPBI_API_KEY`, `NEXT_PUBLIC_UPBI_API` (same base, for images).

## Notes

- No component library, no chart dependency — hand-rolled SVG/divs.
- Party logos hide themselves when the file is missing; add PNGs to
  `server/assets/parties/` and they appear with zero code changes.
- Value scales: shares/margins/turnout arrive as fractions (×100 to
  display); religion `*_percent_17` arrive 0–100; `null` = suppressed.
