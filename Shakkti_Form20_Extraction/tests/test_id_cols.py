import unittest

from form20.ocr import CellRead
from form20.pipeline import choose_id_cols
from form20.validate import plain_reading, read_as_printed


def cell(text, conf=90.0):
    return CellRead(reads={"A": text, "B": text}, confs={"A": conf, "B": conf})


def votes(i):
    """3 candidates | valid rejected nota total tendered - a consistent row that varies with i."""
    c = [5 + i, 3, 2 + i % 4]
    valid = sum(c)
    return c + [valid, i % 3, 1, valid + i % 3 + 1, 0]


def sheet(n_ids, n_rows=12, junk=False):
    """Probe table for a sheet with n_ids leading identifier columns (the extras are unreadable names/numbers)."""
    table = []
    for i in range(n_rows):
        ids = [str(i + 1)] + ([""] if n_ids == 2 else ["", ""] if n_ids == 3 else [])
        v = votes(i)
        if junk:
            v = [(x * 7 + 3) % 40 for x in v]          # breaks both identities
        table.append([cell(t) for t in ids + [str(x) for x in v]])
    return table


class PlainReadingTests(unittest.TestCase):
    def test_consistent_row_is_returned(self):
        self.assertEqual(plain_reading([cell(str(x)) for x in votes(0)], 3), votes(0))

    def test_inconsistent_row_is_none(self):
        v = votes(0)
        v[3] += 1
        self.assertIsNone(plain_reading([cell(str(x)) for x in v], 3))

    def test_blank_rejected_is_solved_only_where_allowed(self):
        cells = [cell(str(x)) for x in votes(1)]
        cells[4] = cell("")                      # rejected votes printed as an empty cell
        self.assertIsNone(plain_reading(cells, 3))
        self.assertEqual(plain_reading(cells, 3, blank_ok=(4,)), votes(1))

    def test_blank_candidate_cell_is_never_accepted_by_the_totals_allowance(self):
        cells = [cell(str(x)) for x in votes(1)]
        cells[0] = cell("")
        self.assertIsNone(plain_reading(cells, 3, blank_ok=(4, 5)))

    def test_blank_tendered_counts_as_zero(self):
        cells = [cell(str(x)) for x in votes(0)]
        cells[-1] = cell("")
        self.assertEqual(plain_reading(cells, 3), votes(0))


class BlankZeroTests(unittest.TestCase):
    def test_a_few_unread_candidate_cells_count_as_zero_in_a_probe(self):
        cells = [cell(str(x)) for x in votes(0)]          # 3 candidates: 5, 3, 2 ...
        cells[1] = cell("")                               # the 3 became an unread cell: sum no longer matches
        self.assertIsNone(plain_reading(cells, 3, blank_zero=2))
        zero = votes(0)
        zero[1] = 0
        zero[3] = sum(zero[:3])
        zero[6] = zero[3] + zero[4] + zero[5]
        cells = [cell(str(x)) for x in zero]
        cells[1] = cell("")                               # a printed zero that OCR left blank
        self.assertIsNone(plain_reading(cells, 3))        # not accepted unless the probe allows it
        self.assertEqual(plain_reading(cells, 3, blank_zero=2)[1], 0)

    def test_digits_that_cannot_be_votes_are_not_a_zero(self):
        # a polling-station column read as a candidate holds '5000' in some rows: no booth has that many votes, so it
        # is not an unread zero - only an empty cell is one
        zero = votes(0)
        zero[1] = 0
        zero[3] = sum(zero[:3])
        zero[6] = zero[3] + zero[4] + zero[5]
        cells = [cell(str(x)) for x in zero]
        cells[1] = cell("")
        self.assertEqual(plain_reading(cells, 3, blank_zero=2)[1], 0)
        cells[1] = cell("5000")
        self.assertIsNone(plain_reading(cells, 3, blank_zero=2))

    def test_text_column_is_never_zero_filled(self):
        zero = votes(0)
        zero[1] = 0
        zero[3] = sum(zero[:3])
        zero[6] = zero[3] + zero[4] + zero[5]
        cells = [cell(str(x)) for x in zero]
        cells[1] = cell("")
        self.assertIsNone(plain_reading(cells, 3, blank_zero=2, no_zero={1}))


class ChooseIdColsTests(unittest.TestCase):
    def test_second_identifier_column_is_found_when_language_default_says_one(self):
        n_cols = 2 + 8
        got, share = choose_id_cols(sheet(2), n_cols, default=1)
        self.assertEqual(got, 2)
        self.assertGreater(share[2], 0.9)
        self.assertEqual(share[1], 0.0)

    def test_single_identifier_column_is_found_when_language_default_says_two(self):
        got, _ = choose_id_cols(sheet(1), 1 + 8, default=2)
        self.assertEqual(got, 1)

    def test_default_is_kept_when_it_is_already_right(self):
        got, _ = choose_id_cols(sheet(2), 2 + 8, default=2)
        self.assertEqual(got, 2)

    def test_default_is_kept_when_nothing_is_consistent(self):
        got, share = choose_id_cols(sheet(2, junk=True), 2 + 8, default=1)
        self.assertEqual(got, 1)
        self.assertTrue(all(v < 0.3 for v in share.values()))

    def test_blank_rejected_column_does_not_hide_the_right_choice(self):
        table = sheet(2)
        for row in table:
            row[2 + 4] = cell("")                # sheet prints zero rejected votes as an empty cell
        got, share = choose_id_cols(table, 2 + 8, default=1)
        self.assertEqual(got, 2)
        self.assertEqual(share[1], 0.0)

    def test_empty_probe_keeps_default(self):
        self.assertEqual(choose_id_cols([], 10, default=2), (2, {}))


if __name__ == "__main__":
    unittest.main()


class ReadAsPrintedTests(unittest.TestCase):
    class Row:
        def __init__(self, status, changed=(), primary=()):
            self.status, self.changed, self.primary = status, list(changed), list(primary)

    NC = 3

    def test_ok_row(self):
        self.assertTrue(read_as_printed(self.Row("OK"), self.NC))

    def test_blank_rejected_solved_from_the_equations_counts(self):
        primary = ["5", "3", "2", "10", "", "1", "11", "0"]
        self.assertTrue(read_as_printed(self.Row("AUTO_CORRECTED", [4], primary), self.NC))

    def test_repaired_vote_cell_does_not_count(self):
        primary = ["5", "13", "2", "10", "0", "1", "11", "0"]
        self.assertFalse(read_as_printed(self.Row("AUTO_CORRECTED", [1], primary), self.NC))
        self.assertFalse(read_as_printed(self.Row("REVIEW"), self.NC))
