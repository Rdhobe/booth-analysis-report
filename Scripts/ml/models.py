"""Phase 1 models at constituency (AC) level.

  * typology      k-means groups of ACs with a similar vote history, plus nearest look-alikes
  * surprise      how much an AC's 2017->2022 change differs from ACs that looked like it BEFORE 2022
                  (robust z-score + Isolation Forest). Output wording is "statistical outlier" only.
  * baseline      "if nothing changes" expected share with an error band measured on past transitions
  * gate          a learned forecaster is only worth showing if it beats the baseline on a time split

All randomness is seeded; thresholds come from configs/ml_config.json.
"""
from __future__ import annotations

import logging
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest
from sklearn.linear_model import Ridge
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

try:
    from .features import Features
except ImportError:  # run as a script from Scripts/ml
    from features import Features

log = logging.getLogger(__name__)

SHORT = {"NDA": "BJP-led", "OPP": "SP/INC", "BSP": "BSP"}


# ----------------------------------------------------------------------------- typology
def typology_columns(f: Features) -> list[str]:
    return [f"{c}_{e}" for e in f.elections for c in f.model_camps]


def _group_label(m: pd.Series) -> str:
    """Plain-words label from a group's average vote shares. Auto-generated: a person should review it."""
    s22 = {c: float(m[f"{c}_VS2022"]) for c in ("NDA", "OPP", "BSP")}
    lead, second = sorted(s22, key=s22.get, reverse=True)[:2]
    gap = s22[lead] - s22[second]
    if s22[lead] >= 0.50:
        base = f"{SHORT[lead]} stronghold"
    elif gap < 0.08:
        base = f"{SHORT[lead]} vs {SHORT[second]}, close"
    else:
        base = f"{SHORT[lead]} ahead of {SHORT[second]}"
    extras = []
    if lead != "BSP" and s22["BSP"] >= 0.15:
        extras.append("BSP still strong")
    n24, s24 = float(m["NDA_LS2024"]), float(m["OPP_LS2024"])
    if lead == "NDA" and s24 > n24:
        extras.append("SP/INC ahead in 2024")
    elif lead == "OPP" and n24 > s24:
        extras.append("BJP-led ahead in 2024")
    return base + (", " + ", ".join(extras) if extras else "")


