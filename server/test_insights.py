"""Tests for the insights API. Run from the repo root:  python -m pytest server/test_insights.py -q"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as app_module  # noqa: E402
import insights  # noqa: E402

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.delenv("COMPLIANCE_MODE", raising=False)
    insights._STATE.clear()
    yield
    insights._STATE.clear()


def test_meta_reports_counts_and_limits():
    r = client.get("/api/insights/meta")
    assert r.status_code == 200
    m = r.json()
    assert m["counts"]["acs"] == 403 and m["counts"]["types"] >= 3
    assert m["compliance_mode"] == "off"
    assert m["camps"] == ["NDA", "OPP", "BSP", "OTH"]
    assert m["limits"], "limits must travel with the numbers"


def test_ac_record_has_type_lookalikes_surprise_and_expected():
    r = client.get("/api/insights/ac/86")
    assert r.status_code == 200
    a = r.json()
    assert a["name"] == "Etmadpur" and a["district"] == "Agra"
    assert len(a["look_alikes"]) == 5 and 86 not in [x["ac"] for x in a["look_alikes"]]
    assert set(a["history"]) == {"VS2012", "VS2017", "VS2022", "LS2024"}
    exp = a["expected"]["camps"]["NDA"]
    assert exp["low"] <= exp["expected"] <= exp["high"]
    assert exp["stress_low"] <= exp["low"] and exp["high"] <= exp["stress_high"]


def test_compliance_mode_removes_the_expected_range(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "on")
    a = client.get("/api/insights/ac/86").json()
    assert a["expected"] is None and "Compliance Mode" in a["expected_hidden"]
    assert a["type"]["id"] and a["history"]            # everything else still served
    assert client.get("/api/insights/meta").json()["compliance_mode"] == "on"


def test_unknown_constituency_is_404():
    assert client.get("/api/insights/ac/999").status_code == 404


def test_surprises_are_sorted_and_filterable():
    rows = client.get("/api/insights/surprises").json()["rows"]
    assert rows and all(r["strength"] in {"moderate", "strong"} for r in rows)
    assert [r["maxz"] for r in rows] == sorted((r["maxz"] for r in rows), reverse=True)
    strong = client.get("/api/insights/surprises?min_strength=strong").json()["rows"]
    assert 0 < len(strong) < len(rows) and all(r["strength"] == "strong" for r in strong)
    assert client.get("/api/insights/surprises?min_strength=bogus").status_code == 422


def test_types_cover_every_constituency_once():
    types = client.get("/api/insights/types").json()["types"]
    members = [a for t in types for a in t["members"]]
    assert len(members) == 403 and len(set(members)) == 403


def test_acs_list_is_complete():
    rows = client.get("/api/insights/acs").json()["rows"]
    assert len(rows) == 403 and {"ac", "name", "district", "type", "strength"} <= set(rows[0])


def test_overview_matches_published_seat_counts():
    s = client.get("/api/insights/overview").json()["state"]
    assert s["VS2017"]["seats"]["NDA"] == 325 and s["VS2022"]["seats"]["NDA"] == 273


def test_api_key_is_enforced_when_set(monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret")
    assert client.get("/api/insights/ac/86").status_code == 401
    assert client.get("/api/insights/ac/86", headers={"x-api-key": "secret"}).status_code == 200


def test_missing_data_gives_a_clear_503(monkeypatch):
    monkeypatch.setattr(insights, "_data_dir", lambda: None)
    r = client.get("/api/insights/meta")
    assert r.status_code == 503 and "build_insights" in r.json()["detail"]


def test_ac_has_turnout_and_electors_block():
    a = client.get("/api/insights/ac/86").json()["turnout_block"]
    assert set(a["turnout"]) == {"VS2017", "LS2019", "VS2022", "LS2024"}
    assert 0.3 <= a["turnout"]["VS2022"] <= 0.95 and a["electors"]["LS2024"] > 100000


def test_statewide_turnout_is_close_to_published_levels():
    t = {r["election"]: r for r in client.get("/api/insights/overview").json()["turnout"]}
    assert set(t) == {"VS2017", "LS2019", "VS2022", "LS2024"}
    assert 0.59 <= t["VS2017"]["turnout"] <= 0.63        # published: about 61.2%
    assert 0.57 <= t["LS2019"]["turnout"] <= 0.61        # about 59.2%
    assert 0.58 <= t["VS2022"]["turnout"] <= 0.63        # about 60.7%


def test_model_card_explains_the_data_cleaning():
    cov = client.get("/api/insights/card").json()["data_coverage"]
    first = cov["by_election"][0]
    assert first["acs_read"] > first["first_run"]["read"]
    assert all(u["reason"] for e in cov["by_election"] for u in e["unread"])
