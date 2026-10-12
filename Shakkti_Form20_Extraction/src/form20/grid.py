"""Stage 3: find the table grid (row lines / column lines) on a page.

Scanned lines are thin and broken, so detection is deliberately tolerant:
  * row lines  - found per page; missing lines inside the regular run are
                 re-inserted at the pitch;
  * col lines  - candidates found per page, then a column *template* is built
                 from all pages of a file (voting) and snapped to each page.
"""
from dataclasses import dataclass, field

import cv2
import numpy as np

from .imaging import binarize

ROW_LINE_FRAC = 0.30     # a row line must cover this fraction of the table width
COL_LINE_FRAC = 0.20     # a column line must cover this fraction of the data height
ROW_TOL = 0.28           # spacing tolerance (fraction of pitch) inside the regular run
MIN_RUN = 4


@dataclass
class PageLines:
    left: int
    right: int
    data_edges: list                     # y of lines bounding the regular data rows
    total_edges: list = field(default_factory=list)   # y of lines of the taller rows below
    header_top: int = 0
    col_candidates: list = field(default_factory=list)
    pitch: float = 0.0
    row_lines: list = field(default_factory=list)   # every detected horizontal line (y)


@dataclass
class Grid:
    col_edges: list
    data_edges: list
    total_edges: list
    header_top: int
    left: int
    right: int
    pitch: float
    row_lines: list = field(default_factory=list)

    @property
    def n_cols(self):
        return len(self.col_edges) - 1

    @property
    def n_data_rows(self):
        return len(self.data_edges) - 1


def _cluster(indices, gap=4):
    groups, cur = [], []
    for i in indices:
        if cur and i - cur[-1] > gap:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)
    return [float(np.mean(g)) for g in groups]


def _pitch(spacings):
    """Most common spacing (robust to header / totals rows of other heights)."""
    sp = np.asarray(spacings, float)
    best, best_n = float(np.median(sp)), -1
    for s in sp:
        n = int(np.sum(np.abs(sp - s) <= 0.08 * s))
        if n > best_n or (n == best_n and s < best):
            best, best_n = float(s), n
    members = sp[np.abs(sp - best) <= 0.08 * best]
    return float(np.mean(members))


def _regular_run(lines, min_run=MIN_RUN, pitch=None):
    """Longest run of lines at ~pitch spacing (a spacing of ~2*pitch means one
    line was missed and is re-inserted). Returns (lines_in_run, pitch, end_idx).
    min_run / pitch let a caller who already knows the file's row pitch accept a short run (the last page of a
    sheet often holds only a few booths above the totals). Among runs of equal length the last one is taken then:
    the header's own lines can also be one pitch apart, and the booths are the rows nearest the totals."""
    if len(lines) < min_run + 1:
        return None
    sp = np.diff(lines)
    pitch = pitch or _pitch(sp)
    kinds = []
    for s in sp:
        m = int(round(s / pitch))
        kinds.append(m if m in (1, 2) and abs(s - m * pitch) <= ROW_TOL * pitch else 0)
    best, start = (0, 0), None
    for i, k in enumerate(kinds + [0]):
        if k and start is None:
            start = i
        elif not k and start is not None:
            if i - start > best[1] - best[0] or (min_run < MIN_RUN and i - start == best[1] - best[0]):
                best = (start, i)
            start = None
    if best[1] - best[0] < min_run:
        return None
    out = [lines[best[0]]]
    for i in range(best[0], best[1]):
        if kinds[i] == 2:
            out.append((lines[i] + lines[i + 1]) / 2)
        out.append(lines[i + 1])
    return out, pitch, best[1]


