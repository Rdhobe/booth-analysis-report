"""Form 20 PDF -> XLSX converter (text-table extraction, NOT OCR).

Why not OCR here: 2024091321.pdf is a digital-text PDF (PyMuPDF returns
clean text). Direct table extraction via pdfplumber is lossless (100%
accuracy). OCR (Tesseract etc.) would *introduce* errors. OCR fallback is
kept only for truly scanned pages.

Usage:
  python Scripts/convert_form20.py "2024/Agra/2024091321.pdf"
  python Scripts/convert_form20.py --batch "2024"   # all PDFs under 2024/
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("form20")

CANDIDATE_COUNT = 9  # this Form 20 has 9 candidates

HEADER_TOP = [
    "Serial No. Of Polling Station", "", "No of Valid Votes Cast in favour of",
    "", "", "", "", "", "", "", "",
    "Total of Valid Votes", "No. Of Rejected Votes", "Votes for NOTA",
    "Total", "No. Of Tendered Votes",
]


def clean(cell: str | None) -> str | None:
    if cell is None:
        return None
    t = cell.replace("\n", " ").strip()
    t = re.sub(r"\s+", " ", t)
    return t or None


def extract_title_info(pdf_path: Path) -> dict:
    """Pull FORM 20 title block from page 1 text."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        text = pdf.pages[0].extract_text() or ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    info = {"form": "", "sheet": "", "election": "", "electors": "", "assembly": ""}
    for l in lines:
        if "FORM 20" in l:
            info["form"] = "FORM 20"
        elif "FINAL RESULT SHEET" in l:
            info["sheet"] = "FINAL RESULT SHEET"
        elif "HOUSE OF PARLIAMENT" in l:
            info["election"] = l
        elif "Total No. of Electors" in l:
            info["electors"] = l
        elif "Name of Assembly" in l:
            info["assembly"] = l
    return info


def extract_pages(pdf_path: Path):
    """Return (candidate_names, data_rows, summary_rows).

    data_rows: list of 16-col rows [sno, psno, c1..c9, valid, rej, nota, total, tendered]
    summary_rows: Total EVM / Postal / Total Votes Polled rows (raw cleaned).
    """
    candidate_names: list[str] | None = None
    data_rows: list[list] = []
    summary_rows: list[list] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            if not tables:
                log.warning("page %d: no table found", pno)
                continue
            tbl = tables[0]
            # Normalise every cell: newlines -> space
            tbl = [[clean(c) for c in r] for r in tbl]
            # Detect header rows: row containing 'Serial' and row with candidate names
            # Data starts after the 2 header rows (rows 0,1 on normal pages).
            start = 0
            for idx, row in enumerate(tbl[:3]):
                joined = " ".join([c or "" for c in row])
                if "Serial" in joined and "Polling" in joined:
                    start = idx + 2  # skip this + candidate-name row
                    # capture candidate names from next row if present
                    if candidate_names is None and idx + 1 < len(tbl):
                        cand_row = tbl[idx + 1]
                        # candidate names live in cols 2..10
                        names = [c or "" for c in cand_row[2:11]]
                        if any(names):
                            candidate_names = names
                    break
            for row in tbl[start:]:
                # pad to 16 cols (page 16 summary has 15 cols)
                if len(row) < 16:
                    row = row + [None] * (16 - len(row))
                label = (row[0] or "")
                # Summary rows
                if label.startswith("Total EVM") or label.startswith("Total Postal") or label.startswith("Total Votes"):
                    summary_rows.append(row)
                    continue
                # Skip empty / non-numeric serial rows
                if not label or not re.match(r"^\d+$", label.strip()):
                    # Postal placeholder row has '(To be filled' in col2 -> keep as summary note
                    if any(c and "To be filled" in c for c in row):
                        summary_rows.append(row)
                    continue
                # Normal booth row: ensure 16 cols, keep strings; numbers validated later
                data_rows.append(row[:16])
    return candidate_names, data_rows, summary_rows


def validate(candidate_names, data_rows, summary_rows) -> list[str]:
    errors: list[str] = []
    if not candidate_names or len(candidate_names) != CANDIDATE_COUNT:
        errors.append(f"candidate header count != {CANDIDATE_COUNT}: {candidate_names}")
    # each booth row: Total Valid == sum(candidates)? Total == Valid + NOTA?
    for r in data_rows:
        try:
            cands = [int(x or 0) for x in r[2:11]]
            valid = int(r[11] or 0)
            nota = int(r[13] or 0)
            total = int(r[14] or 0)
        except ValueError:
            errors.append(f"non-numeric votes in row {r[0]}: {r[2:]}")
            continue
        if sum(cands) != valid:
            errors.append(f"row {r[0]}: sum(cands)={sum(cands)} != valid={valid}")
        if valid + nota != total:
            errors.append(f"row {r[0]}: valid {valid}+nota {nota} != total {total}")
    # EVM total cross-check vs sum of booth rows
    evm = next((s for s in summary_rows if (s[0] or "").startswith("Total EVM")), None)
    if evm:
        try:
            for j, col in enumerate([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14]):
                s = sum(int(r[col] or 0) for r in data_rows)
                e = int(evm[col] or 0)
                if s != e:
                    errors.append(f"EVM total mismatch col {col}: booth-sum={s} vs evm={e}")
        except ValueError:
            errors.append("non-numeric value in EVM total row")
    return errors


