"""Build the Form 20 work queue from the PDF/Excel folders and the earlier bulk-run reports.

    python batch/build_queue.py [--data-root data/2024] [--queue-dir queue]

Regenerated on every run (nothing is hand-edited):
    queue/to_convert.csv   PDFs for the OCR converter, in run order (tier, then smallest first)
    queue/to_review.csv    ACs that need a person's decision first
    queue/README.md        counts and what each bucket means
Reads queue/ac_overrides.csv (hand-maintained: file,ac,reason) for mislabelled PDFs.
Read-only on the data folders.
"""
import argparse
import hashlib
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from queue_common import DEFAULT_DATA_ROOT, QUEUE_DIR, SEC_PER_PAGE, ac_of, lang_of, read_csv, write_csv  # noqa: E402

MAX_AC = 403
TIER_OF_STATUS = {"SCANNED": "A", "LEGACY_SKIP": "B", "COMPLEX_SKIP": "B"}
TO_CONVERT_FIELDS = ["priority", "tier", "ac", "file", "lang", "pages", "layout", "size_mb", "est_min", "bulk_status",
                     "note"]
TO_REVIEW_FIELDS = ["ac", "category", "files", "detail", "suggested_action", "blocks_conversion"]
CATEGORY_MEANING = {
    "DUPLICATE": "More than one PDF for the AC - pick the right copy before converting.",
    "QUARANTINED": "The text-layer converter produced a workbook that failed validation (`.REVIEW.xlsx`).",
    "NOT_IN_BULK_REPORT": "Single PDF the earlier bulk run never processed - unknown whether scanned or text.",
    "OK_NOT_FILED": "Bulk run reported OK but no Excel is in data/2024/EXCEL.",
    "UNSUPPORTED_LAYOUT": "Portrait sheet - a different Form 20 variant; the first two piloted files of this kind came out unusable.",
    "RELABEL": "File name disagrees with the AC printed on the page (conversion is not blocked).",
    "UNMAPPED": "No AC number in the file name.",
}


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pdf_shape(path):
    """(page count, 'landscape' | 'portrait') - the extractor is only proven on landscape sheets."""
    try:
        import fitz

        with fitz.open(path) as doc:
            rect = doc[0].rect          # PyMuPDF applies the page rotation flag
            return doc.page_count, "landscape" if rect.width > rect.height else "portrait"
    except Exception:
        return 0, ""


def load_bulk_status(pdf_dir):
    """file name -> (status, error text) from the Eng and Hin bulk reports."""
    out = {}
    for name in ("bulk_eng_report.csv", "bulk_hin_report.csv"):
        for r in read_csv(Path(pdf_dir) / name):
            out[Path(r["rel"].replace("\\", "/")).name] = (r["status"], r.get("error", ""))
    return out


def load_overrides(path):
    return {r["file"]: (int(r["ac"]), r.get("reason", "")) for r in read_csv(path)}


def collect_pdfs(pdf_dir, overrides):
    """-> (infos grouped by AC, infos without an AC number). An override replaces the AC taken from the name."""
    by_ac, unmapped = defaultdict(list), []
    for p in sorted(Path(pdf_dir).glob("*.pdf")):
        label_ac = ac_of(p.name)
        ac = overrides[p.name][0] if p.name in overrides else label_ac
        info = {"file": p.name, "ac": ac, "label_ac": label_ac, "lang": lang_of(p.name),
                "size": p.stat().st_size, "path": p}
        (by_ac[ac] if ac else unmapped).append(info)
    return by_ac, unmapped


def fmt_file(i):
    md5 = f", md5 {i['md5'][:6]}" if i.get("md5") else ""
    return f"{i['file']} ({i['size'] / 1e6:.1f} MB, {i['pages']} p, bulk={i.get('bulk_status') or 'not run'}{md5})"


