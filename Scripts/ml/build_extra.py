"""Build the additional models' outputs (seat watch score, expected turnout, alliance transfer, what-if simulator inputs, booth segments).

    python Scripts/ml/build_extra.py [--export-server] [--no-booths]

Needs data/processed/ac_features_ext.csv (run Scripts/ml/features_ext.py first). Booth segments need the 2024 workbooks in
data/2024/converted and are skipped (with a note) when that folder is missing or --no-booths is given.

Writes, in output/ml:  extra_insights.json  simulator_inputs.json  booth_segments.json  extra_model_card.json
--export-server copies them to server/insights_data (what the API serves).
"""
from __future__ import annotations

import os

os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))   # stops joblib probing 'wmic' on Windows

import argparse
import datetime as dt
import json
import logging
import shutil
import sys
from pathlib import Path

import pandas as pd

try:
    from . import features as F
    from . import models_extra as M
except ImportError:  # run as a script from Scripts/ml
    import features as F
    import models_extra as M

log = logging.getLogger("ml.build_extra")
ROOT = F.ROOT
OUT_DIR = ROOT / "output" / "ml"
FILES = ["extra_insights.json", "simulator_inputs.json", "booth_segments.json", "extra_model_card.json"]

LIMITS = [
    "The seat watch score is a transparent rule. A learned logistic regression did not beat it, and no score is a forecast: only two past elections can be checked, and one of them (2017) was a wave.",
    "Expected turnout says what a seat's history and peers suggest; a gap is a reason to look, not a finding about why people stayed home.",
    "Alliance transfer rates are estimates from 80 parliamentary seats, with wide intervals, and Lok Sabha behaviour does not carry over exactly to assembly elections.",
    "The what-if simulator shows the most likely leader per seat for a swing the user chooses. Even with the true regional swing it calls about three in four seats right, "
    "barely better than repeating the last winner in a normal year. It does not predict the swing.",
    "The region list used by the simulator is a draft that needs sign-off.",
    "Booth segments cover only seats whose 2024 workbook matches the official totals exactly, use 2024 results only (no turnout per booth, no trend), and describe results, not reasons.",
    "Watch scores, the simulator and alliance scenarios are forward-looking and are hidden when Compliance Mode is on.",
]


def build(no_booths: bool = False) -> dict:
    cfg = F.load_config()
    seed = cfg["seed"]
    ext_path = ROOT / "data" / "processed" / "ac_features_ext.csv"
    if not ext_path.exists():
        sys.exit(f"missing {ext_path}: run python Scripts/ml/features_ext.py first")
    feats = F.build_features(cfg)
    ext = pd.read_csv(ext_path, index_col="ac").reindex(feats.wide.index)
    regions, dist2reg = M.load_regions(ROOT / cfg["extra"]["regions_file"])
    unmapped = sorted(set(feats.meta["district"].dropna()) - set(dist2reg))
    if unmapped:
        sys.exit(f"districts missing from the region list: {unmapped}")

    log.info("seat watch score")
    wb = M.watch_backtest(feats, ext, cfg)
    wc = M.watch_current(feats, ext, cfg, wb)
    log.info("expected turnout")
    tm = M.turnout_model(feats, ext, cfg, seed)
    log.info("alliance transfer")
    al = M.alliance_transfer(ext, cfg, seed)
    log.info("simulator inputs and hindcasts")
    sim = M.simulator_inputs(feats, ext, cfg, regions, dist2reg, al)

    booths = {"meta": {"seats_covered": 0, "booths": 0, "excluded": [], "note": "not built"}, "acs": {}}
    bdir = ROOT / cfg["extra"]["booths"]["dir"]
    if no_booths or not bdir.exists():
        booths["meta"]["note"] = "skipped (--no-booths)" if no_booths else f"skipped: {bdir} not found"
    else:
        log.info("booth segments (reads the 2024 workbooks)")
        cand, _ = F.load_ls2024_candidates()
        booths = M.booth_segments(cfg, ROOT, cand)

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    acs = {}
    for ac in feats.wide.index:
        a = int(ac)
        acs[str(a)] = {"watch": wc["per_ac"][a], "turnout": tm["per_ac"][a],
                       "booths": {"available": str(a) in booths["acs"] or a in booths["acs"], "count": (booths["acs"].get(a) or booths["acs"].get(str(a)) or {}).get("booths", 0)}}
    # JSON keys must be strings
    booths["acs"] = {str(k): v for k, v in booths["acs"].items()}
    ranking = sorted(wc["per_ac"], key=lambda a: wc["per_ac"][a]["rank"])
    extra = {
        "meta": {"model_version": cfg["version"], "created_utc": now, "seed": seed, "region_status": sim["region_status"],
                 "inputs_sha256": {p.name: F.file_sha256(p) for p in (ext_path, ROOT / cfg["extra"]["regions_file"], F.CONFIG_PATH)}},
        "acs": acs,
        "watch": {"backtest": wb, "band_cutoffs": wc["band_cutoffs"], "band_names": cfg["extra"]["watch"]["band_names"], "ranking": [int(a) for a in ranking]},
        "turnout": {"targets": tm["targets"], "women_share_statewide_mean": tm["women_share_statewide_mean"], "flag_z": cfg["extra"]["turnout"]["flag_z"]},
        "alliances": al,
    }
    card = {
        "name": "UPBI additional seat-level models", "version": cfg["version"], "created_utc": now, "seed": seed,
        "settings": cfg["extra"], "watch": wb, "turnout": tm["targets"], "alliances": al, "simulator": {"hindcast": sim["hindcast"], "presets": [
            {k: v for k, v in p.items() if k not in ("swings",)} for p in sim["presets"]], "toss_up_pp": sim["toss_up_pp"], "region_status": sim["region_status"]},
        "booths": booths["meta"], "limits": LIMITS,
    }
    return {"extra_insights.json": extra, "simulator_inputs.json": sim, "booth_segments.json": booths, "extra_model_card.json": card}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-server", action="store_true")
    ap.add_argument("--no-booths", action="store_true")
    args = ap.parse_args()
    out = build(no_booths=args.no_booths)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, obj in out.items():
        (OUT_DIR / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ex = out["extra_insights.json"]
    wb = ex["watch"]["backtest"]
    print("watch: decision ->", wb["decision"]["used"], "|", json.dumps({k: v["scores"]["rule"] for k, v in wb["transitions"].items()}))
    for t, v in ex["turnout"]["targets"].items():
        print(f"turnout {t}: used {v['model_used']} (CV miss {v['cv_mae_pts']})")
    print("alliance:", json.dumps({k: v["rate"] for k, v in ex["alliances"]["defaults"].items()}))
    print("simulator hindcast:", json.dumps({k: v["regional_swing"]["seats_called_right_pct"] for k, v in out["simulator_inputs.json"]["hindcast"]["pairs"].items()}))
    print("booths:", out["booth_segments.json"]["meta"].get("seats_covered"), "seats,", out["booth_segments.json"]["meta"].get("booths"), "booths")
    print("wrote", OUT_DIR)
    if args.export_server:
        target = ROOT / "server" / "insights_data"
        target.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            shutil.copy2(OUT_DIR / name, target / name)
        print("exported to", target)


if __name__ == "__main__":
    main()
