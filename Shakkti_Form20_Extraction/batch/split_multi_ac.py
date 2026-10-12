"""Split a PDF that holds several assembly constituencies (one whole Lok Sabha constituency) into one workbook per AC.

    python batch/split_multi_ac.py 137Eng.pdf 141Eng.pdf [--out data/output/split_acs]

Some PDFs (137Eng.pdf, 141Eng.pdf) contain the Form 20 of every assembly segment of a Lok Sabha constituency, one after
the other, so their booth rows add up to about five times one AC's votes. The official file says which ACs share a
Lok Sabha constituency and what each polled, so the row sequence is cut where the running column sums reach each AC's
official running total, and each part is checked against its own AC. Parts that match the official totals exactly are
marked verified and written to data/output/staged_excel/ with the other verified files; the others go to
data/output/split_acs/, clearly marked as not verified, with how far they are off.

Needs the PDF to have been converted already (queue/conversion_ledger.csv). Writes queue/split_report.csv.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from queue_common import QUEUE_DIR, TOOL_DIR, read_csv  # noqa: E402
from stage_verified import assign_names, build_workbook, read_tidy  # noqa: E402
from verify_official import OFFICIAL_CSV, compare, load_official  # noqa: E402

DEFAULT_OUT = TOOL_DIR / "data" / "output" / "split_acs"          # parts that do not verify
VERIFIED_OUT = TOOL_DIR / "data" / "output" / "staged_excel"       # parts that match the official totals exactly
MIN_BOOTHS = 50       # the cut for an AC is searched at least this many rows after the previous one


def acs_of_same_pc(ac, path=OFFICIAL_CSV, state="Uttar Pradesh"):
    """AC numbers (ascending) that share a Lok Sabha constituency with `ac`."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = csv.reader(f)
        next(rows)
        col = {h: i for i, h in enumerate(next(rows))}
        pc_of = {}
        for r in rows:
            if r and r[0].strip().lower() == state.lower():
                pc_of[int(r[col["AC NO"]])] = int(r[col["PC NO"]])
    return sorted(a for a, pc in pc_of.items() if pc == pc_of[ac])


def find_cuts(vectors, acs, official):
    """vectors: per-booth candidate votes (list of lists, sheet column order). Returns the start index of every AC
    block after the first (len(acs) - 1 cut positions), found where the running column sums come closest to the
    official running totals. Sheet columns are lined up with the official candidates by the rank of the PC totals."""
    nc = len(vectors[0])
    names = [n for n, _, _ in official[acs[0]]["candidates"]]
    per_ac = [[{n: v for n, _, v in official[a]["candidates"]}.get(n, 0) for n in names] for a in acs]
    pc_tot = [sum(p[k] for p in per_ac) for k in range(nc)]
    sheet_tot = [sum(v[j] for v in vectors) for j in range(nc)]
    colmap = dict(zip(sorted(range(nc), key=lambda j: sheet_tot[j]), sorted(range(nc), key=lambda k: pc_tot[k])))
    prefix = [[0] * nc]
    for v in vectors:
        prefix.append([prefix[-1][j] + v[j] for j in range(nc)])
    cuts, last, run = [], 0, [0] * nc
    for p in per_ac[:-1]:
        run = [run[k] + p[k] for k in range(nc)]
        best = min(range(last + MIN_BOOTHS, len(vectors)),
                   key=lambda i: sum(abs(prefix[i][j] - run[colmap[j]]) for j in range(nc)))
        cuts.append(best)
        last = best
    return cuts


def exact_columns(sums, ac_official):
    """How many of the block's candidate column sums equal an official total (matched by value)."""
    free = list(v for _, _, v in ac_official["candidates"])
    n = 0
    for t in sums:
        if t in free:
            free.remove(t)
            n += 1
    return n


def refine_cuts(vectors, acs, official, cuts, window=25):
    """Move each cut up to `window` rows to the position where the block before it has the most columns that equal the
    official totals exactly (the first estimate only follows the running sums, which are a few rows out when digits
    are misread)."""
    nc = len(vectors[0])
    bounds = [0] + list(cuts) + [len(vectors)]
    for i in range(1, len(bounds) - 1):
        best, best_pos = -1, bounds[i]
        for pos in range(max(bounds[i - 1] + MIN_BOOTHS, bounds[i] - window), min(len(vectors) - 1, bounds[i] + window) + 1):
            blk = vectors[bounds[i - 1]:pos]
            n = exact_columns([sum(v[j] for v in blk) for j in range(nc)], official[acs[i - 1]])
            if n > best:
                best, best_pos = n, pos
        bounds[i] = best_pos
    return bounds[1:-1]


def split(pdf_name, ledger, official, out_dir):
    row = next(r for r in ledger if r["file"] == pdf_name and r["status"] == "DONE")
    ac0 = int(row["ac"])
    acs = acs_of_same_pc(ac0)
    labels, booths, _ = read_tidy(row["xlsx"])
    nc = len(labels)
    vectors = [[v or 0 for v in b[2]] for b in booths]
    cuts = refine_cuts(vectors, acs, official, find_cuts(vectors, acs, official))
    bounds = [0] + cuts + [len(booths)]
    results = []
    for i, ac in enumerate(acs):
        part = booths[bounds[i]:bounds[i + 1]]
        sums = [sum(b[2][j] or 0 for b in part) for j in range(nc)]
        cand = [(labels[j], sums[j]) for j in range(nc)]
        metrics = {"NOTA": sum(b[3].get("NOTA") or 0 for b in part), "REJECTED": sum(b[3].get("REJECTED") or 0 for b in part)}
        chk = compare(cand, metrics, official[ac])
        names = assign_names(labels, sums, official[ac]["candidates"])
        out = (VERIFIED_OUT if chk["verdict"] == "FULL" else Path(out_dir)) / f"{ac}.xlsx"
        renumbered = [(n + 1, ps, c, t) for n, (_, ps, c, t) in enumerate(part)]       # serials restart at 1 in each AC
        build_workbook(ac, f"{pdf_name} (part {i + 1} of {len(acs)})", labels, renumbered, names, official[ac], out,
                       swap_nota=chk["nota_swapped"] == "yes", verified=chk["verdict"] == "FULL",
                       note=f"{chk['matched']} of {chk['cols_official']} candidate columns match the official EVM totals")
        results.append({"ac": ac, "source": pdf_name, "booths": len(part), "verdict": chk["verdict"],
                        "columns_exact": f"{chk['matched']}/{chk['cols_official']}", "file": str(out)})
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Split multi-constituency PDFs into one workbook per AC.")
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    official = load_official()
    ledger = read_csv(QUEUE_DIR / "conversion_ledger.csv")
    rows = []
    for pdf in args.pdfs:
        for r in split(pdf, ledger, official, args.out):
            rows.append(r)
            print(f"AC {r['ac']:>3} from {r['source']}: {r['booths']} booths, {r['verdict']} ({r['columns_exact']} columns exact)")
    with open(QUEUE_DIR / "split_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["ac", "source", "booths", "verdict", "columns_exact", "file"])
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
