"""Extended backtest: can a learned model beat simple rules once Lok Sabha and candidate features are added?

Forward test (the evidence that counts) - the same recipe applied to two consecutive cycles:
    task A  train:  assembly 2012 + Lok Sabha 2014 (+2009 for the swing)  ->  assembly 2017
    task B  test:   assembly 2017 + Lok Sabha 2019 (+2014 for the swing)  ->  assembly 2022
The model never sees 2022 results. Hyper-parameters are fixed in advance (not tuned on the test).

Cross-section test (weaker evidence, labelled as such): inside task B only, 5-fold CV grouped by district, to see whether
constituency-level extras (turnout, electors, 2019 booth-sheet fronts) add anything beyond the features above.

Lok Sabha features are per parliamentary seat (official results), copied to each assembly segment in the seat.

Run:  python Scripts/ml/backtest_ext.py   (needs data/processed/ac_features_ext.csv from features_ext.py)
Writes output/ml/backtest_ext_report.json and backtest_ext_report.md
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

try:
    from . import features as F
    from . import features_ext as X
except ImportError:  # run as a script from Scripts/ml
    import features as F
    import features_ext as X

log = logging.getLogger("ml.backtest_ext")
FRONTS = ["nda", "opp", "bsp"]
TASKS = {
    "A": {"prev": "VS2012", "target": "VS2017", "ls": "14", "ls_prev": "09", "tag": "17"},
    "B": {"prev": "VS2017", "target": "VS2022", "ls": "19", "ls_prev": "14", "tag": "22"},
}
GROUPS = {
    "history": ["prev_nda", "prev_opp", "prev_bsp", "prev_oth", "prev_margin", "prev_ncand", "prev_win_nda", "prev_win_opp", "prev_win_bsp"],
    "lok_sabha": ["ls_nda", "ls_sp", "ls_bsp", "ls_inc", "ls_rld", "ls_oth", "ls_opp", "ls_swing_nda", "ls_swing_sp", "ls_swing_bsp",
                  "ls_swing_inc", "ls_swing_opp"],
    "nomination": ["inc_recontests", "inc_switched", "n_cand"],          # known only once candidates are announced
}
EXTRAS_B = ["turnout_17_best", "electors_17_best", "female_share_voters_17", "turnout_19", "female_share_voters_19", "nda_19", "gba_19", "inc_19"]


def task_frame(feats: F.Features, ext: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Features known before the target election, and the target front shares."""
    w, e0, e1, tag = feats.wide, spec["prev"], spec["target"], spec["tag"]
    x = pd.DataFrame(index=w.index)
    for f in ("nda", "opp", "bsp", "oth"):
        x[f"prev_{f}"] = w[f"{f.upper()}_{e0}"]
    x["prev_margin"] = feats.winners.xs(e0, level="election")["margin_pp"].reindex(x.index)
    x["prev_ncand"] = w[f"ncand_{e0}"]
    pw = ext[f"prev_winner_front_{tag}"].map({"NDA": "nda", "SPF": "opp", "INC": "opp", "BSP": "bsp"}).fillna("oth")
    for f in ("nda", "opp", "bsp"):
        x[f"prev_win_{f}"] = (pw == f).astype(int).reindex(x.index)
    ls, lp = spec["ls"], spec["ls_prev"]
    for f in ("nda", "sp", "bsp", "inc", "rld", "oth"):
        x[f"ls_{f}"] = ext[f"ls{ls}_{f}"]
    x["ls_opp"] = x["ls_sp"] + x["ls_inc"] + x["ls_rld"]
    for f in ("nda", "sp", "bsp", "inc"):
        x[f"ls_swing_{f}"] = ext[f"ls{ls}_{f}"] - ext[f"ls{lp}_{f}"]
    x["ls_swing_opp"] = x["ls_opp"] - (ext[f"ls{lp}_sp"] + ext[f"ls{lp}_inc"] + ext[f"ls{lp}_rld"])
    x["inc_recontests"] = ext[f"inc_recontests_{tag}"]
    x["inc_switched"] = ((ext[f"inc_recontests_{tag}"] == 1) & (ext[f"inc_same_party_{tag}"] == 0)).astype(int)
    x["n_cand"] = ext[f"n_candidates_{tag}"]
    y = pd.DataFrame({f: w[f"{f.upper()}_{e1}"] for f in FRONTS}, index=w.index)
    return x, y


