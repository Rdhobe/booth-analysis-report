"""Stage 7: write the Excel workbook (and review crops) for one FileResult.

Sheets
  Form20            polling-station rows in the 2024 Form 20 layout, plus the
                    extra columns of the older 2017 layout (blank when the PDF
                    does not carry them) and QC columns
  Tidy              one row per polling station x candidate / total (long form)
  Review_Queue      rows that need a person to look, with a crop of the scan
  Auto_Corrections  cells the arithmetic repaired (audit trail)
  Totals_Check      printed 'Total EVM votes' row vs the sum of the rows
  Run_Log           what was processed and what to watch
"""
from pathlib import Path

import cv2
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .imaging import load_page

HEAD = PatternFill("solid", fgColor="DCE6F1")
YELLOW = PatternFill("solid", fgColor="FFF2CC")
FIXED = PatternFill("solid", fgColor="FFF2A8")
REVIEW = PatternFill("solid", fgColor="F8CBAD")
UNUSUAL = PatternFill("solid", fgColor="FCE4D6")
GREEN = PatternFill("solid", fgColor="E2EFDA")
BOLD = Font(bold=True)
THIN = Side(style="thin", color="999999")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

EXTRA_COLS = [
    "Total Electors (Polling Station)",
    "Voters Turnout - Male",
    "Voters Turnout - Female",
    "Voters Turnout - Other",
    "Voters identified using EPIC",
]
METRICS = ["TOTAL_VALID", "REJECTED", "NOTA", "TOTAL", "TENDERED"]
METRIC_LABELS = ["Total of Valid Votes", "No. of Rejected Votes", "Votes for NOTA", "Total", "No. of Tendered Votes"]


def _display_names(res):
    return [n or f"Candidate {i + 1}" for i, n in enumerate(res.names_en if any(res.names_en) else res.names_native)]


def _title_block(ws, res, ncols):
    seg = res.meta.get("segment_name") or ""
    segno = res.meta.get("segment_no")
    seg_txt = f"{segno}-{seg}" if segno else seg
    lines = [
        "FORM 20",
        "FINAL RESULT SHEET",
        "ELECTION TO THE HOUSE OF PARLIAMENT CONSTITUENCY",
        f"Total No. of Electors in Assembly Constituency/segment ....{res.meta.get('electors') or ''}",
        f"Name of Assembly/segment ...{seg_txt} Assembly Election",
        f"Source file: {res.pdf}",
    ]
    if res.meta.get("constituency"):
        lines.insert(3, f"Parliamentary constituency: {res.meta['constituency']}")
    for i, text in enumerate(lines, start=1):
        c = ws.cell(row=i, column=1, value=text)
        c.font = Font(bold=True, size=12 if i < 4 else 10)
        c.alignment = Alignment(horizontal="center")
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=ncols)
    return len(lines) + 2


