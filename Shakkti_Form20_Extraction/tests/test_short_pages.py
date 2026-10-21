import unittest
from unittest import mock

import cv2
import numpy as np

from form20 import pipeline
from form20.grid import PageLines, detect_lines

HEADER_AND_FIRST_ROW = [200, 255, 344, 383]          # title rule, header block (55, 89), one booth row (39)
TOTAL_ROWS = [491, 633, 741]                          # tall total rows (108, 142, 108)


def last_page(width=2600, height=1500, left=320, right=2430, columns=18):
    img = np.full((height, width), 255, np.uint8)
    ys = HEADER_AND_FIRST_ROW + TOTAL_ROWS
    for y in ys:
        cv2.line(img, (left, y), (right, y), 0, 3)
    for x in np.linspace(left, right, columns):
        cv2.line(img, (int(x), 344), (int(x), ys[-1]), 0, 3)
    return img


def normal_page_lines(left=325, right=2435):
    return PageLines(left=left, right=right, data_edges=list(range(300, 300 + 39 * 27, 39)), pitch=39.0,
                     col_candidates=list(np.linspace(left, right, 18)))


def last_page_with_a_header_rule(width=2600, height=1500, left=320, right=2430, columns=18):
    """The header's own rules are one pitch apart (135, 179) and so are the booth row's (478, 518): both look like a
    one-row table. The booth row, nearest the printed totals, is the real one."""
    img = np.full((height, width), 255, np.uint8)
    ys = [135, 179, 478, 518, 616]
    for y in ys:
        cv2.line(img, (left, y), (right, y), 0, 3)
    for x in np.linspace(left, right, columns):
        cv2.line(img, (int(x), 135), (int(x), ys[-1]), 0, 3)
    return img


class ShortTableTieTests(unittest.TestCase):
    def test_the_booth_row_nearest_the_totals_wins_over_the_header_rules(self):
        pl = detect_lines(last_page_with_a_header_rule(), min_run=1, pitch_hint=40.0)
        self.assertIsNotNone(pl)
        self.assertEqual(len(pl.data_edges), 2)
        self.assertLessEqual(abs(pl.data_edges[0] - 478), 3)
        self.assertLessEqual(abs(pl.data_edges[1] - 518), 3)


class ShortTableDetectionTests(unittest.TestCase):
    def test_default_detector_still_ignores_a_page_with_one_booth_row(self):
        self.assertIsNone(detect_lines(last_page()))

    def test_with_the_file_pitch_a_single_row_is_found_above_the_totals(self):
        pl = detect_lines(last_page(), min_run=1, pitch_hint=39.0)
        self.assertIsNotNone(pl)
        self.assertEqual(pl.data_edges, [344, 383])
        self.assertEqual(pl.total_edges[0], 383)
        self.assertEqual(len(pl.total_edges), 4)                     # three total rows below the booth

    def test_a_page_of_text_without_rules_is_not_taken_for_a_table(self):
        self.assertIsNone(detect_lines(np.full((1500, 2600), 255, np.uint8), min_run=1, pitch_hint=39.0))


class RescueTests(unittest.TestCase):
    def run_rescue(self, page_image, lines):
        msgs = []
        with mock.patch.object(pipeline, "load_page", return_value=(page_image, None)):
            pipeline.rescue_short_pages("x.pdf", lines, msgs.append, "x.pdf")
        return msgs

    def test_a_missing_last_page_is_filled_in(self):
        lines = [normal_page_lines(), normal_page_lines(), None]
        msgs = self.run_rescue(last_page(), lines)
        self.assertIsNotNone(lines[2])
        self.assertEqual(lines[2].data_edges, [344, 383])
        self.assertTrue(any("short table found" in m for m in msgs))

    def test_a_page_whose_table_is_elsewhere_on_the_sheet_is_not_accepted(self):
        lines = [normal_page_lines(left=900, right=2000), normal_page_lines(left=900, right=2000), None]
        self.run_rescue(last_page(), lines)
        self.assertIsNone(lines[2])                                  # edges do not line up with the other pages

    def test_nothing_happens_when_every_page_has_a_table(self):
        lines = [normal_page_lines(), normal_page_lines()]
        self.assertEqual(self.run_rescue(last_page(), lines), [])

    def test_a_single_good_page_is_not_enough_to_judge(self):
        lines = [normal_page_lines(), None]
        self.run_rescue(last_page(), lines)
        self.assertIsNone(lines[1])


if __name__ == "__main__":
    unittest.main()
