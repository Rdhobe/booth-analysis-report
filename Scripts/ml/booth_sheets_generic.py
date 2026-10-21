"""Fallback reader for ECI booth sheets whose columns sit in unusual places.

``Scripts/report/agra_pipeline.py: ingest_eci`` expects fixed column positions. About 90 sheets are the same ECI table with a
shifted layout (an extra blank column, electors split over four columns, "Votes Se cured" typos, the party written in the header
row instead of the data rows). This reader finds each column by its label instead.

It is only used for files the main parser cannot read, and everything it returns goes through the same gates as the main parser's
output (turnout range, reconciliation with official totals). It returns ``None`` when a sheet does not look like a booth table.
"""
from __future__ import annotations

import re

VOTES_RE = re.compile(r"vot(?:e|er)s?\W*se\W*cured", re.I)           # Votes Secured / Voters Secured / Votes Se cured / Votes Se-cured
NOTA_RE = re.compile(r"nota|none of the above", re.I)
ELECTORS_RE = re.compile(r"elector|total\s*no\.?\s*of\s*voters|total\s*voters", re.I)       # 'Total No of Voters' means electors on some sheets
TURNOUT_RE = re.compile(r"turn\s*out|yurn\s*out|voters?\s*cast|number of pers|persons who", re.I)
PS_NAME_RE = re.compile(r"^\s*(\d+)\s*[-\u2013.]\s*\S")                                   # "1-PRIMARY SCHOOL ..." (polling-station number inside the name)
PREAMBLE_RE = re.compile(r"elector[^0-9]{0,90}?(\d[\d,]{4,})", re.I)
GENERIC_HEADER = re.compile(r"^(s\.?\s*no\.?-?\d*|sl\.?\s*no\.?|party affil\w*|affiliation|votes? secured|voters? secured|\d+)$", re.I)


def _txt(v) -> str:
    return re.sub(r"\s+", " ", str("" if v is None else v)).strip()


