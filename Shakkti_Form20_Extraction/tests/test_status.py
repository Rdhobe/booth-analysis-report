import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "batch"))

from status import ac_state, build_status, render_status_md  # noqa: E402


def led(ac, file, status="DONE", rows="300", repaired="0", error="", reason=""):
    return {"ac": str(ac), "file": file, "status": status, "rows": rows, "repaired_rows": repaired, "error": error,
            "review_reason": reason, "xlsx": f"out/{Path(file).stem}_Form20.xlsx" if status == "DONE" else ""}


FULL = {"verdict": "FULL"}


class AcStateTests(unittest.TestCase):
    def state(self, ac=7, excel=(), pdf=(7,), ledger=(), official=None, review=None):
        return ac_state(ac, set(excel), set(pdf), list(ledger), official or {}, review)[0]

    def test_existing_excel_wins(self):
        self.assertEqual(self.state(excel={7}, ledger=[led(7, "7Eng.pdf")]), "DONE_EXCEL")

    def test_official_match_is_verified_and_repair_is_labelled(self):
        off = {"7Eng_Form20.xlsx": FULL}
        self.assertEqual(self.state(ledger=[led(7, "7Eng.pdf")], official=off), "VERIFIED")
        self.assertEqual(self.state(ledger=[led(7, "7Eng.pdf", repaired="3")], official=off), "VERIFIED_REPAIRED")

    def test_converted_without_official_match_is_unverified(self):
        off = {"7Eng_Form20.xlsx": {"verdict": "PARTIAL", "detail": "col off by 4"}}
        self.assertEqual(self.state(ledger=[led(7, "7Eng.pdf")], official=off), "CONVERTED_UNVERIFIED")

    def test_failed_and_best_copy_wins(self):
        self.assertEqual(self.state(ledger=[led(7, "7Eng.pdf", status="FAILED", error="x")]), "FAILED")
        two = [led(7, "7Eng.pdf", status="FAILED", error="x"), led(7, "7Hin.pdf")]
        self.assertEqual(self.state(ledger=two, official={"7Hin_Form20.xlsx": FULL}), "VERIFIED")

    def test_decision_not_run_and_no_pdf(self):
        review = {"files": "7Eng.pdf; 7Hin.pdf", "category": "DUPLICATE", "suggested_action": "keep one"}
        self.assertEqual(self.state(review=review), "NEEDS_DECISION")
        self.assertEqual(self.state(), "NOT_RUN")
        self.assertEqual(self.state(pdf=()), "NO_PDF")


class BuildStatusTests(unittest.TestCase):
    def test_every_ac_gets_exactly_one_state_and_the_summary_adds_up(self):
        rows = build_status({1}, {1, 2, 3}, [led(2, "2Eng.pdf")], {"2Eng_Form20.xlsx": FULL}, [], max_ac=5)
        self.assertEqual([r["state"] for r in rows], ["DONE_EXCEL", "VERIFIED", "NOT_RUN", "NO_PDF", "NO_PDF"])
        text = render_status_md(rows)
        self.assertIn("Usable now: 2 of 5", text)
        self.assertIn("| NO_PDF | 2 |", text)

    def test_non_blocking_review_rows_do_not_hide_a_conversion(self):
        review = [{"ac": "2", "category": "RELABEL", "files": "2Eng.pdf", "suggested_action": "rename",
                   "blocks_conversion": "no"}]
        rows = build_status(set(), {2}, [], {}, review, max_ac=2)
        self.assertEqual(rows[1]["state"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
