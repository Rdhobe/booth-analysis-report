import unittest

import cv2
import numpy as np

from form20.grid import PageLines
from form20.inkcolumns import choose_columns, cut_share, ink_template, page_tokens

LEFT, RIGHT = 200, 2400
CENTRES = [260, 560, 860, 1010, 1160, 1310, 1460, 1610, 1760, 1910, 2060, 2210, 2340]    # x of each column's digits
ROWS, PITCH, Y0 = 24, 44, 400


def page(vertical_rules=False, names=False, seed=0):
    """A table with horizontal rules only: digits centred on CENTRES, optionally text-like blobs between 300 and 800."""
    rng = np.random.RandomState(seed)
    img = np.full((Y0 + ROWS * PITCH + 200, 2600), 255, np.uint8)
    for r in range(ROWS + 1):
        cv2.line(img, (LEFT, Y0 + r * PITCH), (RIGHT, Y0 + r * PITCH), 0, 2)
    for r in range(ROWS):
        for c in CENTRES:
            text = str(int(rng.randint(0, 999)))
            size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)[0]
            cv2.putText(img, text, (c - size[0] // 2, Y0 + r * PITCH + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
        if names:
            x = 300 + int(rng.randint(0, 300))                  # a name: a few letter-sized blobs at a random place
            for k in range(int(rng.randint(3, 8))):
                cv2.rectangle(img, (x + k * 24, Y0 + r * PITCH + 14), (x + k * 24 + 14, Y0 + r * PITCH + 34), 0, 2)
    pl = PageLines(left=LEFT, right=RIGHT, data_edges=[Y0 + r * PITCH for r in range(ROWS + 1)], pitch=float(PITCH),
                   col_candidates=[])
    return img, pl


class InkColumnTests(unittest.TestCase):
    def test_numbers_are_found_by_row_and_position(self):
        img, pl = page()
        tokens = page_tokens(img, pl)
        self.assertEqual(len(tokens), ROWS * len(CENTRES))
        want = [(c - LEFT) / (RIGHT - LEFT) for c in CENTRES]
        for u, row, _, _ in tokens:
            self.assertLess(min(abs(u - w) for w in want), 0.012)       # each number sits on its column
            self.assertTrue(0 <= row < ROWS)

    def test_columns_are_found_without_any_vertical_rule(self):
        pages = [page(seed=s) for s in range(3)]
        template = ink_template([page_tokens(img, pl) for img, pl in pages], {len(CENTRES)})
        self.assertIsNotNone(template)
        self.assertEqual(len(template) - 1, len(CENTRES))
        self.assertEqual((template[0], template[-1]), (0.0, 1.0))
        # every column's digits lie inside its cell
        for k, c in enumerate(CENTRES):
            u = (c - LEFT) / (RIGHT - LEFT)
            self.assertTrue(template[k] < u < template[k + 1])

    def test_text_in_a_name_column_does_not_add_columns(self):
        pages = [page(names=True, seed=s) for s in range(3)]
        template = ink_template([page_tokens(img, pl) for img, pl in pages], {len(CENTRES)})
        self.assertIsNotNone(template)
        self.assertEqual(len(template) - 1, len(CENTRES))

    def test_a_template_with_edges_on_the_digits_cuts_many_numbers(self):
        pages = [page(seed=s) for s in range(3)]
        tokens = [page_tokens(img, pl) for img, pl in pages]
        good = ink_template(tokens, {len(CENTRES)})
        shifted = [0.0] + [u + 0.03 for u in good[1:-1]] + [1.0]            # every inner edge moved onto the digits
        self.assertLess(cut_share(good, tokens), 0.01)
        self.assertGreater(cut_share(shifted, tokens), 0.3)

    def test_good_line_columns_are_kept(self):
        pages = [page(seed=s) for s in range(3)]
        tokens = [page_tokens(img, pl) for img, pl in pages]
        good = ink_template(tokens, {len(CENTRES)})
        template, from_digits, why = choose_columns(tokens, good, {len(CENTRES)})
        self.assertEqual((template, from_digits, why), (good, False, ""))

    def test_line_columns_that_cut_the_numbers_are_replaced_by_the_digits_columns(self):
        pages = [page(seed=s) for s in range(3)]
        tokens = [page_tokens(img, pl) for img, pl in pages]
        good = ink_template(tokens, {len(CENTRES)})
        off = [0.0] + [u + 0.03 for u in good[1:-1]] + [1.0]               # right count, edges on the digits
        template, from_digits, why = choose_columns(tokens, off, {len(CENTRES)})
        self.assertTrue(from_digits)
        self.assertLess(cut_share(template, tokens), 0.01)
        self.assertIn("cut", why)

    def test_a_wrong_column_count_from_the_lines_is_replaced_even_without_cuts(self):
        pages = [page(seed=s) for s in range(3)]
        tokens = [page_tokens(img, pl) for img, pl in pages]
        few = [0.0, 0.5, 1.0]                                              # two columns: not an allowed count
        template, from_digits, _ = choose_columns(tokens, few, {len(CENTRES)})
        self.assertTrue(from_digits)
        self.assertEqual(len(template) - 1, len(CENTRES))

    def test_nothing_changes_when_the_digits_give_no_columns(self):
        img, pl = page()
        tokens = [page_tokens(img, pl)]
        few = [0.0, 0.5, 1.0]
        pl.data_edges = pl.data_edges[:5]
        self.assertEqual(choose_columns([page_tokens(img, pl)], few, {len(CENTRES)}), (few, False, ""))

    def test_a_column_count_the_official_data_does_not_allow_gives_no_template(self):
        pages = [page(seed=s) for s in range(3)]
        self.assertIsNone(ink_template([page_tokens(img, pl) for img, pl in pages], {5, 6}))

    def test_too_few_rows_give_no_template(self):
        img, pl = page()
        pl.data_edges = pl.data_edges[:6]
        self.assertIsNone(ink_template([page_tokens(img, pl)], {len(CENTRES)}))


if __name__ == "__main__":
    unittest.main()


class PreferDigitColumnsTests(unittest.TestCase):
    def test_a_probe_that_fits_nothing_with_the_lines_but_well_with_the_digits_switches(self):
        from form20.pipeline import prefer_digit_columns
        self.assertTrue(prefer_digit_columns(0.0, 0.9))
        self.assertTrue(prefer_digit_columns(0.3, 0.8))

    def test_a_layout_found_with_the_lines_is_never_given_up(self):
        from form20.pipeline import prefer_digit_columns
        self.assertFalse(prefer_digit_columns(0.5, 1.0))      # the lines fit half the rows: leave them
        self.assertFalse(prefer_digit_columns(0.9, 1.0))
        self.assertFalse(prefer_digit_columns(0.95, 0.95))

    def test_the_digits_must_fit_clearly_better_and_well_in_themselves(self):
        from form20.pipeline import prefer_digit_columns
        self.assertFalse(prefer_digit_columns(0.0, 0.5))      # not good enough in itself
        self.assertFalse(prefer_digit_columns(0.45, 0.6))     # not clearly better (needs +0.2)
