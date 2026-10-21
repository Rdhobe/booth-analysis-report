"""Status of the 180 ACs in data/2024/PDF/excel_pdf_map.md (the convert queue), with a plain-language reason for each
one that is not done.

    python batch/priority_status.py            # prints the summary, writes queue/priority_180_status.csv

DONE = every candidate column and NOTA equal the official 2024 totals. Everything else is pending, with the likeliest
cause worked out from the ledger and from how far the workbook's column sums are from the official ones.
AC 109 in the md is really AC 190 (the file 109Eng.pdf is the Lambhua sheet), so it is counted as 190.
"""
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from queue_common import DEFAULT_DATA_ROOT, QUEUE_DIR, ac_of, read_csv  # noqa: E402
from verify_official import check_workbook, load_official, sheet_sums  # noqa: E402

FIELDS = ["ac", "group", "pdf_files", "state", "reason"]
GROUPS = (("Eng single-file", "1. Eng"), ("Hin single-file", "2. Hin"), ("Duplicate PDFs", "3. Duplicate"))


def md_queue(md_path):
    text = Path(md_path).read_text(encoding="utf-8")
    out = {}
    for group, title in GROUPS:
        m = re.search(r"### " + re.escape(title) + r".*?\n(.*?)(?=\n###|\n## )", text, re.S)
        for a in {int(x) for x in re.findall(r"\b\d+\b", m.group(1))}:
            out[190 if a == 109 else a] = group
    return out


def converted_reason(best, source=""):
    verdict, matched, ratio, chk = best
    if source == "text layer" and abs(ratio - 1) <= 0.005:
        return ("Read exactly from the PDF's text; differs from the official totals by a few votes "
                "(a typo in the sheet or in the official data)")
    if matched and chk["cols_sheet"] == chk["cols_official"] and abs(ratio - 1) <= 0.03:
        return "Nearly right: a few digits misread (totals within 3% of official)"
    if chk["cols_sheet"] != chk["cols_official"] and chk["cols_sheet"] > 2 * chk["cols_official"]:
        return "PDF holds several constituencies together (must be split) or the grid is over-detected"
    if 1.9 <= ratio <= 4.1 and abs(ratio - round(ratio)) < 0.08:
        return f"Sheet's own total rows counted as booths (x{round(ratio)})"
    if ratio < 0.9:
        return f"Rows/pages missed: only {int(ratio * 100)}% of the votes captured (table not found on some pages)"
    if ratio > 1.1:
        return f"Extra/duplicated rows or wrong columns ({int(ratio * 100)}% of official votes)"
    return "Digits misread on many rows (totals do not match)"


def failed_reason(errors):
    if "read as printed" in errors:
        return "Table found but not read reliably (unusual layout, or a scan too poor to read)"
    if "columns detected" in errors or "no table lines" in errors:
        return "Could not find the table's columns (scan lines too faint/uneven)"
    return "Extractor error"


def build(data_root=DEFAULT_DATA_ROOT, queue_dir=QUEUE_DIR):
    group_of = md_queue(Path(data_root) / "PDF" / "excel_pdf_map.md")
    official = load_official()
    by_ac = defaultdict(list)
    for r in read_csv(Path(queue_dir) / "conversion_ledger.csv"):
        by_ac[int(r["ac"])].append(r)
    review = {int(r["ac"]): r for r in read_csv(Path(queue_dir) / "to_review.csv") if r["ac"]}
    overrides = {r["file"]: int(r["ac"]) for r in read_csv(Path(queue_dir) / "ac_overrides.csv")}
    pdfs = defaultdict(list)
    for p in sorted((Path(data_root) / "PDF").glob("*.pdf")):
        ac = overrides.get(p.name, ac_of(p.name))
        if ac:
            pdfs[ac].append(p.name)
    rows = []
    for ac in sorted(group_of):
        best = None
        for r in by_ac.get(ac, []):
            if r["status"] == "DONE" and Path(r["xlsx"]).exists():
                chk = check_workbook(ac, r["xlsx"], official)
                cand, _, _ = sheet_sums(r["xlsx"])
                ov = sum(v for _, _, v in official[ac]["candidates"])
                item = (chk["verdict"], int(chk["matched"] or 0), sum(v for _, v in cand) / ov if ov else 0, chk)
                if best is None or item[0] == "FULL" or (best[0] != "FULL" and item[1] > best[1]):
                    best = item
        if best and best[0] == "FULL":
            state, reason = "DONE (verified)", "All candidate columns and NOTA match the official 2024 totals"
        elif best:
            source = next((x.get("source", "") for x in by_ac.get(ac, []) if x["status"] == "DONE"), "")
            state, reason = "CONVERTED, NOT VERIFIED", converted_reason(best, source)
        elif ac in by_ac:
            state, reason = "FAILED", failed_reason(" ".join(r["error"] for r in by_ac[ac]))
        elif ac in review and review[ac]["category"] == "UNSUPPORTED_LAYOUT":
            state, reason = "ON HOLD", "Different form layout (portrait page) the tool cannot read yet"
        else:
            state, reason = "NOT ATTEMPTED", "Not run yet"
        rows.append({"ac": ac, "group": group_of[ac], "pdf_files": "; ".join(pdfs.get(ac, [])), "state": state,
                     "reason": reason})
    for sp in read_csv(Path(queue_dir) / "split_report.csv"):       # ACs delivered by splitting a multi-constituency PDF
        for r in rows:
            if r["ac"] == int(sp["ac"]) and sp["verdict"] == "FULL" and not r["state"].startswith("DONE"):
                r["state"], r["reason"] = "DONE (verified)", f"Split out of {sp['source']}; every column equals the official total"
    return rows


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = build()
    out = QUEUE_DIR / "priority_180_status.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} ACs in the md convert queue -> {out}")
    print(dict(Counter(r["state"] for r in rows)))
    for state in ("CONVERTED, NOT VERIFIED", "FAILED", "ON HOLD", "NOT ATTEMPTED"):
        sub = [r for r in rows if r["state"] == state]
        if sub:
            print(f"== {state}: {len(sub)}")
            for k, v in Counter(re.sub(r"x\d|\d+%", "N", r["reason"]) for r in sub).most_common():
                print(f"   {v:>3}  {k}")
    for group, _ in GROUPS:
        sub = [r for r in rows if r["group"] == group]
        print(f"{group}: {len(sub)} total, {sum(r['state'].startswith('DONE') for r in sub)} done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
