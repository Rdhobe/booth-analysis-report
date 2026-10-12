"""Find a vote table's column structure from its arithmetic, whatever the sheet's layout.

The fixed layouts of pipeline.choose_layout (A, B, C) do not cover every printed variant: a duplicated NOTA column, valid
votes printed twice, no valid or rejected column at all, four or five leading columns. What every variant shares is the
arithmetic, so it is searched for directly. The candidate columns are a contiguous block of as many columns as the
official candidate count; valid is a column equal to the block's sum (or not printed); and valid + rejected + NOTA =
total holds for three more columns (rejected may be missing). The structure that satisfies this on the most rows wins.
"""
import numpy as np

MIN_SHARE = 0.85       # share of rows on which the identities must hold
MIN_ROWS = 8
MAX_IDS = 5            # leading columns before the candidate block


def _matrix(table):
    """Rows of ints (None for a blank or unreadable cell) as a float array with NaN for None."""
    return np.array([[np.nan if c is None else float(c) for c in row] for row in table])


NOTA_BAND = 3.0        # a NOTA column's share of the valid votes may be this many times off the official share


def discover(table, n_off, max_ids=MAX_IDS, nota_ratio=None):
    """table: rows of ints or None, one entry per column (identifier columns included). nota_ratio (the official
    NOTA votes over the official candidate votes) lets a column that is all zeros be refused as the NOTA column - it
    satisfies the identity just as well when NOTA is printed elsewhere (valid = total, rejected and NOTA both zero), so
    with the ratio known such a column is refused outright: no structure is better than a degenerate one.

    Returns (k, nc, spec, share) - k leading columns, nc candidate columns and spec = (valid, rejected, NOTA, total,
    tendered) as column indices relative to column k, None where the sheet does not print one - or None when nothing
    reaches MIN_SHARE."""
    rows = [r for r in table if sum(c is not None for c in r) >= 0.5 * len(r)]
    if len(rows) < MIN_ROWS or n_off < 2:
        return None
    mat = _matrix(rows)
    n_rows, m = mat.shape
    col_sum = np.nansum(mat, axis=0)
    best, best_key = None, None
    for a in range(0, min(max_ids, m - n_off - 2) + 1):
        block = mat[:, a:a + n_off]
        seen = ~np.isnan(block).all(axis=1)
        sums = np.where(seen, np.nansum(block, axis=1), np.nan)
        cols = list(range(a + n_off, m))
        bases = [(None, sums)]
        for j in cols:
            if np.mean(sums == mat[:, j]) >= MIN_SHARE:
                bases.append((j, mat[:, j]))
        for v, base in bases:
            for r in [None] + cols:
                r_vals = np.zeros(n_rows) if r is None else np.nan_to_num(mat[:, r])     # a blank cell is a zero
                for n in cols:
                    partial = base + r_vals + np.nan_to_num(mat[:, n])
                    for t in cols:
                        if len({x for x in (v, r, n, t) if x is not None}) != (v is not None) + (r is not None) + 2:
                            continue
                        share = float(np.mean(partial == mat[:, t]))
                        in_order = r is None or (r < n and col_sum[r] <= col_sum[n])     # rejected comes first and is the smaller
                        if nota_ratio:
                            ref = np.nansum(base)
                            if not (ref > 0 and col_sum[n] > 0 and 1 / NOTA_BAND <= (col_sum[n] / ref) / nota_ratio <= NOTA_BAND):
                                continue                     # not the size NOTA must be: never a NOTA column
                        key = (round(share, 4), v is not None, in_order, r is not None, n < t, -a)
                        if share >= MIN_SHARE and (best_key is None or key > best_key):
                            best_key, best = key, (a, v, r, n, t, share)
    if best is None:
        return None
    a, v, r, n, t, share = best
    used = {x for x in (v, r, n, t) if x is not None}
    spare = [j for j in range(a + n_off, m) if j not in used]
    e = spare[-1] if spare else None                 # tendered: the last column nobody else uses
    spec = tuple(None if x is None else x - a for x in (v, r, n, t, e))
    return a, n_off, spec, share
