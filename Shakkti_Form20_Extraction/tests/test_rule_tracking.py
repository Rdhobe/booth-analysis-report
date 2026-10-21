import unittest

import cv2
import numpy as np

from form20.ocr import rule_tracked_edges


def ruled_page(rows=14, cols=6, pitch=40, colw=300, x0=100, y0=200, drift=0.0, w=2200):
    """A table whose horizontal rules sink `drift` px per px of x (a tilted or bowed page), vertical rules straight."""
    h = y0 + rows * pitch + 300 + int(drift * (cols * colw))
    img = np.full((h, w), 255, np.uint8)
    xs = [x0 + i * colw for i in range(cols + 1)]
    for r in range(rows + 1):
        pts = np.array([[x, int(y0 + r * pitch + drift * (x - x0))] for x in range(xs[0], xs[-1] + 1, 20)], np.int32)
        cv2.polylines(img, [pts], False, 0, 2)
    for x in xs:
        cv2.line(img, (x, y0), (x, y0 + rows * pitch + int(drift * (cols * colw))), 0, 2)
    return img, xs, [y0 + r * pitch for r in range(rows + 1)]


class RuleTrackingTests(unittest.TestCase):
    def test_edges_follow_rules_that_sink_across_the_page(self):
        img, xs, ys = ruled_page(drift=0.03)                       # 54 px over the six columns: more than a row
        edges = rule_tracked_edges(img, xs, ys, 40)
        self.assertIsNotNone(edges)
        self.assertEqual((len(edges), len(edges[0])), (6, len(ys)))
        first, last = edges[0], edges[-1]
        for r in range(len(ys)):
            self.assertLess(abs(first[r] - ys[r] - 0.03 * 150), 4)                      # each column's rule at its own centre
            self.assertLess(abs(last[r] - ys[r] - 0.03 * (5 * 300 + 150)), 5)
        self.assertGreater(last[3] - first[3], 35)                                      # the drift is carried, row for row

    def test_a_level_page_keeps_the_flat_grid(self):
        img, xs, ys = ruled_page(drift=0.0)
        self.assertIsNone(rule_tracked_edges(img, xs, ys, 40))

    def test_a_slight_tilt_stays_with_the_flat_grid(self):
        img, xs, ys = ruled_page(drift=0.003)                      # 5 px across the page, well under a third of a row
        self.assertIsNone(rule_tracked_edges(img, xs, ys, 40))

    def test_a_missing_rule_keeps_the_neighbouring_columns_place(self):
        img, xs, ys = ruled_page(drift=0.03)
        y_mid = int(ys[6] + 0.03 * (3 * 300 + 150))
        img[y_mid - 4:y_mid + 5, xs[3] + 3:xs[4] - 3] = 255                            # rule 6 is missing in column 3
        edges = rule_tracked_edges(img, xs, ys, 40)
        self.assertIsNotNone(edges)
        self.assertLess(abs(edges[3][6] - edges[2][6]), 20)                             # it carries on from column 2's edge
        self.assertEqual(sorted(edges[3]), edges[3])                                    # and the order is kept


if __name__ == "__main__":
    unittest.main()
