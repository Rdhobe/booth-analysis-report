"""Recover rows whose ruling lines the line detector missed.

On a skewed, shadowed or photocopied page the row lines can be too faint or doubled for the detector, which then keeps
only the stretch of the table it is sure about: a page that should hold 24 booths yields 12, and their votes are missing
from every column. Two clues say where the rows went: a page with fewer rows than its neighbours, and a jump in the
serial numbers between pages. The missing rows are then looked for by extending the row grid at the row pitch, above
and below the detected rows, keeping only the bands that really hold digits.
"""
from collections import Counter

import numpy as np

from .ocr import remove_lines

BAND_FILL = 0.3      # share of the numeric columns that must hold ink for a band to be a data row
CELL_INK = 0.004     # dark share of a cell's pixels that counts as ink
SNAP = 0.3           # an extended row edge snaps to a detected ruling line within this many pitches


def typical_rows(counts):
    """Rows on a full page: the commonest count over the middle pages (first and last pages differ), None if unclear."""
    mid = [c for c in counts[1:-1] if c]
    return Counter(mid).most_common(1)[0][0] if len(mid) >= 3 else None


def plan_missing_rows(pages_rows):
    """Which pages lost rows, and where. pages_rows: per page, row dicts with their assigned "serial".

    Returns ({page: (rows missing above, rows missing below)}, {page: rows missing at an unknown end}). A jump in
    the serials at a page boundary says how many rows are missing there; they are given to the page above or below
    it, whichever is short of rows. A short page that no jump explains has its rows missing at an unknown end."""
    counts = [len(r) for r in pages_rows]
    full = typical_rows(counts)
    if full is None:
        return {}, {}
    deficit = {p: full - counts[p] for p in range(1, len(counts) - 1) if counts[p] and counts[p] < full}
    plan = {}

    def give(p, side, k):
        got = plan.setdefault(p, [0, 0])
        got[side] += k
        deficit[p] -= k

    for p in range(len(pages_rows) - 1):
        a, b = pages_rows[p], pages_rows[p + 1]
        if not a or not b:
            continue
        gap = b[0]["serial"] - a[-1]["serial"] - 1
        if gap > 0 and deficit.get(p, 0) > 0:
            k = min(gap, deficit[p])
            give(p, 1, k)
            gap -= k
        if gap > 0 and deficit.get(p + 1, 0) > 0:
            give(p + 1, 0, min(gap, deficit[p + 1]))
    unknown = {p: d for p, d in deficit.items() if d > 0}
    return {p: tuple(v) for p, v in plan.items()}, unknown


def band_fill(clean, grid, id_cols, y0, y1):
    """Share of the numeric columns that hold ink in the band y0..y1 (ruling lines already painted out)."""
    h = clean.shape[0]
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    if y1 - y0 < 8:
        return 0.0
    inset = max(2, int(0.09 * (y1 - y0)))
    hits = total = 0
    for c in range(id_cols, len(grid.col_edges) - 1):
        cell = clean[y0 + inset:y1 - inset, grid.col_edges[c] + 3:grid.col_edges[c + 1] - 3]
        if cell.size:
            total += 1
            hits += (cell < 128).mean() >= CELL_INK
    return hits / total if total else 0.0


def _snap(y, lines, tol):
    near = [ln for ln in lines if abs(ln - y) <= tol]
    return min(near, key=lambda ln: abs(ln - y)) if near else y


def ink_profile(clean, grid, id_cols, pitch):
    """Dark pixels per y over the numeric columns, smoothed: one peak per row of digits."""
    x0, x1 = grid.col_edges[id_cols], grid.col_edges[-1]
    raw = (clean[:, x0:x1] < 128).sum(axis=1).astype(float)
    k = max(3, int(pitch / 8))
    return np.convolve(raw, np.ones(k) / k, mode="same")


def reference_peak(profile, edges):
    """Typical height of the ink peak of a row, from the rows that were detected."""
    return float(np.median([profile[a:b].max() for a, b in zip(edges, edges[1:]) if b > a])) or 1.0


