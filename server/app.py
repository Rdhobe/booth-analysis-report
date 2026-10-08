"""UPBI serving API (FastAPI, read-only SQLite, offline-safe).

Serves the prebuilt store (Scripts/build_servedb.py) + static frontend.
No database writes, no network calls, no CDN. Run:
  uvicorn app:app --host 127.0.0.1 --port 8000        (local)
  DB_PATH=/data/servedb.sqlite uvicorn app:app        (container)

Health: GET /api/meta
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = logging.getLogger("upbi")

try:
    from fastapi.responses import ORJSONResponse as JSONResponse
except ImportError:  # orjson optional
    from fastapi.responses import JSONResponse

HERE = Path(__file__).parent
DB_PATH = os.environ.get("DB_PATH", str(
    HERE.parent / "output" / "servedb.sqlite"))
API_KEY = os.environ.get("API_KEY", "")
PAGE_DEFAULT, PAGE_MAX = 100, 500

# Static store -> responses are immutable until rebuild (restart).
# Caches full-table scans (overview/vote rollups); point lookups
# (booths/booth/votes) stay live - they are already indexed ms queries.
_CACHE: dict = {}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key on /api/* when API_KEY is set.

    Unset API_KEY = open dev mode (localhost). Any shared/public
    deploy MUST set API_KEY. /docs, /swagger, /openapi.json, /assets
    and /api/meta (health checks) stay public; the data does not."""

    async def dispatch(self, request: Request, call_next):
        p = request.url.path
        if (API_KEY and p.startswith("/api/") and p != "/api/meta"):
            if request.headers.get("x-api-key", "") != API_KEY:
                return JSONResponse(
                    {"detail": "invalid or missing API key"}, 401)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not API_KEY:
        log.warning("API_KEY unset - /api/* is OPEN. Set API_KEY "
                    "for any shared or public deploy.")
    # Warm the per-election rollups once: every overview pair is
    # then composed from memory (store is immutable until restart).
    try:
        import time as _t
        t0 = _t.time()
        for e in ("VS2017", "LS2019", "VS2022", "LS2024"):
            _election_rollup(e)
        log.info("overview rollups warmed (%.1fs)", _t.time() - t0)
    except Exception as ex:
        log.warning("warmup skipped (store not built yet?): %s", ex)
    yield

# sort keys are validated against the real booth_row columns
# (see valid_cols()); aliases kept for the old UI param names.
SORT_ALIASES = {"avg": "avg_diff", "latest": "latest_diff"}

ROW_COLS = ("ac, ps, district, name, address, s2017, s2019, s2022, "
            "s2024, zone, avg_diff, latest_diff, party_b, "
            "a2017, b2017, d2017, a2019, b2019, d2019, "
            "a2022, b2022, d2022, a2024, b2024, d2024, "
            "e2017, m2017, f2017, o2017, t2017, to2017, "
            "e2019, m2019, f2019, o2019, t2019, to2019, "
            "e2022, m2022, f2022, o2022, t2022, to2022, "
            "e2024, m2024, f2024, o2024, t2024, to2024, "
            "ac_electors_2024")

app = FastAPI(title="UPBI booth API", version="0.1.0",
              default_response_class=JSONResponse,
              docs_url="/swagger", redoc_url="/redoc",
              lifespan=lifespan)
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
# Next.js frontend runs on another origin - allow it. Tighten for
# public deploys: set ALLOWED_ORIGINS="https://your-app.vercel.app".
_allowed = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed],
    allow_methods=["GET"],
    allow_headers=["*"])


def db() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise HTTPException(500, f"store not found: {DB_PATH} "
                                 "(run Scripts/build_servedb.py)")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True,
                          check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def meta_get(con: sqlite3.Connection, key: str, default=""):
    r = con.execute("SELECT value FROM meta WHERE key=?",
                    (key,)).fetchone()
    return r["value"] if r else default


_VALID_COLS: set[str] | None = None


def valid_cols() -> set[str]:
    """Real booth_row column names (sort whitelist; built once)."""
    global _VALID_COLS
    if _VALID_COLS is None:
        con = db()
        try:
            _VALID_COLS = {r[1] for r in con.execute(
                "PRAGMA table_info(booth_row)")}
        finally:
            con.close()
    return _VALID_COLS


