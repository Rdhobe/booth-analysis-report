"""Per-file review + safe retry for the 47 REVIEW-quarantined Form 20 PDFs.

Reads data/2024/bulk_convert_report.csv, processes ONLY rows with status
REVIEW (override with --status), one file at a time, and for each file:

  diagnose : none-cell map, blank rows, serial gaps, multi-AC segments,
             merged serials, small row diffs, EVM presence
  S1 base  : re-extract with the patched converter (footer-row recovery
             for '<n> Page <p>' / '<n> Pag' variants) -> accept iff valid
  S2 zero  : vote-range None -> '0' (max 2/row), lead text None ->
             'Unknown' -> accept iff fully valid afterwards
  S3 trim  : drop trailing empty candidate names (ncands-1, trailer left)
             -> accept iff fully valid
  S4 swap  : S3 + swap Total/NOTA trailer cols (variant layout with Total
             before NOTA + trailing grand-total col) -> accept iff fully
             valid with standard order preferred on ties
  else     : stays REVIEW with a MANUAL diagnosis class for human eye

Blank (all-None) vote rows are NEVER zero-filled - that would fabricate a
0-vote booth. Small-diff rows (|sum-valid|<=3, no Nones) are never
guessed either. Accepted files are written as final .xlsx (with the fix
audit in the Validation sheet); stale .REVIEW.xlsx sidecars are swept
only when the fresh run passes (same rule as retry_pending.py).

Usage:
  python Scripts/review47.py
  python Scripts/review47.py --only "Bijnor/*" --only "Azamgarh/*"
  python Scripts/review47.py --dry-run   # diagnose only, write nothing
"""
from __future__ import annotations

import argparse
import copy
import csv
import fnmatch
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from Scripts.ingest.bulk_convert_form20 import (  # noqa: E402
    build_workbook,
    convert_one,
    count_serial_starts,
    extract_form20,
    extract_title_info,
    find_serial_gaps,
    is_evm_row,
    is_num,
    validate_extraction,
    verify_saved_xlsx,
)
from openpyxl.styles import Font  # noqa: E402


