"""UPBI serving API (FastAPI, read-only SQLite, offline-safe).

Serves the prebuilt store (Scripts/build_servedb.py) + static frontend.
No database writes, no network calls, no CDN. Run:
  uvicorn app:app --host 127.0.0.1 --port 8000        (local)
  DB_PATH=/data/servedb.sqlite uvicorn app:app        (container)

Health: GET /api/meta
"""
from __future__ import annotations

import json
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

# Phase 1 model output (types, unusual results, expected ranges): static
# JSON written by Scripts/ml/build_insights.py, no database needed.
try:                                  # uvicorn server.app:app
    from .insights import router as insights_router
except ImportError:                   # uvicorn app:app (run inside server/)
    from insights import router as insights_router
app.include_router(insights_router)


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


# --- Party-selectable booth view -------------------------------------------------------------------------------------
# The booth dashboard used to be the BJP's view only. `party` (default BJP) now picks whose side the shares, opponent,
# differences and zones are shown from. They come from the `booth_party` table (Scripts/serve/booth_party.py); a store
# built before that table existed still serves the BJP from the original workbook columns and refuses other parties.
PARTY_DEFAULT = "BJP"
# booth_row columns that depend on the viewing party; every other booth_row column is party-neutral
PARTY_COLS = ("zone", "avg_diff", "latest_diff", "party_b",
              "a2017", "b2017", "d2017", "a2019", "b2019", "d2019",
              "a2022", "b2022", "d2022", "a2024", "b2024", "d2024")
# the opponent actually used in each election (booth_party only): the reference opponent where it stood, else the strongest other party
OPP_COLS = ("opp2017", "opp2019", "opp2022", "opp2024")
_STORE_FLAGS: dict = {}
PARTY_RULE_TEXT = (
    "Booth views are seen from one party's side (the party picker). For a "
    "booth, the share is the party's votes divided by votes polled, and the "
    "comparison party is the strongest other party in that seat (from the "
    "2022 assembly votes; the latest other election if 2022 has no data). "
    "In an election where that party did not stand (an ally took the seat) "
    "the strongest other party in that election is used instead. "
    "The difference is the party's share minus the comparison party's share. Zones: "
    "Safe = average difference above +10 points and latest above 0; "
    "Difficult = average below -10 and latest below 0; Favorable = both "
    "above 0; Battlefield = the rest; Data Not sufficient = fewer than two "
    "elections with a difference. A party counts in a seat and election only "
    "if it stood there (at least 1% of the seat's votes); where it did not, "
    "nothing is shown (not 0%).")


def party_table(con: sqlite3.Connection) -> bool:
    """True when the store has the party-selectable booth view."""
    if "party_table" not in _STORE_FLAGS:
        _STORE_FLAGS["party_table"] = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='booth_party'").fetchone() is not None
    return _STORE_FLAGS["party_table"]


def party_options(con: sqlite3.Connection) -> list:
    """Parties the booth views can be seen from (store meta), else just the default."""
    if "parties" not in _STORE_FLAGS:
        opts = [PARTY_DEFAULT]
        raw = meta_get(con, "parties", "") if party_table(con) else ""
        if raw:
            opts = [p["party"] for p in json.loads(raw)]
        _STORE_FLAGS["parties"] = opts
    return _STORE_FLAGS["parties"]


def resolve_party(con: sqlite3.Connection, party: str) -> str:
    p = (party or PARTY_DEFAULT).strip().upper()
    opts = party_options(con)
    if p not in opts:
        hint = "" if party_table(con) else (
            " (this store has no party view yet: run "
            "Scripts/serve/add_booth_party.py)")
        raise HTTPException(400, f"party must be one of {opts}{hint}")
    return p


def party_sql(con: sqlite3.Connection, party: str):
    """(join SQL, join args, col) to read the party-dependent booth columns of booth_row `r` for `party`.

    col(name) is the SQL expression for that column. Booths the party never stood in have no booth_party row and
    read as 'Data Not sufficient' with empty shares."""
    if party_table(con):
        def col(c):
            return ("COALESCE(p.zone, 'Data Not sufficient')"
                    if c == "zone" else f"p.{c}")
        return ("LEFT JOIN booth_party p ON p.party = ? AND p.ac = r.ac "
                "AND p.ps = r.ps", [party], col)
    return "", [], (lambda c: f"r.{c}")


