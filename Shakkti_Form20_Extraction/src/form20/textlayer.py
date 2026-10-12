"""Read the vote table from a PDF's text layer (typed PDFs, searchable scans) instead of by OCR.

The digits in a text layer are exact, so a file that has one needs no OCR. The columns and rows are found from where
the numbers sit on the page, and the answer is given in the objects the OCR path produces (PageLines for the grid,
CellRead for the cells), so layout detection, validation and export are unchanged. Names are not read here: the Hindi
text layer uses a legacy font that comes out as gibberish.

A file is used only when most of its pages carry numbers, none is rotated, and the numbers fall into at least
MIN_COLS tight columns; anything else returns None and the caller reads the file by OCR as before.
"""
import re
from bisect import bisect_right
from statistics import median
from types import SimpleNamespace

import fitz  # PyMuPDF
import numpy as np

from .discover import discover
from .grid import PageLines
from .imaging import TARGET_WIDTH
from .ocr import CellRead

ALNUM = re.compile(r"\d+[A-Za-z]?")
DIGITS = re.compile(r"\d+")
MIN_TOKENS = 80          # numbers a page needs to count as a table page
MIN_PAGES = 0.7          # share of the pages that must be table pages
ROW_TOL = 0.0023         # first guess at the row grouping: centres closer than this share of the page width
ROW_SPREAD = 0.4         # final grouping: numbers within this many row pitches of each other are on one row (the
                         # columns of a row are often a few pixels off one another)
BIN = 0.002              # histogram bin for the x centres (share of page width)
PEAK_GAP = 0.02          # two columns are at least this far apart
PEAK_WINDOW = 0.012      # numbers within this of a column's centre are counted for it
REACH = 0.005            # a number belongs to a column when it lies within this of the centres seen in that column
# Fallback levels for the share of rows that must have a number in a column (see _columns).
PEAK_MASS = (0.40, 0.25, 0.15, 0.08, 0.04)
MIN_COLS = 6
GAP_FILL = 1.8           # a gap this many times the usual column spacing hides a column with few or no numbers
MIN_ROW_TOKENS = 3       # numbers a row needs to count as a data row
PROBE_MAX_ROWS = 80      # rows used to compare column sets by arithmetic
RUN_SPACING = (0.4, 3.2)  # spacing of consecutive rows, in row pitches, that keeps them in one run (a name that
                          # wraps onto a second line makes its row taller)


NAME_GAP = 1.0           # a number this many digit heights (or less) after a word on its line belongs to a name


def _tokens(page):
    """Numbers on a page as (x centre, y centre, text) in the pixels of imaging.render_page (the upright page).
    A number that directly follows a word on its own line ('SCHOOL NO. 1', 'ROOM 2') is part of a polling-station
    name, not a vote count, and is left out: such digits otherwise form a column of their own. The line is found by
    position (words on one baseline), because a PDF may put the name and its digit in separate text runs."""
    scale = TARGET_WIDTH / page.rect.width
    words = [(x0, y0, x1, y1, t) for x0, y0, x1, y1, t, *_ in page.get_text("words")]
    words.sort(key=lambda w: (w[1] + w[3]) / 2)
    out, line, last_y = [], [], None

    def flush():
        line.sort(key=lambda w: w[0])
        for i, (x0, y0, x1, y1, t) in enumerate(line):
            if not ALNUM.fullmatch(t):
                continue
            if i and any(ch.isalpha() for ch in line[i - 1][4]) and 0 <= x0 - line[i - 1][2] <= NAME_GAP * (y1 - y0):
                continue
            r = fitz.Rect(x0, y0, x1, y1) * page.rotation_matrix if page.rotation else fitz.Rect(x0, y0, x1, y1)
            out.append(((r.x0 + r.x1) / 2 * scale, (r.y0 + r.y1) / 2 * scale, t))

    for w in words:
        y = (w[1] + w[3]) / 2
        if line and y - last_y > 0.4 * (w[3] - w[1]):
            flush()
            line = []
        line.append(w)
        last_y = y
    flush()
    return out


