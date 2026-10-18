"""Build the single-file Insights demo page from the generated JSON.

Run after build_insights.py:
    python Scripts/ml/build_demo_page.py

Reads  output/ml/ac_insights.json, output/ml/model_card.json, Scripts/ml/templates/insights_demo.html
Writes output/ml/insights_demo.html  (data inlined: no server, no network except the web font)
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "ml"
TEMPLATE = Path(__file__).resolve().parent / "templates" / "insights_demo.html"
log = logging.getLogger("ml.page")


def _inline(path: Path) -> str:
    """JSON text safe to put inside a <script> element."""
    text = json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/").replace("<!--", "<\\!--")


def _standalone(fragment: str) -> str:
    """Wrap the fragment so it opens correctly from disk: doctype, UTF-8 charset, viewport; head part split off."""
    head, body = fragment.split('<div class="top">', 1)
    return "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        head + "</head>",
        "<body>",
        '<div class="top">' + body,
        "</body>",
        "</html>",
        "",
    ])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--fragment", type=Path, default=None, help="also write the page without the html/head/body wrapper")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/", _inline(args.out / "ac_insights.json"))
    html = html.replace("/*__CARD__*/", _inline(args.out / "model_card.json"))
    target = args.out / "insights_demo.html"
    target.write_text(_standalone(html), encoding="utf-8")
    log.info("wrote %s (%d KB)", target, target.stat().st_size // 1024)
    if args.fragment:                                  # for hosts that supply their own <html>/<head>/<body>
        args.fragment.write_text(html, encoding="utf-8")
        log.info("wrote fragment %s", args.fragment)


if __name__ == "__main__":
    main()
