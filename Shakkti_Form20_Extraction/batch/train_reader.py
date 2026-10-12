"""Train the neural digit reader (src/form20/reader.py) on the cell crops harvested during conversion runs.

    FORM20_HARVEST_DIR=data/interim/harvest python batch/convert_queue.py ...      # collects labelled crops
    python batch/train_reader.py --data data/interim/harvest --out models/digit_reader.pt

Labels are the final row values, confirmed by each sheet's own arithmetic. 'hard' cells are the ones Tesseract got
wrong or left blank and the arithmetic corrected - the cases the reader exists for. Files (scans) are split into
training and validation sets, so the validation numbers measure how well the reader handles scans it never saw.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from form20.reader import BLANK, CROP_H, CROP_W, build_model, decode  # noqa: E402

MAX_LEN = 6


def load_dataset(data_dirs):
    """data_dirs: one folder or several -> dict(X uint8 (N,32,128), y list[str], hard uint8 (N,), file int (N,),
    files list[str]). A scan present in several folders is kept separately (its folder is part of its name)."""
    if isinstance(data_dirs, (str, Path)):
        data_dirs = [data_dirs]
    X, y, hard, fid, files = [], [], [], [], []
    for p in sorted(q for d in data_dirs for q in Path(d).glob("*.npz")):
        with np.load(p) as d:
            if "hard" not in d.files:
                continue
            labels = [str(s) for s in d["y"]]
            keep = [i for i, s in enumerate(labels) if s.isdigit() and 1 <= len(s) <= MAX_LEN]
            if not keep:
                continue
            X.append(d["X"][keep])
            y += [labels[i] for i in keep]
            hard.append(d["hard"][keep])
            fid += [len(files)] * len(keep)
        files.append(f"{p.parent.name}/{p.stem}")
    if not X:
        raise SystemExit(f"no usable .npz files with labelled crops in {', '.join(map(str, data_dirs))}")
    return {"X": np.concatenate(X), "y": y, "hard": np.concatenate(hard), "file": np.array(fid), "files": files}


def split_files(files, val_every=6):
    """Validation scans: every val_every-th file (at least 2 when there are enough files)."""
    val = {i for i in range(len(files)) if i % val_every == val_every - 1}
    if len(val) < 2 and len(files) >= 6:
        val |= {0, len(files) // 2}
    return val


def augment(x, torch):
    """Scan-like distortions on a GPU batch (B,1,32,128) in 0..1: small affine, stroke thickness, blur, noise, contrast."""
    import torch.nn.functional as F

    b = x.shape[0]
    dev = x.device
    u = lambda lo, hi: torch.empty(b, device=dev).uniform_(lo, hi)
    rot = u(-4, 4) * np.pi / 180
    sx, sy, sh = u(0.88, 1.12), u(0.88, 1.12), u(-0.12, 0.12)
    theta = torch.stack([torch.stack([sx * torch.cos(rot), -sy * torch.sin(rot) + sh, u(-0.05, 0.05)], 1),
                         torch.stack([sx * torch.sin(rot), sy * torch.cos(rot), u(-0.08, 0.08)], 1)], 1)
    x = F.grid_sample(x, F.affine_grid(theta, list(x.shape), align_corners=False), padding_mode="zeros",
                      align_corners=False)
    r = torch.rand(b, 1, 1, 1, device=dev)
    x = torch.where(r < 0.25, F.max_pool2d(x, 3, 1, 1), x)                                   # thicker strokes
    x = torch.where((r >= 0.25) & (r < 0.40), -F.max_pool2d(-x, 3, 1, 1), x)                # thinner strokes
    sigma = float(np.random.uniform(0.3, 1.4))
    k = torch.arange(-2, 3, device=dev).float()
    g = torch.exp(-(k ** 2) / (2 * sigma ** 2))
    g = (g / g.sum())
    blurred = F.conv2d(F.conv2d(x, g.view(1, 1, 1, 5), padding=(0, 2)), g.view(1, 1, 5, 1), padding=(2, 0))
    x = torch.where(torch.rand(b, 1, 1, 1, device=dev) < 0.5, blurred, x)
    x = x * u(0.65, 1.0).view(b, 1, 1, 1) + torch.randn_like(x) * u(0.0, 0.07).view(b, 1, 1, 1)
    specks = (torch.rand_like(x) < 0.0015).float()
    return (x + specks).clamp(0, 1)


def encode(labels, device, torch):
    flat = torch.tensor([int(c) + 1 for s in labels for c in s], dtype=torch.long)
    lens = torch.tensor([len(s) for s in labels], dtype=torch.long)
    return flat.to(device), lens.to(device)


def evaluate(model, X, y, hard, device, torch, batch=2048):
    model.eval()
    ok = np.zeros(len(y), bool)
    with torch.no_grad():
        for s in range(0, len(y), batch):
            xb = torch.from_numpy(X[s:s + batch].astype(np.float32) / 255.0).unsqueeze(1).to(device)
            lp = model(xb).log_softmax(-1).cpu()
            for j, l in enumerate(lp):
                ok[s + j] = decode(l)[0] == y[s + j]
    hard = hard.astype(bool)
    return {"all": float(ok.mean()), "easy": float(ok[~hard].mean()) if (~hard).any() else float("nan"),
            "hard": float(ok[hard].mean()) if hard.any() else float("nan"), "n_hard": int(hard.sum())}


def train(data_dir, out_path, epochs=20, batch=512, device=None, seed=0, hard_weight=4.0, log=print):
    import torch

    torch.manual_seed(seed)
    np.random.seed(seed)
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    ds = load_dataset(data_dir)
    val_files = split_files(ds["files"])
    is_val = np.isin(ds["file"], list(val_files))
    tr, va = np.nonzero(~is_val)[0], np.nonzero(is_val)[0]
    log(f"{len(ds['y']):,} cells from {len(ds['files'])} files; train {len(tr):,} / validation {len(va):,} "
        f"({len(val_files)} unseen files); hard cells: train {int(ds['hard'][tr].sum()):,}, val {int(ds['hard'][va].sum()):,}")
    if len(va) == 0:
        raise SystemExit("not enough files for a validation split")
    model = build_model().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    steps = epochs * max(1, len(tr) // batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=steps, pct_start=0.15)
    ctc = torch.nn.CTCLoss(blank=BLANK, zero_infinity=True)
    w = np.where(ds["hard"][tr] == 1, hard_weight, 1.0)
    w /= w.sum()
    Xv, yv, hv = ds["X"][va], [ds["y"][i] for i in va], ds["hard"][va]
    best, history = -1.0, []
    t0 = time.time()
    for ep in range(1, epochs + 1):
        model.train()
        order = np.random.choice(tr, size=(len(tr) // batch) * batch, replace=True, p=w)
        total = 0.0
        for s in range(0, len(order), batch):
            idx = np.sort(order[s:s + batch])
            xb = torch.from_numpy(ds["X"][idx].astype(np.float32) / 255.0).unsqueeze(1).to(device)
            xb = augment(xb, torch)
            targets, tlens = encode([ds["y"][i] for i in idx], device, torch)
            logp = model(xb).log_softmax(-1).permute(1, 0, 2)                 # (T, B, 11)
            ilens = torch.full((len(idx),), logp.shape[0], dtype=torch.long, device=device)
            loss = ctc(logp, targets, ilens, tlens)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            sched.step()
            total += loss.item()
        m = evaluate(model, Xv, yv, hv, device, torch)
        history.append(m)
        score = m["all"] + m["hard"] if m["hard"] == m["hard"] else m["all"]
        if score > best:
            best = score
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), out_path)
        log(f"epoch {ep:>2}/{epochs}  loss {total / max(1, len(order) // batch):.4f}  validation: all {m['all']:.4f}  "
            f"easy {m['easy']:.4f}  hard {m['hard']:.4f}  ({time.time() - t0:.0f}s)")
    return {"best": best, "last": history[-1], "val_files": sorted(ds["files"][i] for i in val_files)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Train the neural digit reader on harvested cell crops.")
    ap.add_argument("--data", nargs="+", default=["data/interim/harvest"], help="one or more harvest folders")
    ap.add_argument("--out", default="models/digit_reader.pt")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--device", default=None)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    res = train(args.data, args.out, args.epochs, args.batch, args.device)
    print("validation scans:", ", ".join(res["val_files"]))
    print(f"model saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
