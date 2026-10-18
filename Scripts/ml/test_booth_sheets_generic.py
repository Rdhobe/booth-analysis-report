"""Tests for the label-based booth-sheet reader. Run:  python -m pytest Scripts/ml/test_booth_sheets_generic.py -q"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ac_booth_totals as T  # noqa: E402
import booth_sheets_generic as G  # noqa: E402


class FakeCell:
    def __init__(self, value):
        self.value = value


class FakeSheet:
    """Just enough of an xlrd sheet: nrows, ncols, cell(r, c).value, name."""

    def __init__(self, rows, name="Sheet1"):
        self.name = name
        self._rows = rows
        self.nrows = len(rows)
        self.ncols = max(len(r) for r in rows)

    def cell(self, r, c):
        row = self._rows[r] if r < self.nrows else []
        return FakeCell(row[c] if c < len(row) else "")


class FakeBook:
    def __init__(self, sheet):
        self.nsheets = 1
        self._sheet = sheet

    def sheet_by_index(self, i):
        return self._sheet


N = 60                                         # booths per synthetic sheet


def booth_rows(ac=51, electors_cols=1):
    """[ac, ps, name, electors..., M, F, O, T, 0, 0, 1, BJP, v1, 2, SP, v2] for N booths."""
    out = []
    for i in range(1, N + 1):
        elec = [1000 + i] if electors_cols == 1 else [500 + i, 400 + i, 0, 900 + 2 * i]
        out.append([ac, i, f"SCHOOL {i}", *elec, 300 + i, 250 + i, 0, 550 + 2 * i, 0, 0, 1, "BJP", 300 + i, 2, "SP", 250 + i])
    return out


def standard_header(votes_label_1="Voters Secured", votes_label_2="Votes  Secured"):
    return [
        ["UTTAR PRADESH"], ["No. & Name of Assembly Constituency"], ["District-X"],
        ["AC No.", "Polling Station", "", "Total No. of Electors", "Voters Turnout", "", "", "", "No. of voters Identified", "Tendered", "CAND A", "", "", "CAND B", "", ""],
        ["", "No.", "Name", "", "Male", "Female", "Other", "Total", "", "", "S.No.", "Party Affiliation", votes_label_1, "S.No.", "Party Affiliation", votes_label_2],
        list(range(1, 17)),
    ]


class LabelTests(unittest.TestCase):
    def test_votes_secured_spellings(self):
        for label in ["Votes Secured", "Voters Secured", "Voter Secured", "Votes  Secured", "Votes Se cured", "Votes Se-cured"]:
            self.assertTrue(G.VOTES_RE.search(label), label)
        self.assertFalse(G.VOTES_RE.search("Total Voters"))

    def test_turnout_and_electors_label_variants(self):
        for label in ["Voters Turnout", "Voter turn out male", "voters yurn out", "Voter cast", "Number of persons who voted"]:
            self.assertTrue(G.TURNOUT_RE.search(label), label)
        for label in ["Total No. of Electors", "Total No of Voters", "Total electors"]:
            self.assertTrue(G.ELECTORS_RE.search(label), label)

    def test_form20_preamble_electors(self):
        sheet = FakeSheet([["FORM 20"], ["FINAL RESULT SHEET"], ["Total No. of  Electors in Assembly Constituency/segment  ....378401"]] + [[""]] * 20)
        self.assertEqual(G.form20_preamble_electors(FakeBook(sheet)), 378401)


class LayoutTests(unittest.TestCase):
    def check(self, rows, expect_electors_first=1001):
        res = G.parse_sheet(FakeSheet(rows))
        self.assertIsNotNone(res)
        self.assertEqual(len(res["booths"]), N)
        self.assertEqual(res["booths"][0]["electors"], expect_electors_first)
        parties = {f["party"] for f in res["facts"]}
        self.assertEqual(parties, {"BJP", "SP"})
        self.assertEqual(sum(f["votes"] for f in res["facts"] if f["party"] == "BJP"), sum(300 + i for i in range(1, N + 1)))
        return res

    def test_standard_layout_with_label_typos(self):
        res = self.check(standard_header() + booth_rows())
        self.assertEqual(res["booths"][0]["male"], 301)
        self.assertEqual(res["booths"][0]["polled"], 552)

    def test_extra_blank_leading_column(self):
        rows = [[""] + r for r in standard_header() + booth_rows()]
        self.check(rows)

    def test_electors_split_over_four_columns_uses_the_total(self):
        header = [["UTTAR PRADESH"], ["No. & Name"], ["District-X"],
                  ["AC No.", "Polling Station", "", "Total No. of Electors", "", "", "", "Voters Turnout", "", "", "", "Identified", "Tendered", "CAND A", "", "", "CAND B", "", ""],
                  ["", "No.", "Name", "", "", "", "", "Male", "Female", "Other", "Total", "", "", "S.No.", "Party Affiliation", "Votes Secured", "S.No.", "Party Affiliation", "Votes Secured"],
                  list(range(1, 20))]
        data = []
        for i in range(1, N + 1):
            data.append([51, i, f"S{i}", 500 + i, 400 + i, 0, 900 + 2 * i, 300 + i, 250 + i, 0, 550 + 2 * i, 0, 0, 1, "BJP", 300 + i, 2, "SP", 250 + i])
        res = G.parse_sheet(FakeSheet(header + data))
        self.assertIsNotNone(res)
        self.assertEqual(res["booths"][0]["electors"], 902)         # the total column, not the male-electors column

    def test_party_written_in_the_header_row(self):
        header = standard_header()
        header[4][11], header[4][14] = "Bharatiya Janata Party", "Samajwadi Party"     # party in the sub-header, data rows leave it blank
        rows = header + [r[:11] + [""] + r[12:14] + [""] + r[15:] for r in booth_rows()]
        res = G.parse_sheet(FakeSheet(rows))
        self.assertEqual({f["party"] for f in res["facts"]}, {"Bharatiya Janata Party", "Samajwadi Party"})

    def test_polling_station_number_inside_the_name(self):
        data = []
        for i in range(1, N + 1):
            data.append([187, "", f"{i}-PRIMARY SCHOOL", 1000 + i, 300 + i, 250 + i, 0, 550 + 2 * i, 0, 0, 1, "BJP", 300 + i, 2, "SP", 250 + i])
        res = G.parse_sheet(FakeSheet(standard_header() + data))
        self.assertEqual(len(res["booths"]), N)

    def test_repeated_polling_station_numbers_are_accepted(self):
        rows = standard_header() + booth_rows()
        for k in (10, 20, 30, 40):                                   # booths 4 and 4A are both stored as 4
            rows[6 + k][1] = rows[6 + k - 1][1]
        res = G.parse_sheet(FakeSheet(rows))
        self.assertEqual(len(res["booths"]), N)

    def test_a_sheet_without_a_booth_table_is_left_alone(self):
        self.assertIsNone(G.parse_sheet(FakeSheet([["Round 1"], ["Table"]] + [["x", 1, 2]] * 30)))
        self.assertIsNone(G.parse_sheet(FakeSheet([["tiny"]])))


class ChecksTests(unittest.TestCase):
    def test_structure_check(self):
        good = {"booths": 100, "electors": 100000.0, "polled": 60000.0, "booths_no_electors": 0}
        self.assertTrue(T._ac_ok(good))
        self.assertFalse(T._ac_ok({**good, "polled": 2.0}))                    # turnout 0%
        self.assertFalse(T._ac_ok({**good, "electors": 0.0}))                  # no electors
        self.assertFalse(T._ac_ok({**good, "booths_no_electors": 40}))         # electors missing on 40% of booths
        self.assertFalse(T._ac_ok({**good, "polled": 100000.0}))               # turnout 100%


if __name__ == "__main__":
    unittest.main()


class SniffReasonTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2] / "data"

    @unittest.skipUnless((ROOT / "2017" / "259.xls").exists(), "booth sheets not present")
    def test_reasons_are_read_from_the_files(self):
        self.assertIn("postal", G.sniff_reason(self.ROOT / "2017" / "259.xls"))
        self.assertIn("counting-round", G.sniff_reason(self.ROOT / "2017" / "31.xls"))
        self.assertIn("password", G.sniff_reason(self.ROOT / "2017" / "192.xls"))
        self.assertIn("Form 20", G.sniff_reason(self.ROOT / "2019" / "34.xls"))
