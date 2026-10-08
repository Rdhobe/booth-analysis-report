"""Rename the 150 converted 2024 .xlsx sidecars to <AC_no>.xlsx.

Pattern follows data/2017 (e.g. data/2017/Agra/86.xls): the Form-20
workbook for an Assembly Constituency is named by its AC number.
PDF sources are NEVER touched (raw data is immutable) - only the
converted .xlsx outputs are renamed, and only for data_files.json
entries with year==2024, status==converted and a known ac_no
(124 files; 26 converted files have null AC and are listed, skipped).

Reference updates (same run, --apply only):
  - configs/data_files.json `xlsx` fields: byte-surgical replacement
    (the file carries non-UTF8 bytes elsewhere; it is never
    re-serialized, only the ASCII xlsx paths are swapped).
  - data/2024/bulk_convert_report.csv `xlsx` column for renamed rows.

Caveat: bulk_convert_form20 --skip-existing keys off
<pdf-stem>.xlsx, so a future bulk rerun would reconvert (not skip)
renamed files. The rename report lists every mapping.

Usage:
  python Scripts/rename_converted.py            # dry-run, prints plan
  python Scripts/rename_converted.py --apply    # renames + updates refs
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA24 = ROOT / "data" / "2024"
FILEMAP = ROOT / "configs" / "data_files.json"
BULKCSV = DATA24 / "bulk_convert_report.csv"
REPORT_MD = DATA24 / "rename_report.md"


def load_converted():
    raw = FILEMAP.read_bytes()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return raw, [x for x in data["files"]
                 if x.get("year") == "2024"
                 and x.get("status") == "converted"]


def plan():
    _raw, entries = load_converted()
    ok, skipped, missing = [], [], []
    for e in entries:
        src = (e.get("source") or "").replace("/", "\\")
        old = Path(e.get("xlsx") or "")
        old_disk = ROOT / str(e.get("xlsx") or "").replace("/", "\\")
        ac = e.get("ac_no")
        if not ac:
            skipped.append((src, "null AC number - cannot name"))
            continue
        new_disk = old_disk.parent / f"{int(ac)}.xlsx"
        if not old_disk.exists():
            missing.append((src, f"xlsx missing on disk: {old}"))
            continue
        if new_disk.exists() and new_disk.resolve() != old_disk.resolve():
            skipped.append((src, f"collision: {new_disk.name} exists"))
            continue
        if new_disk.resolve() == old_disk.resolve():
            skipped.append((src, "already named"))
            continue
        ok.append((old_disk, new_disk, src, e.get("xlsx")))
    return ok, skipped, missing


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Rename converted xlsx to AC no.")
    ap.add_argument("--apply", action="store_true",
                    help="execute renames + reference updates")
    ap.add_argument("--csv-only", action="store_true",
                    help="only refresh the bulk CSV xlsx column from the "
                    "current data_files.json state (no renames)")
    args = ap.parse_args(argv)

    if args.csv_only:
        _raw, entries = load_converted()
        new_by_pdf = {}
        for e in entries:
            if e.get("ac_no"):
                base = Path(str(e["source"]).replace("\\", "/")).name.lower()
                new_by_pdf[base] = f"{int(e['ac_no'])}.xlsx"
        with open(BULKCSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        n_csv = 0
        for r in rows:
            key = Path((r.get("pdf") or "").replace("\\", "/")).name.lower()
            if key in new_by_pdf and (r.get("xlsx") or "").strip():
                r["xlsx"] = (r.get("pdf") or "").rsplit("\\", 1)[0] + \
                    "\\" + new_by_pdf[key]
                n_csv += 1
        with open(BULKCSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["rel", "pdf", "pages",
                                              "ncands", "booths", "status",
                                              "xlsx", "error", "secs"])
            w.writeheader()
            w.writerows(rows)
        print(f"BULKCSV updated ({n_csv} xlsx paths)", flush=True)
        return 0

    ok, skipped, missing = plan()
    print(f"PLAN  rename={len(ok)} skip={len(skipped)} "
          f"missing={len(missing)}", flush=True)
    for old, new, src, _ in ok:
        print(f"  RENAME {old.relative_to(ROOT)} -> {new.name}",
              flush=True)
    for src, why in skipped:
        print(f"  SKIP   {src} ({why})", flush=True)
    for src, why in missing:
        print(f"  MISSING {src} ({why})", flush=True)
    if not args.apply:
        print("DRY-RUN only. Rerun with --apply to execute.", flush=True)
        return 0

    # 1. rename on disk
    for old, new, _src, _ in ok:
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
    # 2. byte-surgical data_files.json update (ASCII paths only)
    raw = FILEMAP.read_bytes()
    n_rep = 0
    for old, new, _src, xlsx_field in ok:
        old_b = str(xlsx_field).encode("ascii")
        new_b = str(xlsx_field).replace(
            old.name, new.name).encode("ascii")
        if raw.count(old_b) != 1:
            print(f"  WARN   ref count !=1 for {xlsx_field}, left manual",
                  flush=True)
            continue
        raw = raw.replace(old_b, new_b)
        n_rep += 1
    FILEMAP.write_bytes(raw)
    print(f"FILEMAP updated ({n_rep} xlsx refs swapped, rest untouched)",
          flush=True)
    # 3. bulk report xlsx column (matched by PDF basename: the bulk CSV
    # uses a different path prefix than data_files.json)
    with open(BULKCSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    new_by_pdf = {}
    for _old, new, src, _xlsx_field in ok:
        new_by_pdf[Path(src.replace("\\", "/")).name.lower()] = new.name
    n_csv = 0
    for r in rows:
        key = Path((r.get("pdf") or "").replace("\\", "/")).name.lower()
        if key in new_by_pdf and (r.get("xlsx") or "").strip():
            pdf_dir = (r.get("pdf") or "").rsplit("\\", 1)[0]
            r["xlsx"] = pdf_dir + "\\" + new_by_pdf[key]
            n_csv += 1
    with open(BULKCSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "pdf", "pages", "ncands",
                                          "booths", "status", "xlsx",
                                          "error", "secs"])
        w.writeheader()
        w.writerows(rows)
    print(f"BULKCSV updated ({n_csv} xlsx paths)", flush=True)
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("# Rename report - 2024 converted xlsx -> <AC>.xlsx\n\n")
        f.write(f"Renamed {len(ok)}, skipped {len(skipped)}, "
                f"missing {len(missing)}.\n\n")
        f.write("Caveat: bulk --skip-existing keys off "
                "`<pdf-stem>.xlsx`; a future bulk rerun will reconvert "
                "(not skip) renamed files.\n\n")
        for old, new, src, _ in ok:
            f.write(f"- `{src}` -> `{new.name}`\n")
        if skipped:
            f.write("\n## Skipped (original names kept)\n\n")
            for src, why in skipped:
                f.write(f"- `{src}` ({why})\n")
        if missing:
            f.write("\n## Missing on disk\n\n")
            for src, why in missing:
                f.write(f"- `{src}` ({why})\n")
    print(f"REPORT written -> {REPORT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
