"""Neural digit reader: a small CNN + BiGRU with CTC that reads the digits of one table cell.

Tesseract reads every cell twice (see ocr.py); on noisy scans it drops digits or returns blanks. This reader is trained
on this project's own cells (batch/train_reader.py, labels confirmed by the sheets' arithmetic) and is added as one more
reading of every cell. It is optional: without a model file, or with FORM20_READER=off, nothing changes.

Input  : the cleaned binary ink crop of a cell, resized to height 32, left-aligned on a 32x128 canvas (prepare_crop).
Output : (digit string, confidence 0-100) from greedy CTC decoding.
"""
import os
from pathlib import Path

import cv2
import numpy as np

CROP_H, CROP_W = 32, 128
BLANK = 0                      # CTC blank; digit d is class d + 1
DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "models" / "digit_reader.pt"


def prepare_crop(crop):
    """Binary ink crop (255 = ink) -> (32x128 uint8 canvas, used width). Same layout as the stored training crops."""
    h, w = crop.shape
    nw = max(1, min(CROP_W, round(w * CROP_H / h)))
    img = cv2.resize(crop, (nw, CROP_H), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((CROP_H, CROP_W), np.uint8)
    canvas[:, :nw] = img
    return canvas, nw


def build_model():
    import torch.nn as nn

    class DigitReader(nn.Module):
        def __init__(self):
            super().__init__()

            def block(i, o, pool):
                return [nn.Conv2d(i, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                        nn.MaxPool2d(pool)]

            self.cnn = nn.Sequential(*block(1, 32, 2), *block(32, 64, 2), *block(64, 128, (2, 1)),
                                     *block(128, 128, (2, 1)))                       # 32x128 -> 2x32
            self.rnn = nn.GRU(256, 128, bidirectional=True, batch_first=True)
            self.out = nn.Linear(256, 11)

        def forward(self, x):                                  # x: (B, 1, 32, 128) in 0..1
            f = self.cnn(x)                                    # (B, 128, 2, 32)
            b, c, h, w = f.shape
            f = f.permute(0, 3, 1, 2).reshape(b, w, c * h)     # (B, 32, 256)
            f, _ = self.rnn(f)
            return self.out(f)                                 # (B, 32, 11) logits per time step

    return DigitReader()


def decode(logits):
    """Greedy CTC decoding of (T, 11) log-probabilities -> (digits, confidence 0-100). Confidence is the product of the
    per-step probabilities of the emitted symbols (a blank run counts as one symbol with its own probability)."""
    probs = logits.exp()
    best = probs.argmax(-1).tolist()
    pmax = probs.max(-1).values.tolist()
    text, conf, prev = [], 1.0, BLANK
    for k, p in zip(best, pmax):
        if k != prev:
            if k != BLANK:
                text.append(str(k - 1))
            conf *= p
        prev = k
    return "".join(text), 100.0 * conf


class Reader:
    def __init__(self, path=DEFAULT_MODEL, device=None):
        import torch

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = build_model().to(self.device)
        self.model.load_state_dict(torch.load(path, map_location=self.device))
        self.model.eval()

    def read(self, crops, batch=1024):
        """crops: list of binary ink crops (or None) -> [(digits, confidence)] in the same order ('' for None)."""
        torch = self.torch
        out = [("", 0.0)] * len(crops)
        idx = [i for i, c in enumerate(crops) if c is not None]
        for s in range(0, len(idx), batch):
            part = idx[s:s + batch]
            x = np.stack([prepare_crop(crops[i])[0] for i in part]).astype(np.float32) / 255.0
            with torch.no_grad():
                logp = self.model(torch.from_numpy(x).unsqueeze(1).to(self.device)).log_softmax(-1).cpu()
            for i, lp in zip(part, logp):
                out[i] = decode(lp)
        return out


_READER = None


def get_reader():
    """Process-wide reader, or None when disabled (FORM20_READER=off) or no model file exists."""
    global _READER
    path = os.environ.get("FORM20_READER", str(DEFAULT_MODEL))
    if path.lower() == "off" or not Path(path).exists():
        return None
    if _READER is None:
        _READER = Reader(path)
    return _READER
