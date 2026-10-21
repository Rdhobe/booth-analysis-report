"""Independent check of converted workbooks against the official 2024 assembly-segment results.

    python batch/verify_official.py [--workbooks data/output/2024] [--ledger queue/conversion_ledger.csv]

data/assembly-segment-level-voting-data-for-all-constituencies-2024.csv lists, for every assembly segment, each
candidate's EVM votes and the NOTA votes. The booth rows of a correctly converted Form 20 must add up to exactly those
numbers, whatever the sheet's own printed totals row looked like (it is often misread). Candidate columns are matched
to official candidates by value, which also gives the real candidate names.

Writes queue/official_check.csv (one row per workbook). Read-only on the workbooks and the official file.
"""
import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from queue_common import QUEUE_DIR, REPO_ROOT, TOOL_DIR, read_csv, write_csv  # noqa: E402

OFFICIAL_CSV = REPO_ROOT / "data" / "assembly-segment-level-voting-data-for-all-constituencies-2024.csv"
CHECK_FIELDS = ["ac", "file", "verdict", "cols_sheet", "cols_official", "matched", "nota_sheet", "nota_official",
                "nota_swapped", "missing_cells", "detail"]


def load_official(path=OFFICIAL_CSV, state="Uttar Pradesh"):
    """{ac: {'name', 'nota', 'electors', 'candidates': [(name, party, evm votes)]}} for one state."""
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = csv.reader(f)
        next(rows)                       # title line
        head = next(rows)
        col = {h: i for i, h in enumerate(head)}
        for r in rows:
            if not r or r[col["State/UT Name"]].strip().lower() != state.lower():
                continue
            ac = int(r[col["AC NO"]])
            e = out.setdefault(ac, {"name": r[col["AC NAME"]], "nota": int(r[col["NOTA VOTES EVM IN AC"]] or 0),
                                    "electors": int(r[col["TOTAL ELECTORS IN AC"]] or 0), "candidates": []})
            e["candidates"].append((r[col["CANDIDATE NAME"]], r[col["PARTY"]], int(r[col["VOTES SECURED EVM"]] or 0)))
    return out


def sheet_sums(xlsx_path):
    """Column sums from a workbook's Tidy sheet -> (candidate columns in sheet order [(label, sum)], {metric: sum},
    number of cells without a value). Columns are told apart by position, not by name: OCR often gives several
    columns the same (or an empty) name."""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    cols, metrics, missing = [], defaultdict(int), 0
    tidy = list(wb["Tidy"].iter_rows(values_only=True))[1:]
    wb.close()                                    # release the file (Windows keeps read-only workbooks locked)
    i, prev = 0, None                             # candidate column of the current booth; metric of the previous row
    for r in tidy:
        serial, metric, name, votes = r[4], r[6], r[7], r[10]
        if metric == "CANDIDATE":
            if prev != "CANDIDATE":               # a new booth starts (serials restart in multi-constituency PDFs)
                i = 0
            if i >= len(cols):
                cols.append([name, 0])
            if votes is None:
                missing += 1
            else:
                cols[i][1] += votes
            i += 1
        elif votes is None:
            missing += 1
        else:
            metrics[metric] += votes
        prev = metric
    return [(label, total) for label, total in cols], dict(metrics), missing


def compare(cand_sums, metrics, official):
    """Match sheet columns to official candidates by exact value.

    Returns a dict with verdict FULL (every candidate column and the NOTA total equal the official numbers),
    PARTIAL (some columns match) or NONE, the number of matched columns, and a detail string."""
    off = list(official["candidates"])
    unused = Counter(v for _, _, v in off)
    matched, unmatched_sheet = 0, []
    for label, total in cand_sums:
        if unused[total] > 0:
            unused[total] -= 1
            matched += 1
        else:
            unmatched_sheet.append((label, total))
    unmatched_off = sorted(v for v, n in unused.items() for _ in range(n))
    nota_sheet, nota_off = metrics.get("NOTA"), official["nota"]
    nota_ok = nota_sheet == nota_off
    # Some sheets print NOTA before the rejected votes. Both identities are symmetric, so the extractor cannot tell;
    # the official NOTA total can: if the "rejected" column adds up to it, the two labels are swapped.
    swapped = not nota_ok and metrics.get("REJECTED") == nota_off
    nota_ok = nota_ok or swapped
    full = len(cand_sums) == len(off) and matched == len(off) and nota_ok
    verdict = "FULL" if full else ("PARTIAL" if matched else "NONE")
    detail = []
    for (label, total), want in zip(sorted(unmatched_sheet, key=lambda t: t[1]), unmatched_off):
        detail.append(f"{str(label)[:18]}: sheet {total} vs official {want} ({total - want:+d})")
    if len(unmatched_sheet) != len(unmatched_off):
        detail.append(f"{len(cand_sums)} sheet columns vs {len(off)} official candidates")
    if swapped:
        detail.append("NOTA and rejected columns are swapped in the sheet (NOTA was read as 'rejected')")
    elif not nota_ok:
        detail.append(f"NOTA: sheet {nota_sheet} vs official {nota_off}")
    return {"verdict": verdict, "cols_sheet": len(cand_sums), "cols_official": len(off), "matched": matched,
            "nota_sheet": nota_sheet, "nota_official": nota_off, "nota_swapped": "yes" if swapped else "",
            "detail": "; ".join(detail)}


def check_workbook(ac, xlsx_path, official):
    cand, metrics, missing = sheet_sums(xlsx_path)
    if ac not in official:
        return {"ac": ac, "file": Path(xlsx_path).name, "verdict": "NO_OFFICIAL", "missing_cells": missing,
                "cols_sheet": len(cand)}
    res = compare(cand, metrics, official[ac])
    return {"ac": ac, "file": Path(xlsx_path).name, "missing_cells": missing, **res}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check converted workbooks against the official segment results.")
    ap.add_argument("--ledger", default=str(QUEUE_DIR / "conversion_ledger.csv"))
    ap.add_argument("--official", default=str(OFFICIAL_CSV))
    ap.add_argument("--out", default=str(QUEUE_DIR / "official_check.csv"))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    official = load_official(args.official)
    results = []
    for r in sorted(read_csv(args.ledger), key=lambda r: int(r["ac"])):
        if r["status"] == "DONE" and r["xlsx"] and Path(r["xlsx"]).exists():
            results.append(check_workbook(int(r["ac"]), r["xlsx"], official))
    write_csv(args.out, CHECK_FIELDS, results)
    print(dict(Counter(r["verdict"] for r in results)), f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
