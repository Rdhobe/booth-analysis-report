import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from form20.ocr import CellRead
from form20.pipeline import CROP_H, CROP_W, harvest_crops


def cell(text, ink=True):
    crop = np.full((20, 12), 255, np.uint8) if ink else None
    return CellRead(reads={"A": text}, confs={"A": 90.0}, crop=crop)


def row(status, texts, values, primary=None):
    return SimpleNamespace(status=status, cells=[cell(t, ink=t is not None) for t in texts], values=values,
                           primary=primary if primary is not None else [t or "" for t in texts])


class HarvestTests(unittest.TestCase):
    def run_harvest(self, rows):
        res = SimpleNamespace(n_cands=2, rows=rows)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "x.npz"
            n = harvest_crops(res, out)
            if not n:
                return n, None
            with np.load(out) as data:                      # close the file so Windows can delete the folder
                return n, (data["X"].shape, list(data["y"]), list(data["W"]), list(data["hard"]))

    def test_ok_rows_give_one_labelled_crop_per_cell(self):
        n, d = self.run_harvest([row("OK", ["5", "3", "8", "0", "1", "9", "0"], [5, 3, 8, 0, 1, 9, 0])])
        self.assertEqual(n, 7)
        self.assertEqual(d[0], (7, CROP_H, CROP_W))
        self.assertEqual(d[1], ["5", "3", "8", "0", "1", "9", "0"])
        self.assertTrue(all(w == 19 for w in d[2]))             # a 20x12 crop scaled to height 32 is 19 wide

    def test_blank_cell_that_the_arithmetic_makes_zero_is_labelled_zero(self):
        r = row("AUTO_CORRECTED", ["5", "3", "8", "", "1", "9", "0"], [5, 3, 8, 0, 1, 9, 0])
        n, d = self.run_harvest([r])
        self.assertEqual(d[1][3], "0")

    def test_cells_the_arithmetic_corrected_are_harvested_as_hard_with_the_final_value(self):
        changed = row("AUTO_CORRECTED", ["5", "3", "9", "0", "1", "9", "0"], [5, 3, 8, 0, 1, 9, 0])   # 9 was repaired to 8
        n, d = self.run_harvest([changed, row("REVIEW", ["5"] * 7, [5] * 7)])
        self.assertEqual(n, 7)                                   # the review row is skipped
        self.assertEqual(d[1][2], "8")                           # labelled with the repaired value ...
        self.assertEqual(d[3], [0, 0, 1, 0, 0, 0, 0])            # ... and flagged hard

    def test_rows_with_many_wrong_cells_are_too_unreliable_to_harvest(self):
        garbled = row("AUTO_CORRECTED", ["1", "2", "3", "4", "5", "6", "7"], [9, 8, 7, 6, 5, 4, 3])
        self.assertEqual(self.run_harvest([garbled])[0], 0)

    def test_cells_without_ink_are_skipped(self):
        n, d = self.run_harvest([row("OK", ["5", "3", "8", "0", "1", "9", None], [5, 3, 8, 0, 1, 9, 0])])
        self.assertEqual(n, 6)

    def test_nothing_to_harvest_writes_no_file(self):
        self.assertEqual(self.run_harvest([row("REVIEW", ["5"] * 7, [5] * 7)])[0], 0)


if __name__ == "__main__":
    unittest.main()
