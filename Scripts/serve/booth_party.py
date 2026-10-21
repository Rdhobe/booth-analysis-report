"""Party-selectable booth view: one table, `booth_party`, for any party in PARTIES.

The original booth dashboard hard-wired the BJP (A) against its strongest opponent (B). This module computes the same
measures for any listed party P from the booth-level votes already in the store (`vote`, `booth_election`, `ac_party`),
so the server can answer "show this booth dashboard from party P's side" without a rebuild per party.

Rules (the same as the original workbook, `Scripts/report/build_state_report.py`, except where marked):
- Share of P in a booth and election = P votes / booth polled. The reference opponent B = the strongest other party in the
  seat, picked from VS2022 seat votes (fallback LS2024, LS2019, VS2017, in that order, marked with a star).
- Difference = share(P) - share(opponent), per election. The opponent is B where B stood in that election. Average difference = mean over the elections that have one; latest
  difference = the most recent one.
- Zone: fewer than two differences -> "Data Not sufficient"; avg > +0.10 and latest > 0 -> "Safe"; avg < -0.10 and
  latest < 0 -> "Difficult"; avg > 0 and latest > 0 -> "Favorable"; otherwise "Battlefield".
- CHANGE: a seat in an election is left out (no shares for anyone) when more than a quarter of its votes carry a label that is not a
  party (independents lumped as IND, blank, unmapped). In the booth sheets that is almost always a party column that failed to read: the
  winner's votes sit under "IND" and every real party looks tiny. The seats left out are listed in the `label_flags` meta key.
- CHANGE: a booth in an election is unusable (no shares) when its turnout figure cannot be right: fewer than MIN_POLLED voters, fewer
  voters than valid votes, or a share above 100%. These are mis-read turnout cells (e.g. 5 voters but 712 valid votes), and without the
  rule one booth could show a 3,940% share. Counted in the stats as `unusable_booth_rows`.
- CHANGE: where B did not stand in an election (an ally took the seat: the SP in 2017 and 2019 in many seats), the opponent for that
  election is the strongest other party in that seat and election. The workbook counted B as 0% there, so the difference was the party's
  whole share; and without a fallback such a seat keeps one comparison and no zone. The opponent used is stored per election (opp2017...).
- CHANGE: the opponent is never IND, blank or unmapped.
- CHANGE: booths with fewer than two differences keep no average or latest difference (the workbook kept the single one,
  which then leaked into the seat-level zone).
- CHANGE: a party counts in a seat and election only if it stood there (at least 1% of the seat's votes). The
  workbook counted a party as 0% in every seat when it stood anywhere in the state, which made allies' seats look like
  heavy losses. Absent shares are stored as NULL, not 0.

Use: `build_booth_party(con)` on an open, writable store connection (after `ac_party` exists), or
`python Scripts/serve/add_booth_party.py --db output/servedb.sqlite` on a finished store.
"""
from __future__ import annotations

import json
import logging
import re
import time

log = logging.getLogger("booth_party")

ELECTIONS = ["VS2017", "LS2019", "VS2022", "LS2024"]
SAFE_UP, DIFF_DOWN = 0.10, -0.10
ZONES = ["Safe", "Favorable", "Battlefield", "Difficult", "Data Not sufficient"]
# labels that are not a party; a seat-election with this much of its vote under them is not used
BAD_KEYS = ("IND", "BLANK", "UNMAPPED")
BAD_LABEL_SHARE = 0.25
MIN_POLLED = 20
# a party counts as having stood in a seat only if it holds at least this share of the seat's votes; a few stray votes under
# a party's label (mis-read rows) do not make it a candidate
MIN_STOOD_SHARE = 0.01
# Parties offered in the booth dashboard (anyone can be added here; the table grows by about 110,000 rows per party).
PARTIES = ["BJP", "SP", "BSP", "INC"]
LABELS = {"BJP": "BJP", "SP": "SP", "BSP": "BSP", "INC": "INC"}

SHARE_COLS = [f"{k}{y}" for y in ("2017", "2019", "2022", "2024") for k in "abd"]

DDL = """
DROP TABLE IF EXISTS booth_party;
CREATE TABLE booth_party(
  party TEXT, ac INTEGER, ps TEXT, party_b TEXT,
  zone TEXT, avg_diff REAL, latest_diff REAL,
  a2017 REAL, b2017 REAL, d2017 REAL,
  a2019 REAL, b2019 REAL, d2019 REAL,
  a2022 REAL, b2022 REAL, d2022 REAL,
  a2024 REAL, b2024 REAL, d2024 REAL,
  opp2017 TEXT, opp2019 TEXT, opp2022 TEXT, opp2024 TEXT,
  PRIMARY KEY (party, ac, ps)) WITHOUT ROWID;
"""
INDEXES = """
CREATE INDEX idx_bp_zone ON booth_party(party, zone);
CREATE INDEX idx_bp_zone_a2017 ON booth_party(party, zone, a2017);
CREATE INDEX idx_bp_zone_a2019 ON booth_party(party, zone, a2019);
CREATE INDEX idx_bp_zone_a2022 ON booth_party(party, zone, a2022);
CREATE INDEX idx_bp_zone_a2024 ON booth_party(party, zone, a2024);
"""


