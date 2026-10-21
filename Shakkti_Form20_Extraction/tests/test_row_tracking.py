import unittest

import cv2
import numpy as np

from form20.grid import Grid
from form20.ocr import clean_cell, read_cells, slide_uncut, tracked_edges
from tests.test_grid_ocr import synthetic_table


def tilted_page(slope=0.009, blank_col=None):
    """Digits whose baseline sinks `slope` px per px to the right, as on a tilted scan; no ruling lines."""
    img, xs, ys = synthetic_table(rows=12, cols=6, digits=False)
    img[:] = 255
    for r in range(12):
        for c in range(6):
            if c == blank_col:
                continue
            dy = int(slope * (xs[c] + 100 - xs[0]))
            cv2.putText(img, str((r * 7 + c * 3) % 97 + 10), (xs[c] + 100, ys[r] + 28 + dy), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
    return img, xs, ys[:13]


class TrackedEdgesTests(unittest.TestCase):
    def test_edges_follow_a_tilt(self):
        img, xs, ys = tilted_page()
        edges = tracked_edges(img, xs, ys, 40)
        self.assertEqual(len(edges), 6)
        first, last = edges[0][5] - ys[5], edges[5][5] - ys[5]
        self.assertGreaterEqual(last - first, 10)                      # the last column rows sit about 14 px lower
        shifts = [e[5] - ys[5] for e in edges]
        self.assertEqual(shifts, sorted(shifts))                       # and the shift grows steadily across the page

    def test_a_flat_cell_cuts_the_digits_a_tracked_one_keeps_them(self):
        img, xs, ys = tilted_page()
        edges = tracked_edges(img, xs, ys, 40)
        flat = clean_cell(img, xs[5], ys[4], xs[6], ys[5], 3, ref_h=34)[0]
        kept = clean_cell(img, xs[5], edges[5][4], xs[6], edges[5][5], 3, ref_h=34)[0]
        whole = clean_cell(img, xs[0], edges[0][4], xs[1], edges[0][5], 3, ref_h=34)[0]
        self.assertIsNotNone(kept)
        self.assertGreaterEqual(kept.shape[0], 0.95 * whole.shape[0])  # the full digit height
        self.assertTrue(flat is None or flat.shape[0] < 0.8 * whole.shape[0])

    def test_rows_of_different_heights_keep_their_heights(self):
        img, xs, ys = tilted_page(slope=0.0)
        uneven = ys[:9] + [ys[8] + 90, ys[8] + 180]                       # two tall rows (2.25 pitches) at the foot
        for edges in tracked_edges(img, xs, uneven, 40):
            heights = [b - a for a, b in zip(edges, edges[1:])]
            self.assertGreaterEqual(heights[-1], 70)                       # the tall rows stay tall
            self.assertGreaterEqual(heights[-2], 70)

    def test_a_tall_row_is_not_tracked(self):
        img, xs, ys = tilted_page()
        uneven = ys[:9] + [ys[8] + 100, ys[8] + 200]                      # two tall rows at the foot
        edges = tracked_edges(img, xs, uneven, 40)
        for col in (0, 5):                                               # the tall rows keep their flat edges, whatever the tilt
            self.assertLessEqual(abs(edges[col][-1] - uneven[-1]), 1)

    def test_a_row_with_little_ink_does_not_lock_onto_its_neighbour(self):
        img, xs, ys = tilted_page(slope=0.0)
        r = 5
        img[ys[r]:ys[r + 1], :] = 255                                    # row 5 is blank: only its neighbours have digits
        for col in tracked_edges(img, xs, ys, 40):
            for k in (r, r + 1):
                self.assertLessEqual(abs(col[k] - ys[k]), 14)            # its edges stay where the grid put them

    def test_a_blank_first_row_stays_where_the_grid_put_it(self):
        img, xs, ys = tilted_page(slope=0.0)
        img[ys[0]:ys[1], :] = 255                                        # the table's first row has no digits
        for col in tracked_edges(img, xs, ys, 40):
            self.assertLessEqual(abs(col[0] - ys[0]), 4)                 # it keeps its place (a tracked blank row would slide)
            self.assertLessEqual(abs(col[1] - ys[1]), 4)

    def test_a_level_page_keeps_its_edges_exactly(self):
        img, xs, ys = tilted_page(slope=0.0)
        for col in tracked_edges(img, xs, ys, 40):
            self.assertEqual(col, list(ys))                            # no tracking at all

    def test_a_blank_column_takes_its_neighbours_tilt(self):
        img, xs, ys = tilted_page(blank_col=3)
        edges = tracked_edges(img, xs, ys, 40)
        near = sorted([edges[2][5], edges[4][5]])
        self.assertTrue(near[0] - 3 <= edges[3][5] <= near[1] + 3)


class OnlyCutCellsMoveTests(unittest.TestCase):
    def grid(self, xs, ys):
        return Grid(col_edges=xs, data_edges=ys, total_edges=[], header_top=0, left=xs[0], right=xs[-1], pitch=40.0)

    def test_cells_that_fit_are_read_exactly_as_the_flat_grid_reads_them(self):
        import form20.ocr as O
        img, xs, ys = tilted_page(slope=0.0)
        flat_crops, tracked_crops = {}, {}
        for track in (False, True):
            O.TRACK = track
            try:
                tab = read_cells(img, self.grid(xs, ys), ys)
            finally:
                O.TRACK = True
            (tracked_crops if track else flat_crops).update({(r, c): cell.crop for r, row in enumerate(tab) for c, cell in enumerate(row)})
        for key, crop in flat_crops.items():
            other = tracked_crops[key]
            self.assertEqual(crop is None, other is None)
            if crop is not None:
                self.assertTrue((crop == other).all())

    def test_a_cut_cell_is_taken_from_the_tracked_rows(self):
        img, xs, ys = tilted_page(slope=0.009)
        grid = self.grid(xs, ys)
        flat = clean_cell(img, xs[5], ys[4], xs[6], ys[5], 3, ref_h=34)[0]
        tab = read_cells(img, grid, ys)
        crop = tab[4][5].crop
        self.assertIsNotNone(crop)
        self.assertTrue(flat is None or crop.shape[0] > flat.shape[0])


class SlideUncutTests(unittest.TestCase):
    """One column of digits on a white page: row 1 sits 6 px lower than the flat cell (a curved scan), row 2 follows it."""
    def setUp(self):
        self.img = np.full((300, 200), 255, np.uint8)
        cv2.putText(self.img, "42", (60, 140), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)    # ~ y 118..140
        cv2.putText(self.img, "77", (60, 183), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)    # the next row, ~ y 161..183
        self.cell = (20, 100, 180, 140)                                                  # x0, y0, x1, y1 of the flat cell
        self.whole = clean_cell(self.img, 20, 110, 180, 152, 3, ref_h=34)[0]            # the digits with room to spare

    def crop(self):
        return clean_cell(self.img, *self.cell, 3, ref_h=34)

    def test_a_clipped_cell_slides_onto_the_whole_digits_and_only_them(self):
        flat = self.crop()
        x0, y0, x1, y1 = self.cell
        self.assertLess(flat[0].shape[0], self.whole.shape[0])                          # the flat cell does clip them
        got = slide_uncut(self.img, x0, y0, x1, y1, 3, 34, flat, 12)
        self.assertEqual(got[0].shape, self.whole.shape)                                # whole digits, no neighbour merged

    def test_a_crop_that_is_not_clipped_is_returned_as_it_is(self):
        x0, y0, x1, y1 = 20, 110, 180, 152
        crop = clean_cell(self.img, x0, y0, x1, y1, 3, ref_h=34)
        self.assertIs(slide_uncut(self.img, x0, y0, x1, y1, 3, 34, crop, 12), crop)

    def test_digits_clipped_at_both_ends_stay_as_they_are(self):
        x0, y0, x1, y1 = 20, 121, 180, 135                                               # a cell shorter than the digits
        crop = clean_cell(self.img, x0, y0, x1, y1, 3, ref_h=34)
        if crop[0] is not None:
            self.assertIs(slide_uncut(self.img, x0, y0, x1, y1, 3, 34, crop, 12), crop)

    def test_no_slide_within_reach_leaves_the_crop(self):
        flat = self.crop()
        x0, y0, x1, y1 = self.cell
        self.assertIs(slide_uncut(self.img, x0, y0, x1, y1, 3, 34, flat, 4), flat)       # needs ~6 px: out of reach


if __name__ == "__main__":
    unittest.main()
