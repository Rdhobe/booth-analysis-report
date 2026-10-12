import unittest

from form20.pipeline import multi_fix


def mv(cost, row, delta, tag=None):
    return (cost, row, tuple(delta), tag or f"r{row}")


class MultiFixTests(unittest.TestCase):
    # six uncertain rows, two alternative readings each; the deficit is the sum of three specific corrections
    MOVES = [mv(1.0, 0, (10, -10)), mv(1.2, 0, (3, 0)),
             mv(0.8, 1, (0, 20)), mv(1.1, 1, (-5, 5)),
             mv(0.9, 2, (7, 7)), mv(1.0, 2, (1, 2)),
             mv(1.0, 3, (4, 1)), mv(1.3, 3, (2, 9)),
             mv(0.7, 4, (-6, 0)), mv(1.4, 4, (0, 8)),
             mv(1.0, 5, (5, 5)), mv(1.1, 5, (9, -2))]

    def test_three_corrections_in_different_rows_are_found_together(self):
        target = (10 + 0 + 7, -10 + 20 + 7)          # row 0 first alt, row 1 first alt, row 2 first alt
        got = multi_fix(self.MOVES, target)
        self.assertIsInstance(got, list)
        self.assertEqual(sorted(m[3] for m in got), ["r0", "r1", "r2"])
        self.assertEqual([m[2] for m in sorted(got, key=lambda m: m[1])], [(10, -10), (0, 20), (7, 7)])

    def test_no_combination_gives_none(self):
        self.assertIsNone(multi_fix(self.MOVES, (1000, 1000)))

    def test_two_equally_cheap_explanations_are_reported_as_ambiguous(self):
        moves = [mv(1.0, 0, (5, 0)), mv(1.0, 1, (5, 0)), mv(1.0, 2, (0, 3)), mv(1.0, 3, (0, 3))]
        self.assertEqual(multi_fix(moves, (5, 3)), "ambiguous")        # row 0 or 1, and row 2 or 3

    def test_a_clearly_cheaper_explanation_wins(self):
        moves = [mv(0.5, 0, (5, 0)), mv(2.0, 1, (5, 0)), mv(0.5, 2, (0, 3)), mv(2.5, 3, (0, 3))]
        got = multi_fix(moves, (5, 3))
        self.assertEqual(sorted(m[1] for m in got), [0, 2])

    def test_at_most_one_correction_per_row(self):
        moves = [mv(1.0, 0, (4, 0)), mv(1.0, 0, (6, 0)), mv(1.0, 1, (0, 1)), mv(1.0, 2, (0, 0.5))]
        self.assertIsNone(multi_fix(moves, (10, 0)))                   # 4 + 6 would need two corrections in row 0

    def test_more_than_two_corrections(self):
        moves = [mv(1.0 + i * 0.01, i, (1 << i, 0)) for i in range(7)]  # distinct powers of two: unique subset sums
        target = ((1 << 1) + (1 << 3) + (1 << 4) + (1 << 6), 0)
        got = multi_fix(moves, target)
        self.assertEqual(sorted(m[1] for m in got), [1, 3, 4, 6])


if __name__ == "__main__":
    unittest.main()
