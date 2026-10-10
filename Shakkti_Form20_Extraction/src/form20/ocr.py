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
PAD_Y, PAD_X = 16, 24


CONF_MARGIN = 20   # variant B overrides A only when clearly more confident


@dataclass
class CellRead:
    reads: dict = field(default_factory=dict)   # variant -> text
    confs: dict = field(default_factory=dict)   # variant -> confidence 0-100

    @property
    def primary_variant(self):
        a, b = VARIANTS[0][0], VARIANTS[1][0]
        ta, tb = self.reads.get(a, ""), self.reads.get(b, "")
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


def read_cells(gray, grid, row_edges, alnum_cols=(), workers=8):
    """Read every cell of the rows bounded by row_edges.
    Returns list[list[CellRead]] indexed [row][col]."""
    inset = max(3, int(round(0.09 * grid.pitch)))
    xs = grid.col_edges
    n_rows, n_cols = len(row_edges) - 1, len(xs) - 1
    clean = remove_lines(gray, grid.pitch)
    table = [[CellRead() for _ in range(n_cols)] for _ in range(n_rows)]
    cropped = {}
    for r in range(n_rows):
        for c in range(n_cols):
            cropped[(r, c)] = clean_cell(
                clean, xs[c], row_edges[r], xs[c + 1], row_edges[r + 1], inset, ref_h=grid.pitch - 2 * inset
            )
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
    return table
