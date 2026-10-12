import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "batch"))

from build_queue import classify  # noqa: E402
from convert_queue import LayoutNotRecognised, layout_gate, outcome_of, render_summary, review_reason, select_rows  # noqa: E402
from queue_common import ac_of, lang_of  # noqa: E402


def info(file, ac, status="", pages=10, size=2_000_000, md5="", label_ac=None, error=""):
    return {"file": file, "ac": ac, "label_ac": label_ac or ac, "lang": lang_of(file), "size": size,
            "pages": pages, "md5": md5, "bulk_status": status, "bulk_error": error}


class NameTests(unittest.TestCase):
    def test_ac_and_language_from_file_name(self):
        self.assertEqual(ac_of("39HIn.pdf"), 39)
        self.assertEqual(ac_of("2Eng (2).pdf"), 2)
        self.assertIsNone(ac_of("P37.pdf"))
        self.assertEqual(lang_of("39HIn.pdf"), "Hin")
        self.assertEqual(lang_of("1Eng.pdf"), "Eng")


class ClassifyTests(unittest.TestCase):
    def run_classify(self, by_ac, unmapped=(), done=(), stray=(), overrides=None):
        return classify(by_ac, list(unmapped), set(done), set(stray), overrides)

    def test_scanned_goes_to_tier_a_and_text_layer_failures_to_tier_b(self):
        by_ac = {1: [info("1Eng.pdf", 1, "SCANNED", pages=20)],
                 2: [info("2Hin.pdf", 2, "LEGACY_SKIP", pages=5)],
                 3: [info("3Hin.pdf", 3, "COMPLEX_SKIP", pages=7)],
                 4: [info("4Eng.pdf", 4, "SCANNED", pages=8)]}
        conv, rev = self.run_classify(by_ac)
        self.assertEqual([(r["ac"], r["tier"]) for r in conv], [(4, "A"), (1, "A"), (2, "B"), (3, "B")])
        self.assertEqual([r["priority"] for r in conv], [1, 2, 3, 4])      # tier, then fewest pages
        self.assertEqual(rev, [])

    def test_portrait_scan_is_not_queued_because_the_layout_is_unsupported(self):
        f = info("57Hin.pdf", 57, "SCANNED")
        f["layout"] = "portrait"
        conv, rev = self.run_classify({57: [f]})
        self.assertEqual(conv, [])
        self.assertEqual([(r["category"], r["blocks_conversion"]) for r in rev], [("UNSUPPORTED_LAYOUT", "yes")])

    def test_done_ac_is_left_out(self):
        by_ac = {1: [info("1Eng.pdf", 1, "SCANNED")]}
        self.assertEqual(self.run_classify(by_ac, done={1}), ([], []))

    def test_quarantined_and_unknown_status_need_review(self):
        by_ac = {5: [info("5Eng.pdf", 5, "REVIEW", error="row 3 bad")], 6: [info("6Hin.pdf", 6, "")]}
        conv, rev = self.run_classify(by_ac, stray={"5Eng.REVIEW.xlsx"})
        self.assertEqual([(r["ac"], r["tier"]) for r in conv], [(5, "Q")])     # quarantined: OCR as a second opinion
        self.assertEqual([(r["ac"], r["category"]) for r in rev], [(6, "NOT_IN_BULK_REPORT"), (5, "QUARANTINED")])
        self.assertIn("5Eng.REVIEW.xlsx", rev[1]["detail"])
        self.assertEqual([r["blocks_conversion"] for r in rev], ["yes", "no"])

    def test_duplicates_are_reviewed_with_matching_advice(self):
        same = [info("7Hin.pdf", 7, md5="aa"), info("7Hin (2).pdf", 7, md5="aa")]
        mixed = [info("8Eng.pdf", 8, md5="bb"), info("8Hin.pdf", 8, md5="cc")]
        resaved = [info("9Hin.pdf", 9, md5="dd"), info("9Hin (2).pdf", 9, md5="ee")]
        differ = [info("10Hin.pdf", 10, md5="ff", size=1), info("10Hin (1).pdf", 10, md5="gg", size=9)]
        conv, rev = self.run_classify({7: same, 8: mixed, 9: resaved, 10: differ})
        self.assertEqual(len(conv), 8)                                         # every copy is queued (tier D)
        self.assertTrue(all(r["tier"] == "D" for r in conv))
        self.assertTrue(all(r["blocks_conversion"] == "no" for r in rev))
        advice = {r["ac"]: r["suggested_action"] for r in rev}
        self.assertIn("Byte-identical", advice[7])
        self.assertIn("Eng and Hin", advice[8])
        self.assertIn("likely the same scan", advice[9])
        self.assertIn("more complete", advice[10])

    def test_override_converts_under_the_corrected_ac_and_flags_a_relabel(self):
        f = info("109Eng.pdf", 190, "SCANNED", label_ac=109)
        conv, rev = self.run_classify({190: [f]}, overrides={"109Eng.pdf": (190, "header says 190")})
        self.assertEqual([(r["ac"], r["file"]) for r in conv], [(190, "109Eng.pdf")])
        self.assertEqual(conv[0]["note"], "header says 190")
        self.assertEqual([(r["category"], r["blocks_conversion"]) for r in rev], [("RELABEL", "no")])
        self.assertIn("190Eng.pdf", rev[0]["suggested_action"])

    def test_unmapped_pdf_hints_at_the_ac_from_its_name(self):
        by_ac = {50: [info("50Hin.pdf", 50, "SCANNED")]}
        _, rev = self.run_classify(by_ac, unmapped=[info("P50.pdf", None, pages=1)])
        unmapped = [r for r in rev if r["category"] == "UNMAPPED"][0]
        self.assertIn("already has 50Hin.pdf", unmapped["detail"])


