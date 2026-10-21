import unittest
from types import SimpleNamespace

from form20.ocr import CellRead
from form20.pipeline import _fill_single_unknowns
from form20.validate import MAX_CELL_VOTES, RowResult, cell_alternatives, solve_row


def cell(text, conf=90.0):
    return CellRead(reads={"A": text, "B": text}, confs={"A": conf, "B": conf})


class CapTests(unittest.TestCase):
    def test_an_impossible_vote_count_is_never_offered(self):
        values = [v for v, _ in cell_alternatives(cell("4389799"))]
        self.assertTrue(all(v <= MAX_CELL_VOTES for v in values))

    def test_a_stray_leading_digit_is_stripped(self):
        values = [v for v, _ in cell_alternatives(cell("3131"))]
        self.assertIn(131, values)                 # 3131 is impossible; 131 and 313 are the likely readings
        self.assertNotIn(3131, values)

    def test_a_row_with_a_stray_digit_in_one_cell_is_repaired(self):
        # 3 candidates 131 | 200 | 50 -> valid 381, rejected 0, NOTA 4, total 385, tendered 0; first cell read as 3131
        r = solve_row([cell(t) for t in ("3131", "200", "50", "381", "0", "4", "385", "0")], 3)
        self.assertEqual(r.values[:4], [131, 200, 50, 381])
        self.assertEqual(r.status, "AUTO_CORRECTED")

    def test_ordinary_values_are_untouched(self):
        self.assertEqual([v for v, _ in cell_alternatives(cell("1400"))][0], 1400)


def booth(values, status="OK"):
    return SimpleNamespace(values=list(values), status=status, notes=[])


class FillTests(unittest.TestCase):
    # 2 candidates | valid rejected NOTA total tendered
    def res(self, rows, target):
        return SimpleNamespace(n_cands=2, rows=rows, totals={"TOTAL_EVM": RowResult(values=target, status="OK")})

    def test_the_only_unreadable_cell_in_a_column_is_filled_from_the_total(self):
        rows = [booth([100, 50, 150, 0, 2, 152, 0]), booth([None, 40, 120, 0, 1, 121, 0], "REVIEW"),
                booth([90, 30, 120, 0, 3, 123, 0])]
        r = self.res(rows, [100 + 80 + 90, 120, 390 + 0, None, 6, None, None])   # column 0 target 270 -> the blank is 80
        r.totals["TOTAL_EVM"].values = [270, 120, 390, None, 6, None, None]
        _fill_single_unknowns(r)
        self.assertEqual(rows[1].values[0], 80)
        self.assertEqual(rows[1].status, "AUTO_CORRECTED")

    def test_a_fill_that_breaks_the_rows_own_arithmetic_is_refused(self):
        rows = [booth([100, 50, 150, 0, 2, 152, 0]), booth([None, 40, 120, 0, 1, 121, 0], "REVIEW")]
        r = self.res(rows, [100 + 77, 90, 270, None, 3, None, None])           # would give 77, but 77 + 40 != 120
        _fill_single_unknowns(r)
        self.assertIsNone(rows[1].values[0])
        self.assertEqual(rows[1].status, "REVIEW")

    def test_two_unreadable_cells_in_one_column_are_not_guessed(self):
        rows = [booth([None, 50, 150, 0, 2, 152, 0], "REVIEW"), booth([None, 40, 120, 0, 1, 121, 0], "REVIEW")]
        r = self.res(rows, [180, 90, 270, None, 3, None, None])
        _fill_single_unknowns(r)
        self.assertIsNone(rows[0].values[0])
        self.assertIsNone(rows[1].values[0])

    def test_an_impossible_fill_is_refused(self):
        rows = [booth([100, 50, 150, 0, 2, 152, 0]), booth([None, 40, 120, 0, 1, 121, 0], "REVIEW")]
        r = self.res(rows, [100 + 5000, 90, 270, None, 3, None, None])
        _fill_single_unknowns(r)
        self.assertIsNone(rows[1].values[0])


if __name__ == "__main__":
    unittest.main()
