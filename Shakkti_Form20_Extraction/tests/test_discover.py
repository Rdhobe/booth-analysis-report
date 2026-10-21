import random
import unittest

from form20.discover import discover
from form20.pipeline import canonical_cells, m_layout, m_parts, m_unprinted
from form20.ocr import CellRead


def votes(n, rng):
    return [rng.choice([0, 0, 1, 2, 5, 40]) + (rng.randint(100, 400) if i < 2 else 0) for i in range(n)]


def rows_for(build, n_rows=30, seed=1):
    rng = random.Random(seed)
    return [build(rng) for _ in range(n_rows)]


class DiscoverTests(unittest.TestCase):
    def test_standard_layout_is_found(self):
        def build(rng):
            c = votes(5, rng); v = sum(c); rej, nota = rng.randint(0, 3), rng.randint(0, 9)
            return [rng.randint(1, 500)] + c + [v, rej, nota, v + rej + nota, 0]
        a, nc, spec, share = discover(rows_for(build), 5)
        self.assertEqual((a, nc, spec), (1, 5, (5, 6, 7, 8, 9)))
        self.assertEqual(share, 1.0)

    def test_duplicate_nota_column_after_the_candidates(self):
        def build(rng):                          # cands | NOTA again | valid, rejected, NOTA, total, tendered
            c = votes(5, rng); v = sum(c); nota = rng.randint(1, 9)
            return [rng.randint(1, 500)] + c + [nota, v, 0, nota, v + nota, 0]
        a, nc, spec, share = discover(rows_for(build), 5)
        self.assertEqual((a, nc), (1, 5))
        self.assertEqual(spec[0], 6)             # valid is the column that equals the candidates' sum, not the dup NOTA

    def test_no_valid_or_rejected_column_printed(self):
        def build(rng):                          # cands | NOTA, total, tendered
            c = votes(6, rng); nota = rng.randint(1, 9)
            return [rng.randint(1, 500)] + c + [nota, sum(c) + nota, 0]
        a, nc, spec, share = discover(rows_for(build), 6)
        self.assertEqual((a, nc), (1, 6))
        self.assertIsNone(spec[0])               # valid not printed
        self.assertIsNone(spec[1])               # rejected not printed
        self.assertEqual(spec[2:4], (6, 7))

    def test_an_empty_name_column_is_not_taken_for_a_candidate(self):
        def build(rng):                          # serial, name (no digits) | cands | NOTA, total incl. NOTA, tendered
            c = votes(5, rng); nota = rng.randint(1, 9)
            return [rng.randint(1, 500), None] + c + [nota, sum(c) + nota, 0]
        a, nc, spec, share = discover(rows_for(build), 5)
        # shifted one column left, the blank name column is candidate 1 and the last candidate plays 'rejected':
        # the identities hold just the same, but the real block starts after the name column
        self.assertEqual((a, nc), (2, 5))
        self.assertEqual(spec[2:4], (5, 6))

    def test_several_leading_columns(self):
        def build(rng):
            c = votes(5, rng); v = sum(c); nota = rng.randint(0, 9)
            return [rng.randint(1, 9), rng.randint(1, 99), rng.randint(1, 500), v + nota] + c + [v, 0, nota, v + nota, 0]
        a, nc, spec, share = discover(rows_for(build), 5)
        self.assertEqual((a, nc, share), (4, 5, 1.0))

    def test_noise_without_arithmetic_finds_nothing(self):
        rng = random.Random(3)
        table = [[rng.randint(0, 900) for _ in range(12)] for _ in range(30)]
        self.assertIsNone(discover(table, 5))

    def test_a_few_misread_rows_are_tolerated(self):
        def build(rng):
            c = votes(5, rng); v = sum(c)
            return c + [v, 0, 3, v + 3, 0]
        rows = rows_for(build)
        for r in rows[:3]:
            r[0] += 7                            # three rows with a misread cell
        self.assertEqual(discover(rows, 5)[2], (5, 6, 7, 8, 9))

    def test_official_nota_share_refuses_an_all_zero_column_as_nota(self):
        def build(rng):          # cands | NOTA | valid, rejected, valid again, 0, total (= valid + NOTA), tendered
            c = votes(5, rng); v = sum(c); nota = rng.randint(1, 9)
            return [rng.randint(1, 500)] + c + [nota, v, 0, v, 0, v + nota, 0]
        rows = rows_for(build)
        ratio = 0.006                                      # the official NOTA over the official candidate votes
        a, nc, spec, share = discover(rows, 5, nota_ratio=ratio)
        self.assertEqual(spec[0:4], (6, None, 5, 10))      # valid, NOTA right after the block, total (rejected is all zeros)
        self.assertEqual(share, 1.0)

    def test_a_degenerate_structure_is_refused_when_the_official_nota_share_is_known(self):
        def build(rng):          # cands | valid, rejected, NOTA, total, tendered - but 30% of the totals are misread
            c = votes(5, rng); v = sum(c); nota = rng.randint(2, 9)
            total = v + nota + (rng.randint(1, 40) if rng.random() < 0.3 else 0)
            return [rng.randint(1, 500)] + c + [v, 0, nota, total, 0]
        rows = rows_for(build, n_rows=60, seed=4)
        self.assertIsNotNone(discover(rows, 5))                  # no hint: valid taken as the total, zeros as the rest
        self.assertIsNone(discover(rows, 5, nota_ratio=0.01))

    def test_blank_rejected_and_nota_cells_count_as_zero(self):
        def build(rng):
            c = votes(5, rng); v = sum(c); rej, nota = rng.choice([0, 0, 1]), rng.choice([0, 0, 0, 2, 5])
            return [rng.randint(1, 500)] + c + [v, rej or None, nota or None, v + rej + nota, None]
        a, nc, spec, share = discover(rows_for(build, n_rows=40), 5)
        self.assertEqual((a, nc, spec[:4]), (1, 5, (5, 6, 7, 8)))
        self.assertGreaterEqual(share, 0.95)

    def test_too_few_rows_give_no_answer(self):
        self.assertIsNone(discover([[1, 2, 3, 4, 5, 6, 7, 8]] * 4, 3))


class LayoutNameTests(unittest.TestCase):
    def cells(self, texts):
        return [CellRead(reads={"A": t, "B": t}, confs={"A": 100.0, "B": 100.0}) for t in texts]

    def test_name_round_trip_and_unprinted_slots(self):
        name = m_layout(4, (4, None, 6, 7, None))
        self.assertEqual(name, "M:4:4,-,6,7,-")
        self.assertEqual(m_parts(name), (4, [4, None, 6, 7, None]))
        self.assertEqual(m_unprinted(name, 4), (5, 8))

    def test_canonical_cells_reorder_and_blank_fill(self):
        name = m_layout(3, (4, None, 3, 5, None))        # cands 0-2 | NOTA 3, valid 4, total 5
        out = canonical_cells(self.cells(["10", "20", "30", "7", "60", "67"]), name)
        self.assertEqual([c.text for c in out], ["10", "20", "30", "60", "", "7", "67", ""])


if __name__ == "__main__":
    unittest.main()
