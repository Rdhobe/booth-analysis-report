"""Add (or refresh) the party-selectable booth view on a store that is already built.

  python Scripts/serve/add_booth_party.py [--db output/servedb.sqlite] [--parties BJP SP BSP INC]

Reads the store's own booth votes (vote, booth_election, ac_party, booth_row) and writes the `booth_party` table plus the
`parties` / `party_coverage` / `zone_rule` meta keys. No other table is changed, so a store built before the party view
existed does not need the 5-minute full rebuild. Stop the API first (SQLite takes a write lock), restart it after.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

try:                                  # python -m Scripts.serve.add_booth_party
    from Scripts.serve import booth_party
except ImportError:                   # python Scripts/serve/add_booth_party.py
    import booth_party

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("add_booth_party")
ROOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Add the party-selectable booth view to a built store")
    ap.add_argument("--db", default="output/servedb.sqlite")
    ap.add_argument("--parties", nargs="*", default=booth_party.PARTIES)
    args = ap.parse_args(argv)
    dbp = Path(args.db)
    dbp = dbp if dbp.is_absolute() else ROOT / dbp
    if not dbp.exists():
        log.error("store not found: %s (build it with Scripts/serve/build_servedb.py)", dbp)
        return 2
    con = sqlite3.connect(str(dbp))
    try:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = {"booth_row", "booth_election", "vote", "ac_party", "meta"} - have
        if missing:
            log.error("this does not look like a UPBI store, missing tables: %s", sorted(missing))
            return 2
        stats = booth_party.build_booth_party(con, args.parties)
        con.execute("ANALYZE")
        con.commit()
    finally:
        con.close()
    log.info("done: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
