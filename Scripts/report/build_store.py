"""Merge every convertible Excel file into ONE local store.

Sources (from configs/data_files.json + configs/data_file_format.json):
- 2017/2019/2022 .xls ECI triplet sheets (English; Hindi pswise sheets
  without triplets are skipped with note).
- 2024 converted .xlsx sidecars (REVIEW quarantines excluded).
Scanned/legacy PDFs contribute no rows (nothing to merge yet).

Store (SQLite, single file): booth / vote / file_coverage tables.
Schema doubles as the dashboard contract (see output/dashboard.html).

Parsing reuses Scripts/agra_pipeline ingest (ingest_eci, ingest_2024).
Resumable: output/build_progress.json tracks done files; reruns skip them.

Usage:
  python Scripts/build_store.py [--db output/booth_data.db] [--limit N] [--only PREFIX]
  e.g. --only data/2017  (resume in chunks; tool timeouts are real)

Outputs: <db>, output/build_progress.json
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("store")

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import Scripts.report.agra_pipeline as P  # noqa: E402 (reuses ingest_eci, ingest_2024, booth_uid)

EID = {"2017": "VS2017", "2019": "LS2019", "2022": "VS2022", "2024": "LS2024"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS booth (
  booth_uid TEXT PRIMARY KEY, election TEXT, year INTEGER, district TEXT,
  ac_no INTEGER, ac_name TEXT, ps_no TEXT, ps_name TEXT,
  electors INTEGER, polled INTEGER, valid INTEGER, nota INTEGER,
  legacy_names INTEGER, src_file TEXT);
CREATE TABLE IF NOT EXISTS vote (
  booth_uid TEXT, candidate TEXT, party TEXT, votes INTEGER,
  PRIMARY KEY (booth_uid, candidate));
CREATE TABLE IF NOT EXISTS file_coverage (
  file TEXT PRIMARY KEY, year TEXT, district TEXT, ac_no INTEGER,
  booths INTEGER, valid_ok INTEGER, note TEXT);
CREATE INDEX IF NOT EXISTS idx_booth_ac ON booth(ac_no, election);
CREATE INDEX IF NOT EXISTS idx_booth_district ON booth(district, election);
CREATE INDEX IF NOT EXISTS idx_vote_booth ON vote(booth_uid);
"""


def targets():
    """(year, district, path, layout, maprow) for every convertible excel."""
    fmap = json.loads((ROOT / "configs" / "data_files.json").read_text(encoding="utf-8"))
    ffmt = json.loads((ROOT / "configs" / "data_file_format.json").read_text(encoding="utf-8"))
    fmt_by_file = {r["file"]: r for r in ffmt["files"]}
    out = []
    canon = {}  # lower -> first-seen spelling ('Agra' vs 'agra' folders)
    for r in fmap["files"]:
        src = r.get("source", "")
        p = ROOT / src
        district = r["district"]
        district = canon.setdefault(district.lower(), district)
        if r["year"] in ("2017", "2019", "2022"):
            if not src.endswith(".xls") or not p.exists():
                continue
            out.append((r["year"], district, p, "eci",
                        fmt_by_file.get(src, {}).get("layout", ""), r))
        elif r["year"] == "2024" and r.get("status") == "converted":
            x = ROOT / (r.get("xlsx") or "")
            if x.suffix == ".xlsx" and x.exists():
                out.append((r["year"], district, x, "form20",
                            "form20-xlsx", r))
    return sorted(out, key=lambda t: (t[0], t[1], str(t[2])))