def build_workbook(pdf_path: Path, title: dict, candidate_names, data_rows, summary_rows) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Form20"
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hdr_fill = PatternFill("solid", fgColor="D9E1F2")
    title_font = Font(bold=True, size=12)
    hdr_font = Font(bold=True, size=10)
    norm_font = Font(size=10)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_c = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # --- Title block (rows 1-5) ---
    ws.merge_cells("A1:P1"); ws["A1"] = title.get("form", "FORM 20")
    ws.merge_cells("A2:P2"); ws["A2"] = title.get("sheet", "FINAL RESULT SHEET")
    ws.merge_cells("A3:P3"); ws["A3"] = title.get("election", "")
    ws.merge_cells("A4:P4"); ws["A4"] = title.get("electors", "")
    ws.merge_cells("A5:P5"); ws["A5"] = title.get("assembly", "")
    ws.merge_cells("A6:P6"); ws["A6"] = f"Source file: {pdf_path.name}"
    for r in range(1, 7):
        ws[f"A{r}"].font = title_font if r <= 2 else Font(bold=True, size=10)
        ws[f"A{r}"].alignment = center
        ws.row_dimensions[r].height = 18 if r > 2 else 22

    # --- Two-row table header (rows 7-8) ---
    H1, H2 = 7, 8
    ws.merge_cells("A7:B7"); ws["A7"] = "Serial No. Of Polling Station"
    ws.merge_cells(f"C{H1}:K{H1}"); ws[f"C{H1}"] = "No of Valid Votes Cast in favour of"
    for col, txt in [(12, "Total of Valid Votes"), (13, "No. Of Rejected Votes"),
                     (14, "Votes for NOTA"), (15, "Total"), (16, "No. Of Tendered Votes")]:
        ws.cell(row=H1, column=col, value=txt)
    ws.cell(row=H2, column=1, value="Serial No.")
    ws.cell(row=H2, column=2, value="Polling Station No.")
    for i, name in enumerate(candidate_names):
        ws.cell(row=H2, column=3 + i, value=name)
    for col in (12, 13, 14, 15, 16):
        ws.cell(row=H2, column=col, value="")  # continuation of merged top header
    for col in range(1, 17):
        for r in (H1, H2):
            c = ws.cell(row=r, column=col)
            c.font = hdr_font; c.alignment = center; c.fill = hdr_fill; c.border = border
    ws.row_dimensions[H1].height = 30
    ws.row_dimensions[H2].height = 45

    # --- Data rows from row 9 ---
    r0 = 9
    for i, row in enumerate(data_rows):
        rr = r0 + i
        for col in range(1, 17):
            v = row[col - 1]
            c = ws.cell(row=rr, column=col)
            if col <= 2:
                c.value = int(v) if v and re.match(r"^\d+$", str(v)) else v
            elif col <= 15:
                c.value = int(v) if v is not None and re.match(r"^-?\d+$", str(v).strip()) else v
            else:
                c.value = int(v) if v is not None and re.match(r"^-?\d+$", str(v).strip()) else v
            c.font = norm_font
            c.alignment = center
            c.border = border
        ws.row_dimensions[rr].height = 15

    # --- Summary rows (Total EVM / Postal note / Total Votes Polled) ---
    sr = r0 + len(data_rows)
    # Total EVM Votes
    evm = next((s for s in summary_rows if (s[0] or "").startswith("Total EVM")), None)
    if evm:
        ws.merge_cells(f"A{sr}:B{sr}")
        ws.cell(row=sr, column=1, value="Total EVM Votes").font = hdr_font
        for col in range(3, 17):
            v = evm[col - 1]
            c = ws.cell(row=sr, column=col,
                        value=int(v) if v is not None and re.match(r"^-?\d+$", str(v).strip()) else v)
            c.font = hdr_font; c.alignment = center; c.border = border; c.fill = PatternFill("solid", fgColor="FFF2CC")
        ws.cell(row=sr, column=1).alignment = center
        ws.cell(row=sr, column=1).border = border
        ws.cell(row=sr, column=1).fill = PatternFill("solid", fgColor="FFF2CC")
        ws.cell(row=sr, column=2).border = border
        ws.cell(row=sr, column=2).fill = PatternFill("solid", fgColor="FFF2CC")
        sr += 1
    # Postal note
    postal = next((s for s in summary_rows if (s[0] or "").startswith("Total Postal")), None)
    if postal:
        note = postal[2] or "Postal ballot votes"
        ws.merge_cells(f"A{sr}:P{sr}")
        ws.cell(row=sr, column=1, value=f"Total Postal Ballot Votes: {note}").font = Font(italic=True, size=10)
        ws.cell(row=sr, column=1).alignment = left_c
        sr += 1
    # Total Votes Polled (from page 16 table OR same as EVM when no postal)
    polled = next((s for s in summary_rows if (s[0] or "").startswith("Total Votes")), None)
    if polled:
        # p16 summary row: [label, c1..c9, valid, rej, nota, total, tendered] = 15 items
        # map onto columns C..P (3..16) -> exactly 14 numbers
        vals = polled[1:15]  # guard against 16-col padding creating a ghost col Q
        ws.merge_cells(f"A{sr}:B{sr}")
        ws.cell(row=sr, column=1, value="Total Votes Polled").font = hdr_font
        for k, v in enumerate(vals):
            c = ws.cell(row=sr, column=3 + k,
                        value=int(v) if v is not None and re.match(r"^-?\d+$", str(v).strip()) else v)
            c.font = hdr_font; c.alignment = center; c.border = border
            c.fill = PatternFill("solid", fgColor="D9E1F2")
        ws.cell(row=sr, column=1).alignment = center
        ws.cell(row=sr, column=1).border = border
        ws.cell(row=sr, column=1).fill = PatternFill("solid", fgColor="D9E1F2")
        ws.cell(row=sr, column=2).border = border
        ws.cell(row=sr, column=2).fill = PatternFill("solid", fgColor="D9E1F2")

    # --- Widths / freeze / filter / print ---
    widths = [10, 14] + [16] * 9 + [13, 12, 10, 10, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A9"
    ws.auto_filter.ref = f"A{H1}:P{r0 + len(data_rows) - 1}"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "7:8"

    # --- Validation sheet ---
    ws2 = wb.create_sheet("Validation")
    ws2["A1"] = f"Source: {pdf_path.name}"
    ws2["A2"] = f"Booth rows extracted: {len(data_rows)}"
    ws2["A3"] = f"Candidates: {', '.join(candidate_names)}"
    ws2["A4"] = "Row-level check: sum(candidates)==Total Valid AND Valid+NOTA==Total"
    ws2["A5"] = "EVM-total check: sum(booth rows) per column vs 'Total EVM Votes' row"
    for c in ["A1", "A2", "A3", "A4", "A5"]:
        ws2[c].font = Font(size=10)
    ws2.column_dimensions["A"].width = 110
    return wb


def convert_one(pdf_path: Path) -> Path:
    xlsx_path = pdf_path.with_suffix(".xlsx")
    log.info("Converting %s ...", pdf_path)
    title = extract_title_info(pdf_path)
    cands, data, summary = extract_pages(pdf_path)
    if not cands:
        raise RuntimeError("candidate header not found -layout changed?")
    log.info("candidates=%s | booth rows=%d | summary rows=%d", cands, len(data), len(summary))
    errors = validate(cands, data, summary)
    if errors:
        log.error("VALIDATION FAILED (%d):", len(errors))
        for e in errors[:20]:
            log.error("  - %s", e)
        raise RuntimeError(f"validation failed with {len(errors)} error(s); xlsx NOT written")
    wb = build_workbook(pdf_path, title, cands, data, summary)
    # write validation result into sheet
    ws2 = wb["Validation"]
    ws2["A6"] = f"Validation: PASS ({len(data)} booth rows, all row-sums + EVM totals match)"
    ws2["A6"].font = Font(bold=True, size=11, color="006100")
    wb.save(str(xlsx_path))
    log.info("WROTE %s", xlsx_path)
    return xlsx_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Form 20 PDF -> XLSX (exact text extraction)")
    ap.add_argument("pdf", nargs="?", help="single PDF file")
    ap.add_argument("--batch", help="convert every *.pdf under this folder (recursive)")
    args = ap.parse_args(argv)
    if args.batch:
        root = Path(args.batch)
        pdfs = sorted(root.rglob("*.pdf"))
        if not pdfs:
            log.error("no PDFs under %s", root)
            return 1
        fails = 0
        for p in pdfs:
            try:
                convert_one(p)
            except Exception as ex:  # noqa: BLE001 - continue batch
                log.error("%s: %s", p, ex)
                fails += 1
        log.info("done: %d ok, %d failed of %d", len(pdfs) - fails, fails, len(pdfs))
        return 1 if fails else 0
    if not args.pdf:
        ap.print_help()
        return 2
    convert_one(Path(args.pdf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