def write_form20_sheet(wb, res):
    ws = wb.active
    ws.title = "Form20"
    nc = res.n_cands
    names = _display_names(res)
    first_cand = 3
    col_valid = first_cand + nc
    col_extra = col_valid + 5
    col_qc = col_extra + len(EXTRA_COLS)
    ncols = col_qc + 3
    r0 = _title_block(ws, res, ncols)

    # group header
    groups = [
        (1, 2, "Serial No. Of Polling Station"),
        (first_cand, first_cand + nc - 1, "No of Valid Votes Cast in favour of"),
        (col_extra, col_extra + len(EXTRA_COLS) - 1, "Other fields (blank when not present in the PDF)"),
        (col_qc, col_qc + 3, "Quality check"),
    ]
    for a, b, text in groups:
        ws.cell(row=r0, column=a, value=text)
        if b > a:
            ws.merge_cells(start_row=r0, start_column=a, end_row=r0, end_column=b)
    for k, label in enumerate(METRIC_LABELS):
        ws.cell(row=r0, column=col_valid + k, value=label)
        ws.merge_cells(start_row=r0, start_column=col_valid + k, end_row=r0 + 1, end_column=col_valid + k)

    # column header
    heads = ["Serial No.", "Polling Station No. / Name"] + names
    for i, h in enumerate(heads, start=1):
        ws.cell(row=r0 + 1, column=i, value=h)
    for i, h in enumerate(EXTRA_COLS):
        ws.cell(row=r0 + 1, column=col_extra + i, value=h)
    for i, h in enumerate(["Check_Status", "Review_Note", "Source_Page", "Source_Row"]):
        ws.cell(row=r0 + 1, column=col_qc + i, value=h)
    r = r0 + 2
    if res.hindi:
        ws.cell(row=r, column=2, value="Name (Devanagari)")
        for i, n in enumerate(res.names_native):
            ws.cell(row=r, column=first_cand + i, value=n)
        r += 1
    ws.cell(row=r, column=2, value="Party")
    for i, pty in enumerate(res.parties):
        ws.cell(row=r, column=first_cand + i, value=pty or None)
    for rr in range(r0, r + 1):
        for cc in range(1, ncols + 1):
            cell = ws.cell(row=rr, column=cc)
            cell.fill, cell.alignment, cell.border = HEAD, CENTER, BOX
            cell.font = BOLD
    ws.row_dimensions[r0 + 1].height = 48
    data_start = r + 1

    # data rows
    for k, row in enumerate(res.rows):
        rr = data_start + k
        ws.cell(row=rr, column=1, value=row.serial)
        ws.cell(row=rr, column=2, value=row.ps_no)
        for i, v in enumerate(row.values):
            ws.cell(row=rr, column=first_cand + i, value=v)
        ws.cell(row=rr, column=col_qc, value=row.status)
        ws.cell(row=rr, column=col_qc + 1, value="; ".join(row.notes) if row.notes else None)
        ws.cell(row=rr, column=col_qc + 2, value=row.page)
        ws.cell(row=rr, column=col_qc + 3, value=row.row_in_page)
        changed = {i for i, v in enumerate(row.values) if v is not None and row.primary and str(v) != row.primary[i]}
        for cc in range(1, ncols + 1):
            ws.cell(row=rr, column=cc).border = BOX
        if row.status in ("REVIEW", "UNUSUAL"):
            for cc in range(1, ncols + 1):
                ws.cell(row=rr, column=cc).fill = REVIEW if row.status == "REVIEW" else UNUSUAL
        else:
            for i in changed:
                ws.cell(row=rr, column=first_cand + i).fill = FIXED
    end = data_start + len(res.rows) - 1

    # printed totals rows + computed check
    rr = end + 1
    labels = {"TOTAL_EVM": "Total EVM Votes", "TOTAL_POSTAL": "Total Postal Ballot Votes", "TOTAL_POLLED": "Total Votes Polled"}
    for key, label in labels.items():
        if key not in res.totals:
            continue
        ws.cell(row=rr, column=1, value=label)
        ws.merge_cells(start_row=rr, start_column=1, end_row=rr, end_column=2)
        for i, v in enumerate(res.totals[key].values):
            ws.cell(row=rr, column=first_cand + i, value=v)
        for cc in range(1, col_valid + 5):
            c = ws.cell(row=rr, column=cc)
            c.fill, c.font, c.border = YELLOW, BOLD, BOX
        rr += 1
    ws.cell(row=rr, column=1, value="Computed: sum of the rows above")
    ws.merge_cells(start_row=rr, start_column=1, end_row=rr, end_column=2)
    for i in range(nc + 5):
        col = get_column_letter(first_cand + i)
        ws.cell(row=rr, column=first_cand + i, value=f"=SUM({col}{data_start}:{col}{end})")
    for cc in range(1, col_valid + 5):
        c = ws.cell(row=rr, column=cc)
        c.fill, c.font, c.border = GREEN, BOLD, BOX
    ws.freeze_panes = ws.cell(row=data_start, column=3)
    ws.auto_filter.ref = f"A{r0 + 1}:{get_column_letter(ncols)}{end}"
    ws.column_dimensions["A"].width = 11
    ws.column_dimensions["B"].width = 22
    for i in range(first_cand, col_extra):
        ws.column_dimensions[get_column_letter(i)].width = 13
    for i in range(col_extra, col_qc):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.column_dimensions[get_column_letter(col_qc)].width = 16
    ws.column_dimensions[get_column_letter(col_qc + 1)].width = 70