def party_scan(con: sqlite3.Connection, party: str):
    """Index-friendly source for whole-state rollups of one party: (table SQL, WHERE prefix, args, col, ac, ps).

    Reads booth_party directly (every booth has a row for each listed party); an old store reads booth_row."""
    if party_table(con):
        return ("booth_party p", "p.party = ? AND ", [party],
                (lambda c: f"p.{c}"), "p.ac", "p.ps")
    return ("booth_row r", "", [], (lambda c: f"r.{c}"), "r.ac", "r.ps")


def party_votes(roll, party: str) -> dict:
    """{ac: votes} for one party from an election rollup (per_ac keyed by (ac, party code))."""
    return {a: v for (a, n), v in roll[0].items() if n == party}


@app.get("/api/meta")
def api_meta():
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
                "party_view": party_table(con),
                "default_party": PARTY_DEFAULT,
                "parties": party_options(con),
                "party_coverage": json.loads(
                    meta_get(con, "party_coverage", "{}")),
                # seats left out per election: unreadable party labels
                "label_flags": {
                    e: len(v) for e, v in json.loads(
                        meta_get(con, "label_flags", "{}")).items()},
                "zone_rule": json.loads(meta_get(con, "zone_rule", "{}")),
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
        opponent: str = "",
        party: str = PARTY_DEFAULT,
        sort: str = "ps",
        order: str = "asc",
        page: int = Query(1, ge=1),
        page_size: int = Query(PAGE_DEFAULT, ge=1, le=PAGE_MAX)):
    """Booth grid seen from `party`'s side (shares, opponent, differences, zone). Always scoped: requires ac or q
    (never full-table). `opponent` keeps only booths where that party is the strongest opponent."""
    if ac is None and not q.strip():
        raise HTTPException(400, "scope required: ?ac=<no> or ?q=<text>")
    col = sort if sort in valid_cols() else SORT_ALIASES.get(sort, "ps")
    if col not in valid_cols():
        col = "ps"
    direction = "DESC" if order.lower() == "desc" else "ASC"
    con = db()
    try:
        party = resolve_party(con, party)
        pjoin, pargs, pcol = party_sql(con, party)
        # placeholders are bound in the order they appear in the SQL text:
        # FROM ... [search join] [party join] WHERE ...
        join, args = "", []
        if q.strip():
            join = ("JOIN (SELECT rowid FROM booth_fts "
                    "WHERE booth_fts MATCH ?) f ON f.rowid = r.rowid ")
            args.append(q.strip() + "*")
        join += pjoin
        args += pargs
        where = ["1=1"]
        if ac is not None:
            where.append("r.ac = ?")
            args.append(ac)
        if zone:
            where.append(f"{pcol('zone')} = ?")
            args.append(zone)
        if opponent:
            where.append(f"{pcol('party_b')} = ?")
            args.append(opponent.upper())
        # Religion-wise columns live in booth_row but outside ROW_COLS -
        # include them so the group view and tooltips have values.
        base_cols = [c.strip() for c in ROW_COLS.split(",")]
        extra = sorted(valid_cols() - set(base_cols))
        sel = ", ".join(
            f"{pcol(c)} AS {c}" if c in PARTY_COLS else f"r.{c}"
            for c in base_cols) + "".join(f', r."{c}"' for c in extra)
        if party_table(con):
            sel += "".join(f", p.{c} AS {c}" for c in OPP_COLS)
        base = f"FROM booth_row r {join} WHERE {' AND '.join(where)}"
        total = con.execute(f"SELECT COUNT(*) c {base}", args
                            ).fetchone()["c"]
        # NULL/empty serials sort last for ps; numeric-aware via CAST
        if col == "ps":
            order_by = f"CAST(r.ps AS INTEGER) {direction}, r.ps {direction}"
        elif col in PARTY_COLS:
            order_by = f"{pcol(col)} {direction}"
        else:
            order_by = f'r."{col}" {direction}'
        cur = con.execute(
            f"SELECT {sel} {base} ORDER BY {order_by} "
            f"LIMIT ? OFFSET ?", args + [page_size, (page - 1)
                                         * page_size])
        rows = [dict(r) for r in cur]
        return {"total": total, "page": page, "page_size": page_size,
                "party": party, "rows": rows, "demo_cols": extra}
    finally:
        con.close()


