"""Fix residual mirrored candidate names using independent ground truth.

Compares every converted 2024 xlsx's row-8 candidate names against
data/lok-sabha-elections-2024-results.csv (ECI, all UP PCs):
- exact normalized match                      -> keep (verified)
- full-string reverse matches a reference name -> replace (mirrored)
- else                                         -> leave + report as suspect

Only row-8 name cells are touched; vote cells never modified. Every
replacement is printed with file + old -> new. Safe to rerun (idempotent:
already-correct names match exactly and are kept).

Usage: python Scripts/fix_names_reference.py [--apply]
  default dry-run (report only); --apply writes workbooks.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def norm(s: str) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


HDR_CELL_RE = re.compile(
    r"valid votes|serial|polling|station|total|nota|rejected|tendered|"
    r"^\s*no\.?\s*$", re.I)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reference-based mirrored-name fix")
    ap.add_argument("--apply", action="store_true", help="write workbooks (default: report only)")
    args = ap.parse_args(argv)

    ref: dict = {}  # normalized -> display spelling
    ref_tokens: dict = {}  # frozenset(tokens) -> display spelling
    with open(ROOT / "data" / "lok-sabha-elections-2024-results.csv",
              encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            name = re.sub(r"\s+", " ", (r.get("Candidate") or "").strip())
            if name and name.upper() != "NOTA":
                ref.setdefault(norm(name), name)
                toks = tuple(sorted(t for t in re.findall(r"[A-Z]+", name.upper()) if len(t) > 1))
                if toks:
                    ref_tokens.setdefault(frozenset(toks), name)
    print(f"reference names: {len(ref)}", flush=True)

    import openpyxl
    fixed, reordered, suspect, ok = [], [], [], 0
    for x in sorted((ROOT / "data" / "2024").rglob("*.xlsx")):
        if x.name.endswith(".REVIEW.xlsx"):
            continue
        wb = openpyxl.load_workbook(str(x))
        ws = wb["Form20"] if "Form20" in wb.sheetnames else wb.active
        nc = ws.max_column
        # candidate block starts after serial [+ PS] cols: skip cells
        # that are themselves sub-headers, not names
        start = 2
        while start < nc - 4 and re.search(
                r"polling|station|serial|^\s*no\.?\s*$",
                str(ws.cell(8, start).value or ""), re.I):
            start += 1
        changed = False
        for c in range(start, nc - 4):
            cell = ws.cell(8, c)
            name = str(cell.value or "")
            if not name.strip() or HDR_CELL_RE.search(name):
                continue
            if norm(name) in ref:
                ok += 1
                continue
            rev = name[::-1]
            if norm(rev) in ref:
                new = ref[norm(rev)]
                fixed.append((str(x.relative_to(ROOT)), name, new))
                if args.apply:
                    cell.value = new
                    changed = True
                continue
            toks = frozenset(t for t in re.findall(r"[A-Z]+", name.upper())
                             if len(t) > 1)
            if len(toks) >= 2 and toks in ref_tokens:
                new = ref_tokens[toks]
                reordered.append((str(x.relative_to(ROOT)), name, new))
                if args.apply:
                    cell.value = new
                    changed = True
                continue
            rtoks = frozenset(t for t in re.findall(r"[A-Z]+", rev.upper())
                              if len(t) > 1)
            if len(rtoks) >= 2 and rtoks in ref_tokens:
                new = ref_tokens[rtoks]
                fixed.append((str(x.relative_to(ROOT)), name, new))
                if args.apply:
                    cell.value = new
                    changed = True
                continue
            toks = [t for t in re.findall(r"[A-Za-z]{4,}", name)]
            if toks and not re.search(r"[\u0900-\u097F]", name):
                suspect.append((str(x.relative_to(ROOT)), name))
        if changed and args.apply:
            wb.save(str(x))
        wb.close()
    print(f"verified-exact: {ok}", flush=True)
    print(f"fixed-mirrored: {len(fixed)}", flush=True)
    for rel, old, new in fixed:
        print(f"  {rel}\n    {old}\n -> {new}", flush=True)
    print(f"fixed-word-order: {len(reordered)}", flush=True)
    for rel, old, new in reordered[:30]:
        print(f"  {rel}\n    {old}\n -> {new}", flush=True)
    print(f"suspect (left untouched): {len(suspect)}", flush=True)
    for rel, name in sorted(set(suspect))[:40]:
        print(f"  {rel} :: {name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