def write_tidy_sheet(wb, res):
    ws = wb.create_sheet("Tidy")
    ws.append([
        "Source_File", "Segment_No", "Segment_Name", "Electors", "PS_Serial", "PS_No",
        "Metric", "Name", "Name_Native", "Party", "Votes", "Check_Status",
    ])
    names = _display_names(res)
    for row in res.rows:
        base = [res.pdf, res.meta.get("segment_no"), res.meta.get("segment_name"), res.meta.get("electors"),
                row.serial, row.ps_no]
        for i in range(res.n_cands):
            ws.append(base + ["CANDIDATE", names[i], res.names_native[i], res.parties[i] or None,
                              row.values[i], row.status])
        for k, m in enumerate(METRICS):
            ws.append(base + [m, METRIC_LABELS[k], None, None, row.values[res.n_cands + k], row.status])
    for c in ws[1]:
        c.font, c.fill = BOLD, HEAD
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _crop_row(pdf_path, row, out_path, context=1):
    page, x0, y0, x1, y1 = row.box
    gray, _ = load_page(pdf_path, page)
    pitch = y1 - y0
    top, bottom = max(0, y0 - context * pitch), min(gray.shape[0], y1 + context * pitch)
    crop = gray[top:bottom, max(0, x0 - 5): x1 + 5]
    cv2.imwrite(str(out_path), crop)
    return out_path, (y0 - top, y1 - top)


def write_review_sheet(wb, res, pdf_path, crops_dir, with_crops=True):
    ws = wb.create_sheet("Review_Queue")
    ws.append(["Page", "Row on page", "Serial", "PS No.", "Why it needs a look", "Values as read (plain OCR)",
               "Values used", "Scan (row +/- 1)", "Status"])
    for c in ws[1]:
        c.font, c.fill = BOLD, HEAD
    review_rows = [r for r in res.rows if r.status in ("REVIEW", "UNUSUAL")]
    crops_dir = Path(crops_dir)
    if with_crops and review_rows:
        crops_dir.mkdir(parents=True, exist_ok=True)
    line = 2
    for r in review_rows:
        ws.append([
            r.page, r.row_in_page, r.serial, r.ps_no, "; ".join(r.notes) or "needs review",
            " | ".join(x or "?" for x in r.primary), " | ".join("?" if v is None else str(v) for v in r.values),
            None, r.status,
        ])
        if with_crops and r.box:
            p, _ = _crop_row(pdf_path, r, crops_dir / f"p{r.page}_serial{r.serial}.png")
            img = XlImage(str(p))
            scale = 900 / img.width if img.width > 900 else 1
            img.width, img.height = img.width * scale, img.height * scale
            ws.add_image(img, f"H{line}")
            ws.row_dimensions[line].height = max(30, img.height * 0.75)
        line += 1
    for k, text in enumerate(res.meta.get("file_issues", [])):
        ws.append(["-", "-", "-", "-", text])
    ws.column_dimensions["E"].width = 60
    ws.column_dimensions["F"].width = 45
    ws.column_dimensions["G"].width = 45
    ws.column_dimensions["H"].width = 120
    ws.freeze_panes = "A2"


def write_corrections_sheet(wb, res):
    ws = wb.create_sheet("Auto_Corrections")
    ws.append(["Page", "Serial", "PS No.", "Column", "Plain OCR reading", "Value used", "Note"])
    for c in ws[1]:
        c.font, c.fill = BOLD, HEAD
    names = _display_names(res) + METRIC_LABELS
    for r in res.rows:
        if not r.primary:
            continue
        for i, v in enumerate(r.values):
            if v is not None and str(v) != r.primary[i]:
                ws.append([r.page, r.serial, r.ps_no, names[i], r.primary[i] or "(blank)", v,
                           "; ".join(n for n in r.notes if "column totals" in n) or "fixed by row arithmetic"])
    ws.freeze_panes = "A2"
    ws.column_dimensions["D"].width = 24


