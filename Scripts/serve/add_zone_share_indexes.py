"""One-off migration: composite (zone, share) indexes on an EXISTING
servedb.sqlite, so the overview top-booth ORDER BY/LIMIT queries use
an index instead of sorting ~48k rows per zone.

Safe to re-run (IF NOT EXISTS). No rebuild needed. Run externally:

  python Scripts/add_zone_share_indexes.py [--db server/servedb.sqlite]

Also mirrored in build_servedb.py's index block for future rebuilds.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("zoneidx")

IDXS = [
    ("idx_row_zone_a2017", "a2017"),
    ("idx_row_zone_a2019", "a2019"),
    ("idx_row_zone_a2022", "a2022"),
    ("idx_row_zone_a2024", "a2024"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="server/servedb.sqlite")
    args = ap.parse_args(argv)
    dbp = Path(args.db)
    if not dbp.exists():
        ap.error(f"not found: {dbp}")
    t = time.time()
    con = sqlite3.connect(str(dbp))
    for name, col in IDXS:
        con.execute(f'CREATE INDEX IF NOT EXISTS {name} ON booth_row'
                    f'(zone, "{col}")')
        log.info("ok %s", name)
    con.commit()
    con.execute("ANALYZE booth_row;")
    con.commit()
    con.close()
    log.info("done in %.0fs -> %s", time.time() - t, dbp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
