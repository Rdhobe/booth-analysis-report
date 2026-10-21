"""Collect labelled digit crops from the scans that fail, to train the digit reader on the scan quality it must handle.

    python batch/harvest_noisy.py --out data/interim/harvest_noisy [--pages 6] [--workers 3]

For each pending file (queue/priority_180_status.csv, digit-problem reasons) the first few pages are run through the
extractor with the identifier-column count fixed from the official candidate count, the neural reader switched off
(so the labels cannot reinforce its own mistakes) and no early abort. Rows the sheet's arithmetic confirms give
labelled cell crops (see pipeline.harvest_crops). Nothing is written to the ledger or the PDF/EXCEL folders.
"""
import argparse
import csv
import os
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from queue_common import DEFAULT_DATA_ROOT, QUEUE_DIR, TOOL_DIR  # noqa: E402

DIGIT_REASONS = ("Digits misread", "Table found but digits", "Nearly right", "Sheet's own total rows",
                 "Extra/duplicated rows")
SKIP_ACS = {137, 141}      # several constituencies in one PDF


def one(job):
    import cv2
    cv2.setNumThreads(1)
    from form20.pipeline import process_pdf
    from verify_official import load_official

    pdf, ac, pages = job
    try:
        n_off = len(load_official()[ac]["candidates"])
        res = process_pdf(pdf, progress=lambda m: None, expected_cols={n_off + 5 + k for k in (1, 2, 3)},
                          expected_candidates=n_off, limit_pages=pages)
        return Path(pdf).name, res.meta.get("harvested_crops", 0), ""
    except Exception as e:
        return Path(pdf).name, 0, f"{type(e).__name__}: {e}"[:80]


def pending_jobs(pdf_dir, pages):
    rows = list(csv.DictReader(open(QUEUE_DIR / "priority_180_status.csv", encoding="utf-8-sig")))
    jobs = []
    for r in rows:
        if r["state"] == "DONE (verified)" or int(r["ac"]) in SKIP_ACS:
            continue
        if not any(r["reason"].startswith(k) for k in DIGIT_REASONS):
            continue
        for f in r["pdf_files"].split("; "):
            if f:
                jobs.append((str(Path(pdf_dir) / f), int(r["ac"]), pages))
    return jobs


def main(argv=None):
    ap = argparse.ArgumentParser(description="Harvest labelled digit crops from the failing scans.")
    ap.add_argument("--out", default=str(TOOL_DIR / "data" / "interim" / "harvest_noisy"))
    ap.add_argument("--pdf-dir", default=str(DEFAULT_DATA_ROOT / "PDF"))
    ap.add_argument("--pages", type=int, default=6)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    Path(args.out).mkdir(parents=True, exist_ok=True)
    os.environ.update({"FORM20_HARVEST_DIR": args.out, "FORM20_READER": "off", "OMP_THREAD_LIMIT": "1",
                       "FORM20_OCR_WORKERS": "2"})
    jobs = pending_jobs(args.pdf_dir, args.pages)
    print(f"{len(jobs)} files, first {args.pages} pages each -> {args.out}", flush=True)
    total = 0
    with Pool(args.workers) as pool:
        for i, (name, n, err) in enumerate(pool.imap_unordered(one, jobs), 1):
            total += n
            print(f"[{i}/{len(jobs)}] {name}: {n} cells {err}", flush=True)
    print(f"done: {total:,} labelled cells")
    return 0


if __name__ == "__main__":
    sys.exit(main())
