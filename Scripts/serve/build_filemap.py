"""Map every data file by district + AC number -> configs/data_files.json.

Scans data/2017, data/2019, data/2022, data/2024 (district folders).
- 2017/2019/2022 sources ARE excel (.xls named by AC): status source-excel.
- 2024 sources are PDFs (coded filenames); AC comes from the title block:
  converted .xlsx sidecars (Name of Assembly/segment cell) or raw PDF
  first-page text. Missing sidecar  =>  "xlsx": "NOT FOUND".
- Folders named "*Data not found*" => missing_districts.
- Unparseable AC (scanned Hindi titles) => ac_no null + note (needs OCR).

Usage: python Scripts/build_filemap.py
Output: configs/data_files.json
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
OUT = ROOT / "configs" / "data_files.json"

AC_RE = re.compile(r"(\d{2,3})\s*[-–]\s*([A-Za-z\u0900-\u097F .()]+)")


def ac_from_title(text: str):
    """Find 'NN-Name' near Assembly/segment markers (EN or Hindi)."""
    if not text:
        return None, None
    for line in text.splitlines():
        if re.search(r"Assembly/segment|विधान सभा|AC No", line, re.I):
            m = AC_RE.search(line)
            if m:
                return int(m.group(1)), m.group(2).strip()
    m = AC_RE.search(text)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, None


def main() -> int:
    files, missing_districts = [], []
    for year in ["2017", "2019", "2022", "2024"]:
        ydir = DATA / year
        if not ydir.exists():
            continue
        for d in sorted(p for p in ydir.iterdir() if p.is_dir()):
            if "data not found" in d.name.lower():
                missing_districts.append(f"{year}/{d.name}")
                continue
            district = d.name
            if year in ("2017", "2019", "2022"):
                for x in sorted(d.glob("*.xls")):
                    m = re.search(r"(\d{2,3})", x.stem)
                    ac = int(m.group(1)) if m else None
                    files.append({"year": year, "district": district,
                                  "ac_no": ac, "ac_name": "",
                                  "source": str(x.relative_to(ROOT)).replace("\\", "/"),
                                  "status": "source-excel", "note": ""})
                continue
            # 2024: PDFs + converted xlsx sidecars (rglob: some batches
            # sit nested, e.g. data/2024/Banda/Barabanki/)
            pdfs = sorted(d.rglob("*.pdf"))
            for pdf in pdfs:
                rel = str(pdf.relative_to(ROOT)).replace("\\", "/")
                cand = pdf.with_suffix(".xlsx")
                x = cand if cand.exists() else None
                review = None
                if x is None:
                    cand = pdf.with_name(pdf.stem + ".REVIEW.xlsx")
                    if cand.exists():
                        review = cand
                ac_no, ac_name, note, status = None, "", "", "converted"
                if x is None and review is None:
                    status, xlsx = "missing_xlsx", "NOT FOUND"
                elif review is not None:
                    status = "review"
                    xlsx = str(review.relative_to(ROOT)).replace("\\", "/")
                    note = "quarantined REVIEW sidecar - needs human eye"
                else:
                    xlsx = str(x.relative_to(ROOT)).replace("\\", "/")
                # AC from sidecar title, else raw PDF text
                if status == "converted" and x is not None:
                    try:
                        import openpyxl
                        wb = openpyxl.load_workbook(str(x), data_only=True,
                                                   read_only=True)
                        ws = wb.active
                        t = " ".join(str(ws.cell(r, 1).value or "")
                                     for r in range(1, 7))
                        wb.close()
                        ac_no, ac_name = ac_from_title(t)
                        if ac_no is None:
                            note = "sidecar title block unreadable (mirrored PDF?)"
                    except Exception as ex:  # noqa: BLE001
                        note = f"title unreadable: {ex}"
                if ac_no is None and status in ("missing_xlsx", "review"):
                    try:
                        import pdfplumber
                        with pdfplumber.open(str(pdf)) as doc:
                            t = doc.pages[0].extract_text() or "" if doc.pages else ""
                        ac_no, ac_name = ac_from_title(t)
                        if ac_no is None:
                            note = ((note + "; ") if note else "") + (
                                "AC title not in text layer (scan?) - needs OCR"
                                if len(t) < 500 else
                                "AC title undecodable (legacy/Hindi font?) - needs check")
                    except Exception as ex:  # noqa: BLE001
                        note = ((note + "; ") if note else "") + f"pdf unreadable: {ex}"
                files.append({"year": year, "district": district,
                              "ac_no": ac_no, "ac_name": ac_name or "",
                              "source": rel, "xlsx": xlsx,
                              "status": status, "note": note})
    # cross-check converted count vs report CSV if present
    rep = DATA / "2024" / "bulk_convert_report.csv"
    rep_ok = set()
    if rep.exists():
        with open(rep, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("status") or "") == "OK":
                    rep_ok.add(r.get("rel", "").replace("\\", "/"))
    doc = {"meta": {"generated_by": "Scripts/build_filemap.py",
                    "roots": ["data/2017", "data/2019", "data/2022", "data/2024"],
                    "xlsx_rule": "same folder + basename as PDF; absent => \"NOT FOUND\"",
                    "report_crosscheck_ok": len(rep_ok)},
           "missing_districts": sorted(missing_districts),
           "files": sorted(files, key=lambda r: (r["year"], r["district"],
                                                 r["ac_no"] if r["ac_no"] is not None else 9999))}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print("wrote", OUT)
    print("files:", len(files),
          dict(Counter((r["year"], r["status"]) for r in files)))
    print("missing districts:", len(missing_districts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
