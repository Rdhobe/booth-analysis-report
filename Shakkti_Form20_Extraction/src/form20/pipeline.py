"""Orchestration: one Form 20 PDF -> FileResult (rows, totals, checks, flags)."""
import csv
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import header
from .discover import discover
from .grid import align_to_rules, apply_template, build_col_template, detect_lines, unruled_tail
from .imaging import load_page, page_count
from .inkcolumns import choose_columns, page_tokens
from .ocr import CellRead, read_cells, remove_lines
from .rescue import (fits_shortfall, follow_rows, holding_rows, ink_profile, plan_missing_rows, reference_peak,
                     rescue_edges, shortfall)
from .textlayer import open_text_doc
from .validate import ALT_GAP, MAX_CELL_VOTES, RowResult, enumerate_solutions, plain_reading, read_as_printed, solve_row

TOTAL_LABELS = ("TOTAL_EVM", "TOTAL_POSTAL", "TOTAL_POLLED")
DEFAULT_CANDIDATES = Path(__file__).resolve().parents[2] / "config" / "candidates.csv"

# Leading identifier columns (serial, polling-station number and/or name) differ between sheet variants.
ID_COL_CHOICES = (1, 2, 3)
MAX_ID_COLS = 5       # identifier columns allowed when the official candidate count fixes how many there are
PROBE_ROWS = 40        # rows (first page, then the second) read to choose between them
TEXT_PROBE_ROWS = 80   # the same when the numbers come from a text layer (free to read; sparse columns need many rows)
ID_SWITCH_MIN = 0.3    # the better choice must satisfy both vote identities on this share of probe rows ...
ID_SWITCH_GAIN = 0.2   # ... and beat the language default by this much, otherwise the default stays
PROBE_BLANK_ZERO = 3   # a probe row may have up to this many unread candidate cells (taken as 0)
DEAD_COLUMN = 0.9      # a column blank in at least this share of probe rows is text, not votes
DISCOVER_BELOW = 0.85  # when no fixed layout satisfies this share of probe rows, the structure is searched for


@dataclass
class RowOut:
    page: int
    row_in_page: int
    serial: int
    ps_no: str
    values: list                      # candidates..., valid, rejected, NOTA, total, tendered
    status: str                       # OK | AUTO_CORRECTED | REVIEW
    notes: list = field(default_factory=list)
    changed: list = field(default_factory=list)   # value indices changed by the solver
    primary: list = field(default_factory=list)   # plain first reading of the numeric cells
    min_conf: float = 0.0
    alternatives: list = field(default_factory=list)
    cells: list = None
    box: tuple = None            # (page_index, x0, y0, x1, y1) of the row on the deskewed page
    serial_read: object = None   # what OCR read in the serial cell (None: no digits)


@dataclass
class FileResult:
    pdf: str
    meta: dict
    hindi: bool
    id_cols: int
    n_cands: int
    names_native: list
    names_en: list
    parties: list
    names_source: str
    rows: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)       # label -> RowOut-like dict
    page_errors: list = field(default_factory=list)
    checks: list = field(default_factory=list)       # (label, printed, computed, ok)
    n_pages: int = 0
    seconds: float = 0.0


def load_candidate_map(path=DEFAULT_CANDIDATES):
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            out.setdefault(r["file"], []).append(r)
    for k in out:
        out[k].sort(key=lambda r: int(r["position"]))
    return out


B_ORDERS = ("vrtT", "vrTt", "vtrT", "vtTr", "vTrt", "vTtr")   # physical order of the 4 trailing columns of layout B:
#                                                                  v valid, r rejected, t tendered, T total


C_ORDERS = ("vrNt", "vrNT", "vNrt", "vNrT")   # physical order of the 4 trailing columns of layout C:
#                                               v valid, r rejected, N NOTA, t tendered, T total; one of t / T is missing


def c_missing(order):
    """Which of the total (T) / tendered (t) columns a layout-C order does not print."""
    return "T" if "t" in order else "t"


def c_synthetic_index(layout, nc):
    """Canonical index of the blank cell standing in for the column a layout-C sheet does not print."""
    return nc + 3 if c_missing(layout[2:]) == "T" else nc + 4


def b_order(layout):
    """Trailing-column order of a layout-B variant: 'B' is the default, 'B-vrTt' etc. are the others."""
    return "vrtT" if layout == "B" else layout[2:]


def m_parts(layout):
    """(candidate columns, [valid, rejected, NOTA, total, tendered] column index or None) of a discovered layout
    'M:<nc>:<v>,<r>,<N>,<T>,<t>' (indices relative to the first candidate column, '-' = not printed)."""
    _, nc, spec = layout.split(":")
    return int(nc), [None if s == "-" else int(s) for s in spec.split(",")]


def m_layout(nc, spec):
    return f"M:{nc}:" + ",".join("-" if x is None else str(x) for x in spec)


def m_unprinted(layout, nc):
    """Canonical indices of the slots a discovered layout does not print (the solver fills them from the identities)."""
    return tuple(nc + i for i, x in enumerate(m_parts(layout)[1]) if x is None)


def canonical_cells(cells, layout):
    """Numeric cells of a row (after the identifier columns) in the order solve_row expects:
    candidates | valid, rejected, NOTA, total, tendered.

    Layout B sheets carry NOTA as the last candidate-like column (and count it in the valid total) and end with
    valid, rejected, tendered, total (in one of several orders, see B_ORDERS). They are reordered here, with a synthetic zero NOTA cell filling the slot, so
    both vote identities keep their usual form; to_canonical_a() converts the finished result back."""
    if layout.startswith("M"):
        nc, spec = m_parts(layout)
        blank = CellRead(reads={"A": "", "B": ""}, confs={})
        return list(cells[:nc]) + [blank if x is None else cells[x] for x in spec]
    if layout.startswith("C"):
        nc = len(cells) - 4
        pos = dict(zip(layout[2:], cells[nc:]))
        blank = CellRead(reads={"A": "", "B": ""}, confs={})          # not printed: the solver fills it from the identities
        return list(cells[:nc]) + [pos["v"], pos["r"], pos["N"], pos.get("T", blank), pos.get("t", blank)]
    if not layout.startswith("B"):
        return cells
    nb = len(cells) - 4
    zero = CellRead(reads={"A": "0", "B": "0"}, confs={"A": 100.0, "B": 100.0})
    pos = dict(zip(b_order(layout), cells[nb:]))
    return list(cells[:nb]) + [pos["v"], pos["r"], zero, pos["T"], pos["t"]]


def _b_values(v, nc):
    """Layout-B internal values (nc+1 candidate-like columns incl. NOTA, valid, rejected, synthetic NOTA, total,
    tendered) -> canonical: nc candidates | valid (= sum of candidates), rejected, NOTA, total, tendered."""
    if v is None or len(v) != nc + 6:
        return v
    valid = v[nc + 1] - v[nc] if v[nc + 1] is not None and v[nc] is not None else None
    return list(v[:nc]) + [valid, v[nc + 2], v[nc], v[nc + 4], v[nc + 5]]


def _b_strings(p, nc):
    return list(p[:nc]) + ["", p[nc + 2], p[nc], p[nc + 4], p[nc + 5]] if len(p) == nc + 6 else p


def _b_index(i, nc):
    """Canonical index of a layout-B internal column (None for the synthetic NOTA slot and the valid column)."""
    return i if i < nc else {nc: nc + 2, nc + 2: nc + 1, nc + 4: nc + 3, nc + 5: nc + 4}.get(i)


def to_canonical_a(res):
    """Convert a finished layout-B result to the canonical column layout (NOTA as its own column)."""
    nc = res.n_cands - 1
    for r in res.rows:
        r.values = _b_values(r.values, nc)
        r.primary = _b_strings(r.primary, nc)
        r.changed = sorted({j for j in (_b_index(i, nc) for i in r.changed) if j is not None})
        r.alternatives = [(gap, _b_values(v, nc)) for gap, v in r.alternatives]
    for rr in res.totals.values():
        rr.values = _b_values(rr.values, nc)
    res.n_cands = nc
    res.names_native, res.names_en, res.parties = res.names_native[:nc], res.names_en[:nc], res.parties[:nc]


