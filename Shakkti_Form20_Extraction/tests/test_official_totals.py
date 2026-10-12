import unittest
from types import SimpleNamespace

from form20.pipeline import apply_official_totals
from form20.validate import RowResult


def make_res(rows, nc):
    return SimpleNamespace(
        n_cands=nc, totals={}, meta={},
        rows=[SimpleNamespace(values=list(v)) for v in rows],
    )


class OfficialTotalsTests(unittest.TestCase):
    # 3 candidates | valid rejected nota total tendered
    ROWS = [[100, 50, 10, 160, 0, 3, 163, 0], [200, 40, 20, 260, 0, 4, 264, 0]]

    def test_targets_are_paired_by_rank_and_installed(self):
        res = make_res(self.ROWS, 3)                    # column sums: 300, 90, 30
        official = {"candidates": [31, 300, 91], "nota": 7}   # sheet order differs from official order
        self.assertTrue(apply_official_totals(res, official))
        t = res.totals["TOTAL_EVM"].values
        self.assertEqual(t[:3], [300, 91, 31])          # largest with largest, smallest with smallest
        self.assertEqual(t[3], 31 + 300 + 91)           # total valid
        self.assertEqual(t[5], 7)                       # NOTA
        self.assertEqual((t[4], t[6], t[7]), (None, None, None))
        self.assertEqual(res.meta["totals_source"], "official")
        self.assertIsInstance(res.totals["TOTAL_EVM"], RowResult)

    def test_far_off_columns_are_not_paired(self):
        res = make_res(self.ROWS, 3)
        self.assertFalse(apply_official_totals(res, {"candidates": [900, 90, 30], "nota": 7}))
        self.assertEqual(res.totals, {})

    def test_candidate_count_mismatch_is_rejected(self):
        res = make_res(self.ROWS, 3)
        self.assertFalse(apply_official_totals(res, {"candidates": [300, 90], "nota": 7}))


class SwappedNotaTests(unittest.TestCase):
    OFFICIAL = {"nota": 1186, "candidates": [("A", "", 500), ("B", "", 300)]}

    def test_rejected_column_that_equals_the_official_nota_means_the_labels_are_swapped(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "batch"))
        from verify_official import compare
        got = compare([("a", 500), ("b", 300)], {"NOTA": 0, "REJECTED": 1186}, self.OFFICIAL)
        self.assertEqual((got["verdict"], got["nota_swapped"]), ("FULL", "yes"))
        self.assertIn("swapped", got["detail"])

    def test_a_genuine_nota_mismatch_is_not_excused(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "batch"))
        from verify_official import compare
        got = compare([("a", 500), ("b", 300)], {"NOTA": 7, "REJECTED": 9}, self.OFFICIAL)
        self.assertEqual((got["verdict"], got["nota_swapped"]), ("PARTIAL", ""))


if __name__ == "__main__":
    unittest.main()
