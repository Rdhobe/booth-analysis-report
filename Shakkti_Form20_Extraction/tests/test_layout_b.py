import unittest
from types import SimpleNamespace

from form20.ocr import CellRead
from form20.pipeline import (_b_index, apply_official_totals, b_order, c_missing, c_synthetic_index, canonical_cells,
                             choose_layout, to_canonical_a)
from form20.validate import read_as_printed, solve_row


def cell(text, conf=90.0):
    return CellRead(reads={"A": text, "B": text}, confs={"A": conf, "B": conf})


def b_numbers(i):
    """Layout B numeric part: 3 candidates + NOTA | valid (incl. NOTA) rejected tendered total."""
    c = [5 + i, 3, 2 + i % 4]
    nota = 1 + i % 3
    valid = sum(c) + nota
    rej, tend = i % 2, 0
    return c + [nota, valid, rej, tend, valid + rej]


def a_numbers(i):
    """Layout A: 3 candidates | valid rejected NOTA total tendered."""
    c = [5 + i, 3, 2 + i % 4]
    valid, rej, nota = sum(c), i % 2, 1 + i % 3
    return c + [valid, rej, nota, valid + rej + nota, 0]


def table(numbers, n_ids, n_rows=12):
    ids = lambda i: [str(i + 1)] + [""] * (n_ids - 1)
    return [[cell(t) for t in ids(i) + [str(x) for x in numbers(i)]] for i in range(n_rows)]


class CanonicalCellsTests(unittest.TestCase):
    def test_layout_a_is_left_alone(self):
        cells = [cell("1"), cell("2")]
        self.assertIs(canonical_cells(cells, "A"), cells)

    def test_layout_b_is_reordered_and_solves_as_a_consistent_row(self):
        cells = [cell(str(x)) for x in b_numbers(3)]
        canon = canonical_cells(cells, "B")
        self.assertEqual(len(canon), len(cells) + 1)               # a synthetic NOTA slot was added
        self.assertEqual(canon[-3].text, "0")                      # ... in the canonical NOTA position
        r = solve_row(canon, 4)                                    # 3 candidates + NOTA
        self.assertEqual(r.status, "OK")


def b_numbers_total_first(i):
    """Layout B variant whose last two columns are total, tendered (instead of tendered, total)."""
    c = [5 + i, 3, 2 + i % 4]
    nota = 1 + i % 3
    valid = sum(c) + nota
    rej, tend = i % 2, 1 + i % 2
    return c + [nota, valid, rej, valid + rej, tend]


class BOrderTests(unittest.TestCase):
    def test_default_and_named_orders(self):
        self.assertEqual(b_order("B"), "vrtT")
        self.assertEqual(b_order("B-vrTt"), "vrTt")

    def test_variant_order_is_reordered_correctly(self):
        cells = [cell(str(x)) for x in b_numbers_total_first(4)]
        canon = canonical_cells(cells, "B-vrTt")
        self.assertEqual(solve_row(canon, 4).status, "OK")                   # identities hold in canonical order
        self.assertNotEqual(solve_row(canonical_cells(cells, "B"), 4).status, "OK")   # the default order would not

    def test_the_probe_learns_the_variant_order(self):
        got = choose_layout(table(b_numbers_total_first, 2), 2 + 8, default_id_cols=1)
        self.assertEqual(got[:2], (2, "B-vrTt"))

    def test_the_default_order_wins_when_orders_are_indistinguishable(self):
        zero_tendered = lambda i: b_numbers(i)[:-3] + [b_numbers(i)[-3], 0, b_numbers(i)[-1]]
        self.assertEqual(choose_layout(table(zero_tendered, 2), 2 + 8, default_id_cols=1)[:2], (2, "B"))


def c_numbers_no_total(i):
    """Layout C: 3 candidates | valid rejected NOTA tendered - the sheet prints no total column."""
    c = [5 + i, 3, 2 + i % 4]
    valid = sum(c)
    return c + [valid, i % 2, 1 + i % 3, 0]


class LayoutCTests(unittest.TestCase):
    def test_missing_column_and_synthetic_index(self):
        self.assertEqual(c_missing("vrNt"), "T")
        self.assertEqual(c_missing("vrNT"), "t")
        self.assertEqual(c_synthetic_index("C:vrNt", 8), 8 + 3)         # the blank stands in for the total
        self.assertEqual(c_synthetic_index("C:vrNT", 8), 8 + 4)         # ... or for the tendered column

    def test_reordering_gives_canonical_cells_with_a_blank_for_the_missing_column(self):
        cells = [cell(str(x)) for x in c_numbers_no_total(2)]
        canon = canonical_cells(cells, "C:vrNt")
        self.assertEqual(len(canon), len(cells) + 1)
        self.assertEqual(canon[3 + 3].text, "")                         # blank total, to be solved
        r = solve_row(canon, 3)
        self.assertEqual(r.status, "AUTO_CORRECTED")                    # the blank total is solved, not guessed
        valid, rej, nota = r.values[3], r.values[4], r.values[5]
        self.assertEqual(r.values[6], valid + rej + nota)               # total = valid + rejected + NOTA

    def test_read_as_printed_accepts_the_unprinted_column(self):
        cells = [cell(str(x)) for x in c_numbers_no_total(2)]
        r = solve_row(canonical_cells(cells, "C:vrNt"), 3)
        row = SimpleNamespace(status=r.status, changed=r.changed, primary=r.primary, values=r.values)
        self.assertFalse(read_as_printed(row, 3))
        self.assertTrue(read_as_printed(row, 3, extra_blank=(c_synthetic_index("C:vrNt", 3),)))

    def test_with_the_official_candidate_count_layout_c_is_found(self):
        # 2 identifier columns + 3 candidates + 4 trailing = 9 columns; 3 official candidates
        got = choose_layout(table(c_numbers_no_total, 2), 2 + 3 + 4, default_id_cols=1, n_off=3)
        self.assertEqual(got[:2], (2, "C:vrNt"))

    def test_canonical_sheets_still_pick_layout_a_when_the_official_count_is_given(self):
        got = choose_layout(table(a_numbers, 2), 2 + 8, default_id_cols=1, n_off=3)
        self.assertEqual(got[:2], (2, "A"))


