import unittest
from types import SimpleNamespace

from form20.grid import apply_template, page_registration

TEMPLATE = [0.0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0]


def page(left=100, right=1100, columns=TEMPLATE, scale=1.0, offset=0.0):
    """A page whose detected column rules are the template mapped through x -> scale * x + offset."""
    width = right - left
    cands = [scale * (left + u * width) + offset for u in columns]
    return SimpleNamespace(left=left, right=right, col_candidates=cands, data_edges=[0, 10], total_edges=[],
                           header_top=0, pitch=10.0, row_lines=[])


class PageRegistrationTests(unittest.TestCase):
    def test_a_page_that_is_already_registered_is_left_alone(self):
        self.assertEqual(page_registration(page(), TEMPLATE), (1.0, 0.0))

    def test_small_drift_is_left_to_snapping(self):
        self.assertEqual(page_registration(page(offset=3), TEMPLATE), (1.0, 0.0))

    def test_a_shift_larger_than_snapping_is_corrected(self):
        a, b = page_registration(page(offset=20), TEMPLATE)
        self.assertAlmostEqual(a, 1.0, places=3)
        self.assertAlmostEqual(b, 20.0, delta=1.0)

    def test_a_stretched_page_is_corrected(self):
        a, b = page_registration(page(scale=0.97, offset=30), TEMPLATE)
        self.assertAlmostEqual(a, 0.97, places=2)
        self.assertAlmostEqual(b, 30.0, delta=2.0)

    def test_too_few_matching_rules_leave_the_page_alone(self):
        pl = page(offset=20)
        pl.col_candidates = pl.col_candidates[:3]
        self.assertEqual(page_registration(pl, TEMPLATE), (1.0, 0.0))

    def test_rules_unrelated_to_the_template_are_ignored(self):
        pl = page(columns=[0.03, 0.15, 0.27, 0.42, 0.58, 0.72, 0.9])
        self.assertEqual(page_registration(pl, TEMPLATE), (1.0, 0.0))

    def test_apply_template_puts_columns_on_the_detected_rules(self):
        pl = page(offset=20)
        grid = apply_template(pl, TEMPLATE)
        self.assertEqual(grid.col_edges, [round(c) for c in pl.col_candidates])

    def test_apply_template_without_registration_error_is_unchanged(self):
        pl = page()
        self.assertEqual(apply_template(pl, TEMPLATE).col_edges, [round(c) for c in pl.col_candidates])


if __name__ == "__main__":
    unittest.main()
