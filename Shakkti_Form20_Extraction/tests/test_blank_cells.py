import unittest
from types import SimpleNamespace

from form20.ocr import CellRead
from form20.validate import read_as_printed, solve_row


def cell(a, b=None, conf=90.0):
    b = a if b is None else b
    return CellRead(reads={"A": a, "B": b}, confs={"A": conf, "B": conf})


def row(*texts):
    return [cell(t) for t in texts]


NC = 4     # four candidates; layout: c1 c2 c3 c4 | valid rejected nota total tendered


class BlankCandidateTests(unittest.TestCase):
    def test_several_blank_candidates_are_zeros_when_the_arithmetic_agrees(self):
        r = solve_row(row("245", "102", "", "", "347", "0", "2", "349", "0"), NC)     # two printed zeros left blank
        self.assertEqual(r.status, "AUTO_CORRECTED")
        self.assertEqual(r.values[:4], [245, 102, 0, 0])

    def test_a_single_blank_candidate_is_still_solved_from_the_equations(self):
        r = solve_row(row("245", "102", "", "4", "351", "0", "2", "353", "0"), NC)
        self.assertEqual(r.status, "AUTO_CORRECTED")
        self.assertEqual(r.values[2], 0)

    def test_a_blank_that_hides_a_nonzero_digit_is_solved_when_it_is_the_only_one(self):
        r = solve_row(row("245", "102", "", "1", "352", "0", "2", "354", "0"), NC)
        self.assertEqual(r.values[2], 4)

    def test_two_blanks_hiding_a_nonzero_digit_are_flagged_not_guessed(self):
        r = solve_row(row("245", "102", "", "", "351", "0", "2", "353", "0"), NC)     # one of the two blanks is a 4
        self.assertEqual(r.status, "REVIEW")                                          # ambiguous: do not guess


class NeuralVariantTests(unittest.TestCase):
    def test_a_confident_neural_read_becomes_the_primary_reading(self):
        c = CellRead(reads={"A": "6", "B": "6", "N": "5"}, confs={"A": 80.0, "B": 80.0, "N": 97.0})
        self.assertEqual((c.primary_variant, c.text), ("N", "5"))
        self.assertEqual(c.ordered_reads()[0], "5")
        self.assertIn("6", c.ordered_reads())            # Tesseract's reading stays available to the solver

    def test_an_unsure_neural_read_is_only_an_alternative(self):
        c = CellRead(reads={"A": "6", "B": "6", "N": "5"}, confs={"A": 80.0, "B": 80.0, "N": 40.0})
        self.assertEqual(c.text, "6")
        self.assertIn("5", c.ordered_reads())

    def test_neural_read_fills_a_cell_both_tesseract_variants_left_blank(self):
        c = CellRead(reads={"A": "", "B": "", "N": "4"}, confs={"A": 0.0, "B": 0.0, "N": 60.0})
        self.assertEqual(c.text, "")                     # not confident enough to be primary ...
        self.assertIn("4", c.ordered_reads())            # ... but the solver can use it


class ReadAsPrintedBlankTests(unittest.TestCase):
    def test_a_blank_that_became_zero_counts_as_read_as_printed(self):
        r = SimpleNamespace(status="AUTO_CORRECTED", changed=[2], primary=["245", "102", "", "0", "347", "0", "2", "349", "0"],
                            values=[245, 102, 0, 0, 347, 0, 2, 349, 0])
        self.assertTrue(read_as_printed(r, NC))

    def test_a_blank_filled_with_a_nonzero_value_does_not_count(self):
        r = SimpleNamespace(status="AUTO_CORRECTED", changed=[2], primary=["245", "102", "", "1", "352", "0", "2", "354", "0"],
                            values=[245, 102, 4, 1, 352, 0, 2, 354, 0])
        self.assertFalse(read_as_printed(r, NC))


if __name__ == "__main__":
    unittest.main()
