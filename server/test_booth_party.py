"""Tests for the party-selectable booth dashboard API (server/app.py + Scripts/serve/booth_party.py).

Run from the repo root:  python -m pytest server/test_booth_party.py -q
They build a tiny synthetic store (two seats, six booths each) in a temp folder, so the real 300 MB store is not needed.

Seat 1: the BJP leads every booth by 14 to 34 points in all three elections; the SP is second, the BSP third; the INC
never stood. Seat 2 is close: the BJP and SP swap the lead (diffs -0.03, +0.06, -0.02); the INC stood in 2017 only.
"""
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SERVE = ROOT / "Scripts" / "serve"
pytestmark = pytest.mark.skipif(not (SERVE / "booth_party.py").is_file(), reason="Scripts/serve is not in this folder")
sys.path.insert(0, str(HERE))
if SERVE.is_dir():
    sys.path.insert(0, str(SERVE))
import app as app_module  # noqa: E402

DEMO = ["electors_17", "hindu_percent_17", "muslim_percent_17", "christian_percent_17", "sikh_percent_17", "jain_percent_17",
        "buddhist_percent_17", "parsi_percent_17"]
ELECTIONS = ["VS2017", "LS2019", "VS2022"]
NAMES = {1: ["Alpha School", "Beta School", "Gamma Hall", "Delta Hall", "Epsilon Office", "Zeta Office"],
         2: ["Eta School", "Theta School", "Iota Hall", "Kappa Hall", "Lambda Office", "Mu Office"],
         3: ["Nu School", "Xi School", "Omicron Hall", "Pi Hall", "Rho Office", "Sigma Office"],
         4: ["Tau School", "Upsilon School", "Phi Hall", "Chi Hall", "Psi Office", "Omega Office"]}


def votes_for(ac, e, k):
    """{party: votes} for booth k (1..6) of seat ac in election e; every booth polls 100."""
    if ac == 1:
        bjp = 50 + 2 * k
        return {"BJP": bjp, "SP": 90 - bjp, "BSP": 10}
    if ac == 4:   # seat 4: the SP's ally (INC) took the seat in 2017, the BSP in 2019; the SP itself stood only in 2022
        return {"VS2017": {"BJP": 50, "INC": 40, "BSP": 10}, "LS2019": {"BJP": 55, "BSP": 45},
                "VS2022": {"BJP": 55, "SP": 30, "BSP": 15}}[e]
    if ac == 3:   # seat 3: the 2017 sheet's party column failed to read, so the winner's votes sit under "IND"
        return {"VS2017": {"IND": 60, "SP": 30, "BSP": 10}, "LS2019": {"BJP": 55, "SP": 35, "BSP": 10},
                "VS2022": {"BJP": 60, "SP": 30, "BSP": 10}}[e]
    return {"VS2017": {"BJP": 46, "SP": 49, "INC": 5}, "LS2019": {"BJP": 53, "SP": 47},
            "VS2022": {"BJP": 49, "SP": 51}}[e]


