"""Find a table's columns from where its digits sit, for scans whose vertical rules are faint or missing.

The column template normally comes from the vertical ruling lines. Some sheets have none between the candidate columns
(or only broken ones), and the template then has the wrong number of columns, so cells cut across digits and the file is
not read. The digits themselves still line up in columns, which is what the typed PDFs' text layer is used for in
textlayer.py: here the numbers are the digit-sized ink blobs found in the data rows, grouped into numbers, and the same
peak logic finds the columns, using the official candidate count to decide how many there are.
"""
from statistics import median

import cv2
import numpy as np

from .imaging import TARGET_WIDTH
from .textlayer import _columns, _fill_gaps, _peaks

GLYPH = (0.25, 0.95)      # height of a digit, in row pitches
MAX_WIDTH = 1.2           # widest glyph, in row pitches
TOKEN_GAP = 0.8           # glyphs closer than this many glyph heights belong to one number
MIN_ROWS = 20             # data rows needed over the whole file to trust the columns


def page_tokens(clean, pl):
    """[(u, row, u_left, u_right)] for the numbers in the data rows of a page: u is the centre of the number as a share
    of the table width (u_left / u_right its extent), row the index of its data row. clean: the page with the ruling
    lines painted out."""
    edges, pitch = pl.data_edges, pl.pitch
    y0, y1, x0, x1 = int(edges[0]), int(edges[-1]), int(pl.left), int(pl.right)
    if y1 - y0 < pitch or x1 - x0 < 10:
        return []
    ink = (clean[y0:y1, x0:x1] < 128).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    by_row = {}
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 10 or not GLYPH[0] * pitch <= h <= GLYPH[1] * pitch or w > MAX_WIDTH * pitch:
            continue
        row = int(np.searchsorted(edges, y + h / 2 + y0) - 1)
        if 0 <= row < len(edges) - 1:
            by_row.setdefault(row, []).append((x, x + w, h))
    out, width = [], float(x1 - x0)
    for row, glyphs in by_row.items():
        glyphs.sort()
        gap = TOKEN_GAP * median(h for _, _, h in glyphs)
        number = [glyphs[0]]
        for g in glyphs[1:]:
            if g[0] - number[-1][1] <= gap:
                number.append(g)
            else:
                out.append(_token(number, row, width))
                number = [g]
        out.append(_token(number, row, width))
    return out


def _token(number, row, width):
    a, b = number[0][0], number[-1][1]
    return ((a + b) / 2 / width, row, a / width, b / width)


def ink_template(pages_tokens, expected_cols):
    """Column template (edges as shares of the table width, 0 and 1 at the outer edges) from the numbers of every page, or
    None when the digits do not fall into a column count in expected_cols. pages_tokens: per page, page_tokens output."""
    xs, row_of, rows = [], [], {}
    for p, tokens in enumerate(pages_tokens):
        for u, r, _, _ in tokens:
            xs.append(u * TARGET_WIDTH)
            row_of.append(rows.setdefault((p, r), len(rows)))
    if len(rows) < MIN_ROWS:
        return None
    peaks = _peaks(xs, row_of, len(rows), TARGET_WIDTH)
    centres = _fill_gaps(_columns(peaks, expected_cols), peaks)
    if len(centres) < 2 or len(centres) not in expected_cols:
        return None
    u = [c / TARGET_WIDTH for c in centres]
    return [0.0] + [(a + b) / 2 for a, b in zip(u, u[1:])] + [1.0]


CUT_MARGIN = 0.004        # an edge this close to a number's end does not cut it


def cut_share(template, pages_tokens):
    """Share of the numbers that a template's column edges cut through. Right columns cut almost none; edges that lie
    on digits (a vertical 'rule' that is really a stroke of text, a column count that is wrong) cut many."""
    edges = np.asarray(template[1:-1], float)
    total = cut = 0
    for tokens in pages_tokens:
        for _, _, a, b in tokens:
            total += 1
            cut += bool(((edges > a + CUT_MARGIN) & (edges < b - CUT_MARGIN)).any())
    return cut / total if total else 0.0


CUT_BAD = 0.08            # a template whose edges cut more than this share of the numbers is not the table's columns
CUT_GAIN = 0.5            # and the digits' columns must cut at most this share of what the lines' columns cut


def choose_columns(pages_tokens, template, allowed_cols):
    """(template, from_digits, why): the line-based template if it fits, else the digit-based one.

    The line-based template is kept when it has an allowed number of columns and its edges cut few numbers. Otherwise the
    columns are found from the digits; they replace it if the lines' count is not an allowed one, or if they cut much
    less (CUT_BAD, CUT_GAIN). `why` says in words what was found, '' when the template is kept."""
    n = len(template) - 1
    cut = cut_share(template, pages_tokens)
    if n in allowed_cols and cut < CUT_BAD:
        return template, False, ""
    by_digits = ink_template(pages_tokens, allowed_cols)
    if by_digits is None:
        return template, False, ""
    better = cut_share(by_digits, pages_tokens)
    if n not in allowed_cols or (better < CUT_BAD and better <= CUT_GAIN * cut):
        return by_digits, True, (f"the column lines give {n} columns and cut {cut:.0%} of the numbers; "
                                 f"the digits give {len(by_digits) - 1} columns cutting {better:.0%}")
    return template, False, ""
