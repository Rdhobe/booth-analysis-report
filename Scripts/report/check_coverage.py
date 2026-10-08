"""Coverage audit: which AC workbooks exist per year root, what's missing.

- 2017/2019/2022: expect ACs 1..403 (stems, AC-prefix stripped).
- 2024: expect the 150 converted workbooks (short <AC>.xlsx at root;
  REVIEW sidecars, PDFs and null-AC long names stay in subfolders).
- Lists: missing ACs, non-standard names, excels left in subfolders
  (with reason: locked / duplicate-conflict / review / not-targeted),
  and duplicate stems at root.

Read-only, except: retries the 4 previously-locked 2024 moves when
--retry-locked is passed.

Usage:
  python Scripts/check_coverage.py
  python Scripts/check_coverage.py --retry-locked
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


def ac_stem(name: str):
    m = re.match(r"^(?:AC)?(\d+)$", Path(name).stem)
    return int(m.group(1)) if m else None


def audit_year(y: str):
    root = DATA / y
    found: dict = {}
    odd, sub = [], []
    for p in sorted(root.glob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".xls", ".xlsx"):
            continue
        ac = ac_stem(p.name)
        if ac is None:
            odd.append(p.name)
        else:
            found.setdefault(ac, []).append(p.name)
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.parent != root \
                and p.suffix.lower() in (".xls", ".xlsx") \
                and "REVIEW" not in p.name:
            sub.append(str(p.relative_to(ROOT)))
    return found, odd, sub


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="AC coverage audit")
    ap.add_argument("--retry-locked", action="store_true")
    args = ap.parse_args(argv)

    for y in ("2017", "2019", "2022"):
        found, odd, sub = audit_year(y)
        missing = sorted(set(range(1, 404)) - set(found))
        dupes = {a: n for a, n in found.items() if len(n) > 1}
        print(f"{y}: root={sum(len(v) for v in found.values())} "
              f"unique-AC={len(found)} missing={missing}", flush=True)
        if dupes:
            print(f"  DUPES at root: {dupes}", flush=True)
        if odd:
            print(f"  ODD names at root: {odd}", flush=True)
        if sub:
            print(f"  LEFT in subfolders ({len(sub)}):", flush=True)
            for s in sub:
                print(f"    - {s}", flush=True)

    # 2024: root shorts vs subfolder shorts
    r24 = DATA / "2024"
    at_root = sorted(p.name for p in r24.glob("*.xlsx")
                     if "REVIEW" not in p.name)
    in_sub = sorted(str(p.relative_to(ROOT)) for p in r24.rglob("*.xlsx")
                    if p.parent != r24 and "REVIEW" not in p.name)
    print(f"2024: root xlsx={len(at_root)} subfolder xlsx={len(in_sub)} "
          f"total={len(at_root) + len(in_sub)} (expect 150)", flush=True)
    for s in in_sub:
        print(f"    - {s}", flush=True)
    moved = 0
    if args.retry_locked:
        for s in list(in_sub):
            src = ROOT / s
            dst = r24 / Path(s).name
            if dst.exists():
                print(f"  SKIP (root has {dst.name}): {s}", flush=True)
                continue
            try:
                src.rename(dst)
                moved += 1
                print(f"  MOVED {s} -> {dst.name}", flush=True)
            except OSError as ex:
                print(f"  STILL LOCKED {s}: {ex}", flush=True)
        print(f"retry-locked: moved {moved}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