def detect_lines(gray, min_run=MIN_RUN, pitch_hint=None):
    bw = binarize(gray)
    h, w = bw.shape
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (w // 40, 1)))
    hor = cv2.morphologyEx(hor, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (w // 25, 1)))
    ys_px, xs_px = np.nonzero(hor)
    if len(xs_px) == 0:
        return None
    left, right = int(np.percentile(xs_px, 0.5)), int(np.percentile(xs_px, 99.5))
    width = right - left
    rowsum = (hor[:, left:right] > 0).sum(axis=1)
    row_lines = _cluster(np.nonzero(rowsum > ROW_LINE_FRAC * width)[0], gap=5)
    run = _regular_run(row_lines, min_run, pitch_hint)
    if run is None:
        return None
    data_lines, pitch, end_idx = run

    below = [y for y in row_lines[end_idx + 1 :] if y > data_lines[-1] + 0.5 * pitch]
    total_lines = [data_lines[-1]] + below if below else []

    y0, y1 = int(data_lines[0]), int(data_lines[-1])
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25)))
    ver = cv2.morphologyEx(ver, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(pitch * 2))))
    colsum = (ver[y0:y1, :] > 0).sum(axis=0)
    cols = _cluster(np.nonzero(colsum > COL_LINE_FRAC * (y1 - y0))[0], gap=4)
    cols = [c for c in cols if left - 20 <= c <= right + 20]

    return PageLines(
        left=left,
        right=right,
        data_edges=[int(round(y)) for y in data_lines],
        total_edges=[int(round(y)) for y in total_lines],
        header_top=int(round(row_lines[0])),
        col_candidates=cols,
        pitch=pitch,
        row_lines=[int(round(y)) for y in row_lines],
    )


def build_col_template(pages, tol=0.004, min_frac=0.6):
    """Pool column-line candidates (as fractions of table width) over all pages
    of a file; keep positions that occur on at least min_frac of the pages."""
    us = []
    for pl in pages:
        if pl is None:
            continue
        width = pl.right - pl.left
        us += [(c - pl.left) / width for c in pl.col_candidates]
    n_pages = sum(1 for p in pages if p is not None)
    us.sort()
    clusters, cur = [], []
    for u in us:
        if cur and u - cur[-1] > tol:
            clusters.append(cur)
            cur = []
        cur.append(u)
    if cur:
        clusters.append(cur)
    return [float(np.mean(c)) for c in clusters if len(c) >= min_frac * n_pages]


SHIFT_REACH = 0.03       # a page's registration error is looked for up to this fraction of the table width


def _line_fit(x, y):
    """Least-squares line y = a * x + b in closed form. (np.polyfit goes through MKL's LAPACK, which aborts the process
    with an OpenMP duplicate-runtime error once torch - the neural digit reader - is loaded in the same process.)"""
    mx, my = x.mean(), y.mean()
    var = ((x - mx) ** 2).sum()
    a = ((x - mx) * (y - my)).sum() / var if var > 0 else 1.0
    return a, my - a * mx


def page_registration(pl, template, snap_tol=0.006):
    """Linear map (scale a, offset b) from the template placed on this page to the column rules detected on it.

    The table's left/right extent is estimated from its horizontal rules; on a page with few rules (a short last page)
    or a ragged edge it can be off by a digit width, which moves the columns by different amounts - more than the
    per-edge snapping can correct - and the first candidate's crop then picks up the neighbour's last digit. A least-squares
    fit of each template edge to its nearest detected rule (re-matched after every fit, within SHIFT_REACH) estimates the
    map. It is used only when most edges find a rule and it moves some edge by more than snapping would anyway;
    otherwise (a=1, b=0): a page that is already registered is left alone."""
    width = pl.right - pl.left
    cands = np.asarray(pl.col_candidates, float)
    if len(cands) < 4 or width <= 0:
        return 1.0, 0.0
    x = pl.left + np.asarray(template, float) * width
    a, b = 1.0, 0.0
    for _ in range(3):
        pred = a * x + b
        c = cands[np.abs(cands[None, :] - pred[:, None]).argmin(1)]
        ok = np.abs(c - pred) <= SHIFT_REACH * width
        if ok.sum() < max(4, 0.6 * len(x)):
            return 1.0, 0.0
        a, b = _line_fit(x[ok], c[ok])
    pred = a * x + b
    resid = np.abs(cands[np.abs(cands[None, :] - pred[:, None]).argmin(1)] - pred)
    if np.median(resid) > snap_tol * width or not 0.9 < a < 1.1:
        return 1.0, 0.0                                   # the fit is no better than the raw placement: ignore it
    if np.max(np.abs(pred - x)) <= snap_tol * width:
        return 1.0, 0.0
    return float(a), float(b)


