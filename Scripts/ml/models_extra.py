"""Additional seat-level models for UPBI (all classical, seeded, CPU only).

1. watch_*       Seat watch score: which seats are most likely to change hands? A fixed rule (closeness of the last result plus how the
                 Lok Sabha mood moved against the leading side). A learned logistic regression is backtested against it.
2. turnout_*     Expected turnout from other elections and seat facts (ridge regression, whole districts held out) and the gap to actual.
3. alliance_*    How much of a partner's vote moved to an alliance candidate (ecological regression by parliamentary seat, bootstrap).
4. simulator_*   What-if seat simulator: swing by region and front, optional alliance, most likely leader per seat. Hindcasts decide its claims.
5. booth_*       Booth segments (Stronghold / Lean / Competitive) from the 2024 Form 20 workbooks that match the official totals.

Every model reports a backtest next to its output. A learned model replaces its simple baseline only if it clears the gate in
configs/ml_config.json ("extra"); otherwise the baseline is used and the result is reported as "not promoted".
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

log = logging.getLogger("ml.extra")

FR4 = ["NDA", "OPP", "BSP", "OTH"]
FR5 = ["NDA", "SPF", "INC", "BSP", "OTH"]
FRONT_NAMES = {"NDA": "BJP-led (NDA)", "SPF": "SP-led", "INC": "INC", "BSP": "BSP", "OTH": "Others", "OPP": "SP/INC bloc"}


def r(x, nd=4):
    """JSON-safe rounded float (None for missing)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(v) else round(v, nd)


# ============================================================================== regions
def load_regions(path: Path) -> tuple[dict, dict]:
    """(region -> [districts], district -> region). The file is a DRAFT list that needs sign-off."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    regions = d["regions"]
    dist2reg = {dist: reg for reg, ds in regions.items() for dist in ds}
    return regions, dist2reg


# ============================================================================== 1. seat watch score
def _winner_front4(feats, election: str) -> pd.Series:
    c = feats.winners.xs(election, level="election")["camp"]
    return c.map({"NDA": "NDA", "SPF": "OPP", "INC": "OPP", "BSP": "BSP"}).fillna("OTH").reindex(feats.wide.index)


def _ls_mass(ext: pd.DataFrame, y: str) -> pd.Series:
    """Lok Sabha lean of the parliamentary seat: BJP-led share minus everyone else's (excluding others)."""
    nda = ext[f"ls{y}_nda"]
    return nda - (1 - nda - ext[f"ls{y}_oth"])


def watch_frame(feats, ext: pd.DataFrame, e0: str, ls_now: str, ls_prev: str) -> pd.DataFrame:
    """Facts known before the next assembly election: the last result at e0 and the Lok Sabha vote since (shown per seat)."""
    w = feats.wide
    x = pd.DataFrame(index=w.index)
    sh = w[[f"{f}_{e0}" for f in FR4]].set_axis(FR4, axis=1)
    lead = _winner_front4(feats, e0)
    s = -np.sort(-sh.to_numpy(), axis=1)
    win = feats.winners.xs(e0, level="election").reindex(x.index)
    x["margin_pp"] = win["margin_pp"]
    x["margin_votes"] = win["margin_votes"]
    x["leader_share"], x["challenger_share"], x["third_share"] = s[:, 0], s[:, 1], s[:, 2]
    x["ncand"] = w[f"ncand_{e0}"]
    m_ls, m_lp = _ls_mass(ext, ls_now).reindex(x.index), _ls_mass(ext, ls_prev).reindex(x.index)
    m_vs = sh["NDA"] - (sh["OPP"] + sh["BSP"])
    sign = np.where(lead == "NDA", 1.0, -1.0)
    x["mood_against_leader"] = sign * (m_vs - m_ls)           # > 0: the Lok Sabha mood moved against the side that led
    x["ls_agrees_with_leader"] = ((m_ls > 0) == (lead == "NDA")).astype(float).where(m_ls.notna())
    x["ls_volatility"] = (m_ls - m_lp).abs()
    x["leader_front"] = lead
    return x


def watch_labels(feats, e0: str, e1: str) -> pd.Series:
    a, b = _winner_front4(feats, e0), _winner_front4(feats, e1)
    return (a != b).astype(int)


def watch_composite(x: pd.DataFrame, mood_weight: float) -> pd.Series:
    """Higher = more likely to change hands. Percentile ranks, so nothing is fitted and no election-specific scale leaks in."""
    close = (-x["margin_pp"]).rank(pct=True)
    mood = x["mood_against_leader"].rank(pct=True).fillna(0.5)
    return (1 - mood_weight) * close + mood_weight * mood


