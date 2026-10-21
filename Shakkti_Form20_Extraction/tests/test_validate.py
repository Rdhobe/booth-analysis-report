import unittest

from form20.ocr import CellRead
from form20.validate import solve_row


def cell(a, b=None, conf=90.0):
    b = a if b is None else b
    return CellRead(reads={"A": a, "B": b}, confs={"A": conf, "B": conf})


def row(*texts, **kw):
    return [cell(t, **kw) for t in texts]


NC = 3   # three candidates; layout: c1 c2 c3 | valid rejected nota total tendered


class SolveRowTests(unittest.TestCase):
    def test_consistent_row_is_ok(self):
        r = solve_row(row("5", "3", "2", "10", "0", "1", "11", "0"), NC)
        self.assertEqual(r.status, "OK")
        self.assertEqual(r.values, [5, 3, 2, 10, 0, 1, 11, 0])

    def test_blank_cell_is_solved_from_the_sum(self):
        r = solve_row(row("5", "", "2", "10", "0", "1", "11", "0"), NC)
        self.assertEqual(r.status, "AUTO_CORRECTED")
        self.assertEqual(r.values[1], 3)

    def test_ruling_line_residue_leading_one_is_stripped(self):
        r = solve_row(row("5", "13", "2", "10", "0", "1", "11", "0"), NC)
        self.assertEqual(r.values[1], 3)
        self.assertEqual(r.status, "AUTO_CORRECTED")

    def test_trailing_residue_one_is_stripped(self):
        r = solve_row(row("5", "31", "2", "10", "0", "1", "11", "0"), NC)
        self.assertEqual(r.values[1], 3)

    def test_other_variant_reading_is_used_when_it_satisfies_the_arithmetic(self):
        cells = row("5", "3", "2", "10", "0", "1", "11", "0")
        cells[0] = CellRead(reads={"A": "6", "B": "5"}, confs={"A": 80.0, "B": 80.0})
        r = solve_row(cells, NC)
        self.assertEqual(r.values[0], 5)

    def test_unfixable_row_goes_to_review(self):
        r = solve_row(row("5", "3", "2", "10", "0", "1", "99", "0"), NC)
        # a total of 99 can be solved by treating it as unknown, so check a harder case
        r = solve_row(row("", "", "2", "10", "0", "1", "11", "0"), NC)
        self.assertEqual(r.status, "REVIEW")

    def test_low_confidence_cell_is_the_one_that_changes(self):
        cells = row("5", "3", "2", "10", "0", "1", "11", "0")
        # valid total is wrong by 1 (read 11 instead of 10): either c1..c3 or valid could be 'the' error
        cells[3] = CellRead(reads={"A": "11", "B": "11"}, confs={"A": 20.0, "B": 20.0})
        r = solve_row(cells, NC)
        self.assertEqual(r.values[3], 10)


if __name__ == "__main__":
    unittest.main()