@app.get("/api/meta")
def api_meta():
    import json
    if "meta" in _CACHE:
        return _CACHE["meta"]
    con = db()
    try:
        counts = {t: con.execute(f"SELECT COUNT(*) c FROM {t}")
                  .fetchone()["c"] for t in
                  ("booth_row", "booth_election", "vote",
                   "ac_summary", "coverage")}
        counts["acs"] = con.execute(
            "SELECT COUNT(DISTINCT ac) c FROM booth_row").fetchone()["c"]
        store_ok = all(counts.get(t, 0) > 0 for t in
                       ("booth_row", "booth_election", "vote",
                        "ac_summary", "coverage"))
        out = {"counts": counts,
                "store_ok": store_ok,
                "scope": meta_get(con, "scope", "unknown"),
                "is_slice": meta_get(con, "slice", "0") == "1",
                "built_at": meta_get(con, "built_at"),
                "elections": json.loads(meta_get(con, "elections",
                                                 "[]")),
                "demo_cols": json.loads(meta_get(con, "demo_cols",
                                                 "[]")),
                "compliance_mode": os.environ.get(
                    "COMPLIANCE_MODE", "off")}
        _CACHE["meta"] = out
        return out
    finally:
        con.close()


@app.get("/api/acs")
def api_acs(district: str = ""):
    ck = ("acs", district)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        q = ("SELECT ac, ac_name, district, election, booths, electors, "
             "polled, valid, nota, turnout_pct FROM ac_summary")
        args: list = []
        if district:
            q += " WHERE district = ?"
            args.append(district)
        q += " ORDER BY ac, election"
        rows = [dict(r) for r in con.execute(q, args)]
        zones = [dict(r) for r in con.execute(
            "SELECT ac, zone, n FROM ac_zones")]
        dists = [r["d"] for r in con.execute(
            "SELECT DISTINCT district d FROM ac_summary ORDER BY 1")]
        out = {"rows": rows, "zones": zones, "districts": dists}
        _CACHE[ck] = out
        return out
    finally:
        con.close()


@app.get("/api/booths")
def api_booths(
        ac: int | None = None,
        zone: str = "",
        q: str = "",
        party: str = "",
        sort: str = "ps",
        order: str = "asc",
        page: int = Query(1, ge=1),
        page_size: int = Query(PAGE_DEFAULT, ge=1, le=PAGE_MAX)):
    """Booth grid. Always scoped: requires ac or q (never full-table)."""
    if ac is None and not q.strip():
        raise HTTPException(400, "scope required: ?ac=<no> or ?q=<text>")
    col = sort if sort in valid_cols() else SORT_ALIASES.get(sort, "ps")
    if col not in valid_cols():
        col = "ps"
    direction = "DESC" if order.lower() == "desc" else "ASC"
    where, args = ["1=1"], []
    if ac is not None:
        where.append("r.ac = ?")
        args.append(ac)
    if zone:
        where.append("r.zone = ?")
        args.append(zone)
    if party:
        where.append("r.party_b = ?")
        args.append(party.upper())
    join = ""
    if q.strip():
        join = ("JOIN (SELECT rowid FROM booth_fts "
                "WHERE booth_fts MATCH ?) f ON f.rowid = r.rowid")
        args.append(q.strip() + "*")
    con = db()
    try:
        # Religion-wise columns live in booth_row but outside ROW_COLS -
        # include them so the group view and tooltips have values.
        base_cols = {c.strip() for c in ROW_COLS.split(",")}
        extra = sorted(valid_cols() - base_cols)
        sel = ROW_COLS + "".join(f', r."{c}"' for c in extra)
        base = f"FROM booth_row r {join} WHERE {' AND '.join(where)}"
        total = con.execute(f"SELECT COUNT(*) c {base}", args
                            ).fetchone()["c"]
        # NULL/empty serials sort last for ps; numeric-aware via CAST
        order_by = (f"CAST(r.ps AS INTEGER) {direction}, r.ps {direction}"
                    if col == "ps" else f'r."{col}" {direction}')
        cur = con.execute(
            f"SELECT {sel} {base} ORDER BY {order_by} "
            f"LIMIT ? OFFSET ?", args + [page_size, (page - 1)
                                         * page_size])
        rows = []
        for r in cur:
            d = dict(r)
            rows.append(d)
        return {"total": total, "page": page, "page_size": page_size,
                "rows": rows, "demo_cols": extra}
    finally:
        con.close()


@app.get("/api/booth/{ac}/{ps}")
def api_booth(ac: int, ps: str):
    con = db()
    try:
        demo_names = [c[1] for c in
                      con.execute("PRAGMA table_info(booth_row)")]
        extra = [c for c in demo_names
                 if c not in set(ROW_COLS.replace(" ", "").split(","))]
        r = con.execute(f"SELECT {ROW_COLS}"
                        + (", " + ", ".join(f'"{c}"' for c in extra)
                           if extra else "")
                        + " FROM booth_row WHERE ac=? AND ps=?",
                        (ac, ps)).fetchone()
        if not r:
            raise HTTPException(404, "booth not found")
        elec = [dict(x) for x in con.execute(
            "SELECT * FROM booth_election WHERE ac=? AND ps=? "
            "ORDER BY election", (ac, ps))]
        votes = {}
        for e in elec:
            votes[e["election"]] = [dict(x) for x in con.execute(
                "SELECT candidate, party, votes FROM vote "
                "WHERE booth_uid=? ORDER BY votes DESC LIMIT 15",
                (e["booth_uid"],))]
        return {"row": dict(r), "elections": elec, "votes": votes}
    finally:
        con.close()


