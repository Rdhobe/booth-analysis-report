"""Compare a produced Form20 workbook with a correct (ground-truth) workbook.

    python eval/compare.py produced.xlsx truth.xlsx [--out mismatches.csv]

Both files may be in the Form 20 layout (header row starting with 'Serial No.').
Rows are matched on the serial number; the numeric columns are matched by
position starting at the third column, up to and including 'No. of Tendered
Votes'. Prints cell- and row-level accuracy and lists every difference.
"""
import argparse
import csv
import sys

from openpyxl import load_workbook


def read_form20(path, sheet=None):
    wb = load_workbook(path, data_only=True)
    ws = wb[sheet] if sheet else (wb["Form20"] if "Form20" in wb.sheetnames else wb.active)
    header_row = None
    for r in range(1, 40):
        v = ws.cell(row=r, column=1).value
        if isinstance(v, str) and v.strip().lower().startswith("serial no") and ws.cell(row=r, column=3).value:
            header_row = r
            break
    if header_row is None:
        raise SystemExit(f"{path}: no header row starting with 'Serial No.' found")
    last = 3
    names = []
    while True:
        v = ws.cell(row=header_row, column=last).value
        if v is None:
            break
        names.append(str(v).strip())
        if "tendered" in str(v).lower():
            break
        last += 1
    rows = {}
    for r in range(header_row + 1, ws.max_row + 1):
        serial = ws.cell(row=r, column=1).value
        if not isinstance(serial, (int, float)):
            continue
        rows[int(serial)] = [ws.cell(row=r, column=c).value for c in range(3, last + 1)]
    return names, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("produced")
    ap.add_argument("truth")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    pn, prod = read_form20(a.produced)
    tn, truth = read_form20(a.truth)
    if len(pn) != len(tn):
        print(f"warning: column counts differ (produced {len(pn)}, truth {len(tn)}); comparing the common prefix")
    ncol = min(len(pn), len(tn))
    cells = bad_cells = rows_ok = 0
    diffs = []
    for s, trow in sorted(truth.items()):
        prow = prod.get(s)
        if prow is None:
            diffs.append((s, "(row missing in produced)", "", ""))
            continue
        row_bad = False
        for i in range(ncol):
            cells += 1
            if prow[i] != trow[i]:
                bad_cells += 1
                row_bad = True
                diffs.append((s, tn[i], prow[i], trow[i]))
        rows_ok += not row_bad
    extra = sorted(set(prod) - set(truth))
    print(f"rows in truth: {len(truth)}   rows produced: {len(prod)}   extra rows produced: {len(extra)}")
    print(f"rows exactly right: {rows_ok}/{len(truth)} ({100 * rows_ok / max(1, len(truth)):.2f}%)")
    print(f"cells right: {cells - bad_cells}/{cells} ({100 * (cells - bad_cells) / max(1, cells):.3f}%)")
    if a.out:
        with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["serial", "column", "produced", "truth"])
            w.writerows(diffs)
        print("differences written to", a.out)
    else:
        for d in diffs[:30]:
            print("  serial", d[0], "|", d[1], "| produced", d[2], "| truth", d[3])
        if len(diffs) > 30:
            print(f"  ... {len(diffs) - 30} more (use --out)")
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())