def make_store(path, party_view=True, bad_seat=False, alliance_seat=False):
    bs = importlib.import_module("build_servedb")
    bp = importlib.import_module("booth_party")
    con = sqlite3.connect(str(path))
    demo_ddl = ",\n  ".join(f'"{c}" REAL' for c in DEMO)
    con.executescript(bs.SCHEMA.format(demo_cols=demo_ddl + ","))
    cur = con.cursor()
    seats = (1, 2) + ((3,) if bad_seat else ()) + ((4,) if alliance_seat else ())
    for ac in seats:
        for k in range(1, 7):
            # a distinctive "workbook" zone so a store without booth_party can be told apart
            cur.execute("INSERT INTO booth_row (ac, ps, district, name, address, zone, avg_diff, latest_diff, party_b, a2017, "
                        "electors_17, hindu_percent_17) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ac, str(k), "Testpur", f"{k} - {NAMES[ac][k - 1]}", NAMES[ac][k - 1], "Safe", 0.5, 0.5, "SP", 0.77,
                         200, 80.0))
            for e in ELECTIONS:
                if ac == 1 and k == 6 and e == "LS2019":
                    continue            # booth 6 has no 2019 row
                uid = f"{e}-{ac:03d}-{k}"
                cur.execute("INSERT INTO booth_election VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (uid, e, ac, str(k), NAMES[ac][k - 1], 200, 60, 40, 0, 0, 0, 100, 100, 0, "t.xls"))
                for p, v in votes_for(ac, e, k).items():
                    cur.execute("INSERT INTO vote VALUES (?,?,?,?)", (uid, f"{p} candidate", p, v))
    for ac in seats:
        for e in ELECTIONS:
            cur.execute("INSERT INTO ac_summary VALUES (?,?,?,?,?,?,?,?,?,?)", (ac, e, f"Seat {ac}", "Testpur", 6, 1200, 600, 600, 0, 50.0))
    cur.execute("INSERT INTO ac_party SELECT b.ac, b.election, v.party, SUM(v.votes) FROM vote v "
                "JOIN booth_election b ON v.booth_uid = b.booth_uid GROUP BY b.ac, b.election, v.party")
    cur.execute("INSERT INTO ac_zones SELECT ac, zone, COUNT(*) FROM booth_row GROUP BY ac, zone")
    cur.execute("INSERT INTO coverage (election, ac, ac_name, file, booths, valid_ok, has_total, note) VALUES ('VS2017','1','','f','6','','','')")
    cur.execute("INSERT INTO booth_fts(ac, ps, name, district) SELECT ac, ps, name, district FROM booth_row")
    cur.execute("INSERT INTO meta VALUES ('demo_cols', ?)", ('["' + '","'.join(DEMO) + '"]',))
    con.commit()
    stats = bp.build_booth_party(con, progress=False) if party_view else None
    con.commit()
    con.close()
    return stats


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "MIN_VOTES", 100)       # the real cut-off (2,000) would hide the tiny test seats
    def build(party_view=True, bad_seat=False, alliance_seat=False):
        db = tmp_path / ("view.sqlite" if party_view else "legacy.sqlite")
        make_store(db, party_view, bad_seat, alliance_seat)
        monkeypatch.setattr(app_module, "DB_PATH", str(db))
        app_module._CACHE.clear()
        app_module._ROLL.clear()
        app_module._BAD.clear()
        app_module._STORE_FLAGS.clear()
        app_module._VALID_COLS = None
        return TestClient(app_module.app)
    yield build
    app_module._CACHE.clear()
    app_module._ROLL.clear()
    app_module._BAD.clear()
    app_module._STORE_FLAGS.clear()
    app_module._VALID_COLS = None


def booths(client, **q):
    r = client.get("/api/booths", params=q)
    assert r.status_code == 200, r.text
    return r.json()


# ---- rules ---------------------------------------------------------------------------------------------------------

def test_party_key_matches_the_server_spelling_rules():
    bp = importlib.import_module("booth_party")
    for raw in ["BJP", "B.J.P.", "BHARATIYA JANATA PARTY", "Samajwadi Party", "SP", "BAHUJAN SAMAJ PARTY", "INC",
                "Indian National Congress", "APNA DAL (S)", "SUHELDEV BHARATIYA SAMAJ PARTY", "SBSP", "RASHTRIYA LOK DAL",
                "RLD", "IND", "NOTA", "", None, "candidate-name"]:
        assert bp.party_key(raw) == app_module._norm_party(raw), raw


def test_zone_rule():
    bp = importlib.import_module("booth_party")
    assert bp.zone_of([None, None, None, None])[0] == "Data Not sufficient"
    assert bp.zone_of([0.5, None, None, None])[0] == "Data Not sufficient"       # one election is not enough
    assert bp.zone_of([0.2, 0.15, 0.3, None])[0] == "Safe"
    assert bp.zone_of([-0.2, -0.15, -0.3, None])[0] == "Difficult"
    assert bp.zone_of([0.05, 0.02, 0.03, None])[0] == "Favorable"                 # positive but not above +0.10
    assert bp.zone_of([0.3, 0.3, -0.01, None])[0] == "Battlefield"                # lost the latest one
    z, avg, latest = bp.zone_of([None, 0.1, None, -0.1])
    assert (z, round(avg, 4), latest) == ("Battlefield", 0.0, -0.1)


