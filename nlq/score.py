"""Does a generated result match the reference result? (DL-026 scoring rules)

- Every reference column must match a different column of the generated result.
  Extra generated columns are allowed; column names and order are ignored.
- Rows must match as whole rows: same number, and the same values in the matched
  columns (as a multiset, or in order when `ordered`).
- Numbers are compared rounded to 2 decimals. A share and the same share as a
  percentage count as equal (a column may be scaled by 100 either way).
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from decimal import Decimal
from itertools import product

# (reference scale, generated scale): same units; reference is a share and the
# generated a percentage; or the other way round.
SCALES = ((1, 1), (100, 1), (1, 100))


def _norm(value, scale=1):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return round(float(value) * scale + 0.0, 2)
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time(0) else value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value).strip()


def _is_numeric_column(values) -> bool:
    present = [v for v in values if v is not None]
    return bool(present) and all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
                                 for v in present)


def matches(ref_rows: list, gen_rows: list, ordered: bool = False) -> bool:
    ref_rows, gen_rows = [tuple(r) for r in ref_rows], [tuple(r) for r in gen_rows]
    if len(ref_rows) != len(gen_rows):
        return False
    if not ref_rows:
        return True
    n_ref, n_gen = len(ref_rows[0]), len(gen_rows[0])
    if n_gen < n_ref:
        return False

    ref_cols = [[r[j] for r in ref_rows] for j in range(n_ref)]
    gen_cols = [[r[k] for r in gen_rows] for k in range(n_gen)]
    # Candidate (generated column, reference scale, generated scale) per reference column.
    candidates = []
    for col in ref_cols:
        scales = SCALES if _is_numeric_column(col) else ((1, 1),)
        options = []
        for rs, gs in scales:
            ref_counter = Counter(_norm(v, rs) for v in col)
            options += [(k, rs, gs) for k in range(n_gen)
                        if (gs == 1 or _is_numeric_column(gen_cols[k]))
                        and Counter(_norm(v, gs) for v in gen_cols[k]) == ref_counter]
        if not options:
            return False
        candidates.append(options)

    # Try assignments of distinct generated columns; compare whole rows.
    for choice in product(*candidates):
        ks = [k for k, _, _ in choice]
        if len(set(ks)) != len(ks):
            continue
        ref_t = [tuple(_norm(r[j], rs) for j, (_, rs, _) in enumerate(choice)) for r in ref_rows]
        gen_t = [tuple(_norm(g[k], gs) for k, _, gs in choice) for g in gen_rows]
        if (ref_t == gen_t) if ordered else (Counter(ref_t) == Counter(gen_t)):
            return True
    return False