class SelectTests(unittest.TestCase):
    ROWS = [{"priority": str(i), "tier": t, "ac": str(a), "file": f"{a}Eng.pdf", "pages": str(p)}
            for i, (t, a, p) in enumerate([("A", 1, 5), ("A", 2, 9), ("A", 3, 30), ("B", 4, 6)], 1)]

    def test_tier_filter_and_priority_order(self):
        self.assertEqual([r["ac"] for r in select_rows(self.ROWS, {"A"})], ["1", "2", "3"])
        self.assertEqual([r["ac"] for r in select_rows(self.ROWS, {"A", "B"})], ["1", "2", "3", "4"])

    def test_done_and_failed_are_skipped_unless_retrying(self):
        got = select_rows(self.ROWS, {"A"}, done={"1Eng.pdf"}, failed={"2Eng.pdf"})
        self.assertEqual([r["ac"] for r in got], ["3"])
        got = select_rows(self.ROWS, {"A"}, done={"1Eng.pdf"}, failed={"2Eng.pdf"}, retry_failed=True)
        self.assertEqual([r["ac"] for r in got], ["2", "3"])

    def test_ac_limit_and_max_pages(self):
        self.assertEqual([r["ac"] for r in select_rows(self.ROWS, {"A"}, acs={2, 3})], ["2", "3"])
        self.assertEqual([r["ac"] for r in select_rows(self.ROWS, {"A"}, limit=2)], ["1", "2"])
        self.assertEqual([r["ac"] for r in select_rows(self.ROWS, {"A"}, max_pages=10)], ["1", "2"])


class LayoutGateTests(unittest.TestCase):
    PASS1 = "[x.pdf] language=Hindi columns={c} candidates={n} meta={{'electors': None}}"

    def test_gate_stops_the_run_when_too_few_candidates_are_detected(self):
        seen = []
        gate = layout_gate(seen.append)
        gate("[x.pdf] pass 1/2: locating tables on 5 pages")           # unrelated lines pass through
        with self.assertRaises(LayoutNotRecognised):
            gate(self.PASS1.format(c=9, n=2))
        with self.assertRaises(LayoutNotRecognised):
            gate(self.PASS1.format(c=4, n=-2))
        with self.assertRaises(LayoutNotRecognised):
            gate(self.PASS1.format(c=-1, n=-8))                          # no stable column lines at all
        self.assertEqual(len(seen), 4)                                  # every line is still logged

    def test_gate_lets_a_normal_layout_through(self):
        layout_gate(lambda m: None)(self.PASS1.format(c=20, n=14))

    PAGE = "[x.pdf] page {p}/10: {r} rows, {k} read as printed"

    def test_gate_stops_when_almost_nothing_is_read_as_printed(self):
        gate = layout_gate(lambda m: None)
        gate(self.PAGE.format(p=1, r=20, k=1))
        gate(self.PAGE.format(p=2, r=20, k=0))                    # too early to judge (fewer than 3 pages)
        with self.assertRaises(LayoutNotRecognised):
            gate(self.PAGE.format(p=3, r=20, k=1))

    def test_gate_keeps_a_file_that_is_mostly_read_as_printed(self):
        gate = layout_gate(lambda m: None)
        for p in range(1, 8):
            gate(self.PAGE.format(p=p, r=30, k=22))


class _Row:
    def __init__(self, values):
        self.values = values


class _Read:
    """The part of a form20 FileResult that official_score reads: candidates | valid rejected NOTA total tendered."""
    def __init__(self, cands, nota):
        self.n_cands = len(cands)
        self.rows = [_Row(list(cands) + [sum(cands), 0, nota, sum(cands) + nota, 0])]