def test_opponent_is_the_strongest_other_party():
    bp = importlib.import_module("booth_party")
    sv = {"VS2022": {"BJP": 100, "SP": 80, "BSP": 90, "NOTA": 500}, "LS2024": {"BJP": 1, "INC": 9}}
    assert bp.choose_party_b(sv, "BJP") == ("BSP", "VS2022")           # NOTA never counts
    assert bp.choose_party_b(sv, "BSP") == ("BJP", "VS2022")
    assert bp.choose_party_b({"LS2024": {"BJP": 1, "INC": 9}}, "BJP") == ("INC", "LS2024*")   # falls back, marked
    assert bp.choose_party_b({}, "BJP") == ("", "")


# ---- the built table -----------------------------------------------------------------------------------------------

def test_build_counts_and_shares(api):
    c = api()
    row = booths(c, ac=1, party="BJP", sort="ps")["rows"][0]
    assert row["ps"] == "1" and row["party_b"] == "SP"
    assert row["a2017"] == 0.52 and row["b2017"] == 0.38 and row["d2017"] == 0.14      # 52 / 100, 38 / 100
    assert row["a2024"] is None and row["d2024"] is None                              # no 2024 booth data: empty, not 0
    assert row["zone"] == "Safe" and row["avg_diff"] == 0.14 and row["latest_diff"] == 0.14


def test_a_party_that_did_not_stand_shows_nothing_not_zero(api):
    c = api()
    rows = booths(c, ac=1, party="INC")["rows"]
    assert {r["zone"] for r in rows} == {"Data Not sufficient"}
    assert all(r["a2017"] is None and r["d2017"] is None and r["avg_diff"] is None for r in rows)
    # standing in one election only is not enough for a zone
    rows2 = booths(c, ac=2, party="INC")["rows"]
    assert {r["zone"] for r in rows2} == {"Data Not sufficient"}
    assert rows2[0]["a2017"] == 0.05 and rows2[0]["a2019"] is None and rows2[0]["party_b"] == "SP"
    assert rows2[0]["avg_diff"] is None and rows2[0]["d2017"] == -0.44               # one election: a difference, but no average


def test_same_booths_look_different_from_each_party(api):
    c = api()
    bjp = booths(c, ac=1, party="BJP")["rows"]
    sp = booths(c, ac=1, party="SP")["rows"]
    bsp = booths(c, ac=1, party="BSP")["rows"]
    assert {r["zone"] for r in bjp} == {"Safe"} and {r["party_b"] for r in bjp} == {"SP"}
    assert {r["zone"] for r in sp} == {"Difficult"} and {r["party_b"] for r in sp} == {"BJP"}
    assert {r["zone"] for r in bsp} == {"Difficult"} and {r["party_b"] for r in bsp} == {"BJP"}
    assert sp[0]["d2017"] == -0.14 and bjp[0]["d2017"] == 0.14                          # mirror images
    close = booths(c, ac=2, party="BJP")["rows"]
    assert {r["zone"] for r in close} == {"Battlefield"}
    assert [close[0][k] for k in ("d2017", "d2019", "d2022")] == [-0.03, 0.06, -0.02]
    assert {r["zone"] for r in booths(c, ac=2, party="SP")["rows"]} == {"Battlefield"}


def test_default_party_is_the_bjp_and_names_are_case_insensitive(api):
    c = api()
    assert booths(c, ac=1)["party"] == "BJP"
    assert booths(c, ac=1, party="sp")["party"] == "SP"
    assert booths(c, ac=1)["rows"][0]["zone"] == "Safe"


