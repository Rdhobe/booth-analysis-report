import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from form20.grid import unruled_tail
from tests.test_grid_ocr import synthetic_table


def grid_for(xs, ys):
    return SimpleNamespace(col_edges=list(xs), data_edges=list(ys), total_edges=[], pitch=40.0)


class UnruledTailTests(unittest.TestCase):
    def setUp(self):
        self.img, self.xs, self.ys = synthetic_table(rows=20, cols=6, digits=True)

    def test_rows_inside_the_rules_are_all_kept(self):
        self.assertEqual(unruled_tail(self.img, grid_for(self.xs, self.ys[3:15])), 0)
        self.assertEqual(unruled_tail(self.img, grid_for(self.xs, self.ys[3:21])), 0)

    def test_rows_below_where_the_vertical_rules_end_are_counted(self):
        img = self.img.copy()
        cut = self.ys[12]
        img[cut + 6:, :] = 255                                                # the table's ink ends at the 12th line ...
        for y in (self.ys[14], self.ys[16]):
            cv2.line(img, (0, y), (img.shape[1] - 1, y), 0, 3)               # ... but footer lines go on below it
        edges = [self.ys[i] for i in range(3, 13)] + [self.ys[14], self.ys[16]]
        got = unruled_tail(img, grid_for(self.xs, edges))
        self.assertEqual(got, 2)

    def test_a_tilted_rule_still_counts_as_a_rule(self):
        img = np.full_like(self.img, 255)
        top, bottom = self.ys[3], self.ys[15]
        for x in self.xs:
            cv2.line(img, (x - 3, top), (x + 3, bottom), 0, 1)                 # 6 px of drift over the table: a skewed scan
        for y in self.ys[3:16]:
            cv2.line(img, (self.xs[0] - 3, y), (self.xs[-1] + 3, y), 0, 2)
        self.assertEqual(unruled_tail(img, grid_for(self.xs, self.ys[3:16])), 0)

    def test_rules_that_drift_away_from_the_columns_on_a_curved_scan_still_count(self):
        img = np.full_like(self.img, 255)
        for y0, y1 in zip(self.ys[3:15], self.ys[4:16]):
            drift = int(10 * (y0 - self.ys[3]) / (self.ys[14] - self.ys[3]))       # up to 10 px (a quarter of a row) by the foot
            for x in self.xs:
                cv2.line(img, (x + drift, y0), (x + drift, y1), 0, 2)
            cv2.line(img, (self.xs[0], y0), (self.xs[-1] + 10, y0), 0, 2)
        self.assertEqual(unruled_tail(img, grid_for(self.xs, self.ys[3:16])), 0)

    def test_a_page_without_rules_is_not_judged(self):
        blank = np.full_like(self.img, 255)
        self.assertEqual(unruled_tail(blank, grid_for(self.xs, self.ys[3:15])), 0)


if __name__ == "__main__":
    unittest.main()
