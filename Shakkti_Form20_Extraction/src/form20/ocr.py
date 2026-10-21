"""Stage 5: read the digits of every table cell.

Each cell is cleaned (table-line residue removed, ink cropped tight and scaled
to a fixed height) and read on its own with Tesseract's single-word mode.
Cells are sent to Tesseract in batches (image-list mode, one process loads the
model once), several batches in parallel.

Every cell is read twice with two different renderings (variants A and B).
Where they disagree the cell is uncertain, and validation chooses the reading
that satisfies the sheet's arithmetic.
"""
import concurrent.futures as cf
import csv
import io
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

import cv2
import numpy as np

DIGITS = "0123456789"
ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# (name, target digit height in px, rendering)
VARIANTS = (("A", 44, "binary"), ("B", 56, "gray"))
# Cells that both variants read as blank (usually a lone 0, 4 or 1) are re-read in Tesseract's single-character mode.
EXTRA_VARIANTS = (("C", 44, "binary"), ("D", 72, "gray"))
PAD_Y, PAD_X = 16, 24


CONF_MARGIN = 20   # variant B overrides A only when clearly more confident
# The neural reader (reader.py) becomes a cell's primary reading when it is at least this confident (0-100).
READER_PRIMARY_CONF = float(os.environ.get("FORM20_READER_CONF", "90"))


@dataclass
class CellRead:
    reads: dict = field(default_factory=dict)   # variant -> text
    confs: dict = field(default_factory=dict)   # variant -> confidence 0-100
    crop: object = None                         # cleaned binary ink crop of the cell (None: no ink); used for training

    @property
    def primary_variant(self):
        if self.reads.get("N") and self.confs.get("N", 0.0) >= READER_PRIMARY_CONF:
            return "N"
        a, b = VARIANTS[0][0], VARIANTS[1][0]
        ta, tb = self.reads.get(a, ""), self.reads.get(b, "")
        if not ta and not tb:
            for extra, _, _ in EXTRA_VARIANTS:
                if self.reads.get(extra):
                    return extra
        if not ta and tb:
            return b
        if ta and tb and ta != tb and self.confs.get(b, 0) >= self.confs.get(a, 0) + CONF_MARGIN:
            return b
        return a

    @property
    def text(self):
        return self.reads.get(self.primary_variant, "")

    @property
    def conf(self):
        return self.confs.get(self.primary_variant, 0.0)

    def ordered_reads(self):
        """Readings, the primary one first."""
        first = self.primary_variant
        return [self.reads.get(first, "")] + [t for k, t in self.reads.items() if k != first]


def remove_lines(gray, pitch):
    """Paint the table's ruling lines white so they cannot leak into cells."""
    h, w = gray.shape
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, w // 60), 1)))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(pitch * 1.3))))
    mask = cv2.dilate(cv2.bitwise_or(hor, ver), np.ones((3, 3), np.uint8), iterations=2)
    out = gray.copy()
    out[mask > 0] = 255
    return out


TRACK = os.environ.get("FORM20_ROW_TRACK", "on") != "off"
RULE_TRACK = os.environ.get("FORM20_RULE_TRACK", "on") != "off"
TRACK_REACH = 0.3      # a row may sit this many pitches away from where the flat grid puts it, in a given column
TRACK_WINDOW = 0.45    # half height, in pitches, of the window whose ink centre is taken as the row's centre
TRACK_MIN = 0.3        # a window with less ink than this share of the typical one is not trusted
TRACK_REGULAR = 0.3    # only rows within this share of one pitch in height are tracked (the printed totals are taller)
TRACK_OUTLIER = 0.15   # a row whose offset differs this many pitches from its neighbours' median takes theirs
TRACK_OWN = 0.5        # a row is tracked only if its own window holds this share of the typical ink (a blank row is not)
TRACK_LEVEL = 0.1      # a page whose rows drift less than this many pitches (across, and from row to row) is left flat
TRACK_DRIFT = 0.12     # ... unless one in ten of its cells has its digits this many pitches off the flat grid (a cell's margin)