def test_unknown_party_is_refused_with_the_choices(api):
    c = api()
    for path in ("/api/booths?ac=1&party=XYZ", "/api/overview?party=XYZ", "/api/trend?party=XYZ", "/api/zones?party=XYZ",
                 "/api/ac/1/past?party=XYZ", "/api/booth/1/1?party=XYZ"):
        r = c.get(path)
        assert r.status_code == 400 and "BJP" in r.json()["detail"], path


# ---- filters, sorting, search --------------------------------------------------------------------------------------

def test_zone_and_opponent_filters_follow_the_party(api):
    c = api()
    assert booths(c, ac=1, party="BJP", zone="Safe")["total"] == 6
    assert booths(c, ac=1, party="BJP", zone="Difficult")["total"] == 0
    assert booths(c, ac=1, party="SP", zone="Difficult")["total"] == 6
    assert booths(c, ac=1, party="SP", opponent="bjp")["total"] == 6                   # BJP is SP's strongest opponent
    assert booths(c, ac=1, party="BJP", opponent="BJP")["total"] == 0
    assert booths(c, ac=1, party="INC", zone="Data Not sufficient")["total"] == 6


def test_sorting_uses_the_party_columns(api):
    c = api()
    desc = [r["ps"] for r in booths(c, ac=1, party="BJP", sort="avg_diff", order="desc")["rows"]]
    asc_sp = [r["ps"] for r in booths(c, ac=1, party="SP", sort="avg_diff", order="asc")["rows"]]
    assert desc == ["6", "5", "4", "3", "2", "1"]          # the BJP's best booth is booth 6
    assert asc_sp == desc                                    # the SP's worst booth is the same booth
    assert [r["ps"] for r in booths(c, ac=1, party="BJP", sort="d2017", order="asc")["rows"]][0] == "1"


def test_search_and_constituency_together(api):
    c = api()
    out = booths(c, ac=2, q="School", party="SP")
    assert out["total"] == 2 and {r["ps"] for r in out["rows"]} == {"1", "2"}           # not seat 1's schools
    assert booths(c, q="Alpha")["total"] == 1                                            # search on its own still works


def test_booth_detail_carries_the_party_view(api):
    c = api()
    r = c.get("/api/booth/1/3", params={"party": "SP"}).json()
    assert r["party"] == "SP" and r["row"]["zone"] == "Difficult" and r["row"]["party_b"] == "BJP"
    assert r["row"]["d2022"] == -0.22 and len(r["elections"]) == 3 and set(r["votes"]) == set(ELECTIONS)


# ---- dashboard rollups ---------------------------------------------------------------------------------------------

def test_overview_is_seen_from_the_chosen_party(api):
    c = api()
    o_bjp = c.get("/api/overview", params={"election": "VS2022", "vs": "VS2017"}).json()
    o_sp = c.get("/api/overview", params={"election": "VS2022", "vs": "VS2017", "party": "SP"}).json()
    assert o_bjp["party"] == "BJP" and o_sp["party"] == "SP"
    assert o_bjp["seats"] == o_sp["seats"]                                               # seat table lists every party
    # VS2022: the BJP leads seat 1 (all six booths), the SP leads seat 2 (51 to 49 in every booth)
    assert {s["party"]: s["seats"] for s in o_bjp["seats"]} == {"BJP": 1, "SP": 1}
    # share: BJP votes / all votes in VS2022 = (sum 52..62 + 6*49) / 1200
    bjp_votes = sum(50 + 2 * k for k in range(1, 7)) + 6 * 49
    assert o_bjp["avg_share"] == round(100.0 * bjp_votes / 1200, 2)
    sp_votes = sum(90 - (50 + 2 * k) for k in range(1, 7)) + 6 * 51
    assert o_sp["avg_share"] == round(100.0 * sp_votes / 1200, 2)
    zone_of = {z["zone"]: z["members"] for z in o_bjp["ac_zones"]}
    assert zone_of["Safe"] == [1] and zone_of["Battlefield"] == [2]
    zone_sp = {z["zone"]: z["members"] for z in o_sp["ac_zones"]}
    assert zone_sp["Difficult"] == [1] and zone_sp["Battlefield"] == [2]
    assert {z["zone"]: z["booths"] for z in o_bjp["booth_zones"]}["Safe"] == 6
    assert {z["zone"]: z["booths"] for z in o_sp["booth_zones"]}["Difficult"] == 6


