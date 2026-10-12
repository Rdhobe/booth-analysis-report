import unittest

import numpy as np

from form20.ocr import CellRead
from form20.pipeline import label_tail

XS = [0, 170, 250]          # a first column 170 px wide


def row(width_px):
    """A table row whose first cell holds ink `width_px` wide (None: an empty cell) and one more cell."""
    first = CellRead(crop=None if width_px is None else np.ones((20, width_px), np.uint8))
    return [first, CellRead()]


class LabelTailTests(unittest.TestCase):
    def test_the_first_wide_label_in_the_page_tail_starts_the_cut(self):
        tab = [row(30)] * 14 + [row(130), row(40), row(160), row(39), row(120)]    # 14 booths, then the subtotal rows
        self.assertEqual(label_tail(tab, XS), 14)

    def test_a_page_of_booths_only_is_left_alone(self):
        self.assertIsNone(label_tail([row(30), row(28), row(35)] * 8, XS))

    def test_a_wide_cell_far_from_the_foot_of_the_page_is_not_a_label_tail(self):
        tab = [row(30)] * 6 + [row(140)] + [row(30)] * 18          # odd, but 18 booth rows follow it
        self.assertIsNone(label_tail(tab, XS))

    def test_too_few_booth_rows_above_do_not_make_a_label_tail(self):
        self.assertIsNone(label_tail([row(30)] * 3 + [row(140)] * 3, XS))

    def test_a_sheet_whose_serials_are_wide_is_not_cut(self):
        tab = [row(90)] * 14 + [row(100), row(95)]                  # serials already fill half the cell: no outlier
        self.assertIsNone(label_tail(tab, XS))

    def test_a_taller_closing_row_with_a_narrow_label_starts_the_cut(self):
        tab = [row(30)] * 14 + [row(46)]                           # page 1: only "total of this page" closes the page
        edges = [i * 41 for i in range(15)] + [14 * 41 + 52]       # that row is 52 px against 41
        self.assertEqual(label_tail(tab, XS, edges), 14)

    def test_a_merged_pair_of_rows_is_not_taken_for_a_subtotal(self):
        tab = [row(30)] * 14 + [row(30)]
        edges = [i * 41 for i in range(15)] + [14 * 41 + 82]       # twice a booth's height: two rows the grid merged
        self.assertIsNone(label_tail(tab, XS, edges))

    def test_rows_of_one_height_give_no_tall_row(self):
        tab = [row(30)] * 16
        self.assertIsNone(label_tail(tab, XS, [i * 41 for i in range(17)]))

    def test_empty_cells_are_ignored(self):
        tab = [row(None)] * 3 + [row(30)] * 10 + [row(150)]
        self.assertEqual(label_tail(tab, XS), 13)


if __name__ == "__main__":
    unittest.main()