def _prec_at(y: pd.Series, score: pd.Series, k: int) -> float:
    top = score.sort_values(ascending=False, kind="mergesort").index[:k]
    return float(y.loc[top].mean())


def _band_edges(score: pd.Series, fractions: list[float]) -> list[float]:
    """Score cut-points for cumulative top fractions, e.g. [0.10, 0.25, 0.50]: top 10%, next 15%, next 25%."""
    return [float(score.quantile(1 - f)) for f in fractions]


def _band_of(score: pd.Series, edges: list[float], names: list[str]) -> pd.Series:
    out = pd.Series(names[-1], index=score.index)
    for edge, name in reversed(list(zip(edges, names[:-1]))):
        out[score >= edge] = name
    return out


def watch_backtest(feats, ext: pd.DataFrame, cfg: dict) -> dict:
    wc = cfg["extra"]["watch"]
    pairs = {"VS2012->VS2017": ("VS2012", "VS2017", "14", "09"), "VS2017->VS2022": ("VS2017", "VS2022", "19", "14")}
    frames = {k: watch_frame(feats, ext, e0, ln, lp) for k, (e0, e1, ln, lp) in pairs.items()}
    labels = {k: watch_labels(feats, e0, e1) for k, (e0, e1, _, _) in pairs.items()}
    cols = ["margin_pp", "leader_share", "challenger_share", "third_share", "ncand", "mood_against_leader", "ls_agrees_with_leader", "ls_volatility"]

    def logit(train_key: str):
        x, y = frames[train_key][cols], labels[train_key]
        ok = x.notna().all(axis=1)
        return make_pipeline(StandardScaler(), LogisticRegression(C=wc["logistic_C"], max_iter=2000)).fit(x[ok], y[ok])

    models = {k: logit(k) for k in pairs}
    out = {"transitions": {}, "bands": {}}
    other = {"VS2012->VS2017": "VS2017->VS2022", "VS2017->VS2022": "VS2012->VS2017"}
    gate_ok = []
    for k, (e0, e1, _, _) in pairs.items():
        x, y = frames[k], labels[k]
        ok = x[cols].notna().all(axis=1)
        xx, yy = x[ok], y[ok]
        scores = {
            "margin_only": -xx["margin_pp"],
            "rule": watch_composite(xx, wc["mood_weight"]),
            "logistic (trained on the other transition)": pd.Series(models[other[k]].decision_function(xx[cols]), index=xx.index),
        }
        rows = {}
        for name, sc in scores.items():
            rows[name] = {"auc": r(roc_auc_score(yy, sc), 3), **{f"precision_at_{kk}": r(_prec_at(yy, sc, kk), 2) for kk in wc["eval_top_k"]}}
        out["transitions"][k] = {"seats": int(len(yy)), "flips": int(yy.sum()), "flip_rate": r(yy.mean(), 3), "scores": rows}
        k0 = f"precision_at_{wc['eval_top_k'][0]}"
        gate_ok.append((rows["logistic (trained on the other transition)"][k0] - rows["margin_only"][k0]) * 100 >= wc["promotion_margin_pts"])
        # observed flip rate by band (bands cut within the same election)
        comp = scores["rule"]
        edges = _band_edges(comp, wc["band_top_fractions"])
        band = _band_of(comp, edges, wc["band_names"])
        out["bands"][k] = [{"band": b, "seats": int((band == b).sum()), "flip_rate": r(yy[band == b].mean(), 2)} for b in wc["band_names"]]
    out["decision"] = {
        "logistic_beats_margin_only_by_gate_in_both_directions": bool(all(gate_ok)),
        "used": "rule" if not all(gate_ok) else "logistic",
        "text": ("A learned logistic regression did not beat ranking by margin alone by the required "
                 f"{wc['promotion_margin_pts']:.0f} points of precision in both directions, so the transparent rule is used."
                 if not all(gate_ok) else "The learned model cleared its gate in both directions."),
    }
    out["features_used_by_logistic"] = cols
    return out


