"""Map Agra pipeline outputs into the Mahad-style workbook (configs/output_format.json).

Reads data/processed/agra_{fact,booth}.csv, writes output/agra_booth_report.xlsx
(output/ — NEVER data/, which is input storage only).

Layout per spec: ONE All_ACs sheet (all booths AC86..AC94 with an AC
column + per-row Party B; booth rows: label/address/serials/zone +
per-election A/B shares + Voting.Diff), Booth_Votes (alternating
booth/votes rows), Zone_Counts, Methods_Zones.

Party A = BJP (fixed). Party B = top non-BJP party by AC votes in the
latest fully-mapped election (VS2022), fixed per AC, recorded per row
(Party B column) and in Methods.
Zones: Safe/Favorable/Battlefield/Difficult/Data Not sufficient
(see output_format.json).

Usage: python Scripts/output_mahad.py [--out output]
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROC = ROOT / "data" / "processed"

ELECTIONS = ["VS2017", "LS2019", "VS2022", "LS2024"]
E_LABEL = {"VS2017": "2017 Vidhansabha", "LS2019": "2019 Loksabha",
           "VS2022": "2022 Vidhansabha", "LS2024": "2024 Loksabha"}
PARTY_A = "BJP"
SAFE_UP, DIFF_DOWN = 0.10, -0.10

# Report palette (also documented in Methods_Zones)
ZONE_FILL = {"Safe": "C6EFCE", "Favorable": "E2EFDA",
             "Battlefield": "FFEB9C", "Difficult": "FFC7CE",
             "Data Not sufficient": "D9D9D9", "UNMAPPED": "D9D9D9"}
ZONE_FONT = {"Safe": "006100", "Favorable": "375623",
             "Battlefield": "9C6500", "Difficult": "9C0006",
             "Data Not sufficient": "404040", "UNMAPPED": "404040"}
HDR_FILL, HDR_FONT = "1F4E79", "FFFFFF"
POS_FILL, NEG_FILL = "C6EFCE", "FFC7CE"


def style_report_workbook(wb):
    """Conditional formatting + coloring for the whole workbook."""
    from openpyxl.formatting.rule import CellIsRule, DataBarRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    hdr_fill = PatternFill("solid", fgColor=HDR_FILL)
    hdr_font = Font(bold=True, color=HDR_FONT, size=11)
    pos_fill = PatternFill("solid", fgColor=POS_FILL)
    neg_fill = PatternFill("solid", fgColor=NEG_FILL)
    wrap = Alignment(wrap_text=True, vertical="center")
    for ws in wb.worksheets:
        if ws.max_row < 2:
            continue
        # title row + header row styling (row1 title, row2 headers;
        # Booth_Votes/Zone_Counts/AC_Summary have headers on row1)
        hrow = 2 if ws.title == "All_ACs" else 1
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(hrow, c)
            if str(cell.value or "").strip():
                cell.fill = hdr_fill
                cell.font = hdr_font
                cell.alignment = wrap
        if ws.title == "All_ACs":
            ws.cell(1, 1).font = Font(bold=True, size=12)
            last = ws.max_row
            # diff columns: green/red vs zone thresholds (I,J + P,U,Z,AE)
            for col in ["I", "J", "P", "U", "Z", "AE"]:
                rng = f"{col}4:{col}{last}"
                ws.conditional_formatting.add(
                    rng, CellIsRule("greaterThan", formula=[SAFE_UP], fill=pos_fill))
                ws.conditional_formatting.add(
                    rng, CellIsRule("lessThan", formula=[DIFF_DOWN], fill=neg_fill))
            # share columns: data bars 0..1
            for col in ["M", "N", "R", "S", "W", "X", "AB", "AC"]:
                ws.conditional_formatting.add(
                    f"{col}4:{col}{last}",
                    DataBarRule(start_type="num", start_value=0,
                                end_type="num", end_value=1, color="638EC6"))
            # zone column H: fill by value (explicit cells beat rules here)
            for r in range(4, last + 1):
                cell = ws.cell(r, 8)
                z = str(cell.value or "")
                if z in ZONE_FILL:
                    cell.fill = PatternFill("solid", fgColor=ZONE_FILL[z])
                    cell.font = Font(bold=True, color=ZONE_FONT[z])
        if ws.title == "Zone_Counts":
            for r in range(2, ws.max_row + 1):
                z = str(ws.cell(r, 1).value or "")
                if z in ZONE_FILL:
                    for c in (1, 2):
                        ws.cell(r, c).fill = PatternFill(
                            "solid", fgColor=ZONE_FILL[z])
        if ws.title == "Methods_Zones":
            ws.column_dimensions["A"].width = 180
            ws["A1"].alignment = wrap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agra -> Mahad-format workbook")
    ap.add_argument("--out", default="output")
    args = ap.parse_args(argv)
    outdir = ROOT / args.out
    outdir.mkdir(parents=True, exist_ok=True)

    facts = list(csv.DictReader(open(PROC / "agra_fact.csv", encoding="utf-8")))
    booths = list(csv.DictReader(open(PROC / "agra_booth.csv", encoding="utf-8")))

    votes: dict = {}   # (uid, party) -> votes
    booth_by_uid = {}
    for b in booths:
        booth_by_uid[b["booth_uid"]] = b
    for f in facts:
        if f["party"] in ("NOTA", "UNMAPPED"):
            continue
        votes[(f["booth_uid"], f["party"])] = \
            votes.get((f["booth_uid"], f["party"]), 0) + int(f["votes"])

    def booths_of(ac, election):
        return [b for b in booths
                if b["ac"] == str(ac) and b["election"] == election]

    def share(uid, party):
        b = booth_by_uid[uid]
        # unmapped party in this election -> unknown, NOT zero
        if party not in fielded.get(b["election"], set()):
            return None
        polled = int(b["polled"] or 0)
        if not polled:
            return None
        return votes.get((uid, party), 0) / polled

    # Party B per AC: top non-BJP by AC votes in latest mapped election
    party_b = {}
    for ac in range(86, 95):
        for e in reversed(ELECTIONS):
            tot: dict = {}
            for b in booths_of(ac, e):
                for (uid, p), v in votes.items():
                    if uid == b["booth_uid"] and p != PARTY_A:
                        tot[p] = tot.get(p, 0) + v
            tot = {p: v for p, v in tot.items() if v > 0}
            if tot:
                party_b[ac] = (max(tot, key=lambda p: tot[p]), e)
                break
        if ac not in party_b:
            party_b[ac] = ("", "")

    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # fielded parties per election (UNMAPPED/None excluded)
    fielded = {}
    for f in facts:
        if f["party"] not in ("NOTA", "UNMAPPED"):
            fielded.setdefault(f["election"], set()).add(f["party"])
    zone_counts = defaultdict(int)

    def header_rows(ws):
        ws.append(["AGRA (AC 86-94) BOOTH ANALYSIS (A=BJP fixed; "
                   "B = per-row Party B col, top non-BJP by latest mapped "
                   "election votes)"])
        ws.append(["AC", "Polling station name", "Polling Station Address",
                   "2017", "2019", "2022", "2024",
                   "Defination", "Average Diff", "Latest Diff", "",
                   "Party B",
                   f"{E_LABEL['VS2017']}", "", "",
                   "Voting.Diff", "",
                   f"{E_LABEL['LS2019']}", "", "",
                   "Voting.Diff", "",
                   f"{E_LABEL['VS2022']}", "", "",
                   "Voting.Diff", "",
                   f"{E_LABEL['LS2024']}", "", "",
                   "Voting.Diff"])
        ws.append(["", "मतदान केंद्र", "मतदान केंद्र का विवरण",
                   "", "", "", "", "", "", "", "", "",
                   f"{PARTY_A} V.%", "B V.%", "",
                   "", "",
                   f"{PARTY_A} V.%", "B V.%", "",
                   "", "",
                   f"{PARTY_A} V.%", "B V.%", "",
                   "", "",
                   f"{PARTY_A} V.%", "B V.%", "",
                   ""])

    ws = wb.create_sheet("All_ACs")
    header_rows(ws)
    for ac in range(86, 95):
        bparty, belec = party_b[ac]
        # booth universe: union of PS numbers across elections
        ps_all = sorted({b["ps"] for e in ELECTIONS for b in booths_of(ac, e)},
                        key=lambda p: (0, int(p)) if p.isdigit() else (1, p))
        detail = []
        for ps in ps_all:
            per_e = {}
            for e in ELECTIONS:
                bl = booths_of(ac, e)
                hit = [b for b in bl if b["ps"] == ps]
                per_e[e] = hit[0] if hit else None
            if not any(per_e.values()):
                continue
            # latest readable name: long English-case station names beat
            # numeric repeats ('1') and legacy codes; fall back gracefully
            cands = []
            for e in reversed(ELECTIONS):
                if per_e[e] and per_e[e]["ps_name"]:
                    cands.append(per_e[e]["ps_name"])
            eng = [n for n in cands
                   if not any(ch.islower() for ch in n) and len(n) > 6]
            nm = max(eng, key=len) if eng else ""
            nm = nm or next((n for n in cands if n.strip() != ""), "")
            row = [str(ac), f"{ps} - {nm}", nm,
                   *[per_e[e]["ps"] if per_e[e] else "" for e in ELECTIONS]]
            diffs = []
            for e in ELECTIONS:
                if not per_e[e]:
                    diffs.append(None)
                    continue
                uid = per_e[e]["booth_uid"]
                a = share(uid, PARTY_A)
                bb = share(uid, bparty) if bparty else None
                diffs.append(None if a is None or bb is None else a - bb)
            have = [d for d in diffs if d is not None]
            avg = sum(have) / len(have) if have else None
            latest = next((d for d in reversed(diffs) if d is not None), None)
            if len(have) < 2:
                zone = "Data Not sufficient"
            elif avg > SAFE_UP and (latest or 0) > 0:
                zone = "Safe"
            elif avg < DIFF_DOWN and (latest or 0) < 0:
                zone = "Difficult"
            elif (avg or 0) > 0 and (latest or 0) > 0:
                zone = "Favorable"
            else:
                zone = "Battlefield"
            zone_counts[zone] += 1
            row += [zone,
                    round(avg, 4) if avg is not None else "",
                    round(latest, 4) if latest is not None else "", "",
                    bparty or ""]
            for e, d in zip(ELECTIONS, diffs):
                if not per_e[e]:
                    row += ["", "", "", "", ""]
                    continue
                uid = per_e[e]["booth_uid"]
                a = share(uid, PARTY_A)
                bb = share(uid, bparty) if bparty else None
                row += [round(a, 4) if a is not None else "",
                        round(bb, 4) if bb is not None else "", "",
                        round(d, 4) if d is not None else "", ""]
            ws.append(row)
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = ws.dimensions
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 34
    # Booth_Votes sheet (booth row + votes row pattern, cf. example)
    wv = wb.create_sheet("Booth_Votes")
    wv.append(["AC", "booth", "address", "2017", "2019", "2022", "2024",
               "Defination"])
    for ac in range(86, 95):
        ps_all = sorted({b["ps"] for e in ELECTIONS for b in booths_of(ac, e)},
                        key=lambda p: (0, int(p)) if p.isdigit() else (1, p))
        wv.append([f"AC{ac}"])
        for ps in ps_all:
            per_e = {}
            for e in ELECTIONS:
                hit = [b for b in booths_of(ac, e) if b["ps"] == ps]
                per_e[e] = hit[0] if hit else None
            if not any(per_e.values()):
                continue
            nm = ""
            for e in reversed(ELECTIONS):
                if per_e[e] and per_e[e]["ps_name"]:
                    nm = per_e[e]["ps_name"]
                    break
            erow = [f"{ps} - {nm}", nm,
                    *[per_e[e]["ps"] if per_e[e] else "" for e in ELECTIONS], ""]
            wv.append(erow)
            vrow = ["", ""]
            for e in ELECTIONS:
                if not per_e[e]:
                    vrow.append("")
                    continue
                uid = per_e[e]["booth_uid"]
                va = votes.get((uid, PARTY_A), 0)
                bparty = party_b[ac][0]
                vb = votes.get((uid, bparty), 0) if bparty else 0
                tot = int(per_e[e]["polled"] or 0)
                vrow.append(f"A={va} B={vb} total={tot}")
            vrow.append("")
            wv.append(vrow)
    wz = wb.create_sheet("Zone_Counts")
    wz.append(["Type of Booths", "Nos"])
    for z in ["Safe", "Favorable", "Battlefield", "Difficult",
              "Data Not sufficient"]:
        wz.append([z, zone_counts.get(z, 0)])
    wm = wb.create_sheet("Methods_Zones")
    wm["A1"] = ("Format per configs/output_format.json (from Mahad example). "
                "Single All_ACs sheet (AC column; filter it for per-AC views) "
                "instead of one sheet per AC. A=BJP fixed; B per row = top "
                "non-BJP by latest mapped election votes (Party B column): "
                + "; ".join(f"AC{ac}={party_b[ac][0]}({party_b[ac][1]})" for ac in range(86, 95))
                + ". Shares = votes/polled (fraction). Voting.Diff = A-B. "
                "Zones: Safe avg>+0.10&latest>0; Difficult avg<-0.10&latest<0; "
                "Favorable avg>0&latest>0 (leading, not Safe); Battlefield "
                "otherwise contested; Data Not sufficient <2 elections. "
                "Names as-is (legacy codes kept). UNMAPPED excluded from shares. "
                "2024 has no electors (turnout N/A). Flags are statistical_outlier, never fraud.")
    outpath = Path(args.out)
    if not outpath.is_absolute():
        outpath = ROOT / outpath
    outpath.mkdir(parents=True, exist_ok=True)
    path = outpath / "agra_booth_report.xlsx"
    style_report_workbook(wb)
    try:
        wb.save(str(path))
    except PermissionError:
        # file open in Excel: versioned fallback instead of crashing
        import datetime as _dt
        path = outpath / ("agra_booth_report_%s.xlsx"
                          % _dt.datetime.now().strftime("%Y%m%d-%H%M"))
        wb.save(str(path))
        print(f"(main file locked - saved {path.name} instead)", flush=True)
    print(f"wrote {path} zones={dict(zone_counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