def fit_typology(f: Features, cfg: dict, seed: int) -> dict:
    """Standardise the vote history, keep its main directions (PCA), then k-means.

    k is chosen by silhouette + bootstrap stability. ACs form a continuum, so groups are slices of it.
    """
    tc = cfg["typology"]
    X = f.wide[typology_columns(f)]
    fit_mask = f.clean.to_numpy()
    scaler = StandardScaler().fit(X[fit_mask])
    Z_all = scaler.transform(X)
    pca = PCA(n_components=tc["pca_components"], random_state=seed).fit(Z_all[fit_mask])
    P_all = pca.transform(Z_all)
    Z = P_all[fit_mask]                       # clustering happens in the PCA space
    rng = np.random.default_rng(seed)

    table = []
    for k in range(tc["k_range"][0], tc["k_range"][1] + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(Z)
        sil = float(silhouette_score(Z, km.labels_))
        aris = []
        for _ in range(tc["bootstrap_resamples"]):
            idx = rng.choice(len(Z), len(Z), replace=True)
            kb = KMeans(n_clusters=k, n_init=3, random_state=int(rng.integers(0, 2**31 - 1))).fit(Z[idx])
            aris.append(adjusted_rand_score(km.labels_, kb.predict(Z)))
        table.append({
            "k": k, "silhouette": round(sil, 3),
            "stability_ari_mean": round(float(np.mean(aris)), 3), "stability_ari_min": round(float(np.min(aris)), 3),
            "smallest_group": int(np.bincount(km.labels_, minlength=k).min()),
        })
    for row in table:
        row["score"] = round(row["silhouette"] + row["stability_ari_mean"], 3)
    eligible = [r for r in table if r["smallest_group"] >= tc["min_group_size"]] or table
    best = max(eligible, key=lambda r: (r["score"], -r["k"]))

    km = KMeans(n_clusters=best["k"], n_init=10, random_state=seed).fit(Z)
    raw = km.predict(P_all)
    # stable ids: order groups by their mean BJP-led share in 2022 (highest first), 1-based
    order = X.assign(g=raw).groupby("g")["NDA_VS2022"].mean().sort_values(ascending=False).index.tolist()
    remap = {old: new + 1 for new, old in enumerate(order)}
    labels = pd.Series([remap[g] for g in raw], index=X.index, name="type_id")
    means = X.groupby(labels).mean()
    base = {int(g): _group_label(means.loc[g]) for g in means.index}
    count, seen, names = Counter(base.values()), {}, {}
    for g in sorted(base):                                    # keep labels unique if two groups read the same
        if count[base[g]] > 1:
            seen[base[g]] = seen.get(base[g], 0) + 1
            names[g] = f"{base[g]} ({'I' * seen[base[g]]})"
        else:
            names[g] = base[g]

    # distance of every AC to every other, for look-alikes
    D = np.sqrt(((Z_all[:, None, :] - Z_all[None, :, :]) ** 2).sum(axis=2))
    return {"scaler": scaler, "pca": pca, "kmeans": km, "columns": typology_columns(f), "labels": labels, "names": names,
            "pca_variance_explained": round(float(pca.explained_variance_ratio_.sum()), 3), "P_all": P_all,
            "means": means, "distance": pd.DataFrame(D, index=X.index, columns=X.index),
            "selection": table, "chosen_k": best["k"], "chosen": best, "remap": remap}


def look_alikes(distance: pd.DataFrame, ac: int, n: int) -> list[tuple[int, float]]:
    d = distance.loc[ac].drop(ac).sort_values(kind="stable")
    return [(int(a), round(float(v), 2)) for a, v in d.head(n).items()]


# ----------------------------------------------------------------------------- surprise
def compute_surprise(wide: pd.DataFrame, clean: pd.Series, all_camps: list[str], cfg: dict, seed: int) -> pd.DataFrame:
    """Compare each AC's change over the latest assembly pair with ACs that looked like it before that pair."""
    sc = cfg["surprise"]
    camps, (t0, t1) = sc["camps"], sc["pair"]
    past = wide[[f"{c}_{e}" for e in sc["peer_features"] for c in all_camps]]
    clean_np = clean.to_numpy()
    Zp = StandardScaler().fit(past[clean_np]).transform(past)
    clean_pos = np.flatnonzero(clean_np)
    change = pd.DataFrame({c: wide[f"{c}_{t1}"] - wide[f"{c}_{t0}"] for c in camps}, index=wide.index)
    ch = change.to_numpy()

    D = np.sqrt(((Zp[:, None, :] - Zp[clean_pos][None, :, :]) ** 2).sum(axis=2))
    peer = np.full(ch.shape, np.nan)
    for i in range(len(wide)):
        d = D[i].copy()
        if clean_np[i]:
            d[np.searchsorted(clean_pos, i)] = np.inf          # never compare an AC with itself
        nn = np.argsort(d, kind="stable")[: sc["peers"]]
        peer[i] = np.median(ch[clean_pos[nn]], axis=0)
    resid = ch - peer

    r = resid[clean_np]
    med = np.median(r, axis=0)
    mad = np.maximum(np.median(np.abs(r - med), axis=0), 1e-9)
    z = 0.6745 * (resid - med) / mad                           # modified z-score (Iglewicz-Hoaglin)
    maxz = np.abs(z).max(axis=1)

    iso = IsolationForest(n_estimators=sc["isolation_forest_trees"], contamination="auto", random_state=seed).fit(r)
    score = iso.score_samples(resid)
    thr = np.percentile(score[clean_np], sc["isolation_forest_bottom_pct"])
    agree = score <= thr
    flag = ((maxz >= sc["z_flag"]) & agree) | (maxz >= sc["z_extreme"])

    out = pd.DataFrame(index=wide.index)
    for j, c in enumerate(camps):
        out[f"change_{c}"], out[f"peer_{c}"], out[f"z_{c}"] = ch[:, j], peer[:, j], z[:, j]
    out["maxz"], out["if_score"], out["if_agrees"] = maxz, score, agree
    out["flag"] = flag & clean_np
    out["strength"] = np.where(~clean_np, "n/a", np.where(maxz >= sc["z_extreme"], "strong", np.where(out["flag"], "moderate", "none")))
    return out


def injected_anomaly_test(wide: pd.DataFrame, clean: pd.Series, all_camps: list[str], cfg: dict, seed: int) -> list[dict]:
    """Shift the BJP-led share of random ACs by a known amount and see how many get flagged (TASKS T4.5)."""
    sc = cfg["surprise"]
    t1 = sc["pair"][1]
    rng = np.random.default_rng(seed)
    clean_ids = wide.index[clean.to_numpy()]
    out = []
    for shift in sc["injected_shifts_pts"]:
        rec, fa = [], []
        for _ in range(sc["injected_trials"]):
            picked = rng.choice(clean_ids, sc["injected_acs_per_trial"], replace=False)
            signs = rng.choice([-1.0, 1.0], size=len(picked))
            w = wide.copy()
            for ac, sg in zip(picked, signs):
                old = float(w.loc[ac, f"NDA_{t1}"])
                new = float(np.clip(old + sg * shift / 100, 0.0, 1.0))
                scale = (1 - new) / (1 - old) if old < 1 else 1.0
                for c in all_camps:                        # all_camps = the model camps (NDA, OPP, BSP, OTH)
                    col = f"{c}_{t1}"
                    w.loc[ac, col] = new if c == "NDA" else w.loc[ac, col] * scale
            res = compute_surprise(w, clean, all_camps, cfg, seed)
            others = clean & ~wide.index.isin(picked)
            rec.append(float(res.loc[picked, "flag"].mean()))
            fa.append(float(res.loc[others.to_numpy(), "flag"].mean()))
        out.append({"shift_pts": shift, "recall": round(float(np.mean(rec)), 3), "false_flag_rate": round(float(np.mean(fa)), 3)})
    return out


# ----------------------------------------------------------------------------- baseline and gate
def baseline_bands(wide: pd.DataFrame, clean: pd.Series, cfg: dict) -> dict:
    """Error of 'same as last election' per camp on past transitions; the band is the 80% quantile."""
    q = cfg["baseline"]["band_quantile"]
    camps = cfg["surprise"]["camps"]
    out = {}
    for c in camps:
        errs = [(wide[f"{c}_{t1}"] - wide[f"{c}_{t0}"]).abs()[clean].to_numpy() for t0, t1 in cfg["baseline"]["transitions"]]
        pooled, last = np.concatenate(errs), errs[-1]
        out[c] = {"band_pooled": round(float(np.quantile(pooled, q)), 4), "mae_pooled": round(float(pooled.mean()), 4),
                  "band_last": round(float(np.quantile(last, q)), 4), "mae_last": round(float(last.mean()), 4)}
    return out


def compare_learned_forecasters(wide: pd.DataFrame, clean: pd.Series, all_camps: list[str], cfg: dict, seed: int) -> dict:
    """Learn on the first transition, test on the last. A learned model must beat persistence by a margin."""
    (a0, a1), (b0, b1) = cfg["baseline"]["transitions"][0], cfg["baseline"]["transitions"][-1]
    margin = cfg["baseline"]["promotion_margin_pts"] / 100
    def feats(e: str) -> pd.DataFrame:
        x = wide[[f"{c}_{e}" for c in all_camps]][clean]
        return x.rename(columns=lambda col: col.rsplit("_", 1)[0])           # same names at fit and predict
    Xtr, Xte = feats(a0), feats(b0)
    rows, verdicts = [], {}
    for camp in cfg["surprise"]["camps"]:
        ytr, yte = wide[f"{camp}_{a1}"][clean], wide[f"{camp}_{b1}"][clean]
        persist = Xte[camp]
        preds = {
            "Same as last election": persist,
            "Last election plus true state swing (ceiling, only known afterwards)": persist + (yte.mean() - persist.mean()),
            "Ridge on previous shares": pd.Series(Ridge(alpha=1.0).fit(Xtr, ytr).predict(Xte), index=Xte.index),
            "Gradient boosting on previous shares": pd.Series(
                HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, random_state=seed).fit(Xtr, ytr).predict(Xte),
                index=Xte.index),
        }
        base_mae = float((yte - preds["Same as last election"]).abs().mean())
        for name, p in preds.items():
            e = (yte - p).abs()
            rows.append({"camp": camp, "method": name, "mae_pts": round(float(e.mean()) * 100, 2),
                         "within_80pct_pts": round(float(np.quantile(e, 0.8)) * 100, 2)})
        learned = [r for r in rows if r["camp"] == camp and r["method"].startswith(("Ridge", "Gradient"))]
        verdicts[camp] = any(r["mae_pts"] / 100 <= base_mae - margin for r in learned)   # best learned model must win
    return {"train_transition": [a0, a1], "test_transition": [b0, b1], "rows": rows,
            "promoted_by_camp": verdicts, "decision": "A learned forecaster replaces the baseline" if all(verdicts.values())
            else "Baseline stays: no learned forecaster beat 'same as last election' on every camp"}
