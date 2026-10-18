"""Extra constituency features for the prediction work: turnout, electors, Lok Sabha 2019 fronts, candidate history.

Built from files that already exist in the repo (nothing is fetched, nothing is invented):
  data/processed/ac_booth_*.csv     booth sheets summed to AC level (Scripts/ml/ac_booth_totals.py)
  data/Uttar_Pradesh.csv            official assembly results (candidates, parties, votes)
  data/parliament.csv               official Lok Sabha results per parliamentary seat (used to check 2019)
  data/uprolls2017.csv              2017 roll counts per booth (electors for every AC)
  ECI 2024 segment file             electors and 2024 votes per AC, and the AC -> parliamentary seat map

Every value passes a gate; a value that fails becomes missing (NaN) and is counted in the report.
Run:  python Scripts/ml/features_ext.py        (writes data/processed/ac_features_ext.csv, output/ml/features_ext_report.json)
"""
from __future__ import annotations

import difflib
import io
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from . import features as F
except ImportError:  # run as a script from Scripts/ml
    import features as F

log = logging.getLogger("ml.features_ext")
ROOT = F.ROOT
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output" / "ml"
PARLIAMENT = ROOT / "data" / "parliament.csv"
UPROLLS = ROOT / "data" / "uprolls2017.csv"


# ----------------------------------------------------------------------------- party names on booth sheets
_LEGACY = {  # Kruti Dev spellings seen on the 2019 sheets (Hindi text typed in a legacy font)
    "HKKJRHTURKIKVHZ": "BJP",
    "JKVHYKSDNY": "RLD",
}
_RULES = [  # (regex on the letters-only upper-case name, canonical code)
    (r"^BJP$|^BHARATIYAJANATA|^BHARTIYAJANATA|^BHARATIYAJANTA|^BHARTIYAJANTA", "BJP"),
    (r"^BSP$|^BAHUJANSAMAJ|^BHUJANSAMAJ", "BSP"),
    (r"^SP$|^SAMAJWADIPARTY|^SAMAJWADI$", "SP"),
    (r"^INC$|^INDIANNATIONALCONGRESS|^CONGRESS", "INC"),
    (r"^RLD$|^RASHTRIYALOKDAL", "RLD"),
    (r"^SBSP$|^SUHELDEV", "SBSP"),
    (r"^ADS$|^AD$|APNADAL\(?SONE|APNADALS$|^APNADAL\(S\)", "ADS"),
    (r"^IND$|^INDEPENDENT$|^INDP", "IND"),
    (r"^NOTA$|NONEOFTHEABOVE", "NOTA"),
]


def canon_party(raw: str) -> str:
    """Canonical code for a party string from a booth sheet; "" when the string is unreadable junk."""
    t = re.sub(r"[^A-Z0-9()]", "", str(raw).upper())
    if t in _LEGACY:
        return _LEGACY[t]
    for pat, code in _RULES:
        if re.search(pat, t):
            return code
    return t if len(t) >= 3 else ""          # keep other readable names as they are; drop ",,", "B", "S", '"'


# ----------------------------------------------------------------------------- loading
def load_sums() -> tuple[pd.DataFrame, pd.DataFrame]:
    sums = pd.read_csv(PROC / "ac_booth_sums.csv")
    party = pd.read_csv(PROC / "ac_booth_party_votes.csv")
    return sums, party


def ac_to_pc() -> pd.Series:
    """AC number -> parliamentary seat number, from the ECI 2024 segment file (delimitation is unchanged since 2008)."""
    lines = F.SEG_CSV.read_text(encoding="utf-8-sig").splitlines()
    start = next(i for i, ln in enumerate(lines) if "AC NO" in ln.upper() and "PARTY" in ln.upper())
    s = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    s.columns = [c.strip() for c in s.columns]
    s = s[s["State/UT Name"].astype(str).str.strip().str.lower() == "uttar pradesh"]
    return s.drop_duplicates("AC NO").set_index("AC NO")["PC NO"].astype(int).sort_index().rename("pc")