@app.get("/api/booth/{ac}/{ps}")
def api_booth(ac: int, ps: str, party: str = PARTY_DEFAULT):
    con = db()
    try:
        party = resolve_party(con, party)
        pjoin, pargs, pcol = party_sql(con, party)
        demo_names = [c[1] for c in
                      con.execute("PRAGMA table_info(booth_row)")]
        base_cols = [c.strip() for c in ROW_COLS.split(",")]
        extra = [c for c in demo_names if c not in set(base_cols)]
        sel = ", ".join(
            f"{pcol(c)} AS {c}" if c in PARTY_COLS else f"r.{c}"
            for c in base_cols) + "".join(f', r."{c}"' for c in extra)
        if party_table(con):
            sel += "".join(f", p.{c} AS {c}" for c in OPP_COLS)
        r = con.execute(f"SELECT {sel} FROM booth_row r {pjoin} "
                        "WHERE r.ac=? AND r.ps=?",
                        pargs + [ac, ps]).fetchone()
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
        return {"party": party, "row": dict(r), "elections": elec,
                "votes": votes}
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
# Seats whose party labels are not usable in an election, per election: more than BAD_LABEL_SHARE of the seat's
# votes sit under IND, blank or unmapped labels (in the booth sheets that is a party column that failed to read:
# the winner's votes end up under "IND"). Such a seat has no winner and no party share; it is reported, not guessed.
_BAD: dict = {}
BAD_LABELS = ("", "IND", "UNMAPPED")
BAD_LABEL_SHARE = 0.25
# a party stood in a seat only if it holds at least this share of the seat's votes (a few stray votes under a party's
# label are mis-read rows, not a candidate); same rule as Scripts/serve/booth_party.py
STOOD_SHARE = 0.01


def _stood(votes, total) -> bool:
    return bool(total) and votes > 0 and votes / total >= STOOD_SHARE


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
        per_ac, labels, ac_tot, bad_votes = {}, {}, {}, {}
        for r in rows:
            ac_tot[r["ac"]] = ac_tot.get(r["ac"], 0) + (r["v"] or 0)
            n = _norm_party(r["party"])
            if n in BAD_LABELS:
                bad_votes[r["ac"]] = (bad_votes.get(r["ac"], 0)
                                      + (r["v"] or 0))
            if not n or n == "NOTA":
                continue  # counted in totals, never a winner/label
            key = (r["ac"], n)
            per_ac[key] = per_ac.get(key, 0) + (r["v"] or 0)
            lbl = (r["party"] or "").strip()
            if n not in labels:
                labels[n] = [lbl, r["v"] or 0]
            elif (r["v"] or 0) > labels[n][1]:
                labels[n] = [lbl, r["v"] or 0]
        bad = {a for a, bv in bad_votes.items()
               if ac_tot.get(a) and bv / ac_tot[a] >= BAD_LABEL_SHARE}
        ac_bjp, win = {}, {}
        for (ac, n), v in per_ac.items():
            if n == "BJP":
                ac_bjp[ac] = ac_bjp.get(ac, 0) + v
            if ac_tot.get(ac, 0) >= MIN_VOTES and ac not in bad and (
                    ac not in win or v > win[ac][1]):
                win[ac] = (n, v)
        out = (per_ac, ac_tot, ac_bjp, win, labels, nota)
        _BAD[e] = bad
        _ROLL[e] = out
        return out
    finally:
        con.close()


