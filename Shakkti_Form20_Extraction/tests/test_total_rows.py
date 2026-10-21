import unittest
from types import SimpleNamespace

from form20.pipeline import (drop_excess_rows, drop_impossible_rows, drop_official_total_rows, drop_subtotal_rows,
                             drop_summary_rows, drop_total_rows)


def booth(page, serial, cands, nota=1):
    valid = sum(cands)
    return SimpleNamespace(page=page, serial=serial, values=list(cands) + [valid, 0, nota, valid + nota, 0])


def sheet(booths, extra_rows=()):
    return SimpleNamespace(n_cands=3, meta={}, rows=list(booths) + list(extra_rows))


def column_total(booths):
    n = len(booths[0].values)
    return [sum(b.values[c] for b in booths) for c in range(n)]


class DropTotalRowsTests(unittest.TestCase):
    BOOTHS = [booth(1 + i // 4, i + 1, [10 + i, 5, 2 + i % 3]) for i in range(12)]

    def total_row(self, serial):
        t = column_total(self.BOOTHS)
        return SimpleNamespace(page=3, serial=serial, values=t)

    def test_total_rows_read_as_booths_are_removed(self):
        res = sheet(self.BOOTHS, [self.total_row(13)])
        self.assertEqual(drop_total_rows(res), [(3, 13)])
        self.assertEqual(len(res.rows), 12)
        self.assertEqual(res.meta["dropped_total_rows"], [(3, 13)])

    def test_repeated_total_and_blank_postal_rows_after_it_go_too(self):
        zero = SimpleNamespace(page=3, serial=14, values=[0] * 8)
        res = sheet(self.BOOTHS, [self.total_row(13), zero, self.total_row(15)])
        self.assertEqual([s for _, s in drop_total_rows(res)], [13, 14, 15])
        self.assertEqual(len(res.rows), 12)

    def test_sheet_without_total_rows_is_untouched(self):
        res = sheet(self.BOOTHS)
        self.assertEqual(drop_total_rows(res), [])
        self.assertEqual(len(res.rows), 12)

    def test_a_row_that_only_looks_big_is_not_dropped(self):
        big = booth(3, 13, [500, 400, 300])                         # large booth, not the sum of the others
        res = sheet(self.BOOTHS, [big])
        self.assertEqual(drop_total_rows(res), [])
        self.assertEqual(len(res.rows), 13)

    def test_rows_with_unread_cells_are_never_taken_for_totals(self):
        t = self.total_row(13)
        t.values[1] = None
        res = sheet(self.BOOTHS, [t])
        self.assertEqual(drop_total_rows(res), [])

    def test_a_genuine_booth_after_the_total_stops_the_removal(self):
        res = sheet(self.BOOTHS, [self.total_row(13), booth(3, 14, [7, 7, 7])])
        self.assertEqual(drop_total_rows(res), [])                  # something real follows: leave the sheet alone
        self.assertEqual(len(res.rows), 14)


class OutlierRuleTests(unittest.TestCase):
    def booths(self, n=30):
        return [booth(1 + i // 10, i + 1, [300 + i, 100, 50]) for i in range(n)]

    def test_a_total_row_that_does_not_equal_the_sum_is_still_caught_by_size(self):
        rows = self.booths()
        total = [sum(b.values[c] for b in rows) + 7 for c in range(8)]          # one misread booth: off by 7
        res = sheet(rows, [SimpleNamespace(page=4, serial=31, values=total)])
        self.assertEqual(drop_total_rows(res), [(4, 31)])
        self.assertEqual(len(res.rows), 30)

    def test_blank_rows_between_and_after_the_total_go_with_it(self):
        rows = self.booths()
        total = [sum(b.values[c] for b in rows) + 7 for c in range(8)]
        zero = SimpleNamespace(page=4, serial=32, values=[0] * 8)
        res = sheet(rows, [SimpleNamespace(page=4, serial=31, values=total), zero])
        self.assertEqual([s for _, s in drop_total_rows(res)], [31, 32])

    def test_a_big_but_ordinary_booth_is_kept(self):
        rows = self.booths() + [booth(4, 31, [900, 700, 400])]                   # large booth, nowhere near 15x
        res = sheet(rows)
        self.assertEqual(drop_total_rows(res), [])

    def test_trailing_zero_rows_alone_are_not_dropped(self):
        res = sheet(self.booths(), [SimpleNamespace(page=4, serial=31, values=[0] * 8)])
        self.assertEqual(drop_total_rows(res), [])


OFFICIAL = {"candidates": [106873, 75848, 20017, 641, 620, 445], "nota": 1447}


class DropOfficialTotalRowsTests(unittest.TestCase):
    BOOTHS = [booth(1, i + 1, [300 + i, 120, 40, 9, 5, 3]) for i in range(6)]

    def sheet(self, extra):
        return SimpleNamespace(n_cands=6, meta={}, rows=list(self.BOOTHS) + extra)

    def test_total_row_with_unreadable_big_cells_is_removed(self):
        total = SimpleNamespace(page=2, serial=7, values=[0, 0, 17, 641, 620, 445, 0, 0, 1447, 0, 0])
        res = self.sheet([total])
        self.assertEqual(drop_official_total_rows(res, OFFICIAL), [(2, 7)])
        self.assertEqual(len(res.rows), 6)
        self.assertEqual(res.meta["dropped_total_rows"], [(2, 7)])

    def test_dropped_rows_are_added_to_those_already_recorded(self):
        total = SimpleNamespace(page=2, serial=7, values=[0, 0, 17, 641, 620, 445, 0, 0, 1447, 0, 0])
        res = self.sheet([total])
        res.meta["dropped_total_rows"] = [(2, 8)]
        drop_official_total_rows(res, OFFICIAL)
        self.assertEqual(res.meta["dropped_total_rows"], [(2, 8), (2, 7)])

    def test_one_or_two_chance_matches_are_not_a_total_row(self):
        booth_row = SimpleNamespace(page=2, serial=7, values=[641, 80, 12, 9, 5, 3, 0, 0, 1447, 0, 0])
        res = self.sheet([booth_row])
        self.assertEqual(drop_official_total_rows(res, OFFICIAL), [])
        self.assertEqual(len(res.rows), 7)

    def test_unreadable_cells_do_not_break_the_check(self):
        row = SimpleNamespace(page=2, serial=7, values=[None, 80, 12, 9, 5, 3, 0, 0, None, 0, 0])
        res = self.sheet([row])
        self.assertEqual(drop_official_total_rows(res, OFFICIAL), [])


class DropSubtotalRowsTests(unittest.TestCase):
    def page_rows(self, page, first, count):
        return [booth(page, first + i, [30 + i, 12, 3 + i % 2]) for i in range(count)]

    def subtotal(self, page, serial, rows):
        return SimpleNamespace(page=page, serial=serial, values=column_total(rows))

    def sheet_with_page_subtotals(self):
        p1, p2 = self.page_rows(1, 1, 6), self.page_rows(2, 7, 7)
        return SimpleNamespace(n_cands=3, meta={}, rows=p1 + [self.subtotal(1, 99, p1)] + p2 + [self.subtotal(2, 98, p2)]), p1 + p2

    def test_page_sub_totals_are_removed(self):
        res, booths = self.sheet_with_page_subtotals()
        self.assertEqual(drop_subtotal_rows(res), [(1, 99), (2, 98)])
        self.assertEqual(len(res.rows), 13)
        self.assertEqual(res.meta["dropped_subtotal_rows"], [(1, 99), (2, 98)])

    def test_running_totals_are_removed(self):
        p1, p2 = self.page_rows(1, 1, 6), self.page_rows(2, 7, 6)
        running = SimpleNamespace(page=2, serial=98, values=column_total(p1 + p2))
        res = SimpleNamespace(n_cands=3, meta={}, rows=p1 + [self.subtotal(1, 99, p1)] + p2 + [running])
        self.assertEqual([s for _, s in drop_subtotal_rows(res)], [99, 98])

    def test_sheet_without_sub_totals_is_untouched(self):
        res = SimpleNamespace(n_cands=3, meta={}, rows=self.page_rows(1, 1, 12))
        self.assertEqual(drop_subtotal_rows(res), [])
        self.assertEqual(len(res.rows), 12)

    def test_too_few_rows_above_do_not_count_for_near_empty_rows(self):
        p1 = [booth(1, i + 1, [1, 0, i % 2]) for i in range(3)]
        res = SimpleNamespace(n_cands=3, meta={}, rows=p1 + [self.subtotal(1, 99, p1)])
        self.assertEqual(drop_subtotal_rows(res), [])

    def test_total_of_a_one_booth_section_is_removed(self):
        p1, last = self.page_rows(1, 1, 6), self.page_rows(2, 7, 1)          # a section of six booths, then one of one
        res = SimpleNamespace(n_cands=3, meta={}, rows=p1 + [self.subtotal(1, 98, p1)] + last + [self.subtotal(2, 99, last)])
        self.assertEqual(drop_subtotal_rows(res), [(1, 98), (2, 99)])
        self.assertEqual(len(res.rows), 7)

    def test_a_row_identical_to_the_one_above_is_removed_even_when_the_earlier_total_is_gone(self):
        p1 = self.page_rows(1, 1, 6)
        res = SimpleNamespace(n_cands=3, meta={}, rows=p1 + [booth(2, 7, [224, 36, 25]), booth(2, 8, [224, 36, 25])])
        self.assertEqual(drop_subtotal_rows(res), [(2, 8)])
        self.assertEqual(len(res.rows), 7)

    def test_two_different_booths_in_a_row_are_not_mistaken_for_a_total(self):
        p1 = self.page_rows(1, 1, 8)
        res = SimpleNamespace(n_cands=3, meta={}, rows=p1)
        self.assertEqual(drop_subtotal_rows(res), [])


class DropImpossibleRowsTests(unittest.TestCase):
    def row(self, serial, cells):
        return SimpleNamespace(page=1, serial=serial, primary=[str(c) for c in cells], values=list(cells))

    def sheet(self, source):
        rows = [self.row(i, [40 + i, 12, 3, 55 + i, 0, 1, 56 + i, 0]) for i in range(1, 8)]
        total = self.row(8, [9136, 1808, 36, 11000, 0, 57, 11057, 0])
        return SimpleNamespace(n_cands=3, meta={"source": source}, rows=rows + [total])

    def test_text_layer_row_with_an_impossible_count_is_dropped(self):
        res = self.sheet("text layer")
        self.assertEqual(drop_impossible_rows(res), [(1, 8)])
        self.assertEqual(len(res.rows), 7)
        self.assertEqual(res.meta["dropped_impossible_rows"], [(1, 8)])

    def test_ocr_rows_are_never_dropped_for_that(self):
        res = self.sheet("ocr")
        self.assertEqual(drop_impossible_rows(res), [])
        self.assertEqual(len(res.rows), 8)


class DropExcessRowsTests(unittest.TestCase):
    def row(self, serial, cands, nota, status="OK", page=1):
        v = list(cands) + [sum(cands), 0, nota, sum(cands) + nota, 0]
        return SimpleNamespace(page=page, serial=serial, status=status, values=v)

    def sheet(self, extra):
        rows = [self.row(i, [100 + i, 40 + i, 9], 2 + i % 2) for i in range(1, 9)]
        return SimpleNamespace(n_cands=3, meta={"layout": "A"}, rows=rows + extra), rows

    def official(self, rows, extra=(0, 0, 0, 0)):
        c = [sum(r.values[k] for r in rows) for k in range(3)]
        return {"candidates": c, "nota": sum(r.values[5] for r in rows)}

    def test_one_stray_row_equal_to_the_excess_is_removed(self):
        stray = self.row(9, [4, 3, 1], 2, status="AUTO_CORRECTED", page=2)
        res, real = self.sheet([stray])
        self.assertEqual(drop_excess_rows(res, self.official(real)), [(2, 9)])
        self.assertEqual(len(res.rows), 8)
        self.assertEqual(res.meta["dropped_excess_rows"], [(2, 9)])

    def test_two_unsure_rows_adding_up_to_the_excess_are_removed(self):
        a = self.row(9, [4, 0, 1], 1, status="REVIEW", page=2)
        b = self.row(10, [0, 3, 2], 1, status="AUTO_CORRECTED", page=2)
        res, real = self.sheet([a, b])
        self.assertEqual(sorted(drop_excess_rows(res, self.official(real))), [(2, 9), (2, 10)])

    def test_a_tiny_excess_is_left_alone(self):
        small = self.row(9, [0, 3, 0], 0, page=2)           # 3 votes in one column: could be a real booth
        res, real = self.sheet([small])
        self.assertEqual(drop_excess_rows(res, self.official(real)), [])
        self.assertEqual(len(res.rows), 9)

    def test_sheet_equal_to_the_official_totals_is_untouched(self):
        res, real = self.sheet([])
        self.assertEqual(drop_excess_rows(res, self.official(real)), [])

    def test_a_sheet_far_from_the_official_totals_is_untouched(self):
        res, real = self.sheet([self.row(9, [4, 3, 1], 2, page=2)])
        off = self.official(real)
        off["candidates"] = [c * 3 for c in off["candidates"]]
        self.assertEqual(drop_excess_rows(res, off), [])


class DropSummaryRowsTests(unittest.TestCase):
    def row(self, serial_read, cands, page=1):
        v = list(cands) + [sum(cands), 0, 2, sum(cands) + 2, 0]
        return SimpleNamespace(page=page, serial=serial_read or 0, serial_read=serial_read, values=v)

    def sheet(self, extra):
        rows = [self.row(100 + i, [200 + (i * 7) % 90, 90 + i % 13, 30 + i % 7]) for i in range(40)]
        return SimpleNamespace(n_cands=3, meta={}, rows=rows + extra)

    def test_page_and_running_totals_are_removed(self):
        page_total = self.row(None, [4200, 1900, 650], page=2)
        previous = self.row(None, [11000, 5200, 1400], page=2)
        res = self.sheet([page_total, previous])
        self.assertEqual(len(drop_summary_rows(res)), 2)
        self.assertEqual(len(res.rows), 40)
        self.assertEqual(len(res.meta["dropped_summary_rows"]), 2)

    def test_a_total_row_with_a_serial_read_is_still_removed_when_huge(self):
        res = self.sheet([self.row(7, [4200, 1900, 650], page=2)])
        self.assertEqual(len(drop_summary_rows(res)), 1)

    def test_a_moderately_large_row_needs_a_blank_serial_to_be_removed(self):
        keep = self.row(139, [1000, 400, 200])              # 1600 valid: about 4.2x the median, but it has a serial
        drop = self.row(None, [1000, 400, 200])
        res = self.sheet([keep, drop])
        self.assertEqual(len(drop_summary_rows(res)), 1)
        self.assertIn(keep, res.rows)

    def test_sheet_without_summary_rows_is_untouched(self):
        res = self.sheet([])
        self.assertEqual(drop_summary_rows(res), [])
        self.assertEqual(len(res.rows), 40)

    def test_a_short_sheet_is_left_alone(self):
        res = SimpleNamespace(n_cands=3, meta={}, rows=[self.row(1, [200, 90, 30]) for _ in range(10)] + [self.row(None, [9000, 4000, 1000])])
        self.assertEqual(drop_summary_rows(res), [])


if __name__ == "__main__":
    unittest.main()
