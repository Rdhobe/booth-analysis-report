"""Insights API, part 2: seat watch list, expected turnout, alliance transfer, what-if simulator and booth segments.

Serves the files written by ``Scripts/ml/build_extra.py`` (``extra_insights.json``, ``simulator_inputs.json``, ``booth_segments.json``,
``extra_model_card.json``), from the same folder as the Phase 1 files. Pure Python: no numpy, no database. The what-if simulator is
a few arithmetic steps per seat (see ``simulate``); ``Scripts/ml/models_extra.simulate_reference`` is the numpy twin the tests compare against.

Compliance Mode (``COMPLIANCE_MODE`` on): the watch list, the per-seat watch score, the simulator and its setup return
``{"hidden": true, ...}`` instead of forward-looking numbers. Expected turnout, alliance estimates and booth results look backwards and stay available.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

log = logging.getLogger("upbi.insights.extra")

FR5 = ["NDA", "SPF", "INC", "BSP", "OTH"]
HIDDEN_MSG = "Compliance Mode is on: forward-looking numbers are hidden."
FILES = {"extra": "extra_insights.json", "sim": "simulator_inputs.json", "booths": "booth_segments.json", "card": "extra_model_card.json"}


class SimRequest(BaseModel):
    """What-if inputs. Swings are percentage points (e.g. 3.0 means +3 points of vote share)."""
    preset: str | None = None
    swing_all: dict[str, float] | None = Field(None, description="Statewide swing for NDA, SPF and BSP, added to every region")
    swings: dict[str, dict[str, float]] | None = Field(None, description="Region name -> {NDA, SPF, BSP} swing, added on top")
    alliance: Literal["SP+INC", "SP+BSP"] | None = None
    rate: float | None = Field(None, ge=0.0, le=1.0, description="Share of the partner's voters who move to the SP-led front")


def band_for(margin: float, edges_pp: list[float]) -> int:
    """Index of the margin band (0 = the narrowest) for a margin given as a fraction."""
    m = margin * 100
    for i, e in enumerate(edges_pp):
        if m < e:
            return i
    return len(edges_pp)


def simulate(seats: list[dict], n_regions: int, swings: list[list[float]], alliance: str | None, rate: float) -> list[dict]:
    """Leader and runner-up per seat after an optional alliance and a swing by region.

    base shares are (NDA, SPF, INC, BSP, OTH). swings[region] = [NDA, SPF, BSP] as fractions. INC and OTH absorb the opposite of the
    swings in proportion to their size, then shares are clipped at zero and renormalised.
    """
    out = []
    for s in seats:
        b = list(s["base"])
        if alliance == "SP+INC":
            b[1] += rate * b[2]
            b[2] *= (1 - rate)
        elif alliance == "SP+BSP":
            b[1] += rate * b[3]
            b[3] *= (1 - rate)
        sw = swings[s["region"]]
        b[0] += sw[0]
        b[1] += sw[1]
        b[3] += sw[2]
        absorb = -(sw[0] + sw[1] + sw[2])
        pool = b[2] + b[4]
        w = b[2] / pool if pool > 0 else 0.5
        b[2] += absorb * w
        b[4] += absorb * (1 - w)
        b = [max(x, 0.0) for x in b]
        tot = sum(b)
        b = [x / tot for x in b]
        order = sorted(range(5), key=lambda i: -b[i])
        out.append({"lead": order[0], "second": order[1], "margin": b[order[0]] - b[order[1]], "shares": b})
    return out


def build_router(compliance_on: Callable[[], bool], data_dir: Callable[[], Path | None]) -> APIRouter:
    router = APIRouter(tags=["insights-extra"])
    state: dict = {}

    def load(key: str):
        """Lazy load of one generated file; None when it is not there (the Phase 1 pages keep working)."""
        if key in state:
            return state[key]
        folder = data_dir()
        path = folder / FILES[key] if folder else None
        state[key] = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None
        return state[key]

    def need(key: str):
        d = load(key)
        if d is None:
            raise HTTPException(503, f"{FILES[key]} not built (run: python Scripts/ml/build_extra.py --export-server)")
        return d

    def names() -> dict[int, dict]:
        if "names" not in state:
            sim = load("sim")
            state["names"] = {s["ac"]: {"name": s["name"], "district": s["district"]} for s in sim["seats"]} if sim else {}
        return state["names"]

    # ---------------------------------------------------------------- availability
    @router.get("/extra/meta")
    def extra_meta():
        """Which of the additional models are built, plus the settings the pages need."""
        extra, sim, booths, card = load("extra"), load("sim"), load("booths"), load("card")
        return {
            "available": {"watch": extra is not None, "turnout": extra is not None, "alliances": extra is not None, "simulator": sim is not None,
                          "booths": bool(booths and booths["meta"].get("seats_covered"))},
            "compliance_mode": "on" if compliance_on() else "off",
            "region_status": (sim or {}).get("region_status"),
            "booths": {k: v for k, v in (booths or {}).get("meta", {}).items() if k != "excluded"} if booths else None,
            "limits": (card or {}).get("limits", []),
            "model_version": (extra or {}).get("meta", {}).get("model_version"),
        }

    # ---------------------------------------------------------------- seat watch list
    @router.get("/watchlist")
    def watchlist(band: str | None = None, district: str | None = None, q: str | None = None,
                  limit: int = Query(60, ge=1, le=403), offset: int = Query(0, ge=0)):
        """Seats ranked by the watch score, highest first. Hidden in Compliance Mode."""
        if compliance_on():
            return {"hidden": True, "message": HIDDEN_MSG}
        extra = need("extra")
        nm = names()
        rows = []
        for ac in extra["watch"]["ranking"]:
            w = extra["acs"][str(ac)]["watch"]
            row = {"ac": ac, **nm.get(ac, {}), **w}
            if band and w["band"] != band:
                continue
            if district and row.get("district") != district:
                continue
            if q and q.lower() not in f"{row.get('name', '')} {row.get('district', '')} {ac}".lower():
                continue
            rows.append(row)
        counts = {b: sum(1 for ac in extra["watch"]["ranking"] if extra["acs"][str(ac)]["watch"]["band"] == b) for b in extra["watch"]["band_names"]}
        return {"total": len(rows), "rows": rows[offset:offset + limit], "band_counts": counts, "band_names": extra["watch"]["band_names"],
                "backtest": extra["watch"]["backtest"], "districts": sorted({n["district"] for n in nm.values()})}

    # ---------------------------------------------------------------- expected turnout
    @router.get("/turnout")
    def turnout():
        """Actual against expected turnout for every seat (2022 assembly and 2024 Lok Sabha) and the women's share of voters."""
        extra = need("extra")
        nm = names()
        rows = []
        for ac_s, rec in extra["acs"].items():
            ac = int(ac_s)
            rows.append({"ac": ac, **nm.get(ac, {}), "turnout": rec["turnout"]})
        return {"rows": rows, "targets": extra["turnout"]["targets"], "women_share_statewide_mean": extra["turnout"]["women_share_statewide_mean"],
                "flag_z": extra["turnout"]["flag_z"]}

    # ---------------------------------------------------------------- alliances
    @router.get("/alliances")
    def alliances():
        """Estimated transfer of a partner's voters in the 2019 and 2024 Lok Sabha alliances."""
        return need("extra")["alliances"]

    # ---------------------------------------------------------------- simulator
    @router.get("/simulator/setup")
    def simulator_setup():
        """Regions, presets, defaults and the hindcast evidence the page shows next to every result."""
        if compliance_on():
            return {"hidden": True, "message": HIDDEN_MSG}
        sim = need("sim")
        actual = {f: sum(1 for s in sim["seats"] if s["winner"] == f) for f in FR5}
        return {k: v for k, v in sim.items() if k != "seats"} | {"seat_count": len(sim["seats"]), "actual_2022": actual}

    @router.post("/simulate")
    def simulate_endpoint(req: SimRequest):
        """Most likely leader of every seat for a chosen swing and alliance. Hidden in Compliance Mode."""
        if compliance_on():
            return {"hidden": True, "message": HIDDEN_MSG}
        sim = need("sim")
        regions = [r["name"] for r in sim["regions"]]
        n = len(regions)
        swings = [[0.0, 0.0, 0.0] for _ in range(n)]
        alliance, rate = req.alliance, req.rate
        if req.preset:
            p = next((p for p in sim["presets"] if p["id"] == req.preset), None)
            if p is None:
                raise HTTPException(422, f"unknown preset: {req.preset}")
            swings = [list(map(float, row)) for row in p["swings"]]
            alliance = alliance if req.alliance is not None else p.get("alliance")
            rate = rate if req.rate is not None else p.get("rate")
        for key in ("NDA", "SPF", "BSP"):
            for d in ([req.swing_all] if req.swing_all else []) + list((req.swings or {}).values()):
                if key in d and abs(d[key]) > 30:
                    raise HTTPException(422, "swings must be between -30 and +30 points")
        if req.swing_all:
            add = [req.swing_all.get(k, 0.0) / 100 for k in ("NDA", "SPF", "BSP")]
            swings = [[a + b for a, b in zip(row, add)] for row in swings]
        for rname, d in (req.swings or {}).items():
            if rname not in regions:
                raise HTTPException(422, f"unknown region: {rname}")
            i = regions.index(rname)
            swings[i] = [a + d.get(k, 0.0) / 100 for a, k in zip(swings[i], ("NDA", "SPF", "BSP"))]
        if alliance and rate is None:
            rate = sim["alliance_defaults"][alliance]
        rate = 0.0 if rate is None else rate
        res = simulate(sim["seats"], n, swings, alliance, rate)
        edges = sim["margin_band_edges_pp"]
        hist = {i: b["leader_won_pct"] for i, b in enumerate(sim["hindcast"]["bands"]["pooled"])}
        t = sim["toss_up_pp"] / 100
        leads = {f: 0 for f in FR5}
        lower = {f: 0 for f in FR5}
        upper = {f: 0 for f in FR5}
        flips = 0
        by_region = [{"name": r["name"], "seats": 0, "leads": {f: 0 for f in FR5}} for r in sim["regions"]]
        seats_out = []
        for s, r in zip(sim["seats"], res):
            lead, second = FR5[r["lead"]], FR5[r["second"]]
            leads[lead] += 1
            toss = r["margin"] < t
            if not toss:
                lower[lead] += 1
            upper[lead] += 1
            if toss:
                upper[second] += 1
            flip = lead != s["winner"]
            flips += flip
            reg = by_region[s["region"]]
            reg["seats"] += 1
            reg["leads"][lead] += 1
            bi = band_for(r["margin"], edges)
            seats_out.append({"ac": s["ac"], "name": s["name"], "district": s["district"], "region": s["region"], "lead": lead, "second": second,
                              "margin_pts": round(r["margin"] * 100, 1), "band": bi, "history_pct": hist.get(bi), "winner_2022": s["winner"], "flips_vs_2022": bool(flip),
                              "shares": [round(x, 4) for x in r["shares"]]})
        return {
            "summary": {"leads": leads, "bounds": {f: [lower[f], upper[f]] for f in FR5}, "toss_up_seats": sum(1 for r in res if r["margin"] < t),
                        "toss_up_rule": f"margin under {sim['toss_up_pp']:.0f} points", "flips_vs_2022": int(flips)},
            "regions": by_region, "seats": seats_out,
            "assumptions": {"alliance": alliance, "rate": rate, "swings_pp": {regions[i]: [round(x * 100, 1) for x in swings[i]] for i in range(n)},
                            "fronts": ["NDA", "SPF", "BSP"], "note": "INC and others absorb the opposite of the swings in proportion to their size."},
        }

    # ---------------------------------------------------------------- booth segments
    @router.get("/booths")
    def booths_coverage():
        """Seats with booth segments, with a one-line summary each."""
        b = need("booths")
        nm = names()
        rows = []
        for ac_s, v in b["acs"].items():
            ac = int(ac_s)
            comp = sum(c.get("Competitive", 0) for c in v["segments"].values())
            rows.append({"ac": ac, **nm.get(ac, {}), "booths": v["booths"], "seat_leader": v["seat_leader"], "competitive": comp, "against_seat_leader": v["against_seat_leader"]})
        rows.sort(key=lambda r: r["ac"])
        return {"meta": b["meta"], "rows": rows}

    @router.get("/booths/{ac}")
    def booths_for_ac(ac: int):
        """Booth segments for one seat: segment counts by leading front, the closest booths and every booth row."""
        b = need("booths")
        rec = b["acs"].get(str(ac))
        if rec is None:
            reason = next((e["reason"] for e in b["meta"].get("excluded", []) if e["ac"] == ac), "no 2024 booth workbook that matches the official totals yet")
            raise HTTPException(404, f"no booth segments for constituency {ac}: {reason}")
        return {"ac": ac, **names().get(ac, {}), **rec, "meta": {k: v for k, v in b["meta"].items() if k != "excluded"}}

    # ---------------------------------------------------------------- merged into the seat record
    def for_ac(ac: int) -> dict | None:
        extra = load("extra")
        if extra is None:
            return None
        rec = extra["acs"].get(str(ac))
        if rec is None:
            return None
        out = {"turnout": rec["turnout"], "booths": rec["booths"]}
        if compliance_on():
            out["watch"] = None
            out["watch_hidden"] = HIDDEN_MSG
        else:
            out["watch"] = rec["watch"]
        return out

    def extra_meta_available() -> bool:
        return load("extra") is not None

    router.for_ac = for_ac                                     # type: ignore[attr-defined]
    router.extra_meta_available = extra_meta_available         # type: ignore[attr-defined]
    router.extra_card = lambda: load("card")                   # type: ignore[attr-defined]
    router.reset = state.clear                                 # type: ignore[attr-defined]
    return router