@app.get("/api/overview")
def api_overview(election: str = "LS2024", vs: str = "VS2022",
                 party: str = PARTY_DEFAULT):
    """Homepage rollup for the selected election vs a comparison one,
    seen from `party`'s side.

    Seats = per-AC plurality winner (NOTA never wins; ACs with no
    usable votes are reported as gaps, not seats). VS years use booth
    sums; LS2024 uses official segment totals. Shares/zone/best-worst
    derive from the same rollups - see server/DASHBOARD_LOGIC.md. The
    seat table lists every party; the share, zones, best/worst and top
    booths are the chosen party's."""
    elecs = ("VS2017", "LS2019", "VS2022", "LS2024")
    if election not in elecs or vs not in elecs:
        raise HTTPException(400, "election/vs must be one of %s"
                            % (elecs,))
    con = db()
    try:
        party = resolve_party(con, party)
    finally:
        con.close()
    ck = ("overview", election, vs, party)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        pjoin, pargs, pcol = party_sql(con, party)
        roll_e = _election_rollup(election)
        _, tot_e, _bjp, win_e, labels, nota_e = roll_e
        roll_v = _election_rollup(vs)
        _, tot_v, _bjp_v, _, _, _ = roll_v
        bjp_e = party_votes(roll_e, party)   # the chosen party's votes
        bjp_v = party_votes(roll_v, party)   # (name kept from the BJP-only version)
        # seats whose party labels are unreadable in an election are left
        # out of every share (see _BAD)
        bad_e, bad_v = _BAD.get(election, set()), _BAD.get(vs, set())
        tot_all_e = sum(v for a, v in tot_e.items()
                        if a not in bad_e) + nota_e
        tot_all_v = sum(v for a, v in tot_v.items() if a not in bad_v)
        bjp_all_e = sum(v for a, v in bjp_e.items() if a not in bad_e)
        bjp_all_v = sum(v for a, v in bjp_v.items() if a not in bad_v)

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

        tbl, pre, targs, tc, tac, tps = party_scan(con, party)
        ac_zone = {}
        for r in con.execute(
                f"SELECT {tac} ac, AVG({tc('avg_diff')}) a, "
                f"AVG({tc('latest_diff')}) l, "
                f"COUNT({tc('avg_diff')}) n "
                f"FROM {tbl} WHERE {pre}1=1 GROUP BY {tac}", targs):
            ac_zone[r["ac"]] = _ac_zone(r["a"], r["l"], r["n"])

        zones = []
        for z in _PARTY_ORDER:
            members = [a for a, zz in ac_zone.items() if zz == z]
            # best/least performing: only seats where the party stood
            shr = [(a, bjp_e.get(a, 0) / tot_e[a])
                   for a in members
                   if tot_e.get(a, 0) >= MIN_VOTES
                   and _stood(bjp_e.get(a, 0), tot_e.get(a, 0))
                   and a not in bad_e]
            shr.sort(key=lambda x: x[1])
            def acinfo(a):
                nm = con.execute(
                    "SELECT ac_name, district FROM ac_summary "
                    "WHERE ac=? LIMIT 1", (a,)).fetchone()
                return {"ac": a,
                        "ac_name": nm["ac_name"] if nm else "",
                        "district": nm["district"] if nm else "",
                        "share": round(100.0 * bjp_e.get(a, 0)
                                       / tot_e[a], 1)
                        if _stood(bjp_e.get(a, 0), tot_e.get(a, 0))
                        and a not in bad_e else None,
                        "share_vs":
                        round(100.0 * bjp_v.get(a, 0) / tot_v[a], 1)
                        if _stood(bjp_v.get(a, 0), tot_v.get(a, 0))
                        and a not in bad_v else None}
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
        zone_n = {r["zone"]: r["n"] for r in con.execute(
            f"SELECT {tc('zone')} zone, COUNT(*) n FROM {tbl} "
            f"WHERE {pre}1=1 GROUP BY {tc('zone')}", targs)}
        for z in _PARTY_ORDER:
            n = zone_n.get(z, 0)
            top = None
            for r in con.execute(
                    f"SELECT {tac} ac, {tps} ps, "
                    f"{tc(ycol)} s, {tc(yvs)} sv "
                    f"FROM {tbl} "
                    f"WHERE {pre}{tc('zone')}=? AND {tc(ycol)} IS NOT NULL "
                    f"ORDER BY {tc(ycol)} DESC LIMIT 12", targs + [z]):
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
                    bn = con.execute(
                        "SELECT name FROM booth_row WHERE ac=? AND ps=?",
                        (r["ac"], r["ps"])).fetchone()
                    top = {"ac": r["ac"],
                           "ac_name": nm["ac_name"] if nm else "",
                           "ps": r["ps"], "name": bn["name"] if bn else "",
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
        if bad_e:
            notes.append("%d seats are left out of %s: the party names in "
                         "their booth sheets are unreadable (more than a "
                         "quarter of the votes are labelled IND or blank)"
                         % (len(bad_e), election))
        if election == "LS2024":
            notes.append("2024 seats are assembly-segment leads "
                         "(Lok Sabha), not seats won")
        out = {"election": election, "vs": vs, "party": party,
               # seats where the party had any votes: a party that did not
               # stand is not a party that lost
               "party_stood": sum(1 for a, v in bjp_e.items()
                                  if _stood(v, tot_e.get(a, 0))
                                  and a not in bad_e),
               "party_stood_vs": sum(1 for a, v in bjp_v.items()
                                     if _stood(v, tot_v.get(a, 0))
                                     and a not in bad_v),
               "seats": seats, "seats_counted": len(win_e),
               "avg_share": round(100.0 * bjp_all_e / tot_all_e, 2)
               if tot_all_e else None,
               "avg_share_vs": round(100.0 * bjp_all_v / tot_all_v, 2)
               if tot_all_v else None,
               "ac_shares": {
                   a: [(round(100.0 * bjp_e.get(a, 0) / tot_e[a], 1)
                        if _stood(bjp_e.get(a, 0), tot_e.get(a, 0))
                        and a not in bad_e else None),
                       (round(100.0 * bjp_v.get(a, 0) / tot_v[a], 1)
                        if _stood(bjp_v.get(a, 0), tot_v.get(a, 0))
                        and a not in bad_v else None)]
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
def api_trend(party: str = PARTY_DEFAULT):
    """Statewide per-election rollup: the chosen party's share + seats/
    leads + turnout. One call replaces N overview fetches for trend
    charts."""
    con = db()
    try:
        party = resolve_party(con, party)
    finally:
        con.close()
    ck = ("trend", party)
    if ck in _CACHE:
        return _CACHE[ck]
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
            roll = _election_rollup(e)
            per_ac, ac_tot, _ac_bjp, win, labels, nota = roll
            bad = _BAD.get(e, set())      # unreadable party labels: left out
            tot = sum(v for a, v in ac_tot.items() if a not in bad)
            pv = sum(v for a, v in party_votes(roll, party).items()
                     if a not in bad)
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
                "share": round(100.0 * pv / tot, 2) if tot else None,
                "seats": wins.get(party, 0),
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
        out = {"party": party, "rows": rows}
        _CACHE[ck] = out
        return out
    finally:
        con.close()


@app.get("/api/ac/{ac}/past")
def api_ac_past(ac: int, party: str = PARTY_DEFAULT):
    """Per-election result sheet: turnout, party shares, winner,
    runner-up, margins (votes + pp). LS2024 from official segment
    totals; else converted-booth sums. `party_votes`/`party_share` are
    the chosen party's."""
    con = db()
    try:
        party = resolve_party(con, party)
    finally:
        con.close()
    ck = ("past", ac, party)
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
            unreadable = ac in _BAD.get(e, set())
            w = parties[0] if parties and not unreadable else None
            r = parties[1] if len(parties) > 1 and not unreadable else None
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
                "labels_unreadable": unreadable,
                "party_votes": next((p["votes"] for p in parties
                                     if p["party"] == party), 0)
                if not unreadable else 0,
                "party_share": next((p["share"] for p in parties
                                     if p["party"] == party), None)
                if not unreadable else None,
                "winner": w["party"] if w else None,
                "winner_votes": w["votes"] if w else None,
                "runnerup": r["party"] if r else None,
                "margin_votes": (w["votes"] - r["votes"])
                if w and r else None,
                "margin_pp": round(w["share"] - r["share"], 2)
                if w and r and w["share"] is not None
                and r["share"] is not None else None,
                "parties": parties if not unreadable else [],
                "source": src})
        out = {"party": party, "rows": rows}
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
def api_zones(district: str = "", party: str = PARTY_DEFAULT):
    """Booth counts per zone, seen from `party`'s side."""
    con = db()
    try:
        party = resolve_party(con, party)
    finally:
        con.close()
    ck = ("zones", district, party)
    if ck in _CACHE:
        return _CACHE[ck]
    con = db()
    try:
        pjoin, pargs, pcol = party_sql(con, party)
        z = pcol("zone")
        if district:
            rows = con.execute(
                f"SELECT {z} AS zone, COUNT(*) n FROM booth_row r {pjoin} "
                f"WHERE r.district=? GROUP BY {z}", pargs + [district])
        else:
            rows = con.execute(
                f"SELECT {z} AS zone, COUNT(*) n FROM booth_row r {pjoin} "
                f"GROUP BY {z}", pargs)
        out = {"party": party, "zones": [dict(r) for r in rows]}
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
               "party_rule": PARTY_RULE_TEXT,
               "zone_counts": json.loads(meta_get(con, "zone_counts",
                                                  "[]"))}
        _CACHE["methods"] = out
        return out
    finally:
        con.close()


# Optional: the web UI loads no images, so a deployment may leave this folder out.
if (HERE / "assets").is_dir():
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