import re as _re

_PARTY_ORDER = ["Safe", "Favorable", "Battlefield", "Difficult",
                "Data Not sufficient"]


def _norm_party(p):
    n = _re.sub(r"[^A-Z0-9]", "", (p or "").upper())
    # ECI spelling variants collapse to one key (display label keeps
    # the most-voted original spelling)
    if n.startswith("BHARATIYAJANATA"):
        return "BJP"
    if n.startswith("SAMAJWADI"):
        return "SP"
    if n.startswith("BAHUJANSAMAJ"):
        return "BSP"
    if n == "INC" or n.startswith("INDIANNATIONALCONGRESS"):
        return "INC"
    if n.startswith("APNADAL"):
        return "ADAL"
    if n.startswith("SUHELDEV") or n == "SBSP":
        return "SBSP"
    if n.startswith("RASHTRIYALOKDAL") or n == "RLD":
        return "RLD"
    return n


# ACs with fewer counted votes are noise (single-file fragments,
# candidate-name-as-party rows) - kept in totals, out of winners
# and best/worst picks. Documented in DASHBOARD_LOGIC.md.
MIN_VOTES = 2000


# Per-election vote rollups, cached in memory (store is immutable).
# One heavy join-scan per election, then every overview pair composes
# from these in ms. Warmed at startup (see lifespan).
_ROLL: dict = {}


def _election_rollup(e):
    if e in _ROLL:
        return _ROLL[e]
    con = db()
    try:
        if e == "LS2024":
            rows = [dict(r) for r in con.execute(
                "SELECT ac, party, SUM(votes) v FROM seg2024 "
                "GROUP BY ac, party")]
            nota = con.execute(
                "SELECT SUM(nota) FROM seg2024_ac").fetchone()[0] or 0
        else:
            rows = [dict(r) for r in con.execute(
                "SELECT b.ac, v.party, SUM(v.votes) v FROM vote v "
                "JOIN booth_election b ON v.booth_uid = b.booth_uid "
                "WHERE b.election=? GROUP BY b.ac, v.party", (e,))]
            nota = 0
        per_ac, labels, ac_tot = {}, {}, {}
        for r in rows:
            ac_tot[r["ac"]] = ac_tot.get(r["ac"], 0) + (r["v"] or 0)
            n = _norm_party(r["party"])
            if not n or n == "NOTA":
                continue  # counted in totals, never a winner/label
            key = (r["ac"], n)
            per_ac[key] = per_ac.get(key, 0) + (r["v"] or 0)
            lbl = (r["party"] or "").strip()
            if n not in labels:
                labels[n] = [lbl, r["v"] or 0]
            elif (r["v"] or 0) > labels[n][1]:
                labels[n] = [lbl, r["v"] or 0]
        ac_bjp, win = {}, {}
        for (ac, n), v in per_ac.items():
            if n == "BJP":
                ac_bjp[ac] = ac_bjp.get(ac, 0) + v
            if ac_tot.get(ac, 0) >= MIN_VOTES and (
                    ac not in win or v > win[ac][1]):
                win[ac] = (n, v)
        out = (per_ac, ac_tot, ac_bjp, win, labels, nota)
        _ROLL[e] = out
        return out
    finally:
        con.close()