def _row_groups(ys, tol):
    """Indices of the numbers grouped into rows by y centre, top to bottom."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    groups, last = [], None
    for i in order:
        if groups and ys[i] - last <= tol:
            groups[-1].append(i)
        else:
            groups.append([i])
        last = ys[i]
    return groups


def _peaks(xs, row_of, n_rows, width):
    """Column centres from the x centres of the numbers: [(centre, share of rows with a number there)], left to right."""
    bin_w = BIN * width
    hist = np.bincount((np.asarray(xs) / bin_w).astype(int))
    smooth = np.convolve(hist, np.ones(5), "same")
    gap = PEAK_GAP * width / bin_w
    chosen = []
    for i in np.argsort(-smooth, kind="stable"):
        if smooth[i] < 3:
            break
        if all(abs(i - j) >= gap for j in chosen):
            chosen.append(int(i))
    xs_a, rows_a = np.asarray(xs), np.asarray(row_of)
    out = []
    for i in sorted(chosen):
        near = np.abs(xs_a - (i + 0.5) * bin_w) <= PEAK_WINDOW * width
        if near.any():
            out.append((float(xs_a[near].mean()), len(set(rows_a[near])) / n_rows))
    return out


def _columns(peaks, expected_cols):
    """Peaks kept as columns. Real columns have a number in almost every row; digits ending some station names make
    sparse clusters of their own. So the peaks are cut where the share of rows drops most steeply (keeping at least
    MIN_COLS). If that count is not one the official candidate count allows, the strictest fixed level (PEAK_MASS)
    that gives an allowed count is tried before settling for the natural break."""
    ranked = sorted(peaks, key=lambda p: -p[1])
    if len(ranked) < MIN_COLS:
        return sorted(c for c, _ in ranked)
    masses = [m for _, m in ranked] + [0.0]
    keep = max(range(MIN_COLS, len(ranked) + 1), key=lambda n: (masses[n - 1] - masses[n], -n))
    natural = sorted(c for c, _ in ranked[:keep])
    if expected_cols and len(natural) not in expected_cols:
        for level in PEAK_MASS:
            kept = [c for c, m in peaks if m >= level]
            if len(kept) in expected_cols:
                return kept
    return natural


def _fill_gaps(centres, peaks):
    """Add the columns that sit in a gap of two or more column spacings on the right of the name column: one that
    prints no number at all (an empty rejected-votes column), or hardly any (a candidate with a handful of votes, which
    leaves a sparse peak that the cut-off in _columns dropped). A sparse peak near where the column should be is
    used; otherwise the column is placed at an even spacing."""
    if len(centres) < 4:
        return centres
    gaps = [b - a for a, b in zip(centres, centres[1:])]
    name = max(range(min(4, len(gaps))), key=lambda i: gaps[i])      # the widest of the leftmost gaps is the name column
    right = gaps[name + 1:]
    if len(right) < 3:
        return centres
    usual = median(right)
    out = []
    for j, c in enumerate(centres):
        out.append(c)
        if j > name and j < len(gaps) and gaps[j] / usual >= GAP_FILL:
            k = round(gaps[j] / usual)
            for m in range(1, k):
                even = c + gaps[j] * m / k
                near = [x for x, _ in peaks if abs(x - even) <= 0.35 * usual and x not in centres]
                out.append(min(near, key=lambda x: abs(x - even)) if near else even)
    return out


class TextDoc:
    """Columns, rows and cell texts of one PDF read from its text layer. Build with open_text_doc."""

    def __init__(self, tokens, centres, windows, pitch):
        self.row_tol = ROW_SPREAD * pitch
        self.tokens = tokens              # per page: [(x, y, text)]
        self.centres = centres            # column centres
        self.windows = windows            # (lo, hi) x range in which a number belongs to each column
        self.pitch = pitch
        self.bounds = ([2 * centres[0] - (centres[0] + centres[1]) / 2]
                       + [(a + b) / 2 for a, b in zip(centres, centres[1:])]
                       + [2 * centres[-1] - (centres[-1] + centres[-2]) / 2])

    def column_of(self, x):
        """Index of the column whose window holds x, or None (a number outside every column is ignored)."""
        i = bisect_right([lo for lo, _ in self.windows], x) - 1
        return i if i >= 0 and x <= self.windows[i][1] else None

    def accepted(self, p):
        """Numbers of page p that sit in a column: [(x, y, text, column)]."""
        out = []
        for x, y, t in self.tokens[p]:
            c = self.column_of(x)
            if c is not None:
                out.append((x, y, t, c))
        return out

    def page_lines(self, p):
        """The page's table as PageLines (the longest run of evenly spaced rows), or None when it has none."""
        toks = self.accepted(p)
        groups = [g for g in _row_groups([t[1] for t in toks], self.row_tol) if len(g) >= MIN_ROW_TOKENS]
        centres = [float(np.mean([toks[i][1] for i in g])) for g in groups]
        run = _longest_run(centres, self.pitch)
        if not run:
            return None
        first = (run[1] - run[0]) / 2 if len(run) > 1 else self.pitch / 2
        last = (run[-1] - run[-2]) / 2 if len(run) > 1 else self.pitch / 2
        edges = [run[0] - first] + [(a + b) / 2 for a, b in zip(run, run[1:])] + [run[-1] + last]
        return PageLines(
            left=int(self.bounds[0]), right=int(self.bounds[-1]), data_edges=[int(round(e)) for e in edges],
            header_top=max(0, int(edges[0] - 4 * self.pitch)),
            col_candidates=[int(round(b)) for b in self.bounds], pitch=float(self.pitch),
        )

    def reader(self, p):
        """A drop-in for ocr.read_cells for page p: cells come from the numbers in the text layer."""
        def read(gray, grid, row_edges, alnum_cols=(), workers=None):
            n_rows, n_cols = len(row_edges) - 1, len(self.windows)
            if len(grid.col_edges) - 1 != n_cols:
                raise ValueError(f"grid has {len(grid.col_edges) - 1} columns, the text layer found {n_cols}")
            cells = [[[] for _ in range(n_cols)] for _ in range(n_rows)]
            for x, y, t, c in self.accepted(p):
                r = bisect_right(row_edges, y) - 1
                if 0 <= r < n_rows and y <= row_edges[-1] and (c in alnum_cols or DIGITS.fullmatch(t)):
                    cells[r][c].append((x, t))
            table = []
            for row in cells:
                out = []
                for found in row:
                    text = "".join(t for _, t in sorted(found))
                    out.append(CellRead(reads={"A": text, "B": text}, confs={"A": 100.0 if text else 0.0,
                                                                              "B": 100.0 if text else 0.0}))
                table.append(out)
            return table
        return read