def choose_layout(table, n_cols, default_id_cols, only_k=None, n_off=None, nota_ratio=None):
    """Pick (id_cols, layout) by how many probe rows already satisfy both vote identities under each hypothesis:
    layout A (the canonical column order) or one of the B variants (see canonical_cells), with 1-3 identifier
    columns. The language default (A) stays unless another hypothesis is clearly better. Ties between B orders go to
    the default order. only_k fixes the number of identifier columns. n_off (the official candidate count) is
    stronger: it fixes the candidate columns, so only the layouts that give exactly that many are scored - A and B
    with n_cols - n_off - 5 identifier columns, and the layout-C family (four trailing columns) with one more.
    Returns (id_cols, layout, {(layout, k): share})."""
    share = {}
    n_off_given = n_off
    # columns blank in (almost) every probe row hold text (station names): never zero-fill them as candidates
    dead = {j for j in range(n_cols) if table and sum(1 for row in table if not row[j].text) >= DEAD_COLUMN * len(table)}
    if n_off is not None:
        k_a = n_cols - n_off - 5
        only_k = k_a if 1 <= k_a <= MAX_ID_COLS else None
        if only_k is None and not 1 <= k_a + 1 <= MAX_ID_COLS:
            n_off = None
    if only_k is not None:
        default_id_cols = only_k
    for k in ID_COL_CHOICES if only_k is None else (only_k,):
        nc = n_cols - k - 5
        if n_off is not None and nc != n_off:
            continue                        # A and B with this many identifier columns give the wrong candidate count
        no_zero = {j - k for j in dead}
        if nc >= 2 and table:
            share[("A", k)] = sum(plain_reading(row[k:], nc, (nc + 1, nc + 2), PROBE_BLANK_ZERO, no_zero) is not None
                                  for row in table) / len(table)
        nb = n_cols - k - 4
        if nb >= 3 and table:
            for order in B_ORDERS:
                name = "B" if order == "vrtT" else "B-" + order
                share[(name, k)] = sum(
                    plain_reading(canonical_cells(row[k:], name), nb, (nb + 1, nb + 2, nb + 4), PROBE_BLANK_ZERO,
                                  no_zero) is not None for row in table) / len(table)
    if n_off is not None and table:
        k_c = n_cols - n_off - 4                                    # layout C: four trailing columns
        if 1 <= k_c <= MAX_ID_COLS:
            no_zero_c = {j - k_c for j in dead}
            for order in C_ORDERS:
                name = "C:" + order
                syn = c_synthetic_index(name, n_off)
                share[(name, k_c)] = sum(
                    plain_reading(canonical_cells(row[k_c:], name), n_off, (n_off + 1, n_off + 2, syn),
                                  PROBE_BLANK_ZERO, no_zero_c) is not None for row in table) / len(table)
    default = ("A", default_id_cols)
    top = max(share.values()) if share else 0.0
    if n_off_given is not None and table and top < DISCOVER_BELOW:
        # none of the fixed layouts fits: look for the structure by arithmetic (see discover.py)
        found = discover([[int(c.text) if c.text.isdigit() else None for c in row] for row in table], n_off_given,
                         nota_ratio=nota_ratio)
        if found and found[3] > top + 0.05:
            k, nc, spec, found_share = found
            name = m_layout(nc, spec)
            share[(name, k)] = found_share
            return k, name, share
    if not share:
        return default_id_cols, "A", share
    best = max(share, key=lambda h: (share[h], h == default, h[0] == "B", h[0] == "A"))
    if best != default and share[best] >= ID_SWITCH_MIN and share[best] >= share.get(default, 0.0) + ID_SWITCH_GAIN:
        return best[1], best[0], share
    return default_id_cols, "A", share


def detect_layout(gray, grid, default_id_cols, only_k=None, n_off=None, reader=None, probe_rows=PROBE_ROWS,
                  nota_ratio=None, more=()):
    """Read the first rows of the first page and choose the layout (see choose_layout). `reader` replaces the OCR
    (textlayer.TextDoc.reader); reading is free then, so probe_rows can be raised to see sparse columns. `more` lists
    (gray, grid) of further pages whose first rows join the probe until it holds probe_rows rows: the layouts are told
    apart by the share of rows that satisfy them, and a handful of rows lets one misread row decide."""
    edges = grid.data_edges[: probe_rows + 1]
    if len(edges) < 4:
        return (only_k or default_id_cols), "A", {}
    table = list((reader or read_cells)(gray, grid, edges))
    for more_gray, more_grid in more:
        room = probe_rows - len(table)
        if room < 4 or len(more_grid.data_edges) < 5:
            break
        table += list(read_cells(more_gray, more_grid, more_grid.data_edges[: room + 1]))
    return choose_layout(table, len(grid.col_edges) - 1, default_id_cols, only_k, n_off, nota_ratio)


def choose_id_cols(table, n_cols, default):
    """Pick how many leading identifier columns the sheet has.

    For each choice the remaining columns are read as candidates + 5 totals, and the choice for which most probe
    rows already satisfy both vote identities wins. Returns (id_cols, {choice: share of consistent rows})."""
    share = {}
    for k in ID_COL_CHOICES:
        nc = n_cols - k - 5
        if nc >= 2 and table:
            blank_ok = (nc + 1, nc + 2)     # rejected / NOTA may be printed blank; a blank candidate cell never counts
            share[k] = sum(plain_reading(row[k:], nc, blank_ok) is not None for row in table) / len(table)
    if not share:
        return default, share
    best = max(share, key=lambda k: (share[k], k == default))
    if best != default and share[best] >= ID_SWITCH_MIN and share[best] >= share.get(default, 0.0) + ID_SWITCH_GAIN:
        return best, share
    return default, share


def detect_id_cols(gray, grid, default):
    """Read the first rows of the first page and choose the identifier-column count (see choose_id_cols)."""
    edges = grid.data_edges[: PROBE_ROWS + 1]
    if len(edges) < 4:
        return default, {}
    return choose_id_cols(read_cells(gray, grid, edges), len(grid.col_edges) - 1, default)


NUMBERING_MAX = 40     # column numbers printed in a header never exceed this


def _is_numbering_row(cells):
    """True for a row of column numbers, even a partial one: every printed cell holds its own column number, i.e. the
    value minus the position is the same for all of them ('10 11 12 13' over the last four columns, or '10 . 12')."""
    pts = [(i, int(c.text)) for i, c in enumerate(cells) if c.text.isdigit()]
    if len(pts) < 2 or any(v > NUMBERING_MAX for _, v in pts):
        return False
    offset = pts[0][1] - pts[0][0]
    return offset >= 1 and all(v - i == offset for i, v in pts)


def _is_index_row(row, n_cols):
    hits = sum(1 for c, cell in enumerate(row) if cell.text == str(c + 1))
    return hits >= 0.6 * n_cols


def _num_cells(row, id_cols):
    return row[id_cols:]


def _parse_ps(text):
    m = re.fullmatch(r"(\d+)([A-Z]?)", text or "")
    return (int(m.group(1)), m.group(2)) if m else None


def _assign_serials(pages_rows):
    """Serial numbers form one continuous sequence 1..N across the file, so a
    page starts at (previous last + 1). The narrow serial cells are read badly,
    so reads are only used to detect a real break in the sequence (a clear
    majority of reads agreeing on a different offset)."""
    prev_last = 0
    for rows in pages_rows:
        if not rows:
            continue
        expected = prev_last + 1

        def agrees(off):
            n = 0
            for i, r in enumerate(rows):
                v, want = r["serial_read"], str(off + i)
                if v is not None and (str(v) == want or (len(str(v)) >= 2 and want.endswith(str(v)))):
                    n += 1
            return n

        offset = expected
        reads = [(r["serial_read"] - i) for i, r in enumerate(rows) if r["serial_read"] and r["serial_read"] >= 100]
        if len(reads) >= 5:
            alt, support = Counter(reads).most_common(1)[0]
            if alt != expected and support >= 0.6 * len(reads) and agrees(alt) > 2 * agrees(expected):
                offset = alt
                note = f"serial discontinuity (expected {expected}, page starts at {alt})"
                if note not in rows[0]["notes"]:
                    rows[0]["notes"].append(note)
        for i, r in enumerate(rows):
            r["serial"] = offset + i
        prev_last = rows[-1]["serial"]


