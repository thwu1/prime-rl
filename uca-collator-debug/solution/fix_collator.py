#!/usr/bin/env python3
"""
Fix the three bugs in /app/collator.py.

Bug 1 — Missing NFD normalisation:
    The sort_key() method must normalise the input to NFD before building
    the collation element array.  The current code passes the raw string
    through unchanged.

Bug 2 — Wrong bit-shift in implicit weight derivation:
    The fallback path in _compute_implicit() uses ``cp >> 16`` to compute
    the AAAA primary-weight lead unit for unassigned code points.  UTS #10
    Section 10.1.3 specifies ``cp >> 15`` (each AAAA group covers 32 K code
    points, not 64 K).

Bug 3 — SHIFTED mode L4 taken from L2 instead of L1:
    In _apply_variable_weighting(), the quaternary weight for a variable
    element is assigned from ``w2`` (the original secondary weight) instead
    of ``w1`` (the original primary weight).
"""

import re


def apply_fixes():
    path = "/app/collator.py"
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # ------------------------------------------------------------------
    # Bug 1: replace  ``normalized = string``
    #    with ``normalized = unicodedata.normalize("NFD", string)``
    # ------------------------------------------------------------------
    old_norm = 'normalized = string'
    new_norm = 'normalized = unicodedata.normalize("NFD", string)'
    if old_norm in src:
        src = src.replace(old_norm, new_norm, 1)
        print("[fix] Bug 1: added NFD normalisation in sort_key()")
    else:
        print("[skip] Bug 1: pattern not found (already fixed?)")

    # ------------------------------------------------------------------
    # Bug 2: replace  ``cp >> 16``  with  ``cp >> 15``
    #         in the unassigned-fallback path of _compute_implicit()
    # ------------------------------------------------------------------
    old_shift = "(cp >> 16)"
    new_shift = "(cp >> 15)"
    if old_shift in src:
        src = src.replace(old_shift, new_shift, 1)
        print("[fix] Bug 2: corrected implicit-weight shift to >> 15")
    else:
        print("[skip] Bug 2: pattern not found (already fixed?)")

    # ------------------------------------------------------------------
    # Bug 3: replace  ``l4 = w2``  with  ``l4 = w1``
    #         inside the variable-element branch of _apply_variable_weighting()
    # ------------------------------------------------------------------
    old_l4 = "l4 = w2"
    new_l4 = "l4 = w1"
    if old_l4 in src:
        src = src.replace(old_l4, new_l4, 1)
        print("[fix] Bug 3: SHIFTED L4 now uses original L1 (primary)")
    else:
        print("[skip] Bug 3: pattern not found (already fixed?)")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)

    print("\nAll fixes applied.")


if __name__ == "__main__":
    apply_fixes()