@app.get("/api/overview")
def api_overview(election: str = "LS2024", vs: str = "VS2022"):
    """Homepage rollup for the selected election vs a comparison one.

    Seats = per-AC plurality winner (NOTA never wins; ACs with no
    usable votes are reported as gaps, not seats). VS years use booth
    sums; LS2024 uses official segment totals. Shares/zone/best-worst
    derive from the same rollups - see server/DASHBOARD_LOGIC.md."""
    elecs = ("VS2017", "LS2019", "VS2022", "LS2024")
    if election not in elecs or vs not in elecs:
        raise HTTPException(400, "election/vs must be one of %s"
                            % (elecs,))
    ck = ("overview", election, vs)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        _, tot_e, bjp_e, win_e, labels, nota_e = _election_rollup(
            election)
        _, tot_v, bjp_v, _, _, _ = _election_rollup(vs)
        tot_all_e = sum(tot_e.values()) + nota_e
        tot_all_v = sum(tot_v.values())
        bjp_all_e = sum(bjp_e.values())
        bjp_all_v = sum(bjp_v.values())

        wins = {}
        for ac, (n, _) in win_e.items():
            wins[n] = wins.get(n, 0) + 1
        majors = ("BJP", "SP", "BSP", "INC", "RLD", "ADAL", "SBSP")
        seats = [{"party": n if n in majors else labels.get(n, [n])[0],
                  "seats": s}
                 for n, s in sorted(wins.items(), key=lambda x: -x[1])]

        # AC zones: same cutoffs as booth zones, applied to the AC's
        # mean (avg_diff, latest_diff) over its booths. Stable across
        # elections; Data Not sufficient when the AC has no margins.
        def _ac_zone(avg, latest, n):
            if not n or avg is None:
                return "Data Not sufficient"
            if avg > 0.10 and (latest or 0) > 0:
                return "Safe"
            if avg < -0.10 and (latest or 0) < 0:
                return "Difficult"
            if (avg or 0) > 0 and (latest or 0) > 0:
                return "Favorable"
            return "Battlefield"

        ac_zone = {}
        for r in con.execute(
                "SELECT ac, AVG(avg_diff) a, AVG(latest_diff) l, "
                "COUNT(avg_diff) n FROM booth_row GROUP BY ac"):
            ac_zone[r["ac"]] = _ac_zone(r["a"], r["l"], r["n"])

        zones = []
        for z in _PARTY_ORDER:
            members = [a for a, zz in ac_zone.items() if zz == z]
            shr = [(a, bjp_e.get(a, 0) / tot_e[a])
                   for a in members if tot_e.get(a, 0) >= MIN_VOTES]
            shr.sort(key=lambda x: x[1])
            def acinfo(a):
                nm = con.execute(
                    "SELECT ac_name, district FROM ac_summary "
                    "WHERE ac=? LIMIT 1", (a,)).fetchone()
                return {"ac": a,
                        "ac_name": nm["ac_name"] if nm else "",
                        "district": nm["district"] if nm else "",
                        "share": round(100.0 * bjp_e.get(a, 0)
                                       / tot_e[a], 1) if tot_e.get(a)
                        else None,
                        "share_vs":
                        round(100.0 * bjp_v.get(a, 0) / tot_v[a], 1)
                        if tot_v.get(a) else None}
            zones.append({
                "zone": z, "acs": len(members), "members": members,
                "best": acinfo(shr[-1][0]) if shr else None,
                "worst": acinfo(shr[0][0]) if shr else None})

        # booth zones + top booth (must have real E-rows, not constants)
        ycol = {"VS2017": "a2017", "LS2019": "a2019",
                "VS2022": "a2022", "LS2024": "a2024"}[election]
        yvs = {"VS2017": "a2017", "LS2019": "a2019",
               "VS2022": "a2022", "LS2024": "a2024"}[vs]
        booth_zones = []
        for z in _PARTY_ORDER:
            n = con.execute("SELECT COUNT(*) c FROM booth_row "
                            "WHERE zone=?", (z,)).fetchone()["c"]
            top = None
            for r in con.execute(
                    f'SELECT ac, ps, name, "{ycol}" s, "{yvs}" sv '
                    f"FROM booth_row "
                    f"WHERE zone=? AND \"{ycol}\" IS NOT NULL "
                    f"ORDER BY \"{ycol}\" DESC LIMIT 12", (z,)):
                hit = con.execute(
                    "SELECT ps_name FROM booth_election WHERE ac=? "
                    "AND ps=? AND election=? LIMIT 1",
                    (r["ac"], r["ps"], election)).fetchone()
                if hit:
                    nm = con.execute(
                        "SELECT ac_name FROM ac_summary WHERE ac=? "
                        "LIMIT 1", (r["ac"],)).fetchone()
                    # workbook writes 0 (not NULL) for missing
                    # elections - null the vs share unless vs rows exist
                    vs_hit = con.execute(
                        "SELECT 1 FROM booth_election WHERE ac=? "
                        "AND ps=? AND election=? LIMIT 1",
                        (r["ac"], r["ps"], vs)).fetchone()
                    top = {"ac": r["ac"],
                           "ac_name": nm["ac_name"] if nm else "",
                           "ps": r["ps"], "name": r["name"],
                           "share": round(100.0 * (r["s"] or 0), 1),
                           "share_vs": round(100.0 * (r["sv"] or 0), 1)
                           if (r["sv"] is not None and vs_hit) else None}
                    break
            booth_zones.append({"zone": z, "booths": n, "top": top})

        # voter profile (selected election; fallback VS2022)
        voter_from = election
        v = con.execute(
            'SELECT SUM(male) m, SUM(female) f, SUM(polled) p, '
            'SUM(electors) e FROM booth_election WHERE election=?',
            (election,)).fetchone()
        if not v["m"] and not v["f"]:
            voter_from = "VS2022"
            v = con.execute(
                'SELECT SUM(male) m, SUM(female) f, SUM(polled) p, '
                'SUM(electors) e FROM booth_election '
                "WHERE election='VS2022'").fetchone()
        mf = (v["m"] or 0) + (v["f"] or 0)
        voter = {"male_pct": round(100.0 * (v["m"] or 0) / mf, 1)
                 if mf else None,
                 "female_pct": round(100.0 * (v["f"] or 0) / mf, 1)
                 if mf else None,
                 "voting_pct":
                 round(100.0 * (v["p"] or 0) / (v["e"] or 1), 1),
                 "from": voter_from}

        # religion: electors-weighted statewide means (2017 vintage)
        rels = ["hindu", "muslim", "christian", "sikh", "jain",
                "buddhist", "parsi"]
        expr = ", ".join(
            "SUM(\"%s_percent_17\"*electors_17)/SUM(electors_17)"
            % r for r in rels)
        wmean = con.execute(
            "SELECT %s FROM booth_row" % expr).fetchone()
        religion = {r: round(wmean[i], 1) if wmean[i] is not None
                    else None for i, r in enumerate(rels)}
        s = sum(x for x in religion.values() if x is not None)
        religion["others"] = round(max(0.0, 100.0 - s), 1)

        notes = []
        if len(win_e) < 403:
            notes.append("seats/shares counted in %d of 403 ACs "
                         "(booth conversion thin for %s)"
                         % (len(win_e), election))
        if election == "LS2024":
            notes.append("2024 seats are assembly-segment leads "
                         "(Lok Sabha), not seats won")
        out = {"election": election, "vs": vs,
               "seats": seats, "seats_counted": len(win_e),
               "avg_share": round(100.0 * bjp_all_e / tot_all_e, 2)
               if tot_all_e else None,
               "avg_share_vs": round(100.0 * bjp_all_v / tot_all_v, 2)
               if tot_all_v else None,
               "ac_shares": {
                   a: [(round(100.0 * bjp_e.get(a, 0) / tot_e[a], 1)
                        if tot_e.get(a) else None),
                       (round(100.0 * bjp_v.get(a, 0) / tot_v[a], 1)
                        if tot_v.get(a) else None)]
                   for a in set(tot_e) | set(tot_v)},
               "ac_zones": zones, "ac_zone": ac_zone,
               "booth_zones": booth_zones,
               "voter": voter, "religion": religion, "notes": notes}
        _CACHE[ck] = out
        return out
    finally:
        con.close()