def party_key(raw) -> str:
    """Canonical party code. Mirrors `_norm_party` in server/app.py (a test keeps the two equal)."""
    n = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
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


def zone_of(diffs):
    """Zone from the four per-election differences (None where there is none). Returns (zone, avg, latest)."""
    have = [d for d in diffs if d is not None]
    avg = sum(have) / len(have) if have else None
    latest = next((d for d in reversed(diffs) if d is not None), None)
    if len(have) < 2:
        return "Data Not sufficient", avg, latest
    if avg > SAFE_UP and (latest or 0) > 0:
        return "Safe", avg, latest
    if avg < DIFF_DOWN and (latest or 0) < 0:
        return "Difficult", avg, latest
    if (avg or 0) > 0 and (latest or 0) > 0:
        return "Favorable", avg, latest
    return "Battlefield", avg, latest


def labels_ok(votes):
    """True when the party labels of one seat in one election can be trusted. votes: {party_key: votes} (NOTA left out)."""
    tot = sum(votes.values())
    bad = sum(votes.get(k, 0) for k in BAD_KEYS)
    return tot > 0 and bad / tot < BAD_LABEL_SHARE


def choose_party_b(seat_votes, party):
    """Strongest other party in one seat. seat_votes: {election: {party_key: votes}}. Returns (key, source) or ("", "")."""
    def top(e):
        if not labels_ok(seat_votes.get(e, {})):
            return ""
        tot = {p: v for p, v in seat_votes.get(e, {}).items() if p != party and v > 0 and p not in ("NOTA",) + BAD_KEYS}
        return max(tot, key=lambda p: tot[p]) if tot else ""
    b = top("VS2022")
    if b:
        return b, "VS2022"
    for e in reversed(ELECTIONS):
        if e == "VS2022":
            continue
        b = top(e)
        if b:
            return b, e + "*"
    return "", ""


def opponent_for(votes, party, ref_b):
    """Opponent of `party` in one seat and election. votes: {party_key: votes} (NOTA left out).

    The reference opponent if it stood (at least MIN_STOOD_SHARE of the votes); otherwise the strongest other party that did."""
    tot = sum(votes.values())
    if not tot or not labels_ok(votes):
        return ""

    def ok(k):
        return bool(k) and k != party and k not in BAD_KEYS and votes.get(k, 0) / tot >= MIN_STOOD_SHARE
    if ref_b and ok(ref_b):
        return ref_b
    cands = {k: v for k, v in votes.items() if ok(k)}
    return max(cands, key=lambda k: cands[k]) if cands else ""