def test_overview_best_and_least_only_count_seats_the_party_stood_in(api):
    c = api()
    o = c.get("/api/overview", params={"election": "VS2022", "vs": "VS2017", "party": "INC"}).json()
    dns = next(z for z in o["ac_zones"] if z["zone"] == "Data Not sufficient")
    assert dns["acs"] == 2 and dns["best"] is None and dns["worst"] is None             # INC stood in neither in VS2022
    o2 = c.get("/api/overview", params={"election": "VS2017", "vs": "VS2022", "party": "INC"}).json()
    dns2 = next(z for z in o2["ac_zones"] if z["zone"] == "Data Not sufficient")
    assert dns2["best"]["ac"] == 2 and dns2["best"]["share"] == 5.0 and dns2["worst"]["ac"] == 2


def test_top_booth_is_the_partys_own(api):
    c = api()
    o = c.get("/api/overview", params={"election": "VS2022", "vs": "VS2017"}).json()
    top = next(z for z in o["booth_zones"] if z["zone"] == "Safe")["top"]
    assert top["ac"] == 1 and top["ps"] == "6" and top["share"] == 62.0 and top["share_vs"] == 62.0
    osp = c.get("/api/overview", params={"election": "VS2022", "vs": "VS2017", "party": "SP"}).json()
    top_sp = next(z for z in osp["booth_zones"] if z["zone"] == "Difficult")["top"]
    assert top_sp["ps"] == "1" and top_sp["share"] == 38.0


def test_trend_zones_and_past_follow_the_party(api):
    c = api()
    t = c.get("/api/trend", params={"party": "SP"}).json()
    assert t["party"] == "SP"
    by = {r["election"]: r for r in t["rows"]}
    assert by["VS2022"]["seats"] == 1 and by["VS2022"]["share"] == round(100.0 * (sum(90 - (50 + 2 * k) for k in range(1, 7)) + 6 * 51) / 1200, 2)
    assert all("bjp_share" not in r for r in t["rows"])
    z = {r["zone"]: r["n"] for r in c.get("/api/zones", params={"party": "SP"}).json()["zones"]}
    assert z == {"Difficult": 6, "Battlefield": 6}
    zd = {r["zone"]: r["n"] for r in c.get("/api/zones", params={"party": "BJP", "district": "Testpur"}).json()["zones"]}
    assert zd == {"Safe": 6, "Battlefield": 6}
    p = c.get("/api/ac/1/past", params={"party": "SP"}).json()
    r22 = next(r for r in p["rows"] if r["election"] == "VS2022")
    assert p["party"] == "SP" and r22["party_votes"] == sum(90 - (50 + 2 * k) for k in range(1, 7))
    assert r22["party_share"] == round(100.0 * sum(90 - (50 + 2 * k) for k in range(1, 7)) / 600, 2)


def test_meta_lists_the_parties_and_coverage(api):
    c = api()
    m = c.get("/api/meta").json()
    assert m["party_view"] is True and m["default_party"] == "BJP" and m["parties"] == ["BJP", "SP", "BSP", "INC"]
    cov = m["party_coverage"]
    assert cov["BJP"] == {"VS2017": 2, "LS2019": 2, "VS2022": 2, "LS2024": 0}
    assert cov["INC"]["VS2017"] == 1 and cov["INC"]["VS2022"] == 0 and cov["BSP"]["VS2022"] == 1
    assert m["zone_rule"]["safe_up"] == 0.1


def test_methods_explains_the_rule(api):
    c = api()
    t = c.get("/api/methods").json()["party_rule"]
    assert "strongest other party" in t and "did not" in t


