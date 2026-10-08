"""Bulk Form 20 PDF -> XLSX converter with verification + progress prints.

Kept separate from Scripts/convert_form20.py (single-file, fixed 9-candidate
version) - this file generalises to ANY candidate count / column width and
adds batch progress reporting.

What it does per PDF (digital-text extraction, NOT OCR):
  1. Extract tables with pdfplumber (lossless for digital PDFs).
  2. Auto-detect candidate count:  ncols - 7  (2 leading + 5 trailing cols).
  3. Validate: row sums + EVM totals match.
  4. Write .xlsx next to the .pdf (same basename) + Validation sheet.
  5. Re-load the .xlsx and verify row counts / spot values (post-save check).
  6. On validation failure: write <name>.REVIEW.xlsx (quarantine) instead.

Usage:
  python Scripts/bulk_convert_form20.py --root 2024
  python Scripts/bulk_convert_form20.py --root 2024 --exclude "2024/Agra/2024091321.pdf"
  python Scripts/bulk_convert_form20.py --root 2024 --no-skip-existing --exclude "2024/Agra/*"

Flags:
  --root            folder to scan recursively for *.pdf (default: 2024)
  --exclude         repeatable glob / path to skip (matched against path as-given
                    AND relative to --root AND absolute). Default: none.
  --skip-existing / --no-skip-existing   skip PDFs whose .xlsx already exists
                    and is newer than the .pdf (default: skip).
  --report          CSV report path (default: <root>/bulk_convert_report.csv)
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import re
import sys
import time
import traceback
from pathlib import Path

import pdfplumber
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------- helpers

# openpyxl rejects C0 control chars in cell strings - strip them everywhere.
ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

NUM_RE = re.compile(r"^-?\d+$")

TRAILER_PHRASES = ("total of", "total no", "rejected", "nota",
                   "tender", "votes for nota")


def clean(cell):
    if cell is None:
        return None
    t = cell.replace("\n", " ").strip()
    t = re.sub(r"\s+", " ", t)
    t = ILLEGAL_CHARS_RE.sub("", t)
    if not t or is_num(t):
        return t or None
    return maybe_unmirror(t) or None


def maybe_unmirror(t):
    """Some PDFs store text strings fully mirrored (e.g. 'hselihkA vadaY'
    for Akhilesh Yadav, '.oN laireS' for Serial No.). If the reversed
    string scores clearly more English than the forward one, restore it.
    Numbers and genuine Devanagari are never touched."""
    if re.search(r"[\u0900-\u097F]", t):
        return t
    toks = re.findall(r"[A-Za-z]{3,}", t)
    if not toks:
        return t
    fwd = sum(1 for w in toks if w.lower() in ENGLISH_WORDS)
    rev = sum(1 for w in toks if w[::-1].lower() in ENGLISH_WORDS)
    if rev > fwd and rev >= 1:
        return t[::-1]
    return t


def is_num(s):
    return s is not None and bool(NUM_RE.match(str(s).strip()))


def is_header_row(row) -> bool:
    joined = " ".join(c or "" for c in row)
    low = joined.lower()
    return (
        ("serial" in low and "polling" in low)
        or "valid votes" in low  # covers 'No of Valid ...' and 'No. of Valid votes ...'
        or "polling station no" in low
        or "fof/kekU" in joined  # Hindi-encoded Form 20 header (e.g. Maharajganj)
        or "LFky" in joined
    )


def is_column_index_row(row) -> bool:
    """Helper row of sequential column numbers, e.g. ['1','2','3',...],
    ['1', '', '2','3','4',...] or ['1', '1', '2','3',...] (serial duplicated).
    Never booth data (booth rows always carry a name/text cell or large
    vote counts, never exactly 1..k)."""
    try:
        seq = [(c or "").strip() for c in row if (c or "").strip() != ""]
        if len(seq) < 5:
            return False
        if all(s == str(i + 1) for i, s in enumerate(seq)):
            return True
        # duplicate-serial form: ['1','1','2','3',...]
        if seq[0] == "1" and seq[1] == "1" \
                and all(s == str(i + 1) for i, s in enumerate(seq[1:])):
            return True
        return False
    except IndexError:
        return False


def names_look_plausible(names) -> bool:
    """Candidate-name cells must be actual names, never header labels or
    blanks. Guards against capturing 'No of Valid Votes…' as a candidate."""
    filled = [c for c in names if (c or "").strip()]
    if len(filled) < 2:
        return False
    bad_re = re.compile(r"valid votes|serial no|polling station|rejected|"
                         r"tendered|^total$|^nota$", re.I)
    return not any(bad_re.search(c or "") for c in filled)


def find_trailer_start(row, lead: int):
    """Index of first trailing-total column ('Total of Valid Votes',
    'Total No. of valid votes', 'No. of Rejected Votes', NOTA, ...).
    Returns None if this row has no trailer labels."""
    for i in range(lead, len(row)):
        low = (row[i] or "").lower()
        if any(p in low for p in TRAILER_PHRASES):
            return i
    return None


def is_evm_row(label: str) -> bool:
    if not label:
        return False
    if "Total EVM" in label:
        return True
    # Hindi-encoded ECI PDFs: EVM total mentions recorded-votes-at-station;
    # postal rows ('Mkd...' = Dak) and grand totals ('egk...') must NOT match.
    return "vfHkfyf[kr" in label and "Mkd" not in label and "egk" not in label


def is_postal_row(label: str, row) -> bool:
    if "Postal" in (label or "") or "To be filled" in " ".join(c or "" for c in row):
        return True
    return (label or "").startswith("Mkd")


# Words for telling mirrored-English PDF text apart from legacy-encoded
# (DevLys/Kruti-era) Hindi. A mirrored token reversed must be one of these
# (or plain Titlecase English); legacy-decoded-reversed tokens never are.
ENGLISH_WORDS = frozenset("""
congress national nationalist bharatiya janata samajwadi bahujan party
communist aam aadmi shiv sena akali dal lok jan shakti rashtriya samta
singh kumar devi lal ram prasad yadav sharma verma gupta mishra patel
tiwari dubey chaudhary choudhary khan ali ahmad ahmed hussain mohammad
mohammed mohd abdul rahman anil sunil vijay ajay sanjay rajesh suresh
ramesh rakesh mukesh dinesh mahesh rajendra narendra narender virendra
jitendra surendra chandra prakash kishori kishore nand nanhe smriti
irani chauhan maurya pasi rana danish kanwar kunwar tanwar amroha indian
room school vidhyalay vidyalaya composite primary prathmik inter college
number nota none above nada patel maurya gautam khatik kumar shukla
yadav pal maurya mehta meena kumari sita gita rita babu lal chand saran
swami nath mishra pandey pathak singh chauhan tomar tomar tomar rana
rawat negi bisht mehra upadhyay sharma joshi pandit pandey kashyap
nishad bind kewat mallah rajbhar chauhan paswan manjhi sahni das ram
paswan indian national congress samajwadi bahujan samaj bharatiya janata
independant independent nota total valid votes polled tendered rejected
assembly parliament lok sabha vidhan polling station booth form final
result sheet election commission india uttar pradesh up agra aligarh
amroha amethi auraiya ayodhya azamgarh baghpat bahraich ballia balrampur
banda barabanki bareilly basti bhadohi bijnor budaun bulandshahr chandauli
deoria etah etawah farrukhabad fatehpur firozabad ghaziabad ghazipur gonda
gorakhpur hamirpur hapur hardoi hathras jalaun jaunpur jhansi kannauj
kanpur kasganj kaushambi kheri kushinagar lucknow maharajganj mahoba
mainpuri mathura mau meerut mirzapur moradabad muzaffarnagar pilibhit
pratapgarh prayagraj raebareli rampur saharanpur sambhal sant kabir
shahjahanpur shamli shrawasti siddharthnagar sitapur sultanpur unnao
varanasi doctor adv advocate alias urf son wife daughter mohan sohan
rohan kishan kisan majdoor vyapari neta manoj rajiv sanjeev rajiv gandhi
akhilesh imran zafar bin sen raj roy dev subrat jila jeet bharatiy vidhan booth sankhya
matdan sthal nirvachan aayog serial number name station valid votes favour
following total rejected nota tendered form final result sheet rule
""".split())

# Chars that never occur in English/Unicode-Hindi names but are typical
# legacy-font glyph codes (DevLys/Kruti-era Hindi PDFs).
LEGACY_GLYPH_RE = re.compile(r"[¡-¿ƒ„…†‡ˆ‰Š‹ŒžŸ«»½¼¾^~`öäüÖÄÜ€Ææ]")


def looks_legacy_encoded(candidate_names) -> bool:
    """True if candidate-name cells look like legacy-font (DevLys/Kruti-era)
    codes that would come out corrupt, e.g. 'dqjoj nkfu'k vyh' instead of
    'कंवर सिंह तंवर'. Real Devanagari or plain/mirrored English -> False."""
    s = " ".join(candidate_names or [])
    if not s.strip():
        return False
    if re.search(r"[\u0900-\u097F]", s):
        return False  # genuine Unicode Devanagari - keep as-is, convertible
    if LEGACY_GLYPH_RE.search(s):
        return True
    if not any(c.islower() for c in s):
        return False  # pure UPPER/league-numbers = English
    toks = [t.strip("'") for t in re.findall(r"[A-Za-z']+", s)]
    toks = [t for t in toks if len(t) >= 4]
    if len(toks) < 3:
        return False
    hit = sum(1 for t in toks
              if t.lower() in ENGLISH_WORDS or t[::-1].lower() in ENGLISH_WORDS)
    return (hit / len(toks)) < 0.34


def extract_title_info(pdf_path: Path) -> dict:
    info = {"form": "FORM 20", "sheet": "FINAL RESULT SHEET",
            "election": "", "electors": "", "assembly": ""}
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        return info
    for line in (l.strip() for l in text.splitlines() if l.strip()):
        if "FORM 20" in line:
            info["form"] = "FORM 20"
        elif "FINAL RESULT SHEET" in line:
            info["sheet"] = "FINAL RESULT SHEET"
        elif "HOUSE OF PARLIAMENT" in line:
            info["election"] = line
        elif "Total No. of Electors" in line:
            info["electors"] = line
        elif "Name of Assembly" in line:
            info["assembly"] = line
    if not info["election"] and not info["electors"]:
        info["election"] = pdf_path.stem  # Hindi-encoded PDFs: fall back to filename
    return info


def extract_form20(pdf_path: Path) -> dict:
    """Dynamic extraction. Returns dict(pages, ncols, lead, trailer, ncands,
    candidates, data_rows, summary_rows). Raises on layout failure.

    Layouts handled:
      * Parliament Form 20: 2 leading cols (S.No, PS No), two-row header,
        candidate names in a dedicated row  -> lead=2.
      * Assembly Form 20 (e.g. Amethi): 3 leading cols (S.No, PS No,
        PS Name), single-row header with names inline -> lead=3.
      * Hindi-encoded PDFs: same geometry, garbled text.
    """
    candidates = None
    lead = 2
    trailer = None  # first trailing-total column index; default ncols-5
    ncols = 0
    n_tables = 0
    n_textchars = 0
    n_alphawords = 0
    data_rows: list[list] = []
    summary_rows: list[list] = []
    npages = 0

    with pdfplumber.open(str(pdf_path)) as pdf:
        npages = len(pdf.pages)
        for page in pdf.pages:
            try:
                _tx = page.extract_text() or ""
            except Exception:
                _tx = ""
            n_textchars += len(_tx)
            n_alphawords += len(re.findall(r"[A-Za-z]{3,}", _tx))
            tables = [t for t in page.extract_tables() if t]
            if not tables:
                continue
            n_tables += len(tables)
            tbl = max(tables, key=lambda t: len(t))  # largest table on page
            tbl = [[clean(c) for c in r] for r in tbl]
            if not tbl:
                continue
            ncols = max(ncols, max(len(r) for r in tbl))
            for row in tbl:
                raw_len = len(row)
                if len(row) < ncols:
                    row = row + [None] * (ncols - len(row))
                # Last-page summary rows often merge the first two cols
                # (e.g. 14 cells vs 15): insert placeholder at idx 1 to
                # realign vote columns before any further handling.
                label0 = ((row[0] or "").strip())
                if label0 and not re.match(r"^\d+$", label0) and raw_len == ncols - 1 \
                        and any(is_num(c) for c in row[1:]):
                    row = [row[0], None] + row[1:]
                    row = row[:ncols]
                    label0 = ((row[0] or "").strip())
                # Case B: single-row header (Assembly layout and mirrored /
                # single-serial variants) - candidate names inline, e.g.
                # [Serial No., ...Polling Station, Name Of Polling Station,
                # CAND1, ..., Total of Valid ...]. Fires only when trailer
                # labels sit inline in the same row (a two-row header whose
                # col0 happens to read 'Serial No.' has none and must NOT
                # fire) and the name block is plausible.
                if candidates is None and is_header_row(row) \
                        and re.search(r"serial", row[0] or "", re.I):
                    t = find_trailer_start(row, 3)
                    l = 3 if any(re.search(r"name", c or "", re.I)
                                 and re.search(r"polling|station", c or "", re.I)
                                 for c in row[1:4]) else 2
                    if row[2] and re.search(r"name", row[2] or "", re.I) \
                            and re.search(r"polling|station", row[2] or "", re.I):
                        l = 3
                    names = [(c or "") for c in row[l:t if t is not None else ncols - 5]]
                    if t is not None and names_look_plausible(names):
                        candidates = names
                        lead = l
                        trailer = t
                    continue
                # Case A: dedicated candidate-name row with empty first cell,
                # e.g. [None, '', name1, name2, ...] (Parliament, lead=2),
                # ['', name1, name2, ...] (single-serial sheets, lead=1,
                # e.g. Azamgarh), or ['', '', name1, ...] (Hindi, lead=2).
                # The first non-empty, non-numeric cell anchors the block.
                # Attempted BEFORE the header skip: candidate rows on some
                # sheets (Ambedkar 1310) carry inline trailer labels, which
                # also trip the header test. Plausibility decides.
                if candidates is None and not (row[0] or "").strip():
                    start = None
                    for i in range(1, ncols):
                        c = (row[i] or "").strip()
                        if c and not is_num(c):
                            start = i
                            break
                    if start is not None:
                        t = find_trailer_start(row, start)
                        end = t if t is not None else ncols - 5
                        names = [(c or "") for c in row[start:end]]
                        if names_look_plausible(names) \
                                and not is_column_index_row(row):
                            candidates = names
                            lead = start
                            if t is not None:
                                trailer = t
                            continue
                if is_header_row(row) or is_column_index_row(row):
                    continue
                label = (row[0] or "").strip()
                # Page-footer contamination: the last booth row of each page
                # often absorbs footer text. Variant 1: col0='24 Page',
                # col1='24 1' (booth 24, page 1). Variant 2: the word 'Page'
                # shatters across cells, e.g. col0='P 54', col1='ag 54',
                # col2='e 1 17' (booth 54, page 1, cand-1 votes 17).
                # Restore the pure numbers; validation judges the result.
                m0 = re.match(r"^(\d+)\s*Pages?\s*\d*\s*$", label, re.I) \
                    or re.match(r"^(\d+)\s*Pag\s*\d*\s*$", label, re.I)
                if m0:
                    row[0] = m0.group(1)
                    label = row[0]
                    m1 = re.match(r"^(\d+)\s+\d+\s*$", (row[1] or "").strip())
                    if m1:
                        row[1] = m1.group(1)
                else:
                    m0 = re.match(r"^P\s+(\d+)$", label)
                    m1 = re.match(r"^ag\s+(\d+)$", (row[1] or "").strip())
                    m2 = re.match(r"^e\s+\d+\s+(\d+)$", str(row[2] or "").strip())
                    if m0 and m1 and m2 and m0.group(1) == m1.group(1):
                        row[0] = m0.group(1)
                        row[1] = m1.group(1)
                        row[2] = m2.group(1)
                        label = row[0]
                # Variant 2b (runs regardless of the col0 branch above):
                # clean serial in col0, footer shatter in col1/col2, e.g.
                # ['260','260 e 1','19 0',...] (booth 260, page 10 as
                # '1'+'0'). First number of the fused pair is the vote;
                # validation judges the result.
                m1b = re.match(r"^(\d+)\s*e\s*\d+\s*$",
                               (row[1] or "").strip())
                m2b = re.match(r"^(\d+)\s+\d+\s*$",
                               str(row[2] or "").strip())
                if label and re.match(r"^\d+$", label) and m1b and m2b \
                        and label == m1b.group(1):
                    row[1] = m1b.group(1)
                    row[2] = m2b.group(1)
                vote_cells = row[lead:]
                has_numbers = any(is_num(c) for c in vote_cells)
                if label and re.match(r"^\d+$", label) and has_numbers:
                    data_rows.append(row[:ncols])
                elif has_numbers and label:
                    # summary row (Total EVM / Total Votes Polled / Hindi labels)
                    # but guard: candidate-name rows already handled above
                    if candidates is not None:
                        summary_rows.append(row[:ncols])
                # else: stray/empty row -> ignore

    if n_tables == 0:
        if n_textchars < 500 or n_alphawords < 25:
            raise RuntimeError("no extractable tables (scanned-image PDF - needs OCR)")
        raise RuntimeError("tables not detected by ruling lines (layout changed?)")
    if candidates is None:
        raise RuntimeError("candidate header row not found - layout changed?")
    if trailer is None:
        trailer = ncols - 5
    ncands = trailer - lead
    if ncands <= 0 or trailer + 5 > ncols + 1:
        raise RuntimeError(f"implausible geometry: ncols={ncols} lead={lead} "
                           f"trailer={trailer}")
    if len(candidates) != ncands:
        # trim/pad defensively, validation will catch real problems
        candidates = (candidates + [""] * ncands)[:ncands]
    return {"pages": npages, "ncols": ncols, "lead": lead, "trailer": trailer,
            "ncands": ncands, "candidates": candidates, "data": data_rows,
            "summary": summary_rows}


def find_serial_gaps(info: dict) -> list[int]:
    """Booth serials absent from min..max (lost pages / footer-diverted rows
    / deleted booths). Purely descriptive - callers decide severity."""
    nums: list[int] = []
    for r in info["data"]:
        s = ((r[0] if len(r) > 0 else None) or "").strip()
        if re.match(r"^\d+$", s):
            nums.append(int(s))
    if not nums:
        return []
    return sorted(set(range(min(nums), max(nums) + 1)) - set(nums))


def count_serial_starts(info: dict) -> int:
    """How many data rows carry serial '1' - >1 means several AC segments
    are concatenated in one PDF (multi-AC file)."""
    return sum(1 for r in info["data"] if ((r[0] or "").strip()) == "1")


def validate_extraction(info: dict) -> list[str]:
    errors: list[str] = []
    lead, trailer, ncands = info["lead"], info["trailer"], info["ncands"]
    data, summary = info["data"], info["summary"]
    c0, c_valid, c_nota, c_total = lead, trailer, trailer + 2, trailer + 3
    if not data:
        return ["no booth data rows extracted"]
    for r in data:
        try:
            s = sum(int(r[c] or 0) for c in range(c0, c0 + ncands) if is_num(r[c]) or r[c] is None)
            # strict: every candidate cell must be numeric
            for c in range(c0, c0 + ncands):
                if not is_num(r[c]):
                    raise ValueError(f"col {c}={r[c]!r}")
            valid = int(r[c_valid] or 0)
            nota = int(r[c_nota] or 0)
            total = int(r[c_total] or 0)
        except (ValueError, IndexError):
            errors.append(f"row {r[0]}: non-numeric vote cell: {r[c0:c0+ncands]}")
            continue
        if s != valid:
            errors.append(f"row {r[0]}: sum(cands)={s} != valid={valid}")
        if valid + nota != total:
            errors.append(f"row {r[0]}: valid {valid}+nota {nota} != total {total}")
    evm = next((s for s in summary if is_evm_row(s[0] or "")), None)
    notes: list[str] = info.setdefault("_notes", [])  # type: ignore[union-attr]
    if evm is not None:
        for c in list(range(c0, c0 + ncands)) + [c_valid, c_nota, c_total]:
            try:
                s = sum(int(r[c] or 0) for r in data)
                e = int(evm[c] or 0)
            except (ValueError, IndexError):
                errors.append(f"col {c}: non-numeric booth cells present - "
                              f"fix flagged rows first; EVM check skipped "
                              f"for col {c}")
                continue
            if s != e:
                errors.append(f"EVM total mismatch col {c}: booth-sum={s} vs evm={e}")
    else:
        notes.append("EVM total row not found (label unmatched) - "
                     "AC-totals cross-check skipped; row-math only")
    # Missing booth rows: descriptive note always (missing serials explain
    # an EVM shortfall); only row-math / EVM-mismatch entries fail the file.
    gaps = find_serial_gaps(info)
    if gaps:
        notes.append(f"missing serial rows (booths absent from 1..max): "
                     f"{gaps[:30]}{'...' if len(gaps) > 30 else ''} "
                     f"({len(gaps)} booths absent - lost pages, footer "
                     f"diversion, or deleted booths)")
    n_starts = count_serial_starts(info)
    if n_starts > 1:
        notes.append(f"multi-AC file: serial '1' appears {n_starts}x - "
                     f"several AC segments concatenated; split per AC "
                     f"before downstream use")
    return errors


# ---------------------------------------------------------------- workbook

def build_workbook(pdf_path: Path, title: dict, info: dict) -> Workbook:
    ncols, ncands, lead, trailer = (info["ncols"], info["ncands"],
                                    info["lead"], info["trailer"])
    candidates, data, summary = info["candidates"], info["data"], info["summary"]
    last_col = get_column_letter(ncols)
    lead_letter = get_column_letter(lead)  # A..B (lead=2) or A..C (lead=3)
    cand_end = get_column_letter(lead + ncands)  # 1-based last candidate col

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

    ws.merge_cells(f"A1:{last_col}1"); ws["A1"] = title.get("form", "FORM 20")
    ws.merge_cells(f"A2:{last_col}2"); ws["A2"] = title.get("sheet", "FINAL RESULT SHEET")
    ws.merge_cells(f"A3:{last_col}3"); ws["A3"] = title.get("election", "")
    ws.merge_cells(f"A4:{last_col}4"); ws["A4"] = title.get("electors", "")
    ws.merge_cells(f"A5:{last_col}5"); ws["A5"] = title.get("assembly", "")
    ws.merge_cells(f"A6:{last_col}6"); ws["A6"] = f"Source file: {pdf_path.name}"
    for r in range(1, 7):
        ws[f"A{r}"].font = title_font if r <= 2 else Font(bold=True, size=10)
        ws[f"A{r}"].alignment = center
        ws.row_dimensions[r].height = 18 if r > 2 else 22

    H1, H2 = 7, 8
    ws.merge_cells(f"A7:{lead_letter}7"); ws["A7"] = "Serial No. Of Polling Station"
    ws.merge_cells(f"{get_column_letter(lead + 1)}{H1}:{cand_end}{H1}")
    ws.cell(row=H1, column=lead + 1, value="No of Valid Votes Cast in favour of")
    trailers = ["Total of Valid Votes", "No. Of Rejected Votes",
                "Votes for NOTA", "Total", "No. Of Tendered Votes"]
    for k, txt in enumerate(trailers):
        ws.cell(row=H1, column=trailer + 1 + k, value=txt)
    ws.cell(row=H2, column=1, value="Serial No.")
    if lead == 3:
        ws.cell(row=H2, column=2, value="Polling Station No.")
        ws.cell(row=H2, column=3, value="Polling Station Name")
    else:
        ws.cell(row=H2, column=2, value="Polling Station No. / Name")
    for i, name in enumerate(candidates):
        ws.cell(row=H2, column=lead + 1 + i, value=name)
    for col in range(1, ncols + 1):
        for r in (H1, H2):
            c = ws.cell(row=r, column=col)
            c.font = hdr_font; c.alignment = center; c.fill = hdr_fill; c.border = border
    ws.row_dimensions[H1].height = 30
    ws.row_dimensions[H2].height = 45

    r0 = 9
    for i, row in enumerate(data):
        rr = r0 + i
        for col in range(1, ncols + 1):
            v = row[col - 1]
            c = ws.cell(row=rr, column=col)
            # leading cols may be booth NAME text - store as-is
            c.value = int(v) if is_num(v) else v
            c.font = norm_font; c.alignment = center; c.border = border
        ws.row_dimensions[rr].height = 15

    sr = r0 + len(data)
    evm = next((s for s in summary if is_evm_row(s[0] or "")), None)
    if evm is not None:
        ws.merge_cells(f"A{sr}:{lead_letter}{sr}")
        ws.cell(row=sr, column=1, value=evm[0]).font = hdr_font
        for col in range(lead + 1, ncols + 1):
            v = evm[col - 1]
            c = ws.cell(row=sr, column=col, value=int(v) if is_num(v) else v)
            c.font = hdr_font; c.alignment = center; c.border = border
            c.fill = PatternFill("solid", fgColor="FFF2CC")
        for cc in range(1, lead + 1):
            ws.cell(row=sr, column=cc).alignment = center
            ws.cell(row=sr, column=cc).border = border
            ws.cell(row=sr, column=cc).fill = PatternFill("solid", fgColor="FFF2CC")
        sr += 1
    # any other summary rows (postal notes, Hindi totals, Total Votes Polled)
    for s in summary:
        if evm is not None and s is evm:
            continue
        if is_postal_row(s[0] or "", s) and not any(is_num(c) for c in s[lead:]):
            ws.merge_cells(f"A{sr}:{last_col}{sr}")
            note = s[lead] or "Postal ballot votes"
            ws.cell(row=sr, column=1,
                    value=f"Total Postal Ballot Votes: {note}").font = Font(italic=True, size=10)
            ws.cell(row=sr, column=1).alignment = left_c
            sr += 1
        elif any(is_num(c) for c in s[lead:]):
            ws.merge_cells(f"A{sr}:{lead_letter}{sr}")
            ws.cell(row=sr, column=1, value=s[0]).font = hdr_font
            for col in range(lead + 1, ncols + 1):
                v = s[col - 1] if col - 1 < len(s) else None
                c = ws.cell(row=sr, column=col, value=int(v) if is_num(v) else v)
                c.font = hdr_font; c.alignment = center; c.border = border
                c.fill = PatternFill("solid", fgColor="D9E1F2")
            for cc in range(1, lead + 1):
                ws.cell(row=sr, column=cc).alignment = center
                ws.cell(row=sr, column=cc).border = border
                ws.cell(row=sr, column=cc).fill = PatternFill("solid", fgColor="D9E1F2")
            sr += 1

    widths = ([10, 22] if lead == 2 else [10, 14, 26]) + [16] * ncands + [13, 12, 10, 10, 12]
    for i, w in enumerate(widths[:ncols], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A9"
    ws.auto_filter.ref = f"A{H1}:{last_col}{r0 + len(data) - 1}"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "7:8"

    ws2 = wb.create_sheet("Validation")
    ws2["A1"] = f"Source: {pdf_path.name}"
    ws2["A2"] = f"Booth rows extracted: {len(data)}"
    ws2["A3"] = f"Candidates ({ncands}): {', '.join(candidates)}"
    ws2["A4"] = "Row-level check: sum(candidates)==Total Valid AND Valid+NOTA==Total"
    ws2["A5"] = "EVM-total check: sum(booth rows) per column vs Total EVM row (if present)"
    for cell in ["A1", "A2", "A3", "A4", "A5"]:
        ws2[cell].font = Font(size=10)
    ws2.column_dimensions["A"].width = 130
    return wb


def verify_saved_xlsx(xlsx: Path, info: dict) -> list[str]:
    """Post-save check: reload workbook, compare counts + first/last rows."""
    errs: list[str] = []
    try:
        wb = load_workbook(str(xlsx), data_only=True)
        ws = wb["Form20"]
        ncols, data = info["ncols"], info["data"]
        r0 = 9
        n_rows = ws.max_row
        # count booth rows = first col numeric from row 9
        found = 0
        r = r0
        while r <= n_rows and ws.cell(r, 1).value is not None \
                and re.match(r"^\d+$", str(ws.cell(r, 1).value).strip()):
            found += 1
            r += 1
        if found != len(data):
            errs.append(f"saved-row count {found} != extracted {len(data)}")
        for idx in [0, len(data) - 1]:
            if len(data) == 0:
                break
            rr = r0 + idx
            for col in range(1, ncols + 1):
                v = ws.cell(rr, col).value
                v = str(v) if v is not None else None
                e = data[idx][col - 1]
                if v != e:
                    errs.append(f"saved cell r{rr}c{col}: xlsx={v!r} pdf={e!r}")
                    break
    except Exception as ex:
        errs.append(f"reload failed: {ex}")
    return errs


# ---------------------------------------------------------------- batch

def matches_exclude(p: Path, root: Path, patterns: list[str]) -> bool:
    strs = [str(p), str(p.as_posix())]
    try:
        strs.append(str(p.relative_to(root)))
        strs.append(str(p.relative_to(root).as_posix()))
    except ValueError:
        pass
    strs.append(p.name)
    for pat in patterns:
        for s in strs:
            if fnmatch.fnmatch(s, pat) or s == pat:
                return True
    return False


def convert_one(pdf: Path, skip_existing: bool = True) -> dict:
    """Returns result dict. Prints progress lines (flush) for live monitoring."""
    res = {"pdf": str(pdf), "status": "", "booths": 0, "ncands": 0,
           "pages": 0, "xlsx": "", "error": "", "secs": 0.0}
    t0 = time.time()
    xlsx = pdf.with_suffix(".xlsx")
    if skip_existing and xlsx.exists() and xlsx.stat().st_mtime >= pdf.stat().st_mtime:
        print(f"  SKIP   existing up-to-date -> {xlsx.name}", flush=True)
        res.update(status="SKIPPED", xlsx=str(xlsx))
        return res
    try:
        print(f"  READ   {pdf.name} ({pdf.stat().st_size // 1024} KB) ...", flush=True)
        title = extract_title_info(pdf)
        info = extract_form20(pdf)
        res.update(booths=len(info["data"]), ncands=info["ncands"], pages=info["pages"])
        print(f"  PARSE  pages={info['pages']} cols={info['ncols']} "
              f"candidates={info['ncands']} booths={len(info['data'])} "
              f"summary={len(info['summary'])}", flush=True)
        print(f"         candidates: {', '.join(info['candidates'][:6])}"
              f"{' ...' if len(info['candidates']) > 6 else ''}", flush=True)

        if looks_legacy_encoded(info["candidates"]):
            print("  SKIP   legacy Hindi font (DevLys/Kruti-era codes) - names "
                  "would come out corrupt, so no xlsx is written", flush=True)
            res.update(status="LEGACY_SKIP", xlsx="",
                       error="legacy-encoded Hindi names; skipped, not converted",
                       secs=time.time() - t0)
            return res

        errors = validate_extraction(info)
        if errors:
            print(f"  VERIFY FAIL ({len(errors)}): {errors[0]}", flush=True)
            for e in errors[1:4]:
                print(f"           - {e}", flush=True)
            review = pdf.with_name(pdf.stem + ".REVIEW.xlsx")
            wb = build_workbook(pdf, title, info)
            wb["Validation"]["A6"] = (f"Validation: FAIL ({len(errors)} error(s)). "
                                      "See console/report. File quarantined for manual review.")
            wb["Validation"]["A6"].font = Font(bold=True, size=11, color="9C0006")
            r = 7
            for e in errors[:50]:
                wb["Validation"][f"A{r}"] = e
                r += 1
            for n in info.get("_notes", []):
                wb["Validation"][f"A{r}"] = f"NOTE: {n}"
                r += 1
            wb.save(str(review))
            res.update(status="REVIEW", xlsx=str(review),
                       error="; ".join(errors[:5]), secs=time.time() - t0)
            print(f"  QUARANTINED -> {review.name}", flush=True)
            return res

        print("  VERIFY PASS (row sums + EVM totals match)", flush=True)
        wb = build_workbook(pdf, title, info)
        wb["Validation"]["A6"] = (f"Validation: PASS ({len(info['data'])} booth rows, "
                                  "all row-sums + EVM totals match)")
        wb["Validation"]["A6"].font = Font(bold=True, size=11, color="006100")
        r = 7
        for n in info.get("_notes", []):
            wb["Validation"][f"A{r}"] = f"NOTE: {n}"
            r += 1
        wb.save(str(xlsx))

        post = verify_saved_xlsx(xlsx, info)
        if post:
            print(f"  POST-SAVE VERIFY FAIL: {post[0]}", flush=True)
            res.update(status="REVIEW", xlsx=str(xlsx),
                       error="; ".join(post[:3]), secs=time.time() - t0)
            return res
        secs = time.time() - t0
        print(f"  WROTE  {xlsx.name} ({xlsx.stat().st_size // 1024} KB) "
              f"in {secs:.1f}s + POST-SAVE VERIFIED", flush=True)
        res.update(status="OK", xlsx=str(xlsx), secs=secs)
        return res
    except Exception as ex:
        msg = str(ex)
        if "scanned-image PDF" in msg:
            print("  SKIP   scanned-image PDF (no extractable text/tables) - "
                  "needs OCR, left untouched", flush=True)
            res.update(status="SCANNED", xlsx="", error=msg,
                       secs=time.time() - t0)
            return res
        if "candidate header row not found" in msg \
                or "implausible geometry" in msg \
                or "tables not detected by ruling lines" in msg:
            try:
                if has_cid_gaps(pdf):
                    print("  SKIP   unmapped glyphs (cid:) + complex layout - "
                          "names can never be complete; manual handling",
                          flush=True)
                    res.update(status="COMPLEX_SKIP", xlsx="",
                               error="unmapped (cid:) glyphs / complex layout; "
                                     "manual handling",
                               secs=time.time() - t0)
                    return res
                if legacy_probe(pdf):
                    print("  SKIP   legacy Hindi font (DevLys/Kruti-era codes) - "
                          "names would come out corrupt, so no xlsx is written",
                          flush=True)
                    res.update(status="LEGACY_SKIP", xlsx="",
                               error="legacy-encoded Hindi names; skipped, not converted",
                               secs=time.time() - t0)
                    return res
                if garbled_ocr_probe(pdf):
                    print("  SKIP   broken OCR/text layer (interleaved runs) - "
                          "names unrecoverable; needs re-OCR or manual handling",
                          flush=True)
                    res.update(status="COMPLEX_SKIP", xlsx="",
                               error="garbled OCR/text layer; needs re-OCR or manual",
                               secs=time.time() - t0)
                    return res
                if "tables not detected by ruling lines" in msg:
                    # In this batch, ruling-less files are scans/legacy/
                    # garbled ones (verified by sampling); a clean digital
                    # table without rulings has not occurred. Route the
                    # leftovers to manual handling, not FAILED-retry.
                    # (Geometry/capture failures keep FAILED: tables exist,
                    # so parsing may still be fixable.)
                    print("  SKIP   no ruling-line tables and text unusable - "
                          "needs OCR or manual handling", flush=True)
                    res.update(status="COMPLEX_SKIP", xlsx="",
                               error="no ruling-line tables; text unusable - "
                                     "OCR/manual",
                               secs=time.time() - t0)
                    return res
            except Exception:
                pass
        print(f"  ERROR  {type(ex).__name__}: {ex}", flush=True)
        traceback.print_exc()
        res.update(status="FAILED", error=f"{type(ex).__name__}: {ex}",
                   secs=time.time() - t0)
        return res


def has_cid_gaps(pdf_path: Path) -> bool:
    """True if extracted text contains raw (cid:N) markers = glyphs whose
    characters are permanently lost (no font mapping). Names in such files
    can never be recovered by text extraction."""
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:3]:
                try:
                    if "(cid:" in (page.extract_text() or ""):
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


# Header/summary vocabulary: never candidate names, never legacy codes.
# Excluded from legacy-probe scoring so English summary tables cannot
# mask a legacy-encoded file (nor rescue it wrongly).
HEADER_VOCAB = frozenset("""
serial number name station stations polling valid votes favour following
total rejected nota tendered polled counted highest second leading
candidate candidates difference balance form final result sheet rule
favour page pages
""".split())


def legacy_probe(pdf_path: Path) -> bool:
    """Fallback when no candidate row is found: scan raw table text for
    legacy-encoded Hindi. Returns True if the file looks legacy-encoded
    (then it is SKIPPED, not FAILED). Mixed-font cells carrying genuine
    Devanagari fragments are ignored as noise. A strong forward-English
    name signal (>=3 distinct English words outside header vocabulary)
    rescues genuine English layouts. Files with no ruling-line tables
    fall back to raw page text."""
    texts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables():
                for row in tbl[:4]:
                    for c in row[1:]:
                        c = clean(c)
                        if not c or is_num(c) or len(c) < 4:
                            continue
                        if re.search(r"[\u0900-\u097F]", c) or "(cid:" in c:
                            continue
                        texts.append(c)
                        if len(texts) > 300:
                            break
        if len(texts) < 5:
            # No ruling-line tables (e.g. Shamli): use raw page text.
            # Note {3,}: legacy codes fragment on dashes/punctuation.
            for page in list(pdf.pages)[:4]:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    continue
                for w in re.findall(r"[A-Za-z'/-]{3,}", t):
                    if re.search(r"[\u0900-\u097F]", w):
                        continue
                    texts.append(w)
                    if len(texts) > 300:
                        break
    if len(texts) < 5:
        return False
    if LEGACY_GLYPH_RE.search(" ".join(texts)):
        return True
    toks = [t.strip("'") for s in texts for t in re.findall(r"[A-Za-z']+", s)]
    toks = [t for t in toks
            if len(t) >= 4 and t.lower() not in HEADER_VOCAB]
    if len(toks) < 5:
        return False
    fwd = {t.lower() for t in toks if t.lower() in ENGLISH_WORDS}
    if len(fwd) >= 3:
        return False
    hit = sum(1 for t in toks
              if t.lower() in ENGLISH_WORDS or t[::-1].lower() in ENGLISH_WORDS)
    return (hit / len(toks)) < 0.34


def garbled_ocr_probe(pdf_path: Path) -> bool:
    """True if extractable text looks like a broken OCR/text layer with
    interleaved runs (e.g. 'NumbSetra', 'Kaushaomntyb'): many tokens with
    pathological interior case flips. Such names are unrecoverable."""
    toks: list[str] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in list(pdf.pages)[:4]:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    continue
                toks += [w for w in re.findall(r"[A-Za-z]{4,}", t)
                         if w.lower() not in HEADER_VOCAB]
    except Exception:
        return False
    if len(toks) < 10:
        return False
    flips = [w for w in toks
             if re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", w)]
    return len(flips) >= 5 and len(flips) / len(toks) > 0.25


def main(argv=None) -> int:
    # Windows console defaults to cp1252: Hindi/Unicode print() calls crash
    # the whole batch (and break `> log.txt` redirection). Force UTF-8.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Bulk Form 20 PDF->XLSX with verification")
    ap.add_argument("--root", default="data/2024", help="folder to scan recursively")
    ap.add_argument("--exclude", action="append", default=[],
                    help="glob/path to skip (repeatable)")
    ap.add_argument("--only", action="append", default=[],
                    help="glob/path to include only (repeatable; matched "
                    "against relative path with either separator)")
    ap.add_argument("--skip-existing", dest="skip_existing", action="store_true",
                    default=True)
    ap.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    ap.add_argument("--report", default=None, help="CSV report path")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: root not found: {root}", flush=True)
        return 2
    all_pdfs = sorted(root.rglob("*.pdf"))
    print(f"SCAN  root={root}  found {len(all_pdfs)} PDFs", flush=True)
    if args.exclude:
        print(f"EXCLUDE patterns: {args.exclude}", flush=True)
    print(f"SKIP-EXISTING: {'ON' if args.skip_existing else 'OFF'}", flush=True)

    todo = [p for p in all_pdfs
            if not matches_exclude(p, root, args.exclude)]
    skipped_by_excl = len(all_pdfs) - len(todo)
    if args.only:
        def _match(rel, pat):
            return (fnmatch.fnmatch(rel, pat)
                    or fnmatch.fnmatch(rel.replace("\\", "/"), pat))
        todo = [p for p in todo
                if any(_match(str(p.relative_to(root))
                              if p.is_relative_to(root) else str(p), q)
                       for q in args.only)]
        print(f"ONLY patterns: {args.only} -> {len(todo)} files", flush=True)
    print(f"PLAN  to-process={len(todo)}  excluded={skipped_by_excl}", flush=True)
    if not todo:
        print("Nothing to do.", flush=True)
        return 0

    report_path = Path(args.report) if args.report else (root / "bulk_convert_report.csv")
    results: list[dict] = []
    t_all = time.time()
    for i, pdf in enumerate(todo, start=1):
        rel = pdf.relative_to(root) if pdf.is_relative_to(root) else pdf
        print(f"[{i}/{len(todo)}] START {rel}", flush=True)
        res = convert_one(pdf, skip_existing=args.skip_existing)
        res["rel"] = str(rel)
        results.append(res)
        print(f"[{i}/{len(todo)}] DONE  {rel} -> {res['status']} "
              f"({res['secs']:.1f}s)", flush=True)

    ok = sum(1 for r in results if r["status"] == "OK")
    skipped = sum(1 for r in results if r["status"] == "SKIPPED")
    legacy = sum(1 for r in results if r["status"] == "LEGACY_SKIP")
    scanned = sum(1 for r in results if r["status"] == "SCANNED")
    complex_ = sum(1 for r in results if r["status"] == "COMPLEX_SKIP")
    review = sum(1 for r in results if r["status"] == "REVIEW")
    failed = sum(1 for r in results if r["status"] == "FAILED")
    total_s = time.time() - t_all
    print("=" * 70, flush=True)
    print(f"SUMMARY  total={len(results)}  OK={ok}  SKIPPED={skipped}  "
          f"LEGACY_SKIP={legacy}  SCANNED={scanned}  COMPLEX_SKIP={complex_}  "
          f"REVIEW={review}  FAILED={failed}  elapsed={total_s:.0f}s", flush=True)
    bad = [r for r in results if r["status"] in ("REVIEW", "FAILED")]
    if bad:
        print("NEEDS ATTENTION:", flush=True)
        for r in bad[:30]:
            print(f"  - {r['rel']}: [{r['status']}] {r['error']}", flush=True)
    leg = [r for r in results if r["status"] == "LEGACY_SKIP"]
    if leg:
        print(f"LEGACY-SKIPPED ({len(leg)} files, Hindi legacy font - names left "
              f"untouched, convert manually):", flush=True)
        for r in leg:
            print(f"  - {r['rel']}", flush=True)
    for tag, statuses in (("SCANNED (needs OCR)",
                           ["SCANNED"]),
                          ("COMPLEX-SKIP (unmapped glyphs/complex layout, manual)",
                           ["COMPLEX_SKIP"])):
        grp = [r for r in results if r["status"] in statuses]
        if grp:
            print(f"{tag} ({len(grp)} files):", flush=True)
            for r in grp[:40]:
                print(f"  - {r['rel']}", flush=True)

    # merge with any existing report FIRST (read before truncating!)
    # so targeted runs (--only/--exclude) never drop other files' rows
    merged: dict = {}
    if report_path.exists():
        try:
            with open(report_path, newline="", encoding="utf-8") as rf:
                for row in csv.DictReader(rf):
                    if row.get("rel"):
                        merged[row["rel"]] = row
        except Exception:
            pass
    for r in results:
        merged[r.get("rel", "")] = \
            {k: r.get(k, "") for k in
             ["rel", "pdf", "pages", "ncands", "booths",
              "status", "xlsx", "error", "secs"]}
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["rel", "pdf", "pages", "ncands",
                                          "booths", "status", "xlsx", "error", "secs"])
        w.writeheader()
        for rel in sorted(merged):
            w.writerow(merged[rel])
    print(f"REPORT written -> {report_path}", flush=True)
    return 1 if (failed or review) else 0


if __name__ == "__main__":
    sys.exit(main())
