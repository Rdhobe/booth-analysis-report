"""Tests for the Phase 1 AC-level models. Run:  python -m pytest Scripts/ml/test_ml.py -q"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402
import models as M  # noqa: E402

CFG = F.load_config()
FEATS = F.build_features(CFG)
FAST = copy.deepcopy(CFG)
FAST["typology"].update({"bootstrap_resamples": 6, "k_range": [3, 5]})


class FeatureTests(unittest.TestCase):
    def test_every_election_has_403_acs(self):
        self.assertEqual(set(FEATS.checks["acs_per_election"].values()), {403})

    def test_seat_counts_match_published_results(self):
        # Published results: 2012 SP 224, BSP 80, BJP 47; 2017 NDA 325 (BJP 312), SP+INC 54; 2022 NDA 273 (BJP 255), SP alliance 125.
        seats = FEATS.checks["seats_by_camp"]
        self.assertEqual((seats["VS2012"]["NDA"], seats["VS2012"]["SPF"], seats["VS2012"]["BSP"]), (47, 224, 80))
        self.assertEqual((seats["VS2017"]["NDA"], seats["VS2017"]["SPF"], seats["VS2017"]["BSP"]), (325, 54, 19))
        self.assertEqual((seats["VS2022"]["NDA"], seats["VS2022"]["SPF"]), (273, 125))

    def test_shares_sum_to_one(self):
        for e in FEATS.elections:
            total = FEATS.wide[[f"{c}_{e}" for c in FEATS.camps]].sum(axis=1)
            self.assertLess((total - 1).abs().max(), 1e-9)

    def test_ls2024_keeps_only_uttar_pradesh(self):
        ls, info = F.load_ls2024_candidates()
        self.assertEqual(int((ls["party"] != "NOTA").sum()), 4288)    # not Uttarakhand, whose AC numbers 1-70 collide
        self.assertEqual(len(info), 403)

    def test_allies_do_not_stand_against_their_front_leader(self):
        self.assertEqual(FEATS.checks["alliance_overlap_acs"]["VS2022"].get("NDA", 0), 0)
        self.assertEqual(FEATS.checks["alliance_overlap_acs"]["LS2024"].get("NDA", 0), 0)

    def test_incomplete_source_rows_are_kept_out_of_fitting(self):
        for ac in FEATS.checks["excluded_from_fitting"]:
            self.assertFalse(bool(FEATS.clean.loc[ac]))


class ModelTests(unittest.TestCase):
    def test_typology_is_repeatable(self):
        a = M.fit_typology(FEATS, FAST, CFG["seed"])
        b = M.fit_typology(FEATS, FAST, CFG["seed"])
        self.assertTrue((a["labels"] == b["labels"]).all())
        self.assertEqual(a["names"], b["names"])

    def test_surprise_is_repeatable_and_skips_incomplete_acs(self):
        a = M.compute_surprise(FEATS.wide, FEATS.clean, FEATS.model_camps, CFG, CFG["seed"])
        b = M.compute_surprise(FEATS.wide, FEATS.clean, FEATS.model_camps, CFG, CFG["seed"])
        self.assertTrue((a["flag"] == b["flag"]).all())
        self.assertFalse(a.loc[~FEATS.clean, "flag"].any())

    def test_a_very_large_shift_is_flagged(self):
        w = FEATS.wide.copy()
        ac = int(w.index[(FEATS.clean) & (w["NDA_VS2022"] < 0.40)][0])
        old = w.loc[ac, "NDA_VS2022"]
        new = old + 0.40
        scale = (1 - new) / (1 - old)
        for c in FEATS.model_camps:
            w.loc[ac, f"{c}_VS2022"] = new if c == "NDA" else w.loc[ac, f"{c}_VS2022"] * scale
        res = M.compute_surprise(w, FEATS.clean, FEATS.model_camps, CFG, CFG["seed"])
        self.assertTrue(bool(res.loc[ac, "flag"]))

    def test_baseline_bands_are_positive(self):
        bands = M.baseline_bands(FEATS.wide, FEATS.clean, CFG)
        for camp in CFG["surprise"]["camps"]:
            self.assertGreater(bands[camp]["band_last"], 0)
            self.assertGreater(bands[camp]["band_pooled"], 0)

    def test_look_alikes_exclude_the_ac_itself(self):
        ty = M.fit_typology(FEATS, FAST, CFG["seed"])
        got = M.look_alikes(ty["distance"], 86, 5)
        self.assertEqual(len(got), 5)
        self.assertNotIn(86, [a for a, _ in got])


if __name__ == "__main__":
    unittest.main()
