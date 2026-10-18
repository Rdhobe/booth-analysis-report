"""Insights API: constituency types, unusual results and expected ranges (Phase 1 models).

Serves the files written by ``Scripts/ml/build_insights.py`` (``ac_insights.json`` and
``model_card.json``). No database is needed: the models run offline in a batch and this
router only reads their output, so every response is static until the files are replaced
and the server restarts.

Data folder, first match wins:
  1. ``INSIGHTS_DIR`` environment variable
  2. ``server/insights_data/``            (what the Docker image carries; refresh with
                                            ``python Scripts/ml/build_insights.py --export-server``)
  3. ``output/ml/``                       (local development)

Compliance Mode: when ``COMPLIANCE_MODE`` is on / 1 / true / yes, the forward-looking
"expected" range is removed from every AC response, so the switch holds even if a client ignores it.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

log = logging.getLogger("upbi.insights")

HERE = Path(__file__).resolve().parent
router = APIRouter(prefix="/api/insights", tags=["insights"])

_STATE: dict = {}


def compliance_on() -> bool:
    """True while forward-looking numbers must stay hidden (read on every call, so tests can flip it)."""
    return os.environ.get("COMPLIANCE_MODE", "off").strip().lower() in {"on", "1", "true", "yes"}


def _data_dir() -> Path | None:
    for cand in (os.environ.get("INSIGHTS_DIR"), HERE / "insights_data", HERE.parent / "output" / "ml"):
        if cand and (Path(cand) / "ac_insights.json").is_file():
            return Path(cand)
    return None


def _load() -> dict:
    """Load and index the generated files once."""
    if _STATE:
        return _STATE
    folder = _data_dir()
    if folder is None:
        raise HTTPException(503, "insights data not built (run: python Scripts/ml/build_insights.py "
                                 "--export-server)")
    data = json.loads((folder / "ac_insights.json").read_text(encoding="utf-8"))
    card_path = folder / "model_card.json"
    card = json.loads(card_path.read_text(encoding="utf-8")) if card_path.is_file() else {}
    _STATE.update({"folder": str(folder), "data": data, "card": card, "by_ac": {a["ac"]: a for a in data["acs"]}})
    log.info("insights loaded from %s (%d ACs)", folder, len(data["acs"]))
    return _STATE


def _public_ac(ac: dict) -> dict:
    """AC record as served: the expected range is dropped while Compliance Mode is on."""
    if not compliance_on():
        return ac
    out = dict(ac)
    out["expected"] = None
    out["expected_hidden"] = "Compliance Mode is on: forward-looking numbers are hidden."
    return out


@router.get("/meta")
def insights_meta():
    """Versions, front labels, error bands and the limits to show next to any result."""
    s = _load()
    meta, card = s["data"]["meta"], s["card"]
    flagged = sum(1 for a in s["data"]["acs"] if a["surprise"] and a["surprise"]["flag"])
    return {
        **meta,
        "compliance_mode": "on" if compliance_on() else "off",
        "counts": {"acs": len(s["data"]["acs"]), "types": len(s["data"]["types"]), "flagged": flagged},
        "limits": card.get("limits", []),
        "scope": card.get("scope", ""),
    }


@router.get("/overview")
def insights_overview():
    """Statewide shares and seats by front, top-ten lists and the district table."""
    return _load()["data"]["overview"]


@router.get("/types")
def insights_types():
    """The constituency types with average shares, typical members and the full member list."""
    return {"types": _load()["data"]["types"]}


@router.get("/acs")
def insights_acs():
    """One light row per constituency, for pickers and tables."""
    rows = [{"ac": a["ac"], "name": a["name"], "district": a["district"], "type": a["type"]["id"],
             "clean": a["clean"], "strength": a["surprise"]["strength"] if a["surprise"] else "n/a"}
            for a in _load()["data"]["acs"]]
    return {"rows": rows}


@router.get("/ac/{ac}")
def insights_ac(ac: int):
    """Everything about one constituency: history, type, look-alikes, surprise reading, expected range."""
    rec = _load()["by_ac"].get(ac)
    if rec is None:
        raise HTTPException(404, f"unknown constituency: {ac}")
    return _public_ac(rec)


@router.get("/surprises")
def insights_surprises(min_strength: str = Query("moderate", pattern="^(moderate|strong)$")):
    """Constituencies flagged as statistical outliers, strongest first."""
    keep = {"strong"} if min_strength == "strong" else {"strong", "moderate"}
    rows = [{"ac": a["ac"], "name": a["name"], "district": a["district"], "type": a["type"]["id"],
             "strength": a["surprise"]["strength"], "maxz": a["surprise"]["maxz"],
             "drivers": a["surprise"]["drivers"]}
            for a in _load()["data"]["acs"] if a["surprise"] and a["surprise"]["strength"] in keep]
    rows.sort(key=lambda r: -r["maxz"])
    return {"rows": rows, "rule": _load()["card"].get("surprise", {})}


@router.get("/card")
def insights_card():
    """The model card: input hashes, checks, selection tables, backtests and limits."""
    return _load()["card"]
