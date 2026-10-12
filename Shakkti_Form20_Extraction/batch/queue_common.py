"""Shared paths and CSV helpers for the Form 20 batch tools (build_queue.py, convert_queue.py)."""
import csv
import re
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOL_DIR.parent
DEFAULT_DATA_ROOT = REPO_ROOT / "data" / "2024"
QUEUE_DIR = TOOL_DIR / "queue"
SEC_PER_PAGE = 8.5  # README: about 8-9 s per page on a laptop CPU


def ac_of(name):
    """Assembly-constituency number from a file name such as '39HIn.pdf' or '2Eng (2).pdf'."""
    m = re.match(r"\s*(\d+)", name)
    return int(m.group(1)) if m else None


def lang_of(name):
    low = name.lower()
    return "Hin" if "hin" in low else "Eng" if "eng" in low else "?"


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    """Write via a temp file so a crash never leaves a half-written CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
