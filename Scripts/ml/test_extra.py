"""Tests for the additional seat-level models. Run:  python -m pytest Scripts/ml/test_extra.py -q

Unit tests use small synthetic inputs; the rest read the files written by Scripts/ml/build_extra.py and skip if they are missing.
"""
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402
import models_extra as M  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "ml"
HAVE_OUT = all((OUT / n).is_file() for n in ("extra_insights.json", "simulator_inputs.json", "booth_segments.json", "extra_model_card.json"))
HAVE_EXT = (ROOT / "data" / "processed" / "ac_features_ext.csv").is_file()


# ---------------------------------------------------------------- unit tests
def test_bands_split_seats_by_cumulative_top_fractions():
    score = pd.Series(np.linspace(0, 1, 1000))
    edges = M._band_edges(score, [0.10, 0.25, 0.50])
    band = M._band_of(score, edges, ["Highest", "High", "Moderate", "Lower"])
    shares = band.value_counts(normalize=True).round(2).to_dict()
    assert shares == {"Lower": 0.50, "Moderate": 0.25, "High": 0.15, "Highest": 0.10}


def test_watch_composite_ranks_a_closer_seat_higher_and_mood_breaks_ties():
    x = pd.DataFrame({"margin_pp": [0.01, 0.02, 0.02, 0.40], "mood_against_leader": [0.0, 0.0, 0.30, 0.0]})
    c = M.watch_composite(x, 0.25)
    assert c.iloc[0] > c.iloc[1]                         # closer margin, same mood
    assert c.iloc[2] > c.iloc[1]                         # same margin, mood against the leader
    assert c.iloc[3] == c.min()                          # a wide margin scores lowest
    assert M.watch_composite(x, 0.0).equals((-x["margin_pp"]).rank(pct=True))     # weight 0 = margin only


def _base():
    return np.array([[0.40, 0.35, 0.05, 0.15, 0.05], [0.30, 0.34, 0.06, 0.25, 0.05], [0.20, 0.20, 0.30, 0.20, 0.10]])


def test_simulator_zero_swing_keeps_the_leaders_and_shares_sum_to_one():
    r = M.simulate_reference(_base(), np.array([0, 0, 1]), np.zeros((2, 3)), None, 0.0)
    assert r["lead"].tolist() == [0, 1, 2]
    assert np.allclose(r["shares"].sum(axis=1), 1) and np.allclose(r["shares"], _base() / _base().sum(axis=1, keepdims=True))


def test_simulator_swing_and_absorption():
    sw = np.array([[0.10, -0.10, 0.0], [0.0, 0.0, 0.0]])
    r = M.simulate_reference(_base(), np.array([0, 0, 1]), sw, None, 0.0)
    assert r["lead"][1] == 0 and r["shares"][1, 0] == pytest.approx(0.40) and r["shares"][1, 1] == pytest.approx(0.24)   # NDA +10, SPF -10
    assert r["shares"][2].tolist() == pytest.approx((_base()[2] / _base()[2].sum()).tolist())                          # other region untouched
    big = M.simulate_reference(_base(), np.array([0, 0, 0]), np.array([[0.30, -0.30, 0.0]]), None, 0.0)
    assert (big["shares"] >= 0).all() and np.allclose(big["shares"].sum(axis=1), 1)                                    # clipping keeps it valid


def test_simulator_alliance_moves_the_partner_vote():
    r = M.simulate_reference(_base(), np.array([0, 0, 0]), np.zeros((1, 3)), "SP+INC", 1.0)
    assert r["shares"][:, 2].max() == pytest.approx(0.0, abs=1e-9) and r["shares"][2, 1] == pytest.approx(0.50)
    half = M.simulate_reference(_base(), np.array([0, 0, 0]), np.zeros((1, 3)), "SP+BSP", 0.5)
    assert half["shares"][1, 1] == pytest.approx(0.34 + 0.5 * 0.25) and half["shares"][1, 3] == pytest.approx(0.125)


def test_transfer_fit_recovers_known_rates_and_stays_in_bounds():
    rng = np.random.default_rng(1)
    X = rng.dirichlet(np.ones(6), size=200)
    beta = np.array([0.9, 0.6, 0.0, 0.1, 0.0, 0.2])
    y = X @ beta + rng.normal(0, 0.01, 200)
    est = M._fit_share(X, y)
    assert np.abs(est - beta).max() < 0.08 and est.min() >= 0 and est.max() <= 1
    y2 = X @ np.array([1.4, 0, 0, 0, 0, 0])                                     # an impossible rate is capped at 1
    assert M._fit_share(X, y2).max() <= 1.0


def test_region_list_covers_every_district_once():
    regions, d2r = M.load_regions(ROOT / "configs" / "regions_up.json")
    all_districts = [d for ds in regions.values() for d in ds]
    assert len(all_districts) == len(set(all_districts)) == 75 and len(regions) == 6
    acs = json.loads((ROOT / "configs" / "ac_format.json").read_text(encoding="utf-8"))["assembly_constituencies"]
    assert {a["district"] for a in acs} <= set(d2r)


def test_rounding_helper_handles_missing_values():
    assert M.r(None) is None and M.r(float("nan")) is None and M.r("x") is None and M.r(0.123456, 3) == 0.123