def watch_current(feats, ext: pd.DataFrame, cfg: dict, backtest: dict) -> dict:
    """Scores for the next assembly election, from the 2022 result and the 2024 Lok Sabha vote. Rank 1 = highest watch."""
    wc = cfg["extra"]["watch"]
    x = watch_frame(feats, ext, "VS2022", "24", "19")
    comp = watch_composite(x, wc["mood_weight"])
    edges = _band_edges(comp, wc["band_top_fractions"])
    band = _band_of(comp, edges, wc["band_names"])
    rank = comp.rank(ascending=False, method="first").astype(int)
    flips_hist = (watch_labels(feats, "VS2012", "VS2017") + watch_labels(feats, "VS2017", "VS2022"))
    pct_closer = (x["margin_pp"].rank(pct=True) * 100)
    out = {}
    for ac in x.index:
        row = x.loc[ac]
        reasons = []
        if np.isfinite(row["margin_pp"]):
            reasons.append(f"Won by {int(row['margin_votes']):,} votes ({row['margin_pp'] * 100:.1f} points) in 2022, closer than {100 - pct_closer.loc[ac]:.0f}% of seats."
                           if pct_closer.loc[ac] <= 50 else f"Won by {int(row['margin_votes']):,} votes ({row['margin_pp'] * 100:.1f} points) in 2022, a wider margin than {pct_closer.loc[ac]:.0f}% of seats.")
        if np.isfinite(row["mood_against_leader"]) and row["mood_against_leader"] > 0.05:
            reasons.append(f"The 2024 Lok Sabha vote in this area moved {row['mood_against_leader'] * 100:.0f} points against the side that led in 2022.")
        if row["ls_agrees_with_leader"] == 0:
            reasons.append("The Lok Sabha seat was led by the other side in 2024.")
        out[int(ac)] = {
            "score": r(comp.loc[ac] * 100, 1), "band": str(band.loc[ac]), "rank": int(rank.loc[ac]),
            "margin_votes": None if not np.isfinite(row["margin_votes"]) else int(row["margin_votes"]),
            "margin_pts": r(row["margin_pp"] * 100, 1), "mood_against_leader_pts": r(row["mood_against_leader"] * 100, 1),
            "ls_disagrees": None if not np.isfinite(row["ls_agrees_with_leader"]) else bool(row["ls_agrees_with_leader"] == 0),
            "past_flips": int(flips_hist.loc[ac]), "leader_front": str(row["leader_front"]), "reasons": reasons[:3],
        }
    return {"per_ac": out, "band_cutoffs": {n: r(e, 4) for n, e in zip(wc["band_names"][:-1], edges)}}


# ============================================================================== 2. expected turnout
def _turnout_table(feats, ext: pd.DataFrame) -> pd.DataFrame:
    d = pd.DataFrame(index=ext.index)
    d["t17"], d["t19"], d["t22"], d["t24"] = ext["turnout_17_best"], ext["turnout_19"], ext["turnout_22"], ext["turnout_24"]
    d["el17"], d["growth"] = ext["electors_17_best"], ext["elector_growth_17_24"]
    d["fem17"], d["fem19"], d["fem22"] = ext["female_share_voters_17"], ext["female_share_voters_19"], ext["female_share_voters_22"]
    d["reserved"] = feats.meta["reserved_for"].astype(str).str.upper().isin(["SC", "ST"]).astype(int).reindex(d.index)
    d["district"] = ext["district"]
    return d


TURNOUT_SPECS = {
    "VS2022": {"col": "t22", "prev": "t17", "feats": ["t17", "t19", "el17", "growth", "fem17", "fem19", "reserved"], "label": "Assembly 2022"},
    "LS2024": {"col": "t24", "prev": "t19", "feats": ["t17", "t19", "t22", "el17", "growth", "fem17", "fem19", "fem22", "reserved"], "label": "Lok Sabha 2024"},
}


def _make_reg(kind: str, alpha: float, seed: int):
    if kind == "ridge":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=alpha))
    return make_pipeline(SimpleImputer(strategy="median"), HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, random_state=seed))