@app.get("/api/ac/{ac}/religion")
def api_ac_religion(ac: int):
    """Electors-weighted religion means over one AC's booths (2017
    vintage, modeled - same formula as the statewide panel)."""
    ck = ("religion", ac)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        rels = ["hindu", "muslim", "christian", "sikh", "jain",
                "buddhist", "parsi"]
        expr = ", ".join(
            "SUM(\"%s_percent_17\"*electors_17)/SUM(electors_17)"
            % r for r in rels)
        wmean = con.execute(
            "SELECT %s FROM booth_row WHERE ac=?" % expr, (ac,)).fetchone()
        religion = {r: round(wmean[i], 1) if wmean[i] is not None
                    else None for i, r in enumerate(rels)}
        s = sum(x for x in religion.values() if x is not None)
        religion["others"] = round(max(0.0, 100.0 - s), 1)
        n = con.execute(
            'SELECT COUNT(*) c, COUNT("electors_17") d FROM booth_row '
            "WHERE ac=?", (ac,)).fetchone()
        out = {"religion": religion, "booths": n["c"],
               "with_data": n["d"]}
        _CACHE[ck] = out
        return out
    finally:
        con.close()


@app.get("/api/trend")
def api_trend():
    """Statewide per-election rollup: BJP share + seats/leads +
    turnout. One call replaces N overview fetches for trend charts."""
    if "trend" in _CACHE:
        return _CACHE["trend"]
    con = db()
    try:
        to = {}
        for r in con.execute(
                "SELECT election, SUM(electors) e, SUM(polled) p "
                "FROM booth_election GROUP BY election"):
            to[r["election"]] = (r["e"], r["p"])
        seg = con.execute(
            "SELECT SUM(electors) e, SUM(valid_sum) v, SUM(nota) n "
            "FROM seg2024_ac").fetchone()
        rows = []
        for e in ("VS2017", "LS2019", "VS2022", "LS2024"):
            per_ac, ac_tot, ac_bjp, win, labels, nota = \
                _election_rollup(e)
            tot = sum(ac_tot.values())
            bjp = sum(ac_bjp.values())
            wins = {}
            for ac, (n, _) in win.items():
                wins[n] = wins.get(n, 0) + 1
            if e == "LS2024":
                tot += nota
                turnout = ((seg["v"] or 0) + (seg["n"] or 0)) / \
                    (seg["e"] or 1) if seg["e"] else None
            else:
                el, po = to.get(e, (0, 0))
                turnout = po / el if el else None
            rows.append({
                "election": e,
                "bjp_share": round(100.0 * bjp / tot, 2) if tot else None,
                "bjp_seats": wins.get("BJP", 0),
                "seats_counted": len(win),
                "seats_word": "leads" if e.startswith("LS") else "seats",
                "turnout": round(100.0 * turnout, 2)
                if turnout is not None else None,
                "top": [{"party": n if n in
                         ("BJP", "SP", "BSP", "INC", "RLD", "ADAL",
                          "SBSP") else (labels.get(n, [n])[0]),
                         "seats": s}
                        for n, s in sorted(wins.items(),
                                           key=lambda x: -x[1])[:6]]})
        out = {"rows": rows}
        _CACHE["trend"] = out
        return out
    finally:
        con.close()


