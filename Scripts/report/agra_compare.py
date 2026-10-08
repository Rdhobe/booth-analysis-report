"""Agra cross-year comparison workbook: one sheet per AC (86->94).

Reads data/processed/agra_{fact,booth,crosswalk}.csv (built by
agra_pipeline.py from Excel only) and writes
data/processed/agra_comparison.xlsx.

Per booth (matched by AC + PS number; PS names shown for check; booths
without PS numbers roll up to an AC-total row):
- per election: winner party/candidate/share, margin, turnout
- per major party (BJP/SP/BSP/INC): latest mapped share, years led,
  gap-to-win (pp and votes), zone

Zones (thresholds below, see Methods sheet):
  SAFE         led every mapped election (>=3 mapped)
  LEADING      leads the latest mapped election (but not all)
  CRITICAL     gap to winner <= 5pp  (winnable now)
  UPHILL       gap 5-15pp
  NOT_POSSIBLE gap > 15pp
A party unmapped in an election (2024 non-BJP: TODO(verify)) is simply
not counted there; reference election + mapped count shown honestly.

Usage: python Scripts/agra_compare.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROC = ROOT / "data" / "processed"

ELECTIONS = ["VS2017", "LS2019", "VS2022", "LS2024"]
E_LABEL = {"VS2017": "2017 VS", "LS2019": "2019 LS",
           "VS2022": "2022 VS", "LS2024": "2024 LS"}
MAJORS = ["BJP", "SP", "BSP", "INC"]
Z_CRIT, Z_UPHILL, MIN_MAPPED = 5.0, 15.0, 3


def load():
    facts = list(csv.DictReader(open(PROC / "agra_fact.csv", encoding="utf-8")))
    booths = list(csv.DictReader(open(PROC / "agra_booth.csv", encoding="utf-8")))
    links = list(csv.DictReader(open(PROC / "agra_crosswalk.csv", encoding="utf-8")))
    return facts, booths, links


def main() -> int:
    facts, booths, links = load()

    # votes per (booth, party); booth meta
    pv: dict = {}
    meta: dict = {}
    for b in booths:
        pv[b["booth_uid"]] = {}
        meta[b["booth_uid"]] = b
    for f in facts:
        if f["party"] == "NOTA":
            continue
        d = pv[f["booth_uid"]]
        d[f["party"]] = d.get(f["party"], 0) + int(f["votes"])
    # candidate names per booth (for winner candidate display)
    cand_by_booth: dict = {}
    for f in facts:
        cand_by_booth.setdefault(f["booth_uid"], []).append(
            (f["candidate"], f["party"], int(f["votes"])))

    def share(uid, party):
        b = meta[uid]
        polled = int(b["polled"] or 0)
        if not polled:
            return None
        return pv[uid].get(party, 0) / polled * 100

    def winner(uid):
        cands = cand_by_booth.get(uid, [])
        if not cands:
            return None, None, None
        tot = sum(v for _, _, v in cands)
        # party totals for winner party (NOTA excluded already)
        pt: dict = {}
        for _c, p, v in cands:
            pt[p] = pt.get(p, 0) + v
        wparty = max(pt, key=lambda p: pt[p])
        wcand = max([c for c in cands if c[1] == wparty],
                    key=lambda c: c[2])[0]
        polled = int(meta[uid]["polled"] or 0) or tot or 1
        return wparty, wcand, pt[wparty] / polled * 100

    # booth lineage across elections: follow crosswalk 1:1 links (conf>=0.8)
    # keyed (ac, ps) per election; lineage = dict election -> booth_uid
    by_ac_ps: dict = {}
    for b in booths:
        try:
            ac = int(b["ac"])
        except ValueError:
            continue
        by_ac_ps.setdefault((ac, b["ps"]), {})[b["election"]] = b["booth_uid"]
    conf_min: dict = {}
    for L in links:
        if L["link"] == "1:1":
            try:
                c = float(L["conf"])
            except ValueError:
                continue
            key = (L["curr_uid"], L["pair"])
            conf_min[key] = min(conf_min.get(key, 1.0), c)

    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # AC x election x party summary (for quick reading)
    ac_tot: dict = {}
    ac_polled: dict = {}
    for f in facts:
        if f["party"] == "NOTA":
            continue
        ac_tot[(int(f["ac"]), f["election"], f["party"])] = \
            ac_tot.get((int(f["ac"]), f["election"], f["party"]), 0) + int(f["votes"])
    for b in booths:
        try:
            ac_polled[(int(b["ac"]), b["election"])] = \
                ac_polled.get((int(b["ac"]), b["election"]), 0) + int(b["polled"] or 0)
        except ValueError:
            pass
    ws0 = wb.create_sheet("AC_Summary")
    ws0.append(["AC", "election", "party", "votes", "share % of AC polled"])
    for (ac, e, p) in sorted(ac_tot):
        polled = ac_polled.get((ac, e)) or 0
        ws0.append([ac, E_LABEL[e], p, ac_tot[(ac, e, p)],
                    round(ac_tot[(ac, e, p)] / polled * 100, 2) if polled else ""])
    for ac in range(86, 95):
        ws = wb.create_sheet(f"AC{ac}")
        header = ["PS No", "PS Name (latest)", "min link conf", "AC-total row?"]
        for e in ELECTIONS:
            el = E_LABEL[e]
            header += [f"{el} winner", f"{el} winner cand", f"{el} winner %",
                       f"{el} margin pp", f"{el} turnout %"]
        for p in MAJORS:
            header += [f"{p} latest %", f"{p} led (x/y mapped)",
                       f"{p} gap to win pp", f"{p} votes needed",
                       f"{p} zone"]
        ws.append(header)
        # booth rows for this AC, PS order numeric-first
        keys = sorted([k for k in by_ac_ps if k[0] == ac],
                      key=lambda k: (0, int(k[1])) if k[1].isdigit()
                      else (1, k[1]))
        # AC-total fallback: booths without PS numbers (none in current
        # data) would aggregate here at AC level instead of per-PS rows.
        psless = [b for b in booths
                  if b["ac"] == str(ac) and not b["ps"]]
        if psless:
            ws.append(["(AC total: %d booths without PS numbers - see "
                       "agra_booth.csv)" % len(psless), "", "", "YES"])
        for ps_key in keys:
            lin = by_ac_ps[ps_key]
            row = [ps_key[1]]
            # latest non-numeric name
            nm, mc = "", 1.0
            for e in reversed(ELECTIONS):
                if e in lin:
                    nm = meta[lin[e]]["ps_name"] or nm
                    for Lpair in [f"{ELECTIONS[i]}>{ELECTIONS[i+1]}"
                                  for i in range(3)]:
                        mc = min(mc, conf_min.get((lin[e], Lpair), 1.0))
            row += [nm, round(mc, 2), ""]
            # per-election blocks
            elec_data = {}
            for e in ELECTIONS:
                if e not in lin:
                    row += ["", "", "", "", ""]
                    elec_data[e] = None
                    continue
                uid = lin[e]
                wparty, wcand, wshare = winner(uid)
                tot = pv[uid]
                polled = int(meta[uid]["polled"] or 0) or sum(tot.values()) or 1
                shares = sorted(((p, v / polled * 100) for p, v in tot.items()),
                                key=lambda kv: -kv[1])
                margin = shares[0][1] - (shares[1][1] if len(shares) > 1 else 0)
                el = meta[uid]["electors"]
                turn = (int(meta[uid]["polled"] or 0) / int(el) * 100) \
                    if el and str(el).isdigit() and int(el) else None
                row += [wparty, wcand,
                        round(wshare, 2) if wshare is not None else "",
                        round(margin, 2),
                        round(turn, 2) if turn is not None else ""]
                elec_data[e] = {"winner": wparty, "wshare": wshare,
                                "polled": int(meta[uid]["polled"] or 0)}
            # per-party zones
            for p in MAJORS:
                # mapped = elections where the party fielded (overall set)
                mapped = [e for e in ELECTIONS if e in lin and p in fielded[e]]
                led = [e for e in mapped
                       if elec_data[e] and elec_data[e]["winner"] == p]
                if not mapped:
                    row += ["", f"0/{len([e for e in ELECTIONS if e in lin])}",
                            "", "", "UNMAPPED"]
                    continue
                ref = mapped[-1]
                ref_share = share(lin[ref], p) or 0.0
                wshare = elec_data[ref]["wshare"] or 0.0
                gap = round(wshare - ref_share, 2)
                votes_needed = max(0, round(gap / 100 * elec_data[ref]["polled"]))
                if len(led) == len(mapped) and len(mapped) >= MIN_MAPPED:
                    zone = "SAFE"
                elif elec_data[ref]["winner"] == p:
                    zone = "LEADING"
                elif gap <= Z_CRIT:
                    zone = "CRITICAL"
                elif gap <= Z_UPHILL:
                    zone = "UPHILL"
                else:
                    zone = "NOT_POSSIBLE"
                row += [round(ref_share, 2), f"{len(led)}/{len(mapped)}",
                        gap, votes_needed, zone]
            ws.append(row)
        # freeze + widths + filter
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.column_dimensions["A"].width = 10
        ws.column_dimensions["B"].width = 30

    # fielded parties per election (for zones) must exist before loop:
    # (computed below; sheets already written using it -> recompute first)
    m = wb.create_sheet("Methods_Zones")
    m["A1"] = ("One row per polling station (AC + PS No. match; PS names shown "
               "for check; min link conf shown; swings only on conf>=0.8). "
               "Shares = votes/polled. Zones per major party over MAPPED "
               "elections only: SAFE led all (>=3 mapped); LEADING leads "
               "latest; CRITICAL gap<=5pp; UPHILL gap 5-15pp; NOT_POSSIBLE "
               "gap>15pp; UNMAPPED where 2024 labels missing (TODO verify). "
               "gap_to_win = winner% - party% at reference (latest mapped) "
               "election; votes_needed = gap% x polled. "
               "2024 has no electors: turnout N/A touching 2024. "
               "Flags are statistical_outlier, never fraud. See brain/.")
    wb.save(str(PROC / "agra_comparison.xlsx"))
    print("wrote", PROC / "agra_comparison.xlsx")
    return 0


if __name__ == "__main__":
    # fielded[...] referenced inside main loop: build before main runs
    import csv as _csv
    fielded = {}
    for _r in _csv.DictReader(open(PROC / "agra_fact.csv", encoding="utf-8")):
        if _r["party"] not in ("NOTA", "UNMAPPED"):
            fielded.setdefault(_r["election"], set()).add(_r["party"])
    sys.exit(main())