def _assign_ps(all_rows, hindi):
    """English sheets carry a separate polling-station number that increments by
    one per row, except for rows with a letter suffix (41, 41A, 42): such a row
    repeats the previous base. The narrow cells are read unreliably, so the
    sequence is used and the read only decides whether a row is a suffix row."""
    prev_base, prev_suffix = 0, ""
    agree = total = 0
    for r in all_rows:
        if hindi:
            r["ps_no"] = str(r["serial"])
            continue
        got = _parse_ps(r["ps_read"])
        if got and got[1] and got[0] == prev_base and prev_suffix == "":
            base, suffix = got
        else:
            base, suffix = prev_base + 1, ""
        r["ps_no"] = f"{base}{suffix}"
        if got and len(r["ps_read"]) >= 2:
            total += 1
            agree += got == (base, suffix)
        prev_base, prev_suffix = base, suffix
    return agree, total


def _place(gray, pl, template, ink=False):
    """The column template laid on a page: snapped to the detected vertical rules and slid onto them - or, when the
    columns were found from the digits (ink=True), laid on the table's extent as it is."""
    if ink:
        return apply_template(pl, template, snap_tol=0.0, register=False)
    grid = apply_template(pl, template)
    return align_to_rules(gray, grid) if gray is not None else grid


def _digit_columns(pdf_path, lines, template, allowed_cols):
    """The column template, replaced by one found from where the digits sit when the column lines do not fit the
    official candidate count or cut through the numbers (see inkcolumns.choose_columns). Returns (template, from_digits,
    why)."""
    pages = []
    for p, pl in enumerate(lines):
        if pl is not None:
            g, _ = load_page(pdf_path, p)
            pages.append(page_tokens(remove_lines(g, pl.pitch), pl))
    return choose_columns(pages, template, allowed_cols)


def _rescue_tail(pdf_path, lines, pages_rows, template, make_row, progress, stem, id_cols, alnum, official, layout, ink=False):
    """Rows lost at the end of the last page: the votes still missing against the official totals say how many booths to
    look for below the last row read. Bands that hold digits are read one by one and kept while the row fits what is
    still missing in every column - a row that overshoots is a totals row or a stray line, and stops the search. (The
    line detector often files the last booths as "total rows", so the rows it calls totals are looked at too.)"""
    if official is None or not any(pages_rows):
        return
    last = max(p for p, rows in enumerate(pages_rows) if rows)
    pl = lines[last]
    if pl is None:
        return
    b = layout.startswith("B")
    votes = list(official["candidates"]) + ([official["nota"]] if b else [])
    values = [r["res"].values for rows in pages_rows for r in rows]
    missing = shortfall(values, votes)
    if not missing or min(missing.values()) < -TAIL_SLACK:
        return
    booth = sum(sum((v[c] or 0) for c in missing) for v in values) / max(len(values), 1)
    wanted = int(round(sum(max(v, 0) for v in missing.values()) / booth)) if booth else 0
    if wanted < 1:
        return
    g, _ = load_page(pdf_path, last)
    grid = _place(g, pl, template, ink)
    pitch = float(np.median(np.diff(grid.data_edges)))
    clean = remove_lines(g, pitch)
    profile = ink_profile(clean, grid, id_cols, pitch)
    edges = follow_rows(grid.data_edges[-1], pitch, min(wanted + 2, 8), +1, pl.row_lines, profile,
                        reference_peak(profile, grid.data_edges))
    n = holding_rows(clean, grid, id_cols, grid.data_edges[-1], edges, +1)
    if not n:
        return
    use = [grid.data_edges[-1]] + edges[:n]
    kept = []
    for r, row in enumerate(read_cells(g, grid, use, alnum_cols=alnum)):
        made = make_row(last, grid, row, use[r], use[r + 1])
        if not isinstance(made, dict) or made["res"].status == "REVIEW" or not fits_shortfall(made["res"].values, missing):
            break
        for c in missing:
            missing[c] -= made["res"].values[c] or 0
        made["notes"].append("row recovered below the last row read, to make up votes missing against the official totals")
        kept.append(made)
    if kept:
        pages_rows[last] = pages_rows[last] + kept
        for i, r in enumerate(pages_rows[last]):
            r["row_in_page"] = i + 1
        progress(f"[{stem}] page {last + 1}: {len(kept)} row(s) recovered below the last one read "
                 "(votes missing against the official totals)")
        _assign_serials(pages_rows)


def _rescue_missing_rows(pdf_path, lines, pages_rows, template, make_row, progress, stem, id_cols, alnum, ink=False,
                         official=None, layout="A"):
    """Pages that came out short of rows (see rescue.py): read the rows the line detector missed, keep those whose
    arithmetic holds and - when the official totals are known - that fit the votes still missing, and number everything
    again. A page one row short with no serial jump behind it is ordinary variation and is left alone."""
    plan, unknown = plan_missing_rows(pages_rows)
    missing = None
    if official is not None:
        votes = list(official["candidates"]) + ([official["nota"]] if layout.startswith("B") else [])
        missing = shortfall([r["res"].values for rows in pages_rows for r in rows], votes)
        if missing is None or min(missing.values()) < -TAIL_SLACK:
            missing = None                     # the columns are not the official ones, or the sheet is already over
    if missing is None:                        # nothing to vouch for a row: only a clear shortage (2 or more) is acted on
        unknown = {p: k for p, k in unknown.items() if k >= 2}
    if not plan and not unknown:
        return
    for p in sorted(set(plan) | set(unknown)):
        pl = lines[p]
        if pl is None:
            continue
        up, down = plan.get(p, (0, 0))
        g, _ = load_page(pdf_path, p)
        grid = _place(g, pl, template, ink)
        above, below = rescue_edges(g, grid, pl.row_lines, id_cols, up, down, unknown.get(p, 0))
        added = {"top": [], "bottom": []}
        tried = 0
        for where, edges in (("top", above + [grid.data_edges[0]] if above else []),
                             ("bottom", [grid.data_edges[-1]] + below if below else [])):
            if len(edges) < 2:
                continue
            tab = read_cells(g, grid, edges, alnum_cols=alnum)
            for r, row in enumerate(tab):
                made = make_row(p, grid, row, edges[r], edges[r + 1])
                tried += 1
                if not isinstance(made, dict) or made["res"].status == "REVIEW":    # junk or unreadable: leave it out
                    continue
                if missing is not None:
                    if not fits_shortfall(made["res"].values, missing):               # more votes than are missing: not a booth
                        continue
                    for c in missing:
                        missing[c] -= made["res"].values[c] or 0
                made["notes"].append("row recovered: its ruling lines were not detected on the scan")
                added[where].append(made)
        k = len(added["top"]) + len(added["bottom"])
        progress(f"[{stem}] page {p + 1}: rescue wanted {up} above / {down} below / {unknown.get(p, 0)} at an unknown end; "
                 f"{len(above)} above and {len(below)} below hold digits; {tried} read, {k} kept")
        if k:
            pages_rows[p] = added["top"] + pages_rows[p] + added["bottom"]
            for i, r in enumerate(pages_rows[p]):
                r["row_in_page"] = i + 1
            progress(f"[{stem}] page {p + 1}: {k} row(s) the line detector missed were recovered")
    _assign_serials(pages_rows)