class OnlyKTests(unittest.TestCase):
    def test_known_id_column_count_overrides_a_misleading_probe(self):
        noisy = table(a_numbers, 2)                       # truth: 2 identifier columns
        for row in noisy[:-2]:
            for j in (5, 6, 7, 8):
                row[j] = cell("")                         # noise leaves too few consistent rows for the probe
        got = choose_layout(noisy, 2 + 8, default_id_cols=1, only_k=2)
        self.assertEqual(got[:2], (2, "A"))               # with the count known, the answer is no longer in doubt

    def test_only_the_given_count_is_scored(self):
        got = choose_layout(table(a_numbers, 2), 2 + 8, default_id_cols=1, only_k=2)
        self.assertTrue(all(h[1] == 2 for h in got[2]))


class ChooseLayoutTests(unittest.TestCase):
    def test_layout_b_is_chosen_when_only_it_fits(self):
        got = choose_layout(table(b_numbers, 2), 2 + 8, default_id_cols=1)
        self.assertEqual(got[:2], (2, "B"))

    def test_layout_a_is_kept_for_canonical_sheets(self):
        got = choose_layout(table(a_numbers, 2), 2 + 8, default_id_cols=2)
        self.assertEqual(got[:2], (2, "A"))

    def test_second_identifier_column_found_for_layout_a(self):
        got = choose_layout(table(a_numbers, 2), 2 + 8, default_id_cols=1)
        self.assertEqual(got[:2], (2, "A"))

    def test_nothing_fits_keeps_the_default(self):
        junk = [[cell(str((i * 7 + j * 13) % 41)) for j in range(10)] for i in range(12)]
        self.assertEqual(choose_layout(junk, 10, default_id_cols=1)[:2], (1, "A"))


class ToCanonicalATests(unittest.TestCase):
    def test_result_is_converted_to_the_canonical_layout(self):
        nc_a = 3
        nums = b_numbers(4)                                         # c1 c2 c3 NOTA valid rej tend total
        canon_cells = canonical_cells([cell(str(x)) for x in nums], "B")
        r = solve_row(canon_cells, nc_a + 1)
        row = SimpleNamespace(values=r.values, primary=r.primary, changed=[nc_a + 2], alternatives=[(0.5, r.values)])
        totals = {"TOTAL_EVM": SimpleNamespace(values=list(r.values))}
        res = SimpleNamespace(rows=[row], totals=totals, n_cands=nc_a + 1,
                              names_native=["a", "b", "c", "NOTA"], names_en=["a", "b", "c", "NOTA"], parties=["", "", "", ""])
        to_canonical_a(res)
        c1, c2, c3, nota, valid, rej, tend, total = nums[0], nums[1], nums[2], nums[3], nums[4], nums[5], nums[6], nums[7]
        self.assertEqual(res.n_cands, 3)
        self.assertEqual(row.values, [c1, c2, c3, c1 + c2 + c3, rej, nota, total, tend])
        self.assertEqual(row.values[3], valid - nota)               # valid votes exclude NOTA again
        self.assertEqual(row.alternatives[0][1], row.values)
        self.assertEqual(totals["TOTAL_EVM"].values, row.values)
        self.assertEqual(res.names_native, ["a", "b", "c"])
        self.assertEqual(len(row.primary), 8)

    def test_changed_indices_follow_the_columns(self):
        nc = 3
        self.assertEqual(_b_index(1, nc), 1)           # candidate
        self.assertEqual(_b_index(3, nc), 5)           # NOTA column -> canonical NOTA
        self.assertEqual(_b_index(5, nc), 4)           # rejected
        self.assertEqual(_b_index(7, nc), 6)           # total
        self.assertEqual(_b_index(8, nc), 7)           # tendered
        self.assertIsNone(_b_index(4, nc))             # valid column is derived
        self.assertIsNone(_b_index(6, nc))             # synthetic NOTA slot


class OfficialTargetsLayoutBTests(unittest.TestCase):
    def test_nota_is_paired_as_a_candidate_like_column_and_counted_in_valid(self):
        rows = [SimpleNamespace(values=v) for v in ([100, 50, 10, 4, 164, 0, 0, 164, 0], [200, 40, 20, 6, 266, 0, 0, 266, 0])]
        res = SimpleNamespace(n_cands=4, totals={}, meta={"layout": "B"}, rows=rows)    # sums 300, 90, 30, 10
        self.assertTrue(apply_official_totals(res, {"candidates": [300, 91, 31], "nota": 10}))
        t = res.totals["TOTAL_EVM"].values
        self.assertEqual(t[:4], [300, 91, 31, 10])
        self.assertEqual(t[4], 300 + 91 + 31 + 10)     # valid includes NOTA in layout B
        self.assertIsNone(t[6])                        # the synthetic NOTA slot has no target


if __name__ == "__main__":
    unittest.main()
