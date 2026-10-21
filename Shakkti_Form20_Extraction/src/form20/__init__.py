"""Form 20 (final result sheet) scan -> Excel extraction pipeline."""
import os
from pathlib import Path

_TESSDATA = Path(__file__).resolve().parents[2] / "tessdata"
if _TESSDATA.is_dir():
    os.environ.setdefault("TESSDATA_PREFIX", str(_TESSDATA))