# ---------------------------------------------------------------- checks on the written outputs
@pytest.fixture(scope="module")
def out():
    return {n: json.loads((OUT / f"{n}.json").read_text(encoding="utf-8")) for n in ("extra_insights", "simulator_inputs", "booth_segments", "extra_model_card")}


@pytest.mark.skipif(not HAVE_OUT, reason="run Scripts/ml/build_extra.py first")
def test_watch_outputs_cover_every_seat_and_are_honest(out):
    e = out["extra_insights"]
    assert len(e["acs"]) == 403 and sorted(e["watch"]["ranking"]) == list(range(1, 404))
    ranks = sorted(v["watch"]["rank"] for v in e["acs"].values())
    assert ranks == list(range(1, 404))
    assert e["watch"]["backtest"]["decision"]["used"] == "rule"                  # the learned model failed its gate: say so
    t = e["watch"]["backtest"]["transitions"]
    assert t["VS2017->VS2022"]["flips"] == 106 and t["VS2012->VS2017"]["flips"] == 318
    rule, base = t["VS2017->VS2022"]["scores"]["rule"], t["VS2017->VS2022"]["scores"]["margin_only"]
    assert rule["auc"] >= base["auc"] - 0.01                                     # the rule does not lose to margin-only in a normal year
    bands = e["watch"]["backtest"]["bands"]["VS2017->VS2022"]
    assert bands[0]["flip_rate"] > 0.5 and bands[-1]["flip_rate"] < 0.15


@pytest.mark.skipif(not HAVE_OUT, reason="run Scripts/ml/build_extra.py first")
def test_turnout_model_beats_its_baseline_and_gaps_centre_on_zero(out):
    for name, v in out["extra_insights"]["turnout"]["targets"].items():
        assert v["promoted"] and v["cv_mae_pts"]["ridge"] + 0.2 <= v["cv_mae_pts"]["persistence_plus_statewide_change"], name
        assert abs(v["statewide"]["actual_mean"] - v["statewide"]["expected_mean"]) < 0.002
    for rec in out["extra_insights"]["acs"].values():
        t = rec["turnout"]["LS2024"]
        if t["actual"] is not None:
            assert 0.3 <= t["actual"] <= 0.95 and 0.3 <= t["expected"] <= 0.95


@pytest.mark.skipif(not HAVE_OUT, reason="run Scripts/ml/build_extra.py first")
def test_alliance_rates_beat_the_naive_rules(out):
    for g in out["extra_insights"]["alliances"]["groups"]:
        assert g["loo_mae_pts"]["fitted"] <= min(g["loo_mae_pts"]["partner_votes_all_transfer"], g["loo_mae_pts"]["partner_votes_none_transfer"]) + 0.2
        assert g["seats"] >= 8


@pytest.mark.skipif(not HAVE_OUT, reason="run Scripts/ml/build_extra.py first")
def test_simulator_inputs_reproduce_2022_and_state_their_limit(out):
    s = out["simulator_inputs"]
    base = np.array([x["base"] for x in s["seats"]])
    lead = np.array(s["fronts"])[base.argmax(axis=1)]
    assert (lead == np.array([x["winner"] for x in s["seats"]])).all()          # zero swing = the actual 2022 winners
    h = s["hindcast"]["pairs"]["VS2017->VS2022"]
    assert h["regional_swing"]["seats_called_right_pct"] < 85                    # never claim more than the hindcast shows
    assert h["regional_swing"]["seats_called_right_pct"] - h["same_winner_as_before_pct"] < 10
    assert s["presets"][1]["reproduces_ls2024_segment_leader_pct"] > 70


@pytest.mark.skipif(not HAVE_OUT, reason="run Scripts/ml/build_extra.py first")
def test_booth_segments_are_consistent(out):
    b = out["booth_segments"]
    assert b["meta"]["seats_covered"] == len(b["acs"]) > 0 and b["meta"]["booths"] == sum(v["booths"] for v in b["acs"].values())
    for ac, v in list(b["acs"].items())[:40]:
        assert v["booths"] == len(v["rows"]) > 0
        assert all(0 <= r[2] <= 100 and r[3] >= 50 for r in v["rows"])
        assert sum(sum(s.values()) for s in v["segments"].values()) == v["booths"]
        assert v["against_seat_leader"] == sum(1 for r in v["rows"] if r[1] != {"NDA": "N", "SPF": "S", "BSP": "B", "OTH": "O"}[v["seat_leader"]])
    # seats whose workbook does not match the official totals never appear (a copy without those workbooks lists no exclusions)
    assert not {296, 301, 314, 346, 375} & {int(k) for k in b["acs"]} and not {e["ac"] for e in b["meta"]["excluded"]} & {int(k) for k in b["acs"]}


@pytest.mark.skipif(not (HAVE_EXT and HAVE_OUT), reason="needs data/processed and the built outputs")
def test_alliance_fit_is_deterministic():
    cfg = F.load_config()
    cfg = copy.deepcopy(cfg)
    cfg["extra"]["alliance"]["bootstrap"] = 40
    ext = pd.read_csv(ROOT / "data" / "processed" / "ac_features_ext.csv", index_col="ac")
    a = M.alliance_transfer(ext, cfg, cfg["seed"])
    b = M.alliance_transfer(ext, cfg, cfg["seed"])
    assert a == b