class TextThenOcrTests(unittest.TestCase):
    OFF = {"candidates": [60, 30, 20, 10], "nota": 5}

    def run_with(self, text_read, ocr_read, off=OFF):
        import form20.pipeline as pipeline
        from convert_queue import run_process_pdf
        calls, logs = [], []

        def fake(pdf, candidates_csv=None, progress=None, official=None, expected_cols=None, text_layer=None):
            calls.append(text_layer)
            if text_layer is None:
                progress("[x.pdf] text layer found: numbers are read from the PDF, no OCR")
                return text_read
            return ocr_read
        real, pipeline.process_pdf = pipeline.process_pdf, fake
        try:
            return run_process_pdf("x.pdf", off, None, logs.append), calls
        finally:
            pipeline.process_pdf = real

    def test_a_text_read_that_equals_the_official_totals_is_kept_without_ocr(self):
        right = _Read([60, 30, 20, 10], 5)
        got, calls = self.run_with(right, _Read([1, 1, 1, 1], 1))
        self.assertIs(got, right)
        self.assertEqual(calls, [None])

    def test_a_text_read_that_misses_the_totals_is_read_by_ocr_too_and_the_closer_one_wins(self):
        text, ocr = _Read([60, 29, 20, 10], 5), _Read([60, 30, 20, 10], 5)
        got, calls = self.run_with(text, ocr)
        self.assertIs(got, ocr)
        self.assertEqual(calls, [None, False])

    def test_the_text_read_stays_when_ocr_is_no_closer(self):
        text, ocr = _Read([60, 29, 20, 10], 5), _Read([59, 29, 20, 10], 5)
        got, _ = self.run_with(text, ocr)
        self.assertIs(got, text)
        text, ocr = _Read([60, 29, 20, 10], 5), _Read([60, 29, 20, 10], 5)                 # a tie also goes to the text read
        got, _ = self.run_with(text, ocr)
        self.assertIs(got, text)

    def test_without_official_totals_the_text_read_is_taken_as_it_is(self):
        text = _Read([60, 29, 20, 10], 5)
        got, calls = self.run_with(text, _Read([60, 30, 20, 10], 5), off=None)
        self.assertIs(got, text)
        self.assertEqual(calls, [None])


class OutcomeTests(unittest.TestCase):
    def entry(self, ac, status="DONE", needs="no", **kw):
        return {"ac": str(ac), "file": f"{ac}Eng.pdf", "status": status, "needs_review": needs, "rows": "300", "exact": "290", "ok": "290",
                "auto_corrected": "5", "review": "0", "totals": "match", "review_reason": "", "error": "", "pages": "9",
                **kw}

    def test_outcome_buckets(self):
        self.assertEqual(outcome_of(self.entry(1)), "CLEAN")
        self.assertEqual(outcome_of(self.entry(2, needs="yes")), "FLAGGED")
        self.assertEqual(outcome_of(self.entry(3, status="FAILED", needs="yes")), "FAILED")

    def test_summary_lists_each_bucket_and_what_is_still_to_run(self):
        ledger = {e["file"]: e for e in (
            self.entry(1), self.entry(2, needs="yes", review_reason="3 REVIEW rows"),
            self.entry(3, status="FAILED", needs="yes", error="LayoutNotRecognised: 2 candidates"))}
        queue = [{"file": f"{a}Eng.pdf", "tier": t} for a, t in ((1, "A"), (2, "A"), (3, "A"), (4, "A"), (5, "B"))]
        text = render_summary(ledger, queue)
        self.assertIn("| CLEAN | 1 |", text)
        self.assertIn("| FLAGGED | 1 |", text)
        self.assertIn("| FAILED | 1 |", text)
        self.assertIn("tier A: 1, tier B: 1", text)
        self.assertIn("3 REVIEW rows", text)
        self.assertIn("LayoutNotRecognised: 2 candidates", text)


class ReviewReasonTests(unittest.TestCase):
    CLEAN = {"status": "DONE", "rows": "300", "exact": "280", "review": "0", "totals": "match", "page_errors": "0",
             "ac_check": "ok", "segment_read": "5-X"}

    def test_clean_file_needs_no_review(self):
        self.assertEqual(review_reason(self.CLEAN), "")

    def test_each_problem_is_reported(self):
        bad = dict(self.CLEAN, review="3", totals="DIFFER", page_errors="2", ac_check="MISMATCH", segment_read="190-L")
        why = review_reason(bad)
        for part in ("3 REVIEW rows", "totals differ", "2 pages without a table", "190-L"):
            self.assertIn(part, why)
        self.assertIn("not read", review_reason(dict(self.CLEAN, totals="not read")))
        self.assertIn("no rows", review_reason(dict(self.CLEAN, rows="0", exact="0")))

    def test_low_exact_read_rate_is_reported_as_unsupported_layout(self):
        self.assertIn("layout probably unsupported", review_reason(dict(self.CLEAN, exact="100")))
        self.assertEqual(review_reason(dict(self.CLEAN, exact="150")), "")      # exactly half is still accepted

    def test_failure_is_always_reviewed(self):
        self.assertIn("boom", review_reason({"status": "FAILED", "error": "boom"}))


if __name__ == "__main__":
    unittest.main()
