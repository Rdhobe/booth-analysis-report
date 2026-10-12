import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "batch"))

from split_multi_ac import exact_columns, find_cuts, refine_cuts  # noqa: E402

NAMES = ["A", "B", "C"]


def make(blocks):
    """blocks: per AC, a list of booth vectors. -> (all vectors, official dict, acs)."""
    acs = [100 + i for i in range(len(blocks))]
    official = {a: {"candidates": [(n, "", sum(v[k] for v in blk)) for k, n in enumerate(NAMES)]} for a, blk in zip(acs, blocks)}
    return [v for blk in blocks for v in blk], official, acs


def booths(n, seed):
    return [[100 + (seed * 37 + i * 13) % 90, 40 + (seed * 11 + i * 7) % 30, 3 + (i + seed) % 5] for i in range(n)]


class SplitTests(unittest.TestCase):
    BLOCKS = [booths(120, 1), booths(150, 2), booths(110, 3)]

    def test_cuts_fall_where_the_running_sums_reach_each_acs_total(self):
        vectors, official, acs = make(self.BLOCKS)
        self.assertEqual(find_cuts(vectors, acs, official), [120, 270])

    def test_a_cut_that_is_a_few_rows_out_is_moved_to_the_exact_match(self):
        vectors, official, acs = make(self.BLOCKS)
        self.assertEqual(refine_cuts(vectors, acs, official, [118, 273]), [120, 270])

    def test_exact_columns_counts_columns_equal_to_an_official_total(self):
        _, official, acs = make(self.BLOCKS)
        right = [sum(v[k] for v in self.BLOCKS[0]) for k in range(3)]
        self.assertEqual(exact_columns(right, official[acs[0]]), 3)
        self.assertEqual(exact_columns([right[0], right[1] + 1, right[2]], official[acs[0]]), 2)

    def test_misread_votes_do_not_move_the_cut(self):
        vectors, official, acs = make(self.BLOCKS)
        vectors[10][0] += 4                                 # a few misread digits do not change where the AC ends
        vectors[200][1] -= 3
        self.assertEqual(find_cuts(vectors, acs, official), [120, 270])


if __name__ == "__main__":
    unittest.main()
