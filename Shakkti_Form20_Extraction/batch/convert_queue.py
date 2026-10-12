"""Batch OCR converter: run the Form 20 extractor over queue/to_convert.csv.

    python batch/convert_queue.py --dry-run               # what would run and how long
    python batch/convert_queue.py --limit 3               # pilot: the 3 smallest tier A files
    python batch/convert_queue.py                         # all of tier A
    python batch/convert_queue.py --tier A,B              # tiers A and B
    python batch/convert_queue.py --workers 4             # four PDFs at the same time
    python batch/convert_queue.py --ac 8,9,10 --redo      # chosen ACs, even if already done

Resumable: every finished PDF is written to queue/conversion_ledger.csv straight away, and files already DONE
are skipped on the next run (FAILED ones only with --retry-failed). One PDF that crashes is logged and skipped.
Workbooks go to data/output/2024/ (git-ignored); the PDF and EXCEL folders are never touched.
After each file queue/run_summary.md sorts every PDF into CLEAN / FLAGGED / FAILED, and
queue/review_after_conversion.csv lists the flagged and failed ones.
"""
import argparse
import os
import re
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from queue_common import DEFAULT_DATA_ROOT, QUEUE_DIR, SEC_PER_PAGE, TOOL_DIR, read_csv, write_csv  # noqa: E402

DEFAULT_OUT = TOOL_DIR / "data" / "output" / "2024"
LEDGER_FIELDS = ["ac", "file", "tier", "outcome", "status", "pages", "rows", "exact", "ok", "auto_corrected", "unusual", "review",
                 "totals", "totals_source", "source", "repaired_rows", "page_errors", "segment_read", "ac_check", "names",
                 "needs_review", "review_reason",
                 "seconds", "xlsx", "error", "finished_at"]
MIN_CANDIDATES = 4     # fewer candidate columns than this means grid detection failed (another Form 20 layout)
LOW_EXACT_READ = 0.5   # below this share of OK rows the layout is probably not one the extractor supports
BLANK = {"rows": 0, "exact": 0, "ok": 0, "auto_corrected": 0, "unusual": 0, "review": 0, "totals": "", "totals_source": "", "source": "", "repaired_rows": 0, "page_errors": 0,
         "segment_read": "", "ac_check": "", "names": ""}


class LayoutNotRecognised(Exception):
    pass


_PASS1_LINE = re.compile(r"columns=(-?\d+) candidates=(-?\d+)")
_PAGE_LINE = re.compile(r"page (\d+)/\d+: (\d+) rows, (\d+) read as printed")
GATE_MIN_PAGES, GATE_MIN_ROWS, GATE_MIN_PRINTED = 3, 40, 0.15   # early abort: samples read 80-95% as printed


def layout_gate(log):
    """Progress callback for process_pdf: logs, and stops the run early when it is clearly wasted.

    * right after pass 1 (table detection, about a sixth of the run time) if the file-wide column template implies
      too few candidates;
    * after a few pages if almost no row is read as printed - the layout is not one the extractor handles."""
    rows_seen = printed_seen = 0

    def progress(msg):
        nonlocal rows_seen, printed_seen
        log(msg)
        m = _PASS1_LINE.search(msg)
        if m and int(m.group(2)) < MIN_CANDIDATES:
            raise LayoutNotRecognised(f"{m.group(1)} table columns detected -> {m.group(2)} candidates; "
                                      "not a layout the extractor supports")
        m = _PAGE_LINE.search(msg)
        if m:
            rows_seen += int(m.group(2))
            printed_seen += int(m.group(3))
            if (int(m.group(1)) >= GATE_MIN_PAGES and rows_seen >= GATE_MIN_ROWS
                    and printed_seen < GATE_MIN_PRINTED * rows_seen):
                raise LayoutNotRecognised(f"only {printed_seen} of {rows_seen} rows read as printed after "
                                          f"{m.group(1)} pages; not a layout the extractor supports")
    return progress


def select_rows(rows, tiers, acs=None, done=(), failed=(), retry_failed=False, max_pages=None, limit=None):
    """Queue rows to run now, in priority order."""
    picked = []
    for r in sorted(rows, key=lambda r: int(r["priority"])):
        if r["tier"] not in tiers:
            continue
        if acs and int(r["ac"]) not in acs:
            continue
        if r["file"] in done or (r["file"] in failed and not retry_failed):
            continue
        if max_pages and int(r["pages"]) > max_pages:
            continue
        picked.append(r)
    return picked[:limit] if limit else picked