def turnout_model(feats, ext: pd.DataFrame, cfg: dict, seed: int) -> dict:
    tc = cfg["extra"]["turnout"]
    d = _turnout_table(feats, ext)
    per_ac: dict[int, dict] = {int(a): {} for a in d.index}
    targets = {}
    for tname in tc["targets"]:
        spec = TURNOUT_SPECS[tname]
        y, prev, cols = d[spec["col"]], d[spec["prev"]], spec["feats"]
        known = y.notna()
        both = known & prev.notna()
        persist = prev
        trend = prev + float((y[both] - prev[both]).mean())
        oof = {}
        for kind in ("ridge", "gbm"):
            pred = pd.Series(np.nan, index=d.index)
            idx_known = d.index[known]
            gkf = GroupKFold(n_splits=tc["cv_folds"])
            for tr, te in gkf.split(idx_known, groups=d.loc[idx_known, "district"]):
                m = _make_reg(kind, tc["ridge_alpha"], seed).fit(d.loc[idx_known[tr], cols], y.loc[idx_known[tr]])
                pred.loc[idx_known[te]] = m.predict(d.loc[idx_known[te], cols])
            oof[kind] = pred
        mae = lambda p: float((y[both] - p[both]).abs().mean() * 100)                      # noqa: E731
        scores = {"persistence": mae(persist), "persistence_plus_statewide_change": mae(trend), "ridge": mae(oof["ridge"]), "gradient_boosting": mae(oof["gbm"])}
        best_kind = "ridge" if scores["ridge"] <= scores["gradient_boosting"] else "gbm"
        best_mae = min(scores["ridge"], scores["gradient_boosting"])
        promoted = (scores["persistence_plus_statewide_change"] - best_mae) >= tc["promotion_margin_pts"]
        if promoted:
            full = _make_reg(best_kind, tc["ridge_alpha"], seed).fit(d.loc[known, cols], y[known])
            expected = pd.Series(full.predict(d[cols]), index=d.index)
            expected[known] = oof[best_kind][known]           # a seat is never scored by a model that saw its own turnout
            used = {"ridge": "ridge regression", "gbm": "gradient boosting"}[best_kind]
        else:
            expected, used = trend, "persistence plus statewide change"
        gap = (y - expected)
        sd = float(gap.std())
        z = gap / sd
        rank = gap.rank(method="first").astype("Int64")
        for ac in d.index:
            per_ac[int(ac)][tname] = {
                "actual": r(y.loc[ac], 4), "expected": r(expected.loc[ac], 4), "gap_pts": r(gap.loc[ac] * 100, 1) if pd.notna(gap.loc[ac]) else None,
                "z": r(z.loc[ac], 2) if pd.notna(z.loc[ac]) else None, "flag": bool(z.loc[ac] <= tc["flag_z"]) if pd.notna(z.loc[ac]) else None,
                "rank_lowest": None if pd.isna(rank.loc[ac]) else int(rank.loc[ac]),
            }
        targets[tname] = {
            "label": spec["label"], "seats_scored": int(known.sum()), "model_used": used, "promoted": bool(promoted),
            "cv_mae_pts": {k: r(v, 2) for k, v in scores.items()}, "gap_sd_pts": r(sd * 100, 2),
            "statewide": {"actual_mean": r(y.mean(), 4), "expected_mean": r(expected[known].mean(), 4)},
            "features": cols,
        }
    state_f = {y: r(d[c].mean(), 4) for y, c in (("VS2017", "fem17"), ("LS2019", "fem19"), ("VS2022", "fem22"))}
    for ac in d.index:
        per_ac[int(ac)]["women_share_of_voters"] = {y: r(d.loc[ac, c], 4) for y, c in (("VS2017", "fem17"), ("LS2019", "fem19"), ("VS2022", "fem22"))}
    return {"per_ac": per_ac, "targets": targets, "women_share_statewide_mean": state_f}


# ============================================================================== 3. alliance transfer
def _pc_table(ext: pd.DataFrame) -> pd.DataFrame:
    return ext.groupby("pc").first()


def _blocs(pc: pd.DataFrame, y: str) -> pd.DataFrame:
    return pd.DataFrame({"SP": pc[f"ls{y}_sp"], "BSP": pc[f"ls{y}_bsp"], "RLD": pc[f"ls{y}_rld"], "INC": pc[f"ls{y}_inc"], "NDA": pc[f"ls{y}_nda"], "OTH": pc[f"ls{y}_oth"]})


