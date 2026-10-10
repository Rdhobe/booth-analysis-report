"""Orchestration: one Form 20 PDF -> FileResult (rows, totals, checks, flags)."""
import csv
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import header
from .grid import apply_template, build_col_template, detect_lines
from .imaging import load_page, page_count
from .ocr import read_cells
from .validate import ALT_GAP, enumerate_solutions, solve_row

TOTAL_LABELS = ("TOTAL_EVM", "TOTAL_POSTAL", "TOTAL_POLLED")
DEFAULT_CANDIDATES = Path(__file__).resolve().parents[2] / "config" / "candidates.csv"


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
                rows[0]["notes"].append(f"serial discontinuity (expected {expected}, page starts at {alt})")
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


def process_pdf(pdf_path, candidates_csv=DEFAULT_CANDIDATES, progress=print, name_pages=3):
    t0 = time.time()
    pdf_path = str(pdf_path)
    stem = Path(pdf_path).name
    n = page_count(pdf_path)

    # ---- pass 1: table lines on every page -> column template
    progress(f"[{stem}] pass 1/2: locating tables on {n} pages")
    lines, first_gray = [], None
    for p in range(n):
        g, _ = load_page(pdf_path, p)
        lines.append(detect_lines(g))
        if p == 0:
            first_gray = g
    template = build_col_template(lines)
    n_cols = len(template) - 1

    # ---- title block / language / layout
    grid0 = apply_template(next(pl for pl in lines if pl), template)
    first_pl = lines[0] or next(pl for pl in lines if pl)
    title = header.title_text(first_gray, apply_template(first_pl, template))
    hindi = header.is_hindi(title)
    meta = header.parse_title(title, hindi)
    id_cols = 1 if hindi else 2
    n_cands = n_cols - id_cols - 5
    progress(f"[{stem}] language={'Hindi' if hindi else 'English'} columns={n_cols} candidates={n_cands} meta={meta}")

    # ---- pass 2: read every page
    pages_rows, all_name_reads, totals_rows, page_errors, dropped = [], [], [], [], []
    alnum = () if hindi else (1,)
    for p in range(n):
        pl = lines[p]
        if pl is None:
            page_errors.append((p + 1, "table not found"))
            pages_rows.append([])
            continue
        g, _ = load_page(pdf_path, p)
        grid = apply_template(pl, template)
        tab = read_cells(g, grid, grid.data_edges, alnum_cols=alnum)
        rows = []
        for r, row in enumerate(tab):
            if hindi and _is_index_row(row, n_cols):
                continue
            numeric = _num_cells(row, id_cols)
            if sum(1 for c in numeric if c.text) < 0.4 * len(numeric):
                dropped.append((p + 1, r + 1))   # not a data row (stray line / border / footer)
                continue
            res = solve_row(numeric, n_cands)
            serial_txt = row[0].reads.get("A", "")
            ps_txt = row[1].reads.get("A", "") if id_cols == 2 else ""
            conf = min([c.conf for c in _num_cells(row, id_cols) if c.text] or [0.0])
            rows.append(
                {
                    "page": p + 1,
                    "row_in_page": len(rows) + 1,
                    "serial_read": int(serial_txt) if serial_txt.isdigit() else None,
                    "ps_read": ps_txt,
                    "res": res,
                    "cells": numeric,
                    "box": (p, grid.left, grid.data_edges[r], grid.right, grid.data_edges[r + 1]),
                    "notes": [],
                    "conf": conf,
                }
            )
        pages_rows.append(rows)
        if pl.total_edges and len(pl.total_edges) >= 2:
            ttab = read_cells(g, grid, pl.total_edges, alnum_cols=alnum)
            for k, row in enumerate(ttab[:3]):
                totals_rows.append((TOTAL_LABELS[k], solve_row(_num_cells(row, id_cols), n_cands)))
        if p < name_pages:
            all_name_reads.append(header.read_candidate_names(g, grid, id_cols, n_cands, hindi))
        progress(f"[{stem}] page {p + 1}/{n}: {len(rows)} rows")

    # ---- ids
    _assign_serials(pages_rows)
    flat = [r for rows in pages_rows for r in rows]
    ps_agree, ps_total = _assign_ps(flat, hindi)

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
            )
        )
    for label, rr in totals_rows:
        res.totals[label] = rr

    _file_checks(res)
    res.meta['ps_read_agreement'] = (ps_agree, ps_total)
    res.meta['dropped_non_data_rows'] = dropped
    res.seconds = time.time() - t0
    return res


def _reconcile_with_totals(res):
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
    """Compare column sums over all polling-station rows with the printed
    'Total EVM votes' row, and the electors figure with the title block."""
    _reconcile_with_totals(res)
    nc = res.n_cands
    labels = list(res.names_en or res.names_native) + ["Total valid votes", "Rejected votes", "NOTA", "Total", "Tendered votes"]
    printed = res.totals.get("TOTAL_EVM")
    if printed is None:
        res.checks.append(("Printed EVM total row", "not found", "", False))
        return
    for i in range(nc + 5):
        s = sum(r.values[i] for r in res.rows if r.values[i] is not None)
        pv = printed.values[i]
        res.checks.append((labels[i] if i < len(labels) else f"col {i}", pv, s, pv == s))
    bad = [c[0] for c in res.checks if not c[3]]
    res.meta["column_total_mismatches"] = bad
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