# ----------------------------------------------------------------------------- turnout and electors
def turnout_features(sums: pd.DataFrame, official: pd.DataFrame, party: pd.DataFrame, cfg: dict, wide24: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Electors, turnout and female share of voters per election, with gates. Returns (frame, report)."""
    g = cfg["features_ext"]
    lo, hi = g["reconcile_ratio_range"]
    t_lo, t_hi = g["turnout_range"]
    out = pd.DataFrame(index=pd.RangeIndex(1, 404, name="ac"))
    rep: dict = {}

    pv_tot = party.groupby(["election", "ac"])["votes"].sum()
    off_tot = official.groupby(["YEAR", "AC_NO"])["VOTES"].sum()
    for eid, year in (("VS2017", 2017), ("LS2019", 2019), ("VS2022", 2022)):
        s = sums[sums["election"] == eid].set_index("ac").copy()
        pre = s["booths"] == 0                                 # Form 20 sheets: electors from the preamble, no booth rows
        if eid in ("VS2017", "VS2022") and pre.any():
            off_polled = official[official["YEAR"] == year].groupby("AC_NO")["polled_votes"].first()
            s.loc[pre, "polled"] = off_polled.reindex(s.index[pre]).to_numpy()
        ok = pd.Series(True, index=s.index)
        why = pd.Series("", index=s.index)
        t = s["polled"] / s["electors"].replace(0, np.nan)
        bad_t = ~t.between(t_lo, t_hi)
        ok &= ~bad_t
        why[bad_t] += "turnout outside range; "
        bad_e = s["booths_no_electors"] > 0.1 * s["booths"]
        ok &= ~bad_e
        why[bad_e] += "electors missing on >10% of booths; "
        if eid in ("VS2017", "VS2022"):                        # official AC totals exist: booth votes must reconcile
            ratio = (pv_tot.xs(eid, level="election") / off_tot.xs(year, level="YEAR")).reindex(s.index)
            bad_r = ~ratio.between(lo, hi) & ~pre             # preamble rows have no booth votes to reconcile
            ok &= ~bad_r
            why[bad_r] += "booth votes differ from official total; "
            rep[f"{eid}_reconcile"] = {"compared": int(ratio.notna().sum()), "within_range": int(ratio.between(lo, hi).sum()),
                                      "median_ratio": round(float(ratio.median()), 4)}
        tag = {"VS2017": "17", "LS2019": "19", "VS2022": "22"}[eid]
        out[f"electors_{tag}"] = s["electors"].where(ok).reindex(out.index)
        out[f"turnout_{tag}"] = t.where(ok).reindex(out.index)
        out[f"female_share_voters_{tag}"] = (s["female"] / (s["male"] + s["female"] + s["other"]).replace(0, np.nan)).where(ok).reindex(out.index)
        rep[f"{eid}_turnout"] = {"acs_read": int(len(s)), "trusted": int(ok.sum()), "of_which_electors_from_form20_preamble": int((ok & pre).sum()),
                                 "dropped": {k: int(v) for k, v in why[~ok].value_counts().items()}}

    # electors 2017 for every AC from the 2017 roll file; scaled to the sheet level (the roll file runs about 2% low)
    u = pd.read_csv(UPROLLS, usecols=["ac_id_09", "electors_17"], low_memory=False)
    roll = u.groupby("ac_id_09")["electors_17"].sum().reindex(out.index)
    out["electors_17_roll"] = roll / g["electors17_source_scale"]
    out["electors_17_best"] = out["electors_17"].fillna(out["electors_17_roll"])
    out["electors_24"] = wide24["electors_LS2024"].reindex(out.index)
    out["turnout_24"] = wide24["turnout_LS2024"].reindex(out.index)
    out["elector_growth_17_24"] = out["electors_24"] / out["electors_17_best"] - 1
    # 2017 turnout for every AC: sheet-based where trusted, else official polled votes over the roll electors
    polled17 = official[official["YEAR"] == 2017].groupby("AC_NO")["polled_votes"].first().reindex(out.index)
    out["turnout_17_best"] = out["turnout_17"].fillna(polled17 / out["electors_17_best"])
    rep["electors_17_roll_vs_sheet_median_ratio"] = round(float((out["electors_17_roll"] / out["electors_17"]).median()), 3)
    return out, rep


# ----------------------------------------------------------------------------- Lok Sabha 2019 fronts
_OFFICIAL_CODE = {"AD(S)": "ADS", "AD": "ADS"}


def _official_ls2019_candidates() -> dict[int, list[tuple[str, str]]]:
    off = pd.read_csv(PARLIAMENT, low_memory=False)
    off = off[(off["YEAR"] == 2019) & off["STATE"].astype(str).str.contains("Uttar Pradesh")]
    out: dict[int, list[tuple[str, str]]] = {}
    for r in off.itertuples():
        code = str(r.PARTY_CODE).upper().strip()
        out.setdefault(int(r.PC_NO), []).append((str(r.CANDIDATE), _OFFICIAL_CODE.get(code, code)))
    return out


def resolve_ls2019_codes(party: pd.DataFrame, pc_map: pd.Series, nm: dict) -> pd.DataFrame:
    """Party code for every LS2019 candidate column: the official party of the matching candidate in that parliamentary seat first,
    then the party text on the sheet. This recovers columns whose party cell is junk (",,", a single letter, legacy-font text)."""
    p = party[party["election"] == "LS2019"].copy()
    p["pc"] = p["ac"].map(pc_map)
    cands = _official_ls2019_candidates()
    cache: dict = {}

    def official(pc, name):
        key = (pc, name)
        if key not in cache:
            cache[key] = next((code for oname, code in cands.get(int(pc), []) if same_person(name, oname, nm["ratio"], nm["min_tokens_for_subset"])), None)
        return cache[key]

    p["official"] = [official(pc, n) if pd.notna(pc) and str(n) not in ("", "nan") else None for pc, n in zip(p["pc"], p["candidate"])]
    p["sheet"] = p["party"].map(canon_party)
    p["code"] = p["official"].fillna(p["sheet"])
    return p


def ls2019_fronts(p: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    """Front shares per AC from resolved candidate columns, kept only where the three main fronts carry enough of the vote."""
    g = cfg["features_ext"]
    fronts = g["ls2019_fronts"]
    p = p.copy()
    rev = {c: f for f, codes in fronts.items() for c in codes}
    p["front"] = p["code"].map(rev).fillna("OTH")
    tot = p.groupby("ac")["votes"].sum()
    sh = p.pivot_table(index="ac", columns="front", values="votes", aggfunc="sum").reindex(columns=list(fronts) + ["OTH"]).fillna(0.0)
    sh = sh.div(tot, axis=0)
    mapped = sh[list(fronts)].sum(axis=1)                       # share carried by the three main fronts
    ok = mapped >= g["ls2019_mapped_min"]
    out = sh.add_suffix("_19").where(ok, np.nan).rename(columns=lambda c: c.lower())
    out.index.name = "ac"
    both = p[p["official"].notna() & (p["sheet"] != "")]
    rep = {"acs_read": int(len(sh)), "trusted": int(ok.sum()), "dropped_party_names_unreadable": int((~ok).sum()),
           "party_from_official_candidate_list_vote_share": round(float(p.loc[p["official"].notna(), "votes"].sum() / p["votes"].sum()), 4),
           "sheet_and_official_party_disagree_vote_share": round(float(both.loc[both["official"] != both["sheet"], "votes"].sum() / max(both["votes"].sum(), 1)), 4),
           "still_unreadable_vote_share": round(float(p.loc[p["code"] == "", "votes"].sum() / p["votes"].sum()), 4)}
    return out, rep


def pc_level_ls(years: tuple[int, ...] = (2009, 2014, 2019, 2024)) -> pd.DataFrame:
    """Official Lok Sabha vote shares per parliamentary seat (from data/parliament.csv), one column set per year.

    Raw party shares plus ``nda`` (BJP and its Apna Dal ally; BJP alone in 2009; RLD joined in 2024) and ``oth`` (the rest,
    NOTA included). These are official results, so they cover all 80 seats; they are per seat, not per assembly segment.
    """
    off = pd.read_csv(PARLIAMENT, low_memory=False)
    off = off[off["STATE"].astype(str).str.contains("Uttar Pradesh")].copy()
    off["code"] = off["PARTY_CODE"].astype(str).str.upper().str.strip()
    out = []
    for y in years:
        d = off[off["YEAR"] == y]
        tot = d.groupby("PC_NO")["VOTES"].sum()
        by = d.pivot_table(index="PC_NO", columns="code", values="VOTES", aggfunc="sum").fillna(0.0)
        sh = pd.DataFrame(index=by.index)
        get = lambda c: by[c] if c in by.columns else pd.Series(0.0, index=by.index)  # noqa: E731
        sh["bjp"] = get("BJP")
        sh["ads"] = get("AD") + get("AD(S)")
        sh["sp"], sh["bsp"], sh["inc"], sh["rld"] = get("SP"), get("BSP"), get("INC"), get("RLD")
        sh["nda"] = sh["bjp"] + (sh["ads"] if y >= 2014 else 0) + (sh["rld"] if y >= 2024 else 0)
        sh["oth"] = tot - sh[["bjp", "ads", "sp", "bsp", "inc", "rld"]].sum(axis=1)
        sh = sh.div(tot, axis=0)
        out.append(sh.add_prefix(f"ls{str(y)[2:]}_"))
    res = pd.concat(out, axis=1)
    res.index.name = "pc"
    return res


def check_ls2019_against_official(sums: pd.DataFrame, p: pd.DataFrame, pc_map: pd.Series, cfg: dict) -> tuple[dict, set, set]:
    """For parliamentary seats whose ACs were all read, booth totals must match the official EVM votes.

    Returns (summary, seats that failed, seats that passed). Seats with missing ACs cannot be checked and are in neither set.
    """
    tol = cfg["features_ext"]["pc_check_tolerance"]
    off = pd.read_csv(PARLIAMENT, low_memory=False)
    off = off[(off["YEAR"] == 2019) & off["STATE"].astype(str).str.contains("Uttar Pradesh")]
    off_tot = off.groupby("PC_NO")["EVM Votes"].sum()
    off_bjp = off[off["PARTY_CODE"] == "BJP"].groupby("PC_NO")["EVM Votes"].sum()
    s = sums[sums["election"] == "LS2019"].set_index("ac")
    booth_tot = p.groupby("ac")["votes"].sum()
    booth_bjp = p[p["code"] == "BJP"].groupby("ac")["votes"].sum()
    rows = []
    for pc, acs in pc_map.groupby(pc_map).groups.items():
        acs = list(acs)
        if not all(a in s.index for a in acs) or pc not in off_tot.index:
            continue
        rows.append({"pc": int(pc), "acs": len(acs), "total_ratio": booth_tot.reindex(acs).sum() / off_tot[pc],
                     "bjp_ratio": booth_bjp.reindex(acs).sum() / off_bjp.get(pc, np.nan)})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"complete_pcs": 0}, set(), set()
    ok = ((df["total_ratio"] - 1).abs() <= tol) & ((df["bjp_ratio"] - 1).abs() <= tol)
    summary = {"complete_pcs": int(len(df)),
               "total_votes_within_tol": int(((df["total_ratio"] - 1).abs() <= tol).sum()),
               "bjp_votes_within_tol": int(((df["bjp_ratio"] - 1).abs() <= tol).sum()),
               "both_within_tol": int(ok.sum()),
               "median_total_ratio": round(float(df["total_ratio"].median()), 4),
               "median_bjp_ratio": round(float(df["bjp_ratio"].median()), 4),
               "failed_pcs": [int(x) for x in df.loc[~ok, "pc"]]}
    return summary, set(df.loc[~ok, "pc"].astype(int)), set(df.loc[ok, "pc"].astype(int))


# ----------------------------------------------------------------------------- candidates and incumbency
_HONORIFICS = {"DR", "SHRI", "SMT", "SMT.", "SRI", "ADV", "MR", "MRS", "MD", "MOHD", "MOHAMMAD", "MOHAMMED", "MOHAMAD", "MO", "KUMARI", "KU", "PROF", "ER"}


def _tokens(name: str) -> frozenset:
    t = re.sub(r"[^A-Za-z ]", " ", str(name)).upper().split()
    return frozenset(w for w in t if w not in _HONORIFICS and len(w) > 1)


def same_person(a: str, b: str, ratio: float = 0.85, min_subset: int = 2) -> bool:
    """Same candidate name written two ways, compared inside one constituency (so a loose rule is safe)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if (ta <= tb or tb <= ta) and min(len(ta), len(tb)) >= min_subset:
        return True
    return difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() >= ratio


def candidate_features(cfg: dict, feats: F.Features) -> tuple[pd.DataFrame, dict]:
    """Per AC and assembly election after 2012: did the sitting MLA stand again, and under which party."""
    cand = F.load_vs_candidates()
    nm = cfg["features_ext"]["name_match"]
    rev_by_e = {e: {c: camp for camp, codes in cfg["camps"]["elections"][e].items() for c in codes} for e in feats.elections}
    rows = []
    for ac, g in cand[cand["party"] != "NOTA"].groupby("ac"):
        by_e = {e: d.sort_values("votes", ascending=False) for e, d in g.groupby("election")}
        rec = {"ac": ac}
        for prev, cur, tag in (("VS2012", "VS2017", "17"), ("VS2017", "VS2022", "22")):
            if prev not in by_e or cur not in by_e:
                continue
            w = by_e[prev].iloc[0]
            cur_df = by_e[cur]
            hit = next((r for r in cur_df.itertuples() if same_person(w["candidate"], r.candidate, nm["ratio"], nm["min_tokens_for_subset"])), None)
            rec[f"inc_recontests_{tag}"] = int(hit is not None)
            rec[f"inc_same_party_{tag}"] = (int(hit.party == w["party"]) if hit is not None else np.nan)
            rec[f"inc_front_{tag}"] = rev_by_e[cur].get(hit.party, "OTH") if hit is not None else ""
            rec[f"prev_winner_front_{tag}"] = rev_by_e[prev].get(w["party"], "OTH")
            rec[f"n_candidates_{tag}"] = int(len(cur_df))
            rec[f"inc_won_{tag}"] = (int(cur_df.iloc[0]["candidate"] == hit.candidate) if hit is not None else np.nan)
        rows.append(rec)
    df = pd.DataFrame(rows).set_index("ac")
    rep = {}
    for tag, label in (("17", "VS2017"), ("22", "VS2022")):
        r = df[f"inc_recontests_{tag}"]
        sw = df[f"inc_same_party_{tag}"]
        rep[label] = {"incumbent_recontests": int(r.sum()), "of": int(r.notna().sum()),
                      "recontest_under_new_party": int(((r == 1) & (sw == 0)).sum()),
                      "recontesting_incumbents_who_won": int(df[f"inc_won_{tag}"].sum())}
    return df, rep


# ----------------------------------------------------------------------------- driver
def build(cfg: dict | None = None) -> tuple[pd.DataFrame, dict]:
    cfg = cfg or F.load_config()
    feats = F.build_features(cfg)
    sums, party = load_sums()
    official = pd.read_csv(F.VS_CSV)
    official["PARTY"] = official["PARTY"].astype(str).str.strip().str.upper()
    pc_map = ac_to_pc()

    turn, rep_turn = turnout_features(sums, official, party, cfg, feats.wide)
    ls19_resolved = resolve_ls2019_codes(party, pc_map, cfg["features_ext"]["name_match"])
    ls19, rep_ls = ls2019_fronts(ls19_resolved, cfg)
    pc_check, bad_pcs, good_pcs = check_ls2019_against_official(sums, ls19_resolved, pc_map, cfg)
    cand, rep_cand = candidate_features(cfg, feats)

    ext = turn.join(ls19, how="left").join(cand, how="left")
    ext["pc"] = pc_map.reindex(ext.index)
    in_bad = ext["pc"].isin(bad_pcs)                           # a seat that fails its official check cannot be trusted
    for col in ls19.columns:
        ext.loc[in_bad, col] = np.nan
    ext["ls19_checked_ok"] = ext["pc"].isin(good_pcs).astype(int)
    rep_ls["set_to_missing_because_seat_failed_official_check"] = int(in_bad.sum())
    rep_ls["acs_in_seats_that_passed_official_check"] = int(ext["ls19_checked_ok"].sum())
    pcls = pc_level_ls()
    ext = ext.join(pcls, on="pc")
    ext = ext.join(feats.meta[["name", "district"]], how="left")
    report = {"turnout_and_electors": rep_turn, "ls2019_fronts": rep_ls, "ls2019_vs_official_by_parliamentary_seat": pc_check,
              "official_lok_sabha_by_seat": {"seats": int(len(pcls)), "years": [2009, 2014, 2019, 2024]},
              "candidates": rep_cand,
              "coverage_non_missing": {c: int(ext[c].notna().sum()) for c in
                                       ("turnout_17_best", "turnout_19", "turnout_22", "turnout_24", "nda_19", "ls14_nda", "ls19_nda",
                                        "elector_growth_17_24", "inc_recontests_22")}}
    return ext, report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ext, report = build()
    PROC.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    ext.to_csv(PROC / "ac_features_ext.csv", encoding="utf-8")
    (OUT / "features_ext_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    log.info("wrote %s (%d ACs, %d columns)", PROC / "ac_features_ext.csv", len(ext), ext.shape[1])
    log.info("%s", json.dumps(report, indent=1, default=float)[:3000])


if __name__ == "__main__":
    main()