def follow_rows(anchor, pitch, k, direction, lines, profile, ref_peak):
    """Edges of k rows beyond `anchor` (direction -1 above, +1 below), nearest first. Each row's centre is moved to the
    nearest ink peak within a third of a pitch of where the pitch puts it, and the next prediction continues from
    there, so the grid follows a skewed or curved page. The edge between two rows lies half way between their centres
    (snapped to a detected ruling line when one is close)."""
    centres, c = [], anchor + direction * pitch / 2
    for _ in range(k):
        lo, hi = max(0, int(c - pitch / 3)), min(len(profile), int(c + pitch / 3) + 1)
        if hi > lo:
            peak = lo + int(np.argmax(profile[lo:hi]))
            if profile[peak] >= 0.25 * ref_peak:
                c = float(peak)
        centres.append(c)
        c += direction * pitch
    out = []
    for i, ci in enumerate(centres):
        nxt = centres[i + 1] if i + 1 < len(centres) else ci + direction * pitch
        out.append(int(round(_snap((ci + nxt) / 2, lines, SNAP * pitch))))
    return out


def holding_rows(clean, grid, id_cols, anchor, new_edges, direction):
    """How many of the new bands, nearest first, hold a data row."""
    n, prev = 0, anchor
    for y in new_edges:
        y0, y1 = (y, prev) if direction < 0 else (prev, y)
        if band_fill(clean, grid, id_cols, y0, y1) < BAND_FILL:
            break
        n, prev = n + 1, y
    return n


TAIL_TOLERANCE = 5     # votes a recovered row may overshoot a column's remaining shortfall by (a misread digit or two)


def shortfall(rows_values, official_votes, nota=None):
    """What the rows still lack against the official totals, per column: {column: votes}. rows_values: value lists
    (candidate columns first); official_votes: the official candidate totals; the sheet's columns are paired with them by
    rank. None when the pairing is not close (the columns are not the official ones at all), so nothing is guessed."""
    nc = len(official_votes)
    sums = [sum((v[i] or 0) for v in rows_values) for i in range(nc)]
    out = {}
    for rank, col in enumerate(sorted(range(nc), key=lambda i: sums[i])):
        want = sorted(official_votes)[rank]
        if abs(sums[col] - want) > 0.15 * want + 5:
            return None
        out[col] = want - sums[col]
    return out


def fits_shortfall(values, missing, tolerance=TAIL_TOLERANCE):
    """True when a row's votes do not overshoot what is still missing in any column (by more than the tolerance)."""
    return all((values[c] or 0) <= missing[c] + tolerance for c in missing)


def rescue_edges(gray, grid, lines, id_cols, up, down, unknown):
    """Row edges to add above and below the detected rows, as (edges above in page order, edges below), bands that
    hold no digits left out. `up` / `down` rows are wanted at a known end, `unknown` at whichever end has them (below
    only: the top of a table is bounded by its header, which also holds ink, so a shortfall with no serial evidence is
    never looked for above). The number of rows a page lost to a serial jump is reliable; where they were is not (a jump
    says only that they are on one side), so what a side cannot supply is taken from the other."""
    edges = grid.data_edges
    pitch = float(np.median(np.diff(edges)))
    clean = remove_lines(gray, pitch)
    profile = ink_profile(clean, grid, id_cols, pitch)
    ref = reference_peak(profile, edges)
    k = up + down + unknown
    above = follow_rows(edges[0], pitch, k, -1, lines, profile, ref)
    below = follow_rows(edges[-1], pitch, k, +1, lines, profile, ref)
    n_above = holding_rows(clean, grid, id_cols, edges[0], above, -1)
    n_below = holding_rows(clean, grid, id_cols, edges[-1], below, +1)
    u, d = min(up, n_above), min(down, n_below)
    left = up + down - u - d                                 # planned rows that their own side could not supply
    spare_d = min(unknown, n_below - d)                      # rows with no serial evidence: below only
    more_d = min(left, n_below - d - spare_d)                # the planned rest: below first, then above
    more_u = min(left - more_d, n_above - u)
    u, d = u + more_u, d + spare_d + more_d
    return above[:u][::-1], below[:d]
