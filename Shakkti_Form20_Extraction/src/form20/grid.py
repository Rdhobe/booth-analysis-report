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


def _regular_run(lines):
    """Longest run of lines at ~pitch spacing (a spacing of ~2*pitch means one
    line was missed and is re-inserted). Returns (lines_in_run, pitch, end_idx)."""
    if len(lines) < MIN_RUN + 1:
        return None
    sp = np.diff(lines)
    pitch = _pitch(sp)
    kinds = []
    for s in sp:
        m = int(round(s / pitch))
        kinds.append(m if m in (1, 2) and abs(s - m * pitch) <= ROW_TOL * pitch else 0)
    best, start = (0, 0), None
    for i, k in enumerate(kinds + [0]):
        if k and start is None:
            start = i
        elif not k and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if best[1] - best[0] < MIN_RUN:
        return None
    out = [lines[best[0]]]
    for i in range(best[0], best[1]):
        if kinds[i] == 2:
            out.append((lines[i] + lines[i + 1]) / 2)
        out.append(lines[i + 1])
    return out, pitch, best[1]


def detect_lines(gray):
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
    run = _regular_run(row_lines)
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


def apply_template(pl, template, snap_tol=0.006):
    """Place the template on this page, snapping to detected lines when close."""
    width = pl.right - pl.left
    edges = []
    for u in template:
        x = pl.left + u * width
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
