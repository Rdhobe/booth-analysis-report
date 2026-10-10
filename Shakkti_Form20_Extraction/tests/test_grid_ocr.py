import unittest

import cv2
import numpy as np

from form20.grid import apply_template, build_col_template, detect_lines
from form20.ocr import CellRead, clean_cell, remove_lines, tess_batch, render


def synthetic_table(rows=20, cols=6, pitch=40, w=2600, h=1800, x0=200, colw=300, y0=300, digits=True):
    img = np.full((h, w), 255, np.uint8)
    xs = [x0 + i * colw for i in range(cols + 1)]
    ys = [y0 + i * pitch for i in range(rows + 1)]
    for y in ys:
        cv2.line(img, (xs[0], y), (xs[-1], y), 0, 2)
    for x in xs:
        cv2.line(img, (x, ys[0]), (x, ys[-1]), 0, 2)
    # a taller header row above
    cv2.line(img, (xs[0], y0 - 120), (xs[-1], y0 - 120), 0, 2)
    if digits:
        for r in range(rows):
            for c in range(cols):
                cv2.putText(img, str((r * 7 + c * 3) % 97), (xs[c] + 100, ys[r] + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
    return img, xs, ys


class GridTests(unittest.TestCase):
    def test_rows_and_columns_are_found(self):
        img, xs, ys = synthetic_table()
        pl = detect_lines(img)
        self.assertIsNotNone(pl)
        self.assertEqual(len(pl.data_edges) - 1, 20)
        tpl = build_col_template([pl, pl])
        grid = apply_template(pl, tpl)
        self.assertEqual(grid.n_cols, 6)
        for got, want in zip(grid.col_edges, xs):
            self.assertLess(abs(got - want), 4)

    def test_missing_row_line_is_reinserted(self):
        img, xs, ys = synthetic_table(digits=False)
        y = ys[7]
        cv2.line(img, (xs[0] - 5, y), (xs[-1] + 5, y), 255, 6)      # erase one ruling line
        pl = detect_lines(img)
        self.assertEqual(len(pl.data_edges) - 1, 20)


class OcrTests(unittest.TestCase):
    def test_line_residue_is_removed_and_digits_kept(self):
        img, xs, ys = synthetic_table(rows=3, cols=2, digits=False, pitch=44)
        cv2.putText(img, "506", (xs[0] + 90, ys[1] + 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
        clean = remove_lines(img, 44)
        crop, bbox = clean_cell(clean, xs[0], ys[1], xs[1], ys[2], inset=4, ref_h=36)
        self.assertIsNotNone(crop)
        self.assertGreater(crop.shape[1], crop.shape[0])        # three digits wide

    def test_tesseract_reads_rendered_digits(self):
        img, xs, ys = synthetic_table(rows=2, cols=1, digits=False, pitch=60)
        cv2.putText(img, "1294", (xs[0] + 60, ys[0] + 42), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2)
        clean = remove_lines(img, 60)
        crop, _ = clean_cell(clean, xs[0], ys[0], xs[1], ys[1], inset=4, ref_h=50)
        out = tess_batch([render(crop, 44)])
        self.assertEqual(out[0][0], "1294")


if __name__ == "__main__":
    unittest.main()
