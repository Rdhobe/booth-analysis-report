"""Sum the ECI booth sheets (2017, 2019, 2022) to constituency (AC) level.

Reuses the repo's own parser (``Scripts/report/agra_pipeline.py: ingest_eci``) so booth rows are read exactly
as the rest of the pipeline reads them. Booth sums are EVM votes only (postal ballots are not on these sheets).

Run from the repo root (needs ``xlrd==2.0.2`` for the legacy .xls files):
    python Scripts/ml/ac_booth_totals.py [--workers 4]

Writes (generated, in the git-ignored ``data/processed/``):
    ac_booth_sums.csv         one row per election x AC: booths, electors, male/female/other voters, polled, valid, NOTA
    ac_booth_party_votes.csv  one row per election x AC x party: votes (party names as normalised by the parser)
    ac_booth_coverage.csv     one row per file: status, ACs found, booths, any AC/file-name mismatch

Not covered: the 176 Hindi 2022 ``.xlsx`` files (the parser does not read them), so 2022 has about 225 ACs.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

try:
    from . import booth_sheets_generic as G
except ImportError:  # run as a script from Scripts/ml
    import booth_sheets_generic as G

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PROC = DATA / "processed"
PIPELINE = ROOT / "Scripts" / "report" / "agra_pipeline.py"
ELECTIONS = [("VS2017", "2017"), ("LS2019", "2019"), ("VS2022", "2022")]
log = logging.getLogger("ml.booth_totals")

_MOD = None


class _Cell:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class _XlsxSheet:
    """The few xlrd sheet methods the parser uses, backed by an openpyxl worksheet (empty cells read as '')."""

    def __init__(self, ws):
        self.name = ws.title
        self._rows = [tuple("" if v is None else v for v in row) for row in ws.iter_rows(values_only=True)]
        self.nrows = len(self._rows)
        self.ncols = max((len(r) for r in self._rows), default=0)
        # xlrd merged ranges are (first_row, last_row + 1, first_col, last_col + 1), zero-based
        self.merged_cells = [(m.min_row - 1, m.max_row, m.min_col - 1, m.max_col) for m in ws.merged_cells.ranges]

    def cell(self, r: int, c: int) -> _Cell:
        row = self._rows[r] if 0 <= r < self.nrows else ()
        return _Cell(row[c] if 0 <= c < len(row) else "")


class _XlsxBook:
    def __init__(self, path: str):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)       # not read-only: merged ranges are needed for candidate names
        self._sheets = [_XlsxSheet(ws) for ws in wb.worksheets]
        self.nsheets = len(self._sheets)

    def sheet_by_index(self, i: int) -> _XlsxSheet:
        return self._sheets[i]


def _install_xlsx_support() -> None:
    """Let the repo's xlrd-based parser open .xlsx files too (the 2022 'xlsx' files use the same English ECI layout)."""
    import xlrd
    if getattr(xlrd, "_upbi_xlsx", False):
        return
    original = xlrd.open_workbook

    def open_workbook(path, *a, **k):
        return _XlsxBook(str(path)) if str(path).lower().endswith(".xlsx") else original(path, *a, **k)

    xlrd.open_workbook = open_workbook
    xlrd._upbi_xlsx = True


def _pipeline():
    """Load the repo's ingest module by path (once per process)."""
    global _MOD
    if _MOD is None:
        spec = importlib.util.spec_from_file_location("agra_pipeline", PIPELINE)
        _MOD = importlib.util.module_from_spec(spec)
        sys.modules["agra_pipeline"] = _MOD
        spec.loader.exec_module(_MOD)
        logging.getLogger().setLevel(logging.WARNING)      # the parser logs one line per file
        logging.getLogger("agra").setLevel(logging.WARNING)
        _install_xlsx_support()
    return _MOD


_AUTH: dict | None = None


def _authority(year: str, name: str) -> int | None:
    """AC a file is meant to hold: configs/data_files.json first (as build_state_report does), then the file name."""
    global _AUTH
    if _AUTH is None:
        raw = (ROOT / "configs" / "data_files.json").read_bytes().decode("utf-8", errors="replace")
        _AUTH = {}
        for e in json.loads(raw)["files"]:
            try:
                ac = int(e.get("ac_no"))
            except (TypeError, ValueError):
                continue
            _AUTH[(str(e.get("year", "")), str(e.get("source", "")).replace("\\", "/").rsplit("/", 1)[-1].lower())] = ac
    if (year, name.lower()) in _AUTH:
        return _AUTH[(year, name.lower())]
    m = re.match(r"^(?:AC)?(\d+?)(?:-1)?$", Path(name).stem, re.I)
    return int(m.group(1)) if m else None