def summarize(res, expected_ac):
    """Ledger columns from a form20 FileResult."""
    from form20.validate import read_as_printed
    counts = Counter(r.status for r in res.rows)
    seg = res.meta.get("segment_no")
    if res.hindi:
        ac_check = "not checked (Hindi header)"      # Hindi titles do not reliably carry the AC number
    elif seg is None:
        ac_check = "unread"
    else:
        ac_check = "ok" if seg == expected_ac else "MISMATCH"
    exact = sum(read_as_printed(r, res.n_cands) for r in res.rows)
    totals = "not read" if not res.checks else ("match" if all(c[3] for c in res.checks) else "DIFFER")
    return {
        "rows": len(res.rows), "exact": exact, "ok": counts["OK"], "auto_corrected": counts["AUTO_CORRECTED"],
        "unusual": counts["UNUSUAL"], "review": counts["REVIEW"], "totals": totals,
        "totals_source": res.meta.get("totals_source", "printed"), "source": res.meta.get("source", "ocr"),
        "repaired_rows": res.meta.get("official_repair_rows", 0),
        "page_errors": len(res.page_errors),
        "segment_read": f"{seg}-{res.meta.get('segment_name')}" if seg is not None else "",
        "ac_check": ac_check,
        "names": "OCR-unverified" if "UNVERIFIED" in res.names_source else "verified",
    }


def review_reason(e):
    """Why a finished entry needs a person to look ('' if it does not). Works on ints or CSV strings."""
    if e["status"] == "FAILED":
        return "conversion failed: " + str(e.get("error", ""))
    why = []
    if int(e["rows"]) == 0:
        why.append("no rows read")
    if int(e["rows"]) and int(e["exact"]) < LOW_EXACT_READ * int(e["rows"]):   # samples read 92-94% exactly
        why.append(f"only {100 * int(e['exact']) // int(e['rows'])}% of rows read as printed - layout probably unsupported")
    if int(e["review"]):
        why.append(f"{e['review']} REVIEW rows")
    if e["totals"] == "DIFFER":
        why.append("column totals differ from the printed totals")
    elif e["totals"] == "not read":
        why.append("printed totals row not read")
    if int(e["page_errors"]):
        why.append(f"{e['page_errors']} pages without a table")
    if e["ac_check"] == "MISMATCH":
        why.append(f"page header says {e['segment_read']}")
    return "; ".join(why)


def _new_entry(row):
    return {"ac": row["ac"], "file": row["file"], "tier": row["tier"], "pages": row["pages"], **BLANK}


