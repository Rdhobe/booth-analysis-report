import unittest

from form20.pipeline import _assign_ps, _assign_serials, _parse_ps


def page(n, reads=None):
    return [{"serial_read": (reads or {}).get(i), "ps_read": "", "notes": []} for i in range(n)]


class IdTests(unittest.TestCase):
    def test_serials_continue_across_pages_despite_bad_reads(self):
        p1, p2 = page(26, {0: 1, 5: 6}), page(26, {0: 2, 3: 9})     # 2nd page reads are garbage
        _assign_serials([p1, p2])
        self.assertEqual([r["serial"] for r in p1], list(range(1, 27)))
        self.assertEqual([r["serial"] for r in p2], list(range(27, 53)))

    def test_real_break_in_sequence_is_flagged(self):
        p1 = page(10)
        p2 = [{"serial_read": 200 + i, "ps_read": "", "notes": []} for i in range(10)]
        _assign_serials([p1, p2])
        self.assertEqual(p2[0]["serial"], 200)
        self.assertTrue(any("discontinuity" in n for n in p2[0]["notes"]))

    def test_polling_station_suffix_rows(self):
        rows = [{"serial": i + 1, "ps_read": t, "notes": []} for i, t in enumerate(["1", "2", "2A", "garbage", "4"])]
        _assign_ps(rows, hindi=False)
        self.assertEqual([r["ps_no"] for r in rows], ["1", "2", "2A", "3", "4"])

    def test_parse_ps(self):
        self.assertEqual(_parse_ps("41A"), (41, "A"))
        self.assertEqual(_parse_ps("17"), (17, ""))
        self.assertIsNone(_parse_ps("1x7"))


if __name__ == "__main__":
    unittest.main()