def _num(v):
    """Number from an int/float/numeric string, else None (booleans and text are not numbers)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def _is_helper(vals: list) -> bool:
    """The 1, 2, 3, ... column-number row printed under the header."""
    nums = [_num(v) for v in vals if _num(v) is not None]
    return len(nums) >= 5 and max(nums) <= 70 and all(float(i) == n for i, n in enumerate(nums, start=nums[0] if nums else 1))


def _row(sh, r: int) -> list:
    return [sh.cell(r, c).value for c in range(sh.ncols)]


def parse_sheet(sh) -> dict | None:
    nr, nc = sh.nrows, sh.ncols
    if nr < 20 or nc < 8:
        return None
    # 1. the label row: first row mentioning electors
    lab_r = next((r for r in range(min(10, nr)) if any(ELECTORS_RE.search(_txt(sh.cell(r, c).value)) for c in range(nc))), None)
    if lab_r is None:
        return None
    # 2. first data row: several numbers, at least one over 100 (electors), and not the 1,2,3... helper row
    data0 = None
    for r in range(lab_r + 1, min(lab_r + 8, nr)):
        vals = _row(sh, r)
        nums = [_num(v) for v in vals[:12] if _num(v) is not None]
        if len(nums) >= 5 and max(nums) >= 100 and not _is_helper(vals):
            data0 = r
            break
    if data0 is None:
        return None
    hdr_rows = range(max(0, lab_r - 1), data0)
    label = [" ".join(_txt(sh.cell(r, c).value) for r in hdr_rows).lower() for c in range(nc)]

    # 3. electors and turnout columns
    elec_cands = [c for c in range(nc) if ELECTORS_RE.search(label[c])]
    data_rows = [_row(sh, r) for r in range(data0, min(data0 + 8, nr))]
    c_e0 = next((c for c in elec_cands if all(c < len(rw) and (_num(rw[c]) or 0) >= 20 for rw in data_rows)), None)
    if c_e0 is None:
        return None
    c_t0 = next((c for c in range(c_e0 + 1, nc) if TURNOUT_RE.search(label[c])), None)
    if c_t0 is None:
        return None
    c_elec = c_t0 - 1 if c_t0 - c_e0 > 1 else c_e0              # electors split over several columns: the last one is the total
    sub = [" ".join(_txt(sh.cell(r, c).value) for r in range(lab_r + 1, data0)).lower() for c in range(nc)]
    cm = cf = co = ct = None
    for c in range(c_t0, min(c_t0 + 6, nc)):
        t = sub[c]
        if ("female" in t or "women" in t) and cf is None:
            cf = c
        elif ("male" in t or re.search(r"\bmen\b", t)) and cm is None:
            cm = c
        elif ("other" in t or "trans" in t) and co is None:
            co = c
        elif "total" in t and ct is None:
            ct = c
    cm, cf, co, ct = (cm if cm is not None else c_t0), (cf if cf is not None else c_t0 + 1), (co if co is not None else c_t0 + 2), (ct if ct is not None else c_t0 + 3)

    # 4. AC and polling-station number columns, found from the data: PS counts 1, 2, 3 ...; AC is constant
    probe = [_row(sh, r) for r in range(data0, min(data0 + 25, nr))]
    c_ps = c_ac = None
    for c in range(min(c_e0, 6)):
        col = [_num(row[c]) for row in probe if c < len(row)]
        col = [v for v in col if v is not None]
        if len(col) >= 8 and col == sorted(col) and len(set(col)) >= 0.6 * len(col) and len(set(col)) > 1 and col[0] <= 3 and c_ps is None:
            c_ps = c
        elif len(col) >= 8 and len(set(col)) == 1 and c_ac is None:
            c_ac = c
    c_psname = None
    if c_ps is None:                                              # no number column: the number may sit in front of the name
        for c in range(min(c_e0, 6)):
            hits = [PS_NAME_RE.match(_txt(row[c])) for row in probe if c < len(row)]
            if sum(1 for h in hits if h) >= 0.7 * max(len(hits), 1) and len(hits) >= 8:
                c_psname = c
                break
        if c_psname is None:
            return None

    # 5. candidate vote columns: the sub-header row with the most 'Votes Secured'-like cells; stop at the summary column
    best = None
    for r in hdr_rows:
        cols = [c for c in range(c_t0 + 4, nc) if VOTES_RE.search(_txt(sh.cell(r, c).value)) and not re.search(r"total", _txt(sh.cell(r, c).value), re.I)]
        if cols and (best is None or len(cols) > len(best[1])):
            best = (r, cols)
    vcols = best[1] if best else []
    cand = []
    for v in vcols:
        party = ""
        for row in probe[:10]:
            p = _txt(row[v - 1]) if v - 1 < len(row) else ""
            if p and _num(p) is None and not GENERIC_HEADER.match(p):
                party = p
                break
        name = ""
        for r in reversed(list(hdr_rows)):
            for c in range(max(0, v - 2), v + 1):
                t = _txt(sh.cell(r, c).value)
                if t and not GENERIC_HEADER.match(t) and not VOTES_RE.search(t):
                    if not party and c == v - 1:
                        party = t                                # party written in the header row, not in the data rows
                    elif c != v - 1:
                        name = name or t
            if name:
                break
        cand.append((name or f"CAND_{v}", party, v))

    # 6. booth rows
    booths, facts = [], []
    for r in range(data0, nr):
        row = _row(sh, r)
        if c_ps is not None:
            ps = _num(row[c_ps]) if c_ps < len(row) else None
        else:
            m = PS_NAME_RE.match(_txt(row[c_psname])) if c_psname < len(row) else None
            ps = float(m.group(1)) if m else None
        if ps is None:
            continue
        def g(c):
            return _num(row[c]) if c is not None and c < len(row) else None
        votes = [(n, p, g(v) or 0.0) for n, p, v in cand]
        nota = sum(v for n, p, v in votes if NOTA_RE.search(n) or NOTA_RE.search(p))
        valid = sum(v for _n, _p, v in votes)
        ac = g(c_ac)
        booths.append({"ac": int(ac) if ac is not None else None, "electors": g(c_elec), "male": g(cm), "female": g(cf), "other": g(co),
                       "polled": g(ct) if g(ct) is not None else valid, "valid": valid, "nota": nota})
        for n, p, v in votes:
            facts.append({"ac": booths[-1]["ac"], "candidate": n, "party": "NOTA" if NOTA_RE.search(n) or NOTA_RE.search(p) else p, "votes": v})
    if len(booths) < 50:
        return None
    return {"booths": booths, "facts": facts, "has_party_votes": bool(cand)}


def parse_workbook(bk) -> dict | None:
    """First sheet that looks like a booth table."""
    for i in range(bk.nsheets):
        try:
            res = parse_sheet(bk.sheet_by_index(i))
        except Exception:
            res = None
        if res:
            return res
    return None


def form20_preamble_electors(bk) -> int | None:
    """Total electors of the constituency from a Form 20 preamble line ("Total No. of Electors in Assembly Constituency ... 378401")."""
    for i in range(bk.nsheets):
        sh = bk.sheet_by_index(i)
        for r in range(min(12, sh.nrows)):
            line = " ".join(_txt(sh.cell(r, c).value) for c in range(min(sh.ncols, 12)))
            m = PREAMBLE_RE.search(line)
            if m:
                n = int(m.group(1).replace(",", ""))
                if 20_000 <= n <= 800_000:
                    return n
    return None


def sniff_reason(path) -> str:
    """Why a workbook has no booth table, judged from its sheet names and first rows (so the reason is never assumed)."""
    import xlrd
    try:
        bk = xlrd.open_workbook(str(path))
    except Exception as exc:
        return "password-protected workbook" if "encrypt" in str(exc).lower() else f"cannot be opened ({type(exc).__name__})"
    names = [bk.sheet_by_index(i).name for i in range(bk.nsheets)]
    text = ""
    for i in range(min(bk.nsheets, 3)):
        sh = bk.sheet_by_index(i)
        for r in range(min(8, sh.nrows)):
            text += " ".join(str(sh.cell(r, c).value) for c in range(min(sh.ncols, 6))) + " "
    joined_names = " ".join(names)
    if re.search(r"postal", text + joined_names, re.I):
        return "postal-vote sheet, no booth table"
    if names and re.fullmatch(r"R\d+", names[0].strip()) and sum(bool(re.fullmatch(r"R\d+", n.strip())) for n in names) >= 3:
        return "counting-round sheets, no booth table"
    if re.search(r"&20|form\s*20|format\s*20|result_form20|pswise|final 20", text + " " + joined_names, re.I):
        return "Form 20 results sheet: votes per polling station but no electors"
    return "layout not recognised"
