"""Stage 4: page header (title block) and candidate-name row."""
import re
from collections import Counter

import cv2
import numpy as np
import pytesseract

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def title_text(gray, grid, lang="eng+hin"):
    """OCR of everything above the table."""
    top = max(0, grid.header_top - 4)
    crop = gray[:top, :]
    return pytesseract.image_to_string(crop, lang=lang, config="--oem 1 --psm 6")


def is_hindi(text):
    return len(_DEVANAGARI.findall(text)) > 25


def parse_title(text, hindi):
    """Pull electors / segment / constituency out of the title block."""
    meta = {"electors": None, "segment_no": None, "segment_name": None, "constituency": None}
    flat = re.sub(r"\s+", " ", text)
    if not hindi:
        m = re.search(r"Electors[^0-9]{0,60}?(\d{4,7})", flat)
        if m:
            meta["electors"] = int(m.group(1))
        m = re.search(r"segment\s*[.\-–—_\s]*(\d+)\s*[-–—]\s*([A-Za-z][A-Za-z .]+?)\s+Assembly", flat)
        if m:
            meta["segment_no"] = int(m.group(1))
            meta["segment_name"] = m.group(2).strip()
    else:
        m = re.search(r"(\d{5,7})\s*$", flat) or re.search(r"संख्या\S*\s*[-–—]?\s*(\d{5,7})", flat)
        if m:
            meta["electors"] = int(m.group(1))
        m = re.search(r"से\s*(\d+)\s*[-–—]+\s*([^\s,]+)", flat)
        if m:
            meta["segment_no"] = int(m.group(1))
            meta["segment_name"] = m.group(2).strip()
        m = re.search(r"(\d+)\s*[-–—]+\s*([^\s,]+)\s*,\s*विधानसभा", flat)
        if m:
            meta["constituency"] = f"{int(m.group(1))}-{m.group(2).strip()}"
    return meta


def names_band(grid):
    """y-range of the candidate-name row: between the last two header lines."""
    lines = [y for y in grid.row_lines if y <= grid.data_edges[0] + 2]
    if len(lines) >= 2:
        return lines[-2], lines[-1]
    return max(0, grid.data_edges[0] - int(4 * grid.pitch)), grid.data_edges[0]


def read_candidate_names(gray, grid, id_cols, n_cands, hindi):
    """OCR of one page's candidate-name cells (list of str, '' when unreadable)."""
    y0, y1 = names_band(grid)
    out = []
    for c in range(id_cols, id_cols + n_cands):
        x0, x1 = grid.col_edges[c] + 1, grid.col_edges[c + 1] - 1
        cell = gray[y0 + 2 : y1 - 1, x0:x1]
        if cell.size == 0:
            out.append("")
            continue
        if hindi:
            cell = cv2.rotate(cell, cv2.ROTATE_90_CLOCKWISE)
            scale = 1.6
            lang, cfg = "hin", "--oem 1 --psm 6"
        else:
            scale = 2.0
            lang, cfg = "eng", "--oem 1 --psm 6"
        cell = cv2.resize(cell, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        cell = cv2.copyMakeBorder(cell, 12, 12, 12, 12, cv2.BORDER_REPLICATE)
        txt = pytesseract.image_to_string(cell, lang=lang, config=cfg)
        txt = re.sub(r"\s+", " ", txt).strip()
        if not hindi:
            txt = re.sub(r"[^A-Za-z .]", "", txt).strip().upper()
        out.append(txt)
    return out


def _similar(a, b):
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def consensus(per_page_names):
    """For each candidate column pick the reading most similar to the others
    (medoid) - robust to the odd truncated or garbled page."""
    n = max((len(p) for p in per_page_names), default=0)
    result = []
    for i in range(n):
        reads = [p[i] for p in per_page_names if i < len(p) and p[i]]
        if not reads:
            result.append("")
            continue
        best = max(reads, key=lambda r: (sum(_similar(r, o) for o in reads), len(r)))
        result.append(best)
    return result
