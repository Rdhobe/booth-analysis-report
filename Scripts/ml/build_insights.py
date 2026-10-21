"""Build the Phase 1 AC-level insights: features -> models -> JSON outputs.

Run from the repo root:
    python Scripts/ml/build_insights.py                 # full build, writes output/ml/
    python Scripts/ml/build_insights.py --quick         # skip the injected-anomaly test (dev only)

Writes (generated, safe to delete and regenerate):
    output/ml/ac_insights.json    per-AC types, look-alikes, surprise, expected range, history + overview
    output/ml/model_card.json     data hashes, checks, selection tables, backtest, limits
    output/ml/ac_typology.joblib  the fitted scaler + k-means (a few KB)
"""
from __future__ import annotations

import os

os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))   # stops joblib probing 'wmic' on Windows

import argparse
import datetime as dt
import hashlib
import json
import logging
import platform
import re
import shutil
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

try:
    from . import booth_sheets_generic as BG
    from . import features as F
    from . import models as M
except ImportError:  # run as a script from Scripts/ml
    import booth_sheets_generic as BG
    import features as F
    import models as M

log = logging.getLogger("ml.build")
ROOT = F.ROOT
OUT_DIR = ROOT / "output" / "ml"


def _r(x, n: int = 4):
    """Round to a plain Python float; NaN becomes None."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    x = float(x)
    return None if np.isnan(x) else round(x, n)


PROC = ROOT / "data" / "processed"
ELECTION_FILES = {"VS2017": ("Assembly 2017", "2017"), "LS2019": ("Lok Sabha 2019", "2019"), "VS2022": ("Assembly 2022", "2022")}
# measured on 2026-10-17 before the label-based reader, the .xlsx support and the "Voters Secured" header fix (see brain/CHANGELOG.md)
FIRST_RUN = {"VS2017": {"read": 328, "trusted_turnout": 300}, "LS2019": {"read": 321, "trusted_turnout": 298}, "VS2022": {"read": 205, "trusted_turnout": 175}}


def load_ext() -> pd.DataFrame | None:
    """Extended AC features (turnout, electors, ...) written by features_ext.py, if it has been run."""
    path = PROC / "ac_features_ext.csv"
    return pd.read_csv(path, index_col="ac") if path.exists() else None


def turnout_block(ext: pd.DataFrame | None, ac: int) -> dict | None:
    """Turnout and electors per election for one AC. Missing or untrusted values are None, never guessed."""
    if ext is None or ac not in ext.index:
        return None
    r = ext.loc[ac]
    pairs = {"VS2017": ("turnout_17_best", "electors_17_best"), "LS2019": ("turnout_19", "electors_19"),
             "VS2022": ("turnout_22", "electors_22"), "LS2024": ("turnout_24", "electors_24")}
    out = {"turnout": {e: _r(r[t]) for e, (t, _el) in pairs.items()}, "electors": {e: (None if pd.isna(r[el]) else int(r[el])) for e, (_t, el) in pairs.items()}}
    out["source_2017"] = "booth sheets" if pd.notna(r["turnout_17"]) else "2017 roll file"
    return out


def statewide_turnout(ext: pd.DataFrame | None) -> list[dict]:
    """Votes over electors, summed over the constituencies with trusted values (so the count of ACs is shown next to it)."""
    if ext is None:
        return []
    rows = []
    for e, (t, el, src) in {"VS2017": ("turnout_17_best", "electors_17_best", "booth sheets, roll file where a sheet failed its checks"),
                            "LS2019": ("turnout_19", "electors_19", "booth sheets"), "VS2022": ("turnout_22", "electors_22", "booth sheets"),
                            "LS2024": ("turnout_24", "electors_24", "ECI segment file, EVM votes only")}.items():
        d = ext[[t, el]].dropna()
        d = d[d[el] > 0]
        rows.append({"election": e, "acs": int(len(d)), "turnout": _r((d[t] * d[el]).sum() / d[el].sum()), "source": src})
    return rows


def data_coverage(ext: pd.DataFrame | None) -> dict | None:
    """What was read from the ECI booth sheets, what passed the checks, and why the rest is unread."""
    cov_p, sums_p, rep_p = PROC / "ac_booth_coverage.csv", PROC / "ac_booth_sums.csv", OUT_DIR / "features_ext_report.json"
    if not (cov_p.exists() and sums_p.exists() and rep_p.exists()):
        return None
    cov, sums, rep = pd.read_csv(cov_p), pd.read_csv(sums_p), json.loads(rep_p.read_text(encoding="utf-8"))
    out = []
    for e, (label, year) in ELECTION_FILES.items():
        c = cov[cov["election"] == e]
        unread: dict[str, list[str]] = {}
        for r in c[c["status"] != "ok"].itertuples():
            try:
                why = BG.sniff_reason(ROOT / "data" / year / r.file)
            except Exception:                                  # xlrd missing or file unreadable: say so rather than guess
                why = "not checked"
            unread.setdefault(why, []).append(re.sub(r"^AC|\.xlsx?$", "", r.file, flags=re.I))
        t = rep["turnout_and_electors"][f"{e}_turnout"]
        s_e = sums[sums["election"] == e]
        out.append({"election": e, "label": label, "files": int(len(c)), "acs_read": int(len(s_e)), "trusted_turnout": int(t["trusted"]),
                    "first_run": FIRST_RUN[e], "readers": {k: int(v) for k, v in s_e["reader"].value_counts().items()},
                    "unread": [{"reason": k, "files": sorted(v, key=lambda x: int(x) if x.isdigit() else 0)} for k, v in sorted(unread.items())]})
    return {
        "note": "Booth sheets summed to constituency level. A value is kept only if it passes its checks; otherwise it is left missing, never guessed.",
        "by_election": out,
        "checks": {"vs2017_votes_vs_official": rep["turnout_and_electors"]["VS2017_reconcile"],
                   "vs2022_votes_vs_official": rep["turnout_and_electors"]["VS2022_reconcile"],
                   "ls2019_seats_vs_official": {k: rep["ls2019_vs_official_by_parliamentary_seat"][k] for k in ("complete_pcs", "both_within_tol")},
                   "ls2019_constituencies_in_verified_seats": rep["ls2019_fronts"]["acs_in_seats_that_passed_official_check"]},
        "filled": "Turnout for 2017 is available for all 403: from the booth sheet where it passes the checks, otherwise official votes over the 2017 roll file.",
    }


def _history(f: F.Features, ac: int) -> dict:
    w, out = f.wide, {}
    for e in f.elections:
        win = f.winners.loc[(ac, e)]
        h = {
            "sh": [_r(w.loc[ac, f"{c}_{e}"]) for c in f.model_camps],
            "raw": [_r(w.loc[ac, f"{c}_{e}"]) for c in f.camps],
            "votes": int(w.loc[ac, f"polled_{e}"]),
            "winner": {"name": str(win["candidate"]), "party": str(win["party"]), "camp": str(win["camp"]),
                       "share": _r(win["winner_share"])},
            "margin_votes": int(win["margin_votes"]), "margin_pp": _r(win["margin_pp"]),
            "candidates": int(w.loc[ac, f"ncand_{e}"]),
        }
        if e == "LS2024":
            h["electors"] = int(w.loc[ac, "electors_LS2024"])
            h["turnout"] = _r(w.loc[ac, "turnout_LS2024"])
        out[e] = h
    return out


def _driver(camp: str, change: float, peer: float, labels: dict) -> str:
    return f"{labels[camp]} share changed {change * 100:+.1f} pts; ACs that looked like it changed {peer * 100:+.1f} pts"


def build_acs(f, ty, sur, bands, cfg, ext=None) -> list[dict]:
    labels = cfg["camps"]["labels"]
    base = cfg["baseline"]["forecast_base_election"]
    n_look = cfg["typology"]["look_alikes"]
    flags_by_ac: dict[int, list[str]] = {}
    for item in f.checks["low_coverage_ac_elections"]:
        flags_by_ac.setdefault(item["ac"], []).append(
            f"{item['election']} results are incomplete in the source file (rows cover {item['coverage'] * 100:.0f}% of votes polled)")
    acs = []
    for ac in f.wide.index:
        ac = int(ac)
        tid = int(ty["labels"].loc[ac])
        la = [{"ac": a, "name": f.meta.loc[a, "name"], "distance": d} for a, d in M.look_alikes(ty["distance"], ac, n_look)]
        s = sur.loc[ac]
        if bool(f.clean.loc[ac]):
            top = sorted(cfg["surprise"]["camps"], key=lambda c: abs(float(s[f"z_{c}"])), reverse=True)[:2]
            surprise = {
                "flag": bool(s["flag"]), "strength": str(s["strength"]), "maxz": _r(s["maxz"], 2),
                "z": {c: _r(s[f"z_{c}"], 2) for c in cfg["surprise"]["camps"]},
                "change": {c: _r(s[f"change_{c}"]) for c in cfg["surprise"]["camps"]},
                "peer_change": {c: _r(s[f"peer_{c}"]) for c in cfg["surprise"]["camps"]},
                "drivers": [_driver(c, float(s[f"change_{c}"]), float(s[f"peer_{c}"]), labels) for c in top],
            }
        else:
            surprise = None
        expected = {}
        for c in cfg["surprise"]["camps"]:
            e = float(f.wide.loc[ac, f"{c}_{base}"])
            b, wide_b = bands[c]["band_" + cfg["baseline"]["band_source"]], bands[c]["band_pooled"]
            expected[c] = {"expected": _r(e), "low": _r(max(0.0, e - b)), "high": _r(min(1.0, e + b)),
                           "stress_low": _r(max(0.0, e - wide_b)), "stress_high": _r(min(1.0, e + wide_b))}
        acs.append({
            "ac": ac, "name": f.meta.loc[ac, "name"], "district": f.meta.loc[ac, "district"],
            "reserved": f.meta.loc[ac, "reserved_for"], "clean": bool(f.clean.loc[ac]),
            "data_flags": flags_by_ac.get(ac, []), "history": _history(f, ac), "turnout_block": turnout_block(ext, ac),
            "type": {"id": tid, "label": ty["names"][tid]}, "look_alikes": la,
            "surprise": surprise, "expected": {"base": base, "camps": expected},
        })
    return acs


def build_types(f, ty, sur) -> list[dict]:
    Z = ty["P_all"]
    km, remap = ty["kmeans"], ty["remap"]
    inv = {new: old for old, new in remap.items()}
    out = []
    for tid in sorted(ty["names"]):
        members = ty["labels"].index[ty["labels"] == tid]
        centre = km.cluster_centers_[inv[tid]]
        d = np.sqrt(((Z[f.wide.index.get_indexer(members)] - centre) ** 2).sum(axis=1))
        typical = [int(members[i]) for i in np.argsort(d, kind="stable")[:5]]
        m = ty["means"].loc[tid]
        out.append({
            "id": tid, "label": ty["names"][tid], "size": int(len(members)),
            "mean_shares": {e: {c: _r(m[f"{c}_{e}"]) for c in ("NDA", "OPP", "BSP")} for e in f.elections},
            "typical_acs": typical, "members": [int(a) for a in members],
            "flagged": int(sur.loc[members, "flag"].sum()),
        })
    return out


def build_overview(f, cfg, ext=None) -> dict:
    w, E, camps = f.wide, f.elections, f.camps
    rows_total = {e: float(w[f"rows_votes_{e}"].sum()) for e in E}
    state = {e: {
        "votes": int(w[f"polled_{e}"].sum()),
        "camp_share": {c: _r((w[f"{c}_{e}"] * w[f"rows_votes_{e}"]).sum() / rows_total[e]) for c in f.model_camps},
        "seats": {c: int(v) for c, v in f.checks["seats_by_camp"][e].items()},
    } for e in E}

    def ac_row(a, v):
        return {"ac": int(a), "name": f.meta.loc[a, "name"], "district": f.meta.loc[a, "district"], "value": _r(v, 4)}

    growth = (w["polled_VS2022"] - w["polled_VS2017"])
    pct = growth / w["polled_VS2017"]
    lists = {
        "top_votes_vs2022": [ac_row(a, v) for a, v in w["polled_VS2022"].nlargest(10).items()],
        "top_growth_votes": [dict(ac_row(a, v), pct=_r(pct[a])) for a, v in growth.nlargest(10).items()],
        "turnout_ls2024_high": [ac_row(a, v) for a, v in w["turnout_LS2024"].nlargest(10).items()],
        "turnout_ls2024_low": [ac_row(a, v) for a, v in w["turnout_LS2024"].nsmallest(10).items()],
    }

    g = w.join(f.meta[["district"]]).groupby("district")
    rows = []
    for dname, d in g:
        r22, r24 = d["rows_votes_VS2022"].sum(), d["rows_votes_LS2024"].sum()
        rows.append({
            "district": dname, "acs": int(len(d)),
            "votes_2017": int(d["polled_VS2017"].sum()), "votes_2022": int(d["polled_VS2022"].sum()),
            "growth_pct": _r(d["polled_VS2022"].sum() / d["polled_VS2017"].sum() - 1),
            "evm_votes_2024": int(d["rows_votes_LS2024"].sum()), "electors_2024": int(d["electors_LS2024"].sum()),
            "turnout_2024": _r(d["rows_votes_LS2024"].sum() / d["electors_LS2024"].sum()),
            "share_2022": {c: _r((d[f"{c}_VS2022"] * d["rows_votes_VS2022"]).sum() / r22) for c in ("NDA", "OPP", "BSP")},
            "share_2024": {c: _r((d[f"{c}_LS2024"] * d["rows_votes_LS2024"]).sum() / r24) for c in ("NDA", "OPP", "BSP")},
        })
    rows.sort(key=lambda r: r["district"])
    return {"state": state, "lists": lists, "districts": rows, "turnout": statewide_turnout(ext)}


def build_model_card(f, ty, sur, bands, learned, injected, cfg, started, coverage=None) -> dict:
    flag_rate = float(sur.loc[f.clean.to_numpy(), "flag"].mean())
    versions = {"python": platform.python_version(), "scikit-learn": sklearn.__version__,
                "numpy": np.__version__, "pandas": pd.__version__}
    return {
        "name": "UPBI AC insights", "version": cfg["version"], "created_utc": started.isoformat(timespec="seconds"),
        "seed": cfg["seed"], "versions": versions,
        "scope": "Constituency level only. Assembly 2012, 2017, 2022 and Lok Sabha 2024 by assembly segment (EVM votes). No booth data, no news, no demographics.",
        "data_checks": f.checks,
        "data_coverage": coverage,
        "typology": {"selection": ty["selection"], "chosen_k": ty["chosen_k"], "chosen": ty["chosen"],
                     "pca_components": cfg["typology"]["pca_components"], "pca_variance_explained": ty["pca_variance_explained"],
                     "honest_reading": "ACs form a continuum rather than separate clusters (silhouette is modest). Groups are convenient slices, re-checked for stability by resampling.",
                     "group_sizes": {int(k): int(v) for k, v in ty["labels"].value_counts().sort_index().items()},
                     "note": "Group labels are generated from average vote shares and need review by a person."},
        "surprise": {"rule": "flag if (modified z >= z_flag and Isolation Forest agrees) or modified z >= z_extreme",
                     "thresholds": {k: cfg["surprise"][k] for k in ("z_flag", "z_extreme", "isolation_forest_bottom_pct", "peers")},
                     "flag_rate": round(flag_rate, 4), "flagged": int(sur["flag"].sum()),
                     "injected_anomaly_test": injected,
                     "wording": "Flags are statistical outliers. They are not evidence of anything improper."},
        "baseline": {"definition": "Expected share = share at the base election; band = 80% quantile of absolute error of 'same as last election' over the listed transitions.",
                     "transitions": cfg["baseline"]["transitions"], "bands": bands},
        "learned_forecaster_vs_baseline": learned,
        "limits": [
            "Only three assembly elections and one Lok Sabha election feed these models; ranges are wide on purpose.",
            "Expected ranges say what a repeat of the last result would look like, with the error seen in past transitions. They are not predictions of 2027.",
            "The second transition (2012 to 2017) includes a one-off jump in BJP-led vote share, which widens the pooled band.",
            "Camps combine allied party codes per election (see configs/ml_config.json); small allies not listed fall into Others.",
            "Lok Sabha 2024 figures are EVM votes only (postal ballots excluded) and are not assembly results.",
            "Type labels are automatic descriptions of average vote shares, not findings about why people vote.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--quick", action="store_true", help="skip the injected-anomaly test")
    ap.add_argument("--export-server", action="store_true",
                    help="also copy ac_insights.json and model_card.json to server/insights_data/ (what the API serves)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    started = dt.datetime.now(dt.timezone.utc)

    cfg = F.load_config()
    seed = cfg["seed"]
    f = F.build_features(cfg)
    log.info("features: %d ACs, %d usable for fitting", len(f.wide), int(f.clean.sum()))

    ty = M.fit_typology(f, cfg, seed)
    log.info("typology: k=%d (silhouette %.3f, stability %.3f)", ty["chosen_k"], ty["chosen"]["silhouette"], ty["chosen"]["stability_ari_mean"])
    sur = M.compute_surprise(f.wide, f.clean, f.model_camps, cfg, seed)
    log.info("surprise: %d of %d ACs flagged (%.1f%%)", int(sur["flag"].sum()), int(f.clean.sum()), 100 * sur.loc[f.clean.to_numpy(), "flag"].mean())
    bands = M.baseline_bands(f.wide, f.clean, cfg)
    learned = M.compare_learned_forecasters(f.wide, f.clean, f.model_camps, cfg, seed)
    log.info("learned vs baseline: %s", learned["decision"])
    injected = [] if args.quick else M.injected_anomaly_test(f.wide, f.clean, f.model_camps, cfg, seed)
    for row in injected:
        log.info("injected %+d pts: recall %.2f, false flags %.3f", row["shift_pts"], row["recall"], row["false_flag_rate"])

    ext = load_ext()
    data_version = hashlib.sha256(json.dumps(f.checks["inputs_sha256"], sort_keys=True).encode()).hexdigest()[:12]
    payload = {
        "meta": {"data_version": data_version, "model_version": cfg["version"], "camps": f.model_camps, "raw_camps": f.camps,
                 "band_source": cfg["baseline"]["band_source"], "band_note": cfg["baseline"]["band_note"],
                 "camp_labels": cfg["camps"]["labels"], "elections": f.elections,
                 "election_labels": cfg["elections"]["labels"], "base_election": cfg["baseline"]["forecast_base_election"],
                 "band_quantile": cfg["baseline"]["band_quantile"], "bands": bands},
        "overview": build_overview(f, cfg, ext),
        "types": build_types(f, ty, sur),
        "acs": build_acs(f, ty, sur, bands, cfg, ext),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ac_insights.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    card = build_model_card(f, ty, sur, bands, learned, injected, cfg, started, data_coverage(ext))
    (args.out / "model_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    joblib.dump({"scaler": ty["scaler"], "pca": ty["pca"], "kmeans": ty["kmeans"], "columns": ty["columns"],
                 "names": ty["names"], "remap": ty["remap"], "data_version": data_version}, args.out / "ac_typology.joblib")
    log.info("wrote %s (%s KB insights, %s KB model)", args.out,
             (args.out / "ac_insights.json").stat().st_size // 1024, (args.out / "ac_typology.joblib").stat().st_size // 1024)
    if args.export_server:
        target = ROOT / "server" / "insights_data"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("ac_insights.json", "model_card.json"):
            shutil.copyfile(args.out / name, target / name)
        log.info("exported to %s", target)


if __name__ == "__main__":
    main()