RULE_REACH = 0.05        # the column edges may move this share of the table width to land on the vertical rules
RULE_SCALES = tuple(np.arange(0.90, 1.10001, 0.0025))    # and the table may be this much narrower or wider
RULE_GAIN = 1.3          # the best placement must show this many times the rule evidence of the template as placed ...
RULE_MIN_MORE = 3        # ... and at least this many more column edges on a rule


def rule_profile(gray, y0, y1, pitch):
    """Darkness of long vertical lines per x over the rows y0..y1 (anything shorter than 2.5 row pitches is ignored)."""
    y0, y1 = max(0, int(y0)), min(gray.shape[0], int(y1))
    if y1 - y0 < 3 * pitch:
        return None
    bw = binarize(gray[y0:y1])
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, int(2.5 * pitch)))))
    prof = (ver > 0).sum(axis=0).astype(float)
    return np.convolve(prof, np.ones(3) / 3, mode="same")


RULE_LENGTH = 0.8        # only vertical ink at least this many row pitches long counts as a rule: that is longer than any digit
RULE_COVER = 0.7         # a column strip is a rule in a row when such ink covers this share of the row's height
RULE_STRIP = 1           # (a strip is 2 * this + 1 px wide, so a tilted rule still fills it)
RULE_PEAK = 5            # one rule is counted once within this many px
MIN_RULES = 4            # a page's typical row shows at least this many rules for rows to be judged at all
UNRULED_SHARE = 0.2      # a row with fewer rules than this share of the page's typical row lies outside the table


def unruled_tail(gray, grid):
    """How many data rows at the bottom of the page lie outside the table's vertical rules.

    The row lines the page shows can include a page footer or border one pitch below the last booth (a gap of two
    pitches is read as one missed line, and the line after it joins the run); the table's own vertical rules end at the
    last booth, and the strip below holds only stray marks, which the reader still turns into digits. Each row's rules
    are counted in the page's long vertical ink only (an opening that drops horizontal lines, digits and text), so no
    column positions are needed and a page whose grid sits off its rules is judged like any other. A row is outside the
    table when it shows hardly any of the rules a typical row of the page shows. Only trailing rows are judged, and
    only on a page whose rows plainly show rules, so a page whose rules are faint or missing is left alone."""
    edges = grid.data_edges
    if len(edges) < 5:
        return 0
    vertical = cv2.morphologyEx((binarize(gray) > 0).astype(np.uint8), cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, int(RULE_LENGTH * grid.pitch))))) > 0
    counts = []
    for y0, y1 in zip(edges[:-1], edges[1:]):
        if y1 - y0 < 8 or y0 < 0 or y1 > vertical.shape[0]:
            counts.append(None)                                # too thin to tell: not judged
            continue
        cover = np.convolve(vertical[y0 + 2:y1 - 2].mean(axis=0), np.ones(2 * RULE_STRIP + 1), mode="same")
        hits = np.nonzero(cover >= RULE_COVER)[0]
        counts.append(int(1 + np.count_nonzero(np.diff(hits) > RULE_PEAK)) if len(hits) else 0)
    known = [c for c in counts if c is not None]
    typical = float(np.median(known)) if known else 0.0
    if typical < MIN_RULES:
        return 0
    n = 0
    while n < len(counts) and counts[-1 - n] is not None and counts[-1 - n] <= UNRULED_SHARE * typical:
        n += 1
    return n