def _finish(entry, t0):
    entry["seconds"] = round(time.time() - t0)
    entry["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["review_reason"] = review_reason(entry)
    entry["needs_review"] = "yes" if entry["review_reason"] else "no"
    return entry


def failed_entry(row, exc):
    entry = _new_entry(row)
    entry.update(status="FAILED", xlsx="", error=f"{type(exc).__name__}: {exc}"[:300])
    return _finish(entry, time.time())


_OFFICIAL = {}


def official_for(ac):
    """Official EVM totals for one assembly segment, {"candidates": [votes], "nota": n}, or None."""
    if not _OFFICIAL:
        from verify_official import load_official
        _OFFICIAL.update(load_official())
    e = _OFFICIAL.get(ac)
    return {"candidates": [v for _, _, v in e["candidates"]], "nota": e["nota"]} if e else None


def official_score(res, off):
    """(verdict, candidate columns equal to an official total) of a finished read, counted the way verify_official does."""
    from verify_official import compare
    nc = res.n_cands

    def total(i):
        return sum(r.values[i] for r in res.rows if r.values[i] is not None)
    chk = compare([(i, total(i)) for i in range(nc)], {"NOTA": total(nc + 2), "REJECTED": total(nc + 1)},
                  {"candidates": [(None, None, v) for v in off["candidates"]], "nota": off["nota"]})
    return chk["verdict"], chk["matched"] + (chk["nota_sheet"] == chk["nota_official"] or chk["nota_swapped"] == "yes")


def run_process_pdf(pdf, off, expected, log):
    """process_pdf with the layout gate. A PDF with a text layer is read from it (exact, no OCR); if that read is
    refused or crashes, the PDF is read again by OCR as before. A text read that does not equal the official totals is
    no better than a guess (the layer of a scan can hold OCR errors, or lose a column), so the PDF is also read by OCR
    and the closer of the two is kept - the text read when they tie."""
    from form20.pipeline import DEFAULT_CANDIDATES, process_pdf
    used_text = []

    def attempt(text_layer):
        gate = layout_gate(log)

        def progress(msg):
            if "text layer found" in msg:
                used_text.append(True)
            gate(msg)
        res = process_pdf(pdf, candidates_csv=DEFAULT_CANDIDATES, progress=progress, official=off,
                          expected_cols=expected, text_layer=text_layer)    # official also fixes the id-column count
        if res.n_cands < MIN_CANDIDATES:   # fallback if the pass-1 log line ever changes format
            raise LayoutNotRecognised(f"only {res.n_cands} candidate columns detected")
        return res

    try:
        res = attempt(None)
    except Exception as exc:
        if not used_text:
            raise
        log(f"text layer read failed ({type(exc).__name__}: {exc}); reading the PDF by OCR instead")
        return attempt(False)
    if not (used_text and off):
        return res
    verdict, score = official_score(res, off)
    if verdict == "FULL":
        return res
    log(f"text layer read matches {score} of {len(off['candidates']) + 1} official totals; reading the PDF by OCR as well")
    try:
        by_ocr = attempt(False)
    except Exception as exc:
        log(f"OCR read failed ({type(exc).__name__}: {exc}); keeping the text layer read")
        return res
    ocr_verdict, ocr_score = official_score(by_ocr, off)
    log(f"OCR read matches {ocr_score} of {len(off['candidates']) + 1} official totals")
    return by_ocr if ocr_score > score else res


def convert_one(row, pdf_dir, out_dir, with_crops, log, use_official=False):
    from form20.export import export_workbook

    pdf = Path(pdf_dir) / row["file"]
    entry = _new_entry(row)
    t0 = time.time()
    try:
        off = official_for(int(row["ac"])) if use_official else None
        # table columns = identifier columns (1-3) + candidates + 5 total columns (NOTA counts as one of the 5 in layout A)
        expected = {len(off["candidates"]) + 5 + k for k in (1, 2, 3)} if off else None
        res = run_process_pdf(pdf, off, expected, log)
        path = export_workbook(res, pdf, out_dir, with_crops=with_crops)
        entry.update(status="DONE", xlsx=str(path), error="", **summarize(res, int(row["ac"])))
    except Exception as exc:  # one bad PDF must not stop a multi-hour batch
        log(traceback.format_exc())
        if isinstance(exc, StopIteration):   # process_pdf found no table lines on any page
            exc = LayoutNotRecognised("no table lines found on any page")
        entry.update(status="FAILED", xlsx="", error=f"{type(exc).__name__}: {exc}"[:300])
    return _finish(entry, t0)


def _convert_task(job):
    """One PDF with its own log file; top-level so that a worker process can run it."""
    row, pdf_dir, out_dir, with_crops, log_dir, use_official = job
    with open(Path(log_dir) / f"{row['file']}.log", "w", encoding="utf-8") as lf:
        def log(msg):
            lf.write(f"{datetime.now():%H:%M:%S} {msg}\n")
            lf.flush()
        return convert_one(row, pdf_dir, out_dir, with_crops, log, use_official)


def run_jobs(todo, workers, pdf_dir, out_dir, with_crops, log_dir, use_official=False):
    """Yield one ledger entry per PDF as it finishes (in queue order when single-process)."""
    jobs = [(r, str(pdf_dir), str(out_dir), with_crops, str(log_dir), use_official) for r in todo]
    if workers <= 1:
        for job in jobs:
            yield _convert_task(job)
        return
    # Several PDFs at once: split the cores between them instead of oversubscribing (set before the workers start).
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    os.environ.setdefault("FORM20_OCR_WORKERS", str(max(2, (os.cpu_count() or 8) // workers)))
    ex = ProcessPoolExecutor(max_workers=workers)
    try:
        futs = {ex.submit(_convert_task, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            try:
                entry = fut.result()
            except Exception as exc:   # a worker process died (e.g. out of memory)
                entry = failed_entry(futs[fut], exc)
            yield entry
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def outcome_of(e):
    """CLEAN: converted and every check passed; FLAGGED: converted but a person must look; FAILED: no workbook."""
    if e["status"] == "FAILED":
        return "FAILED"
    return "FLAGGED" if e["needs_review"] == "yes" else "CLEAN"


def render_summary(ledger, queue_rows):
    by = {"CLEAN": [], "FLAGGED": [], "FAILED": []}
    for r in sorted(ledger.values(), key=lambda r: int(r["ac"])):
        by[outcome_of(r)].append(r)
    pending = [r for r in queue_rows if r["file"] not in ledger]
    pend_a = [r for r in pending if r["tier"] == "A"]
    pend_b = [r for r in pending if r["tier"] == "B"]
    out = [
        "# Conversion run summary",
        "",
        f"Generated by `batch/convert_queue.py`, last updated {datetime.now():%Y-%m-%d %H:%M:%S}. Do not edit by hand.",
        "",
        "| Outcome | PDFs | Meaning |",
        "|---|---:|---|",
        f"| CLEAN | {len(by['CLEAN'])} | Converted; no REVIEW rows, column totals match the printed totals. "
        "Ready to file after a spot-check. Candidate names are still OCR'd unless the PDF is in `config/candidates.csv`. |",
        f"| FLAGGED | {len(by['FLAGGED'])} | Converted, but a person must check the workbook's `Review_Queue` sheet. |",
        f"| FAILED | {len(by['FAILED'])} | No usable workbook (layout not recognised or crash) - to be worked on afterwards. |",
        f"| Not run yet | {len(pending)} | tier A: {len(pend_a)}, tier B: {len(pend_b)} |",
        "",
        "## CLEAN",
        "",
        ", ".join(f"{r['ac']} ({r['file']}, {r['rows']} rows)" for r in by["CLEAN"]) or "none yet",
        "",
        "## FLAGGED - converted, needs a look",
        "",
    ]
    if by["FLAGGED"]:
        out += ["| AC | File | Rows | OK | Auto | Review | Totals | Why |", "|---|---|---:|---:|---:|---:|---|---|"]
        out += [f"| {r['ac']} | {r['file']} | {r['rows']} | {r['ok']} | {r['auto_corrected']} | {r['review']} | "
                f"{r['totals']} | {r['review_reason']} |" for r in by["FLAGGED"]]
    else:
        out.append("none yet")
    out += ["", "## FAILED - to work on afterwards", ""]
    if by["FAILED"]:
        out += ["| AC | File | Pages | Reason |", "|---|---|---:|---|"]
        out += [f"| {r['ac']} | {r['file']} | {r['pages']} | {r['error']} |" for r in by["FAILED"]]
    else:
        out.append("none yet")
    return "\n".join(out) + "\n"


def save_views(ledger, queue_dir, queue_rows=()):
    for r in ledger.values():
        r["outcome"] = outcome_of(r)
    rows = sorted(ledger.values(), key=lambda r: (r["tier"], int(r["ac"])))
    try:
        write_csv(queue_dir / "conversion_ledger.csv", LEDGER_FIELDS, rows)
        write_csv(queue_dir / "review_after_conversion.csv", LEDGER_FIELDS,
                  [r for r in rows if r["needs_review"] == "yes"])
        (queue_dir / "run_summary.md").write_text(render_summary(ledger, queue_rows), encoding="utf-8")
    except PermissionError:
        print("  (could not write the ledger - is it open in Excel? It will be rewritten after the next file)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert the queued scanned Form 20 PDFs to Excel (OCR).")
    ap.add_argument("--queue-dir", default=str(QUEUE_DIR), help="folder with to_convert.csv (default: queue/)")
    ap.add_argument("--pdf-dir", default=str(DEFAULT_DATA_ROOT / "PDF"), help="folder holding the PDFs")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="workbook folder (default: data/output/2024)")
    ap.add_argument("--tier", default="A", help="A, B, D, Q, a comma list such as 'A,B', or 'all' (default: A)")
    ap.add_argument("--ac", help="comma-separated AC numbers to run")
    ap.add_argument("--limit", type=int, help="run at most this many files")
    ap.add_argument("--max-pages", type=int, help="skip PDFs longer than this")
    ap.add_argument("--retry-failed", action="store_true", help="also re-run files that FAILED earlier")
    ap.add_argument("--redo", action="store_true", help="ignore the ledger: re-run even DONE files")
    ap.add_argument("--no-crops", action="store_true", help="skip scan crops for the review queue")
    ap.add_argument("--use-official", action="store_true",
                    help="settle uncertain rows against the official segment totals (marks the ledger totals_source)")
    ap.add_argument("--workers", type=int, default=1, help="PDFs converted at the same time (default: 1)")
    ap.add_argument("--dry-run", action="store_true", help="list what would run, then stop")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    queue_dir, pdf_dir, out_dir = Path(args.queue_dir), Path(args.pdf_dir), Path(args.out)
    rows = read_csv(queue_dir / "to_convert.csv")
    if not rows:
        print(f"{queue_dir / 'to_convert.csv'} is missing or empty - run batch/build_queue.py first", file=sys.stderr)
        return 1
    ledger = {r["file"]: r for r in read_csv(queue_dir / "conversion_ledger.csv")}
    done = {f for f, r in ledger.items() if r["status"] == "DONE" and r["xlsx"] and Path(r["xlsx"]).exists()}
    failed = {f for f, r in ledger.items() if r["status"] == "FAILED"}
    if args.redo:
        done, failed = set(), set()
    tiers = {"A", "B", "D", "Q"} if args.tier.lower() == "all" else {t.strip().upper() for t in args.tier.split(",")}
    acs = {int(a) for a in args.ac.split(",")} if args.ac else None
    todo = select_rows(rows, tiers, acs, done, failed, args.retry_failed, args.max_pages, args.limit)

    pages = sum(int(r["pages"]) for r in todo)
    print(f"{len(todo)} PDFs to convert, {pages:,} pages, about {pages * SEC_PER_PAGE / 3600:.1f} h "
          f"(already done: {len(done)}, failed earlier: {len(failed)})")
    if args.dry_run or not todo:
        for r in todo:
            print(f"  #{r['priority']:>3} tier {r['tier']} AC {r['ac']:>3} {r['file']:<16} {r['pages']:>3} p")
        return 0

    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"{args.workers} worker(s); one log per PDF in {log_dir}", flush=True)
    t_run, pages_done = time.time(), 0
    total_pages = pages
    try:
        for n, e in enumerate(run_jobs(todo, args.workers, pdf_dir, out_dir, not args.no_crops, log_dir,
                                         args.use_official), 1):
            ledger[e["file"]] = e
            save_views(ledger, queue_dir, rows)
            head = f"[{n}/{len(todo)}] AC {e['ac']} {e['file']} ({e['pages']} p):"
            if e["status"] == "DONE":
                print(f"{head} DONE {e['seconds']}s rows={e['rows']} OK={e['ok']} AUTO={e['auto_corrected']} "
                      f"UNUSUAL={e['unusual']} REVIEW={e['review']} totals={e['totals']} AC-check={e['ac_check']}")
            else:
                print(f"{head} FAILED {e['seconds']}s {e['error']}")
            if e["needs_review"] == "yes":
                print(f"    -> needs review: {e['review_reason']}")
            pages_done += int(e["pages"])
            elapsed = time.time() - t_run
            if total_pages > pages_done:
                print(f"    {elapsed / max(pages_done, 1):.1f} s/page wall time so far, about "
                      f"{(total_pages - pages_done) * elapsed / max(pages_done, 1) / 60:.0f} min left", flush=True)
    except KeyboardInterrupt:
        print("\nstopped - finished files are saved in the ledger; re-run to resume")
    finally:
        save_views(ledger, queue_dir, rows)

    mine = [ledger[r["file"]] for r in todo if r["file"] in ledger]
    flagged = [e for e in mine if e["needs_review"] == "yes"]
    print(f"\nthis run: {sum(e['status'] == 'DONE' for e in mine)} done, "
          f"{sum(e['status'] == 'FAILED' for e in mine)} failed, {len(flagged)} need review, "
          f"{(time.time() - t_run) / 60:.0f} min")
    print(f"ledger: {queue_dir / 'conversion_ledger.csv'}\nreview: {queue_dir / 'review_after_conversion.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