def _fit_share(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Non-negative transfer rates in [0, 1] of each earlier bloc's voters to the alliance candidate (no intercept: shares sum to 1)."""
    return lsq_linear(X, y, bounds=(0.0, 1.0), method="bvls").x


def _group_estimates(X: pd.DataFrame, y: pd.Series, own: str, partner: str, others: list[str], rng, B: int, level: float, label: str) -> dict:
    cols = list(X.columns)
    Xv, yv = X.to_numpy(), y.to_numpy()
    beta = _fit_share(Xv, yv)
    boots = np.empty((B, len(cols)))
    n = len(yv)
    for b in range(B):
        i = rng.integers(0, n, n)
        boots[b] = _fit_share(Xv[i], yv[i])
    lo, hi = np.percentile(boots, [(1 - level) / 2 * 100, (1 + level) / 2 * 100], axis=0)
    # leave-one-out error against two naive rules
    loo = np.empty(n)
    for k in range(n):
        keep = np.arange(n) != k
        loo[k] = Xv[k] @ _fit_share(Xv[keep], yv[keep])
    ip, io = cols.index(partner), cols.index(own)
    naive_full = Xv[:, io] + Xv[:, ip]
    naive_none = Xv[:, io]
    rows = []
    for c in cols:
        j = cols.index(c)
        rows.append({"from": c, "estimate": r(beta[j], 2), "low": r(lo[j], 2), "high": r(hi[j], 2)})
    return {
        "label": label, "seats": int(n), "own": own, "partner": partner, "transfer_from_partner": r(beta[ip], 2),
        "transfer_interval": [r(lo[ip], 2), r(hi[ip], 2)], "retention_of_own": r(beta[io], 2), "all_blocs": rows,
        "loo_mae_pts": {"fitted": r(np.abs(yv - loo).mean() * 100, 2), "partner_votes_all_transfer": r(np.abs(yv - naive_full).mean() * 100, 2),
                        "partner_votes_none_transfer": r(np.abs(yv - naive_none).mean() * 100, 2)},
    }


def alliance_transfer(ext: pd.DataFrame, cfg: dict, seed: int) -> dict:
    ac = cfg["extra"]["alliance"]
    rng = np.random.default_rng(seed)
    pc = _pc_table(ext)
    b14, b19 = _blocs(pc, "14"), _blocs(pc, "19")
    out = {"method": "Ecological regression across parliamentary seats: the alliance candidate's share regressed (rates between 0 and 1, no intercept) "
                     "on each earlier bloc's share. Bootstrap interval over seats. These are estimates from 80 seats, not counts of voters.",
           "groups": [], "defaults": {}}
    # --- 2019: SP-BSP-RLD alliance, from the 2014 vote
    y19 = pc["ls19_sp"] + pc["ls19_bsp"] + pc["ls19_rld"]
    sp_seats = (pc["ls19_sp"] > pc["ls19_bsp"]) & (pc["ls19_sp"] > pc["ls19_rld"]) & (pc["ls19_sp"] > 0.05)
    bsp_seats = (pc["ls19_bsp"] > pc["ls19_sp"]) & (pc["ls19_bsp"] > pc["ls19_rld"]) & (pc["ls19_bsp"] > 0.05)
    groups = [
        ("2019 SP-BSP-RLD alliance, seats where SP stood: BSP's 2014 voters moved to the SP candidate", b14[sp_seats], y19[sp_seats], "SP", "BSP", "BSP", "SP"),
        ("2019 SP-BSP-RLD alliance, seats where BSP stood: SP's 2014 voters moved to the BSP candidate", b14[bsp_seats], y19[bsp_seats], "BSP", "SP", "SP", "BSP"),
    ]
    # --- 2024: SP-INC alliance, from the 2019 vote
    y24 = pc["ls24_sp"] + pc["ls24_inc"]
    sp24 = pc["ls24_sp"] > pc["ls24_inc"]
    groups += [
        ("2024 SP-INC alliance, seats where SP stood: INC's 2019 voters moved to the SP candidate", b19[sp24], y24[sp24], "SP", "INC", "INC", "SP"),
        ("2024 SP-INC alliance, seats where INC stood: SP's 2019 voters moved to the INC candidate", b19[~sp24 & (pc["ls24_inc"] > 0.05)], y24[~sp24 & (pc["ls24_inc"] > 0.05)], "INC", "SP", "SP", "INC"),
    ]
    for label, X, y, own, partner, frm, to in groups:
        if len(y) < ac["min_seats"]:
            out["groups"].append({"label": label, "seats": int(len(y)), "skipped": f"fewer than {ac['min_seats']} seats"})
            continue
        g = _group_estimates(X, y, own, partner, [], rng, ac["bootstrap"], ac["interval"], label)
        g.update({"from_bloc": frm, "to_candidate_of": to, "election": "LS2019" if "2019 SP" in label else "LS2024"})
        out["groups"].append(g)
    pick = lambda i: out["groups"][i] if "transfer_from_partner" in out["groups"][i] else None             # noqa: E731
    if pick(0):
        out["defaults"]["BSP_to_SP"] = {"rate": pick(0)["transfer_from_partner"], "interval": pick(0)["transfer_interval"], "source": "Lok Sabha 2019, seats where SP stood"}
    if pick(2):
        out["defaults"]["INC_to_SP"] = {"rate": pick(2)["transfer_from_partner"], "interval": pick(2)["transfer_interval"], "source": "Lok Sabha 2024, seats where SP stood"}
    out["caveat"] = "Lok Sabha transfer rates are borrowed for assembly scenarios; assembly elections have different candidates and local issues."
    return out


# ============================================================================== 4. what-if simulator
def _shares5(feats, e: str) -> pd.DataFrame:
    return feats.wide[[f"{f}_{e}" for f in FR5]].set_axis(FR5, axis=1)


def _winner5(feats, e: str) -> pd.Series:
    return feats.winners.xs(e, level="election")["camp"].reindex(feats.wide.index)


def simulate_reference(base: np.ndarray, region_idx: np.ndarray, swings: np.ndarray, alliance: str | None, rate: float) -> dict:
    """Numpy reference for the server's pure-Python simulator (the two must agree; see test_extra.py).

    base: seats x 5 shares (NDA, SPF, INC, BSP, OTH). swings: regions x 3 percentage-point changes (NDA, SPF, BSP) as fractions.
    alliance: None | "SP+INC" | "SP+BSP", with a transfer rate. Others (INC, OTH) absorb the opposite of the swings in proportion to their size.
    """
    s = base.copy()
    if alliance == "SP+INC":
        s[:, 1] += rate * s[:, 2]
        s[:, 2] *= (1 - rate)
    elif alliance == "SP+BSP":
        s[:, 1] += rate * s[:, 3]
        s[:, 3] *= (1 - rate)
    sw = swings[region_idx]                                               # seats x 3
    s[:, 0] += sw[:, 0]
    s[:, 1] += sw[:, 1]
    s[:, 3] += sw[:, 2]
    absorb = -sw.sum(axis=1)
    pool = s[:, 2] + s[:, 4]
    w_inc = np.where(pool > 0, s[:, 2] / np.where(pool > 0, pool, 1), 0.5)
    s[:, 2] += absorb * w_inc
    s[:, 4] += absorb * (1 - w_inc)
    s = np.clip(s, 0, None)
    s = s / s.sum(axis=1, keepdims=True)
    order = np.argsort(-s, axis=1, kind="stable")
    lead, second = order[:, 0], order[:, 1]
    rows = np.arange(len(s))
    return {"shares": s, "lead": lead, "second": second, "margin": s[rows, lead] - s[rows, second]}


def _region_swings_true(s0: pd.DataFrame, s1: pd.DataFrame, region: pd.Series, statewide: bool) -> pd.DataFrame:
    d = (s1 - s0)
    if statewide:
        return pd.DataFrame(np.tile(d.mean().to_numpy(), (len(d), 1)), index=d.index, columns=FR5)
    return d.groupby(region).transform("mean")


def simulator_hindcast(feats, region: pd.Series, pairs: list[list[str]], edges: list[float]) -> dict:
    """Give the simulator the TRUE swing and see what it gets wrong. The gap between this and 'perfect' is the honest limit."""
    out = {"pairs": {}, "bands": {}}
    pooled = []
    for e0, e1 in pairs:
        s0, s1 = _shares5(feats, e0), _shares5(feats, e1)
        ok = s0.notna().all(axis=1) & s1.notna().all(axis=1)
        idx = s0.index[ok]
        actual = _winner5(feats, e1).loc[idx]
        prev = _winner5(feats, e0).loc[idx]
        res = {}
        for key, statewide in (("regional_swing", False), ("statewide_swing", True)):
            sw = _region_swings_true(s0.loc[idx], s1.loc[idx], region.loc[idx], statewide)
            shifted = np.clip(s0.loc[idx].to_numpy() + sw.to_numpy(), 0, None)
            order = np.argsort(-shifted, axis=1, kind="stable")
            lead = np.array(FR5)[order[:, 0]]
            right = (lead == actual.to_numpy())
            counts_pred = pd.Series(lead).value_counts().reindex(FR5).fillna(0).astype(int)
            counts_act = actual.value_counts().reindex(FR5).fillna(0).astype(int)
            res[key] = {"seats_called_right_pct": r(right.mean() * 100, 1), "predicted_counts": counts_pred.to_dict(), "actual_counts": counts_act.to_dict(),
                        "mean_count_miss_main_fronts": r(float(np.abs(counts_pred[["NDA", "SPF", "BSP"]] - counts_act[["NDA", "SPF", "BSP"]]).mean()), 1)}
            if key == "regional_swing":
                top2 = -np.sort(-shifted, axis=1)[:, :2]
                pooled.append(pd.DataFrame({"pair": f"{e0}->{e1}", "margin": top2[:, 0] - top2[:, 1], "right": right}))
        res["same_winner_as_before_pct"] = r((prev.to_numpy() == actual.to_numpy()).mean() * 100, 1)
        res["seats"] = int(len(idx))
        out["pairs"][f"{e0}->{e1}"] = res
    allp = pd.concat(pooled)
    bins = [0] + [e / 100 for e in edges] + [1.0]
    labels = [f"{bins[i] * 100:.0f} to {bins[i + 1] * 100:.0f} points" if i < len(bins) - 2 else f"{bins[i] * 100:.0f} points or more" for i in range(len(bins) - 1)]
    allp["band"] = pd.cut(allp["margin"], bins=bins, labels=labels, include_lowest=True, right=False)
    for pair, g in list(allp.groupby("pair")) + [("pooled", allp)]:
        out["bands"][pair] = [{"band": str(b), "seats": int((g["band"] == b).sum()), "leader_won_pct": r(g.loc[g["band"] == b, "right"].mean() * 100, 0) if (g["band"] == b).any() else None}
                              for b in labels]
    return out


def simulator_inputs(feats, ext: pd.DataFrame, cfg: dict, regions: dict, dist2reg: dict, alliance: dict) -> dict:
    sc = cfg["extra"]["simulator"]
    w, meta = feats.wide, feats.meta
    base = _shares5(feats, sc["base"])
    region = meta["district"].map(dist2reg).reindex(w.index)
    reg_names = list(regions)
    win = feats.winners.xs(sc["base"], level="election").reindex(w.index)
    seats = []
    for ac in w.index:
        seats.append({"ac": int(ac), "name": str(meta.loc[ac, "name"]), "district": str(meta.loc[ac, "district"]), "region": reg_names.index(region.loc[ac]),
                      "base": [r(v, 4) for v in base.loc[ac]], "winner": str(win.loc[ac, "camp"]), "margin_votes": int(win.loc[ac, "margin_votes"])})
    hind = simulator_hindcast(feats, region, sc["hindcast_pairs"], sc["margin_bands_pp"])
    # preset: the regional shift between assembly 2022 and Lok Sabha 2024, with SP and INC treated as one bloc
    s22 = base
    ls = pd.DataFrame({"NDA": w["NDA_LS2024"], "OPP": w["OPP_LS2024"], "BSP": w["BSP_LS2024"]})
    delta = pd.DataFrame({"NDA": ls["NDA"] - s22["NDA"], "SPF": ls["OPP"] - (s22["SPF"] + s22["INC"]), "BSP": ls["BSP"] - s22["BSP"]})
    ok = delta.notna().all(axis=1)
    by_region = delta[ok].groupby(region[ok]).mean()
    swings_ls = [[r(by_region.loc[rn, c], 4) for c in ("NDA", "SPF", "BSP")] for rn in reg_names]
    base_np = base.to_numpy()
    region_idx = np.array([reg_names.index(x) for x in region])
    sim = simulate_reference(base_np, region_idx, np.array(swings_ls, dtype=float), "SP+INC", 1.0)
    ls_lead = np.array(["NDA" if i == 0 else "SPF" if i == 1 else "BSP" if i == 3 else "OTH" for i in sim["lead"]])
    ls_actual = _winner5(feats, "LS2024").reindex(w.index).map({"INC": "SPF"}).fillna(_winner5(feats, "LS2024").reindex(w.index))
    agree = float((ls_lead[ok.to_numpy()] == ls_actual[ok].to_numpy()).mean() * 100)
    presets = [
        {"id": "repeat2022", "label": "Repeat 2022", "note": "No change from the 2022 result.", "swings": [[0.0, 0.0, 0.0] for _ in reg_names], "alliance": None, "rate": 0.0},
        {"id": "ls2024", "label": "2022 to Lok Sabha 2024 shift", "alliance": "SP+INC", "rate": 1.0, "swings": swings_ls,
         "note": "Each region moves by the average change between its 2022 assembly shares and its 2024 Lok Sabha shares (SP and INC counted as one bloc). An illustration of a past shift, not a forecast.",
         "reproduces_ls2024_segment_leader_pct": r(agree, 1)},
    ]
    defaults = {"SP+INC": alliance["defaults"].get("INC_to_SP", {}).get("rate", 0.8), "SP+BSP": alliance["defaults"].get("BSP_to_SP", {}).get("rate", 0.6)}
    return {
        "fronts": FR5, "front_names": FRONT_NAMES, "regions": [{"name": n, "districts": regions[n], "seats": int((region == n).sum())} for n in reg_names],
        "base_election": sc["base"], "seats": seats, "presets": presets, "alliance_defaults": defaults,
        "toss_up_pp": sc["toss_up_pp"], "margin_band_edges_pp": sc["margin_bands_pp"], "hindcast": hind,
        "region_status": "DRAFT region list: needs sign-off (configs/regions_up.json)",
    }


# ============================================================================== 5. booth segments
def booth_segments(cfg: dict, root: Path, feats_ls_cand: pd.DataFrame) -> dict:
    """Booth segments from the 2024 Form 20 workbooks whose candidate columns all equal the official totals. Read-only on the workbooks."""
    import openpyxl
    bc = cfg["extra"]["booths"]
    front_of = {code: f for f, codes in cfg["camps"]["elections"][bc["fronts_election"]].items() for code in codes}
    letters = {"NDA": "N", "SPF": "S", "BSP": "B", "OTH": "O"}
    cand = feats_ls_cand[feats_ls_cand["party"] != "NOTA"]
    acs, excluded, fingerprints = {}, [], {}
    src = root / bc["dir"]
    for path in sorted(src.glob("*.xlsx"), key=lambda p: int(p.stem) if p.stem.isdigit() else 10**6):
        if not path.stem.isdigit():
            continue
        ac = int(path.stem)
        try:
            wb = openpyxl.load_workbook(path, read_only=True)
            rows = [list(x) for x in wb["Form20"].iter_rows(values_only=True)]
            wb.close()
            hi = next(i for i, x in enumerate(rows) if x and x[0] == "Serial No." and x[1] == "Polling Station No")
            top = rows[hi - 1]
            iv = next(i for i, v in enumerate(top) if v and "Total of Valid" in str(v))
            cols = list(range(2, iv))
            booths = [x for x in rows[hi + 1:] if isinstance(x[0], (int, float))]
        except Exception as e:  # noqa: BLE001
            excluded.append({"ac": ac, "reason": f"could not read the workbook ({type(e).__name__})"})
            continue
        official = cand[cand["ac"] == ac][["candidate", "party", "votes"]].to_numpy().tolist()
        sums = [sum(x[c] for x in booths if isinstance(x[c], (int, float))) for c in cols]
        remaining, mapping = list(official), {}
        for c, s in zip(cols, sums):
            hit = [o for o in remaining if o[2] == s]
            fronts = {front_of.get(str(o[1]).upper(), "OTH") for o in hit}
            if hit and len(fronts) == 1:
                mapping[c] = front_of.get(str(hit[0][1]).upper(), "OTH")
                remaining.remove(hit[0])
            else:
                mapping[c] = None
        if len(cols) != len(official) or any(v is None for v in mapping.values()):
            excluded.append({"ac": ac, "reason": "candidate columns do not all equal the official totals"})
            continue
        fingerprints[str(ac)] = hashlib.sha256(path.read_bytes()).hexdigest()
        recs, dropped = [], 0
        for x in booths:
            fv = {"NDA": 0.0, "SPF": 0.0, "BSP": 0.0, "OTH": 0.0}
            for c in cols:
                fv[mapping[c]] += x[c] if isinstance(x[c], (int, float)) else 0
            valid = sum(fv.values())
            if valid < bc["min_votes"]:
                dropped += 1
                continue
            ordered = sorted(fv.items(), key=lambda kv: -kv[1])
            margin = (ordered[0][1] - ordered[1][1]) / valid * 100
            seg = "Stronghold" if margin >= bc["strong_pp"] else "Lean" if margin >= bc["lean_pp"] else "Competitive"
            recs.append((x[1], ordered[0][0], round(margin, 1), int(valid), seg))
        if not recs:
            excluded.append({"ac": ac, "reason": "no booth rows with enough votes"})
            continue
        tot = {f: sum(v for c, v in zip(cols, sums) if mapping[c] == f) for f in letters}
        seat_leader = max(tot, key=tot.get)
        counts: dict[str, dict[str, int]] = {}
        for _, lead, _, _, seg in recs:
            counts.setdefault(lead, {}).setdefault(seg, 0)
            counts[lead][seg] += 1
        comp = sorted([x for x in recs if x[4] == "Competitive"], key=lambda x: x[2])[:25]
        acs[ac] = {
            "booths": len(recs), "dropped_rows": dropped, "seat_leader": seat_leader,
            "segments": {f: counts.get(f, {}) for f in letters if f in counts},
            "against_seat_leader": sum(1 for x in recs if x[1] != seat_leader),
            "competitive": [{"ps": x[0], "leader": x[1], "margin_pts": x[2], "votes": x[3]} for x in comp],
            "rows": [[x[0], letters[x[1]], x[2], x[3]] for x in recs],
        }
    return {
        "meta": {"election": "LS2024", "seats_covered": len(acs), "booths": int(sum(v["booths"] for v in acs.values())),
                 "segment_rule": f"Stronghold: leading front ahead by {bc['strong_pp']:.0f} points or more; Lean: {bc['lean_pp']:.0f} to {bc['strong_pp']:.0f}; Competitive: under {bc['lean_pp']:.0f}. "
                                 "Margins are the leading front's share of valid votes minus the runner-up's.",
                 "fronts": {"N": "BJP-led (NDA)", "S": "SP/INC bloc (with allies)", "B": "BSP", "O": "Others"}, "excluded": excluded,
                 "source": "Form 20 workbooks in data/2024/converted whose candidate columns all equal the official 2024 totals (read-only)",
                 # SHA-256 of each verified workbook: the booth database build skips a workbook that no longer matches (see build_state_report)
                 "source_sha256": fingerprints},
        "acs": acs,
    }