def tracked_edges(clean, xs, row_edges, pitch):
    """Row edges for every column, following the digits of that column.

    On a tilted or curved scan the rows are not level: the digits of the right-hand columns sit lower (or higher) than
    those of the left-hand ones, and a flat cell cuts them. For each column and row the centre of the ink in a window
    around the row is found (the window is re-centred a few times, so digits that start outside it are caught), but never
    further than TRACK_REACH from the flat position. A tilt is a straight line across the page, a curve changes slowly
    from row to row: so the slope is the median over the rows, each row has its own offset, an offset far from the
    median of its neighbours (a row with little ink that locked onto the next row's digits) is replaced by theirs, and
    what is left over is taken from the neighbouring columns. Rows that are not about one pitch tall (the printed totals)
    are not tracked at all, and an edge moves by the average shift of the two rows it separates.
    Returns a list per column of len(row_edges) edges."""
    n_rows, n_cols = len(row_edges) - 1, len(xs) - 1
    flat = [(row_edges[r] + row_edges[r + 1]) / 2 for r in range(n_rows)]
    regular = np.abs(np.diff(row_edges) - pitch) <= TRACK_REGULAR * pitch
    reach, half, h = TRACK_REACH * pitch, TRACK_WINDOW * pitch, clean.shape[0]
    shift = np.full((n_rows, n_cols), np.nan)
    power = np.zeros((n_rows, n_cols))
    for c in range(n_cols):
        band = clean[:, xs[c] + 3:xs[c + 1] - 3] < 128
        if band.shape[1] < 4:
            continue
        ink = band.sum(axis=1).astype(float)
        own = [ink[max(0, int(flat[r] - half)):int(flat[r] + half) + 1].sum() for r in range(n_rows)]
        typical = float(np.median([o for o, ok in zip(own, regular) if ok and o > 0] or [0.0]))
        for r in range(n_rows):
            if not regular[r] or own[r] < TRACK_OWN * typical:
                continue                                  # a row with no ink of its own would slide onto the next row's
            centre = flat[r]
            for _ in range(3):
                lo, hi = max(0, int(centre - half)), min(h, int(centre + half) + 1)
                total = ink[lo:hi].sum()
                if hi - lo < 3 or total <= 0:
                    break
                centre = float((np.arange(lo, hi) * ink[lo:hi]).sum() / total)
                centre = min(max(centre, flat[r] - reach), flat[r] + reach)
            power[r, c] = ink[max(0, int(centre - half)):min(h, int(centre + half) + 1)].sum()
            shift[r, c] = centre - flat[r]
    seen = power[power > 0]
    shift[power < TRACK_MIN * (np.median(seen) if len(seen) else 0.0)] = np.nan
    xc = np.array([(xs[c] + xs[c + 1]) / 2 for c in range(n_cols)], float)
    xc -= xc.mean()
    slopes = []
    for r in range(n_rows):
        ok = ~np.isnan(shift[r])
        if ok.sum() >= 3 and np.ptp(xc[ok]) > 0:
            slopes.append(((xc[ok] - xc[ok].mean()) * (shift[r, ok] - shift[r, ok].mean())).sum()
                          / ((xc[ok] - xc[ok].mean()) ** 2).sum())
    slope = float(np.median(slopes)) if slopes else 0.0
    offset = np.full(n_rows, np.nan)
    for r in range(n_rows):
        ok = ~np.isnan(shift[r])
        if ok.any():
            offset[r] = float(np.median(shift[r, ok] - slope * xc[ok]))
    for r in range(n_rows):                              # an offset far from its neighbours' is taken from them
        near = offset[max(0, r - 2):r + 3]
        near = near[~np.isnan(near)]
        if len(near) >= 3 and (np.isnan(offset[r]) or abs(offset[r] - np.median(near)) > TRACK_OUTLIER * pitch):
            offset[r] = float(np.median(near))
    tracked = offset[~np.isnan(offset)]
    tilt = abs(slope) * float(np.ptp(xc))                # how far the rows drift across the page
    spread = float(np.percentile(tracked, 90) - np.percentile(tracked, 10)) if len(tracked) >= 5 else 0.0
    moved = np.abs(shift[regular][~np.isnan(shift[regular])])         # how far the digits sit from the flat grid: a curved
    drift = float(np.percentile(moved, 90)) if len(moved) else 0.0   # page has columns off by more than the margin of a
    if tilt < TRACK_LEVEL * pitch and spread < TRACK_LEVEL * pitch and drift < TRACK_DRIFT * pitch:   # cell, with no tilt
        return [[int(r) for r in row_edges] for _ in range(n_cols)]    # a level page needs no tracking (and it only risks
    smooth = np.zeros((n_rows, n_cols))                  # making noise in header rows look like data)
    for r in range(n_rows):
        if not regular[r] or np.isnan(offset[r]):
            continue                                     # untracked rows keep the flat grid
        line = offset[r] + slope * xc
        resid = np.where(np.isnan(shift[r]), np.nan, shift[r] - line)
        for c in range(n_cols):
            near = resid[max(0, c - 1):c + 2]
            near = near[~np.isnan(near)]
            local = float(np.median(near)) if len(near) else 0.0
            smooth[r, c] = line[c] + (local if abs(local) <= TRACK_OUTLIER * pitch else 0.0)
    out = []
    for c in range(n_cols):                        # each edge keeps its place in the grid (rows differ in height: the
        edges = [row_edges[0] + smooth[0, c]]      # printed totals are taller than a booth) and moves by the average
        edges += [row_edges[r] + (smooth[r - 1, c] + smooth[r, c]) / 2 for r in range(1, n_rows)]   # shift of its two rows
        edges.append(row_edges[-1] + smooth[n_rows - 1, c])
        out.append([int(round(e)) for e in edges])
    return out