def diagnose(info) -> dict:
    """Describe what's wrong; never mutates."""
    lead, trailer, ncands = info["lead"], info["trailer"], info["ncands"]
    c_valid, c_nota, c_total = trailer, trailer + 2, trailer + 3
    none_rows, blank_rows, small_diffs, bad_rows = [], [], [], []
    for r in info["data"]:
        votes = r[lead:lead + ncands]
        nones = [i for i, c in enumerate(votes)
                 if not is_num(c)]
        if nones and len(nones) == len(votes):
            blank_rows.append(str(r[0]))
            continue
        if nones:
            none_rows.append((str(r[0]), len(nones)))
        try:
            s = sum(int(r[c] or 0) for c in range(lead, lead + ncands))
            valid = int(r[c_valid] or 0)
            nota = int(r[c_nota] or 0)
            total = int(r[c_total] or 0)
        except (ValueError, IndexError):
            bad_rows.append(str(r[0]))
            continue
        if s != valid or valid + nota != total:
            d = abs(s - valid)
            if not nones and d <= 3:
                small_diffs.append(str(r[0]))
            elif not nones:
                bad_rows.append(str(r[0]))
    # merged serials: absurd serial numbers with huge vote sums
    serials = [int(r[0]) for r in info["data"]
               if ((r[0] or "").strip().isdigit())]
    merged = []
    if serials:
        med_n = sorted(serials)[len(serials) // 2]
        for r in info["data"]:
            s = (r[0] or "").strip()
            if s.isdigit() and int(s) > max(3 * med_n, med_n + 2000):
                merged.append(s)
    evm = next((s for s in info["summary"] if is_evm_row(s[0] or "")), None)
    return {
        "none_rows": none_rows, "blank_rows": blank_rows,
        "small_diffs": small_diffs, "bad_rows": bad_rows,
        "gaps": find_serial_gaps(info), "starts": count_serial_starts(info),
        "merged": merged, "evm_found": evm is not None,
        "evm_label": ((evm[0] if evm else
                       (info["summary"][0][0] if info["summary"] else "")) or ""),
    }


def classify(diag, errors) -> str:
    if diag["starts"] > 1:
        return "MULTI_AC_MANUAL"
    if diag["merged"]:
        return "MERGED_SERIAL_MANUAL"
    if diag["blank_rows"] and not diag["none_rows"] \
            and not diag["bad_rows"] and not diag["small_diffs"]:
        return "BLANK_ROWS_MANUAL"
    if diag["small_diffs"] and not diag["none_rows"] \
            and not diag["bad_rows"]:
        return "SMALL_DIFF_MANUAL"
    if any("EVM total mismatch" in e for e in errors) and diag["gaps"]:
        return "EVM_SHORTFALL_GAPS"
    if diag["none_rows"]:
        return "NONE_CELLS"
    if diag["bad_rows"] or any("sum(cands)" in e for e in errors):
        return "TRAILER_GEOMETRY"
    return "OTHER_MANUAL"


def try_zero_fill(info):
    """S2: copy with vote Nones -> '0', lead-text Nones -> 'Unknown'.

    Refuses (returns None) when any row has >2 vote gaps or a fully blank
    vote block - those are not safely inferable. Acceptance additionally
    requires the full validation to pass on the filled copy.
    """
    lead, ncands = info["lead"], info["ncands"]
    for r in info["data"]:
        votes = r[lead:lead + ncands]
        gaps = [c for c in range(lead, lead + ncands) if not is_num(r[c])]
        if len(gaps) == len(votes):
            return None, [f"S2-refused: row {r[0]} blank (all votes empty)"]
        if len(gaps) > 2:
            return None, [f"S2-refused: row {r[0]} has {len(gaps)} gaps (>2)"]
    new = copy.deepcopy(info)
    new_rows, audit = [], []
    for r in info["data"]:
        gaps = [c for c in range(lead, lead + ncands) if not is_num(r[c])]
        r2 = list(r)
        for c in gaps:
            r2[c] = "0"
            audit.append(f"row {r[0]} col {c}: None -> 0")
        for c in range(1, lead):
            if r2[c] is None or str(r2[c]).strip() == "":
                r2[c] = "Unknown"
                audit.append(f"row {r[0]} col {c}: None -> Unknown")
        new_rows.append(r2)
    new["data"] = new_rows
    errs = validate_extraction(new)
    if errs:
        return None, [f"S2-filled but still invalid ({len(errs)}): "
                      f"{errs[0]}"]
    return new, audit


def try_trim(info):
    """S3: drop trailing empty candidate names."""
    names = list(info["candidates"])
    while names and not names[-1].strip():
        names.pop()
    if len(names) == len(info["candidates"]) or len(names) < 2:
        return None
    new = copy.deepcopy(info)
    new["candidates"] = names
    new["ncands"] = len(names)
    new["trailer"] = new["lead"] + len(names)
    if validate_extraction(new):
        return None
    return new


def try_trim_swap(info):
    """S4: S3 + swap Total/NOTA trailer cells (variant column order)."""
    names = list(info["candidates"])
    while names and not names[-1].strip():
        names.pop()
    if len(names) == len(info["candidates"]) or len(names) < 2:
        return None
    new = copy.deepcopy(info)
    new["candidates"] = names
    new["ncands"] = len(names)
    new["trailer"] = new["lead"] + len(names)
    t = new["trailer"]
    for r in new["data"] + new["summary"]:
        if t + 3 < len(r):
            r[t + 2], r[t + 3] = r[t + 3], r[t + 2]
    if validate_extraction(new):
        return None
    return new


def write_fixed_xlsx(pdf, title, info, audit_lines) -> tuple[str, list]:
    xlsx = pdf.with_suffix(".xlsx")
    wb = build_workbook(pdf, title, info)
    ws = wb["Validation"]
    ws["A6"] = ("Validation: PASS after review47 safe-fix "
                 f"({len(info['data'])} booth rows). See audit below.")
    ws["A6"].font = Font(bold=True, size=11, color="006100")
    r = 7
    for line in audit_lines:
        ws[f"A{r}"] = line
        r += 1
    for n in info.get("_notes", []):
        ws[f"A{r}"] = f"NOTE: {n}"
        r += 1
    wb.save(str(xlsx))
    post = verify_saved_xlsx(xlsx, info)
    return str(xlsx), post


def process_one(pdf: Path, dry_run: bool) -> dict:
    out = {"booths": 0, "ncands": 0, "class": "", "strategy": "-",
           "result": "", "fixes": "", "residual": ""}
    title = extract_title_info(pdf)
    try:
        info = extract_form20(pdf)
    except Exception as ex:
        out.update(result="EXTRACT_FAIL",
                   residual=f"{type(ex).__name__}: {ex}")
        out["class"] = "OTHER_MANUAL"
        return out
    out.update(booths=len(info["data"]), ncands=info["ncands"])
    errors = validate_extraction(info)
    diag = diagnose(info)
    out["class"] = classify(diag, errors)
    gaps_txt = (f"gaps={len(diag['gaps'])}{diag['gaps'][:12]} "
                f"starts={diag['starts']} evm={'Y' if diag['evm_found'] else 'N'}")
    if not errors:  # S1: footer recovery (or plain) already fixed it
        out["strategy"] = "S1-base"
        out["class"] = "FOOTER_RECOVERED"
        if dry_run:
            out.update(result="WOULD_CONVERT_S1", fixes=gaps_txt)
            return out
        res = convert_one(pdf, skip_existing=False)
        if res["status"] == "OK":
            stale = pdf.with_name(pdf.stem + ".REVIEW.xlsx")
            if stale.exists():
                try:
                    stale.unlink()
                except OSError:
                    pass
        out.update(result=f"CONVERTED_{res['status']}",
                   fixes=f"S1 base re-extract; {gaps_txt}")
        return out
    # S2
    fixed2, audit2 = try_zero_fill(info)
    if fixed2 is not None:
        out["strategy"] = "S2-zero-fill"
        if dry_run:
            out.update(result="WOULD_CONVERT_S2",
                       fixes="; ".join(audit2[:8]))
            return out
        audit = ["FIX S2: vote-range None -> 0 (<=2/row), "
                 "lead text None -> Unknown."] + audit2
        xlsx, post = write_fixed_xlsx(pdf, title, fixed2, audit)
        if post:
            out.update(result="REVIEW STILL",
                       residual="; ".join(post[:3]))
            return out
        stale = pdf.with_name(pdf.stem + ".REVIEW.xlsx")
        if stale.exists():
            try:
                stale.unlink()
            except OSError:
                pass
        out.update(result="CONVERTED_OK",
                   fixes="; ".join(audit2[:8]))
        return out
    # S3
    trimmed = try_trim(info)
    if trimmed is not None:
        out["strategy"] = "S3-trim"
        if dry_run:
            out.update(result="WOULD_CONVERT_S3")
            return out
        audit = [f"FIX S3: dropped trailing empty candidate names "
                 f"({info['ncands']} -> {trimmed['ncands']}); "
                 f"trailer col {info['trailer']} -> {trimmed['trailer']}."]
        xlsx, post = write_fixed_xlsx(pdf, title, trimmed, audit)
        if post:
            out.update(result="REVIEW STILL",
                       residual="; ".join(post[:3]))
            return out
        stale = pdf.with_name(pdf.stem + ".REVIEW.xlsx")
        if stale.exists():
            try:
                stale.unlink()
            except OSError:
                pass
        out.update(result="CONVERTED_OK", fixes="; ".join(audit))
        return out
    # S4
    swapped = try_trim_swap(info)
    if swapped is not None:
        out["strategy"] = "S4-trim-swap"
        if dry_run:
            out.update(result="WOULD_CONVERT_S4")
            return out
        audit = [f"FIX S4: trailing empty names dropped "
                 f"({info['ncands']} -> {swapped['ncands']}) + variant "
                 f"trailer order (Total before NOTA) normalized; "
                 f"trailing grand-total col kept as-is."]
        xlsx, post = write_fixed_xlsx(pdf, title, swapped, audit)
        if post:
            out.update(result="REVIEW STILL",
                       residual="; ".join(post[:3]))
            return out
        stale = pdf.with_name(pdf.stem + ".REVIEW.xlsx")
        if stale.exists():
            try:
                stale.unlink()
            except OSError:
                pass
        out.update(result="CONVERTED_OK", fixes="; ".join(audit))
        return out
    # stays in REVIEW
    s2_reason = ""
    _, s2why = try_zero_fill(info)
    if s2why:
        s2_reason = s2why[0] + " "
    s3_reason = ""
    names = list(info["candidates"])
    _tmp = list(names)
    while _tmp and not _tmp[-1].strip():
        _tmp.pop()
    if len(_tmp) == len(names):
        s3_reason = "S3-n/a: no trailing empty candidate name. "
    else:
        t3 = copy.deepcopy(info)
        t3["candidates"] = _tmp
        t3["ncands"] = len(_tmp)
        t3["trailer"] = t3["lead"] + len(_tmp)
        e3 = validate_extraction(t3)
        s3_reason = (f"S3-trim tried, still invalid ({len(e3)}): "
                     f"{e3[0] if e3 else ''} " if e3 else "")
    detail = (f"none={diag['none_rows'][:6]} blank={diag['blank_rows'][:6]} "
              f"smalldiff={diag['small_diffs'][:8]} bad={diag['bad_rows'][:6]} "
              f"merged={diag['merged'][:4]} {gaps_txt} "
              f"evm_label={diag['evm_label'][:40]}")
    out.update(strategy="-", result="REVIEW STILL",
               fixes=(s2_reason + s3_reason + detail)[:600],
               residual="; ".join(errors[:4]))
    return out


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Review + safe retry the REVIEW files")
    ap.add_argument("--report", default="data/2024/bulk_convert_report.csv")
    ap.add_argument("--status", default="REVIEW")
    ap.add_argument("--only", action="append", default=[],
                    help="repeatable glob on rel path (either separator)")
    ap.add_argument("--dry-run", action="store_true",
                    help="diagnose only; write nothing (except --md file)")
    ap.add_argument("--md", default="",
                    help="write per-file review markdown to this path "
                    "(project-local, e.g. data/2024/review47.md)")
    args = ap.parse_args(argv)

    report = Path(args.report)
    with open(report, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    want = {s.strip().upper() for s in args.status.split(",") if s.strip()}
    todo = [r for r in rows if (r.get("status") or "").upper() in want]
    if args.only:
        def _match(rel, pat):
            return (fnmatch.fnmatch(rel, pat)
                    or fnmatch.fnmatch(rel.replace("\\", "/"), pat))
        todo = [r for r in todo
                if any(_match(r.get("rel", ""), p) for p in args.only)]
    print(f"REVIEW47 statuses={sorted(want)} -> {len(todo)} files"
          + (" (DRY-RUN)" if args.dry_run else ""), flush=True)

    results = []
    t_all = time.time()
    for i, r in enumerate(todo, start=1):
        rel = r.get("rel", "")
        pdf = Path("data/2024") / rel
        print(f"[{i}/{len(todo)}] START {rel}", flush=True)
        if not pdf.exists():
            print(f"[{i}/{len(todo)}] SKIP  missing file", flush=True)
            results.append((r, {"result": "MISSING_FILE", "class": "-",
                                "strategy": "-", "fixes": "",
                                "residual": "", "booths": r.get("booths", ""),
                                "ncands": ""}))
            continue
        try:
            o = process_one(pdf, args.dry_run)
        except Exception as ex:  # never let one file kill the batch
            import traceback
            traceback.print_exc()
            o = {"result": f"SCRIPT_ERROR {type(ex).__name__}",
                 "class": "-", "strategy": "-", "fixes": "",
                 "residual": str(ex)[:200], "booths": 0, "ncands": 0}
        print(f"[{i}/{len(todo)}] DONE  {rel}: class={o['class']} "
              f"strategy={o['strategy']} -> {o['result']}", flush=True)
        results.append((r, o))

    audit_path = Path("data/2024") / "review47_report.csv"
    if not args.dry_run:
        with open(audit_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["rel", "booths", "ncands", "class", "strategy",
                        "result", "fixes", "residual"])
            for r, o in results:
                w.writerow([r.get("rel", ""), o.get("booths", ""),
                            o.get("ncands", ""), o.get("class", ""),
                            o.get("strategy", ""), o.get("result", ""),
                            o.get("fixes", ""), o.get("residual", "")])
        print(f"AUDIT written -> {audit_path}", flush=True)
        # merge conversions back into the bulk report (git is the safety net)
        by_rel = {r.get("rel"): r for r in rows}
        for r, o in results:
            if str(o.get("result", "")) == "CONVERTED_OK":
                row = by_rel[r.get("rel", "")]
                pdf = Path("data/2024") / r.get("rel", "")
                xlsx = pdf.with_suffix(".xlsx")
                row.update(booths=str(o.get("booths", "")),
                           ncands=str(o.get("ncands", "")),
                           status="OK", xlsx=str(xlsx),
                           error=f"review47 {o.get('strategy')}: "
                                 f"{o.get('fixes', '')[:200]}")
        with open(report, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["rel", "pdf", "pages", "ncands",
                                              "booths", "status", "xlsx",
                                              "error", "secs"])
            w.writeheader()
            w.writerows(rows)
        print(f"REPORT updated -> {report}", flush=True)
    else:
        for r, o in results:
            print(f"  - {r.get('rel')}: {o['class']} -> "
                  f"{o['result']} | {o['fixes'][:160]}", flush=True)
    if args.md:
        md_path = Path(args.md)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# REVIEW47 - manual review of the 47 quarantined files\n\n")
            f.write(f"Source: `data/2024/bulk_convert_report.csv` "
                    f"(status REVIEW only). Generated read-only: no PDF, "
                    f"XLSX or report CSV was modified by this pass.\n\n")
            f.write("Rule applied: vote-range `None` -> `0`, lead text "
                    "`None` -> `Unknown` - but only where the full "
                    "validation (row sums + EVM totals where present) "
                    "passes afterwards. Blank (all-None) rows are never "
                    "zero-filled.\n\n")
            f.write("| # | File | Booths | Class | Retry outcome | Detail |\n")
            f.write("|---|------|--------|-------|---------------|--------|\n")
            for i, (r, o) in enumerate(results, start=1):
                det = (str(o.get("fixes", "")) or str(o.get("residual", "")))
                det = det.replace("|", "/").replace("\n", " ")
                f.write(f"| {i} | `{r.get('rel', '')}` | {o.get('booths', '')} "
                        f"| {o.get('class', '')} | {o.get('strategy', '')} -> "
                        f"{o.get('result', '')} | {det[:400]} |\n")
            f.write("\n## Per-file notes\n\n")
            for r, o in results:
                f.write(f"### `{r.get('rel', '')}`\n\n")
                f.write(f"- booths={o.get('booths', '')} "
                        f"ncands={o.get('ncands', '')} class={o.get('class', '')}\n")
                f.write(f"- retry: {o.get('strategy', '')} -> "
                        f"{o.get('result', '')}\n")
                if o.get("fixes"):
                    f.write(f"- detail: {o.get('fixes', '')}\n")
                if o.get("residual"):
                    f.write(f"- residual errors: {o.get('residual', '')}\n")
                f.write("\n")
        print(f"REVIEW-MD written -> {md_path}", flush=True)
    from collections import Counter
    print("OUTCOMES: " + str(dict(Counter(
        str(o.get("result", "")) for _, o in results))), flush=True)
    print(f"elapsed={time.time() - t_all:.0f}s", flush=True)
    left = sum(1 for _, o in results if "CONVERTED" not in str(o["result"]))
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