def build_booth_party(con, parties=None, progress=True):
    """(Re)build `booth_party` and the `parties` / `party_coverage` / `zone_rule` meta keys. Returns a stats dict.

    Needs tables booth_row, booth_election, vote and ac_party. Safe to run again."""
    parties = list(parties or PARTIES)
    t0 = time.time()
    cur = con.cursor()

    # seat votes by party key: {ac: {election: {key: votes}}}
    seat: dict = {}
    for ac, e, p, v in cur.execute("SELECT ac, election, party, votes FROM ac_party"):
        k = party_key(p) or "BLANK"
        if k == "NOTA":
            continue
        d = seat.setdefault(ac, {}).setdefault(e, {})
        d[k] = d.get(k, 0) + (v or 0)

    # opponent per (party, seat) and the keys we need booth votes for in each seat
    opp: dict = {}
    opp_e: dict = {}                     # (party, seat, election) -> the opponent used that election
    need: dict = {}
    for ac, ev in seat.items():
        keys = set(parties)
        for p in parties:
            opp[(p, ac)] = choose_party_b(ev, p)
            for e in ELECTIONS:
                o = opponent_for(ev.get(e, {}), p, opp[(p, ac)][0])
                opp_e[(p, ac, e)] = o
                if o:
                    keys.add(o)
        need[ac] = keys

    flags = {(ac, e): not labels_ok(d) for ac, ev in seat.items() for e, d in ev.items()}
    label_flags = {e: sorted(ac for (ac, ee), bad in flags.items() if bad and ee == e) for e in ELECTIONS}

    # booth identity per election
    uid_info: dict = {}
    by_key: dict = {}
    for uid, e, ac, ps, polled, valid in cur.execute("SELECT booth_uid, election, ac, ps, polled, valid FROM booth_election"):
        uid_info[uid] = (ac, e, str(ps), polled, valid)
        by_key[(ac, e, str(ps))] = uid

    # booth votes, only for the keys we need
    acc: dict = {}
    cache: dict = {}
    n = 0
    for uid, raw, votes in cur.execute("SELECT booth_uid, party, votes FROM vote"):
        n += 1
        info = uid_info.get(uid)
        if info is None:
            continue
        k = cache.get(raw)
        if k is None:
            k = cache[raw] = party_key(raw)
        if k in need.get(info[0], ()):
            d = acc.setdefault(uid, {})
            d[k] = d.get(k, 0) + (votes or 0)
        if progress and n % 1000000 == 0:
            log.info("booth_party: scanned %d vote rows ...", n)

    booths = [(ac, str(ps)) for ac, ps in cur.execute("SELECT ac, ps FROM booth_row")]
    con.executescript(DDL)
    rows: list = []
    zone_n: dict = {}
    bad_uids: set = set()
    for p in parties:
        for ac, ps in booths:
            bkey, _src = opp.get((p, ac), ("", ""))
            seatv = seat.get(ac, {})
            vals = []
            opps = []
            diffs = []
            for e in ELECTIONS:
                uid = by_key.get((ac, e, ps))
                polled = uid_info[uid][3] if uid else None
                valid = uid_info[uid][4] if uid else None
                if uid and polled and (polled < MIN_POLLED or (valid is not None and polled < valid)):
                    polled = None                  # a mis-read turnout cell: the booth has no usable share this election
                    bad_uids.add(uid)
                tot_e = sum(seatv.get(e, {}).values())
                stood_a = tot_e > 0 and seatv.get(e, {}).get(p, 0) / tot_e >= MIN_STOOD_SHARE
                okey = opp_e.get((p, ac, e), "")         # B, or the strongest other party where B did not stand
                stood_b = bool(okey)
                a = b = d = None
                if uid and polled and not flags.get((ac, e), False):
                    if stood_a:
                        a = round(acc.get(uid, {}).get(p, 0) / polled, 4)
                    if stood_b:
                        b = round(acc.get(uid, {}).get(okey, 0) / polled, 4)
                    if (a is not None and a > 1.0) or (b is not None and b > 1.0):
                        a = b = None               # more votes than voters
                        bad_uids.add(uid)
                    if a is not None and b is not None:
                        d = round(a - b, 4)
                vals += [a, b, d]
                opps.append(okey if b is not None else None)
                diffs.append(d)
            zone, avg, latest = zone_of(diffs)
            if zone == "Data Not sufficient":
                avg = latest = None   # one election is not an average; keeps the seat-level zone honest
            zone_n[(p, zone)] = zone_n.get((p, zone), 0) + 1
            rows.append((p, ac, ps, bkey, zone, round(avg, 4) if avg is not None else None,
                         round(latest, 4) if latest is not None else None, *vals, *opps))
            if len(rows) >= 20000:
                cur.executemany("INSERT INTO booth_party VALUES (" + ",".join("?" * 23) + ")", rows)
                rows = []
    if rows:
        cur.executemany("INSERT INTO booth_party VALUES (" + ",".join("?" * 23) + ")", rows)
    con.executescript(INDEXES)

    # coverage: in how many seats did each party stand, per election
    cov = {p: {e: sum(1 for ac, ev in seat.items() if sum(ev.get(e, {}).values()) > 0
                      and ev.get(e, {}).get(p, 0) / sum(ev.get(e, {}).values()) >= MIN_STOOD_SHARE) for e in ELECTIONS} for p in parties}
    meta = {"parties": json.dumps([{"party": p, "label": LABELS.get(p, p)} for p in parties]),
            "party_coverage": json.dumps(cov),
            "label_flags": json.dumps(label_flags),
            "zone_rule": json.dumps({"safe_up": SAFE_UP, "difficult_down": DIFF_DOWN,
                                     "min_elections": 2})}
    for k, v in meta.items():
        cur.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (k, v))
    con.commit()
    stats = {"label_flags": {e: len(v) for e, v in label_flags.items()}, "parties": parties, "booths": len(booths), "unusable_booth_rows": len(bad_uids), "rows": len(booths) * len(parties), "vote_rows": n,
             "zones": {f"{p}/{z}": c for (p, z), c in sorted(zone_n.items())}, "seconds": round(time.time() - t0, 1)}
    log.info("booth_party built: %s", stats)
    return stats
