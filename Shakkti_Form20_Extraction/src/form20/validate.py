"""Stage 6: validation and automatic repair using the sheet's own arithmetic.

Every polling-station row of a Form 20 must satisfy

    (1)  sum(candidate votes)            == total of valid votes
    (2)  valid + rejected + NOTA         == total

and the printed "Total EVM votes" row must equal the column sums of all rows.

For each row we collect alternative readings for every cell (the two OCR
variants and the usual slips such as a ruling-line residue read as a leading or
trailing "1"), then search for the cheapest combination that satisfies both
identities. Blank cells are solved from the equations. Changing a low-confidence
reading is cheaper than changing a confident one. A row that cannot be made
consistent, or whose best fix is not unique, goes to manual review.
"""
import itertools
from dataclasses import dataclass, field

COST_B = 1.0          # reading from the other OCR variant
COST_STRIP = 1.5      # drop a leading / trailing "1" (line residue)
COST_FREE = 3.0       # value solved from the equations instead of read
MAX_COMBOS = 4000
AMBIGUITY_GAP = 0.25  # best fix must beat the runner-up by this much
ALT_GAP = 3.0         # alternatives kept for column-total reconciliation


@dataclass
class RowResult:
    values: list                    # nc + 5 ints (None where unresolved)
    status: str                     # OK | AUTO_CORRECTED | REVIEW
    note: str = ""
    changed: list = field(default_factory=list)       # indices that differ from the primary read
    primary: list = field(default_factory=list)       # the plain first reading (str)
    alternatives: list = field(default_factory=list)  # [(extra_cost, values)] other plausible fixes


def _to_int(t):
    return int(t) if t.isdigit() and len(t) <= 7 else None


def cell_scale(cell):
    """Changing a low-confidence reading is cheaper than changing a confident one."""
    return 0.4 + 0.6 * (cell.conf / 100.0 if cell.text else 0.5)


def cell_alternatives(cell):
    """[(value, cost)] for one cell; empty list when nothing was read."""
    out = {}
    scale = cell_scale(cell)

    def add(v, cost):
        cost = cost * scale
        if v is not None and (v not in out or cost < out[v]):
            out[v] = cost

    for k, t in enumerate(cell.ordered_reads()):
        if not t:
            continue
        add(_to_int(t), 0.0 if k == 0 else COST_B)
        if len(t) > 1:
            if t[0] == "1":
                add(_to_int(t[1:]), COST_STRIP)
            if t[-1] == "1":
                add(_to_int(t[:-1]), COST_STRIP)
    return sorted(out.items(), key=lambda kv: kv[1])


def _solve(vals, nc):
    """Fill single unknowns using the two identities. vals: list with None for
    unknown. Returns the completed list, or None if inconsistent/unsolvable."""
    v = list(vals)
    iv, ir, inn, it = nc, nc + 1, nc + 2, nc + 3
    for _ in range(4):
        progressed = False
        eq1 = list(range(nc)) + [iv]
        eq2 = [iv, ir, inn, it]
        for eq, rhs_idx, lhs in ((eq1, iv, list(range(nc))), (eq2, it, [iv, ir, inn])):
            unknown = [i for i in eq if v[i] is None]
            if len(unknown) == 1:
                u = unknown[0]
                if u == rhs_idx:
                    x = sum(v[i] for i in lhs)
                else:
                    x = v[rhs_idx] - sum(v[i] for i in lhs if i != u)
                if x < 0:
                    return None
                v[u] = x
                progressed = True
        if not progressed:
            break
    if any(v[i] is None for i in range(nc + 4)):
        return None
    if sum(v[:nc]) != v[iv] or v[iv] + v[ir] + v[inn] != v[it]:
        return None
    return v


def enumerate_solutions(cells, nc, max_extra=2):
    """All identity-satisfying readings of a row: [(cost, values)] sorted by cost.
    max_extra = how many additional cells may be solved from the equations
    (beyond blank ones) when no cheaper reading works."""
    n = nc + 5
    alts = [cell_alternatives(c) for c in cells]
    scales = [cell_scale(c) for c in cells]

    def search(free_set):
        found = {}
        choices = []
        for i in range(n):
            if i in free_set or not alts[i]:
                choices.append([(None, COST_FREE * scales[i] if i in free_set else 0.0)])
            else:
                choices.append(alts[i])
        size = 1
        for ch in choices:
            size *= len(ch)
        if size > MAX_COMBOS:
            choices = [ch[:2] for ch in choices]
        for combo in itertools.product(*choices):
            vals = [c[0] for c in combo]
            cost = sum(c[1] for c in combo)
            tendered_blank = vals[nc + 4] is None
            solved = _solve(vals[: nc + 4] + [0 if tendered_blank else vals[nc + 4]], nc)
            if solved is None:
                continue
            if tendered_blank:
                solved[nc + 4] = None
            key = tuple(solved)
            if key not in found or cost < found[key]:
                found[key] = cost
        return found

    blanks = {i for i in range(nc + 4) if not alts[i]}
    pool = [i for i in range(nc + 4) if i not in blanks]
    best = {}
    for extra in range(0, max_extra + 1):
        subsets = [()] if extra == 0 else list(itertools.combinations(pool, extra))
        for sub in subsets:
            for k, c in search(set(sub)).items():
                if k not in best or c < best[k]:
                    best[k] = c
        if best:
            break
    return sorted(((c, list(k)) for k, c in best.items()), key=lambda t: t[0])


def solve_row(cells, nc):
    """cells: list of CellRead for the nc+5 numeric columns -> RowResult."""
    n = nc + 5
    alts = [cell_alternatives(c) for c in cells]
    primary = [c.text for c in cells]
    base = [(a[0][0] if a and a[0][1] == 0.0 else None) for a in alts]

    # Fast path: the plain primary reading already satisfies both identities.
    if None not in base[: nc + 4]:
        full = list(base)
        if full[nc + 4] is None:
            full[nc + 4] = 0
        if _solve(full[: nc + 4] + [full[nc + 4]], nc) == full:
            return RowResult(values=full, status="OK", primary=primary)

    found = enumerate_solutions(cells, nc, max_extra=2)
    if found:
        best_cost, vals = found[0]
        changed = [i for i in range(n) if vals[i] is not None and str(vals[i]) != primary[i]]
        others = [(c - best_cost, v) for c, v in found[1:] if c - best_cost < ALT_GAP][:12]
        if any(gap < AMBIGUITY_GAP for gap, _ in others):
            return RowResult(
                vals, "REVIEW", "ambiguous: several equally likely readings", changed, primary,
                alternatives=others,
            )
        return RowResult(vals, "AUTO_CORRECTED", "", changed, primary, alternatives=others)

    prim_vals = [_to_int(p) if p else None for p in primary]
    return RowResult(prim_vals, "REVIEW", "arithmetic cannot be satisfied", [], primary)
