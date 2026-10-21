import unittest

from form20.ocr import CellRead
from form20.pipeline import _is_numbering_row


def cells(texts):
    return [CellRead(reads={"A": t, "B": t}, confs={"A": 90.0, "B": 90.0}) for t in texts]


class NumberingRowTests(unittest.TestCase):
    def test_partial_numbering_over_the_last_columns(self):
        self.assertTrue(_is_numbering_row(cells(["", "", "", "", "", "", "", "10", "11", "12", "13", ""])))

    def test_numbering_with_a_gap(self):
        self.assertTrue(_is_numbering_row(cells(["", "", "", "", "", "", "", "", "10", "", "12", "", ""])))

    def test_full_numbering_row(self):
        self.assertTrue(_is_numbering_row(cells(["2", "3", "4", "5", "6", "7"])))

    def test_real_booth_rows_are_not_numbering_rows(self):
        self.assertFalse(_is_numbering_row(cells(["306", "5", "", "", "", "", "", "", "334", "", "", "334", ""])))
        self.assertFalse(_is_numbering_row(cells(["23", "306", "5", "", "", "", "", "", "334", "", "", "334", ""])))

    def test_a_single_number_is_not_enough(self):
        self.assertFalse(_is_numbering_row(cells(["", "", "9", "", ""])))

    def test_large_values_are_never_column_numbers(self):
        self.assertFalse(_is_numbering_row(cells(["", "", "", "", "", "", "", "", "", "100", "101", "102"])))


if __name__ == "__main__":
    unittest.main()
