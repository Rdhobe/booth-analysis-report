"""Tests for the additional insights endpoints. Run from the repo root:  python -m pytest server/test_insights_extra.py -q

Needs server/insights_data/{extra_insights,simulator_inputs,booth_segments,extra_model_card}.json
(python Scripts/ml/build_extra.py --export-server).
"""
import random
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import app as app_module  # noqa: E402
import insights  # noqa: E402

client = TestClient(app_module.app)
FR5 = ["NDA", "SPF", "INC", "BSP", "OTH"]
NEEDED = ["extra_insights.json", "simulator_inputs.json", "booth_segments.json", "extra_model_card.json"]
pytestmark = pytest.mark.skipif(not all((HERE / "insights_data" / f).is_file() for f in NEEDED), reason="run Scripts/ml/build_extra.py --export-server first")


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.delenv("COMPLIANCE_MODE", raising=False)
    insights._STATE.clear()
    insights._extra.reset()
    yield
    insights._STATE.clear()
    insights._extra.reset()


def sim(**body):
    r = client.post("/api/insights/simulate", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_extra_meta_says_what_is_built():
    m = client.get("/api/insights/extra/meta").json()
    assert all(m["available"].values()), m
    assert m["booths"]["seats_covered"] > 0 and m["limits"]
    assert "DRAFT" in m["region_status"]
    assert client.get("/api/insights/meta").json()["extra_available"] is True


def test_watchlist_is_ranked_filterable_and_carries_its_evidence():
    r = client.get("/api/insights/watchlist?limit=403").json()
    assert r["total"] == 403 and [x["rank"] for x in r["rows"]] == list(range(1, 404))
    assert sum(r["band_counts"].values()) == 403 and set(r["band_counts"]) == {"Highest", "High", "Moderate", "Lower"}
    scores = [x["score"] for x in r["rows"]]
    assert scores == sorted(scores, reverse=True)
    b = r["backtest"]["transitions"]["VS2017->VS2022"]
    assert b["flips"] == 106 and b["scores"]["rule"]["auc"] > 0.75
    assert r["backtest"]["decision"]["used"] == "rule"
    hi = client.get("/api/insights/watchlist?band=Highest&limit=403").json()
    assert hi["total"] == r["band_counts"]["Highest"] and all(x["band"] == "Highest" for x in hi["rows"])
    assert client.get("/api/insights/watchlist?q=etmadpur").json()["total"] == 1


def test_watch_bands_separate_in_the_backtest():
    bands = client.get("/api/insights/watchlist").json()["backtest"]["bands"]["VS2017->VS2022"]
    rates = [b["flip_rate"] for b in bands]
    assert rates == sorted(rates, reverse=True) and rates[0] >= 0.5 and rates[-1] <= 0.15       # Highest ... Lower


def test_seat_record_gets_the_extra_block_and_compliance_hides_only_the_watch_score(monkeypatch):
    a = client.get("/api/insights/ac/86").json()
    assert a["extra"]["watch"]["band"] in {"Highest", "High", "Moderate", "Lower"} and a["extra"]["turnout"]["LS2024"]["expected"]
    assert a["extra"]["booths"]["available"] is False                               # Etmadpur's 2024 workbook is not in the verified set
    assert client.get("/api/insights/ac/1").json()["extra"]["booths"]["available"] is True
    monkeypatch.setenv("COMPLIANCE_MODE", "on")
    a = client.get("/api/insights/ac/86").json()
    assert a["extra"]["watch"] is None and "Compliance Mode" in a["extra"]["watch_hidden"]
    assert a["extra"]["turnout"]["LS2024"]["expected"]                              # backward-looking: still served


def test_turnout_gap_table():
    t = client.get("/api/insights/turnout").json()
    assert len(t["rows"]) == 403
    ls = t["targets"]["LS2024"]
    assert ls["promoted"] and ls["cv_mae_pts"]["ridge"] < ls["cv_mae_pts"]["persistence_plus_statewide_change"]
    known = [r["turnout"]["LS2024"] for r in t["rows"] if r["turnout"]["LS2024"]["gap_pts"] is not None]
    assert len(known) >= 400 and abs(sum(k["gap_pts"] for k in known) / len(known)) < 0.2            # gaps centre on zero
    assert sum(1 for k in known if k["flag"]) < 0.15 * len(known)


def test_alliance_estimates_are_between_zero_and_one_with_intervals():
    a = client.get("/api/insights/alliances").json()
    assert len(a["groups"]) == 4
    for g in a["groups"]:
        lo, hi = g["transfer_interval"]
        assert 0 <= lo <= g["transfer_from_partner"] <= hi <= 1
        assert g["loo_mae_pts"]["fitted"] <= g["loo_mae_pts"]["partner_votes_none_transfer"]
    assert set(a["defaults"]) == {"BSP_to_SP", "INC_to_SP"}


def test_simulator_setup_and_hindcast_evidence():
    s = client.get("/api/insights/simulator/setup").json()
    assert len(s["regions"]) == 6 and sum(r["seats"] for r in s["regions"]) == 403
    assert {p["id"] for p in s["presets"]} == {"repeat2022", "ls2024"}
    h = s["hindcast"]["pairs"]["VS2017->VS2022"]
    assert 70 < h["regional_swing"]["seats_called_right_pct"] < 85
    pooled = [b["leader_won_pct"] for b in s["hindcast"]["bands"]["pooled"]]
    assert pooled == sorted(pooled)                                                  # wider margin, more reliable leader


def test_repeat_2022_reproduces_the_actual_result():
    r = sim(preset="repeat2022")
    assert r["summary"]["leads"] == {"NDA": 273, "SPF": 125, "INC": 2, "BSP": 1, "OTH": 2}
    assert r["summary"]["flips_vs_2022"] == 0 and len(r["seats"]) == 403


def test_a_swing_moves_seats_in_the_right_direction():
    base = sim(preset="repeat2022")["summary"]["leads"]
    up = sim(swing_all={"NDA": 5.0, "SPF": -5.0})["summary"]
    down = sim(swing_all={"NDA": -5.0, "SPF": 5.0})["summary"]
    assert up["leads"]["NDA"] > base["NDA"] > down["leads"]["NDA"]
    assert down["leads"]["SPF"] > base["SPF"] > up["leads"]["SPF"]
    assert up["flips_vs_2022"] > 0
    for s in (up, down):
        assert sum(s["leads"].values()) == 403
        for f in FR5:
            lo, hi = s["bounds"][f]
            assert lo <= s["leads"][f] <= hi


def test_a_regional_swing_only_touches_that_region():
    r = sim(swings={"Bundelkhand": {"SPF": 15.0, "NDA": -15.0}})
    changed = {s["region"] for s in r["seats"] if s["flips_vs_2022"]}
    assert changed == {4}                                                            # Bundelkhand is region 4 in the draft list


def test_alliance_scenario_merges_the_partner_vote():
    plain = sim(preset="repeat2022")["summary"]["leads"]
    merged = sim(alliance="SP+INC", rate=1.0)["summary"]["leads"]
    assert merged["INC"] == 0 and merged["SPF"] >= plain["SPF"] + plain["INC"]
    bsp = sim(alliance="SP+BSP", rate=1.0)["summary"]["leads"]
    assert bsp["BSP"] == 0 and bsp["SPF"] >= plain["SPF"]
    default_rate = sim(alliance="SP+INC")["assumptions"]["rate"]
    assert 0.5 < default_rate < 1.0                                                  # the estimated rate, not 0 or 1


def test_ls2024_preset_uses_its_own_alliance_and_swings():
    r = sim(preset="ls2024")
    assert r["assumptions"]["alliance"] == "SP+INC" and r["assumptions"]["rate"] == 1.0
    assert r["summary"]["leads"]["SPF"] > 125                                       # the 2024 shift favoured the SP/INC bloc


def test_the_server_simulator_matches_the_numpy_reference():
    ml = HERE.parent / "Scripts" / "ml"
    sys.path.insert(0, str(ml))
    np = pytest.importorskip("numpy")
    ref = pytest.importorskip("models_extra")
    setup = client.get("/api/insights/simulator/setup").json()
    seats = insights._extra  # noqa: F841  (router object kept alive)
    data = __import__("json").loads((HERE / "insights_data" / "simulator_inputs.json").read_text(encoding="utf-8"))["seats"]
    base = np.array([s["base"] for s in data])
    reg = np.array([s["region"] for s in data])
    rng = random.Random(7)
    for _ in range(4):
        sw = np.array([[rng.uniform(-0.08, 0.08) for _ in range(3)] for _ in range(len(setup["regions"]))])
        alliance, rate = rng.choice([(None, 0.0), ("SP+INC", 0.7), ("SP+BSP", 0.5)])
        body = {"swings": {r["name"]: {"NDA": float(sw[i][0] * 100), "SPF": float(sw[i][1] * 100), "BSP": float(sw[i][2] * 100)} for i, r in enumerate(setup["regions"])},
                "alliance": alliance, "rate": rate}
        got = sim(**body)["seats"]
        want = ref.simulate_reference(base, reg, sw, alliance, rate)
        assert [FR5.index(s["lead"]) for s in got] == want["lead"].tolist()
        assert np.allclose([s["margin_pts"] for s in got], want["margin"] * 100, atol=0.06)


def test_bad_inputs_are_refused():
    assert client.post("/api/insights/simulate", json={"preset": "nope"}).status_code == 422
    assert client.post("/api/insights/simulate", json={"swings": {"Atlantis": {"NDA": 1.0}}}).status_code == 422
    assert client.post("/api/insights/simulate", json={"swing_all": {"NDA": 50.0}}).status_code == 422
    assert client.post("/api/insights/simulate", json={"alliance": "SP+INC", "rate": 1.5}).status_code == 422
    assert client.post("/api/insights/simulate", json={"alliance": "ALL"}).status_code == 422


def test_compliance_mode_hides_every_forward_looking_endpoint(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "on")
    for url in ("/api/insights/watchlist", "/api/insights/simulator/setup"):
        j = client.get(url).json()
        assert j["hidden"] is True and "Compliance Mode" in j["message"] and "rows" not in j
    j = client.post("/api/insights/simulate", json={"preset": "repeat2022"}).json()
    assert j["hidden"] is True and "seats" not in j
    assert client.get("/api/insights/turnout").status_code == 200                     # looks backwards
    assert client.get("/api/insights/booths").status_code == 200


def test_booth_segments_cover_only_verified_seats_and_add_up():
    c = client.get("/api/insights/booths").json()
    assert c["meta"]["seats_covered"] == len(c["rows"]) > 0
    excluded = {e["ac"] for e in c["meta"]["excluded"]}
    covered = {r["ac"] for r in c["rows"]}
    # seats whose workbook does not match the official totals (296, 301, 314, 346, 375 in the full working copy) never appear;
    # a copy of the repository that lacks those workbooks does not list them as excluded, so only "never covered" is required
    assert not {296, 301, 314, 346, 375} & covered and not excluded & covered
    b = client.get("/api/insights/booths/1").json()
    assert b["booths"] == len(b["rows"]) and all(len(r) == 4 for r in b["rows"])
    assert sum(sum(seg.values()) for seg in b["segments"].values()) == b["booths"]
    assert all(c["margin_pts"] < 10 for c in b["competitive"]) and [c["margin_pts"] for c in b["competitive"]] == sorted(c["margin_pts"] for c in b["competitive"])
    r = client.get("/api/insights/booths/314")
    assert r.status_code == 404 and "official totals" in r.json()["detail"]
    assert client.get("/api/insights/booths/9999").status_code == 404


def test_the_model_card_carries_the_new_models_and_their_limits():
    card = client.get("/api/insights/card").json()
    x = card["extra_models"]
    assert x["watch"]["decision"]["used"] == "rule" and x["turnout"]["LS2024"]["promoted"] and x["limits"]
    assert x["simulator"]["hindcast"]["pairs"] and x["booths"]["seats_covered"] > 0