# ---- a store built before the party view existed -------------------------------------------------------------------

def test_old_store_still_serves_the_bjp_view_and_says_how_to_upgrade(api):
    c = api(party_view=False)
    m = c.get("/api/meta").json()
    assert m["party_view"] is False and m["parties"] == ["BJP"]
    r = booths(c, ac=1)                                                                  # workbook columns, untouched
    assert r["rows"][0]["zone"] == "Safe" and r["rows"][0]["party_b"] == "SP" and r["rows"][0]["a2017"] == 0.77
    bad = c.get("/api/booths", params={"ac": 1, "party": "SP"})
    assert bad.status_code == 400 and "add_booth_party" in bad.json()["detail"]
    assert c.get("/api/overview", params={"election": "VS2022", "vs": "VS2017"}).status_code == 200
    assert booths(c, ac=2, q="School")["total"] == 2


def test_build_is_repeatable(tmp_path):
    bp = importlib.import_module("booth_party")
    db = tmp_path / "again.sqlite"
    make_store(db)
    con = sqlite3.connect(str(db))
    first = con.execute("SELECT COUNT(*), SUM(avg_diff) FROM booth_party").fetchone()
    stats = bp.build_booth_party(con, progress=False)
    second = con.execute("SELECT COUNT(*), SUM(avg_diff) FROM booth_party").fetchone()
    con.close()
    assert first == second and stats["rows"] == 12 * 4


# ---- seats whose party labels are unreadable -----------------------------------------------------------------------

def test_label_guard_rule():
    bp = importlib.import_module("booth_party")
    assert bp.labels_ok({"BJP": 70, "IND": 24, "SP": 6})                       # 24% lumped independents is normal
    assert not bp.labels_ok({"BJP": 5, "IND": 60, "SP": 35})                   # the winner's votes sit under IND
    assert not bp.labels_ok({"BLANK": 30, "SP": 70}) and not bp.labels_ok({"UNMAPPED": 26, "SP": 74})
    assert not bp.labels_ok({})
    # IND is never the opponent, even when it is the second-largest label
    assert bp.choose_party_b({"VS2022": {"BJP": 50, "IND": 20, "SP": 15}}, "BJP") == ("SP", "VS2022")


def test_a_seat_with_unreadable_labels_is_left_out_not_guessed(api):
    c = api(bad_seat=True)
    # the party view: seat 3's 2017 shares are empty for everyone, 2019 and 2022 still count
    row = booths(c, ac=3, party="BJP")["rows"][0]
    assert row["a2017"] is None and row["d2017"] is None and row["a2019"] == 0.55 and row["a2022"] == 0.6
    assert row["zone"] == "Safe" and row["party_b"] == "SP"
    assert booths(c, ac=3, party="SP")["rows"][0]["a2017"] is None
    meta = c.get("/api/meta").json()
    assert meta["label_flags"] == {"VS2017": 1, "LS2019": 0, "VS2022": 0, "LS2024": 0}
    # the seat counts: seat 3 is not a seat won by "IND"
    o = c.get("/api/overview", params={"election": "VS2017", "vs": "VS2022"}).json()
    assert {s["party"]: s["seats"] for s in o["seats"]} == {"BJP": 1, "SP": 1} and o["seats_counted"] == 2
    assert any("left out of VS2017" in n for n in o["notes"])
    assert o["avg_share"] == round(100.0 * (sum(50 + 2 * k for k in range(1, 7)) + 6 * 46) / 1200, 2)   # seat 3 not in the shares
    assert o["ac_shares"]["3"][0] is None and o["ac_shares"]["3"][1] is not None
    assert o["party_stood"] == 2
    # in 2022 it is a normal seat again
    o22 = c.get("/api/overview", params={"election": "VS2022", "vs": "VS2017"}).json()
    assert {s["party"]: s["seats"] for s in o22["seats"]} == {"BJP": 2, "SP": 1}
    t = {r["election"]: r for r in c.get("/api/trend").json()["rows"]}
    assert t["VS2017"]["seats"] == 1 and t["VS2017"]["seats_counted"] == 2 and t["VS2022"]["seats"] == 2
    past = {r["election"]: r for r in c.get("/api/ac/3/past").json()["rows"]}
    assert past["VS2017"]["labels_unreadable"] is True and past["VS2017"]["winner"] is None and past["VS2017"]["parties"] == []
    assert past["VS2022"]["labels_unreadable"] is False and past["VS2022"]["winner"] == "BJP"