def duplicate_advice(files):
    if len({i["md5"] for i in files}) == 1:
        return "Byte-identical copies: keep one, delete the rest, then convert."
    if len({i["lang"] for i in files}) > 1:
        return ("Eng and Hin copies of the same AC: check which is complete (a Hin copy may still have a usable "
                "text layer), keep one, then convert.")
    if len({(i["size"], i["pages"]) for i in files}) == 1:
        return "Same size and page count but different hash: likely the same scan re-saved. Keep one, then convert."
    return "Copies differ in size/pages: open both, keep the more complete one, then convert."


def convert_row(tier, ac, f, note=""):
    return {
        "tier": tier, "ac": ac, "file": f["file"], "lang": f["lang"], "pages": f["pages"], "layout": f.get("layout", ""),
        "size_mb": round(f["size"] / 1e6, 1), "est_min": round(f["pages"] * SEC_PER_PAGE / 60, 1),
        "bulk_status": f.get("bulk_status") or "not run", "note": note,
    }


def classify(by_ac, unmapped, done_acs, stray_xlsx=(), overrides=None):
    """Pure function: split the ACs that still have no Excel into (to_convert rows, to_review rows).

    Every info dict needs file, ac, label_ac, lang, size, pages, md5 (duplicates only), bulk_status, bulk_error.
    """
    overrides = overrides or {}
    to_convert, to_review = [], []
    for ac in sorted(by_ac):
        if ac in done_acs:
            continue
        files = by_ac[ac]
        if len(files) > 1:
            to_review.append({
                "ac": ac, "category": "DUPLICATE", "files": "; ".join(i["file"] for i in files),
                "detail": " | ".join(fmt_file(i) for i in files),
                "suggested_action": duplicate_advice(files) + " Every copy is queued (tier D); the one that verifies "
                                    "against the official totals is kept.",
                "blocks_conversion": "no",
            })
            to_convert += [convert_row("D", ac, i, f"copy of AC {ac}: keep whichever copy verifies") for i in files
                           if i.get("layout") != "portrait"]
            continue
        f = files[0]
        st = f.get("bulk_status") or ""
        if st == "REVIEW":
            stem = Path(f["file"]).stem
            quarantined = f"{stem}.REVIEW.xlsx" in stray_xlsx
            to_review.append({
                "ac": ac, "category": "QUARANTINED", "files": f["file"],
                "detail": (f"{stem}.REVIEW.xlsx; " if quarantined else "") + f.get("bulk_error", "")[:160],
                "suggested_action": "Queued for OCR (tier Q); compare with the quarantined workbook and keep whichever "
                                    "verifies against the official totals.",
                "blocks_conversion": "no",
            })
            to_convert.append(convert_row("Q", ac, f, "quarantined by the text-layer converter; OCR as a second opinion"))
        elif st in TIER_OF_STATUS and f.get("layout") == "portrait":
            to_review.append({
                "ac": ac, "category": "UNSUPPORTED_LAYOUT", "files": f["file"], "detail": fmt_file(f),
                "suggested_action": "Portrait sheet (a different Form 20 variant); the piloted files of this kind came "
                                    "out unusable. Needs a layout adapter in the tool, or manual entry.",
                "blocks_conversion": "yes",
            })
        elif st in TIER_OF_STATUS:
            note = overrides[f["file"]][1] if f["file"] in overrides else ""
            to_convert.append(convert_row(TIER_OF_STATUS[st], ac, f, note))
        else:
            cat = "OK_NOT_FILED" if st == "OK" else "NOT_IN_BULK_REPORT"
            to_review.append({
                "ac": ac, "category": cat, "files": f["file"], "detail": fmt_file(f),
                "suggested_action": "Check the file, then convert (text-layer converter first, OCR if it is a scan).",
                "blocks_conversion": "yes",
            })

    for f in sorted((i for files in by_ac.values() for i in files), key=lambda i: i["file"]):
        if f["file"] in overrides:
            _, reason = overrides[f["file"]]
            to_review.append({
                "ac": f["ac"], "category": "RELABEL", "files": f["file"],
                "detail": f"labelled AC {f['label_ac']}, header says AC {f['ac']}. {reason}",
                "suggested_action": (f"Rename the PDF to {f['ac']}{f['lang']}.pdf and delete any stray "
                                     f"{Path(f['file']).stem}.REVIEW.xlsx; AC {f['label_ac']} then counts as missing."),
                "blocks_conversion": "no",
            })
    for f in unmapped:
        m = re.match(r"[A-Za-z]+(\d+)", f["file"])
        hint_ac = int(m.group(1)) if m else None
        if hint_ac is None:
            hint = ""
        elif hint_ac in by_ac:
            hint = f" The name suggests AC {hint_ac}, which already has {', '.join(i['file'] for i in by_ac[hint_ac])}."
        elif hint_ac in done_acs:
            hint = f" The name suggests AC {hint_ac}, which has an Excel but no PDF."
        else:
            hint = f" The name suggests AC {hint_ac}, which has no PDF and no Excel."
        to_review.append({
            "ac": "", "category": "UNMAPPED", "files": f["file"],
            "detail": f"{f['size'] / 1e6:.1f} MB, {f['pages']} p, bulk={f.get('bulk_status') or 'not run'}.{hint}",
            "suggested_action": "Read the AC from the page header; rename to <AC><Lang>.pdf, or delete if it "
                                "duplicates an existing AC.",
            "blocks_conversion": "yes",
        })

    to_convert.sort(key=lambda r: (r["tier"], r["pages"], r["ac"]))
    for n, r in enumerate(to_convert, 1):
        r["priority"] = n
    to_review.sort(key=lambda r: (r["category"], r["ac"] if r["ac"] != "" else 10**6))
    return to_convert, to_review