def align_to_rules(gray, grid):
    """Move the column edges of a grid onto the table's vertical rules when the template, as placed, misses them.

    A page whose table is narrower or wider than the others (a short last page scanned on its own) or whose left and
    right extent was estimated badly puts the column edges off, and the cells then cut the digits. The edges are
    scaled and shifted to the placement where the most of them sit on a long vertical rule. An edge counts by how
    strongly the rule under it shows, up to a typical rule. The move is made only when it puts clearly more edges on
    rules than the template as placed (RULE_GAIN, RULE_MIN_MORE), so a page that is already right - or has no vertical
    rules - keeps its edges."""
    xs = np.asarray(grid.col_edges, float)
    top = grid.data_edges[0] - 4 * grid.pitch
    bottom = (grid.total_edges[-1] if grid.total_edges else grid.data_edges[-1]) + grid.pitch
    prof = rule_profile(gray, top, bottom, grid.pitch)
    if prof is None or len(xs) < 5 or prof.max() <= 0:
        return grid
    window = np.lib.stride_tricks.sliding_window_view(np.pad(prof, 2), 5).max(axis=1)    # strongest rule within 2 px
    strong = 0.5 * prof.max()

    def evidence(edges):
        idx = np.rint(edges).astype(int)
        ok = (idx >= 0) & (idx < len(window))
        return float(np.minimum(window[idx[ok]] / strong, 1.0).sum())

    base = evidence(xs)
    width, mid = xs[-1] - xs[0], xs.mean()
    reach = int(RULE_REACH * width)
    best, best_score = (1.0, 0.0), base
    for a in RULE_SCALES:
        scaled = a * (xs - mid) + mid
        for b in range(-reach, reach + 1, 2):
            score = evidence(scaled + b)
            if score > best_score:
                best, best_score = (float(a), float(b)), score
    if best_score >= RULE_GAIN * max(base, 1.0) and best_score - base >= RULE_MIN_MORE:
        a, b = best
        xs = a * (xs - mid) + mid + b
    peaks = [i for i in range(len(prof)) if prof[i] >= strong and prof[i] == window[i]]
    grid.col_edges = _snap_edges(xs, peaks, int(RULE_SNAP * width))
    return grid


RULE_SNAP = 0.015        # an edge may move this share of the table width onto the strongest rule near it
RULE_SNAP_MIN = 3        # moves smaller than this many pixels are not made (a page already on its rules stays as it is)


def _snap_edges(xs, peaks, reach):
    """Each column edge onto the nearest strong vertical rule within `reach`. A curved or uneven page is not a straight
    shift of the template: the left columns can sit on their rules while the right ones are 20 px off. Edges with no
    rule near them keep their place; two edges never take the same rule, and the order of the edges is kept."""
    out = [int(round(v)) for v in xs]
    if not len(peaks):
        return out
    peaks = np.asarray(peaks, float)
    taken = set()
    for i, x in sorted(enumerate(xs), key=lambda t: min(abs(peaks - t[1]))):      # the closest matches first
        j = int(np.argmin(np.abs(peaks - x)))
        if abs(peaks[j] - x) > reach or abs(peaks[j] - x) < RULE_SNAP_MIN or j in taken:
            continue
        lo = out[i - 1] if i else -1e9
        hi = out[i + 1] if i + 1 < len(out) else 1e9
        if lo + 10 < peaks[j] < hi - 10:
            out[i] = int(round(peaks[j]))
            taken.add(j)
    return out


def apply_template(pl, template, snap_tol=0.006, register=True):
    """Place the template on this page, correcting its registration and snapping to detected lines when close.
    register=False (and snap_tol=0) lays it on the table's extent as it is: for a template found from the digits, where
    the page's vertical lines say nothing about the columns."""
    width = pl.right - pl.left
    scale, offset = page_registration(pl, template, snap_tol) if register else (1.0, 0.0)
    edges = []
    for u in template:
        x = scale * (pl.left + u * width) + offset
        near = [c for c in pl.col_candidates if abs(c - x) <= snap_tol * width]
        edges.append(int(round(min(near, key=lambda c: abs(c - x)) if near else x)))
    return Grid(
        col_edges=edges,
        data_edges=pl.data_edges,
        total_edges=pl.total_edges,
        header_top=pl.header_top,
        left=pl.left,
        right=pl.right,
        pitch=pl.pitch,
        row_lines=pl.row_lines,
    )