# ---- booth rows whose turnout figure cannot be right ---------------------------------------------------------------

def test_a_booth_with_an_impossible_turnout_figure_has_no_share(tmp_path):
    bp = importlib.import_module("booth_party")
    db = tmp_path / "bad.sqlite"
    make_store(db, party_view=False)
    con = sqlite3.connect(str(db))
    con.execute("UPDATE booth_election SET polled=5 WHERE booth_uid='VS2017-001-3'")     # 5 voters, 100 valid votes
    con.execute("UPDATE booth_election SET polled=12, valid=12 WHERE booth_uid='VS2022-001-4'")   # fewer than 20 voters
    con.commit()
    stats = bp.build_booth_party(con, progress=False)
    b3 = con.execute("SELECT a2017, b2017, d2017, a2019, a2022, zone FROM booth_party WHERE party='BJP' AND ac=1 AND ps='3'").fetchone()
    b4 = con.execute("SELECT a2017, a2022, d2022, zone FROM booth_party WHERE party='BJP' AND ac=1 AND ps='4'").fetchone()
    con.close()
    assert b3[:3] == (None, None, None) and b3[3] == 0.56 and b3[4] == 0.56 and b3[5] == "Safe"     # still two usable elections
    assert b4[0] == 0.58 and b4[1] is None and b4[2] is None and b4[3] == "Safe"     # booth 4 keeps 2017 and 2019, so still a zone
    assert stats["unusable_booth_rows"] == 2


def test_no_share_can_exceed_one_hundred_percent(tmp_path):
    bp = importlib.import_module("booth_party")
    db = tmp_path / "over.sqlite"
    make_store(db, party_view=False)
    con = sqlite3.connect(str(db))
    con.execute("UPDATE vote SET votes=140 WHERE booth_uid='VS2022-002-2' AND party='BJP'")   # more votes than the 100 who polled
    con.commit()
    bp.build_booth_party(con, progress=False)
    over = con.execute("SELECT COUNT(*) FROM booth_party WHERE a2017>1 OR b2017>1 OR a2019>1 OR b2019>1 OR a2022>1 OR b2022>1").fetchone()[0]
    row = con.execute("SELECT a2022, b2022, d2022 FROM booth_party WHERE party='BJP' AND ac=2 AND ps='2'").fetchone()
    con.close()
    assert over == 0 and row == (None, None, None)


# ---- a few stray votes do not make a party a candidate ---------------------------------------------------------------

