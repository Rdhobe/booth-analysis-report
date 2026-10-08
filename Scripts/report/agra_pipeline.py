"""Agra-only booth pipeline: Excel ingest -> crosswalk -> swing -> anomaly.

Scope: 2017/2019/2022 .xls (ECI triplet sheets) + 2024 .xlsx (Form20) for
Agra ACs 86-94. Excel-vs-Excel comparison (no PDFs). Follows brain/:
booth_uid key, crosswalk-first joins (RULES R4), swings in pp of polled
votes (MODELS 1), MAD robust-z "statistical outlier" flags (MODELS 4,
fraud language forbidden), uncertainty/modeled tags (RULES R3).

Usage:
  python Scripts/agra_pipeline.py [--out data/processed]

Outputs (under --out): agra_fact.csv, agra_booth.csv, agra_crosswalk.csv,
agra_swing.csv, agra_anomaly.csv, agra_analysis.xlsx, agra_coverage.csv.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import logging
import re
import statistics
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("agra")

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
ELECTIONS = [
    ("VS2017", "2017", "Agra"),
    ("LS2019", "2019", "agra"),
    ("VS2022", "2022", "Agra"),
    ("LS2024", "2024", "Agra"),
]
AC_MIN, AC_MAX = 86, 94
CONF_MIN_SWING = 0.8
Z_FLAG = 3.5
SMALL_N = 200
SHRINK_K = 200  # EB shrinkage strength (MODELS D7): w = n/(n+K)

NOTA_RE = re.compile(r"nota|none of the above", re.I)
LEGACY_RE = re.compile(r"[a-z]")
HEADER_WORDS = {"S.NO.", "S.NO", "PARTY AFFILIATION", "VOTES SECURED",
                "NO.", "NAME", "TOTAL"}
# Party continuity (T1.5 light): ECI sheets spell parties variants.
PARTY_ALIASES = {"CONG": "INC", "CONGRESS": "INC", "INC.": "INC",
                 "INDIAN NATIONAL CONGRESS": "INC",
                 "INDEPENDENT": "IND", "INDP": "IND", "INDP.": "IND",
                 "IND.": "IND", "PSP(L)(L)(L)": "PSP(L)", "PSP (L)": "PSP(L)",
                 "AIMEIM": "AIMIM",  # ECI-sheet typo, single occurrence family
                 "BHARATIYA JANATA PARTY": "BJP", "BHARTIYA JANATA PARTY": "BJP",
                 "BHARATIYA JANTA PARTY": "BJP", "BHARTIYA JANTA PARTY": "BJP",
                 "BHARATIYA JANATA PARTY (BJP)": "BJP",
                 "BHARTIYA JANTA PATRY": "BJP", "BAHRTIYA JANTA PARTY": "BJP",
                 "BHARATIYAJANATA PARTY": "BJP",
                 "BHARATIYA JANATA PARTY(BJP)": "BJP",
                 "(BHARATIYA JANATA PARTY)": "BJP",
                 "SAMAJWADI PARTY": "SP", "SAMAJ WADI PARTY": "SP",
                 "SAMAJWADI PARTI": "SP", "SAMAJVADI PARTY": "SP",
                 "SAMAJWADI PARTY PARTY": "SP", "SAMAJWADI PARTY (SP)": "SP",
                 "BAHUJAN SAMAJ PARTY": "BSP", "BAHUJAN SAMAJ PARTY (BSP)": "BSP",
                 "RASHTRIYA LOK DAL": "RLD", "RASHTRIYA LOKDAL": "RLD",
                 "RASHTRIYA LOK DAL (RLD)": "RLD", "(RASHTRIYA LOK DAL)": "RLD",
                 "APNA DAL (SONEYLAL)": "APNA DAL (SONELAL)",
                 "APNA DAL (SONEY LAL)": "APNA DAL (SONELAL)",
                 "APNA DAL (SONE LAL)": "APNA DAL (SONELAL)",
                 "APANA DAL(SONELAL)": "APNA DAL (SONELAL)",
                 "APNA DAL (S)": "APNA DAL (SONELAL)",
                 "SUHELDEV BHARTIYA SAMAJ PARTY": "SUHELDEV BHARATIYA SAMAJ PARTY",
                 "NATIONALIST CONGRESS PARTY": "NCP"}
# NOTE: all-caps DevLys codes (e.g. 'HKKJRH; TURK IKVHZ') are NOT aliased:
# undecodable without the legacy font tables; kept verbatim + flagged.


def norm_party(p: str) -> str:
    p = norm_name(p)
    if re.match(r"^([A-Z]\s+)+[A-Z]$", p):
        p = p.replace(" ", "")  # 'A I M E I M' -> 'AIMIM'
    return PARTY_ALIASES.get(p, p)


# ---------------------------------------------------------------- utils

def num(x):
    """xlrd/openpyxl cell -> int or None (strict, no silent coercion)."""
    if x is None or (isinstance(x, str) and not x.strip()):
        return None
    if isinstance(x, float):
        return int(x) if x.is_integer() else None
    if isinstance(x, int):
        return x
    s = str(x).strip().replace(",", "")
    return int(s) if re.match(r"^-?\d+$", s) else None


def norm_name(s) -> str:
    if isinstance(s, float) and s.is_integer():
        return str(int(s))
    return re.sub(r"\s+", " ", str(s or "").strip().upper())


def booth_uid(eid: str, ac: int, ps_raw: str) -> tuple[str, str]:
    m = re.match(r"^(\d+)\s*([A-Za-z]*)$", str(ps_raw).strip())
    ps = m.group(1).zfill(4) if m else "0000"
    suffix = m.group(2) if m else ""
    return f"{eid}-{ac:03d}-{ps}{suffix}", suffix


# ---------------------------------------------------------------- ingest 2024

def ingest_2024(files: list[Path], party_map: dict) -> tuple[list, list, list]:
    """Our Form20 xlsx: title r5, names r8, data from r9, trailers last 5."""
    import openpyxl
    facts, booths, cover = [], [], []
    for f in sorted(files):
        wb = openpyxl.load_workbook(str(f), data_only=True)
        ws = wb["Form20"] if "Form20" in wb.sheetnames else wb.active
        title = str(ws.cell(5, 1).value or "")
        m = re.search(r"(\d{2,3})\s*-\s*(.+)", title)
        ac = int(m.group(1)) if m else -1
        ac_name = m.group(2).strip() if m else "UNKNOWN"
        ncols = ws.max_column
        # lead=2 (serial + PS-no columns) or lead=1 (serial only, e.g.
        # Pryagraj sheets where r8c2 is already a candidate name)
        r8c1 = norm_name(ws.cell(8, 2).value)
        lead = 2 if (not r8c1 or re.search(r"polling|station|ps\.?\s*no|^\d+$", r8c1, re.I)) else 1
        names = [norm_name(ws.cell(8, c).value) for c in range(lead + 1, ncols - 4)]
        rows, r = [], 9
        while r <= ws.max_row:
            v0 = ws.cell(r, 1).value
            if v0 is None or not re.match(r"^\d+$", str(v0).strip()):
                break
            rows.append([ws.cell(r, c).value for c in range(1, ncols + 1)])
            r += 1
        # summary rows right after data (EVM / Postal / Polled)
        evm = [ws.cell(r + 1, c).value for c in range(1, ncols + 1)] \
            if r + 1 <= ws.max_row else []
        nv = sum(num(x) or 0 for row in rows for x in [row[ncols - 5]])
        evm_valid = num(evm[ncols - 5]) if len(evm) >= ncols - 4 else None
        ok = evm_valid in (None, 0) or abs(nv - evm_valid) / max(evm_valid, 1) <= 0.005
        bad_rows = 0
        for row in rows:
            ps_raw = str(row[1]).strip() if (lead == 2 and row[1] is not None) else ""
            if lead == 1 or not ps_raw:
                ps_raw = str(row[0]).strip()
            uid, _sfx = booth_uid("LS2024", ac, ps_raw)
            votes = [num(x) or 0 for x in row[lead:lead + len(names)]]
            # trailers are the last 5 cols: valid|rejected|NOTA|total|tendered
            valid, rej = num(row[ncols - 5]), num(row[ncols - 4])
            nota, tot = num(row[ncols - 3]), num(row[ncols - 2])
            polled = tot if tot is not None else sum(votes) + (nota or 0)
            # genuine row-math gate (not vacuous): candidates must sum
            if valid is not None and sum(votes) != valid:
                bad_rows += 1
            if valid is not None and tot is not None and valid + (nota or 0) != tot:
                bad_rows += 1
            b = {"booth_uid": uid, "election": "LS2024", "ac": ac,
                 "ac_name": ac_name, "ps": ps_raw,
                 "ps_name": ps_raw, "electors": None,
                 "male": None, "female": None, "other": None,
                 "epic": None, "tendered": None, "polled": polled,
                 "valid": valid if valid is not None else sum(votes),
                 "nota": nota or 0, "legacy_names": False, "src": f.name}
            booths.append(b)
            for name, vv in zip(names, votes):
                party = party_map.get(("LS2024", ac, name),
                                      party_map.get(("LS2024", "*", name), "UNMAPPED"))
                facts.append({"booth_uid": uid, "election": "LS2024", "ac": ac,
                              "candidate": name, "party": norm_party(party),
                              "votes": vv})
        cover.append({"election": "LS2024", "ac": ac, "ac_name": ac_name,
                      "file": f.name, "booths": len(rows),
                      "valid_ok": ok and bad_rows == 0,
                      "has_total": evm_valid is not None,
                      "note": f"rowmath_bad={bad_rows}" if bad_rows else ""})
        log.info("2024 ac=%s %-28s booths=%d valid_ok=%s", ac, ac_name[:28],
                 len(rows), ok)
        wb.close()
    return facts, booths, cover


# ---------------------------------------------------------------- ingest ECI xls

def find_vote_header(sh) -> tuple[int, list[int]] | None:
    """Header row index + 'Votes Secured' column indices (any sheet). Picks
    the row with the MOST hits: the sub-header row repeats the label per
    candidate, while a trailing 'Total Votes Secured' cell alone must not
    win (it is a summary column, not a candidate triplet)."""
    best = None
    for r in range(min(12, sh.nrows)):
        cols = [c for c in range(sh.ncols)
                if "Votes Secured" in str(sh.cell(r, c).value)]
        if cols and (best is None or len(cols) > len(best[1])):
            best = (r, cols)
    return best


def ingest_eci(eid: str, files: list[Path]) -> tuple[list, list, list]:
    """ECI triplet sheets: [S.No | Party | Votes Secured] per candidate,
    names in merged header above; booth cols AC|PS|[Name|]Electors|M|F|O|T|
    EPIC|Tendered (Name absent in most 2017 sheets - auto-detected)."""
    import xlrd
    facts, booths, cover = [], [], []
    for f in sorted(files):
        bk = xlrd.open_workbook(str(f))
        seen_in_file: list = []
        file_hit = False
        for si in range(bk.nsheets):
            sh = bk.sheet_by_index(si)
            found = find_vote_header(sh)
            if not found:
                log.info("%s sheet %r: no triplets, skipped", f.name, sh.name)
                continue
            hr, vcols = found
            name_rows = [r for r in (hr - 1, hr - 2) if r >= 0]
            # merged header cells: xlrd reports values only at the merge
            # origin; map every covered cell back to it for name lookup.
            merged_origin: dict = {}
            try:
                for (rlo, rhi, clo, chi) in sh.merged_cells:
                    for rr in range(rlo, rhi):
                        for cc in range(clo, chi):
                            merged_origin[(rr, cc)] = (rlo, clo)
            except Exception:
                pass

            def mval(rr: int, cc: int):
                o = merged_origin.get((rr, cc), (rr, cc))
                return sh.cell(*o).value
            # Booth-block geometry: ECI sheets either carry a booth Name
            # column (AC|PS|Name|Electors|M|F|O|T|EPIC|Tendered, e.g.
            # 2019/2022 and parts of 2017) or omit it
            # (AC|PS|Electors|M|F|O|T|EPIC|Tendered, most 2017 files).
            # A bare 'Name' header in the booth block decides the layout;
            # without it every booth column shifts one cell left and the
            # column-index helper row reads [1,2,4,5,6,7], not [1..6].
            _name_probe = {re.sub(r"\s+", "", str(mval(rr, cc) or "")
                                          .upper())
                           for rr in ({hr} | set(name_rows) | {hr + 1})
                           if 0 <= rr < sh.nrows for cc in range(6)}
            has_name = "NAME" in _name_probe
            # First candidate-triplet column (booth block is 10 cols with
            # Name, 9 without). The trailing-summary / NOTA / total scans
            # below must start past the booth block.
            _b0 = 10 if has_name else 9
            # Trailing summary zone (Total/NOTA/Tendered...) is NOT a
            # candidate triplet even though 'Total Votes Secured' contains
            # the match string. Cut triplets there; capture NOTA/total.
            # Labels may sit on any of the header rows (name rows vary).
            lab_at = lambda cc: " ".join(
                str(mval(rr, cc) or "")
                for rr in ({hr} | set(name_rows))).strip()
            # scan past the booth block (which has its own Tendered)
            tz = None
            for cc in range(_b0, sh.ncols):
                if re.search(r"total|tendered|reject", lab_at(cc), re.I):
                    tz = cc
                    break
            if tz is not None:
                vcols = [v for v in vcols if v < tz]
            nota_col, total_col = None, None
            for cc in range(_b0, sh.ncols):
                lab = lab_at(cc)
                if re.match(r"^\s*NOTA\s*$", lab, re.I):
                    nota_col = cc
                if total_col is None and re.search(r"total", lab, re.I) \
                        and cc not in vcols:
                    total_col = cc
            rows, r, totals, cur_ac = [], hr + 2, None, None
            # Sheet geometry: most sheets lead with the AC number in col0
            # (AC, PS, Name, Electors, M, F, O, T, EPIC, Tendered); some
            # sheets start at the serial (PS, Name, Electors, ...) with the
            # AC only in the file/sheet name. Detect from data shape.
            probe0, probe1 = [], []
            for rr in range(hr + 2, min(hr + 14, sh.nrows)):
                try:
                    a = str(sh.cell(rr, 0).value).strip()
                    if re.match(r"^\d+(\.0)?$", a):
                        probe0.append(int(float(a)))
                except ValueError:
                    pass
                try:
                    b = str(sh.cell(rr, 1).value).strip() if sh.ncols > 1 else ""
                    if re.match(r"^\d+(\.0)?$", b):
                        probe1.append(int(float(b)))
                except ValueError:
                    pass
            ps_first = len(probe0) >= 3 and \
                probe0 == list(range(1, len(probe0) + 1))
            if ps_first:
                m_ac = re.search(r"(\d{2,3})", f.stem) or \
                    re.search(r"(\d{2,3})", sh.name)
                if not m_ac:
                    log.warning("%s sheet %r: serial-first layout but no AC "
                                "in file/sheet name, skipped", f.name, sh.name)
                    continue
                cur_ac = int(m_ac.group(1))
                if has_name:
                    C_PS, C_NAME, C_ELEC = 0, 1, 2
                    C_M, C_F, C_O, C_T = 3, 4, 5, 6
                else:
                    C_PS, C_NAME, C_ELEC = 0, None, 1
                    C_M, C_F, C_O, C_T = 2, 3, 4, 5
            else:
                if has_name:
                    C_PS, C_NAME, C_ELEC = 1, 2, 3
                    C_M, C_F, C_O, C_T = 4, 5, 6, 7
                else:
                    C_PS, C_NAME, C_ELEC = 1, None, 2
                    C_M, C_F, C_O, C_T = 3, 4, 5, 6
            C_EPIC = C_T + 1
            C_TEND = C_T + 2
            while r < sh.nrows:
                c0 = str(sh.cell(r, 0).value).strip()
                c1 = str(sh.cell(r, C_PS if ps_first else 1).value).strip() \
                    if sh.ncols > 1 else ""
                is_ac = bool(re.match(r"^\d+(\.0)?$", c0)) and not ps_first
                is_ps = bool(re.match(r"^\d+(\.0)?$", c1))
                # AC number sharing its cell with the AC name ('72 Barauli')
                m_ac0 = re.match(r"^(\d{2,3})\b", c0)
                if is_ac:
                    cur_ac = int(float(c0))
                elif m_ac0 and not ps_first:
                    cur_ac = int(m_ac0.group(1))
                    is_ac = True
                if is_ps and (is_ac or cur_ac is not None or c0 == ""):
                    vals = [sh.cell(r, c).value for c in range(sh.ncols)]
                    # skip fully-blank rows
                    if all(v in (None, "") for v in vals[1:4]):
                        r += 1
                        continue
                    # skip column-index helper rows (1,2,3,... across).
                    # With-Name sheets read [1,2,3,4,5,6] in cols 0-5, but
                    # no-Name sheets read [1,2,4,5,6,7] and sheets with a
                    # sub-header row read [1,2,3,'',4,5] - so a fixed
                    # head6==[1..6] check misses every variant and ingests
                    # the helper as a phantom booth (AC = column number,
                    # parties = '11','14',...). Detect instead by the
                    # triplet party cells: real rows hold party text
                    # there, the helper row holds column numbers.
                    head6 = [num(vals[c]) if c < len(vals) else None
                             for c in range(6)]
                    if head6 == [1, 2, 3, 4, 5, 6]:
                        r += 1
                        continue
                    helper = sum(
                        1 for v in vcols[:8]
                        if v - 1 < len(vals) and re.match(
                            r"^\d+(\.0)?$",
                            str(vals[v - 1]).strip()))
                    if helper >= 2:
                        r += 1
                        continue
                    rows.append((cur_ac, vals))
                    r += 1
                    continue
                # non-data row: possible totals row (carries numbers)
                if any(isinstance(sh.cell(r, c).value, (int, float))
                       for c in range(min(15, sh.ncols))):
                    totals = r
                r += 1
            if not rows:
                continue
            # Triplets: names from merged header above; party affiliation is
            # STATIC per candidate - read from data rows (the header row
            # only holds the words 'S.No. | Party Affiliation | ...').
            triplets = []
            for v in vcols:
                cname = ""
                for nr in name_rows:  # nearest header row first
                    for cc in range(max(0, v - 2), min(v + 1, sh.ncols)):
                        t = norm_name(mval(nr, cc))
                        if t and t not in HEADER_WORDS:
                            cname = re.sub(r"^\d+\s*[-–.]\s*", "", t)
                            break
                    if cname:
                        break
                party = ""
                for _a2, drow in rows[:5]:
                    p = norm_name(drow[v - 1]) if v - 1 < len(drow) else ""
                    if p and p not in HEADER_WORDS:
                        party = p
                        break
                if not cname and not party:
                    continue  # empty triplet slot, not a candidate
                if party in HEADER_WORDS or cname in HEADER_WORDS:
                    continue  # sub-header leakage, not a candidate
                if re.match(r"^\d+(\.0)?$", party.strip()):
                    continue  # column-index residue, not a party
                if not cname:
                    cname = f"CAND_{v}"
                triplets.append((cname, norm_party(party) or "IND", v))
            if not triplets:
                log.info("%s sheet %r: triplets unreadable, skipped", f.name, sh.name)
                continue
            ac = rows[0][0]
            if ac is None:
                m_ac = re.search(r"(\d{2,3})", f.stem) or \
                    re.search(r"(\d{2,3})", sh.name)
                ac = int(m_ac.group(1)) if m_ac else -1
            if ac == -1:
                log.warning("%s sheet %r: AC unknown, skipped", f.name, sh.name)
                continue
            legacy = any(bool(LEGACY_RE.search(str(row[C_NAME] or "")))
                          for _a, row in rows[:20]
                          if C_NAME is not None and len(row) > C_NAME)
            nv, row_bad = 0, 0
            s_booths, s_facts = [], []
            for ac_row, row in rows:
                ac = ac_row if ac_row is not None else ac
                ps_cell = str(row[C_PS]).strip() if len(row) > C_PS else ""
                mps = re.match(r"^(\d+)", ps_cell)
                ps_raw = mps.group(1) if mps else ps_cell
                uid, _sfx = booth_uid(eid, ac, ps_raw)
                votes = []
                for cname, party, v in triplets:
                    vv = num(row[v] if v < len(row) else None)
                    if vv is None:
                        vv = 0
                    votes.append(vv)
                electors = num(row[C_ELEC]) if len(row) > C_ELEC else None
                # Gender-split turnout (Voters Turnout: Male/Female/Other/
                # Total) plus EPIC-identified and tendered voters. Absent
                # in 2024 Form20 workbooks (None there).
                m_v = num(row[C_M]) if len(row) > C_M else None
                f_v = num(row[C_F]) if len(row) > C_F else None
                o_v = num(row[C_O]) if len(row) > C_O else None
                t_tot = num(row[C_T]) if len(row) > C_T else None
                epic = num(row[C_EPIC]) if len(row) > C_EPIC else None
                tend = num(row[C_TEND]) if len(row) > C_TEND else None
                nota = num(row[nota_col]) if nota_col is not None \
                    and nota_col < len(row) else None
                if nota is None:
                    nota = sum(vv for (cn, _p, _v), vv in zip(triplets, votes)
                               if NOTA_RE.search(cn))
                pvotes = [vv for (cn, _p, _v), vv in zip(triplets, votes)
                          if not NOTA_RE.search(cn)]
                valid = sum(votes)
                nv += valid
                polled = t_tot if t_tot is not None else valid
                # row-math gate: candidates must sum to the explicit total,
                # which may be valid-only or grand (valid+NOTA)
                if total_col is not None and total_col < len(row):
                    tv = num(row[total_col])
                    if tv is not None and tv != valid and tv != valid + nota:
                        row_bad += 1
                s_booths.append({"booth_uid": uid, "election": eid, "ac": ac,
                               "ac_name": "", "ps": ps_raw,
                               "ps_name": (str(row[C_NAME]).strip()
                                           if C_NAME is not None
                                           and len(row) > C_NAME else ""),
                               "electors": electors,
                               "male": m_v, "female": f_v, "other": o_v,
                               "epic": epic, "tendered": tend,
                               "polled": polled, "valid": valid, "nota": nota,
                               "legacy_names": legacy, "src": f"{f.name}#{sh.name}"})
                for (cname, party, _v), vv in zip(triplets, votes):
                    p = "NOTA" if NOTA_RE.search(cname) else norm_party(party or "IND")
                    s_facts.append({"booth_uid": uid, "election": eid, "ac": ac,
                                    "candidate": cname, "party": p, "votes": vv})
            # duplicate sheet in the same file (e.g. Sheet2 + ECI Format):
            # keep the first copy only
            uids = {b["booth_uid"] for b in s_booths}
            if uids and any(uids == s for s in seen_in_file):
                log.info("%s sheet %r: duplicate of an earlier sheet, skipped",
                         f.name, sh.name)
                continue
            seen_in_file.append(uids)
            booths.extend(s_booths)
            facts.extend(s_facts)
            ok, evm_valid = True, None
            if totals is not None:
                evm_valid = num(sh.cell(totals, vcols[-1] + 1)) \
                    if vcols[-1] + 1 < sh.ncols else None
                if evm_valid:
                    ok = abs(nv - evm_valid) / evm_valid <= 0.005
            cover.append({"election": eid, "ac": ac, "ac_name": "",
                          "file": f"{f.name}#{sh.name}", "booths": len(rows),
                          "valid_ok": ok, "has_total": evm_valid is not None,
                          "note": "; ".join(filter(None, [
                              "legacy-names" if legacy else "",
                              f"rowmath_bad={row_bad}" if row_bad else "",
                          ]))})
            file_hit = True
            log.info("%s ac=%s sheet=%r booths=%d legacy=%s", eid, ac, sh.name,
                     len(rows), legacy)
        if not file_hit:
            cover.append({"election": eid, "ac": "", "ac_name": "",
                          "file": f.name, "booths": 0,
                          "valid_ok": False, "has_total": False,
                          "note": "NO-TRIPLET-SHEETS (no usable triplet data - "
                                  "missing 'Votes Secured' header or "
                                  "unreadable triplets - needs parser)"})
    return facts, booths, cover


# ---------------------------------------------------------------- crosswalk + features + anomaly

def crosswalk(booths: list, pairs: list) -> list:
    """Greedy 1:1 links on (ac, ps_no). Exact part-number match is strong
    evidence on its own (base 0.85); name similarity only adjusts it —
    required because some sources carry no usable names (2024 repeats the
    part number; legacy codes). Swings need conf>=0.8 (MODELS.md)."""
    by_ea: dict = {}
    for b in booths:
        by_ea.setdefault((b["election"], b["ac"]), []).append(b)
    links = []
    for e_prev, e_cur in pairs:
        acs = {a for (e, a) in by_ea if e in (e_prev, e_cur)}
        for ac in sorted(acs):
            prev = {b["ps"]: b for b in by_ea.get((e_prev, ac), [])}
            cur = {b["ps"]: b for b in by_ea.get((e_cur, ac), [])}
            for ps, cb in cur.items():
                pb = prev.get(ps)
                if pb is None:
                    links.append({"prev_uid": "", "curr_uid": cb["booth_uid"],
                                  "ac": ac, "pair": f"{e_prev}>{e_cur}",
                                  "link": "new", "conf": 0.0})
                    continue
                pn, cn = str(pb["ps_name"]), str(cb["ps_name"])
                conf = 0.85
                if pn and cn and pn != ps and cn != ps:
                    ratio = difflib.SequenceMatcher(None, pn, cn).ratio()
                    if ratio >= 0.6:
                        conf = min(1.0, conf + 0.1)
                    elif ratio < 0.3:
                        conf = 0.6
                links.append({"prev_uid": pb["booth_uid"],
                              "curr_uid": cb["booth_uid"], "ac": ac,
                              "pair": f"{e_prev}>{e_cur}",
                              "link": "1:1", "conf": round(conf, 3)})
    return links


def shares(facts: list, booths: list) -> tuple[dict, dict]:
    """party shares per booth (denominator: polled votes; documented)."""
    pv: dict = {}
    for b in booths:
        pv[b["booth_uid"]] = {"polled": b["polled"] or 0,
                              "electors": b["electors"],
                              "valid": b["valid"] or 0, "nota": b["nota"] or 0,
                              "ac": b["ac"], "election": b["election"]}
    ps: dict = {}
    for f in facts:
        if f["party"] in ("NOTA",):
            continue
        d = ps.setdefault(f["booth_uid"], {})
        d[f["party"]] = d.get(f["party"], 0) + f["votes"]
    out = {}
    for uid, parties in ps.items():
        polled = pv[uid]["polled"] or sum(parties.values()) or 1
        out[uid] = {p: v / polled for p, v in parties.items()}
    return out, pv


def build_swings(links: list, sh: dict, pv: dict,
                 parties_by_election: dict) -> list:
    """Swing cols only for parties comparable on both sides: the INTERSECTION
    of fielded parties (minus UNMAPPED), for every pair. A party contesting
    only one election would otherwise fake a 'vanish/surge' swing in every
    booth (e.g. 2024 names lack party labels; micro-parties come and go).
    New-entrant effects still surface via margin_d/winner_changed.
    Winner/margin always use the full field. Swings in percentage points."""
    rows = []
    for L in links:
        if L["link"] != "1:1" or L["conf"] < CONF_MIN_SWING:
            continue
        a, b = sh.get(L["prev_uid"], {}), sh.get(L["curr_uid"], {})
        if not a or not b:
            continue  # booth with no measurable party shares on one side
        pa, pb = pv[L["prev_uid"]], pv[L["curr_uid"]]
        e_prev = L["pair"].split(">")[0]
        e_cur = L["pair"].split(">")[1]
        parties = sorted((set(a) | set(b))
                         & parties_by_election.get(e_prev, set())
                         & parties_by_election.get(e_cur, set())
                         - {"UNMAPPED"})
        rec = {"prev_uid": L["prev_uid"], "curr_uid": L["curr_uid"],
               "ac": L["ac"], "pair": L["pair"], "conf": L["conf"],
               "polled_prev": pa["polled"], "polled_curr": pb["polled"]}
        for p in parties:
            rec[f"swing_{p}"] = round((b.get(p, 0) - a.get(p, 0)) * 100, 2)
        wa = max(a.items(), key=lambda kv: kv[1], default=(None, 0))
        wb = max(b.items(), key=lambda kv: kv[1], default=(None, 0))
        sa = sorted(a.values(), reverse=True)
        sb = sorted(b.values(), reverse=True)
        rec["margin_prev"] = round(((sa[0] - (sa[1] if len(sa) > 1 else 0))) * 100, 2)
        rec["margin_curr"] = round(((sb[0] - (sb[1] if len(sb) > 1 else 0))) * 100, 2)
        rec["margin_d"] = round(rec["margin_curr"] - rec["margin_prev"], 2)
        rec["nota_prev"] = round(pa["nota"] / (pa["polled"] or 1) * 100, 2)
        rec["nota_curr"] = round(pb["nota"] / (pb["polled"] or 1) * 100, 2)
        rec["nota_d"] = round(rec["nota_curr"] - rec["nota_prev"], 2)
        if pa["electors"] and pb["electors"] and \
                pa["polled"] >= pa["valid"] and pb["polled"] >= pb["valid"]:
            rec["turnout_prev"] = round(pa["polled"] / pa["electors"] * 100, 2)
            rec["turnout_curr"] = round(pb["polled"] / pb["electors"] * 100, 2)
            rec["turnout_d"] = round(rec["turnout_curr"] - rec["turnout_prev"], 2)
        else:
            # turnout unreliable when the source's own turnout total is
            # below the counted valid votes (4 such booths in VS2022-89,
            # confirmed against the duplicate sheet) or electors missing
            rec["turnout_prev"] = rec["turnout_curr"] = rec["turnout_d"] = None
        rec["winner_prev"], rec["winner_curr"] = wa[0], wb[0]
        rec["winner_changed"] = wa[0] != wb[0]
        rows.append(rec)
    return rows


def mad_z(vals: list) -> list | None:
    """MAD robust-z. Returns None when there is no variation (all values
    identical) — no signal can be extracted, and scaling by ~0 would flag
    every speck of noise."""
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    if mad == 0:
        return None
    return [(v - med) / (1.4826 * mad) for v in vals]


def anomalies(swings: list) -> list:
    """Per (ac, pair): residualize vs AC median, EB-shrink toward the median
    by booth size (MODELS D7: w=n/(n+K), else small booths dominate), then
    MAD robust-z; flag |z|>=3.5. Output name is statistical_outlier
    (never fraud). Small booths flagged low-confidence (RULES R5 spirit:
    uncertainty shown). Deterministic (no RNG)."""
    out, n = [], 0
    groups: dict = {}
    for s in swings:
        groups.setdefault((s["ac"], s["pair"]), []).append(s)
    feat_keys = ["margin_d", "nota_d", "turnout_d"] + sorted(
        {k for s in swings for k in s if k.startswith("swing_")})
    for (ac, pair), g in sorted(groups.items()):
        resid: dict = {}
        # shrinkage sized by the SMALLER side (a 6-vote booth must not
        # drive z-scores even if its pair side is large)
        sizes = [min((s["polled_prev"] or 0), (s["polled_curr"] or 0)) for s in g]
        for k in feat_keys:
            vals = [s.get(k) for s in g]
            if all(v is None for v in vals):
                continue
            fill = [v if v is not None else 0.0 for v in vals]
            med = statistics.median(fill)
            shrunk = []
            for v, nn in zip(fill, sizes):
                w = (nn or 0) / ((nn or 0) + SHRINK_K)
                shrunk.append(med + w * (v - med))
            resid[k] = shrunk
        zmap = {}
        for k, v in resid.items():
            z = mad_z(v)
            if z is not None:
                zmap[k] = z
        for i, s in enumerate(g):
            zs = {k: zmap[k][i] for k in zmap}
            top = sorted(zs.items(), key=lambda kv: -abs(kv[1]))[:2]
            mx = abs(top[0][1]) if top else 0
            small = (s["polled_curr"] or 0) < SMALL_N
            if mx >= Z_FLAG:
                n += 1
                out.append({
                    "booth_uid": s["curr_uid"], "ac": ac, "pair": pair,
                    "result": "statistical_outlier",
                    "score": round(float(mx), 2),
                    "top_features": "; ".join(
                        f"{k}={s.get(k)} (z={z:.1f})" for k, z in top),
                    "winner_changed": s["winner_changed"],
                    "confidence": "low-small-booth" if small else "standard",
                    "benign_note": "merge/split? new colony? migration? "
                                   "caste-cluster voting? boundary shift?"})
    log.info("anomaly flags: %d", n)
    return out


# ---------------------------------------------------------------- validation

def validate_pswise(booths: list) -> list:
    """Cross-check 2022 English-master booth sums against the Hindi pswise
    duplicate sheets (same election, independent extraction). Returns notes
    per AC: match within 0.5% or mismatch (quarantine signal, T1.3)."""
    import xlrd
    notes = []
    master = {}
    for b in booths:
        if b["election"] == "VS2022":
            master[b["ac"]] = master.get(b["ac"], 0) + (b["valid"] or 0)
    for f in sorted((DATA / "2022").glob("AC*.xls")):
        if f.name == "AC86.xls":
            continue
        try:
            acn = int(f.stem[2:])
        except ValueError:
            continue
        if not (AC_MIN <= acn <= AC_MAX):
            continue
        try:
            bk = xlrd.open_workbook(str(f))
        except Exception as ex:  # noqa: BLE001
            notes.append(f"{f.name}: unreadable ({ex})")
            continue
        sh = None
        for si in range(bk.nsheets):
            if "pswise" in bk.sheet_by_index(si).name.lower():
                sh = bk.sheet_by_index(si)
                break
        if sh is None:
            continue
        hdr = next((r for r in range(min(12, sh.nrows))
                    if sum(1 for c in range(sh.ncols)
                           if re.match(r"^\d+&", str(sh.cell(r, c).value or "").strip())) >= 3), None)
        if hdr is None:
            notes.append(f"{f.name}: pswise header not found")
            continue
        cand = [c for c in range(sh.ncols)
                if re.match(r"^\d+&", str(sh.cell(hdr, c).value or "").strip())]
        vv = cand[-1] + 1
        tot, ok_rows, rows = 0, 0, 0
        ac = None
        for r in range(hdr + 1, sh.nrows):
            if not re.match(r"^\d+(\.0)?$", str(sh.cell(r, 0).value).strip()):
                continue
            vs = [num(sh.cell(r, c).value) for c in cand + [vv]]
            if any(v is None for v in vs):
                continue
            rows += 1
            if sum(vs[:-1]) == vs[-1]:
                ok_rows += 1
                tot += vs[-1]
        m = re.search(r"(\d{2,3})", f.stem)
        ac = int(m.group(1)) if m else -1
        ref = master.get(ac, 0)
        match = ref and abs(tot - ref) / ref <= 0.005
        notes.append(f"{f.name} ac={ac} pswise_valid={tot} master_valid={ref} "
                     f"rows={rows} consistent={ok_rows}/{rows} match={bool(match)}")
        log.info("pswise check: %s", notes[-1])
    return notes


# ---------------------------------------------------------------- main (cont.)

def write_csv(path: Path, rows: list, cols: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agra booth pipeline (Excel only)")
    ap.add_argument("--out", default="data/processed")
    args = ap.parse_args(argv)
    out = Path(args.out)

    pmap: dict = {}
    pmf = ROOT / "configs" / "agra_party_map_2024.csv"
    if pmf.exists():
        with open(pmf, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip() and not ln.startswith("#")]
        for r in csv.DictReader(lines):
            pmap[(r["election_id"].strip(), r["ac_no"].strip(),
                  norm_name(r["candidate_name"]))] = r["party"].strip().upper()
    log.info("party map entries: %d", len(pmap))

    facts, booths, cover = [], [], []
    # 2024 first (our xlsx, flat at year root). Agra district = ACs
    # 86..94; other segments (e.g. Jalesar 106) are out of scope.
    # REVIEW quarantines excluded; the AC content filter below selects.
    f24 = sorted(p for p in (DATA / "2024").glob("*.xlsx")
                 if "REVIEW" not in p.name)
    a, b, c = ingest_2024(f24, pmap)
    dropped = [x for x in b
               if x["ac"] == -1 or not (AC_MIN <= x["ac"] <= AC_MAX)]
    if dropped:
        log.info("2024 out-of-scope segments skipped: %d booths (e.g. ac=%s)",
                 len(dropped), dropped[0]["ac"])
    keep = {x["booth_uid"] for x in b
            if x["ac"] != -1 and AC_MIN <= x["ac"] <= AC_MAX}
    facts += [x for x in a if x["booth_uid"] in keep]
    booths += [x for x in b if x["booth_uid"] in keep]
    cover += [x for x in c if x["ac"] != -1 and AC_MIN <= x["ac"] <= AC_MAX]
    # ECI years: 2017/2019 digit-named per-AC files at year root;
    # 2022 English master (AC86.xls, sheets 86..94). Hindi pswise
    # duplicates skipped (covered).
    for eid, year, d in ELECTIONS[:3]:
        if eid == "VS2022":
            use = [DATA / "2022" / "AC86.xls"]
            skipped = ["AC87..AC94 Hindi pswise (covered by master)"]
        else:
            use = sorted(p for p in (DATA / year).glob("*.xls")
                         if p.stem.isdigit()
                         and AC_MIN <= int(p.stem) <= AC_MAX)
            skipped = []
        a, b, c = ingest_eci(eid, use)
        facts += a
        booths += b
        cover += c
        log.info("%s skipped duplicates: %s", eid, skipped[:4])

    pairs = [(ELECTIONS[i][0], ELECTIONS[i + 1][0]) for i in range(3)]
    links = crosswalk(booths, pairs)
    linked = sum(1 for L in links if L["link"] == "1:1")
    log.info("links: %d (1:1 %d)", len(links), linked)
    sh, pv = shares(facts, booths)
    parties_by_election: dict = {}
    for f in facts:
        parties_by_election.setdefault(f["election"], set()).add(f["party"])
    swings = build_swings(links, sh, pv, parties_by_election)
    log.info("swing rows: %d", len(swings))
    flags = anomalies(swings)
    ps_notes = validate_pswise(booths)
    for note in ps_notes:
        print("pswise:", note)
        m = re.match(r"^(\S+) ac=(\d+) .* match=(True|False)$", note)
        if m and m.group(3) == "False":
            for c in cover:
                if c["election"] == "VS2022" and str(c["ac"]) == m.group(2):
                    c["note"] = (c["note"] + "; " if c["note"] else "") + \
                        "pswise-duplicate mismatch (see log); master authoritative"

    write_csv(out / "agra_fact.csv", facts,
              ["booth_uid", "election", "ac", "candidate", "party", "votes"])
    write_csv(out / "agra_booth.csv", booths,
              ["booth_uid", "election", "ac", "ac_name", "ps", "ps_name",
               "electors", "male", "female", "other", "epic", "tendered",
               "polled", "valid", "nota", "legacy_names", "src"])
    write_csv(out / "agra_crosswalk.csv", links,
              ["prev_uid", "curr_uid", "ac", "pair", "link", "conf"])
    sk = sorted({k for s in swings for k in s})
    write_csv(out / "agra_swing.csv", swings, sk)
    write_csv(out / "agra_anomaly.csv", flags,
              ["booth_uid", "ac", "pair", "result", "score", "top_features",
               "winner_changed", "confidence", "benign_note"])
    write_csv(out / "agra_coverage.csv", cover,
              ["election", "ac", "ac_name", "file", "booths", "valid_ok",
               "has_total", "note"])

    # Excel workbook for humans
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Coverage"
    ws.append(["election", "ac", "ac_name", "file", "booths", "valid_ok",
               "has_total", "note"])
    for r in cover:
        ws.append([r["election"], r["ac"], r["ac_name"], r["file"],
                   r["booths"], r["valid_ok"], r["has_total"], r["note"]])
    w2 = wb.create_sheet("TopSwings")
    w2.append(["pair", "ac", "prev_uid", "curr_uid", "winner changed?",
               "margin_d(pp)", "turnout_d(pp)", "nota_d(pp)", "conf"])
    for s in sorted(swings, key=lambda s: -abs(s["margin_d"]))[:200]:
        w2.append([s["pair"], s["ac"], s["prev_uid"], s["curr_uid"],
                   s["winner_changed"], s["margin_d"], s["turnout_d"],
                   s["nota_d"], s["conf"]])
    w3 = wb.create_sheet("Anomalies")
    w3.append(["booth", "ac", "pair", "result", "score", "top features",
               "winner changed", "confidence", "benign checklist"])
    for fl in sorted(flags, key=lambda x: -x["score"]):
        w3.append([fl["booth_uid"], fl["ac"], fl["pair"], fl["result"],
                   fl["score"], fl["top_features"], fl["winner_changed"],
                   fl["confidence"], fl["benign_note"]])
    w4 = wb.create_sheet("Methods")
    w4["A1"] = ("Shares = votes/polled (polled = valid + NOTA; 2024 has no "
                "electors, so turnout features are N/A for pairs touching "
                "2024). Swings in percentage points, only on crosswalk links "
                "conf>=0.8 and only for parties fielded in BOTH elections of "
                "the pair (minus UNMAPPED) — one-sided appear/vanish artefacts "
                "are excluded; new-entrant effects still surface via margin "
                "and winner change. IND is an aggregate bloc (different "
                "individuals each election). 2024 party labels are minimal (BJP "
                "verified, rest UNMAPPED TODO(verify)) so 2022>2024 party "
                "swings cover BJP/IND/NOTA-adjacent blocs only. "
                "Anomaly: residualize vs AC median, EB-shrink toward median "
                "with w=n/(n+200) so small booths don't dominate, then "
                "MAD robust-z; flags are statistical_outlier (never fraud); "
                "small booths (polled<200) are low-confidence. 2022 master "
                "sums cross-checked vs Hindi pswise duplicates (see log). "
                "See brain/MODELS.md.")
    wb.save(str(out / "agra_analysis.xlsx"))

    print("=" * 64)
    print(f"booths={len(booths)} facts={len(facts)} links={len(links)} "
          f"swing_rows={len(swings)} anomalies={len(flags)}")
    bad = [c for c in cover if not c["valid_ok"]]
    print(f"coverage rows={len(cover)} invalid_totals={len(bad)}")
    for c in bad[:10]:
        print("  INVALID:", c)
    cov = {}
    for L in links:
        cov[L["pair"]] = cov.get(L["pair"], [0, 0])
        cov[L["pair"]][1] += 1
        cov[L["pair"]][0] += L["link"] == "1:1"
    for p, (k, n) in sorted(cov.items()):
        print(f"crosswalk {p}: {k}/{n} 1:1 ({k / max(n, 1) * 100:.1f}%)")
    print(f"wrote {out}/agra_*.csv + agra_analysis.xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
