"""Command line:  python -m form20 <pdf-or-folder> [--out DIR] [--candidates CSV] [--no-crops]"""
import argparse
import csv
import sys
from pathlib import Path

from .export import METRICS, export_workbook
from .pipeline import DEFAULT_CANDIDATES, process_pdf


def main(argv=None):
    ap = argparse.ArgumentParser(prog="form20", description="Convert scanned Form 20 result sheets (PDF) to Excel.")
    ap.add_argument("input", help="a PDF file, or a folder of PDFs")
    ap.add_argument("--out", default="data/output", help="output folder (default: data/output)")
    ap.add_argument("--candidates", default=str(DEFAULT_CANDIDATES), help="reviewed candidate-name mapping CSV")
    ap.add_argument("--no-crops", action="store_true", help="do not save scan crops for the review queue")
    args = ap.parse_args(argv)

    src = Path(args.input)
    pdfs = sorted(src.glob("*.pdf")) if src.is_dir() else [src]
    if not pdfs:
        print("no PDF files found", file=sys.stderr)
        return 1
    out = Path(args.out)
    summary = []
    for pdf in pdfs:
        res = process_pdf(pdf, candidates_csv=args.candidates)
        path = export_workbook(res, pdf, out, with_crops=not args.no_crops)
        counts = {s: sum(1 for r in res.rows if r.status == s) for s in ("OK", "AUTO_CORRECTED", "UNUSUAL", "REVIEW")}
        print(f"-> {path}  rows={len(res.rows)} {counts} time={res.seconds:.0f}s")
        summary.append((res, counts))

    if len(pdfs) > 1:
        with open(out / "Form20_all_files_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["file", "segment", "electors", "rows", "OK", "AUTO_CORRECTED", "UNUSUAL", "REVIEW", "column_totals_match"])
            for res, c in summary:
                w.writerow([res.pdf, f"{res.meta.get('segment_no')}-{res.meta.get('segment_name')}", res.meta.get("electors"),
                            len(res.rows), c["OK"], c["AUTO_CORRECTED"], c["UNUSUAL"], c["REVIEW"],
                            all(x[3] for x in res.checks) if res.checks else False])
    return 0


if __name__ == "__main__":
    sys.exit(main())
