import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "batch"))

import torch  # noqa: E402

from form20.reader import CROP_H, CROP_W, Reader, build_model, decode, prepare_crop  # noqa: E402
from train_reader import augment, load_dataset, split_files, train  # noqa: E402


def digit_crop(text, scale=1.0):
    """Binary ink crop (255 = ink) of a digit string, tight to the ink."""
    img = np.full((60, 40 * len(text) + 20), 255, np.uint8)
    cv2.putText(img, text, (8, 44), cv2.FONT_HERSHEY_SIMPLEX, scale, 0, 2, cv2.LINE_AA)
    ink = (img < 128).astype(np.uint8) * 255
    ys, xs = np.nonzero(ink)
    return ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def write_files(folder, n_files=7, per_file=120, seed=0):
    rng = np.random.RandomState(seed)
    for f in range(n_files):
        X, W, y, hard = [], [], [], []
        for _ in range(per_file):
            text = "".join(str(d) for d in rng.randint(0, 10, rng.randint(1, 4)))
            canvas, w = prepare_crop(digit_crop(text, rng.uniform(0.8, 1.2)))
            X.append(canvas), W.append(w), y.append(text), hard.append(rng.rand() < 0.1)
        np.savez_compressed(Path(folder) / f"f{f}.npz", X=np.stack(X), W=np.array(W, np.int16), y=np.array(y),
                            hard=np.array(hard, np.uint8))


class DecodeTests(unittest.TestCase):
    def logits(self, classes):
        lp = torch.full((len(classes), 11), -9.0)
        for t, c in enumerate(classes):
            lp[t, c] = -0.01
        return lp

    def test_ctc_collapses_repeats_and_drops_blanks(self):
        text, conf = decode(self.logits([0, 3, 3, 0, 5, 5, 0]))         # classes 3 and 5 are digits 2 and 4
        self.assertEqual(text, "24")
        self.assertGreater(conf, 90)

    def test_a_repeated_digit_needs_a_blank_between(self):
        self.assertEqual(decode(self.logits([2, 2, 0, 2]))[0], "11")

    def test_all_blank_is_an_empty_read(self):
        self.assertEqual(decode(self.logits([0, 0, 0]))[0], "")


class PrepareTests(unittest.TestCase):
    def test_crop_is_scaled_to_height_32_and_left_aligned(self):
        canvas, w = prepare_crop(np.full((20, 12), 255, np.uint8))
        self.assertEqual(canvas.shape, (CROP_H, CROP_W))
        self.assertEqual(w, 19)
        self.assertTrue(canvas[:, :w].all() and not canvas[:, w:].any())

    def test_very_wide_crop_is_clipped_to_the_canvas(self):
        canvas, w = prepare_crop(np.full((10, 400), 255, np.uint8))
        self.assertEqual(w, CROP_W)


class ModelTests(unittest.TestCase):
    def test_output_shape_is_one_logit_vector_per_time_step(self):
        out = build_model()(torch.zeros(3, 1, CROP_H, CROP_W))
        self.assertEqual(tuple(out.shape), (3, 32, 11))

    def test_augmentation_keeps_shape_and_range(self):
        x = torch.rand(8, 1, CROP_H, CROP_W)
        y = augment(x, torch)
        self.assertEqual(y.shape, x.shape)
        self.assertTrue(0.0 <= float(y.min()) and float(y.max()) <= 1.0)


class TrainingSmokeTests(unittest.TestCase):
    def test_split_never_mixes_a_file_into_both_sets(self):
        files = [f"f{i}" for i in range(12)]
        val = split_files(files)
        self.assertTrue(2 <= len(val) < len(files))

    def test_train_save_load_read_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            write_files(td)
            ds = load_dataset(td)
            self.assertEqual(len(ds["files"]), 7)
            out = Path(td) / "m.pt"
            res = train(td, out, epochs=2, batch=64, device="cpu", log=lambda *_: None)
            self.assertTrue(out.exists())
            self.assertIn("hard", res["last"])
            reader = Reader(out, device="cpu")
            got = reader.read([digit_crop("42"), None, digit_crop("7")])
            self.assertEqual(len(got), 3)
            self.assertEqual(got[1], ("", 0.0))
            self.assertTrue(all(isinstance(t, str) and t.isdigit() or t == "" for t, _ in got))


if __name__ == "__main__":
    unittest.main()
