import unittest
from types import SimpleNamespace

from form20.pipeline import drop_duplicate_pages


def booth(page, i, source=None):
    """A booth row whose values depend on the page it is printed on (source: copy another page's values)."""
    k = (source or page) * 41 + i
    return SimpleNamespace(page=page, values=[100 + k, 50 + k % 7, 3, 153 + k, 0, 2, 155 + k, 0])


class DuplicatePageTests(unittest.TestCase):
    def test_a_page_scanned_twice_is_dropped(self):
        rows = [booth(p, i) for p in (1, 2, 3) for i in range(26)] + [booth(4, i, source=3) for i in range(26)]
        res = SimpleNamespace(meta={}, rows=rows)
        self.assertEqual(drop_duplicate_pages(res), [4])
        self.assertEqual(sorted({r.page for r in res.rows}), [1, 2, 3])
        self.assertEqual(res.meta["dropped_duplicate_pages"], [4])

    def test_distinct_pages_are_kept(self):
        res = SimpleNamespace(meta={}, rows=[SimpleNamespace(page=p, values=[100 * p + i, 3, 4, 5]) for p in (1, 2, 3)
                                             for i in range(26)])
        self.assertEqual(drop_duplicate_pages(res), [])
        self.assertEqual(len(res.rows), 78)

    def test_short_pages_and_blank_rows_are_not_mistaken_for_duplicates(self):
        res = SimpleNamespace(meta={}, rows=[SimpleNamespace(page=p, values=[0, 0, 0, 0]) for p in (1, 2) for _ in range(26)])
        self.assertEqual(drop_duplicate_pages(res), [])                      # all-zero rows prove nothing
        tiny = SimpleNamespace(meta={}, rows=[SimpleNamespace(page=p, values=[5, 6, 7]) for p in (1, 2) for _ in range(3)])
        self.assertEqual(drop_duplicate_pages(tiny), [])                     # fewer than 5 rows


if __name__ == "__main__":
    unittest.main()