def render_readme(to_convert, to_review, done_acs, missing_acs, data_root):
    def tier_stats(t):
        rows = [r for r in to_convert if r["tier"] == t]
        pages = sum(r["pages"] for r in rows)
        return len(rows), pages, pages * SEC_PER_PAGE / 3600

    a, b, d, q = tier_stats("A"), tier_stats("B"), tier_stats("D"), tier_stats("Q")
    cats = defaultdict(list)
    for r in to_review:
        cats[r["category"]].append(r)
    review_acs = {r["ac"] for r in to_review if r["ac"] != ""}
    out = [
        "# Form 20 work queue",
        "",
        f"Generated by `batch/build_queue.py` on {datetime.now():%Y-%m-%d %H:%M} from `{data_root}`. "
        "Do not edit by hand - re-run the script. The only hand-maintained input is `ac_overrides.csv`.",
        "",
        "| | ACs | Detail |",
        "|---|---:|---|",
        f"| Already converted (Excel in `data/2024/EXCEL`) | {len(done_acs)} | nothing to do |",
        f"| **To convert** - tier A, scanned | {a[0]} | {a[1]:,} pages, about {a[2]:.1f} h of OCR |",
        f"| **To convert** - tier B, text layer unusable | {b[0]} | {b[1]:,} pages, about {b[2]:.1f} h of OCR |",
        f"| **To convert** - tier D, copies of duplicate ACs | {d[0]} | {d[1]:,} pages; the copy that verifies is kept |",
        f"| **To convert** - tier Q, quarantined by the old converter | {q[0]} | {q[1]:,} pages; OCR as a second opinion |",
        f"| **To review first** | {len(review_acs)} | {len(to_review)} rows in `to_review.csv` |",
        f"| No PDF at all | {len(missing_acs)} | PDFs must be sourced; nothing to convert |",
        "",
        "## Files",
        "",
        "| File | Content |",
        "|---|---|",
        "| `to_convert.csv` | PDFs for `batch/convert_queue.py`, in run order (tier, then fewest pages first) |",
        "| `to_review.csv` | ACs needing a person's decision before any conversion (`blocks_conversion`) |",
        "| `ac_overrides.csv` | Hand-maintained: PDFs whose AC differs from their file name |",
        "| `conversion_ledger.csv` | Written by the converter: one row per PDF it has run |",
        "| `run_summary.md` | Written by the converter: every converted PDF sorted into CLEAN / FLAGGED / FAILED |",
        "| `review_after_conversion.csv` | Subset of the ledger that needs a look (REVIEW rows, totals differ, failures) |",
        "",
        "## Tiers",
        "",
        "* **A - scanned.** The earlier bulk run found no extractable tables (image-only PDFs).",
        "* **B - text layer unusable.** Legacy (DevLys-era) fonts or unmapped glyphs make the text layer garbage. "
        "OCR ignores the text layer, so it should work, but run a few as a pilot first.",
        "* **D - duplicate copies.** Every copy of an AC with several PDFs is OCR'd; the copy that matches the "
        "official totals is kept.",
        "* **Q - quarantined.** The old text-layer converter's `.REVIEW.xlsx` failed validation; OCR is a second opinion.",
        "",
        "## To review - categories",
        "",
        "| Category | Rows | Meaning |",
        "|---|---:|---|",
    ]
    for c, meaning in CATEGORY_MEANING.items():
        out.append(f"| {c} | {len(cats.get(c, []))} | {meaning} |")
    out += ["", "## Missing ACs (no PDF)", "", ", ".join(str(a) for a in missing_acs) or "none", ""]
    out += [
        "## Run",
        "",
        "```",
        "python batch/build_queue.py                      # refresh these lists",
        "python batch/convert_queue.py --dry-run          # what would run, and how long",
        "python batch/convert_queue.py --limit 3          # pilot: 3 smallest tier A files",
        "python batch/convert_queue.py                    # all of tier A (resumable)",
        "python batch/convert_queue.py --tier A,B         # tiers A and B",
        "```",
        "",
    ]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the Form 20 conversion / review queue lists.")
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT), help="folder holding EXCEL/ and PDF/ (default: data/2024)")
    ap.add_argument("--queue-dir", default=str(QUEUE_DIR), help="where to write the lists (default: queue/)")
    args = ap.parse_args(argv)

    root, queue_dir = Path(args.data_root), Path(args.queue_dir)
    pdf_dir, excel_dir = root / "PDF", root / "EXCEL"
    overrides = load_overrides(queue_dir / "ac_overrides.csv")
    status = load_bulk_status(pdf_dir)
    by_ac, unmapped = collect_pdfs(pdf_dir, overrides)
    done_acs = {ac_of(p.name) for p in excel_dir.glob("*.xlsx")} - {None}

    for files in list(by_ac.values()) + [unmapped]:        # pages/md5 only for what is not done
        for i in files:
            if i["ac"] in done_acs:
                continue
            i["pages"], i["layout"] = pdf_shape(i["path"])
            i["md5"] = md5_of(i["path"]) if len(by_ac.get(i["ac"], [])) > 1 else ""
            i["bulk_status"], i["bulk_error"] = status.get(i["file"], ("", ""))
    stray = {p.name for p in pdf_dir.glob("*.xlsx")}

    to_convert, to_review = classify(by_ac, unmapped, done_acs, stray, overrides)
    missing = [a for a in range(1, MAX_AC + 1) if a not in by_ac]
    write_csv(queue_dir / "to_convert.csv", TO_CONVERT_FIELDS, to_convert)
    write_csv(queue_dir / "to_review.csv", TO_REVIEW_FIELDS, to_review)
    (queue_dir / "README.md").write_text(
        render_readme(to_convert, to_review, done_acs & set(by_ac), missing, args.data_root), encoding="utf-8")

    tiers = Counter(r["tier"] for r in to_convert)
    print(f"to_convert: {len(to_convert)} files ({', '.join(f'tier {t} {n}' for t, n in sorted(tiers.items()))}); "
          f"to_review: {len(to_review)} rows; already converted: {len(done_acs & set(by_ac))}; no PDF: {len(missing)}")
    print(f"written to {queue_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