RULE_TRACK_MIN = 0.65    # rules must drift this many pitches across the page before they replace the flat rows (verified
                         # files have pages that drift up to 0.6 and read right as they are; a bowed page drifts 0.7 and more)
RULE_REACH = 0.45        # a rule is matched to the previous column's within this many pitches
RULE_COVER = 0.5         # a column's rule must cover this share of the column's width


def _column_rules(bw, x0, x1):
    """y of every horizontal rule within one column's x-range (rules are the long horizontal ink)."""
    band = bw[:, x0:x1]
    width = x1 - x0
    if width < 12:
        return []
    # a sloping rule drifts several pixels along a column: thicken it vertically so that the opening keeps it whole
    thick = cv2.dilate(band, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 7)))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(0.5 * width)), 1))
    hor = cv2.morphologyEx(thick, cv2.MORPH_OPEN, kernel)
    ys = np.nonzero((hor > 0).sum(axis=1) > RULE_COVER * width)[0]
    out, cur = [], []
    for y in ys:
        if cur and y - cur[-1] > 4:
            out.append(float(np.mean(cur)))
            cur = []
        cur.append(int(y))
    if cur:
        out.append(float(np.mean(cur)))
    return out


def rule_tracked_edges(gray, xs, row_edges, pitch):
    """Row edges for every column, followed along the table's own horizontal rules, for a page whose rows run
    downhill or uphill so far across the page that a flat cell (or the ink tracker, limited to a third of a row) reads
    the neighbouring row's digits in the right-hand columns. Starting from the flat edges in the first column, each
    column takes, for every edge, the nearest rule of its own within RULE_REACH of the previous column's edge - the
    drift between neighbouring columns is small even where it adds up to several rows across the page. An edge with no
    rule near it keeps the previous column's place. Returns a list per column of len(row_edges) edges, or None when no
    column strays from the flat edges by RULE_TRACK_MIN pitches (the page is level enough for the flat grid)."""
    if len(row_edges) < 3 or len(xs) < 3 or pitch <= 0:
        return None
    from .imaging import binarize
    bw = binarize(gray)
    n_cols = len(xs) - 1
    prev = [float(y) for y in row_edges]
    out = []
    for c in range(n_cols):
        rules = _column_rules(bw, xs[c] + 4, xs[c + 1] - 4)
        cur = []
        for y in prev:
            near = [v for v in rules if abs(v - y) <= RULE_REACH * pitch]
            cur.append(min(near, key=lambda v: abs(v - y)) if near else y)
        for i in range(1, len(cur)):                       # two edges never collapse onto one rule
            if cur[i] <= cur[i - 1] + 0.3 * pitch:
                cur[i] = prev[i] + (cur[i - 1] - prev[i - 1])
        out.append(cur)
        prev = cur
    drift = max(abs(out[c][r] - row_edges[r]) for c in range(n_cols) for r in range(len(row_edges)))
    if drift < RULE_TRACK_MIN * pitch:
        return None
    return [[int(round(v)) for v in col] for col in out]


def _is_cut(bbox, y0, y1, inset):
    """True when the digits found in a cell run up to its top or bottom edge, i.e. the flat cell clips them."""
    return bbox is not None and (bbox[1] <= y0 + inset + 1 or bbox[3] >= y1 - inset - 1)


SLIDE_STEP = 2         # px: a clipped cell is slid this far at a time along the clip

