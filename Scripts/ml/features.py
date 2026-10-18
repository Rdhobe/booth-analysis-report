"""Build the constituency-level feature table for the Phase 1 models.

Inputs (read-only, never modified):
  data/Uttar_Pradesh.csv   assembly results 2012 / 2017 / 2022, one row per candidate
  data/assembly-segment-level-voting-data-for-all-constituencies-2024.csv   LS 2024 by assembly segment
  configs/ac_format.json   AC names, districts
  configs/ml_config.json   camps (party fronts), thresholds, seed

Output: a ``Features`` object with one row per AC.  Shares are the share of all counted
votes (candidates plus NOTA) won by each camp.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "ml_config.json"
VS_CSV = ROOT / "data" / "Uttar_Pradesh.csv"
SEG_CSV = ROOT / "data" / "assembly-segment-level-voting-data-for-all-constituencies-2024.csv"
AC_JSON = ROOT / "configs" / "ac_format.json"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Read the ML config (thresholds, seed, party fronts)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    """SHA-256 of a file, used to stamp the model card with the exact inputs."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Features:
    """Everything the models and the demo page need, one row per AC."""

    wide: pd.DataFrame                      # index ac; share columns "<CAMP>_<ELECTION>" plus counts
    winners: pd.DataFrame                   # index (ac, election): winner, party, camp, votes, margin
    meta: pd.DataFrame                      # index ac: name, district, reserved_for
    clean: pd.Series                        # bool per ac: usable for model fitting
    camps: list[str]                        # base camps (NDA, SPF, BSP, INC, OTH)
    model_camps: list[str]                  # camps the models use (NDA, OPP, BSP, OTH)
    elections: list[str]
    checks: dict = field(default_factory=dict)

    def share_cols(self, election: str, camps: list[str] | None = None) -> list[str]:
        return [f"{c}_{election}" for c in (camps or self.camps)]


# ----------------------------------------------------------------------------- loading
def load_vs_candidates(path: Path = VS_CSV) -> pd.DataFrame:
    """Assembly results: one row per candidate (NOTA included as party NOTA)."""
    d = pd.read_csv(path)
    return pd.DataFrame({
        "ac": d["AC_NO"].astype(int),
        "election": "VS" + d["YEAR"].astype(int).astype(str),
        "candidate": d["NAME"].astype(str).str.strip(),
        "party": d["PARTY"].astype(str).str.strip().str.upper(),
        "votes": d["VOTES"].astype(float),
        "polled": d["polled_votes"].astype(float),
    })


def load_ls2024_candidates(path: Path = SEG_CSV) -> tuple[pd.DataFrame, pd.DataFrame]:
    """LS 2024 by assembly segment (UP only). Returns (candidate rows incl. NOTA, per-AC info)."""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    start = next(i for i, ln in enumerate(lines) if "AC NO" in ln.upper() and "PARTY" in ln.upper())
    s = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    s.columns = [c.strip() for c in s.columns]
    # exact match: "Uttar" would also pull in Uttarakhand, whose AC numbers 1-70 collide with UP's
    s = s[s["State/UT Name"].astype(str).str.strip().str.lower() == "uttar pradesh"].copy()
    info = (s.drop_duplicates("AC NO")
              .set_index("AC NO")[["AC NAME", "PC NAME", "TOTAL ELECTORS IN AC", "NOTA VOTES EVM IN AC"]])
    info.index = info.index.astype(int)
    cand = pd.DataFrame({
        "ac": s["AC NO"].astype(int),
        "election": "LS2024",
        "candidate": s["CANDIDATE NAME"].astype(str).str.strip(),
        "party": s["PARTY"].astype(str).str.strip().str.upper(),
        "votes": s["VOTES SECURED EVM"].astype(float),
        "polled": np.nan,
    })
    nota = pd.DataFrame({
        "ac": info.index, "election": "LS2024", "candidate": "NOTA", "party": "NOTA",
        "votes": info["NOTA VOTES EVM IN AC"].astype(float).to_numpy(), "polled": np.nan,
    })
    cand = pd.concat([cand, nota], ignore_index=True)
    cand["polled"] = cand.groupby("ac")["votes"].transform("sum")   # EVM votes counted incl. NOTA
    return cand, info


def load_ac_meta(path: Path = AC_JSON) -> pd.DataFrame:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["assembly_constituencies"]
    m = pd.DataFrame(rows).rename(columns={"ac_no": "ac", "ac_name": "name"}).set_index("ac")
    return m[["name", "district", "reserved_for"]]


# ----------------------------------------------------------------------------- per-election summary
def _reverse_map(mapping: dict[str, list[str]]) -> dict[str, str]:
    rev: dict[str, str] = {}
    for camp, codes in mapping.items():
        for code in codes:
            if code in rev:
                raise ValueError(f"party code {code} listed in two camps ({rev[code]}, {camp})")
            rev[code] = camp
    return rev