@app.get("/api/ac/{ac}/past")
def api_ac_past(ac: int):
    """Per-election result sheet: turnout, party shares, winner,
    runner-up, margins (votes + pp). LS2024 from official segment
    totals; else converted-booth sums."""
    ck = ("past", ac)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        elecs = ("VS2017", "LS2019", "VS2022", "LS2024")
        summ = {r["election"]: dict(r) for r in con.execute(
            "SELECT * FROM ac_summary WHERE ac=?", (ac,))}
        seg = con.execute("SELECT * FROM seg2024_ac WHERE ac=?",
                          (ac,)).fetchone()
        nbooth = {r["election"]: r["c"] for r in con.execute(
            "SELECT election, COUNT(*) c FROM booth_election "
            "WHERE ac=? GROUP BY election", (ac,))}
        rows = []
        for e in elecs:
            per_ac, ac_tot, ac_bjp, win, labels, nota = \
                _election_rollup(e)
            parties = []
            for (a, n), v in per_ac.items():
                if a == ac:
                    parties.append({
                        "party": n if n in
                        ("BJP", "SP", "BSP", "INC", "RLD", "ADAL",
                         "SBSP") else labels.get(n, [n])[0],
                        "votes": v})
            parties.sort(key=lambda x: -x["votes"])
            tot = ac_tot.get(ac, 0)
            for p in parties:
                p["share"] = round(100.0 * p["votes"] / tot, 2) if tot \
                    else None
            w = parties[0] if parties else None
            r = parties[1] if len(parties) > 1 else None
            if e == "LS2024" and seg:
                polled = (seg["valid_sum"] or 0) + (seg["nota"] or 0)
                t = {"electors": seg["electors"], "polled": polled,
                     "turnout": round(100.0 * polled / seg["electors"], 2)
                     if seg["electors"] else None,
                     "nota": seg["nota"]}
                src = "official ECI segment totals (all-AC)"
            else:
                s = summ.get(e, {})
                t = {"electors": s.get("electors"), "polled": s.get("polled"),
                     "turnout": s.get("turnout_pct"), "nota": s.get("nota")}
                src = "sum of converted booths"
            rows.append({
                "election": e, "turnout": t,
                "booths": nbooth.get(e, 0),
                "bjp_votes": next((p["votes"] for p in parties
                                   if p["party"] == "BJP"), 0),
                "bjp_share": next((p["share"] for p in parties
                                   if p["party"] == "BJP"), None),
                "winner": w["party"] if w else None,
                "winner_votes": w["votes"] if w else None,
                "runnerup": r["party"] if r else None,
                "margin_votes": (w["votes"] - r["votes"])
                if w and r else None,
                "margin_pp": round(w["share"] - r["share"], 2)
                if w and r and w["share"] is not None
                and r["share"] is not None else None,
                "parties": parties, "source": src})
        out = {"rows": rows}
        _CACHE[ck] = out
        return out
    finally:
        con.close()


@app.get("/api/ac/{ac}/ages")
def api_ac_ages(ac: int):
    """Modeled age profile (2017 roll): electors-weighted mean/SD
    overall + per religion (weighted by that religion's modeled
    electors). Statistical estimates, never counted people."""
    ck = ("ages", ac)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        rels = ["hindu", "muslim", "christian", "sikh", "jain",
                "buddhist", "parsi"]
        base = con.execute(
            'SELECT COUNT(*) booths, COUNT("electors_17") with_data, '
            'SUM(electors_17) el, '
            'SUM("age_avg_17"*electors_17)/SUM(electors_17) mean, '
            'SUM("age_stddev_17"*electors_17)/SUM(electors_17) sd '
            "FROM booth_row WHERE ac=?", (ac,)).fetchone()
        by_rel = {}
        for r in rels:
            q = con.execute(
                f'SELECT SUM("{r}_percent_17"/100.0*electors_17) rel_el, '
                f'SUM("age_{r}_avg_17"*"{r}_percent_17"/100.0*'
                f'electors_17)/SUM("{r}_percent_17"/100.0*'
                f'electors_17) rel_mean, '
                f'SUM("age_{r}_stddev_17"*"{r}_percent_17"/100.0*'
                f'electors_17)/SUM("{r}_percent_17"/100.0*'
                f'electors_17) rel_sd FROM booth_row WHERE ac=?',
                (ac,)).fetchone()
            by_rel[r] = {
                "electors": round(q["rel_el"] or 0),
                "mean": round(q["rel_mean"], 1)
                if q["rel_mean"] is not None else None,
                "sd": round(q["rel_sd"], 1)
                if q["rel_sd"] is not None else None}
        out = {"overall": {
                   "electors": base["el"],
                   "mean": round(base["mean"], 1)
                   if base["mean"] is not None else None,
                   "sd": round(base["sd"], 1)
                   if base["sd"] is not None else None},
               "by_religion": by_rel,
               "booths": base["booths"], "with_data": base["with_data"]}
        _CACHE[ck] = out
        return out
    finally:
        con.close()


