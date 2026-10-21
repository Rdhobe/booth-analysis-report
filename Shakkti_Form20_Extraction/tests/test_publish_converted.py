import csv
import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "batch"))

from publish_converted import REVIEWED, publish  # noqa: E402


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def workbook(path, marker):
    wb = openpyxl.Workbook()
    wb.active["A1"] = marker
    wb.save(path)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.staged, self.out, self.queue = t / "staged", t / "converted", t / "queue"
        for d in (self.staged, self.queue):
            d.mkdir()
        workbook(self.staged / "1.xlsx", "one")
        workbook(self.staged / "3.xlsx", "three")
        workbook(self.staged / "9.xlsx", "nine")                 # verified, outside the priority list (cut from 3's PDF)
        write_csv(self.queue / "priority_180_status.csv", [
            {"ac": 1, "group": "g", "pdf_files": "1Eng.pdf", "state": "DONE (verified)", "reason": "ok"},
            {"ac": 2, "group": "g", "pdf_files": "2Eng.pdf", "state": "FAILED", "reason": "scan too poor"},
            {"ac": 3, "group": "g", "pdf_files": "3Eng.pdf", "state": "DONE (verified)", "reason": "ok"}])
        write_csv(self.queue / "conversion_ledger.csv", [
            {"ac": 1, "file": "1Eng.pdf", "status": "DONE", "xlsx": "x/1Eng_Form20.xlsx", "source": "text layer", "review": "0"},
            {"ac": 3, "file": "3Eng.pdf", "status": "DONE", "xlsx": "x/3Eng_Form20.xlsx", "source": "ocr", "review": "2"}])
        write_csv(self.queue / "official_check.csv", [
            {"file": "1Eng_Form20.xlsx", "verdict": "FULL"}, {"file": "3Eng_Form20.xlsx", "verdict": "FULL"}])
        write_csv(self.queue / "split_report.csv", [
            {"ac": 9, "source": "3Eng.pdf", "booths": "10", "verdict": "FULL", "columns_exact": "3/3", "file": "f"}])

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self):
        return {int(r["ac"]): r for r in csv.DictReader(open(self.out / "MANIFEST.csv", encoding="utf-8-sig"))}

    def test_verified_workbooks_are_copied_and_every_ac_is_listed(self):
        copied, rows = publish(self.staged, self.out, self.queue)
        self.assertEqual(copied, [1, 3, 9])
        self.assertTrue((self.out / "1.xlsx").exists() and not (self.out / "2.xlsx").exists())
        m = self.manifest()
        self.assertEqual((m[1]["status"], m[1]["how_produced"]), ("VERIFIED", "read from the PDF text layer (exact digits)"))
        self.assertEqual((m[2]["status"], m[2]["output_file"], m[2]["note_or_reason"]), ("FAILED", "", "scan too poor"))
        self.assertEqual(m[3]["note_or_reason"], "2 row(s) flagged for a glance")
        self.assertEqual((m[9]["in_priority_180"], m[9]["input_pdf"]), ("no", "3Eng.pdf"))

    def test_a_workbook_corrected_by_a_person_is_never_overwritten(self):
        self.out.mkdir()
        workbook(self.out / "2.xlsx", "corrected by hand")
        write_csv(self.out / "MANIFEST.csv", [{"ac": 2, "in_priority_180": "yes", "status": "VERIFIED", "output_file": "converted/2.xlsx",
                                              "input_pdf": "2Eng.pdf", "how_produced": REVIEWED, "check": "c", "note_or_reason": ""}])
        workbook(self.staged / "2.xlsx", "from the converter")
        publish(self.staged, self.out, self.queue)
        self.assertEqual(openpyxl.load_workbook(self.out / "2.xlsx").active["A1"].value, "corrected by hand")
        self.assertEqual(self.manifest()[2]["how_produced"], REVIEWED)


if __name__ == "__main__":
    unittest.main()