def write_totals_sheet(wb, res):
    ws = wb.create_sheet("Totals_Check")
    ws.append(["Column", "Printed (Total EVM votes row)", "Sum of the rows", "Difference", "Matches"])
    for c in ws[1]:
        c.font, c.fill = BOLD, HEAD
    for label, printed, computed, ok in res.checks:
        diff = (printed - computed) if isinstance(printed, int) else None
        ws.append([label, printed, computed, diff, "yes" if ok else "NO"])
        if not ok:
            for c in ws[ws.max_row]:
                c.fill = REVIEW
    ws.column_dimensions["A"].width = 26
    for col in "BCDE":
        ws.column_dimensions[col].width = 26


def write_log_sheet(wb, res):
    ws = wb.create_sheet("Run_Log")
    from collections import Counter

    cnt = Counter(r.status for r in res.rows)
    n = max(1, len(res.rows))
    rows = [
        ("Source file", res.pdf),
        ("Language", "Hindi (Devanagari)" if res.hindi else "English"),
        ("Pages processed", res.n_pages),
        ("Polling-station rows extracted", len(res.rows)),
        ("  read correctly first time (OK)", cnt["OK"]),
        ("  repaired by the sheet's arithmetic (AUTO_CORRECTED)", cnt["AUTO_CORRECTED"]),
        ("  arithmetic OK but the source row looks odd - glance at the scan (UNUSUAL)", cnt["UNUSUAL"]),
        ("  need a person to check (REVIEW)", cnt["REVIEW"]),
        ("Automatically verified (OK + AUTO_CORRECTED + UNUSUAL)", f"{100 * (cnt['OK'] + cnt['AUTO_CORRECTED'] + cnt['UNUSUAL']) / n:.1f}%"),
        ("Column totals match the printed Total EVM row",
         "yes - all columns" if res.checks and all(c[3] for c in res.checks) else "NO - see Totals_Check"),
        ("Electors (title block)", res.meta.get("electors")),
        ("Segment", f"{res.meta.get('segment_no')}-{res.meta.get('segment_name')}"),
        ("Parliamentary constituency", res.meta.get("constituency")),
        ("Candidate names from", res.names_source),
        ("Rows dropped as non-data (page, row)", str(res.meta.get("dropped_non_data_rows", []))),
        ("Pages where the table was not found", str(res.page_errors)),
        ("Processing time (s)", round(res.seconds)),
    ]
    for a, b in rows:
        ws.append([a, b])
    for c in ws["A"]:
        c.font = BOLD
    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 60


def collect_file_issues(res):
    issues = []
    if "UNVERIFIED" in res.names_source:
        issues.append("Candidate names were read by OCR and are unverified - add this file to config/candidates.csv and re-run.")
    for a, b, d, rows in res.meta.get("mismatch_suspects", []):
        if b:
            issues.append(f"Printed column totals differ for '{a}' and '{b}' by {d}; likely rows: {rows or 'not localised'}")
        else:
            issues.append(f"Printed column total differs for '{a}' by {d}; not localised")
    for page, why in res.page_errors:
        issues.append(f"Page {page}: {why}")
    return issues


def export_workbook(res, pdf_path, out_dir, with_crops=True):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(res.pdf).stem
    res.meta["file_issues"] = collect_file_issues(res)
    wb = Workbook()
    write_form20_sheet(wb, res)
    write_tidy_sheet(wb, res)
    write_review_sheet(wb, res, pdf_path, out_dir / "review_crops" / stem, with_crops)
    write_corrections_sheet(wb, res)
    write_totals_sheet(wb, res)
    write_log_sheet(wb, res)
    path = out_dir / f"{stem}_Form20.xlsx"
    wb.save(path)
    return path
