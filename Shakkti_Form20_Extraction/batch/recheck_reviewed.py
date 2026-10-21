"""Re-check corrected review packs against the official totals, and file the ones that now match.

    python batch/recheck_reviewed.py data/2024/review/47_review.xlsx [more packs]     # report only
    python batch/recheck_reviewed.py --accept data/2024/review/47_review.xlsx          # also file matching packs

The column totals are recomputed from the booth rows of the pack's Form20 sheet (so corrected cells count). A pack
whose every candidate column and NOTA equal the official 2024 EVM totals is VERIFIED. With --accept it is written to
data/2024/converted/<AC>.xlsx in the same layout as the other converted files, and its MANIFEST.csv row is updated.
A booth row added by hand needs a page number in the Source_Page column to be counted.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from queue_common import REPO_ROOT  # noqa: E402
from review_common import column_sums, read_form20  # noqa: E402
from stage_verified import assign_names, build_workbook  # noqa: E402
from verify_official import compare, load_official  # noqa: E402

CONVERTED = REPO_ROOT / "data" / "2024" / "converted"


def recheck(path, official):
    """(ac, comparison dict, form) for one pack."""
    ac = int(re.match(r"(\d+)", Path(path).name).group(1))
    form = read_form20(path)
    cand, metrics = column_sums(form)
    return ac, compare(cand, metrics, official[ac]), form


def accept(ac, path, form, chk, official, converted=CONVERTED):
    """Write the legacy-layout workbook of a verified pack and update the manifest."""
    cand, _ = column_sums(form)
    sums = [v for _, v in cand]
    names = assign_names(form["labels"], sums, official[ac]["candidates"])
    renumber = any(b["serial"] is None for b in form["booths"])          # a booth added by hand has no serial yet
    booths = [((i + 1) if renumber else b["serial"], (i + 1) if renumber and b["ps_no"] is None else b["ps_no"],
               list(b["cands"]), {"TOTAL_VALID": b["valid"], "REJECTED": b["rejected"], "NOTA": b["nota"],
                                  "TOTAL": b["total"], "TENDERED": b["tendered"]}) for i, b in enumerate(form["booths"])]
    out = Path(converted) / f"{ac}.xlsx"
    build_workbook(ac, Path(path).name, form["labels"], booths, names, official[ac], out,
                   swap_nota=chk["nota_swapped"] == "yes", verified=True,
                   note="reviewed by a person: cells corrected in the review pack")
    manifest = Path(converted) / "MANIFEST.csv"
    if manifest.exists():
        with open(manifest, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
            fields = rows[0].keys() if rows else []
        for r in rows:
            if int(r["ac"]) == ac:
                r.update(status="VERIFIED", output_file=f"converted/{ac}.xlsx", how_produced="read by OCR, corrected by a person in a review pack",
                         check="candidate columns and NOTA equal the official 2024 totals", note_or_reason="")
        with open(manifest, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(fields))
            w.writeheader()
            w.writerows(rows)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Re-check corrected review packs against the official totals.")
    ap.add_argument("packs", nargs="+")
    ap.add_argument("--accept", action="store_true", help="file the packs that now match into data/2024/converted/")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    official = load_official()
    for p in args.packs:
        ac, chk, form = recheck(p, official)
        print(f"AC {ac}: {chk['verdict']} - {chk['matched']}/{chk['cols_official']} candidate columns exact, NOTA "
              f"{chk['nota_sheet']} vs official {chk['nota_official']}" + (f"\n    still off: {chk['detail']}" if chk["detail"] else ""))
        if chk["verdict"] == "FULL" and args.accept:
            print("    filed ->", accept(ac, p, form, chk, official))
    return 0


if __name__ == "__main__":
    sys.exit(main())