def rescue_short_pages(pdf_path, lines, progress, stem):
    """Second chance for pages where no table was found: the last page of a sheet often has only a booth or two above
    the totals rows, too few for the regular-run detector. Knowing the file's row pitch from the other pages, a run of
    even one row is accepted - but only if the table's left and right edges line up with the other pages' and enough
    column rules are found, so a cover sheet or a page of text is not mistaken for table."""
    found = [pl for pl in lines if pl is not None]
    if len(found) < 2 or all(pl is not None for pl in lines):
        return
    pitch = sorted(pl.pitch for pl in found)[len(found) // 2]
    left = sorted(pl.left for pl in found)[len(found) // 2]
    right = sorted(pl.right for pl in found)[len(found) // 2]
    for p, pl in enumerate(lines):
        if pl is not None:
            continue
        g, _ = load_page(pdf_path, p)
        cand = detect_lines(g, min_run=1, pitch_hint=pitch)
        tol = 0.05 * (right - left)
        if (cand is not None and abs(cand.left - left) <= tol and abs(cand.right - right) <= tol
                and len(cand.col_candidates) >= 5):
            lines[p] = cand
            progress(f"[{stem}] page {p + 1}: short table found ({len(cand.data_edges) - 1} row(s))")


TEMPLATE_RETRIES = ((0.008, 0.6), (0.012, 0.6), (0.02, 0.6), (0.012, 0.4), (0.02, 0.4))   # (tol, min_frac) of the vote


def choose_template(lines, expected_cols=None):
    """Column template for a file. The default vote over all pages is kept unless the number of columns it finds is
    not one of expected_cols (known from the official candidate count); then looser votes are tried in turn.
    Returns (template, (tol, min_frac) used or None for the default)."""
    template = build_col_template(lines)
    if not expected_cols or len(template) - 1 in expected_cols:
        return template, None
    for tol, min_frac in TEMPLATE_RETRIES:
        t = build_col_template(lines, tol=tol, min_frac=min_frac)
        if len(t) - 1 in expected_cols:
            return t, (tol, min_frac)
    return template, None


def process_pdf(pdf_path, candidates_csv=DEFAULT_CANDIDATES, progress=print, name_pages=3, official=None,
                expected_cols=None, expected_candidates=None, limit_pages=None, text_layer=None):
    """text_layer: read the numbers from the PDF's text layer when it has a usable one (see textlayer.py), which is
    exact and needs no OCR. None means yes unless the environment variable FORM20_TEXT_LAYER is "off"."""
    t0 = time.time()
    pdf_path = str(pdf_path)
    stem = Path(pdf_path).name
    n = page_count(pdf_path)
    if text_layer is None:
        text_layer = os.environ.get("FORM20_TEXT_LAYER", "auto") != "off"
    # the text layer cannot see a column with no number in it, so layouts B and C (one column fewer) are allowed too
    n_off = expected_candidates if expected_candidates is not None else (len(official["candidates"]) if official else None)
    td = open_text_doc(pdf_path, expected_cols | {c - 1 for c in expected_cols} if expected_cols else None, n_off)         if text_layer else None

    # ---- pass 1: table lines on every page -> column template
    progress(f"[{stem}] pass 1/2: locating tables on {n} pages")
    lines, first_gray = [], None
    if td is not None:
        progress(f"[{stem}] text layer found: numbers are read from the PDF, no OCR")
        lines = [td.page_lines(p) for p in range(n)]
        first_gray, _ = load_page(pdf_path, 0)
    else:
        for p in range(n):
            g, _ = load_page(pdf_path, p)
            lines.append(detect_lines(g))
            if p == 0:
                first_gray = g
        rescue_short_pages(pdf_path, lines, progress, stem)
    template, vote = choose_template(lines, expected_cols)
    n_cols = len(template) - 1
    if vote:
        progress(f"[{stem}] column vote loosened to tol={vote[0]}, min_frac={vote[1]}: {n_cols} columns")
    ink = False
    if td is None and expected_cols:
        template, ink, why = _digit_columns(pdf_path, lines, template, set(expected_cols) | {c - 1 for c in expected_cols})
        if ink:
            n_cols = len(template) - 1
            progress(f"[{stem}] columns found from the digits instead of the column lines: {why}")

    # ---- title block / language / layout
    grid0 = _place(None, next(pl for pl in lines if pl), template, ink)
    first_pl = lines[0] or next(pl for pl in lines if pl)
    title = header.title_text(first_gray, apply_template(first_pl, template, register=not ink))
    hindi = header.is_hindi(title)
    meta = header.parse_title(title, hindi)
    id_cols, layout, id_share = 1 if hindi else 2, "A", {}
    if lines[0] is not None:
        if td is None and not ink:
            grid0 = align_to_rules(first_gray, grid0)
        nota_ratio = official["nota"] / max(sum(official["candidates"]), 1) if official else None
        more = []
        if td is None and len(lines) > 1 and lines[1] is not None:       # rows of the second page join the probe
            g1 = load_page(pdf_path, 1)[0]
            more.append((g1, _place(g1, lines[1], template, ink)))
        id_cols, layout, id_share = detect_layout(first_gray, grid0, id_cols, None, n_off,
                                                  td.reader(0) if td is not None else None,
                                                  TEXT_PROBE_ROWS if td is not None else PROBE_ROWS, nota_ratio, more)
    if id_share:
        shares = ", ".join(f"{h[0]}{h[1]}: {v:.0%}" for h, v in sorted(id_share.items()) if v >= 0.05) or "none above 5%"
        progress(f"[{stem}] identifier columns: {id_cols}, layout {layout} (share of probe rows consistent: {shares})")
    has_ps_col = not hindi and id_cols == 2     # a separate polling-station number column to read and sequence-check
    n_cands = (m_parts(layout)[0] if layout[0] == "M"
               else n_cols - id_cols - (4 if layout[0] in "BC" else 5))   # layout B counts NOTA among the candidates
    progress(f"[{stem}] language={'Hindi' if hindi else 'English'} columns={n_cols} candidates={n_cands} meta={meta}")

    # ---- pass 2: read every page
    pages_rows, all_name_reads, totals_rows, page_errors, dropped = [], [], [], [], []
    alnum = (1,) if has_ps_col else ()

    def make_row(p, grid, row, y0, y1):
        """A row dict for one table row read from page p between y0 and y1; "index" for a row of column numbers and
        "non_data" for a stray line, border or footer."""
        if hindi and _is_index_row(row, n_cols):
            return "index"
        numeric = canonical_cells(_num_cells(row, id_cols), layout)
        printed = sum(1 for c in numeric if c.text)
        non_data = printed < 0.4 * len(numeric)
        if td is not None:
            # a text layer prints no digit for a zero cell, so a real booth can have few numbers: it is still a booth
            # when its valid or total is printed - but some candidate must have votes in it. A row of column
            # numbers is not one, however many cells it fills.
            non_data = ((non_data and not (numeric[n_cands].text or numeric[n_cands + 3].text)) or printed < 2
                    or not any(c.text for c in numeric[:n_cands]) or _is_numbering_row(_num_cells(row, id_cols)))
        if non_data:
            return "non_data"
        res = solve_row(numeric, n_cands)
        serial_txt = row[0].reads.get("A", "")
        ps_txt = row[1].reads.get("A", "") if has_ps_col else ""
        conf = min([c.conf for c in _num_cells(row, id_cols) if c.text] or [0.0])
        return {
            "page": p + 1,
            "row_in_page": 0,
            "serial_read": int(serial_txt) if serial_txt.isdigit() else None,
            "ps_read": ps_txt,
            "res": res,
            "cells": numeric,
            "box": (p, grid.left, y0, grid.right, y1),
            "notes": [],
            "conf": conf,
        }

    for p in range(n if limit_pages is None else min(n, limit_pages)):
        pl = lines[p]
        if pl is None:
            page_errors.append((p + 1, "table not found"))
            pages_rows.append([])
            continue
        g = None if td is not None else load_page(pdf_path, p)[0]
        grid = _place(g, pl, template, ink)
        tab = (td.reader(p) if td is not None else read_cells)(g, grid, grid.data_edges, alnum_cols=alnum)
        outside = unruled_tail(g, grid) if td is None and not ink else 0   # footer lines below the table's own rules
        rows = []
        for r, row in enumerate(tab):
            made = "non_data" if r >= len(tab) - outside else make_row(p, grid, row, grid.data_edges[r], grid.data_edges[r + 1])
            if made == "non_data":
                dropped.append((p + 1, r + 1))   # not a data row (stray line / border / footer)
            elif isinstance(made, dict):
                made["row_in_page"] = len(rows) + 1
                rows.append(made)
        pages_rows.append(rows)
        if pl.total_edges and len(pl.total_edges) >= 2:
            ttab = read_cells(g, grid, pl.total_edges, alnum_cols=alnum)
            for k, row in enumerate(ttab[:3]):
                totals_rows.append(
                    (TOTAL_LABELS[k], solve_row(canonical_cells(_num_cells(row, id_cols), layout), n_cands)))
        if td is None and p < name_pages:
            all_name_reads.append(header.read_candidate_names(g, grid, id_cols, n_cands, hindi))
        unprinted = ((c_synthetic_index(layout, n_cands),) if layout.startswith("C")
                     else m_unprinted(layout, n_cands) if layout.startswith("M") else ())
        printed = sum(read_as_printed(r["res"], n_cands, unprinted) for r in rows)
        progress(f"[{stem}] page {p + 1}/{n}: {len(rows)} rows, {printed} read as printed")

    # ---- ids
    _assign_serials(pages_rows)
    if td is None and limit_pages is None:
        _rescue_missing_rows(pdf_path, lines, pages_rows, template, make_row, progress, stem, id_cols, alnum, ink,
                             official, layout)
        _rescue_tail(pdf_path, lines, pages_rows, template, make_row, progress, stem, id_cols, alnum, official, layout, ink)
    flat = [r for rows in pages_rows for r in rows]
    ps_agree, ps_total = _assign_ps(flat, not has_ps_col)

    # ---- candidate names (reviewed mapping wins over OCR)
    cmap = load_candidate_map(candidates_csv).get(stem, [])
    ocr_names = header.consensus(all_name_reads) if all_name_reads else [""] * n_cands
    if len(cmap) == n_cands:
        names_native = [r["name_native"] for r in cmap]
        names_en = [r["name_en"] for r in cmap]
        parties = [r.get("party", "") for r in cmap]
        names_source = "candidates.csv (reviewed)"
    else:
        names_native = ocr_names
        names_en = ocr_names if not hindi else [""] * n_cands
        parties = [""] * n_cands
        names_source = "OCR - UNVERIFIED, add this file to config/candidates.csv"

    res = FileResult(
        pdf=stem, meta=meta, hindi=hindi, id_cols=id_cols, n_cands=n_cands,
        names_native=names_native, names_en=names_en, parties=parties,
        names_source=names_source, n_pages=n, page_errors=page_errors,
    )
    for r in flat:
        rr = r["res"]
        notes = list(r["notes"])
        status = rr.status
        if rr.note:
            notes.append(rr.note)
        cands = [v for v in rr.values[:n_cands] if v]
        if cands:
            top, count = Counter(cands).most_common(1)[0]
            if top >= 3 and count >= max(5, int(0.4 * n_cands)) and status in ("OK", "AUTO_CORRECTED"):
                notes.append(
                    f"unusual source row: the value {top} appears in {count} candidate columns - "
                    "arithmetic is consistent but please glance at the scan"
                )
                status = "UNUSUAL"
        if any("discontinuity" in x for x in notes) and status == "OK":
            status = "REVIEW"
        res.rows.append(
            RowOut(
                page=r["page"], row_in_page=r["row_in_page"], serial=r["serial"], ps_no=r["ps_no"],
                values=rr.values, status=status, notes=notes, changed=rr.changed,
                primary=rr.primary, min_conf=r["conf"], alternatives=rr.alternatives, cells=r["cells"], box=r["box"],
                serial_read=r["serial_read"],
            )
        )
    for label, rr in totals_rows:
        res.totals[label] = rr

    res.meta["layout"] = layout
    res.meta["source"] = "text layer" if td is not None else "ocr"
    drop_index_rows(res)
    drop_impossible_rows(res)
    if td is None:
        drop_summary_rows(res)
    drop_subtotal_rows(res)
    drop_duplicate_pages(res)
    drop_total_rows(res)
    if official is not None:
        drop_official_total_rows(res, official)
        drop_excess_rows(res, official)
    before = None
    if official is not None and apply_official_totals(res, official):
        before = [list(r.values) for r in res.rows]
    _reconcile_with_totals(res)
    if before is not None:
        res.meta["official_repair_rows"] = sum(1 for r, b in zip(res.rows, before) if r.values != b)
    if os.environ.get("FORM20_HARVEST_DIR"):
        res.meta["harvested_crops"] = harvest_crops(res, Path(os.environ["FORM20_HARVEST_DIR"]) / f"{Path(stem).stem}.npz")
    if layout.startswith("B"):
        to_canonical_a(res)
    _column_checks(res)
    res.meta['ps_read_agreement'] = (ps_agree, ps_total)
    res.meta['dropped_non_data_rows'] = dropped
    res.seconds = time.time() - t0
    return res


CROP_H, CROP_W = 32, 128      # stored training crops: ink (255) on black, height 32, width padded to 128


def harvest_crops(res, out_path):
    """Save labelled cell crops from the rows whose values the sheet's own arithmetic has confirmed, as training data
    for a neural digit reader (see batch/train_reader.py). The label is the row's final value. A cell is 'easy' when
    the OCR read exactly that, and 'hard' when the OCR read something else or nothing and the arithmetic fixed it (the
    cases the reader must learn); hard cells are only taken from rows with at most 2 of them. Rows needing review are
    skipped."""
    import cv2
    import numpy as np

    X, W, y, hard = [], [], [], []
    for r in res.rows:
        if r.status not in ("OK", "AUTO_CORRECTED") or not r.cells or len(r.cells) != len(r.values):
            continue
        wrong = [i for i, (v, p) in enumerate(zip(r.values, r.primary)) if v is not None and p != str(v)]
        if len(wrong) > 2:
            continue
        for i, (cell, v, p) in enumerate(zip(r.cells, r.values, r.primary)):
            if cell.crop is None or v is None:
                continue
            label, is_hard = str(v), p != str(v)
            h, w = cell.crop.shape
            nw = max(1, min(CROP_W, round(w * CROP_H / h)))
            img = cv2.resize(cell.crop, (nw, CROP_H), interpolation=cv2.INTER_AREA)
            canvas = np.zeros((CROP_H, CROP_W), np.uint8)
            canvas[:, :nw] = img
            X.append(canvas)
            W.append(nw)
            y.append(label)
            hard.append(is_hard)
    if X:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out_path, X=np.stack(X), W=np.array(W, np.int16), y=np.array(y),
                            hard=np.array(hard, np.uint8))
    return len(X)


DUPLICATE_PAGE_SHARE = 0.6    # a page whose rows repeat the previous page's at least this much is a re-scan of it


def drop_duplicate_pages(res):
    """Remove pages that are a second scan of the page before them.

    Some PDFs hold the same page twice (the operator scanned it again). Every booth on it would be counted twice. A page
    whose rows are identical, value for value, to the rows of the previous page in at least DUPLICATE_PAGE_SHARE of the
    cases cannot come from different booths. Returns the dropped page numbers."""
    by_page = {}
    for r in res.rows:
        by_page.setdefault(r.page, []).append(r)
    pages = sorted(by_page)
    drop = []
    for a, b in zip(pages, pages[1:]):
        A, B = by_page[a], by_page[b]
        same = sum(1 for u, v in zip(A, B) if u.values == v.values and any(x for x in u.values if x))
        if len(B) >= 5 and same >= DUPLICATE_PAGE_SHARE * min(len(A), len(B)):
            drop.append(b)
    if drop:
        res.rows[:] = [r for r in res.rows if r.page not in drop]
        res.meta["dropped_duplicate_pages"] = drop
    return drop


MIN_INDEX_COLS = 6      # fewer candidate columns than this and 1..n could be a real booth
SUBTOTAL_MIN_ROWS = 5   # rows a sub-total must have above it (since the previous one, or in all) to be recognised ...
SUMMARY_TIMES = 6           # a row with more than this many times the median valid votes is a page or running total
SUMMARY_BLANK_ID_TIMES = 4  # ... or this many when its serial cell has no digits (a label such as 'total of this page')
TAIL_SLACK = 20         # votes a column may already be over the official total before the tail rescue is not tried
SUBTOTAL_INFORMATIVE = (20, 2)   # ... unless it has this many valid votes in at least this many candidate columns


def drop_impossible_rows(res):
    """Remove rows holding a vote count no booth can have, from a PDF read through its text layer.

    The digits of a text layer are exact, so a cell above MAX_CELL_VOTES is not a misread: the row is a sheet total
    (grand total, sub-total, 'total of the chak'). Its big cells would be blanked as impossible further on, which hides
    it from the exact-sum rules, and its small cells would then be counted as a booth. OCR rows are left alone - there a
    huge number may be a misread digit in a real booth. Returns the dropped (page, serial) list."""
    if res.meta.get("source") != "text layer":
        return []
    kept, dropped = [], []
    for r in res.rows:
        (dropped if any(p.isdigit() and int(p) > MAX_CELL_VOTES for p in r.primary) else kept).append(r)
    if not dropped:
        return []
    res.rows[:] = kept
    gone = [(t.page, t.serial) for t in dropped]
    res.meta["dropped_impossible_rows"] = gone
    return gone


def drop_summary_rows(res):
    """Remove page totals, 'previous pages' totals and running totals that were read as polling stations.

    Some sheets print three such rows under every page. Their votes are a page's worth or the whole file's, so they are
    many times any booth: a row with more than SUMMARY_TIMES the median valid votes (SUMMARY_BLANK_ID_TIMES if it has no
    serial number, as a labelled row has not), or whose valid cell is unreadable because the number is impossible for a
    booth, is not a polling station. Used for scans, where digit errors keep the exact-sum rules from seeing these rows;
    a misread digit cannot make a booth that large (the cell would be refused as impossible first).
    Returns the dropped (page, serial) list."""
    rows, nc = res.rows, res.n_cands
    valid = sorted(r.values[nc] for r in rows if r.values[nc])
    if len(valid) < 30:
        return []
    median = valid[len(valid) // 2]

    def summary(r):
        v = r.values[nc]
        blank_id = r.serial_read is None
        if v is None:
            return blank_id
        return v > SUMMARY_TIMES * median or (blank_id and v > SUMMARY_BLANK_ID_TIMES * median)

    dropped = [r for r in rows if summary(r)]
    if not dropped:
        return []
    rows[:] = [r for r in rows if not summary(r)]
    gone = [(t.page, t.serial) for t in dropped]
    res.meta["dropped_summary_rows"] = gone
    return gone


def drop_subtotal_rows(res):
    """Remove sub-total rows that were read as polling stations.

    Some sheets print a total at the foot of every page (or a running total). Such a row equals, exactly and in every
    candidate-like column and in valid, the sum of the rows above it since the previous sub-total, or of all rows
    above it; counting it as a booth doubles the sheet's votes. A real booth cannot equal the sum of five others in
    every column, so exact equality is enough. A row with real content (SUBTOTAL_INFORMATIVE) that repeats the sum of
    even one row above it - the total of a one-booth section, which is simply a row identical to the one above - is a
    sub-total too; rows of near-zero votes could repeat by chance, so those need SUBTOTAL_MIN_ROWS rows above them.
    Returns the dropped (page, serial) list."""
    rows, nc = res.rows, res.n_cands
    cols = range(nc + 1)
    block, run = [0] * (nc + 1), [0] * (nc + 1)
    block_n = run_n = 0
    kept, dropped = [], []
    for r in rows:
        v = r.values
        full = all(v[c] is not None for c in cols) and any(v[c] for c in cols)
        informative = full and v[nc] >= SUBTOTAL_INFORMATIVE[0] and sum(1 for c in range(nc) if v[c]) >= SUBTOTAL_INFORMATIVE[1]
        need = 1 if informative else SUBTOTAL_MIN_ROWS
        repeat = informative and bool(kept) and all(v[c] == kept[-1].values[c] for c in cols)
        if full and (repeat or (block_n >= need and all(v[c] == block[c] for c in cols))
                     or (run_n >= need and all(v[c] == run[c] for c in cols))):
            dropped.append(r)
            block, block_n = [0] * (nc + 1), 0
            continue
        kept.append(r)
        for c in cols:
            block[c] += v[c] or 0
            run[c] += v[c] or 0
        block_n += 1
        run_n += 1
    if not dropped:
        return []
    rows[:] = kept
    gone = [(t.page, t.serial) for t in dropped]
    res.meta["dropped_subtotal_rows"] = gone
    return gone


def drop_index_rows(res):
    """Remove the header's column-number row (1 2 3 ... n) that was read as a polling station.

    Many sheets print the column numbers under the column titles, and where the header repeats on every page the row
    is read once per page, adding 1, 2, ... n to the candidate columns each time so they can never match the official
    totals. A booth whose candidate columns are the numbers 1..n in some order, or run up by one from any start (the
    numbering often continues from the identifier columns: 8, 9, ... 14), is not a polling station (the leading
    candidates alone get hundreds of votes). Returns the dropped (page, serial) list."""
    nc = res.n_cands
    if nc < MIN_INDEX_COLS:
        return []
    want = list(range(1, nc + 1))
    kept, dropped = [], []
    for r in res.rows:
        v = r.values[:nc]
        index_like = None not in v and (sorted(v) == want or (v[0] >= 1 and v == list(range(v[0], v[0] + nc))))
        (dropped if index_like else kept).append(r)
    if not dropped:
        return []
    res.rows[:] = kept
    res.meta["dropped_index_rows"] = [(t.page, t.serial) for t in dropped]
    return res.meta["dropped_index_rows"]


def drop_total_rows(res):
    """Remove printed total rows that were read as polling stations.

    Many sheets print 'Total EVM votes' / 'Total votes polled' in the same table as the booths, so the extractor reads
    them as booths and every column sum comes out 2-4 times too large. A row whose candidate and valid columns equal
    the sum of all rows before it (exactly, over every column) is such a grand total; it and everything after it
    that merely repeats it or is blank (a postal-ballot line) are dropped. Returns the dropped (page, serial) list."""
    rows, nc = res.rows, res.n_cands
    cols = range(nc + 1)                                   # candidate-like columns + total valid
    run = [0] * (nc + 1)
    for i, r in enumerate(rows):
        v = r.values
        if i >= len(rows) // 2 and all(v[c] is not None for c in cols) and any(v[c] for c in cols) \
                and all(v[c] == run[c] for c in cols):
            tail = rows[i:]
            if all(all((t.values[c] or 0) == v[c] for c in cols) or not any(t.values[c] for c in cols) for t in tail):
                dropped = [(t.page, t.serial) for t in tail]
                res.meta["dropped_total_rows"] = dropped
                del rows[i:]
                return dropped
            return []
        for c in cols:
            run[c] += v[c] or 0
    # Second rule, for sheets where a misread booth breaks the exact match above: trailing rows whose valid votes are
    # far larger than any booth (more than OUTLIER_TIMES the median) are totals; blank rows around them go too.
    valid = sorted(r.values[nc] for r in rows if r.values[nc])
    if len(valid) >= 20:
        median = valid[len(valid) // 2]
        i = len(rows)
        while i > 0 and rows[i - 1].values[nc] is not None and (
                rows[i - 1].values[nc] == 0 or rows[i - 1].values[nc] > OUTLIER_TIMES * median):
            i -= 1
        if i < len(rows) and any(r.values[nc] > OUTLIER_TIMES * median for r in rows[i:]):
            dropped = [(t.page, t.serial) for t in rows[i:]]
            res.meta["dropped_total_rows"] = dropped
            del rows[i:]
            return dropped
    return []


OUTLIER_TIMES = 15     # a booth row with more than this many times the median valid votes is really a total row
EXCESS_MIN_VOTES, EXCESS_MIN_COLUMNS = 8, 2   # an excess smaller than this cannot tell a stray row from a real small booth
OFFICIAL_ROW_MATCHES = 4   # a row repeating this many different official column totals is a total row
OFFICIAL_ROW_MIN = 50      # official figures below this are too small to rule anything out (a booth can have 12 votes)


def drop_official_total_rows(res, official):
    """Remove total rows that the exact-sum rule missed, using the official per-candidate totals and NOTA.

    A printed grand total whose big cells were unreadable (or misread) no longer equals the running sums, but its other
    cells still equal the official column totals. A real booth cannot have the whole constituency's votes for a
    candidate in one cell, so a row with OFFICIAL_ROW_MATCHES different official figures in its cells is a total row;
    one or two matches are left alone because small totals can equal a booth's cell by chance. Returns the dropped
    (page, serial) list."""
    figures = {v for v in list(official["candidates"]) + [official["nota"]] if v is not None and v >= OFFICIAL_ROW_MIN}
    if len(figures) < OFFICIAL_ROW_MATCHES:
        return []
    kept, dropped = [], []
    for r in res.rows:
        (dropped if len({v for v in r.values if v in figures}) >= OFFICIAL_ROW_MATCHES else kept).append(r)
    if not dropped:
        return []
    res.rows[:] = kept
    gone = [(t.page, t.serial) for t in dropped]
    res.meta["dropped_total_rows"] = list(res.meta.get("dropped_total_rows", [])) + gone
    return gone
PAIR_TOLERANCE = 0.15   # sheet column sums must lie within this share of the official figure to be paired with it


def drop_excess_rows(res, official):
    """Remove a stray row that accounts exactly for what the sheet holds above the official totals.

    A junk row read from a page's foot (a stray line, a signature, part of a total) adds a few votes to several columns,
    so the sheet ends up a little over the official total in each. If one row - or, among the rows the extractor was
    unsure of or that end a page, two - equals that excess in every candidate column and NOTA, removing it makes the
    sheet equal the official totals, and it is not a booth. An excess of fewer than EXCESS_MIN_VOTES votes in
    EXCESS_MIN_COLUMNS columns is too small to tell a stray row from a real small booth and is left alone.
    Returns the dropped (page, serial) list."""
    nc, rows = res.n_cands, res.rows
    b = res.meta.get("layout", "A").startswith("B")
    votes = sorted(list(official["candidates"]) + ([official["nota"]] if b else []))
    if len(votes) != nc or not rows:
        return []
    cols = list(range(nc)) + ([] if b else [nc + 2])
    sums = [sum(r.values[i] or 0 for r in rows) for i in range(nc)]
    excess = {}
    for rank, col in enumerate(sorted(range(nc), key=lambda i: sums[i])):
        if abs(sums[col] - votes[rank]) > PAIR_TOLERANCE * votes[rank] + 5:
            return []                                   # the columns are not close to the official totals at all
        excess[col] = sums[col] - votes[rank]
    if not b:
        excess[nc + 2] = sum(r.values[nc + 2] or 0 for r in rows) - official["nota"]
    want = [excess[c] for c in cols]
    if min(want) < 0 or sum(want) < EXCESS_MIN_VOTES or sum(1 for w in want if w) < EXCESS_MIN_COLUMNS:
        return []

    def vec(r):
        return [r.values[c] or 0 for c in cols]

    single = [i for i, r in enumerate(rows) if vec(r) == want]
    drop = single if len(single) == 1 else []
    if not drop and not single:
        pages = {}
        for i, r in enumerate(rows):
            pages.setdefault(r.page, []).append(i)
        last = {ix[-1] for ix in pages.values()}
        unsure = [i for i, r in enumerate(rows) if r.status != "OK" or i in last]
        pairs = [(i, j) for k, i in enumerate(unsure) for j in unsure[k + 1:]
                 if [a + c for a, c in zip(vec(rows[i]), vec(rows[j]))] == want]
        if len(pairs) == 1:
            drop = list(pairs[0])
    if not drop:
        return []
    gone = [(rows[i].page, rows[i].serial) for i in drop]
    res.rows[:] = [r for i, r in enumerate(rows) if i not in set(drop)]
    res.meta["dropped_excess_rows"] = gone
    return gone


def apply_official_totals(res, official):
    """Use the official per-candidate EVM totals (and NOTA) as the column-total target instead of the printed
    'Total EVM votes' row, which is often misread. official: {"candidates": [votes...], "nota": int}.

    The sheet's candidate columns are paired with the official figures by rank (largest with largest), which is
    only trusted when every pair is close; otherwise nothing changes. Rejected / total / tendered have no official
    figure and are left out of the check. Returns True when the targets were installed."""
    nc = res.n_cands
    b = res.meta.get("layout", "A").startswith("B")      # layout B counts NOTA among the candidate-like columns
    votes = sorted(list(official["candidates"]) + ([official["nota"]] if b else []))
    if len(votes) != nc or not res.rows:
        return False
    sums = [sum(r.values[i] for r in res.rows if r.values[i] is not None) for i in range(nc)]
    target = [None] * (nc + 5)
    for rank, col in enumerate(sorted(range(nc), key=lambda i: sums[i])):
        if abs(sums[col] - votes[rank]) > PAIR_TOLERANCE * votes[rank] + 5:
            return False
        target[col] = votes[rank]
    target[nc] = sum(votes)                      # total valid votes = sum of the candidates (+ NOTA in layout B)
    if not b:
        target[nc + 2] = official["nota"]
    res.totals["TOTAL_EVM"] = RowResult(values=target, status="OK")
    res.meta["totals_source"] = "official"
    return True


MULTI_MAX_ROWS = 32      # uncertain rows considered by multi_fix
MULTI_HALF_MOVES = 4     # corrections tried per half of those rows (so up to 8 rows are corrected at once)


def multi_fix(moves, target, max_rows=MULTI_MAX_ROWS, max_half=MULTI_HALF_MOVES, margin=0.5):
    """Find the set of row corrections, at most one per row, whose column changes add up exactly to `target`.

    moves: [(cost, row_index, delta_tuple, new_values)], target: the deficit (official or printed total minus the
    current column sums). Meet in the middle: all selections of up to `max_half` corrections are listed for each half of
    the uncertain rows, and the halves are matched on their summed deltas, so combinations of up to 2 * max_half rows
    are tested without trying them one by one. The exact vector match over every checked column makes a coincidence
    very unlikely; still, the cheapest solution must beat the next one by `margin`, else nothing is changed.
    Returns the list of moves, "ambiguous", or None."""
    by_row = {}
    for m in moves:
        by_row.setdefault(m[1], []).append(m)
    for ms in by_row.values():
        ms.sort(key=lambda m: m[0])
        del ms[4:]
    rows = sorted(sorted(by_row, key=lambda i: by_row[i][0][0])[:max_rows])
    if len(rows) < 2:
        return None
    zero = (0,) * len(target)

    def enum(group):
        out = {}

        def rec(k, count, vec, cost, sel):
            if k == len(group):
                lst = out.setdefault(vec, [])
                lst.append((cost, sel))
                if len(lst) > 2:
                    lst.sort(key=lambda t: t[0])
                    del lst[2:]
                return
            rec(k + 1, count, vec, cost, sel)
            if count < max_half:
                for m in by_row[group[k]]:
                    rec(k + 1, count + 1, tuple(a + b for a, b in zip(vec, m[2])), cost + m[0], sel + (m,))

        rec(0, 0, zero, 0.0, ())
        return out

    half = len(rows) // 2
    left, right = enum(rows[:half]), enum(rows[half:])
    found = []
    for vec, entries in right.items():
        need = tuple(t - s for t, s in zip(target, vec))
        for cost_l, sel_l in left.get(need, ()):
            for cost_r, sel_r in entries:
                if sel_l or sel_r:
                    found.append((cost_l + cost_r, list(sel_l) + list(sel_r)))
    if not found:
        return None
    found.sort(key=lambda t: t[0])
    if len(found) > 1 and found[1][0] - found[0][0] < margin:
        return "ambiguous"
    return found[0][1]


def _reconcile_with_totals(res):
    """Settle uncertain rows against the column totals (_reconcile_rows), then fill cells nobody could read when the
    column total leaves exactly one possible value (_fill_single_unknowns)."""
    _reconcile_rows(res)
    _fill_single_unknowns(res)


def _fill_single_unknowns(res):
    """A column with exactly one unreadable cell: the known column total minus the other cells is that cell's value.
    Accepted only when it is a possible vote count and the row's own two identities then hold; otherwise the cell
    stays blank for review. Rows filled this way become AUTO_CORRECTED."""
    printed = res.totals.get("TOTAL_EVM")
    if printed is None:
        return
    nc = res.n_cands
    for j in range(nc + 4):
        target = printed.values[j]
        unknown = [r for r in res.rows if r.values[j] is None]
        if target is None or len(unknown) != 1:
            continue
        row = unknown[0]
        fill = target - sum(r.values[j] for r in res.rows if r.values[j] is not None)
        if not 0 <= fill <= MAX_CELL_VOTES:
            continue
        row.values[j] = fill
        v = row.values
        if None in v[: nc + 4] or sum(v[:nc]) != v[nc] or v[nc] + v[nc + 1] + v[nc + 2] != v[nc + 3]:
            row.values[j] = None                 # the row does not add up with that value: do not guess
            continue
        row.status = "AUTO_CORRECTED"
        row.notes = [n for n in row.notes if not n.startswith("ambiguous")] + [
            "an unreadable cell was filled from the column total (the only value that makes it add up)"]


def _reconcile_rows(res):
    """Use the printed 'Total EVM votes' row to settle rows whose reading is
    uncertain: find the cheapest one- or two-row change (chosen only among the
    readings the OCR actually produced) that makes every column sum equal the
    printed total. A change is applied only when it is the unique best one."""
    printed = res.totals.get("TOTAL_EVM")
    if printed is None:
        return
    nc = res.n_cands
    cols = [i for i in range(nc + 4) if printed.values[i] is not None]
    if not cols or any(r.values[i] is None for r in res.rows for i in range(nc + 4)):
        pass

    def deficit():
        return [printed.values[i] - sum(r.values[i] for r in res.rows if r.values[i] is not None) for i in cols]

    def settle(row, why):
        row.status = "AUTO_CORRECTED"
        row.alternatives = []
        row.notes = [n for n in row.notes if not n.startswith("ambiguous")] + [why]

    D = deficit()
    if not any(D):
        # Totals already balance: an ambiguous row is confirmed if every rival
        # reading would have broken the balance.
        for r in res.rows:
            if r.status == "REVIEW" and r.alternatives and None not in r.values[: nc + 4]:
                deltas = [tuple(v[i] - r.values[i] for i in cols) for _, v in r.alternatives
                          if None not in v[: nc + 4]]
                if deltas and all(any(d) for d in deltas):
                    settle(r, "several readings were plausible; chosen because it is the only one consistent with the printed column totals")
        return

    def moves_from(rows_alts):
        out = []
        for idx, alts in rows_alts:
            cur = res.rows[idx].values
            if any(cur[i] is None for i in cols):
                continue
            for gap, v in alts:
                if any(v[i] is None for i in cols):
                    continue
                delta = tuple(v[i] - cur[i] for i in cols)
                if any(delta):
                    out.append((gap, idx, delta, v))
        return out

    def best_fix(moves, target):
        by_delta = {}
        for m in moves:
            by_delta.setdefault(m[2], []).append(m)
        cands = []
        for m in moves:
            if m[2] == target:
                cands.append((m[0], [m]))
            need = tuple(t - d for t, d in zip(target, m[2]))
            for m2 in by_delta.get(need, []):
                if m2[1] > m[1]:
                    cands.append((m[0] + m2[0], [m, m2]))
        if not cands:
            return None
        cands.sort(key=lambda c: c[0])
        if len(cands) > 1 and cands[1][0] - cands[0][0] < 0.5:
            return "ambiguous"
        return cands[0][1]

    def apply(fix, why):
        for gap, idx, delta, v in fix:
            row = res.rows[idx]
            row.values = list(v)
            settle(row, why)

    # A: alternatives the row solver already kept (uncertain rows)
    stored = [(i, r.alternatives) for i, r in enumerate(res.rows) if r.alternatives]
    fix = best_fix(moves_from(stored), tuple(D))
    if isinstance(fix, list):
        apply(fix, "several readings were plausible; chosen because only this one makes the printed column totals add up")
        return
    if fix == "ambiguous":
        return
    # A2: several uncertain rows corrected together (up to 2 * MULTI_HALF_MOVES), matched exactly against the deficit
    fix = multi_fix(moves_from(stored), tuple(D))
    if isinstance(fix, list):
        apply(fix, "several readings were plausible; chosen because only this combination makes the column totals add up")
        return
    if fix == "ambiguous":
        return
    # B: deeper search over every row (a compensating slip can hide in a row that passed the checks)
    deep = []
    for i, r in enumerate(res.rows):
        if r.cells is None:
            continue
        sols = enumerate_solutions(r.cells, nc, max_extra=1)
        if sols:
            base = next((c for c, v in sols if v == r.values), 0.0)
            deep.append((i, [(c - base, v) for c, v in sols if c - base < ALT_GAP]))
    fix = best_fix(moves_from(deep), tuple(D))
    if isinstance(fix, list):
        apply(fix, "adjusted to a nearby reading because only this makes the printed column totals add up")


def _file_checks(res):
    _reconcile_with_totals(res)
    _column_checks(res)


def _column_checks(res):
    """Compare column sums over all polling-station rows with the printed
    'Total EVM votes' row, and the electors figure with the title block."""
    nc = res.n_cands
    labels = list(res.names_en or res.names_native) + ["Total valid votes", "Rejected votes", "NOTA", "Total", "Tendered votes"]
    printed = res.totals.get("TOTAL_EVM")
    if printed is None:
        res.checks.append(("Printed EVM total row", "not found", "", False))
        return
    for i in range(nc + 5):
        s = sum(r.values[i] for r in res.rows if r.values[i] is not None)
        pv = printed.values[i]
        if pv is None and res.meta.get("totals_source") == "official":
            continue                              # no official figure for this column
        res.checks.append((labels[i] if i < len(labels) else f"col {i}", pv, s, pv == s))
    bad = [c[0] for c in res.checks if not c[3]]
    res.meta["column_total_mismatches"] = bad
    if res.meta.get("totals_source") != "official":    # its column indices assume every column was checked
        _localize_mismatch(res)


def _localize_mismatch(res):
    """The sheet's printed column totals disagree with the sum of its own rows.
    Never edit the source figures; point the reviewer at the likeliest rows."""
    nc = res.n_cands
    diff = {i: c[1] - c[2] for i, c in enumerate(res.checks[: nc + 5]) if isinstance(c[1], int) and c[1] != c[2]}
    if not diff:
        return
    names = [c[0] for c in res.checks]
    pairs = [(i, j) for i in diff for j in diff if i < j and diff[i] == -diff[j]]
    used = set()
    for i, j in pairs:
        d = diff[i]   # printed - computed for column i (computed_j is too low by d... )
        hits = [r for r in res.rows if r.values[i] is not None and r.values[j] is not None
                and r.values[j] - r.values[i] == d]
        for r in hits:
            r.status = "REVIEW"
            r.notes.append(
                f"printed column totals suggest the values of '{names[i]}' and '{names[j]}' "
                f"are swapped in this row (totals differ by {abs(d)}); source figures kept as printed"
            )
        res.meta.setdefault("mismatch_suspects", []).append(
            (names[i], names[j], abs(d), [(r.page, r.serial) for r in hits])
        )
        used |= {i, j}
    for i, d in diff.items():
        if i not in used:
            res.meta.setdefault("mismatch_suspects", []).append((names[i], None, d, []))
