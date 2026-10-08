"""Flatten Excel files: district subfolders -> year root, named by AC.

  data/2017/Agra/86.xls  ->  data/2017/86.xls   (all *.xls* of 2017/19/22)
  data/2024/Agra/86.xlsx ->  data/2024/86.xlsx  (renamed <AC>.xlsx only;
     PDFs, null-AC xlsx and REVIEW sidecars stay where they are)

First basename wins (sorted); later duplicates stay in place and are
reported. Reference updates on --apply: configs/data_files.json
source/xlsx fields (byte-surgical ASCII swap, never re-serialized)
and data/2024/bulk_convert_report.csv xlsx column (PDF column
unchanged - PDFs do not move).

Companion code change (separate): Scripts/agra_pipeline.py discovery
updated to year-root globs in the same sitting.

Usage:
  python Scripts/flatten_excels.py           # dry-run
  python Scripts/flatten_excels.py --apply   # move + update refs
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
FILEMAP = ROOT / "configs" / "data_files.json"
BULKCSV = DATA / "2024" / "bulk_convert_report.csv"
REPORT_MD = DATA / "2024" / "flatten_report.md"

YEARS_3 = ["2017", "2019", "2022"]


def collect():
    """(moves, skips): moves = [(src, dst)], skips = [(src, reason)]."""
    moves, skips = [], []
    seen: dict = {}
    for y in YEARS_3:
        root = DATA / y
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.xls*")):
            if p.parent == root:
                continue  # already flat
            dst = root / p.name
            if dst.name in seen.get(y, set()):
                skips.append((str(p.relative_to(ROOT)),
                              f"collision: {y}/{dst.name} already planned"))
                continue
            if dst.exists():
                skips.append((str(p.relative_to(ROOT)),
                              f"collision: {y}/{dst.name} exists on disk"))
                continue
            seen.setdefault(y, set()).add(dst.name)
            moves.append((p, dst))
    # 2024: only renamed <AC>.xlsx (1-3 digit numeric stems)
    r24 = DATA / "2024"
    seen24: set = set()
    for p in sorted(r24.rglob("*.xlsx")):
        if p.parent == r24 or "REVIEW" in p.name:
            continue
        if not re.match(r"^\d{1,3}\.xlsx$", p.name):
            continue
        if p.name in seen24 or (r24 / p.name).exists():
            skips.append((str(p.relative_to(ROOT)),
                          f"collision: 2024/{p.name} exists"))
            continue
        seen24.add(p.name)
        moves.append((p, r24 / p.name))
    return moves, skips


def leftovers():
    """Non-excel files remaining in district folders (informational)."""
    out = []
    for y in YEARS_3 + ["2024"]:
        root = DATA / y
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.parent != root \
                    and p.suffix.lower() not in (".xls", ".xlsx"):
                out.append(str(p.relative_to(ROOT)))
    return out


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def dupe_verdict(moves, skips):
    """For each skipped collision, compare content hash vs the file that
    won the target name. Returns [(src, target, verdict)]."""
    planned = {}
    for src, dst in moves:
        y = str(dst.relative_to(ROOT)).split("\\")[1]
        planned.setdefault((y, dst.name), []).append(src)
    out = []
    for src, _why in skips:
        name = Path(src).name
        y = str(src).split("\\")[1]  # src is already ROOT-relative
        cands = planned.get((y, name), [])
        disk = None
        for y in YEARS_3 + ["2024"]:
            cand = DATA / y / name
            if cand.exists():
                disk = cand
                break
        target = disk or (cands[0] if cands else None)
        if target is None:
            out.append((src, "-", "NO-TARGET"))
            continue
        try:
            same = sha(ROOT / src) == sha(target)
        except OSError:
            same = False
        out.append((src, str(target.relative_to(ROOT)),
                    "IDENTICAL" if same else "CONFLICT-differs"))
    return out


def a6_source(xlsx: Path):
    """Source PDF basename recorded in the workbook title block (A6)."""
    from openpyxl import load_workbook
    wb = load_workbook(str(xlsx), data_only=True, read_only=True)
    ws = wb["Form20"]
    a6 = str(ws["A6"].value or "")
    m = re.search(r"Source file:\s*(\S+\.pdf)", a6, re.I)
    return m.group(1) if m else ""


def xlsx_booths(p: Path):
    """Data-row count of a Form20 workbook (col A numeric from row 9)."""
    from openpyxl import load_workbook
    wb = load_workbook(str(p), data_only=True, read_only=True)
    ws = wb["Form20"]
    n, r = 0, 9
    while True:
        v = ws.cell(r, 1).value
        if v is None or not re.match(r"^\d+", str(v).strip()):
            break
        n += 1
        r += 1
    return n


def bulk_booths_map():
    """{(district, pdf_basename): booths} from the bulk report."""
    rows = list(csv.DictReader(
        open(DATA / "2024" / "bulk_convert_report.csv", encoding="utf-8")))
    out = {}
    for r in rows:
        rel = (r.get("rel") or "").replace("/", "\\")
        parts = rel.split("\\")
        if len(parts) >= 2:
            try:
                out[(parts[0].lower(), parts[-1].lower())] = int(
                    r.get("booths") or 0)
            except ValueError:
                pass
    return out


BULK_BOOTHS: dict = {}


def a6_source(xlsx: Path):
    """Source PDF basename recorded in the workbook title block (A6)."""
    from openpyxl import load_workbook
    wb = load_workbook(str(xlsx), data_only=True, read_only=True)
    ws = wb["Form20"]
    a6 = str(ws["A6"].value or "")
    m = re.search(r"Source file:\s*(\S+\.pdf)", a6, re.I)
    return m.group(1) if m else ""


def a6_resolve(e, rec, cands, actual, y, claimed):
    """Resolve a missing 2024 xlsx record: prefer unclaimed candidates,
    then A6 source match; zero basename candidates -> full A6 scan over
    short-named workbooks. Returns (pair|None, note)."""
    pdf_base = Path(str(e.get("source", "")).replace(
        "\\", "/")).name.lower()
    src_posix = str(e.get("source", "")).replace("\\", "/")
    pool = cands
    if not pool:
        pool = [p for (yy, _), ps in actual.items() if yy == "2024"
                for p in ps
                if re.match(r"^\d{1,3}\.xlsx$", p.name)]
    free = [c for c in pool
            if str(c.relative_to(ROOT)).replace("/", "\\").lower()
            not in claimed] or pool
    home = "/".join(src_posix.split("/")[:-1]).lower()
    free.sort(key=lambda c: (0 if str(c.parent).replace(
        "\\", "/").lower() == home else 1))
    # booth-count gate: entry's bulk booths must equal the workbook rows
    want = None
    parts = src_posix.split("/")
    if len(parts) >= 3:
        want = BULK_BOOTHS.get((parts[-2].lower(), parts[-1].lower()))
    hits = []
    for hit in free:
        try:
            a6 = a6_source(hit)
        except Exception:
            continue
        if not (a6 and a6.lower() == pdf_base):
            continue
        if want:
            try:
                if xlsx_booths(hit) != want:
                    continue
            except Exception:
                continue
        hits.append(hit)
    if len(hits) == 1:
        return ((rec.replace("\\", "/"),
                 hits[0].relative_to(ROOT).as_posix()), "")
    return (None, f"ambiguous/missing: {rec} "
                  f"({len(cands)} candidates, {len(hits)} A6 match)")


def filemap_reconcile():
    """(pairs, notes): for every filemap record pointing under
    data/<year>/ whose recorded file is MISSING on disk, locate the
    actual workbook by basename (+A6 source check for 2024 xlsx so a
    duplicate-named file is never misassigned)."""
    raw = FILEMAP.read_bytes()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    actual: dict = {}
    for y in YEARS_3 + ["2024"]:
        root = DATA / y
        if not root.exists():
            continue
        for p in root.rglob("*.xls*"):
            if "REVIEW" in p.name:
                continue
            actual.setdefault((y, p.name.lower()), []).append(p)
    pairs, notes = [], []
    claimed = set()
    for e in data["files"]:
        for field in ("source", "xlsx"):
            rec = (e.get(field) or "").replace("/", "\\")
            if rec and (ROOT / rec).exists():
                claimed.add(rec.lower())
    for e in data["files"]:
        y = e.get("year")
        if y not in ("2017", "2019", "2022", "2024"):
            continue
        for field in ("source", "xlsx"):
            rec = (e.get(field) or "").replace("/", "\\")
            if not rec or not rec.lower().startswith("data\\"):
                continue
            if (ROOT / rec).exists():
                continue  # record matches disk: nothing to do
            base = rec.rsplit("\\", 1)[-1].lower()
            cands = actual.get((y, base), [])
            if len(cands) != 1:
                if y == "2024" and field == "xlsx":
                    pair, note = a6_resolve(e, rec, cands, actual, y,
                                            claimed)
                    if pair:
                        pairs.append(pair)
                    else:
                        notes.append(note)
                else:
                    free = [c for c in cands
                            if str(c.relative_to(ROOT)).replace(
                                "/", "\\").lower() not in claimed]
                    if len(free) == 1:
                        pairs.append((rec.replace("\\", "/"),
                                      free[0].relative_to(ROOT).as_posix()))
                    else:
                        notes.append(f"ambiguous/missing: {rec} "
                                     f"({len(cands)} candidates)")
                continue
            hit = cands[0]
            if y == "2024" and field == "xlsx":
                try:
                    a6 = a6_source(hit)
                except Exception:
                    a6 = ""
                pdf_base = Path(str(e.get("source", "")).replace(
                    "\\", "/")).name.lower()
                if a6 and a6.lower() != pdf_base:
                    notes.append(f"A6-mismatch, left manual: {rec} "
                                 f"(A6 source={a6})")
                    continue
            pairs.append((rec.replace("\\", "/"),
                          hit.relative_to(ROOT).as_posix()))
    return pairs, notes


def stale_sidecars():
    """(sidecar, reason): quarantine sidecars whose file is resolved -
    bulk status OK and a final xlsx exists whose A6 source (or same
    stem) matches. REVIEW-file quarantines never qualify."""
    rows = list(csv.DictReader(
        open(DATA / "2024" / "bulk_convert_report.csv", encoding="utf-8")))
    ok_stems = {Path((r.get("pdf") or "").replace("\\", "/")).stem.lower()
                for r in rows if (r.get("status") or "") == "OK"}
    finals = [p for p in DATA.rglob("*.xlsx") if "REVIEW" not in p.name]
    by_a6: dict = {}
    for p in finals:
        try:
            by_a6.setdefault(a6_source(p).rsplit(".", 1)[0].lower(),
                             []).append(p)
        except Exception:
            pass
    out = []
    for p in sorted(DATA.rglob("*.REVIEW.xlsx")):
        stem = p.name[:-len(".REVIEW.xlsx")].lower()
        if stem not in ok_stems:
            continue
        if (p.parent / (p.name[:-len(".REVIEW.xlsx")] + ".xlsx")).exists():
            out.append((str(p.relative_to(ROOT)),
                        "bulk=OK + same-stem final xlsx present"))
        elif len(by_a6.get(stem, [])) == 1:
            out.append((str(p.relative_to(ROOT)),
                        f"bulk=OK + A6-verified final "
                        f"{by_a6[stem][0].relative_to(ROOT)}"))
    return out


def refresh_bulk_csv() -> int:
    """Rewrite the bulk CSV xlsx column from filemap state: for every
    bulk row whose PDF matches a 2024 filemap entry with an on-disk
    xlsx, point the row at the year-root workbook. Returns updates."""
    raw = FILEMAP.read_bytes()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    by_pdf: dict = {}
    for e in data["files"]:
        if e.get("year") != "2024" or not e.get("xlsx"):
            continue
        x = Path(str(e["xlsx"]).replace("/", "\\"))
        if (ROOT / str(e["xlsx"]).replace("/", "\\")).exists():
            pdf_base = Path(str(e.get("source", "")).replace(
                "\\", "/")).name.lower()
            by_pdf[pdf_base] = x.name
    with open(BULKCSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    n = 0
    for r in rows:
        pdf_base = Path((r.get("pdf") or "").replace(
            "\\", "/")).name.lower()
        if pdf_base in by_pdf and (r.get("xlsx") or "").strip():
            want = "2024\\" + by_pdf[pdf_base]
            if (r.get("xlsx") or "").replace("/", "\\") != want:
                r["xlsx"] = want
                n += 1
    with open(BULKCSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "pdf", "pages", "ncands",
                                          "booths", "status", "xlsx",
                                          "error", "secs"])
        w.writeheader()
        w.writerows(rows)
    return n


def swap_filemap(pairs):
    """pairs: [(old_rel_posix, new_rel_posix)] -> count swapped."""
    raw = FILEMAP.read_bytes()
    n = 0
    for old, new in pairs:
        ob = ('"' + old + '"').encode("ascii")
        nb = ('"' + new + '"').encode("ascii")
        if raw.count(ob) != 1:
            print(f"  WARN   ref count !=1 for {old}, left manual",
                  flush=True)
            continue
        raw = raw.replace(ob, nb)
        n += 1
    FILEMAP.write_bytes(raw)
    return n


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Flatten excels to year root")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--csv-refresh", action="store_true",
                    help="only refresh the bulk CSV xlsx column from the "
                    "current on-disk + filemap state (no moves)")
    args = ap.parse_args(argv)

    moves, skips = collect()
    from collections import Counter
    by_year = Counter(str(m[1].relative_to(ROOT)).split("\\")[1]
                      for m in moves)
    print(f"PLAN  move={len(moves)} {dict(by_year)}  "
          f"skip={len(skips)}", flush=True)
    for src, dst in moves:
        print(f"  MOVE {src.relative_to(ROOT)} -> {dst.name}", flush=True)
    for src, why in skips:
        print(f"  SKIP {src} ({why})", flush=True)
    print("DUPE-CONTENT check (skipped vs winner):", flush=True)
    for src, tgt, verdict in dupe_verdict(moves, skips):
        print(f"  {verdict:10s} {src}  vs  {tgt}", flush=True)
    global BULK_BOOTHS
    BULK_BOOTHS = bulk_booths_map()
    rec_pairs, rec_notes = filemap_reconcile()
    print(f"FILEMAP-RECONCILE pairs: {len(rec_pairs)} "
          f"notes: {len(rec_notes)}", flush=True)
    for old, new in rec_pairs[:30]:
        print(f"  FIXREF {old} -> {new}", flush=True)
    if len(rec_pairs) > 30:
        print(f"  ... +{len(rec_pairs) - 30} more", flush=True)
    for n in rec_notes[:15]:
        print(f"  NOTE {n}", flush=True)
    sweeps = stale_sidecars()
    print(f"STALE-SIDECARS to sweep: {len(sweeps)}", flush=True)
    for sc, why in sweeps[:12]:
        print(f"  SWEEP {sc} ({why})", flush=True)
    if len(sweeps) > 12:
        print(f"  ... +{len(sweeps) - 12} more", flush=True)
    lo = leftovers()
    if lo:
        print(f"LEFTOVER non-excel in subfolders: {len(lo)}", flush=True)
        for s in lo[:10]:
            print(f"  - {s}", flush=True)
    if args.csv_refresh:
        n_csv = refresh_bulk_csv()
        print(f"BULKCSV refreshed ({n_csv} xlsx paths)", flush=True)
        return 0
    if not args.apply:
        print("DRY-RUN only. Rerun with --apply to execute.", flush=True)
        return 0

    pairs, locked = [], []
    for src, dst in moves:
        try:
            src.rename(dst)
        except OSError as ex:
            locked.append((str(src.relative_to(ROOT)),
                           f"locked - close Excel/other holders and rerun: "
                           f"{ex}"))
            continue
        old_rel = src.relative_to(ROOT).as_posix()
        new_rel = dst.relative_to(ROOT).as_posix()
        pairs.append((old_rel, new_rel))
    for src, why in locked:
        print(f"  LOCKED {src} ({why})", flush=True)
    n_map = swap_filemap(pairs)
    print(f"FILEMAP updated direct moves ({n_map}/{len(pairs)})",
          flush=True)
    rec_pairs, rec_notes = filemap_reconcile()
    n_rec = swap_filemap(rec_pairs)
    print(f"FILEMAP reconciled ({n_rec}/{len(rec_pairs)} stale refs)",
          flush=True)
    for n in rec_notes[:10]:
        print(f"  NOTE {n}", flush=True)
    sweeps = stale_sidecars()
    for sc, why in sweeps:
        try:
            Path(ROOT / sc).unlink()
            print(f"  swept {sc}", flush=True)
        except OSError as ex:
            print(f"  sweep FAILED {sc}: {ex}", flush=True)
    n_csv = refresh_bulk_csv()
    print(f"BULKCSV refreshed ({n_csv} xlsx paths)", flush=True)
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("# Flatten report - excels moved to year root\n\n")
        f.write(f"Moved {len(moves)}, skipped {len(skips)}.\n\n")
        for src, dst in moves:
            f.write(f"- `{src.relative_to(ROOT)}` -> "
                    f"`{dst.relative_to(ROOT)}`\n")
        if skips:
            f.write("\n## Skipped (left in place)\n\n")
            for src, why in skips:
                f.write(f"- `{src}` ({why})\n")
        if locked:
            f.write("\n## Locked (close holders and rerun --apply)\n\n")
            for src, why in locked:
                f.write(f"- `{src}` ({why})\n")
        dupe_v = dupe_verdict(moves, skips)
        if dupe_v:
            f.write("\n## Skipped duplicates: content vs winner\n\n")
            for src, tgt, verdict in dupe_v:
                f.write(f"- {verdict} `{src}` vs `{tgt}`\n")
        rec_pairs2, rec_notes2 = filemap_reconcile()
        if rec_pairs2 or rec_notes2:
            f.write("\n## Filemap reconcile (post-move state)\n\n")
            for old, new in rec_pairs2:
                f.write(f"- `{old}` -> `{new}`\n")
            for n in rec_notes2:
                f.write(f"- NOTE: {n}\n")
        if sweeps:
            f.write("\n## Stale quarantine sidecars swept (bulk=OK + "
                    "final xlsx present)\n\n")
            for sc, why in sweeps:
                f.write(f"- `{sc}` ({why})\n")
    print(f"REPORT written -> {REPORT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
