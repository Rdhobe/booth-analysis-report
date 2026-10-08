"""Statewide (AC 1-403) booth report: same format as the Agra workbook.

Reads flattened year-root workbooks (data/2017|2019|2022/*.xls,
data/2024/<AC>.xlsx) plus the ECI 2024 assembly-segment file
(AC-level candidate votes/parties/electors), writes
data/processed/state_{fact,booth,coverage}.csv +
output/up_booth_report.xlsx (single All_ACs sheet with AC + District
columns, zeros where data is absent, zones
Safe/Favorable/Battlefield/Difficult/Data Not sufficient; turnout
Electors + Male/Female/Other/Total plus 2017 modeled demographics
live in trailing All_ACs columns, never a separate sheet).

Rules (user-confirmed):
- ACs with no files at all are skipped (no zero-rows invented).
- Absent elections/booths/parties show 0 in numeric cells; zones are
  computed from real diffs only (n<2 -> Data Not sufficient).
- 2024 parties: Agra map (exact) > ECI segment file (official, all
  403 ACs) > ECI UP unambiguous names; the rest is UNMAPPED -> 0.
- 2022/Hindi: English sheets preferred per AC; Hindi only where no
  English exists for that AC. 2022 .xlsx files are Hindi duplicates
  readable only via openpyxl (not ingested - counted as
  HINDI_XLSX_SKIP, so VS2022 covers the 225 English .xls ACs only).
- Duplicate (uid) booth rows: first wins, counted in coverage.
- ECI booth block comes in two geometries (auto-detected per sheet):
  with-Name (AC|PS|Name|Electors|M|F|O|T|EPIC|Tendered) and no-Name
  (most 2017 files: AC|PS|Electors|M|F|O|T|...). Column-index helper
  rows are skipped via their numeric triplet-party cells (never as
  phantom booths).
- Report rule: new data extends existing sheets as new columns; never
  add a new sheet for new/extra data.

Usage:
  python Scripts/build_state_report.py [--districts Agra Lucknow]
      [--out-report output/up_booth_report.xlsx] [--skip-workbook]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("state")

sys.path.insert(0, str(Path(__file__).parent))
from Scripts.report.agra_pipeline import (  # noqa: E402
    booth_uid,
    find_vote_header,
    ingest_eci,
    norm_name,
    norm_party,
    num,
)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
PROC = ROOT / "data" / "processed"

ELECTIONS = ["VS2017", "LS2019", "VS2022", "LS2024"]
YEAR_OF = {"VS2017": "2017", "LS2019": "2019", "VS2022": "2022",
           "LS2024": "2024"}
PARTY_A = "BJP"
SAFE_UP, DIFF_DOWN = 0.10, -0.10
DEVA_RE = re.compile(r"[\u0900-\u097F]")

ZONE_FILL = {"Safe": "C6EFCE", "Favorable": "E2EFDA",
             "Battlefield": "FFEB9C", "Difficult": "FFC7CE",
             "Data Not sufficient": "D9D9D9", "UNMAPPED": "D9D9D9"}
ZONE_FONT = {"Safe": "006100", "Favorable": "375623",
             "Battlefield": "9C6500", "Difficult": "9C0006",
             "Data Not sufficient": "404040", "UNMAPPED": "404040"}
HDR_FILL, HDR_FONT = "1F4E79", "FFFFFF"
POS_FILL, NEG_FILL = "C6EFCE", "FFC7CE"


def load_ac_info():
    d = json.loads((ROOT / "configs" / "ac_format.json").read_text(
        encoding="utf-8"))
    return {int(a["ac_no"]): (a.get("ac_name", ""),
                               a.get("district", "UNKNOWN"))
            for a in d["assembly_constituencies"]}


def load_agra_map():
    m = {}
    p = ROOT / "configs" / "agra_party_map_2024.csv"
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = next(csv.reader([line]))
        if len(parts) < 4 or parts[0] == "election_id":
            continue
        eid, ac, name, party = [x.strip() for x in parts[:4]]
        try:
            ac_key: object = int(ac)
        except ValueError:
            ac_key = ac  # "*" wildcard (agra_pipeline lookup pattern)
        m[(eid, ac_key, norm_name(name))] = party.upper()
    return m


def load_eci_map():
    """Unambiguous normalized candidate name -> party (UP only, LS2024)."""
    m, multi = {}, set()
    p = DATA / "lok-sabha-elections-2024-results.csv"
    for r in csv.DictReader(open(p, encoding="utf-8")):
        if r.get("State") != "Uttar Pradesh":
            continue
        name = norm_name(r.get("Candidate", ""))
        party = (r.get("Party") or "").strip().upper()
        if not name or not party:
            continue
        if name in m and m[name] != party:
            multi.add(name)
        m[name] = party
    for name in multi:
        del m[name]
    return m


def load_segment_2024():
    """ECI assembly-segment file (AC-level, 2024): title row + header +
    one row per (AC, candidate). Returns (cand_party, ac_stats).
    cand_party: norm name -> party, dropping names that map to two
    parties. ac_stats: ac -> {electors, nota, valid_sum}."""
    m, multi = {}, set()
    acs: dict = {}
    p = DATA / ("assembly-segment-level-voting-data-for-all-"
                "constituencies-2024.csv")
    with open(p, encoding="utf-8-sig") as f:
        lines = [ln for ln in f if ln.strip()]
    if lines and not lines[0].startswith("State/UT"):
        lines = lines[1:]  # ECI title row, not data
    for r in csv.DictReader(lines):
        if (r.get("State/UT Name") or "").strip() != "Uttar Pradesh":
            continue
        try:
            ac = int(r.get("AC NO"))
        except (TypeError, ValueError):
            continue
        name = norm_name(r.get("CANDIDATE NAME", ""))
        party = (r.get("PARTY") or "").strip().upper()

        def _int(x):
            try:
                return int(str(x or "0").replace(",", ""))
            except ValueError:
                return 0

        st = acs.setdefault(ac, {"electors": _int(
            r.get("TOTAL ELECTORS IN AC")), "nota": _int(
            r.get("NOTA VOTES EVM IN AC")), "valid_sum": 0})
        st["valid_sum"] += _int(r.get("VOTES SECURED EVM"))
        if not name or not party:
            continue
        if name in m and m[name] != party:
            multi.add(name)
        m[name] = party
    for name in multi:
        del m[name]
    return m, acs


# uprolls2017 modeled-booth-demographics columns (2017 vintage only).
# Keys (id, ac_id_09, booth_id_17) are the join, never displayed.
DEMO_KEY_COLS = {"id", "ac_id_09", "booth_id_17"}
# Administrative columns: shown even under R5 suppression (not inferences).
DEMO_ADMIN_COLS = {"electors_17", "missing_percent_17",
                   "revision_percent_new_17",
                   "revision_percent_deleted_17",
                   "revision_percent_modified_17"}


def load_demo_2017():
    """uprolls2017.csv: one modeled row per (AC, booth), 2017 vintage.
    Returns ({(ac, ps_norm): {col: raw_str}}, [data_cols]). ps keys are
    zero-stripped ("01" -> "1") to match sheet serials."""
    import csv
    demo: dict = {}
    cols: list = []
    with open(DATA / "uprolls2017.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if not cols:
                cols = [c for c in (r.keys() or [])
                        if c not in DEMO_KEY_COLS]
            try:
                ac = int(r["ac_id_09"])
                ps = str(int(r["booth_id_17"]))
            except (TypeError, ValueError):
                continue
            demo[(ac, ps)] = r
    return demo, cols


def demo_norm_ps(ps) -> str:
    s = str(ps or "").strip()
    return str(int(s)) if re.match(r"^0*\d+$", s) else s


def demo_cell(col: str, raw, electors):
    """Raw string -> display value with RULES R5 suppression (modeled
    cells blank when electors_17 < 200) and sanity gates on absurd
    modeled ages (unparsed values leak in as 1e17+)."""
    s = "" if raw is None else str(raw).strip()
    if not s:
        return ""
    if col not in DEMO_ADMIN_COLS:
        try:
            e = float(electors) if electors not in (None, "") else None
        except (TypeError, ValueError):
            e = None
        if e is not None and e < 200:
            return ""
    if col.endswith("_avg_17"):
        try:
            v = float(s)
        except ValueError:
            return ""
        return v if 15 <= v <= 100 else ""
    if col.endswith("_stddev_17"):
        try:
            v = float(s)
        except ValueError:
            return ""
        return v if 0 <= v <= 50 else ""
    return s


def file_is_hindi_xls(path: Path) -> bool:
    """True if the triplet header/name rows carry Devanagari."""
    import xlrd
    try:
        bk = xlrd.open_workbook(str(path), on_demand=True)
    except Exception:
        return False
    try:
        for si in range(bk.nsheets):
            sh = bk.sheet_by_index(si)
            found = find_vote_header(sh)
            if not found:
                continue
            hr, _vcols = found
            for rr in (hr - 1, hr - 2, hr):
                if 0 <= rr < sh.nrows:
                    for cc in range(min(20, sh.ncols)):
                        if DEVA_RE.search(str(sh.cell(rr, cc).value or "")):
                            return True
            return False  # first triplet sheet decides
    finally:
        try:
            bk.release_resources()
        except Exception:
            pass
    return False


def filemap_ac():
    """{year: {basename_lower: ac_no}} authority from data_files.json."""
    raw = (ROOT / "configs" / "data_files.json").read_bytes()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    out: dict = {}
    for e in data["files"]:
        y = str(e.get("year", ""))
        src = str(e.get("source", "")).replace("\\", "/")
        try:
            ac = int(e.get("ac_no"))
        except (TypeError, ValueError):
            continue
        out.setdefault(y, {})[src.rsplit("/", 1)[-1].lower()] = ac
    return out


def stem_ac(path: Path):
    m = re.match(r"^(?:AC)?(\d+?)(?:-1)?$", path.stem, re.I)
    return int(m.group(1)) if m else None


def remap_booths(bs, fs, expected):
    """Force single-AC result to the authority AC (uids embed the AC).
    Returns remapped booth count."""
    n = 0
    uid_map = {}
    for b in bs:
        try:
            cur = int(b["ac"])
        except (TypeError, ValueError):
            continue
        if cur == expected:
            continue
        old_uid = b["booth_uid"]
        rest = old_uid.rsplit("-", 1)[-1]
        new_uid = f"{b['election']}-{expected:03d}-{rest}"
        uid_map[old_uid] = new_uid
        b["booth_uid"] = new_uid
        b["ac"] = expected
        n += 1
    for x in fs:
        if x["booth_uid"] in uid_map:
            x["booth_uid"] = uid_map[x["booth_uid"]]
    return n


def ingest_2024_state(files, agra_map, seg_map, eci_map):
    """Adapted from agra_pipeline.ingest_2024: + filename-AC fallback
    (pre-renamed shorts like 254.xlsx whose title block is unreadable)
    and ECI fallback party maps (Agra exact > segment official >
    unambiguous LS names). Returns (facts, booths, cover)."""
    import openpyxl
    facts, booths, cover = [], [], []
    for f in sorted(files):
        # NOTE: normal (non-read-only) mode like agra_pipeline - random
        # ws.cell() access in read_only mode re-parses per call (O(n^2)).
        wb = openpyxl.load_workbook(str(f), data_only=True)
        ws = wb["Form20"] if "Form20" in wb.sheetnames else wb.active
        title = str(ws.cell(5, 1).value or "")
        m = re.search(r"(\d{2,3})\s*-\s*(.+)", title)
        if m:
            ac, ac_name = int(m.group(1)), m.group(2).strip()
        else:
            m2 = re.match(r"^(\d{1,3})$", f.stem)
            ac = int(m2.group(1)) if m2 else -1
            ac_name = "FROM-FILENAME"
        ncols = ws.max_column
        r8c1 = norm_name(ws.cell(8, 2).value)
        lead = 2 if (not r8c1 or re.search(
            r"polling|station|ps\.?\s*no|^\d+$", r8c1, re.I)) else 1
        names = [norm_name(ws.cell(8, c).value)
                 for c in range(lead + 1, ncols - 4)]
        rows, r = [], 9
        while r <= ws.max_row:
            v0 = ws.cell(r, 1).value
            if v0 is None or not re.match(r"^\d+$", str(v0).strip()):
                break
            rows.append([ws.cell(r, c).value for c in range(1, ncols + 1)])
            r += 1
        bad_rows = 0
        for row in rows:
            ps_raw = str(row[1]).strip() if (lead == 2 and row[1]
                                             is not None) else ""
            if lead == 1 or not ps_raw:
                ps_raw = str(row[0]).strip()
            uid, _sfx = booth_uid("LS2024", ac, ps_raw)
            votes = [num(x) or 0 for x in row[lead:lead + len(names)]]
            valid = num(row[ncols - 5])
            nota = num(row[ncols - 3]) or 0
            tot = num(row[ncols - 2])
            polled = tot if tot is not None else sum(votes) + nota
            if valid is not None and sum(votes) != valid:
                bad_rows += 1
            if valid is not None and tot is not None \
                    and valid + nota != tot:
                bad_rows += 1
            b = {"booth_uid": uid, "election": "LS2024", "ac": ac,
                 "ac_name": ac_name, "ps": ps_raw,
                 "ps_name": ps_raw, "electors": None, "male": None,
                 "female": None, "other": None, "epic": None,
                 "tendered": None, "polled": polled,
                 "valid": valid if valid is not None else sum(votes),
                 "nota": nota, "legacy_names": False, "src": f.name}
            booths.append(b)
            for name, vv in zip(names, votes):
                party = agra_map.get(
                    ("LS2024", ac, name),
                    agra_map.get(("LS2024", "*", name),
                                 seg_map.get(name, eci_map.get(
                                     name, "UNMAPPED"))))
                facts.append({"booth_uid": uid, "election": "LS2024",
                              "ac": ac, "candidate": name,
                              "party": norm_party(party), "votes": vv})
        cover.append({"election": "LS2024", "ac": ac, "ac_name": ac_name,
                      "file": f.name, "booths": len(rows),
                      "note": f"rowmath_bad={bad_rows}" if bad_rows else ""})
        wb.close()
    return facts, booths, cover


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Statewide booth report")
    ap.add_argument("--districts", nargs="*", default=[],
                    help="pilot filter by district (else all)")
    ap.add_argument("--out-report", default="output/up_booth_report.xlsx")
    ap.add_argument("--skip-workbook", action="store_true",
                    help="ingest to CSVs only")
    ap.add_argument("--no-eci-fallback", action="store_true",
                    help="2024 parties: Agra map only (thinner, skips "
                         "segment + LS-results fallbacks)")
    args = ap.parse_args(argv)
    t_all = time.time()

    ac_info = load_ac_info()
    want_ac = None
    if args.districts:
        want = {d.lower() for d in args.districts}
        want_ac = {ac for ac, (_n, d) in ac_info.items()
                   if d.lower() in want}
        log.info("pilot districts=%s -> %d ACs", args.districts,
                 len(want_ac))

    agra_map = load_agra_map()
    eci_map = {} if args.no_eci_fallback else load_eci_map()
    seg_map, seg_ac = load_segment_2024()
    if args.no_eci_fallback:
        seg_map = {}
    log.info("party maps: agra=%d segment=%d eci_up=%d (acs=%d)",
             len(agra_map), len(seg_map), len(eci_map), len(seg_ac))
    demo_2017, demo_cols = load_demo_2017()
    log.info("demo 2017: %d booth rows, %d cols", len(demo_2017),
             len(demo_cols))

    PROC.mkdir(parents=True, exist_ok=True)
    ff = open(PROC / "state_fact.csv", "w", newline="", encoding="utf-8")
    fw = csv.DictWriter(ff, fieldnames=["booth_uid", "election", "ac",
                                        "candidate", "party", "votes"])
    fw.writeheader()
    votes: dict = {}        # (uid, party) -> votes
    by_uid: dict = {}       # uid -> {party: votes}
    booths: list = []
    seen_uid: set = set()
    dup_rows = 0
    cover: list = []

    def keep_booth(b) -> bool:
        try:
            ac = int(b["ac"])
        except (TypeError, ValueError):
            return False
        if ac == -1:
            return False
        return want_ac is None or ac in want_ac

    seen_fact: dict = {}  # (uid, candidate) -> votes (dup guard)
    dup_facts = 0

    def take_facts(fs, allowed_uids=None):
        nonlocal dup_facts
        for x in fs:
            fw.writerow(x)
            if allowed_uids is not None \
                    and x["booth_uid"] not in allowed_uids:
                continue
            if x["party"] in ("NOTA", "UNMAPPED"):
                continue
            key = (x["booth_uid"], x["party"])
            fkey = (x["booth_uid"], x["candidate"])
            vv = int(x["votes"])
            if fkey in seen_fact:
                if seen_fact[fkey] != vv:
                    dup_facts += 1
                continue  # same booth+candidate twice: first wins
            seen_fact[fkey] = vv
            votes[key] = votes.get(key, 0) + vv
            by_uid.setdefault(x["booth_uid"], {})[x["party"]] = \
                by_uid.setdefault(x["booth_uid"], {}).get(
                    x["party"], 0) + vv

    def take_booths(bs):
        nonlocal dup_rows
        for b in bs:
            if not keep_booth(b):
                continue
            b["ac"] = int(b["ac"])
            if b["booth_uid"] in seen_uid:
                dup_rows += 1
                continue
            seen_uid.add(b["booth_uid"])
            booths.append(b)

    # ---- 2017/2019/2022: English first, Hindi only for uncovered ACs.
    # Per-file ingest (one bad workbook can't kill the batch); filename
    # / filemap AC is authoritative over heuristic content reads.
    logging.getLogger("agra").setLevel(logging.WARNING)
    eid_of = {"2017": "VS2017", "2019": "LS2019", "2022": "VS2022"}
    fmap_ac = filemap_ac()
    n_fail = 0
    for year in ("2017", "2019", "2022"):
        # xlrd reads .xls only; 2022 also ships Hindi-duplicate .xlsx
        # files (openpyxl-only) which are counted, not failed.
        files = sorted((DATA / year).glob("*.xls"))
        xls_stems = {f.stem for f in files}
        xlsx_only = sorted(p for p in (DATA / year).glob("*.xlsx")
                           if p.stem not in xls_stems)
        if xlsx_only:
            log.info("%s: %d .xlsx Hindi duplicates not ingested "
                     "(HINDI_XLSX_SKIP)", year, len(xlsx_only))
            cover.append({"election": eid_of[year], "ac": "",
                          "ac_name": "", "file":
                          f"{len(xlsx_only)}x .xlsx Hindi duplicates",
                          "booths": 0,
                          "note": "HINDI_XLSX_SKIP (openpyxl-only, "
                                  "needs Hindi parser): " +
                                  ", ".join(p.name for p in
                                            xlsx_only[:8]) +
                                  ("..." if len(xlsx_only) > 8 else "")})
        if want_ac is not None:
            files = [f for f in files
                     if (fmap_ac.get(year, {}).get(f.name.lower(),
                                                   stem_ac(f))
                         in want_ac)]
        en, hi = [], []
        for f in files:
            (hi if file_is_hindi_xls(f) else en).append(f)
        log.info("%s files=%d EN=%d HI=%d", year, len(files), len(en),
                 len(hi))
        covered: set = set()
        for grp, hindi in ((en, False), (hi, True)):
            for f in grp:
                t_f = time.time()
                try:
                    fs, bs, cv = ingest_eci(eid_of[year], [f])
                except Exception as ex:
                    n_fail += 1
                    cover.append({"election": eid_of[year], "ac": "",
                                  "ac_name": "", "file": f.name,
                                  "booths": 0,
                                  "note": f"INGEST-FAIL "
                                          f"{type(ex).__name__}: {ex}"})
                    continue
                auth = fmap_ac.get(year, {}).get(f.name.lower(),
                                                stem_ac(f))
                got = {b["ac"] for b in bs
                       if isinstance(b.get("ac"), int)}
                if auth is not None and len(got) == 1 \
                        and got != {auth}:
                    n_re = remap_booths(bs, fs, auth)
                    cv = [{**c, "note": (c.get("note") or "") +
                                     f" [AC-override file={auth}]"}
                          for c in cv]
                    log.warning("%s: content AC %s -> filename/filemap "
                                "AC %s (%d booths remapped)", f.name, got,
                                auth, n_re)
                elif auth is not None and len(got) > 1:
                    bad = {a for a in got
                           if not isinstance(a, int)
                           or not 1 <= a <= 403}
                    if bad:
                        keep = [b for b in bs
                                if b.get("ac") not in bad]
                        dropped = len(bs) - len(keep)
                        bs = keep
                        fs_keep = {b["booth_uid"] for b in keep}
                        fs = [x for x in fs
                              if x["booth_uid"] in fs_keep]
                        cv = [{**c, "note": (c.get("note") or "") +
                                         f" [dropped out-of-range ACs "
                                         f"{sorted(bad)}: {dropped} rows]"}
                              for c in cv]
                if hindi:
                    bs = [b for b in bs
                          if not (isinstance(b.get("ac"), int)
                                  and b["ac"] in covered)]
                allowed = {b["booth_uid"] for b in bs if keep_booth(b)}
                take_facts(fs, allowed)
                take_booths(bs)
                log.info("%s: booths=%d facts=%d (%.1fs)", f.name,
                         len(bs), len(fs), time.time() - t_f)
                suffix = " [hindi-fallback]" if hindi else ""
                cover += [{**c, "note": (c.get("note") or "") + suffix}
                          for c in cv]
                if not hindi:
                    covered |= {b["ac"] for b in booths
                                if b["election"] == eid_of[year]
                                and isinstance(b.get("ac"), int)}
    if n_fail:
        log.warning("ingest failures (quarantined, see coverage): %d",
                    n_fail)
    # ---- 2024: flat root shorts (REVIEW excluded), winners only
    f24 = sorted(p for p in (DATA / "2024").glob("*.xlsx")
                 if "REVIEW" not in p.name
                 and re.match(r"^\d{1,3}\.xlsx$", p.name))
    if want_ac is not None:
        f24 = [p for p in f24 if int(p.stem) in want_ac]
    for f in f24:
        try:
            fs, bs, cv = ingest_2024_state([f], agra_map, seg_map,
                                           eci_map)
        except Exception as ex:
            cover.append({"election": "LS2024", "ac": "", "ac_name": "",
                          "file": f.name, "booths": 0,
                          "note": f"INGEST-FAIL {type(ex).__name__}: "
                                  f"{ex}"})
            continue
        take_facts(fs)
        take_booths(bs)
        cover += cv
    ff.close()
    log.info("ingest: booths=%d dup_rows_skipped=%d vote_keys=%d",
             len(booths), dup_rows, len(votes))

    # ---- indexes
    bidx: dict = defaultdict(list)   # (ac, election) -> booths
    psidx: dict = {}                 # (ac, election, ps) -> booth
    for b in booths:
        bidx[(b["ac"], b["election"])].append(b)
        psidx.setdefault((b["ac"], b["election"], str(b["ps"])), b)
    fielded: dict = defaultdict(set)
    for b in booths:
        for p in by_uid.get(b["booth_uid"], {}):
            fielded[b["election"]].add(p)

    def share(uid, party, election):
        if party not in fielded.get(election, set()):
            return None
        b = uid_booth.get(uid)
        if b is None:
            return None
        polled = int(b["polled"] or 0)
        if not polled:
            return None
        return by_uid.get(uid, {}).get(party, 0) / polled

    uid_booth = {b["booth_uid"]: b for b in booths}

    # Party B per AC: top non-BJP in VS2022 (last fully-labeled
    # election). Pins B for comparability with the approved Agra
    # baseline; 2024 labels are name-inferred.
    acs = sorted({b["ac"] for b in booths
                  if isinstance(b.get("ac"), int) and b["ac"] > 0})
    if want_ac is not None:
        acs = [a for a in acs if a in want_ac]
    party_b: dict = {}

    def top_non_bjp(ac, e):
        tot: dict = {}
        for b in bidx.get((ac, e), []):
            for p, v in by_uid.get(b["booth_uid"], {}).items():
                if p != PARTY_A and v > 0:
                    tot[p] = tot.get(p, 0) + v
        return tot

    for ac in acs:
        tot = top_non_bjp(ac, "VS2022")
        if tot:
            party_b[ac] = (max(tot, key=lambda p: tot[p]), "VS2022")
            continue
        for e in reversed(ELECTIONS):
            if e == "VS2022":
                continue
            tot = top_non_bjp(ac, e)
            if tot:
                party_b[ac] = (max(tot, key=lambda p: tot[p]), e + "*")
                break
        if ac not in party_b:
            party_b[ac] = ("", "")

    # ---- 2024 segment check: booth polled sums vs ECI AC totals
    # (segment valid_sum + NOTA). Thin conversion means most ACs differ;
    # reconciled ACs prove the booth set is complete.
    seg_ok = 0
    seg_bad: list = []
    for ac in acs:
        blist = bidx.get((ac, "LS2024"), [])
        st = seg_ac.get(ac)
        if not blist or not st:
            continue
        booth_polled = sum(int(b["polled"] or 0) for b in blist)
        seg_total = st["valid_sum"] + st["nota"]
        if seg_total and abs(booth_polled - seg_total) / seg_total <= 0.005:
            seg_ok += 1
        else:
            pct = booth_polled / seg_total * 100 if seg_total else 0
            seg_bad.append((ac, booth_polled, seg_total, pct))
    for ac, bp, stotal, pct in sorted(seg_bad):
        _nm, _dd = ac_info.get(ac, ("", "UNKNOWN"))
        cover.append({"election": "LS2024", "ac": ac, "ac_name": _nm,
                      "file": "SEG-CHECK (booth sum vs ECI segment total)",
                      "booths": len(bidx.get((ac, "LS2024"), [])),
                      "note": f"booth_polled={bp} "
                              f"seg_valid+nota={stotal} ({pct:.1f}%)"})
    cover.append({"election": "LS2024", "ac": "", "ac_name": "",
                  "file": "SEG-CHECK summary", "booths": "",
                  "note": f"{seg_ok} ACs reconcile within 0.5%, "
                          f"{len(seg_bad)} differ (thin 2024 conversion)"})
    log.info("seg-check: %d ACs reconcile, %d differ", seg_ok,
             len(seg_bad))

    # ---- 2017 demo join check (modeled rolls demographics by AC+PS)
    demo_hit = sum(1 for b in booths if b["election"] == "VS2017"
                   and (b["ac"], demo_norm_ps(b["ps"])) in demo_2017)
    demo_vs = sum(1 for b in booths if b["election"] == "VS2017")
    cover.append({"election": "VS2017", "ac": "", "ac_name": "",
                  "file": "DEMO-CHECK summary (uprolls2017 join)",
                  "booths": "",
                  "note": f"{demo_hit}/{demo_vs} VS2017 booths matched; "
                          f"{len(demo_2017)} demo rows"})
    log.info("demo-check: %d/%d VS2017 booths matched", demo_hit,
             demo_vs)

    # ---- CSVs
    with open(PROC / "state_booth.csv", "w", newline="",
               encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["booth_uid", "election", "ac",
                                          "ac_name", "ps", "ps_name",
                                          "electors", "male", "female",
                                          "other", "epic", "tendered",
                                          "polled", "valid", "nota", "src"])
        w.writeheader()
        for b in booths:
            w.writerow({k: b.get(k, "") for k in
                        ["booth_uid", "election", "ac", "ac_name", "ps",
                         "ps_name", "electors", "male", "female", "other",
                         "epic", "tendered", "polled", "valid", "nota",
                         "src"]})
    with open(PROC / "state_coverage.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["election", "ac", "ac_name",
                                          "file", "booths", "valid_ok",
                                          "has_total", "note"])
        w.writeheader()
        for c in cover:
            w.writerow({k: c.get(k, "") for k in
                        ["election", "ac", "ac_name", "file", "booths",
                         "valid_ok", "has_total", "note"]})
    log.info("CSVs written: %d ACs, %d booths (%.0fs)", len(acs),
             len(booths), time.time() - t_all)
    if args.skip_workbook:
        return 0

    # ---- workbook
    import openpyxl
    from openpyxl.formatting.rule import CellIsRule, DataBarRule
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("All_ACs")
    _to_cols: list = []
    for _e in ("2017", "2019", "2022", "2024"):
        _to_cols += [f"E{_e}", f"M{_e}", f"F{_e}", f"O{_e}", f"T{_e}",
                     f"TO%{_e}"]
    _to_cols.append("2024 AC Electors")
    _demo_hdr = [c + " (modeled)" for c in demo_cols]
    ws.append(["UTTAR PRADESH (AC 1-403) BOOTH ANALYSIS (A=BJP fixed; "
               "B = per-row Party B col; zeros where data absent; "
               "trailing cols = turnout E/M/F/O/T/TO% per election + "
               "2024 AC electors from the ECI segment file + 2017 "
               "modeled booth demographics (uprolls2017))"])
    ws.append(["AC", "District", "Polling station name",
               "Polling Station Address",
               "2017", "2019", "2022", "2024",
               "Defination", "Average Diff", "Latest Diff", "",
               "Party B",
               "2017 Vidhansabha", "", "",
               "Voting.Diff", "",
               "2019 Loksabha", "", "",
               "Voting.Diff", "",
               "2022 Vidhansabha", "", "",
               "Voting.Diff", "",
               "2024 Loksabha", "", "",
               "Voting.Diff", ""] + _to_cols + _demo_hdr)
    ws.append(["", "", "मतदान केंद्र", "मतदान केंद्र का विवरण",
               "", "", "", "", "", "", "", "", "",
               f"{PARTY_A} V.%", "B V.%", "",
               "", "",
               f"{PARTY_A} V.%", "B V.%", "",
               "", "",
               f"{PARTY_A} V.%", "B V.%", "",
               "", "",
               f"{PARTY_A} V.%", "B V.%", "",
               ""] + [""] * (len(_to_cols) + len(_demo_hdr)))
    zone_counts: dict = defaultdict(int)
    for ac in acs:
        _ac_name, dist = ac_info.get(ac, ("", "UNKNOWN"))
        bparty, _belec = party_b.get(ac, ("", ""))
        ps_all = sorted(
            {b["ps"] for e in ELECTIONS for b in bidx.get((ac, e), [])},
            key=lambda p: (0, int(p)) if str(p).isdigit() else (1, str(p)))
        for ps in ps_all:
            per_e = {e: psidx.get((ac, e, str(ps))) for e in ELECTIONS}
            if not any(per_e.values()):
                continue
            cands = [per_e[e]["ps_name"] for e in reversed(ELECTIONS)
                     if per_e[e] and per_e[e].get("ps_name")]
            eng = [n for n in cands
                   if n and not any(ch.islower() for ch in str(n))
                   and len(str(n)) > 6]
            nm = max(eng, key=len) if eng else ""
            nm = nm or next((n for n in cands if str(n or "").strip()),
                            "")
            row = [str(ac), dist, f"{ps} - {nm}", nm,
                   *[per_e[e]["ps"] if per_e[e] else "" for e in ELECTIONS]]
            diffs = []
            for e in ELECTIONS:
                if not per_e[e]:
                    diffs.append(None)
                    continue
                uid = per_e[e]["booth_uid"]
                a = share(uid, PARTY_A, e)
                bb = share(uid, bparty, e) if bparty else None
                diffs.append(None if a is None or bb is None else a - bb)
            have = [d for d in diffs if d is not None]
            avg = sum(have) / len(have) if have else None
            latest = next((d for d in reversed(diffs)
                           if d is not None), None)
            if len(have) < 2:
                zone = "Data Not sufficient"
            elif avg > SAFE_UP and (latest or 0) > 0:
                zone = "Safe"
            elif avg < DIFF_DOWN and (latest or 0) < 0:
                zone = "Difficult"
            elif (avg or 0) > 0 and (latest or 0) > 0:
                zone = "Favorable"
            else:
                zone = "Battlefield"
            zone_counts[zone] += 1
            row += [zone,
                    round(avg, 4) if avg is not None else 0,
                    round(latest, 4) if latest is not None else 0, "",
                    bparty or ""]
            for e, d in zip(ELECTIONS, diffs):
                if not per_e[e]:
                    row += [0, 0, "", 0, ""]
                    continue
                uid = per_e[e]["booth_uid"]
                a = share(uid, PARTY_A, e)
                bb = share(uid, bparty, e) if bparty else None
                row += [round(a, 4) if a is not None else 0,
                        round(bb, 4) if bb is not None else 0, "",
                        round(d, 4) if d is not None else 0, ""]
            # Trailing turnout cols (same sheet, never a new sheet):
            # Electors + Voters Turnout M/F/O/T + TO% per election.
            # 2024 Form20 has no gender split (M/F/O blank, T=polled,
            # TO% blank); AC-level 2024 electors come from the segment
            # file in the last column.
            for e in ELECTIONS:
                bb = per_e[e]
                if not bb:
                    row += ["", "", "", "", "", ""]
                    continue
                elect = bb.get("electors")
                polled = bb.get("polled")
                row += [elect if elect is not None else "",
                        bb.get("male")
                        if bb.get("male") is not None else "",
                        bb.get("female")
                        if bb.get("female") is not None else "",
                        bb.get("other")
                        if bb.get("other") is not None else "",
                        polled if polled is not None else ""]
                if elect and polled is not None:
                    row.append(round(polled / elect, 4))
                else:
                    row.append("")
            row.append(seg_ac.get(ac, {}).get("electors", ""))
            # Trailing 2017 modeled demographics (same sheet, never a
            # new sheet): joined by (AC, PS) on the 2017 booth only, shown
            # on every row of that booth across elections (2017 vintage).
            # R5 suppression + age sanity gates inside demo_cell; the
            # "(modeled)" header tag + Methods carry the uncertainty.
            drow = demo_2017.get((ac, demo_norm_ps(ps)), {})
            d_elect = None
            try:
                d_elect = float(drow.get("electors_17", ""))
            except (TypeError, ValueError):
                d_elect = None
            for _dc in demo_cols:
                row.append(demo_cell(_dc, drow.get(_dc), d_elect)
                           if drow else "")
            ws.append(row)
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = ws.dimensions
    for col, w in (("A", 8), ("B", 18), ("C", 28), ("D", 34)):
        ws.column_dimensions[col].width = w

    # Booth_Votes (AC blocks, zeros where absent)
    wv = wb.create_sheet("Booth_Votes")
    wv.append(["AC", "District", "booth", "address", "2017", "2019",
               "2022", "2024", "Defination"])
    for ac in acs:
        _ac_name, dist = ac_info.get(ac, ("", "UNKNOWN"))
        ps_all = sorted(
            {b["ps"] for e in ELECTIONS for b in bidx.get((ac, e), [])},
            key=lambda p: (0, int(p)) if str(p).isdigit() else (1, str(p)))
        wv.append([f"AC{ac}", dist])
        for ps in ps_all:
            per_e = {e: psidx.get((ac, e, str(ps))) for e in ELECTIONS}
            if not any(per_e.values()):
                continue
            nm = ""
            for e in reversed(ELECTIONS):
                if per_e[e] and per_e[e].get("ps_name"):
                    nm = per_e[e]["ps_name"]
                    break
            wv.append([f"{ps} - {nm}", dist, nm,
                       *[per_e[e]["ps"] if per_e[e] else ""
                         for e in ELECTIONS], ""])
            vrow = ["", "", ""]
            for e in ELECTIONS:
                if not per_e[e]:
                    vrow.append("A=0 B=0 E=0 M=0 F=0 O=0 T=0")
                    continue
                uid = per_e[e]["booth_uid"]
                va = by_uid.get(uid, {}).get(PARTY_A, 0)
                bp = party_b.get(ac, ("", ""))[0]
                vb = by_uid.get(uid, {}).get(bp, 0) if bp else 0
                bb = per_e[e]
                vrow.append(
                    f"A={va} B={vb} E={bb.get('electors') or 0} "
                    f"M={bb.get('male') or 0} F={bb.get('female') or 0} "
                    f"O={bb.get('other') or 0} T={bb.get('polled') or 0}")
            vrow.append("")
            wv.append(vrow)
    wz = wb.create_sheet("Zone_Counts")
    wz.append(["Type of Booths", "Nos"])
    for z in ["Safe", "Favorable", "Battlefield", "Difficult",
              "Data Not sufficient"]:
        wz.append([z, zone_counts.get(z, 0)])
    wm = wb.create_sheet("Methods_Zones")
    wm["A1"] = ("Statewide batch (AC 1-403; ACs with no files skipped). "
                "A=BJP fixed; B per row = top non-BJP by VS2022 AC votes "
                "(Party B col; '*' = thin fallback to the latest available "
                "election). 2024 parties: Agra exact map > ECI "
                "assembly-segment file (official, all 403 ACs) > ECI UP "
                "unambiguous names; rest UNMAPPED->0. 2024 AC electors + "
                "SEG-CHECK validation (booth sums vs segment totals) come "
                "from the segment file; booth M/F/O are blank for 2024 "
                "(Form20 has no gender split). "
                "English sheets preferred per AC; Hindi only where no "
                "English exists. 2022 .xlsx Hindi duplicates need an "
                "openpyxl Hindi parser (HINDI_XLSX_SKIP), so VS2022 covers "
                "the 225 English .xls ACs only. ECI booth blocks come in "
                "with-Name and no-Name (most 2017) geometries, "
                "auto-detected per sheet; column-index helper rows are "
                "skipped via their numeric triplet-party cells (never "
                "phantom booths). Trailing All_ACs cols: Electors + Voters "
                "Turnout Male/Female/Other/Total + TO% per election "
                "(M+F+O=T; blank = no data), then 2024 AC Electors "
                "(segment, per-AC constant), then 2017 modeled booth "
                "demographics (uprolls2017, 2017 vintage, joined by AC+PS "
                "and shown on every row of that booth). Demo cells are "
                "MODELED ESTIMATES with known calibration problems: "
                "parsi/christian/jain/sikh shares inflated vs Census, "
                "women% averages ~66% (implausible), some age cells hold "
                "unparsed astronomic values (blanked unless avg 15-100 / "
                "sd 0-50); modeled cells blanked where electors_17 < 200 "
                "(RULES R5); missing_percent_17 is the quality signal. "
                "New data always extends "
                "existing sheets as columns, never new sheets. "
                "Zeros = absent data (display); zones use "
                "real diffs only (n<2 -> Data Not sufficient). Zones: Safe "
                "avg>+0.10&latest>0; Difficult avg<-0.10&latest<0; "
                "Favorable avg>0&latest>0; Battlefield otherwise. "
                "Duplicate booth rows: first wins. Flags are "
                "statistical_outlier, never fraud.")
    # ---- styling (same vocabulary as the Agra book, shifted for AC+B cols)
    hdr_fill = PatternFill("solid", fgColor=HDR_FILL)
    hdr_font = Font(bold=True, color=HDR_FONT, size=11)
    pos_fill = PatternFill("solid", fgColor=POS_FILL)
    neg_fill = PatternFill("solid", fgColor=NEG_FILL)
    wrap = Alignment(wrap_text=True, vertical="center")
    ws.cell(1, 1).font = Font(bold=True, size=12)
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(2, c)
        if str(cell.value or "").strip():
            cell.fill = hdr_fill
            cell.font = hdr_font
            cell.alignment = wrap
    last = ws.max_row
    for col in ["J", "K", "Q", "V", "AA", "AF"]:
        rng = f"{col}4:{col}{last}"
        ws.conditional_formatting.add(
            rng, CellIsRule("greaterThan", formula=[SAFE_UP],
                            fill=pos_fill))
        ws.conditional_formatting.add(
            rng, CellIsRule("lessThan", formula=[DIFF_DOWN],
                            fill=neg_fill))
    for col in ["N", "O", "T", "U", "Y", "Z", "AD", "AE"]:
        ws.conditional_formatting.add(
            f"{col}4:{col}{last}",
            DataBarRule(start_type="num", start_value=0,
                        end_type="num", end_value=1, color="638EC6"))
    for r in range(4, last + 1):
        cell = ws.cell(r, 9)
        z = str(cell.value or "")
        if z in ZONE_FILL:
            cell.fill = PatternFill("solid", fgColor=ZONE_FILL[z])
            cell.font = Font(bold=True, color=ZONE_FONT[z])
    for c in range(1, wz.max_column + 1):
        cell = wz.cell(1, c)
        cell.fill = hdr_fill
        cell.font = hdr_font
    for r in range(2, wz.max_row + 1):
        z = str(wz.cell(r, 1).value or "")
        if z in ZONE_FILL:
            for c in (1, 2):
                wz.cell(r, c).fill = PatternFill(
                    "solid", fgColor=ZONE_FILL[z])
    wm.column_dimensions["A"].width = 180
    wm["A1"].alignment = wrap

    outpath = ROOT / args.out_report
    outpath.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        wb.save(str(outpath))
    except PermissionError:
        import datetime as _dt
        outpath = outpath.parent / (outpath.stem + "_%s.xlsx"
                                    % _dt.datetime.now().strftime(
                                        "%Y%m%d-%H%M"))
        wb.save(str(outpath))
        print(f"(main file locked - saved {outpath.name} instead)",
              flush=True)
    print(f"wrote {outpath} zones={dict(zone_counts)} "
          f"save={time.time() - t0:.0f}s total={time.time() - t_all:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