def ensure_db(db: Path):
    db.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(str(db))
    cx.executescript(SCHEMA)
    return cx


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Merge all convertible files -> SQLite")
    ap.add_argument("--db", default="output/booth_data.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="prefix filter on data/ path")
    args = ap.parse_args(argv)
    db = ROOT / args.db if not Path(args.db).is_absolute() else Path(args.db)

    pmap = {}
    pmf = ROOT / "configs" / "agra_party_map_2024.csv"
    if pmf.exists():
        with open(pmf, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip() and not ln.startswith("#")]
        for r in csv.DictReader(lines):
            pmap[(r["election_id"].strip(), r["ac_no"].strip(),
                  P.norm_name(r["candidate_name"]))] = r["party"].strip().upper()

    all_t = targets()
    if args.only:
        pref = args.only.replace("\\", "/").rstrip("/")
        all_t = [t for t in all_t
                 if str(t[2].relative_to(ROOT)).replace("\\", "/").startswith(pref)]
    prog_p = Path(str(db) + ".progress.json")
    done = set(json.loads(prog_p.read_text(encoding="utf-8"))) if prog_p.exists() else set()
    todo = [t for t in all_t if str(t[2]) not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"files total={len(all_t)} done={len(done)} todo={len(todo)}", flush=True)

    cx = ensure_db(db)
    t_all = time.time()
    for i, (year, district, path, kind, layout, mrow) in enumerate(todo, 1):
        t0 = time.time()
        try:
            if kind == "eci":
                facts, booths, cover = P.ingest_eci(EID[year], [path])
            else:
                facts, booths, cover = P.ingest_2024([path], pmap)
            ac = mrow.get("ac_no")
            ac_name = mrow.get("ac_name", "") or ""
            remap = {}
            for b in booths:
                if ac is not None and (b["ac"] == -1 or b["ac"] is None):
                    b["ac"] = ac
                    b["ac_name"] = b["ac_name"] or ac_name
                    ps0 = str(b["ps"])
                    new = "%s-%03d-%s" % (b["election"], ac,
                                          ps0.zfill(4) if ps0.isdigit() else ps0)
                    remap[b["booth_uid"]] = new
                    b["booth_uid"] = new
                if b["ac"] in (-1, None):
                    stem = Path(b.get("src_file") or path.stem).stem
                    ps0 = str(b["ps"])
                    new = "%s-NA-%s-%s" % (b["election"], stem,
                                           ps0.zfill(4) if ps0.isdigit() else ps0)
                    remap[b["booth_uid"]] = new
                    b["booth_uid"] = new
                    b["ac"] = None
                    b["ac_name"] = b["ac_name"] or ac_name
            if remap:
                for f in facts:
                    if f["booth_uid"] in remap:
                        f["booth_uid"] = remap[f["booth_uid"]]
            for b in booths:
                cx.execute(
                    "INSERT OR REPLACE INTO booth VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (b["booth_uid"], b["election"], int(year), district,
                     b["ac"] if b["ac"] != -1 else None, b["ac_name"], b["ps"],
                     b["ps_name"], b["electors"], b["polled"], b["valid"],
                     b["nota"], 1 if b["legacy_names"] else 0,
                     str(path.relative_to(ROOT)).replace("\\", "/")))
            for f in facts:
                cx.execute("INSERT OR REPLACE INTO vote VALUES (?,?,?,?)",
                           (f["booth_uid"], f["candidate"], f["party"], f["votes"]))
            for c in cover:
                cx.execute("INSERT OR REPLACE INTO file_coverage VALUES (?,?,?,?,?,?,?)",
                           (str(path.relative_to(ROOT)).replace("\\", "/"), year,
                            district, c["ac"] if c["ac"] != -1 else None,
                            c["booths"], 1 if c["valid_ok"] else 0, c["note"]))
            cx.commit()
            nb = len(booths)
            print(f"[{i}/{len(todo)}] OK {path.relative_to(ROOT)} booths={nb} "
                  f"({time.time() - t0:.1f}s)", flush=True)
        except Exception as ex:  # noqa: BLE001 - record, continue batch
            cx.execute("INSERT OR REPLACE INTO file_coverage VALUES (?,?,?,?,?,?,?)",
                       (str(path.relative_to(ROOT)).replace("\\", "/"), year,
                        district, mrow.get("ac_no"), 0, 0, f"INGEST-ERROR: {ex}"))
            cx.commit()
            print(f"[{i}/{len(todo)}] FAIL {path.relative_to(ROOT)}: {ex}", flush=True)
        done.add(str(path))
        if i % 25 == 0:
            prog_p.write_text(json.dumps(sorted(done)), encoding="utf-8")
    prog_p.write_text(json.dumps(sorted(done)), encoding="utf-8")
    n = cx.execute("SELECT COUNT(*), (SELECT COUNT(*) FROM vote), "
                   "(SELECT COUNT(*) FROM file_coverage) FROM booth").fetchone()
    print(f"STORE booths={n[0]} votes={n[1]} files={n[2]} elapsed={time.time()-t_all:.0f}s",
          flush=True)
    cx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
