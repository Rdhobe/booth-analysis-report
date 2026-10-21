import unittest
from types import SimpleNamespace

from form20.pipeline import drop_index_rows


def booth(page, serial, cands):
    valid = sum(cands)
    return SimpleNamespace(page=page, serial=serial, values=list(cands) + [valid, 0, 1, valid + 1, 0])


def sheet(rows, n_cands=7):
    return SimpleNamespace(n_cands=n_cands, meta={}, rows=list(rows))


class DropIndexRowsTests(unittest.TestCase):
    BOOTHS = [booth(1 + i // 4, i + 1, [300 + i, 120, 40, 9, 5, 3, 1]) for i in range(8)]

    def test_column_number_row_on_every_page_is_removed(self):
        rows = []
        for p in (1, 2):
            rows.append(booth(p, 1, [1, 2, 3, 4, 5, 6, 7]))
            rows += [b for b in self.BOOTHS if b.page == p]
        res = sheet(rows)
        self.assertEqual(drop_index_rows(res), [(1, 1), (2, 1)])
        self.assertEqual(len(res.rows), 8)
        self.assertEqual(res.meta["dropped_index_rows"], [(1, 1), (2, 1)])

    def test_a_shifted_numbering_row_is_removed_too(self):
        res = sheet([booth(1, 1, [2, 3, 4, 5, 6, 7, 1])] + self.BOOTHS)
        self.assertEqual(drop_index_rows(res), [(1, 1)])

    def test_numbering_that_continues_from_the_identifier_columns_is_removed(self):
        res = sheet([booth(1, 1, [8, 9, 10, 11, 12, 13, 14])] + self.BOOTHS)
        self.assertEqual(drop_index_rows(res), [(1, 1)])
        self.assertEqual(len(res.rows), 8)

    def test_real_booths_are_kept(self):
        res = sheet(self.BOOTHS)
        self.assertEqual(drop_index_rows(res), [])
        self.assertEqual(len(res.rows), 8)

    def test_unreadable_cell_in_a_row_keeps_it(self):
        row = booth(1, 1, [1, 2, 3, 4, 5, 6, 7])
        row.values[3] = None
        res = sheet([row] + self.BOOTHS)
        self.assertEqual(drop_index_rows(res), [])

    def test_sheet_with_few_candidates_is_left_alone(self):
        res = sheet([booth(1, 1, [1, 2, 3])] + [booth(1, 2, [50, 20, 3])], n_cands=3)
        self.assertEqual(drop_index_rows(res), [])
        self.assertEqual(len(res.rows), 2)


if __name__ == "__main__":
    unittest.main()