def slide_uncut(clean, x0, y0, x1, y1, inset, ref_h, crop, reach):
    """A clipped crop's cell slid, up to `reach` px, until the digits sit clear of its top and bottom edges.

    The flat grid and the digits of a curved or tilted scan part by a few px in places - more in some columns than in
    others, so a shift estimated for the page averages the clip away. Where the digits run into the cell's edge the
    cell is moved the way they run; a crop whose digits touch neither edge has them whole (a neighbouring row's digits
    entering the window would touch its far edge, and the crop would still count as clipped). Returns the new crop, or
    the crop it was given when no slide frees the digits or the digits are cut at both ends (taller than a cell)."""
    top, bottom = crop[1][1] <= y0 + inset + 1, crop[1][3] >= y1 - inset - 1
    if top == bottom:
        return crop
    d = -1 if top else 1
    for s in range(SLIDE_STEP, reach + 1, SLIDE_STEP):
        if y0 + d * s < 0 or y1 + d * s > clean.shape[0]:
            break
        moved = clean_cell(clean, x0, y0 + d * s, x1, y1 + d * s, inset, ref_h=ref_h)
        if moved[0] is None:
            break
        if not _is_cut(moved[1], y0 + d * s, y1 + d * s, inset):
            return moved if moved[0].shape[0] > crop[0].shape[0] else crop
    return crop


