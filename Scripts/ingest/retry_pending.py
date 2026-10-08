"""Retry only unfinished files: REVIEW + FAILED rows from the bulk report.

Reads data/2024/bulk_convert_report.csv (or --report), reprocesses ONLY rows
whose status is REVIEW or FAILED (override with --status), and merges
the new results back into the same CSV. Files already OK / SKIPPED /
LEGACY_SKIP / SCANNED / COMPLEX_SKIP are never touched, so nothing is
reconverted twice.

Usage:
  python Scripts/retry_pending.py
  python Scripts/retry_pending.py --report data/2024/bulk_convert_report.csv
  python Scripts/retry_pending.py --status REVIEW,FAILED --only "Shamli/*"
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from Scripts.ingest.bulk_convert_form20 import convert_one  # noqa: E402

DEFAULT_STATUS = {"REVIEW", "FAILED"}


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Retry only REVIEW/FAILED files")
    ap.add_argument("--report", default="data/2024/bulk_convert_report.csv")
    ap.add_argument("--status", default="REVIEW,FAILED",
                    help="comma-separated statuses to retry")
    ap.add_argument("--only", action="append", default=[],
                    help="repeatable glob on rel path to limit retry set")
    args = ap.parse_args(argv)

    report = Path(args.report)
    if not report.exists():
        print(f"ERROR: report not found: {report}", flush=True)
        return 2
    want = {s.strip().upper() for s in args.status.split(",") if s.strip()}
    with open(report, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"REPORT {report}: {len(rows)} rows", flush=True)

    todo = [r for r in rows if (r.get("status") or "").upper() in want]
    if args.only:
        def _match(rel, pat):
            return (fnmatch.fnmatch(rel, pat)
                    or fnmatch.fnmatch(rel.replace("\\", "/"), pat))
        todo = [r for r in todo
                if any(_match(r.get("rel", ""), p) for p in args.only)]
    print(f"RETRY-SET statuses={sorted(want)} only={args.only or 'all'} "
          f"-> {len(todo)} files", flush=True)
    for r in todo[:40]:
        print(f"  - {r.get('rel')} [{r.get('status')}]", flush=True)
    if not todo:
        print("Nothing to retry.", flush=True)
        return 0

    by_rel = {r.get("rel"): r for r in rows}
    t_all = time.time()
    for i, r in enumerate(todo, start=1):
        pdf = Path(r["pdf"])
        print(f"[{i}/{len(todo)}] RETRY {r.get('rel')}", flush=True)
        res = convert_one(pdf, skip_existing=False)
        res["rel"] = r.get("rel")
        by_rel[r.get("rel")].update({
            "pages": res.get("pages", ""), "ncands": res.get("ncands", ""),
            "booths": res.get("booths", ""), "status": res.get("status", ""),
            "xlsx": res.get("xlsx", ""), "error": res.get("error", ""),
            "secs": res.get("secs", ""),
        })
        print(f"[{i}/{len(todo)}] DONE  {r.get('rel')}: "
              f"{r.get('status')} -> {res['status']} ({res.get('secs', 0):.1f}s)",
              flush=True)
        if res["status"] == "OK":
            stale = pdf.with_name(pdf.stem + ".REVIEW.xlsx")
            if stale.exists():
                try:
                    stale.unlink()
                    print(f"  swept stale {stale.name}", flush=True)
                except Exception:
                    pass
    with open(report, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "pdf", "pages", "ncands",
                                          "booths", "status", "xlsx",
                                          "error", "secs"])
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print("AFTER: " + str(dict(Counter(r.get("status", "?") for r in rows))),
          flush=True)
    print(f"REPORT updated -> {report}  elapsed={time.time() - t_all:.0f}s",
          flush=True)
    left = sum(1 for r in rows if (r.get("status") or "").upper() in want)
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
