import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "batch"))

from status_report import cause_of, missing_acs, render  # noqa: E402


def row(ac, state, reason="r", group="Eng single-file", pdf=None):
    return {"ac": str(ac), "group": group, "pdf_files": pdf or f"{ac}Eng.pdf", "state": state, "reason": reason}


ROWS = [
    row(1, "DONE (verified)", "All candidate columns and NOTA match the official 2024 totals"),
    row(2, "CONVERTED, NOT VERIFIED", "Nearly right: a few digits misread (totals within 3% of official)"),
    row(3, "CONVERTED, NOT VERIFIED", "Sheet's own total rows counted as booths (x2)", group="Hin single-file"),
    row(4, "CONVERTED, NOT VERIFIED", "Sheet's own total rows counted as booths (x3)", group="Hin single-file"),
    row(5, "ON HOLD", "Different form layout (portrait page) the tool cannot read yet", group="Duplicate PDFs"),
]
SPLITS = [
    {"ac": "138", "source": "137Eng.pdf", "booths": "359", "verdict": "FULL"},
    {"ac": "144", "source": "141Eng.pdf", "booths": "340", "verdict": "PARTIAL"},
]


class ReportTests(unittest.TestCase):
    def test_summary_counts_and_done_list(self):
        text = render(ROWS, SPLITS, [138, 144, 190], today="2026-10-11")
        self.assertIn("Status on 2026-10-11", text)
        self.assertIn("## Done and verified (1)", text)
        self.assertIn("| Done (verified) | 1 | 0 | 0 | **1** |", text)
        self.assertIn("| Converted, not verified | 1 | 2 | 0 | **3** |", text)
        self.assertIn("| **Total** | 2 | 2 | 1 | **5** |", text)

    def test_reasons_are_grouped_and_every_unfinished_ac_is_listed(self):
        text = render(ROWS, SPLITS, [], today="2026-10-11")
        self.assertIn("### Total rows read as booths (2)", text)
        self.assertIn("- **ACs:** 3, 4", text)
        self.assertIn("### Portrait-page layout (1)", text)
        for ac in (2, 3, 4, 5):
            self.assertIn(f"| {ac} | ", text)

    def test_ac_outside_the_list_recovered_by_a_split_is_reported(self):
        text = render(ROWS, SPLITS, [138, 144, 190], today="2026-10-11")
        self.assertIn("AC 138 (from 137Eng.pdf, 359 booths)", text)
        self.assertIn("Recovered and verified from another PDF: 138", text)
        self.assertIn("Partly recovered, not verified: 144", text)
        self.assertIn("Still without a PDF of their own: 1 ACs: 144", text)

    def test_unknown_reason_is_kept_as_it_is(self):
        self.assertEqual(cause_of("something new")[0], "something new")

    def test_missing_acs_are_read_from_the_md(self):
        md = "# t\n\n## Missing ACs (3)\n\n34, 35,\n37\n\n## Duplicate-file ACs (1)\n\n2 (3 files)\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.md"
            p.write_text(md, encoding="utf-8")
            self.assertEqual(missing_acs(p), [34, 35, 37])


if __name__ == "__main__":
    unittest.main()