def baselines(x: pd.DataFrame, y: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Simple rules that need no training."""
    clip = lambda d: d.clip(0, 1)                                      # noqa: E731
    prev = x[["prev_nda", "prev_opp", "prev_bsp"]].set_axis(FRONTS, axis=1)
    swing = pd.DataFrame({"nda": x["ls_swing_nda"], "opp": x["ls_swing_opp"], "bsp": x["ls_swing_bsp"]})
    ls = pd.DataFrame({"nda": x["ls_nda"], "opp": x["ls_opp"], "bsp": x["ls_bsp"]})
    return {
        "Same as last assembly election": prev,
        "Last assembly result plus the Lok Sabha swing": clip(prev + swing),
        "Latest Lok Sabha result for the seat": ls,
        "Average of last assembly result and latest Lok Sabha": clip((prev + ls) / 2),
        "CEILING: last result plus true state swing (only known afterwards)": clip(prev + (y.mean() - prev.mean())),
    }


def make_model(kind: str, seed: int):
    if kind == "ridge":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=10.0))
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=20, random_state=seed)


def fit_predict(kind: str, cols: list[str], xtr, ytr, xte, seed: int) -> pd.DataFrame:
    return pd.DataFrame({f: make_model(kind, seed).fit(xtr[cols], ytr[f]).predict(xte[cols]) for f in FRONTS}, index=xte.index)


def score(y: pd.DataFrame, yhat: pd.DataFrame) -> dict:
    err = (y - yhat).abs() * 100
    lead_true, lead_pred = y.idxmax(axis=1), yhat.idxmax(axis=1)
    return {"mae_pts": {f: round(float(err[f].mean()), 2) for f in FRONTS}, "mean_mae_pts": round(float(err.to_numpy().mean()), 2),
            "within80_pts": round(float(np.quantile(err.to_numpy(), 0.8)), 2), "lead_call_accuracy": round(float((lead_true == lead_pred).mean()), 3)}


def forward_test(feats: F.Features, ext: pd.DataFrame, cfg: dict, seed: int) -> dict:
    xa, ya = task_frame(feats, ext, TASKS["A"])
    xb, yb = task_frame(feats, ext, TASKS["B"])
    ok = feats.clean.to_numpy()
    xa, ya, xb, yb = xa[ok], ya[ok], xb[ok], yb[ok]
    margin = cfg["baseline"]["promotion_margin_pts"]
    results = []
    for name, pred in baselines(xb, yb).items():
        results.append({"method": name, "kind": "ceiling" if name.startswith("CEILING") else "baseline", "features": "none", **score(yb, pred)})
    sets = {"history only": GROUPS["history"],
            "history + Lok Sabha": GROUPS["history"] + GROUPS["lok_sabha"],
            "history + Lok Sabha + candidate (after nominations)": GROUPS["history"] + GROUPS["lok_sabha"] + GROUPS["nomination"]}
    for kind, label in (("ridge", "Ridge"), ("gbm", "Gradient boosting")):
        for sname, cols in sets.items():
            results.append({"method": label, "kind": "learned", "features": sname, **score(yb, fit_predict(kind, cols, xa, ya, xb, seed))})
    base = [r for r in results if r["kind"] == "baseline"]
    best = min(base, key=lambda r: r["mean_mae_pts"])
    learned = [r for r in results if r["kind"] == "learned"]
    for r in learned:
        r["beats_best_baseline_on_every_front"] = all(r["mae_pts"][f] <= best["mae_pts"][f] - margin for f in FRONTS)
    return {"train": "assembly 2012 + Lok Sabha 2009/2014 -> assembly 2017", "test": "assembly 2017 + Lok Sabha 2014/2019 -> assembly 2022",
            "n_train": int(len(xa)), "n_test": int(len(xb)), "best_simple_baseline": best["method"], "best_baseline_mean_mae_pts": best["mean_mae_pts"],
            "promotion_margin_pts": margin, "results": results,
            "any_learned_model_promoted": any(r["beats_best_baseline_on_every_front"] for r in learned)}


def cross_section_test(feats: F.Features, ext: pd.DataFrame, seed: int) -> dict:
    """Inside task B only: 5-fold CV grouped by district. Shows whether AC-level extras add information; not a forward test."""
    xb, yb = task_frame(feats, ext, TASKS["B"])
    ex = ext[EXTRAS_B]
    xb = xb.join(ex)
    ok = feats.clean.to_numpy()
    xb, yb = xb[ok], yb[ok]
    groups = feats.meta.loc[xb.index, "district"].to_numpy()
    base_cols = GROUPS["history"] + GROUPS["lok_sabha"] + GROUPS["nomination"]
    sets = {"history + Lok Sabha + candidate": base_cols, "... plus turnout, electors and 2019 booth-sheet fronts": base_cols + EXTRAS_B}
    res = []
    for kind, label in (("ridge", "Ridge"), ("gbm", "Gradient boosting")):
        for sname, cols in sets.items():
            pred = pd.DataFrame(index=xb.index, columns=FRONTS, dtype=float)
            for tr, te in GroupKFold(n_splits=5).split(xb, groups=groups):
                pred.iloc[te] = fit_predict(kind, cols, xb.iloc[tr], yb.iloc[tr], xb.iloc[te], seed).to_numpy()
            res.append({"method": label, "features": sname, **score(yb, pred)})
    prev_only = score(yb, baselines(xb, yb)["Same as last assembly election"])
    return {"design": "5-fold CV grouped by district inside task B (assembly 2022 as target)", "n": int(len(xb)),
            "same_as_last_for_reference": prev_only, "results": res}


def to_markdown(rep: dict) -> str:
    f = rep["forward_test"]
    lines = ["# Extended backtest", "", f"Train: {f['train']}.  Test: {f['test']}.  {f['n_test']} constituencies in the test.", "",
             "Average miss in percentage points (lower is better).", "",
             "| Method | Features | BJP-led | SP/INC | BSP | Mean | 80% within | Lead called right |", "|---|---|---|---|---|---|---|---|"]
    for r in f["results"]:
        m = r["mae_pts"]
        lines.append(f"| {r['method']} | {r['features']} | {m['nda']} | {m['opp']} | {m['bsp']} | {r['mean_mae_pts']} | {r['within80_pts']} | {r['lead_call_accuracy']:.0%} |")
    lines += ["", f"Best simple baseline: **{f['best_simple_baseline']}** (mean miss {f['best_baseline_mean_mae_pts']} pts).",
              f"A learned model is promoted only if it beats that on every front by {f['promotion_margin_pts']} pts. Promoted: **{f['any_learned_model_promoted']}**.", "",
              "## Cross-section check (not a forward test)", "", rep["cross_section_test"]["design"], "",
              "| Method | Features | BJP-led | SP/INC | BSP | Mean |", "|---|---|---|---|---|---|"]
    for r in rep["cross_section_test"]["results"]:
        m = r["mae_pts"]
        lines.append(f"| {r['method']} | {r['features']} | {m['nda']} | {m['opp']} | {m['bsp']} | {r['mean_mae_pts']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = F.load_config()
    feats = F.build_features(cfg)
    ext = pd.read_csv(X.PROC / "ac_features_ext.csv", index_col="ac")
    rep = {"seed": cfg["seed"], "forward_test": forward_test(feats, ext, cfg, cfg["seed"]), "cross_section_test": cross_section_test(feats, ext, cfg["seed"])}
    X.OUT.mkdir(parents=True, exist_ok=True)
    (X.OUT / "backtest_ext_report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    md = to_markdown(rep)
    (X.OUT / "backtest_ext_report.md").write_text(md, encoding="utf-8")
    log.info("%s", md)


if __name__ == "__main__":
    main()