@app.get("/api/ac/{ac}/averages")
def api_ac_averages(ac: int):
    """Per-booth means per election: electors, male/female polled,
    polled, plus totals and booth counts."""
    ck = ("averages", ac)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        rows = []
        for r in con.execute(
                "SELECT election, COUNT(*) booths, SUM(electors) e, "
                "SUM(male) m, SUM(female) f, SUM(\"other\") o, "
                "SUM(polled) p FROM booth_election WHERE ac=? "
                "GROUP BY election "
                "ORDER BY CASE election WHEN 'VS2017' THEN 1 "
                "WHEN 'LS2019' THEN 2 WHEN 'VS2022' THEN 3 "
                "WHEN 'LS2024' THEN 4 ELSE 5 END", (ac,)):
            n = r["booths"] or 1
            rows.append({
                "election": r["election"], "booths": r["booths"],
                "avg_electors": round((r["e"] or 0) / n, 1),
                "avg_male": round((r["m"] or 0) / n, 1),
                "avg_female": round((r["f"] or 0) / n, 1),
                "avg_polled": round((r["p"] or 0) / n, 1),
                "tot_electors": r["e"], "tot_male": r["m"],
                "tot_female": r["f"], "tot_other": r["o"],
                "tot_polled": r["p"]})
        out = {"rows": rows}
        _CACHE[ck] = out
        return out
    finally:
        con.close()


@app.get("/api/margins")
def api_margins(election: str = "VS2017", order: str = "asc",
                limit: int = 50, ac: int | None = None):
    """Per-booth margins: winner/runner-up (votes + pp), paginated and
    sortable both ways (closest <-> landslides), plus a margin-pp
    histogram for distribution charts. LS2024 covers converted booths
    only. Cached (static data)."""
    elecs = ("VS2017", "LS2019", "VS2022", "LS2024")
    if election not in elecs:
        raise HTTPException(400, "election must be one of %s" % (elecs,))
    if order not in ("asc", "desc"):
        raise HTTPException(400, "order must be asc|desc")
    limit = max(1, min(limit, 500))
    ck = ("margins", election, ac if ac is not None else 0)
    if ck not in _CACHE:
        con = db()
        try:
            q = ("SELECT v.booth_uid, b.ac, b.ps, v.candidate, "
                 "v.party, v.votes FROM vote v "
                 "JOIN booth_election b ON v.booth_uid = b.booth_uid "
                 "WHERE b.election=?")
            args: list = [election]
            if ac is not None:
                q += " AND b.ac=?"
                args.append(ac)
            per: dict = {}
            for r in con.execute(q, args):
                b = per.setdefault(r["booth_uid"],
                                   {"ac": r["ac"], "ps": r["ps"],
                                    "tot": 0, "top": []})
                b["tot"] += r["votes"] or 0
                b["top"].append((r["votes"] or 0, r["candidate"],
                                 r["party"]))
            rows = []
            for uid, b in per.items():
                top = sorted(b["top"], reverse=True)[:2]
                if len(top) < 2:
                    continue
                (wv, wc, wp), (rv, rc, rp) = top
                tot = b["tot"] or 1
                rows.append({
                    "booth_uid": uid, "ac": b["ac"], "ps": b["ps"],
                    "winner": wc, "winner_party": wp, "winner_votes": wv,
                    "winner_share": round(100.0 * wv / tot, 2),
                    "runnerup": rc, "runnerup_party": rp,
                    "runnerup_votes": rv,
                    "margin_votes": wv - rv,
                    "margin_pp": round(100.0 * (wv - rv) / tot, 2)})
            brackets = [1, 2, 5, 10, 20, 100]
            hist = [0] * len(brackets)
            for r in rows:
                for i, edge in enumerate(brackets):
                    if r["margin_pp"] < edge or i == len(brackets) - 1:
                        hist[i] += 1
                        break
            _CACHE[ck] = {"rows": rows, "total": len(rows),
                          "histogram": [
                              {"under_pp": e, "booths": n}
                              for e, n in zip(brackets, hist)],
                          "booths": len(rows)}
        finally:
            con.close()
    full = _CACHE[ck]
    ordered = sorted(full["rows"],
                     key=lambda r: (r["margin_pp"], r["margin_votes"]),
                     reverse=(order == "desc"))
    return {"rows": ordered[:limit], "total": full["total"],
            "histogram": full["histogram"], "booths": full["booths"],
            "order": order, "limit": limit}


