"""Review packs: for each converted AC that does not match the official totals, a workbook that says where to look.

    python batch/review_pack.py                    # every converted AC whose columns are all within 10% of official
    python batch/review_pack.py --ac 47,50         # chosen ACs
    python batch/review_pack.py --all              # every converted AC

Each pack is the converted workbook (nothing in it is changed except highlights) plus an `Official_Gap` sheet in front:
  1. every candidate column and NOTA against the official 2024 EVM total, and the difference;
  2. where votes are probably missing: pages with fewer rows than their neighbours, jumps in the serial numbers, and an
     estimate of how many booths the shortfall is worth;
  3. the rows the extractor flagged (red = review, orange = unusual, yellow = auto-corrected), with links to them.
Pages that lost rows get a blue serial cell with a comment on the Form20 sheet. Packs go to data/2024/review/, with
REVIEW_INDEX.csv classifying every converted AC. After correcting cells, run batch/recheck_reviewed.py on the pack.
"""
import argparse
import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import openpyxl  # noqa: E402
from openpyxl.comments import Comment  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402

from queue_common import QUEUE_DIR, REPO_ROOT, read_csv  # noqa: E402
from review_common import column_sums, ledger_workbook, read_form20  # noqa: E402
from verify_official import check_workbook, compare, load_official  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "data" / "2024" / "review"
BLUE, GREEN, RED, GREY = (PatternFill("solid", fgColor=c) for c in ("9DC3E6", "C6EFCE", "FFC7CE", "D9D9D9"))
BOLD = Font(bold=True)


def rank_pairs(cand_sums, official_candidates):
    """Pair sheet columns with official candidates by rank of the totals: [(sheet index, official name, official votes)]."""
    s = sorted(range(len(cand_sums)), key=lambda i: cand_sums[i][1])
    o = sorted(official_candidates, key=lambda c: c[2])
    return {i: (o[k][0], o[k][2]) for k, i in enumerate(s) if k < len(o)}


def page_inventory(booths):
    """Per page: rows found, first/last serial, flagged counts. Plus the planned gaps (rescue.plan_missing_rows)."""
    from form20.rescue import plan_missing_rows, typical_rows
    n_pages = max(b["page"] for b in booths)
    pages = [[b for b in booths if b["page"] == p + 1] for p in range(n_pages)]
    plan, unknown = plan_missing_rows([[{"serial": b["serial"]} for b in rows] for rows in pages])
    full = typical_rows([len(r) for r in pages])
    return pages, plan, unknown, full


def classify(chk, source, plan, unknown, est_missing, flagged, exact, n_cols, nota_diff):
    """(class, advice) for the index."""
    worst = chk["worst"]
    if exact == n_cols and nota_diff:
        return "NOTA COLUMN", f"Every candidate column is exact; the NOTA total is off by {nota_diff:+d} (a NOTA column problem)."
    if source == "text layer" and worst <= 0.005:
        return "SOURCE DIFFERS", "The digits are exact (typed PDF); the sheet and the official data differ by a few votes."
    gaps = sum(sum(v) for v in plan.values()) + sum(unknown.values())
    if est_missing >= 0.7 and worst <= 0.10:
        where = f"about {gaps} row(s) on the blue-marked pages" if gaps else "no page is short; look at the last pages"
        return "ROWS MISSING", f"Votes for about {est_missing:.0f} booth(s) are missing: {where}. Re-read and add them."
    if est_missing <= -0.7 and worst <= 0.10:
        return "EXTRA ROWS", f"The sheet holds about {-est_missing:.0f} booth(s) more than the official total: look for a duplicated or total row."
    if worst <= 0.10:
        return "CHECK ROWS", f"Digits misread in some of the {flagged} flagged rows, or an unflagged row; check them against the scan."
    return "NEEDS CODE FIX", "Off by more than 10%: rows, pages or columns are wrong; needs a better reader first."