def test_stray_votes_under_a_label_do_not_count_as_standing(tmp_path, monkeypatch):
    bp = importlib.import_module("booth_party")
    db = tmp_path / "stray.sqlite"
    make_store(db, party_view=False)
    con = sqlite3.connect(str(db))
    for k in range(1, 4):                    # seat 1, 2017: three stray INC votes among 600 (0.5%); INC never stood there
        con.execute("INSERT INTO vote VALUES (?,?,?,?)", (f"VS2017-001-{k}", "INC stray", "INC", 1))
    con.execute("DELETE FROM ac_party")
    con.execute("INSERT INTO ac_party SELECT b.ac, b.election, v.party, SUM(v.votes) FROM vote v JOIN booth_election b ON v.booth_uid = b.booth_uid GROUP BY b.ac, b.election, v.party")
    con.commit()
    stats = bp.build_booth_party(con, progress=False)
    rows = con.execute("SELECT a2017, zone FROM booth_party WHERE party='INC' AND ac=1").fetchall()
    meta = dict(con.execute("SELECT key, value FROM meta"))
    con.close()
    assert all(a is None for a, _z in rows) and {z for _a, z in rows} == {"Data Not sufficient"}
    assert json.loads(meta["party_coverage"])["INC"]["VS2017"] == 1                                   # only seat 2
    # and the server agrees
    monkeypatch.setattr(app_module, "DB_PATH", str(db))
    monkeypatch.setattr(app_module, "MIN_VOTES", 100)
    for d in (app_module._CACHE, app_module._ROLL, app_module._BAD, app_module._STORE_FLAGS):
        d.clear()
    app_module._VALID_COLS = None
    c = TestClient(app_module.app)
    o = c.get("/api/overview", params={"election": "VS2017", "vs": "VS2022", "party": "INC"}).json()
    assert o["party_stood"] == 1 and o["ac_shares"]["1"][0] is None and o["ac_shares"]["2"][0] == 5.0
    for d in (app_module._CACHE, app_module._ROLL, app_module._BAD, app_module._STORE_FLAGS):
        d.clear()
    app_module._VALID_COLS = None


# ---- the opponent where the usual one did not stand ------------------------------------------------------------------

def test_where_the_usual_opponent_did_not_stand_the_strongest_other_party_is_used(api):
    c = api(alliance_seat=True)
    r = booths(c, ac=4, party="BJP")["rows"][0]
    assert r["party_b"] == "SP"                                                    # the reference opponent: strongest in 2022
    assert (r["opp2017"], r["opp2019"], r["opp2022"], r["opp2024"]) == ("INC", "BSP", "SP", None)
    assert (r["b2017"], r["b2019"], r["b2022"]) == (0.4, 0.45, 0.3)
    assert (r["d2017"], r["d2019"], r["d2022"]) == (0.1, 0.1, 0.25)                # three comparisons, not one
    assert r["zone"] == "Safe" and r["avg_diff"] == 0.15 and r["latest_diff"] == 0.25
    sp = booths(c, ac=4, party="SP")["rows"][0]                                    # from the SP's side: it stood only in 2022
    assert sp["a2017"] is None and sp["a2019"] is None and sp["a2022"] == 0.3 and sp["zone"] == "Data Not sufficient"
    # a seat where the usual opponent stood in every election keeps it
    r2 = booths(c, ac=1, party="BJP")["rows"][0]
    assert (r2["opp2017"], r2["opp2019"], r2["opp2022"]) == ("SP", "SP", "SP")


# ---- the verified-workbook filter of the booth report builder --------------------------------------------------------

def test_a_workbook_changed_since_it_was_verified_is_skipped(tmp_path):
    import hashlib
    sys.path.insert(0, str(ROOT))
    bsr = importlib.import_module("Scripts.report.build_state_report")
    files = []
    for ac, data in ((10, b"verified bytes"), (11, b"an OLDER version of the workbook"), (12, b"never verified")):
        f = tmp_path / f"{ac}.xlsx"
        f.write_bytes(data)
        files.append(f)
    verified = tmp_path / "booth_segments.json"
    verified.write_text(json.dumps({"meta": {"source_sha256": {"10": hashlib.sha256(b"verified bytes").hexdigest(),
                                                               "11": hashlib.sha256(b"the version that was checked").hexdigest()}},
                                    "acs": {"10": {}, "11": {}}}), encoding="utf-8")
    kept, skipped = bsr.select_verified_2024(files, verified)
    assert [p.stem for p in kept] == ["10"]
    why = {p.stem: w for p, w in skipped}
    assert why["11"].startswith("SKIPPED-CHANGED") and why["12"].startswith("SKIPPED-UNVERIFIED")
    # a verified list without fingerprints (an older file) falls back to the seat list alone
    verified.write_text(json.dumps({"meta": {}, "acs": {"10": {}, "11": {}}}), encoding="utf-8")
    kept2, _ = bsr.select_verified_2024(files, verified)
    assert [p.stem for p in kept2] == ["10", "11"]