def clean_cell(gray, x0, y0, x1, y1, inset, ref_h=None):
    """Return (binary ink crop, bbox) of the cell's digits, or (None, None).
    bbox is (x0, y0, x1, y1) in page coordinates."""
    ix, iy = inset + 1, inset
    ox, oy = x0 + ix, y0 + iy
    c = gray[oy : y1 - iy, ox : x1 - ix]
    if c.size == 0:
        return None, None
    _, b = cv2.threshold(c, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    H, W = b.shape
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    keep = np.zeros_like(b)
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 8 or h < 0.2 * min(H, ref_h or H):
            continue   # specks (scaled to a normal row height, not to tall total rows)
        touches = x == 0 or y == 0 or x + w >= W or y + h >= H
        if touches and min(w, h) <= 5:
            continue   # line residue along the cell border
        keep[lab == i] = 255
    ys, xs = np.nonzero(keep)
    if len(xs) == 0:
        return None, None
    ya, yb, xa, xb = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    if yb - ya < 6:
        return None, None
    return keep[ya:yb, xa:xb], (ox + xa, oy + ya, ox + xb, oy + yb)


def render(crop, target_h):
    """Dark ink on a white canvas, scaled to target_h, padded."""
    s = target_h / crop.shape[0]
    w = max(4, int(round(crop.shape[1] * s)))
    img = cv2.resize(crop, (w, target_h), interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(255 - img, PAD_Y, PAD_Y, PAD_X, PAD_X, cv2.BORDER_CONSTANT, value=255)


def render_gray(gray, bbox, target_h):
    """Grayscale rendering of the same digits (no binarisation of our own)."""
    x0, y0, x1, y1 = bbox
    crop = gray[max(0, y0 - 2) : y1 + 2, max(0, x0 - 2) : x1 + 2]
    s = target_h / crop.shape[0]
    w = max(4, int(round(crop.shape[1] * s)))
    img = cv2.resize(crop, (w, target_h), interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(img, PAD_Y, PAD_Y, PAD_X, PAD_X, cv2.BORDER_REPLICATE)


def _tess_chunk(imgs, psm, lang, whitelist):
    with tempfile.TemporaryDirectory() as td:
        paths = []
        for i, im in enumerate(imgs):
            p = os.path.join(td, f"{i:05d}.png")
            cv2.imwrite(p, im if im is not None else np.full((40, 40), 255, np.uint8))
            paths.append(p)
        lst = os.path.join(td, "list.txt")
        with open(lst, "w") as f:
            f.write("\n".join(paths))
        cmd = [
            "tesseract", lst, "stdout", "-l", lang, "--oem", "1", "--psm", str(psm),
            "-c", f"tessedit_char_whitelist={whitelist}",
            "-c", "load_system_dawg=0", "-c", "load_freq_dawg=0",
            "-c", "tessedit_create_tsv=1",
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8").stdout
    res = [["", []] for _ in imgs]
    for row in csv.reader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(row) < 12 or row[0] != "5":
            continue
        pg = int(row[1]) - 1
        t = row[11].strip()
        if t and 0 <= pg < len(imgs):
            res[pg][0] += t
            res[pg][1].append(float(row[10]))
    return [(a, min(b) if b else 0.0) for a, b in res]


def tess_batch(imgs, psm=8, lang="eng", whitelist=DIGITS, workers=8, min_chunk=40):
    """OCR many small images; returns [(text, conf)] in input order."""
    if not imgs:
        return []
    size = max(min_chunk, -(-len(imgs) // workers))
    chunks = [imgs[i : i + size] for i in range(0, len(imgs), size)]
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(lambda ch: _tess_chunk(ch, psm, lang, whitelist), chunks))
    return [r for p in parts for r in p]


DEFAULT_WORKERS = int(os.environ.get("FORM20_OCR_WORKERS", "8"))   # Tesseract processes per file; the batch runner lowers it


def _neural_reads(table, cropped, alnum_cols):
    """Add the neural reader's reading (variant N) of every digit cell, when a trained model is available."""
    from .reader import get_reader

    reader = get_reader()
    if reader is None:
        return
    keys = [(r, c) for (r, c), (crop, _) in cropped.items() if crop is not None and c not in alnum_cols]
    for (r, c), (text, conf) in zip(keys, reader.read([cropped[k][0] for k in keys])):
        if text:
            table[r][c].reads["N"] = text
            table[r][c].confs["N"] = conf


def _reread_blank_cells(table, cropped, clean, alnum_cols, workers):
    """Second chance for digit cells both variants read as blank: single-character mode (psm 10) on two renderings."""
    todo = [(r, c) for r, row in enumerate(table) for c, cell in enumerate(row)
            if c not in alnum_cols and cell.text == "" and cropped[(r, c)][0] is not None]
    if not todo:
        return
    for name, th, rendering in EXTRA_VARIANTS:
        imgs = []
        for r, c in todo:
            crop, bbox = cropped[(r, c)]
            imgs.append(render(crop, th) if rendering == "binary" else render_gray(clean, bbox, th))
        for (r, c), (t, cf_) in zip(todo, tess_batch(imgs, psm=10, whitelist=DIGITS, workers=workers)):
            table[r][c].reads[name] = t
            table[r][c].confs[name] = cf_


def read_cells(gray, grid, row_edges, alnum_cols=(), workers=DEFAULT_WORKERS):
    """Read every cell of the rows bounded by row_edges.
    Returns list[list[CellRead]] indexed [row][col]."""
    inset = max(3, int(round(0.09 * grid.pitch)))
    xs = grid.col_edges
    n_rows, n_cols = len(row_edges) - 1, len(xs) - 1
    clean = remove_lines(gray, grid.pitch)
    table = [[CellRead() for _ in range(n_cols)] for _ in range(n_rows)]
    cropped = {}
    ruled = rule_tracked_edges(gray, xs, row_edges, grid.pitch) if TRACK and RULE_TRACK and n_rows else None
    per_col = ruled or (tracked_edges(clean, xs, row_edges, grid.pitch) if TRACK and n_rows else None)
    ref_h = grid.pitch - 2 * inset
    reach = int(TRACK_REACH * grid.pitch)
    for r in range(n_rows):
        for c in range(n_cols):
            if ruled:                                  # a strongly curved page: every cell follows its own column's rules
                crop = clean_cell(clean, xs[c], ruled[c][r], xs[c + 1], ruled[c][r + 1], inset, ref_h=ref_h)
                cropped[(r, c)] = crop
                continue
            crop = clean_cell(clean, xs[c], row_edges[r], xs[c + 1], row_edges[r + 1], inset, ref_h=ref_h)
            if TRACK and _is_cut(crop[1], row_edges[r], row_edges[r + 1], inset):
                # the flat cell clips this cell's digits: slide it clear of them, else take the cell that follows the
                # column's own rows
                slid = slide_uncut(clean, xs[c], row_edges[r], xs[c + 1], row_edges[r + 1], inset, ref_h, crop, reach)
                if slid is not crop:
                    crop = slid
                elif per_col is not None:
                    moved = clean_cell(clean, xs[c], per_col[c][r], xs[c + 1], per_col[c][r + 1], inset, ref_h=ref_h)
                    if moved[0] is not None and (crop[0] is None or moved[0].shape[0] > crop[0].shape[0]):
                        crop = moved
            cropped[(r, c)] = crop
    for name, th, rendering in VARIANTS:
        for wl, cols in (
            (ALNUM, [c for c in range(n_cols) if c in alnum_cols]),
            (DIGITS, [c for c in range(n_cols) if c not in alnum_cols]),
        ):
            if not cols or (wl == ALNUM and name != VARIANTS[0][0]):
                continue
            coords, imgs = [], []
            for r in range(n_rows):
                for c in cols:
                    crop, bbox = cropped[(r, c)]
                    if crop is None:
                        imgs.append(None)
                    elif rendering == "binary":
                        imgs.append(render(crop, th))
                    else:
                        imgs.append(render_gray(clean, bbox, th))
                    coords.append((r, c))
            for (r, c), (t, cf_) in zip(coords, tess_batch(imgs, whitelist=wl, workers=workers)):
                table[r][c].reads[name] = t
                table[r][c].confs[name] = cf_
    for (r, c), (crop, _) in cropped.items():
        table[r][c].crop = crop
    _reread_blank_cells(table, cropped, clean, alnum_cols, workers)
    _neural_reads(table, cropped, alnum_cols)
    return table