@app.get("/api/ac/{ac}/sexratio")
def api_ac_sexratio(ac: int):
    """Male/female polling per election (booth sums) + F-per-1000-M."""
    ck = ("sex", ac)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT election, SUM(electors) electors, "
            "SUM(male) male, SUM(female) female, SUM(\"other\") other, "
            "SUM(polled) polled FROM booth_election "
            "WHERE ac=? GROUP BY election "
            "ORDER BY CASE election WHEN 'VS2017' THEN 1 "
            "WHEN 'LS2019' THEN 2 WHEN 'VS2022' THEN 3 "
            "WHEN 'LS2024' THEN 4 ELSE 5 END",
            (ac,))]
        for r in rows:
            m, f = r["male"] or 0, r["female"] or 0
            r["f_per_1000m"] = round(1000.0 * f / m, 1) if m else None
        out = {"rows": rows}
        _CACHE[ck] = out
        return out
    finally:
        con.close()


@app.get("/api/ac/{ac}/votes")
def api_ac_votes(ac: int, election: str = "VS2017"):
    con = db()
    try:
        parties = [dict(r) for r in con.execute(
            "SELECT party, SUM(votes) AS votes FROM vote v "
            "JOIN booth_election b ON v.booth_uid = b.booth_uid "
            "WHERE b.ac=? AND b.election=? GROUP BY party "
            "ORDER BY votes DESC", (ac, election))]
        summ = [dict(r) for r in con.execute(
            "SELECT * FROM ac_summary WHERE ac=? AND election=?",
            (ac, election))]
        source = "sum of converted booths"
        if not parties and election == "LS2024":
            # 2024 booth conversion is thin - fall back to the ECI
            # official assembly-segment totals (all 403 ACs).
            parties = [dict(r) for r in con.execute(
                "SELECT party, SUM(votes) AS votes FROM seg2024 "
                "WHERE ac=? GROUP BY party ORDER BY votes DESC",
                (ac,))]
            seg = con.execute("SELECT * FROM seg2024_ac WHERE ac=?",
                              (ac,)).fetchone()
            nbooth = con.execute(
                "SELECT COUNT(*) c FROM booth_election WHERE ac=? "
                "AND election='LS2024'", (ac,)).fetchone()["c"]
            if seg:
                polled = (seg["valid_sum"] or 0) + (seg["nota"] or 0)
                summ = [{"ac": ac, "election": election, "ac_name": None,
                         "district": None, "booths": nbooth,
                         "electors": seg["electors"], "polled": polled,
                         "valid": seg["valid_sum"], "nota": seg["nota"],
                         "turnout_pct":
                         round(100.0 * polled / seg["electors"], 2)
                         if seg["electors"] else None}]
            source = "official ECI segment totals (all-AC)"
        return {"parties": parties,
                "summary": summ[0] if summ else None,
                "source": source}
    finally:
        con.close()


@app.get("/api/zones")
def api_zones(district: str = ""):
    ck = ("zones", district)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        if district:
            rows = con.execute(
                "SELECT r.zone, COUNT(*) n FROM booth_row r "
                "WHERE r.district=? GROUP BY r.zone", (district,))
        else:
            rows = con.execute(
                "SELECT zone, COUNT(*) n FROM booth_row GROUP BY zone")
        out = {"zones": [dict(r) for r in rows]}
        _CACHE[ck] = out
        return out
    finally:
        con.close()


@app.get("/api/coverage")
def api_coverage():
    if "coverage" in _CACHE:
        return _CACHE["coverage"]
    con = db()
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM coverage ORDER BY election, ac, file")]
        out = {"rows": rows}
        _CACHE["coverage"] = out
        return out
    finally:
        con.close()


@app.get("/api/methods")
def api_methods():
    import json
    if "methods" in _CACHE:
        return _CACHE["methods"]
    con = db()
    try:
        out = {"methods": meta_get(con, "methods"),
               "zone_counts": json.loads(meta_get(con, "zone_counts",
                                                  "[]"))}
        _CACHE["methods"] = out
        return out
    finally:
        con.close()


app.mount("/assets", StaticFiles(directory=HERE / "assets"),
          name="assets")


@app.get("/", include_in_schema=False)
def root():
    # API-only server: the dashboard is the Next.js app in web/.
    return {"service": "UPBI booth API", "docs": "/docs",
            "health": "/api/meta"}


@app.get("/docs", include_in_schema=False)
def docs_page():
    """Static API reference for the Next.js frontend (offline-safe)."""
    return FileResponse(HERE / "frontend" / "docs.html")