def fix_ac_numbers(booths: list, facts: list, auth: int | None) -> str:
    """Repair AC numbers the sheet parser got wrong; returns a note ("" if nothing needed fixing).

    * one AC found but not the file's AC            -> move everything to the file's AC
    * many "ACs" with about one booth each (serials read as AC numbers) -> move everything to the file's AC
    * several real ACs (a file can hold a whole parliamentary seat)     -> keep, dropping numbers outside 1..403
    """
    got = {}
    for b in booths:
        got[b["ac"]] = got.get(b["ac"], 0) + 1
    note = ""
    if auth is not None and len(got) == 1 and next(iter(got)) != auth:
        note = f"AC {next(iter(got))} in sheet, moved to {auth}"
        for rec in booths + facts:
            rec["ac"] = auth
    elif auth is not None and len(got) >= 5 and sorted(got.values())[len(got) // 2] <= 2:
        note = f"{len(got)} serial-like ACs, all {sum(got.values())} booths moved to {auth}"
        for rec in booths + facts:
            rec["ac"] = auth
    elif len(got) > 1:
        bad = {a for a in got if not isinstance(a, int) or not 1 <= a <= 403}
        if bad:
            note = f"dropped {sum(got[a] for a in bad)} booths with AC numbers outside 1..403"
            booths[:] = [b for b in booths if b["ac"] not in bad]
            facts[:] = [f for f in facts if f["ac"] not in bad]
    return note


def _init_worker() -> None:
    _pipeline()


def _read_generic(path: Path, auth: int | None):
    """Label-based fallback reader; returns (booths, facts) or None."""
    import xlrd
    try:
        res = G.parse_workbook(xlrd.open_workbook(str(path)))
    except Exception:
        return None
    if not res:
        return None
    P = _pipeline()
    for b in res["booths"]:
        if b["ac"] is None:
            b["ac"] = auth
    for f in res["facts"]:
        if f["ac"] is None:
            f["ac"] = auth
        f["party"] = "NOTA" if f["party"] == "NOTA" else P.norm_party(f["party"])
        f["candidate"] = P.norm_name(f["candidate"])
    return res["booths"], res["facts"]


def _preamble_electors(path: Path) -> int | None:
    import xlrd
    try:
        return G.form20_preamble_electors(xlrd.open_workbook(str(path)))
    except Exception:
        return None


def _aggregate(booths: list, facts: list, auth: int | None) -> tuple[dict, dict, str]:
    """Repair AC numbers, then sum booths per AC and candidate votes per (AC, party, candidate)."""
    note = fix_ac_numbers(booths, facts, auth)
    acs: dict = {}
    for b in booths:
        a = acs.setdefault(b["ac"], {"booths": 0, "electors": 0.0, "male": 0.0, "female": 0.0, "other": 0.0,
                                     "polled": 0.0, "valid": 0.0, "nota": 0.0, "booths_no_electors": 0})
        a["booths"] += 1
        if b["electors"] is None:
            a["booths_no_electors"] += 1
        for key in ("electors", "male", "female", "other", "polled", "valid", "nota"):
            a[key] += float(b[key] or 0)
    party: dict = {}
    for f in facts:
        k = (f["ac"], f["party"], str(f.get("candidate", "")))
        party[k] = party.get(k, 0.0) + float(f["votes"] or 0)
    return acs, party, note


def _ac_ok(a: dict) -> bool:
    """Basic structure check: electors present on at least 90% of booths and turnout between 30% and 95%."""
    return bool(a["booths"] and a["electors"] and a["booths_no_electors"] <= 0.1 * a["booths"] and 0.30 <= a["polled"] / a["electors"] <= 0.95)


def parse_file(job: tuple[str, str]) -> dict:
    """Parse one ECI workbook and aggregate its booths to AC level.

    The repo's parser goes first. The label-based reader is the fallback when the main parser finds no table, and is also
    tried when the main result fails the basic checks; it is kept only if it passes them for more constituencies.
    """
    eid, path_s = job
    path = Path(path_s)
    year = path.parent.name
    auth = _authority(year, path.name)
    out = {"file": path.name, "eid": eid, "status": "ok", "detail": "", "acs": {}, "party": {}, "reader": "main"}
    facts, booths, err = [], [], ""
    try:
        facts, booths, _cover = _pipeline().ingest_eci(eid, [path])
    except Exception as exc:                                # one bad workbook must not stop the run
        err = f"{type(exc).__name__}: {exc}"[:200]
    acs, party, note = _aggregate(booths, facts, auth) if booths else ({}, {}, "")

    if not booths or not all(_ac_ok(a) for a in acs.values()):
        fallback = _read_generic(path, auth)
        if fallback:
            acs2, party2, note2 = _aggregate(*fallback, auth)
            if sum(_ac_ok(a) for a in acs2.values()) > sum(_ac_ok(a) for a in acs.values()) or not acs:
                acs, party, note, out["reader"] = acs2, party2, note2, "generic"
    if not acs:
        electors = _preamble_electors(path) if auth is not None else None
        if electors:                                        # Form 20 sheet: no electors per booth, but the preamble gives the AC total
            out["acs"][auth] = {"booths": 0, "electors": float(electors), "male": 0.0, "female": 0.0, "other": 0.0, "polled": 0.0,
                                "valid": 0.0, "nota": 0.0, "booths_no_electors": 0}
            out.update(reader="form20_preamble", detail="electors from the Form 20 preamble; no booth rows")
            return out
        out.update(status="error" if err else "no_rows", detail=err or "no booth table recognised")
        return out
    out["acs"], out["party"] = acs, party
    if note:
        out["detail"] = note
    elif auth is not None and auth not in acs:
        out["detail"] = f"file is for AC {auth}, parsed ACs {sorted(acs)[:6]}"
    if out["reader"] == "generic":
        out["detail"] = ("read by the label-based reader; " + out["detail"]).strip("; ")
    return out


def list_jobs() -> list[tuple[str, str]]:
    jobs = []
    for eid, year in ELECTIONS:
        for p in sorted([*(DATA / year).glob("*.xls"), *(DATA / year).glob("*.xlsx")]):
            jobs.append((eid, str(p)))
    return jobs


def run(workers: int) -> None:
    jobs = list_jobs()
    log.info("%d workbooks to read (%d workers)", len(jobs), workers)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        results = list(pool.map(parse_file, jobs, chunksize=8))
    log.info("parsed in %.0fs", time.time() - t0)

    sums: dict[tuple[str, int], dict] = {}
    party: dict[tuple[str, int, str, str], float] = defaultdict(float)
    cov_rows = []
    for r in results:
        cov_rows.append({"election": r["eid"], "file": r["file"], "status": r["status"], "reader": r["reader"], "acs": ";".join(map(str, sorted(r["acs"]))),
                         "booths": sum(a["booths"] for a in r["acs"].values()), "detail": r["detail"]})
        for ac, a in r["acs"].items():
            key = (r["eid"], ac)
            if key in sums:                                  # same AC in two files: keep the larger, flag it
                if a["booths"] > sums[key]["booths"]:
                    sums[key] = {**a, "file": r["file"], "reader": r["reader"], "note": "duplicate AC across files; larger kept"}
                continue
            sums[key] = {**a, "file": r["file"], "reader": r["reader"], "note": ""}
        for (ac, p, cand), v in r["party"].items():
            if (r["eid"], ac) in sums and sums[(r["eid"], ac)]["file"] == r["file"]:
                party[(r["eid"], ac, p, cand)] += v

    PROC.mkdir(parents=True, exist_ok=True)
    cols = ["election", "ac", "file", "reader", "booths", "electors", "male", "female", "other", "polled", "valid", "nota",
            "booths_no_electors", "turnout", "note"]
    with open(PROC / "ac_booth_sums.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for (eid, ac), a in sorted(sums.items()):
            row = {"election": eid, "ac": ac, **{k: a[k] for k in cols if k in a}}
            row["turnout"] = round(a["polled"] / a["electors"], 4) if a["electors"] else ""
            w.writerow(row)
    with open(PROC / "ac_booth_party_votes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["election", "ac", "party", "candidate", "votes"])
        for (eid, ac, p, cand), v in sorted(party.items()):
            w.writerow([eid, ac, p, cand, int(v)])
    with open(PROC / "ac_booth_coverage.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["election", "file", "status", "reader", "acs", "booths", "detail"])
        w.writeheader()
        w.writerows(cov_rows)

    for eid, _ in ELECTIONS:
        n = sum(1 for (e, _a) in sums if e == eid)
        bad = [r for r in cov_rows if r["election"] == eid and r["status"] != "ok"]
        log.info("%s: %d ACs read; %d files not read (%s)", eid, n, len(bad),
                 ", ".join(sorted({r["status"] for r in bad})) or "none")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(args.workers)


if __name__ == "__main__":
    main()
