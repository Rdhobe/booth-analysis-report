"""Fill data/2024/converted/ with the verified workbooks and write its MANIFEST.csv.

    python batch/publish_converted.py              # copy the verified workbooks, rewrite the manifest

Verified = the workbooks in data/output/staged_excel/ (batch/stage_verified.py and batch/split_multi_ac.py put them there:
every candidate column and NOTA equal the official 2024 totals). Each is copied with its checksum checked, and the
manifest lists every AC of the priority 180 - verified or not, with the reason it is pending - plus the verified ACs
outside the 180. Workbooks already in converted/ that a person corrected through a review pack
(batch/recheck_reviewed.py) are kept, and so are their manifest rows. Nothing is written to data/2024/EXCEL.
"""
import argparse
import csv
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from queue_common import QUEUE_DIR, REPO_ROOT, TOOL_DIR, read_csv  # noqa: E402

STAGED = TOOL_DIR / "data" / "output" / "staged_excel"
OUT = REPO_ROOT / "data" / "2024" / "converted"
FIELDS = ["ac", "in_priority_180", "status", "output_file", "input_pdf", "how_produced", "check", "note_or_reason"]
CHECK = "candidate columns and NOTA equal the official 2024 totals"
REVIEWED = "read by OCR, corrected by a person in a review pack"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def produced_by(ac, ledger, split, check):
    """How the verified workbook of an AC was made, and its review note."""
    if ac in split and split[ac]["verdict"] == "FULL":
        return f"cut out of {split[ac]['source']} (multi-constituency PDF)", ""
    for r in ledger.get(ac, []):
        name = Path(r["xlsx"]).name if r["xlsx"] else ""
        if r["status"] == "DONE" and check.get(name, {}).get("verdict") == "FULL":
            how = "read from the PDF text layer (exact digits)" if r.get("source") == "text layer" else "read by OCR"
            note = f"{r['review']} row(s) flagged for a glance" if int(r.get("review") or 0) else ""
            return how, note
    return "", ""


def publish(staged=STAGED, out=OUT, queue=QUEUE_DIR):
    """Copy the staged workbooks and rewrite the manifest. Returns (copied, manifest rows)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    priority = read_csv(Path(queue) / "priority_180_status.csv")
    ledger, split = {}, {}
    for r in read_csv(Path(queue) / "conversion_ledger.csv"):
        ledger.setdefault(int(r["ac"]), []).append(r)
    for r in read_csv(Path(queue) / "split_report.csv"):
        split[int(r["ac"])] = r
    check = {r["file"]: r for r in read_csv(Path(queue) / "official_check.csv")}
    old = {int(r["ac"]): r for r in read_csv(out / "MANIFEST.csv")}
    reviewed = {ac for ac, r in old.items() if r.get("how_produced") == REVIEWED and (out / f"{ac}.xlsx").exists()}

    copied = []
    for path in sorted(Path(staged).glob("*.xlsx"), key=lambda p: int(p.stem)):
        ac = int(path.stem)
        if ac in reviewed:
            continue                                         # a person's corrected workbook is never overwritten
        shutil.copy2(path, out / path.name)
        if sha256(path) != sha256(out / path.name):
            raise RuntimeError(f"copy of {path.name} does not match the original")
        copied.append(ac)

    rows = []
    in180 = set()
    for r in priority:
        ac = int(r["ac"])
        in180.add(ac)
        verified = (out / f"{ac}.xlsx").exists() and (r["state"].startswith("DONE") or ac in reviewed)
        if ac in reviewed:
            rows.append(dict(old[ac]))
            continue
        how, note = produced_by(ac, ledger, split, check) if verified else ("", "")
        rows.append({"ac": ac, "in_priority_180": "yes", "status": "VERIFIED" if verified else r["state"],
                     "output_file": f"converted/{ac}.xlsx" if verified else "", "input_pdf": r["pdf_files"],
                     "how_produced": how, "check": CHECK if verified else "",
                     "note_or_reason": note if verified else r["reason"]})
    for ac in copied:
        if ac not in in180:
            how, _ = produced_by(ac, ledger, split, check)
            rows.append({"ac": ac, "in_priority_180": "no", "status": "VERIFIED", "output_file": f"converted/{ac}.xlsx",
                         "input_pdf": split[ac]["source"] if ac in split else "", "how_produced": how, "check": CHECK,
                         "note_or_reason": "no PDF of its own; cut out of the PDF named in input_pdf" if ac in split else ""})
    rows.sort(key=lambda r: int(r["ac"]))
    with open(out / "MANIFEST.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return copied, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Copy verified workbooks to data/2024/converted/ and write the manifest.")
    ap.add_argument("--staged", default=str(STAGED))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    copied, rows = publish(args.staged, args.out)
    status = {}
    for r in rows:
        status[r["status"]] = status.get(r["status"], 0) + 1
    print(f"{len(copied)} workbooks copied to {args.out}; manifest: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
