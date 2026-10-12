import unittest
from types import SimpleNamespace

from form20.rescue import fits_shortfall, plan_missing_rows, rescue_edges, shortfall, typical_rows
from tests.test_grid_ocr import synthetic_table


def page(first_serial, count):
    return [{"serial": first_serial + i} for i in range(count)]


class PlanTests(unittest.TestCase):
    def test_typical_rows_ignore_first_and_last_page(self):
        self.assertEqual(typical_rows([9, 12, 12, 11, 12, 3]), 12)
        self.assertIsNone(typical_rows([9, 12, 3]))

    def test_serial_jump_above_a_short_page(self):
        pages = [page(1, 9), page(10, 12), page(22, 12), page(40, 6), page(46, 12), page(58, 12), page(70, 3)]
        plan, unknown = plan_missing_rows(pages)
        self.assertEqual(plan, {3: (6, 0)})            # serials 34..39 are missing above the 6 rows of page 3
        self.assertEqual(unknown, {})

    def test_serial_jump_below_a_short_page(self):
        pages = [page(1, 9), page(10, 12), page(22, 12), page(34, 6), page(46, 12), page(58, 12), page(70, 3)]
        plan, unknown = plan_missing_rows(pages)
        self.assertEqual(plan, {3: (0, 6)})            # the 6 rows end at serial 39, the next page starts at 46

    def test_one_jump_shared_by_two_short_pages(self):
        pages = [page(1, 9), page(10, 12), page(22, 11), page(36, 11), page(47, 12), page(59, 12), page(71, 3)]
        plan, unknown = plan_missing_rows(pages)
        self.assertEqual(plan, {2: (0, 1), 3: (1, 0)})  # serials 33 and 34 are missing, one for each page

    def test_short_page_without_a_serial_jump_has_an_unknown_end(self):
        pages = [page(1, 9), page(10, 12), page(22, 10), page(32, 12), page(44, 12), page(56, 3)]
        plan, unknown = plan_missing_rows(pages)
        self.assertEqual((plan, unknown), ({}, {2: 2}))

    def test_complete_file_needs_no_rescue(self):
        pages = [page(1, 9), page(10, 12), page(22, 12), page(34, 12), page(46, 3)]
        self.assertEqual(plan_missing_rows(pages), ({}, {}))


class RescueEdgesTests(unittest.TestCase):
    def assertEdges(self, got, want, tol=4):
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want):
            self.assertLessEqual(abs(g - w), tol)

    def setUp(self):
        self.img, self.xs, self.ys = synthetic_table(rows=20, cols=6, digits=True)

    def grid(self, first, last):
        return SimpleNamespace(col_edges=self.xs, data_edges=self.ys[first:last + 1])

    def test_rows_found_above_and_below_by_the_known_counts(self):
        above, below = rescue_edges(self.img, self.grid(7, 13), self.ys, 1, 7, 6, 0)
        self.assertEdges(above, self.ys[0:7])
        self.assertEdges(below, self.ys[14:20])

    def test_unknown_end_goes_below_first(self):
        above, below = rescue_edges(self.img, self.grid(0, 12), self.ys, 1, 0, 0, 8)
        self.assertEqual(above, [])
        self.assertEdges(below, self.ys[13:21])

    def test_rows_with_no_serial_evidence_are_never_looked_for_above(self):
        above, below = rescue_edges(self.img, self.grid(12, 20), self.ys, 1, 0, 0, 3)
        self.assertEqual((above, below), ([], []))                    # nothing below, and above is the header's side

    def test_rows_that_drift_down_the_page_are_followed(self):
        import cv2
        img, xs, ys = synthetic_table(rows=20, cols=6, digits=False)
        img[:] = 255                                              # no ruling lines at all, and the rows creep downwards
        drift = lambda r: ys[r] + 2 * r                           # noqa: E731 - 2 px per row
        for r in range(20):
            for c in range(6):
                cv2.putText(img, str((r * 7 + c * 3) % 97), (xs[c] + 100, drift(r) + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
        grid = SimpleNamespace(col_edges=xs, data_edges=[drift(r) for r in range(0, 6)])
        _, below = rescue_edges(img, grid, [], 1, 0, 14, 0)
        self.assertEqual(len(below), 14)
        for k, y in enumerate(below):                              # without following, 14 rows would be 28 px out
            self.assertLessEqual(abs(y - drift(6 + k)), 12)

    def test_rows_a_side_cannot_supply_are_taken_from_the_other(self):
        # twelve rows are wanted "below", but only 8 rows exist below; the other 4 must be above
        above, below = rescue_edges(self.img, self.grid(4, 12), self.ys, 1, 0, 12, 0)
        self.assertEqual((len(above), len(below)), (4, 8))
        self.assertEdges(above, self.ys[0:4])

    def test_bands_without_digits_are_never_added(self):
        above, below = rescue_edges(self.img, self.grid(0, 20), self.ys, 1, 4, 4, 0)    # the page has no more rows
        self.assertEqual((above, below), ([], []))


class ShortfallTests(unittest.TestCase):
    ROWS = [[100, 40, 5], [90, 35, 3], [110, 30, 4]]            # candidate columns of three booths

    def test_what_the_rows_lack_against_the_official_totals(self):
        missing = shortfall(self.ROWS, [320, 110, 15])           # official: column 0 +20, column 1 +5, column 2 +3
        self.assertEqual(missing, {0: 20, 1: 5, 2: 3})

    def test_columns_are_paired_by_rank_not_by_position(self):
        missing = shortfall(self.ROWS, [15, 320, 110])           # the same totals in another order
        self.assertEqual(missing, {0: 20, 1: 5, 2: 3})

    def test_totals_far_from_the_sheet_give_no_answer(self):
        self.assertIsNone(shortfall(self.ROWS, [3200, 110, 15]))

    def test_a_row_must_not_overshoot_what_is_missing(self):
        missing = {0: 20, 1: 5, 2: 3}
        self.assertTrue(fits_shortfall([18, 5, 2], missing))
        self.assertTrue(fits_shortfall([24, 5, 3], missing))        # within the tolerance of a misread digit
        self.assertFalse(fits_shortfall([300, 120, 9], missing))    # a totals row


if __name__ == "__main__":
    unittest.main()
