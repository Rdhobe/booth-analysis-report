"""A review page for one AC: the rows worth a person's eye, each next to its scan, with the totals against the official ones
updating as the numbers are corrected.

    python batch/review_page.py --ac 190                  # data/2024/review/190_review.html
    python batch/review_page.py --ac 190 --max-rows 120   # at most this many rows

The page is one self-contained HTML file (the scan crops are embedded); open it in a browser. Nothing is uploaded anywhere.
The rows shown are the ones the extractor flagged: REVIEW and UNUSUAL, and auto-corrected rows in which a cell it had read was
changed. Every other row is taken as read and counted in the totals. Corrections are downloaded as a small JSON file and
applied with batch/apply_review.py. The AC's workbook must come from a converter run that writes the Row_Boxes sheet.
"""
import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cv2  # noqa: E402
import openpyxl  # noqa: E402

from queue_common import DEFAULT_DATA_ROOT, QUEUE_DIR, REPO_ROOT, read_csv  # noqa: E402
from review_common import column_sums, ledger_workbook, read_form20  # noqa: E402
from review_pack import rank_pairs  # noqa: E402
from verify_official import check_workbook, load_official  # noqa: E402

TEMPLATE = Path(__file__).with_name("review_page_template.html")
DEFAULT_OUT = REPO_ROOT / "data" / "2024" / "review"
SCORE = {"REVIEW": 3, "UNUSUAL": 2, "AUTO_CORRECTED": 1}


def read_boxes(path):
    """{(page, source_row): {page_index, box, plain, changed}} from the Row_Boxes sheet of a converted workbook."""
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        if "Row_Boxes" not in wb.sheetnames:
            raise SystemExit(f"{path} has no Row_Boxes sheet: convert the PDF again with the current extractor first")
        out = {}
        for r in list(wb["Row_Boxes"].iter_rows(values_only=True))[1:]:
            page, row, _, pidx, x0, y0, x1, y1, plain, changed = (list(r) + [None] * 10)[:10]
            out[(int(page), int(row))] = {
                "page_index": int(pidx), "box": (int(x0), int(y0), int(x1), int(y1)),
                "plain": [x.strip() for x in str(plain or "").split("|")],
                "changed": [int(i) for i in str(changed or "").split(",") if i != ""]}
        return out
    finally:
        wb.close()


def select_rows(booths, boxes, limit):
    """The rows to show, in page order: flagged ones first when there are more than `limit`. An auto-corrected row counts only
    if a cell the OCR had actually read was changed (a blank cell filled from the identities is not a doubt)."""
    scored = []
    for b in booths:
        info = boxes.get((b["page"], b["page_row"]))
        if info is None:
            continue
        score = SCORE.get(b["status"], 0)
        if b["status"] == "AUTO_CORRECTED" and not any(i < len(info["plain"]) and info["plain"][i] != "" for i in info["changed"]):
            score = 0
        if score:
            scored.append((-score, b["page"], b["page_row"], b))
    scored.sort(key=lambda t: t[:3])
    chosen = [t[3] for t in scored[:limit]]
    return sorted(chosen, key=lambda b: (b["page"], b["page_row"]))


def row_values(b, nc):
    return list(b["cands"]) + [b["valid"], b["rejected"], b["nota"], b["total"], b["tendered"]][: 5]


def build_data(ac, official_ac, form, boxes, workbook, pdf_name, limit, crop_fn):
    """Everything the page needs, as a JSON-able dict. crop_fn(info) -> data URI of the scan crop ('' for none)."""
    nc = form["nc"]
    cand, metrics = column_sums(form)
    pairs = rank_pairs(cand, official_ac["candidates"])
    chosen = select_rows(form["booths"], boxes, limit)
    keys = {(b["page"], b["page_row"]) for b in chosen}
    rest = [b for b in form["booths"] if (b["page"], b["page_row"]) not in keys]
    candidates = []
    for j in range(nc):
        name, votes = pairs.get(j, ("", 0))
        candidates.append({"label": form["labels"][j][:24] or f"col {j + 1}", "name": name, "official": votes,
                           "base": sum((b["cands"][j] or 0) for b in rest)})
    rows = []
    for b in chosen:
        info = boxes[(b["page"], b["page_row"])]
        rows.append({"key": f"p{b['page']}r{b['page_row']}", "page": b["page"], "row": b["page_row"], "serial": b["serial"],
                     "status": b["status"], "note": b["note"] or "", "values": row_values(b, nc), "plain": info["plain"],
                     "changed": info["changed"], "score": SCORE.get(b["status"], 0), "img": crop_fn(info)})
    return {"ac": ac, "name": official_ac["name"], "pdf": pdf_name, "workbook": str(workbook), "total_rows": len(form["booths"]),
            "candidates": candidates,
            "nota": {"official": official_ac["nota"], "base": sum((b["nota"] or 0) for b in rest)}, "rows": rows}


def render_html(data):
    text = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return text.replace("__DATA__", payload).replace("__AC__", str(data["ac"]))


def make_cropper(pdf_path, width=1500, quality=70):
    """crop_fn that cuts a row (and half a row above and below) from the page, as a JPEG data URI. Pages are rendered once."""
    from form20.imaging import load_page
    cache = {}

    def crop(info):
        idx = info["page_index"]
        if idx not in cache:
            cache.clear()
            cache[idx] = load_page(str(pdf_path), idx)[0]
        gray = cache[idx]
        x0, y0, x1, y1 = info["box"]
        pad = int(0.6 * (y1 - y0))
        part = gray[max(0, y0 - pad):min(gray.shape[0], y1 + pad), max(0, x0 - 5):x1 + 5]
        if part.shape[1] > width:
            part = cv2.resize(part, (width, int(part.shape[0] * width / part.shape[1])), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", part, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else ""
    return crop


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a review page for one AC.")
    ap.add_argument("--ac", type=int, required=True)
    ap.add_argument("--max-rows", type=int, default=150)
    ap.add_argument("--xlsx", help="the workbook to use (default: the AC's best converted workbook in the ledger)")
    ap.add_argument("--queue-dir", default=str(QUEUE_DIR))
    ap.add_argument("--pdf-dir", default=str(DEFAULT_DATA_ROOT / "PDF"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    official = load_official()
    ledger = [r for r in read_csv(Path(args.queue_dir) / "conversion_ledger.csv") if int(r["ac"]) == args.ac]
    if args.xlsx:
        row = next((r for r in ledger if r["status"] == "DONE" and Path(r["xlsx"]).name == Path(args.xlsx).name), None) or ledger[0]
        xlsx = args.xlsx
    else:
        row, _ = ledger_workbook(args.ac, ledger, official[args.ac], check_workbook)
        if row is None:
            raise SystemExit(f"AC {args.ac}: no converted workbook in the ledger")
        xlsx = row["xlsx"]
    form, boxes = read_form20(xlsx), read_boxes(xlsx)
    pdf = Path(args.pdf_dir) / row["file"]
    data = build_data(args.ac, official[args.ac], form, boxes, xlsx, row["file"], args.max_rows, make_cropper(pdf))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.ac}_review.html"
    path.write_text(render_html(data), encoding="utf-8")
    print(f"AC {args.ac}: {len(data['rows'])} of {len(form['booths'])} rows to look at -> {path} ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