def _longest_run(centres, pitch):
    """Longest run of row centres in which consecutive rows are neither on top of each other nor more than a few pitches
    apart (a title, a summary table or a footer stands further off). Returns the run, [] when there are no rows."""
    lo, hi = RUN_SPACING
    best, cur = [], []
    for c in centres:
        if cur and lo * pitch <= c - cur[-1] <= hi * pitch:
            cur.append(c)
        else:
            cur = [c]
        if len(cur) > len(best):
            best = list(cur)
    return best


def _windows(centres, xs_a, width):
    windows = []
    for i, c in enumerate(centres):
        lo_cut = (centres[i - 1] + c) / 2 if i else -1e9
        hi_cut = (c + centres[i + 1]) / 2 if i + 1 < len(centres) else 1e9
        mine = xs_a[(np.abs(xs_a - c) <= PEAK_WINDOW * width) & (xs_a > lo_cut) & (xs_a <= hi_cut)]
        if len(mine):
            lo, hi = np.percentile(mine, 1), np.percentile(mine, 99)
        else:                                  # a blank column: a narrow window at its centre
            lo = hi = c
        windows.append((max(lo - REACH * width, lo_cut), min(hi + REACH * width, hi_cut)))
    return windows


def structure_share(doc, n_off, max_rows=PROBE_MAX_ROWS):
    """How well the vote identities hold in the first rows read with this column set (discover.discover's share, 0 when
    no structure with n_off candidates fits)."""
    table = []
    for p in range(len(doc.tokens)):
        pl = doc.page_lines(p)
        if pl is None:
            continue
        grid = SimpleNamespace(col_edges=[0] * (len(doc.windows) + 1))
        for row in doc.reader(p)(None, grid, pl.data_edges):
            table.append([int(c.text) if c.text.isdigit() else None for c in row])
        if len(table) >= max_rows:
            break
    found = discover(table[:max_rows], n_off) if table else None
    return found[3] if found else 0.0


def open_text_doc(pdf_path, expected_cols=None, n_off=None):
    """TextDoc for a PDF whose pages carry a usable text layer, else None. With n_off (the official candidate count)
    the column set is chosen by arithmetic: columns found by gap filling are kept only if they make the vote identities
    hold better (a sparse column may be a real candidate or stray numbers)."""
    with fitz.open(pdf_path) as doc:
        tokens = [_tokens(page) for page in doc]
    if not tokens or sum(len(t) >= MIN_TOKENS for t in tokens) < MIN_PAGES * len(tokens):
        return None
    width = TARGET_WIDTH
    spacings = []                         # the row pitch: spacing of rows that a first, tight grouping finds whole
    for page_tokens in tokens:
        groups = [g for g in _row_groups([t[1] for t in page_tokens], ROW_TOL * width) if len(g) >= 4]
        ys = [float(np.mean([page_tokens[i][1] for i in g])) for g in groups]
        spacings += [b - a for a, b in zip(ys, ys[1:])]
    if not spacings:
        return None
    first = median(spacings)
    pitch = median([s for s in spacings if 0.6 * first <= s <= 1.6 * first])
    xs, row_of, n_rows = [], [], 0
    for page_tokens in tokens:
        for g in _row_groups([t[1] for t in page_tokens], ROW_SPREAD * pitch):
            if len(g) >= 4:
                for i in g:
                    xs.append(page_tokens[i][0])
                    row_of.append(n_rows)
                n_rows += 1
    if n_rows < 20:
        return None
    peaks = _peaks(xs, row_of, n_rows, width)
    centres = _columns(peaks, expected_cols)
    if len(centres) < MIN_COLS:
        return None
    xs_a = np.asarray(xs)
    filled = _fill_gaps(centres, peaks)
    if expected_cols and len(filled) < min(expected_cols) - 2:      # most vote columns carry no digits: a partial layer
        return None
    doc = TextDoc(tokens, filled, _windows(filled, xs_a, width), pitch)
    if n_off is not None and len(filled) != len(centres):
        plain = TextDoc(tokens, centres, _windows(centres, xs_a, width), pitch)
        if structure_share(plain, n_off) >= structure_share(doc, n_off):
            return plain
    return doc