def build_pack(ac, ledger_rows, official, out_dir, max_off):
    row, chk = ledger_workbook(ac, ledger_rows, official[ac], check_workbook)
    if row is None:
        return None
    form = read_form20(row["xlsx"])
    cand, metrics = column_sums(form)
    off = official[ac]
    pairs = rank_pairs(cand, off["candidates"])
    diffs = [(i, cand[i][1] - pairs[i][1], pairs[i][1]) for i in pairs]
    worst = max((abs(d) / max(v, 1) for _, d, v in diffs), default=1.0) if len(cand) == len(off["candidates"]) else 1.0
    exact = sum(1 for _, d, _ in diffs if d == 0)
    booths = form["booths"]
    pages, plan, unknown, full = page_inventory(booths)
    sheet_total = sum(v for _, v in cand)
    off_total = sum(v for _, _, v in off["candidates"])
    avg_booth = sheet_total / max(len(booths), 1)
    est_missing = (off_total - sheet_total) / avg_booth if avg_booth else 0.0
    flagged = [b for b in booths if b["status"] in ("REVIEW", "UNUSUAL")]
    auto = [b for b in booths if b["status"] == "AUTO_CORRECTED"]
    nota_diff = metrics["NOTA"] - off["nota"]
    kind, advice = classify({"worst": worst}, row.get("source", ""), plan, unknown, est_missing, len(flagged), exact,
                            len(off["candidates"]), nota_diff)
    entry = {"ac": ac, "pdf": row["file"], "produced_by": row.get("source") or "ocr", "booth_rows": len(booths),
             "columns_exact": f"{exact}/{len(off['candidates'])}", "worst_column_off_pct": round(100 * worst, 2),
             "estimated_missing_booths": round(est_missing, 1),
             "pages_short": ";".join(str(p + 1) for p in sorted(set(plan) | set(unknown))),
             "rows_to_check": len(flagged), "auto_corrected_rows": len(auto), "class": kind, "advice": advice,
             "review_file": ""}
    if worst > max_off:
        return entry
    wb = openpyxl.load_workbook(row["xlsx"])
    ws = wb["Form20"]
    for p, (up, down) in plan.items():                    # blue serial cells with a comment where rows are missing
        rows = pages[p]
        if up and rows:
            c = ws.cell(rows[0]["row"], 1)
            c.fill, c.comment = BLUE, Comment(f"{up} row(s) missing ABOVE this one (page {p + 1}); serials jump here.", "review pack")
        if down and rows:
            c = ws.cell(rows[-1]["row"], 1)
            c.fill, c.comment = BLUE, Comment(f"{down} row(s) missing BELOW this one (page {p + 1}); serials jump after it.", "review pack")
    for p, k in unknown.items():
        rows = pages[p]
        if rows:
            for c in (ws.cell(rows[0]["row"], 1), ws.cell(rows[-1]["row"], 1)):
                c.fill = BLUE
            ws.cell(rows[0]["row"], 1).comment = Comment(
                f"Page {p + 1} has {len(rows)} rows, a full page {full}: {k} row(s) missing at the top or bottom.", "review pack")
    gap = wb.create_sheet("Official_Gap", 0)
    r = 1

    def put(*vals, bold=False, fill=None, link=None):
        nonlocal r
        for j, v in enumerate(vals, 1):
            c = gap.cell(r, j, v)
            if bold:
                c.font = BOLD
            if fill is not None and v is not None:
                c.fill = fill
        r += 1

    put(f"Review pack - AC {ac} {off['name']}", bold=True)
    put(f"Source PDF: {row['file']}  |  produced by {entry['produced_by']}  |  made {datetime.now():%Y-%m-%d %H:%M}")
    put(f"Class: {kind}. {advice}", bold=True)
    put("Nothing in the Form20 sheet was changed except the highlights. Correct cells there, then run "
        "python batch/recheck_reviewed.py <this file>.")
    r += 1
    put("1. Column totals against the official 2024 EVM totals", bold=True)
    put("Form20 column", "Official candidate (matched by rank)", "Sheet total", "Official total", "Difference", "Off by %", bold=True, fill=GREY)
    for i, d, v in diffs:
        put(openpyxl.utils.get_column_letter(3 + i) + f" ({cand[i][0][:18]})", pairs[i][0], cand[i][1], v, d,
            round(100 * d / max(v, 1), 2), fill=GREEN if d == 0 else RED)
    nota_d = metrics["NOTA"] - off["nota"]
    swapped = nota_d != 0 and metrics["REJECTED"] == off["nota"]
    put("NOTA", "NOTA", metrics["NOTA"], off["nota"], nota_d, round(100 * nota_d / max(off["nota"], 1), 2),
        fill=GREEN if nota_d == 0 else RED)
    if swapped:
        put("The rejected and NOTA columns look swapped: the rejected total equals the official NOTA.")
    r += 1
    put("2. Where votes are probably missing", bold=True)
    put(f"Official total of the candidates {off_total}; sheet {sheet_total}; difference {sheet_total - off_total:+d}; "
        f"about {est_missing:+.1f} booths' worth ({len(booths)} booth rows, a full page holds {full}).")
    if 0.7 <= est_missing <= 1.6 and all(d <= 0 for _, d, _ in diffs):
        short = ", ".join(f"{pairs[i][0]} {-d}" for i, d, _ in diffs if d) + (f", NOTA {-nota_d}" if nota_d else "")
        put("If exactly one booth is missing, its votes would be (to compare with the scan, not to be typed in blindly): " + short)
    put("Page", "Rows found", "Full page", "First serial", "Last serial", "Flagged rows", "Auto-corrected", "Missing", "Go to", bold=True, fill=GREY)
    for p, rows in enumerate(pages):
        miss = plan.get(p, (0, 0))
        text = (f"{miss[0]} above, {miss[1]} below" if any(miss) else (f"{unknown[p]} at the top or bottom" if p in unknown else ""))
        if not rows:
            put(p + 1, 0, full, None, None, None, None, "no rows read on this page" if p else "", None, fill=BLUE if p else None)
            continue
        st = Counter(b["status"] for b in rows)
        put(p + 1, len(rows), full, rows[0]["serial"], rows[-1]["serial"], st["REVIEW"] + st["UNUSUAL"], st["AUTO_CORRECTED"],
            text, f'=HYPERLINK("#Form20!A{rows[0]["row"]}","row {rows[0]["row"]}")', fill=BLUE if text else None)
    r += 1
    put("3. Rows the extractor flagged", bold=True)
    put("Form20 row", "Page", "Row on page", "Serial", "Status", "Note", bold=True, fill=GREY)
    for b in flagged + auto[:200]:
        put(f'=HYPERLINK("#Form20!A{b["row"]}","row {b["row"]}")', b["page"], b["page_row"], b["serial"], b["status"], b["note"])
    if len(auto) > 200:
        put(f"... and {len(auto) - 200} more auto-corrected rows (yellow cells on the Form20 sheet).")
    for col, width in zip("ABCDEFGHI", (30, 34, 14, 14, 14, 14, 16, 28, 14)):
        gap.column_dimensions[col].width = width
    gap.sheet_properties.tabColor = "9DC3E6"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ac}_review.xlsx"
    wb.save(path)
    entry["review_file"] = f"review/{path.name}"
    return entry


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build review packs for converted ACs that do not match the official totals.")
    ap.add_argument("--ac", help="comma-separated AC numbers")
    ap.add_argument("--all", action="store_true", help="a pack for every converted AC, however far off")
    ap.add_argument("--max-off", type=float, default=0.10, help="largest column error (share) that gets a pack")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--queue-dir", default=str(QUEUE_DIR), help="folder with conversion_ledger.csv (default: queue/)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    official = load_official()
    ledger = {}
    queue_dir = Path(args.queue_dir)
    for r in read_csv(queue_dir / "conversion_ledger.csv"):
        ledger.setdefault(int(r["ac"]), []).append(r)
    status = {int(r["ac"]): r for r in read_csv(queue_dir / "priority_180_status.csv")}
    acs = sorted(int(a) for a in args.ac.split(",")) if args.ac else sorted(
        ac for ac, r in status.items() if r["state"].startswith("CONVERTED"))
    out = Path(args.out)
    entries = []
    for ac in acs:
        e = build_pack(ac, ledger.get(ac, []), official, out, 9.99 if args.all else args.max_off)
        if e:
            entries.append(e)
            print(f"AC {ac:>3}: {e['class']:<15} worst column {e['worst_column_off_pct']:>6}% | exact {e['columns_exact']:>6} | "
                  f"about {e['estimated_missing_booths']:>5} booths missing | {e['review_file'] or '(no pack: too far off)'}")
    if entries:
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "REVIEW_INDEX.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(entries[0].keys()))
            w.writeheader()
            w.writerows(entries)
        print(dict(Counter(e["class"] for e in entries)), "->", out / "REVIEW_INDEX.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
