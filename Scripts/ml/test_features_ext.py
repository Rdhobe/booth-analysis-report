"""Tests for the booth-sheet aggregation, extended features and extended backtest. Run:  python -m pytest Scripts/ml/test_features_ext.py -q"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ac_booth_totals as T  # noqa: E402
import backtest_ext as B  # noqa: E402
import features as F  # noqa: E402
import features_ext as X  # noqa: E402

GENERATED = X.PROC / "ac_features_ext.csv"


class PartyNameTests(unittest.TestCase):
    def test_spellings_seen_on_the_sheets_map_to_one_code(self):
        for raw, code in [("B.J.P.", "BJP"), ("B.J.P", "BJP"), ("Bharatiya Janata Party", "BJP"), ("S.P.", "SP"), ("SAMAJWADI PARTY", "SP"),
                          ("B.S.P", "BSP"), ("INDIAN NATIONAL CONGRESS PARTY", "INC"), ("I.N.C", "INC"), ("APNA DAL (SONELAL)", "ADS"),
                          ("AD", "ADS"), ("HKKJRH; TURK IKVHZ", "BJP")]:
            self.assertEqual(X.canon_party(raw), code, raw)

    def test_junk_is_not_guessed(self):
        for raw in [",,", '"', "B", "S", "I"]:
            self.assertEqual(X.canon_party(raw), "", raw)


class NameMatchTests(unittest.TestCase):
    def test_same_candidate_written_two_ways(self):
        self.assertTrue(X.same_person("Mohammad Abdullah Azam Khan", "Abdullah Azam Khan"))
        self.assertTrue(X.same_person("DR. SURABHI", "Surabhi"))   # one distinctive token left after dropping the title
        self.assertFalse(X.same_person("Ram Naresh Rawat", "Shyam Sunder"))
        self.assertFalse(X.same_person("", "Anyone"))


class AcNumberRepairTests(unittest.TestCase):
    @staticmethod
    def booths(acs):
        return [{"ac": a} for a in acs], [{"ac": a} for a in acs]

    def test_single_wrong_ac_is_moved_to_the_files_ac(self):
        b, f = self.booths([1] * 300)
        note = T.fix_ac_numbers(b, f, 257)
        self.assertTrue(note and all(x["ac"] == 257 for x in b + f))

    def test_serials_read_as_ac_numbers_are_moved(self):
        b, f = self.booths(list(range(2, 60)))                 # every booth became its own "AC"
        T.fix_ac_numbers(b, f, 170)
        self.assertEqual({x["ac"] for x in b}, {170})

    def test_a_real_multi_ac_file_is_kept(self):
        b, f = self.booths([214] * 330 + [215] * 340 + [216] * 335)
        self.assertEqual(T.fix_ac_numbers(b, f, 214), "")
        self.assertEqual({x["ac"] for x in b}, {214, 215, 216})

    def test_numbers_outside_1_to_403_are_dropped_from_a_multi_ac_file(self):
        b, f = self.booths([10] * 300 + [11] * 300 + [999] * 5)
        T.fix_ac_numbers(b, f, 10)
        self.assertEqual({x["ac"] for x in b}, {10, 11})


class SeatLevelLokSabhaTests(unittest.TestCase):
    def test_shares_are_valid_and_match_known_statewide_levels(self):
        d = X.pc_level_ls()
        self.assertEqual(len(d), 80)
        for y in ("09", "14", "19", "24"):
            parts = d[[f"ls{y}_{c}" for c in ("bjp", "ads", "sp", "bsp", "inc", "rld", "oth")]]
            self.assertTrue(np.allclose(parts.sum(axis=1), 1.0))
            self.assertTrue((parts >= -1e-9).all().all())
        self.assertAlmostEqual(d["ls19_nda"].mean(), 0.506, delta=0.02)     # BJP + Apna Dal (S) in 2019, about 50.6% on average per seat
        self.assertGreater(d["ls14_nda"].mean(), 0.40)


@unittest.skipUnless(GENERATED.exists(), "run Scripts/ml/features_ext.py first")
class TaskFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feats = F.build_features(F.load_config())
        cls.ext = pd.read_csv(GENERATED, index_col="ac")

    def test_both_tasks_use_the_same_feature_names(self):
        xa, ya = B.task_frame(self.feats, self.ext, B.TASKS["A"])
        xb, yb = B.task_frame(self.feats, self.ext, B.TASKS["B"])
        self.assertEqual(list(xa.columns), list(xb.columns))
        self.assertEqual(list(ya.columns), list(yb.columns))

    def test_features_do_not_depend_on_the_target_election(self):
        spec = B.TASKS["B"]
        x1, _ = B.task_frame(self.feats, self.ext, spec)
        wide = self.feats.wide.copy()
        for c in B.FRONTS:
            wide[f"{c.upper()}_{spec['target']}"] = 0.123          # scramble the 2022 results
        scrambled = F.Features(wide=wide, winners=self.feats.winners, meta=self.feats.meta, clean=self.feats.clean, camps=self.feats.camps,
                               model_camps=self.feats.model_camps, elections=self.feats.elections, checks=self.feats.checks)
        x2, _ = B.task_frame(scrambled, self.ext, spec)
        pd.testing.assert_frame_equal(x1, x2)

    def test_baselines_stay_between_0_and_1_and_have_the_target_shape(self):
        xb, yb = B.task_frame(self.feats, self.ext, B.TASKS["B"])
        for name, pred in B.baselines(xb, yb).items():
            self.assertEqual(list(pred.columns), B.FRONTS, name)
            self.assertTrue(pred.dropna().ge(0).all().all() and pred.dropna().le(1).all().all(), name)

    def test_score_is_zero_for_a_perfect_prediction(self):
        y = pd.DataFrame({"nda": [0.5, 0.4], "opp": [0.3, 0.4], "bsp": [0.1, 0.1]})
        s = B.score(y, y)
        self.assertEqual(s["mean_mae_pts"], 0.0)
        self.assertEqual(s["lead_call_accuracy"], 1.0)

    def test_gates_leave_missing_values_not_guesses(self):
        self.assertTrue(self.ext["turnout_22"].isna().sum() > 0)           # 2022 sheets cover about half the ACs
        self.assertTrue(self.ext["turnout_17_best"].notna().all())          # filled from the 2017 roll file


@unittest.skipUnless(GENERATED.exists() and (X.PROC / "ac_booth_coverage.csv").exists() and (X.OUT / "features_ext_report.json").exists(),
                     "run ac_booth_totals.py and features_ext.py first")
class CoverageOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_insights as BI
        cls.BI = BI
        cls.ext = BI.load_ext()

    def test_statewide_turnout_matches_published_levels(self):
        rows = {r["election"]: r for r in self.BI.statewide_turnout(self.ext)}
        self.assertEqual(set(rows), {"VS2017", "LS2019", "VS2022", "LS2024"})
        for r in rows.values():
            self.assertGreaterEqual(r["acs"], 380)                      # at least 380 of 403 constituencies behind each figure
            self.assertTrue(0.54 < r["turnout"] < 0.64, r)
        self.assertTrue(0.595 < rows["VS2017"]["turnout"] < 0.625)      # published 2017 turnout was about 61%
        self.assertTrue(0.55 < rows["LS2024"]["turnout"] < 0.59)        # 2024 EVM turnout about 57%

    def test_turnout_block_is_none_for_unknown_ac_and_never_guesses(self):
        self.assertIsNone(self.BI.turnout_block(self.ext, 9999))
        b = self.BI.turnout_block(self.ext, 86)
        self.assertEqual(set(b["turnout"]), {"VS2017", "LS2019", "VS2022", "LS2024"})
        for v in b["turnout"].values():
            self.assertTrue(v is None or 0.30 <= v <= 0.95)

    def test_data_coverage_describes_every_unread_file(self):
        cov = self.BI.data_coverage(self.ext)
        self.assertEqual([e["election"] for e in cov["by_election"]], ["VS2017", "LS2019", "VS2022"])
        for e in cov["by_election"]:
            self.assertEqual(sum(e["readers"].values()), e["acs_read"])
            self.assertGreater(e["acs_read"], e["first_run"]["read"])  # cleaning added constituencies
            self.assertEqual(e["files"] - sum(len(u["files"]) for u in e["unread"]) >= 0, True)
            for u in e["unread"]:
                self.assertTrue(u["reason"] and u["files"])

    def test_reason_for_known_unreadable_files(self):
        import booth_sheets_generic as G
        T._install_xlsx_support() if hasattr(T, "_install_xlsx_support") else None
        for rel, word in (("2017/259.xls", "postal"), ("2017/31.xls", "counting-round")):
            path = X.ROOT / "data" / rel
            if path.exists():
                self.assertIn(word, G.sniff_reason(path), rel)


if __name__ == "__main__":
    unittest.main()