def summarise_election(cand: pd.DataFrame, mapping: dict[str, list[str]], camps: list[str]):
    """Camp shares, winner, margin and counts for one election. Returns (wide_part, winners, overlap)."""
    rev = _reverse_map(mapping)
    c = cand.copy()
    c["camp"] = c["party"].map(rev).fillna("OTH")
    rows_votes = c.groupby("ac")["votes"].sum().rename("rows_votes")
    camp_votes = (c.pivot_table(index="ac", columns="camp", values="votes", aggfunc="sum")
                    .reindex(columns=camps).fillna(0.0))
    shares = camp_votes.div(rows_votes, axis=0)

    real = c[c["party"] != "NOTA"].sort_values(["ac", "votes"], ascending=[True, False], kind="mergesort").copy()
    real["rank"] = real.groupby("ac").cumcount() + 1
    first = real[real["rank"] == 1].set_index("ac")
    second = real[real["rank"] == 2].set_index("ac")["votes"].rename("runner_up_votes")
    winners = first[["candidate", "party", "camp", "votes"]].join(second)
    winners["margin_votes"] = winners["votes"] - winners["runner_up_votes"]
    winners["margin_pp"] = winners["margin_votes"] / rows_votes.reindex(winners.index)
    winners["winner_share"] = winners["votes"] / rows_votes.reindex(winners.index)

    polled = c.groupby("ac")["polled"].first().rename("polled")
    ncand = real.groupby("ac").size().rename("ncand")
    part = shares.join(rows_votes).join(polled).join(ncand)
    part["coverage"] = part["rows_votes"] / part["polled"]

    # friendly-fight check: several codes of the same camp standing in one AC
    multi = (real[real["camp"].isin([k for k, v in mapping.items() if len(v) > 1])]
             .groupby(["ac", "camp"])["party"].nunique())
    overlap = {camp: int((multi.xs(camp, level="camp") > 1).sum()) for camp in sorted(set(multi.index.get_level_values("camp")))}
    return part, winners, overlap


# ----------------------------------------------------------------------------- main builder
def build_features(cfg: dict | None = None) -> Features:
    """Load the sources and build the AC table plus data-quality checks."""
    cfg = cfg or load_config()
    camps = cfg["camps"]["order"]
    elections = cfg["elections"]["order"]
    vs = load_vs_candidates()
    ls, ls_info = load_ls2024_candidates()
    cand_by_election = {e: vs[vs["election"] == e] for e in elections if e.startswith("VS")}
    cand_by_election["LS2024"] = ls

    wide_parts, winner_parts, overlaps, acs_per_election = [], [], {}, {}
    for e in elections:
        part, winners, overlap = summarise_election(cand_by_election[e], cfg["camps"]["elections"][e], camps)
        acs_per_election[e] = int(part.shape[0])
        overlaps[e] = overlap
        wide_parts.append(part.add_suffix(f"_{e}"))
        winners = winners.assign(election=e).reset_index().set_index(["ac", "election"])
        winner_parts.append(winners)
    wide = pd.concat(wide_parts, axis=1).sort_index()
    winners = pd.concat(winner_parts).sort_index()

    for name, parts in cfg["camps"].get("derived", {}).items():       # e.g. OPP = SPF + INC
        for e in elections:
            wide[f"{name}_{e}"] = sum(wide[f"{c}_{e}"] for c in parts)

    wide["electors_LS2024"] = ls_info["TOTAL ELECTORS IN AC"].astype(float).reindex(wide.index)
    wide["turnout_LS2024"] = wide["rows_votes_LS2024"] / wide["electors_LS2024"]

    meta = load_ac_meta().reindex(wide.index)

    # ---- data-quality checks
    thr = cfg["data_checks"]
    cov_flags = []
    for e in elections:
        col = f"coverage_{e}"
        bad = wide.index[(wide[col] < thr["coverage_min"]) | (wide[col] > 1 / thr["coverage_min"])]
        cov_flags += [{"ac": int(a), "election": e, "coverage": round(float(wide.loc[a, col]), 3)} for a in bad]
    flagged_acs = {f["ac"] for f in cov_flags}
    clean = pd.Series(~wide.index.isin(flagged_acs), index=wide.index, name="clean")
    sus = wide.index[wide["turnout_LS2024"] > thr["turnout_suspicious_above"]]

    seats = {e: winners.xs(e, level="election")["camp"].value_counts().reindex(camps).fillna(0).astype(int).to_dict()
             for e in elections}
    seats_by_party = {e: winners.xs(e, level="election")["party"].value_counts().head(8).to_dict() for e in elections}

    def norm(s: str) -> str:
        return "".join(ch for ch in str(s).lower() if ch.isalnum())
    seg_names = ls_info["AC NAME"].map(norm).reindex(wide.index)
    name_match = float((seg_names == meta["name"].map(norm)).mean())

    checks = {
        "acs_per_election": acs_per_election,
        "low_coverage_ac_elections": cov_flags,
        "excluded_from_fitting": sorted(flagged_acs),
        "turnout_suspicious_acs": [int(a) for a in sus],
        "alliance_overlap_acs": overlaps,
        "seats_by_camp": seats,
        "seats_by_party_top8": seats_by_party,
        "ac_name_match_rate_ls2024_vs_config": round(name_match, 3),
        "inputs_sha256": {p.name: file_sha256(p) for p in (VS_CSV, SEG_CSV, AC_JSON, CONFIG_PATH)},
    }
    log.info("features built: %d ACs, %d excluded from fitting", len(wide), len(flagged_acs))
    return Features(wide=wide, winners=winners, meta=meta, clean=clean, camps=camps,
                    model_camps=cfg["camps"]["model_camps"], elections=elections, checks=checks)
