#!/usr/bin/env python3
"""
Systematic absence engine for all 230 crystallographic space groups.

Uses the geometric structure factor approach: for each symmetry operation
{W, t} of the general position, compute the reciprocal-space image
q = h @ W and the phase h . t.  Group operations by q and sum phase
factors exp(2 pi i h.t).  If all groups have vanishing sums, the
reflection is systematically absent.

Symmetry operations are obtained from spglib via hall numbers.
"""

import sys
import json
import math
import spglib
import numpy as np

# ---------------------------------------------------------------------------
# Precompute ITC number -> standard hall number mapping (first match)
# ---------------------------------------------------------------------------
_SG_TO_HALL = {}
for _hall in range(1, 531):
    _info = spglib.get_spacegroup_type(_hall)
    _sg = _info["number"]
    if _sg not in _SG_TO_HALL:
        _SG_TO_HALL[_sg] = _hall

# Cache symmetry operations {sg_number: (rotations, translations)}
_OPS_CACHE = {}


def _get_ops(sg):
    """Return (rotations, translations) for a space group number."""
    if sg not in _OPS_CACHE:
        hall = _SG_TO_HALL[sg]
        sym = spglib.get_symmetry_from_database(hall)
        _OPS_CACHE[sg] = (sym["rotations"], sym["translations"])
    return _OPS_CACHE[sg]


def _is_absent(h, k, l, rots, trans):
    """Return True if (h,k,l) is systematically absent.

    Algorithm:
      1. For each operation i, compute  q_i = (h,k,l) @ W_i   (= W_i^T h)
         and  phi_i = (h,k,l) . t_i.
      2. Group operations by q_i.
      3. Within each group, sum  S = sum exp(2 pi i phi_i).
      4. If |S| > 0.5 for any group  =>  reflection is ALLOWED.
         If all groups have |S| < 0.5  =>  reflection is ABSENT.
    """
    hkl = np.array([h, k, l], dtype=np.float64)
    n_ops = len(rots)

    groups = {}
    for i in range(n_ops):
        q = tuple(np.rint(hkl @ rots[i]).astype(int))
        phi = float(hkl @ trans[i])
        if q in groups:
            groups[q].append(phi)
        else:
            groups[q] = [phi]

    for phases in groups.values():
        re_sum = 0.0
        im_sum = 0.0
        for p in phases:
            angle = 2.0 * math.pi * p
            re_sum += math.cos(angle)
            im_sum += math.sin(angle)
        if re_sum * re_sum + im_sum * im_sum > 0.25:
            return False
    return True


# Crystal system -> (min_sg, max_sg) inclusive
_RANGES = {
    "triclinic": (1, 2),
    "monoclinic": (3, 15),
    "orthorhombic": (16, 74),
    "tetragonal": (75, 142),
    "trigonal": (143, 167),
    "hexagonal": (168, 194),
    "cubic": (195, 230),
}


# ===================================================================
# Command: check
# ===================================================================
def _cmd_check(args):
    sg = int(args[0])
    h, k, l = int(args[1]), int(args[2]), int(args[3])
    if h == 0 and k == 0 and l == 0:
        print("absent")
        return
    rots, trans = _get_ops(sg)
    print("absent" if _is_absent(h, k, l, rots, trans) else "allowed")


# ===================================================================
# Command: batch-check
# ===================================================================
def _cmd_batch_check(args):
    sg = int(args[0])
    rots, trans = _get_ops(sg)
    out = []
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        h, k, l = int(parts[0]), int(parts[1]), int(parts[2])
        if h == 0 and k == 0 and l == 0:
            status = "absent"
        else:
            status = "absent" if _is_absent(h, k, l, rots, trans) else "allowed"
        out.append({"h": h, "k": k, "l": l, "status": status})
    print(json.dumps(out))


# ===================================================================
# Command: identify
# ===================================================================
def _cmd_identify(args):
    cs = args[0].lower()
    if cs not in _RANGES:
        print(f"Unknown crystal system: {cs}", file=sys.stderr)
        sys.exit(1)

    observations = []
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        observations.append(
            (int(parts[0]), int(parts[1]), int(parts[2]), parts[3].lower())
        )

    lo, hi = _RANGES[cs]
    compatible = []
    for sg in range(lo, hi + 1):
        rots, trans = _get_ops(sg)
        ok = True
        for h, k, l, status in observations:
            if h == 0 and k == 0 and l == 0:
                continue
            absent = _is_absent(h, k, l, rots, trans)
            if (status == "absent" and not absent) or (
                status == "observed" and absent
            ):
                ok = False
                break
        if ok:
            compatible.append(sg)

    print(json.dumps({"compatible_space_groups": compatible}))


# ===================================================================
# Command: derive
# ===================================================================

def _gen_subset(name):
    """Generate sample Miller indices for a reflection subset.

    Each subset excludes indices belonging to more restrictive child
    subsets so that the hierarchical condition matching works correctly.
    """
    R = range(-8, 9)
    S = range(1, 17)
    if name == "hkl":
        # Exclude zonal subsets (any index zero) and diagonal zones
        # (|h|=|k|, |h|=|l|, |k|=|l| cover hhl and cubic equivalents).
        return [(h, k, l) for h in R for k in R for l in R
                if h != 0 and k != 0 and l != 0
                and abs(h) != abs(k) and abs(h) != abs(l)
                and abs(k) != abs(l)]
    elif name == "0kl":
        # Exclude serial subsets (k=0 -> 00l, l=0 -> 0k0).
        return [(0, k, l) for k in R for l in R if k != 0 and l != 0]
    elif name == "h0l":
        # Exclude serial subsets (h=0 -> 00l, l=0 -> h00).
        return [(h, 0, l) for h in R for l in R if h != 0 and l != 0]
    elif name == "hk0":
        # Exclude serial subsets (h=0 -> 0k0, k=0 -> h00).
        return [(h, k, 0) for h in R for k in R if h != 0 and k != 0]
    elif name == "hhl":
        # Exclude serial subset (h=0 gives (0,0,l) = 00l).
        return [(h, h, l) for h in R for l in R if h != 0]
    elif name == "h00":
        return [(h, 0, 0) for h in S]
    elif name == "0k0":
        return [(0, k, 0) for k in S]
    elif name == "00l":
        return [(0, 0, l) for l in S]
    return []


# Condition candidates: each is (display_string, predicate_for_presence)
# Predicate returns True when the reflection SATISFIES the condition (allowed).
# More restrictive conditions are listed first.
_COND_CANDIDATES = {
    "hkl": [
        ("h+k=2n,h+l=2n,k+l=2n",
         lambda h, k, l: (h+k) % 2 == 0 and (h+l) % 2 == 0 and (k+l) % 2 == 0),
        ("-h+k+l=3n", lambda h, k, l: (-h+k+l) % 3 == 0),
        ("h+k+l=2n", lambda h, k, l: (h+k+l) % 2 == 0),
        ("h+k=2n", lambda h, k, l: (h+k) % 2 == 0),
        ("h+l=2n", lambda h, k, l: (h+l) % 2 == 0),
        ("k+l=2n", lambda h, k, l: (k+l) % 2 == 0),
    ],
    "0kl": [
        ("k=2n,l=2n,k+l=4n",
         lambda h, k, l: k % 2 == 0 and l % 2 == 0 and (k+l) % 4 == 0),
        ("k=2n,l=2n", lambda h, k, l: k % 2 == 0 and l % 2 == 0),
        ("k+l=4n", lambda h, k, l: (k+l) % 4 == 0),
        ("k+l=3n", lambda h, k, l: (k+l) % 3 == 0),
        ("k+l=2n", lambda h, k, l: (k+l) % 2 == 0),
        ("k=2n", lambda h, k, l: k % 2 == 0),
        ("l=2n", lambda h, k, l: l % 2 == 0),
    ],
    "h0l": [
        ("h=2n,l=2n,h+l=4n",
         lambda h, k, l: h % 2 == 0 and l % 2 == 0 and (h+l) % 4 == 0),
        ("h=2n,l=2n", lambda h, k, l: h % 2 == 0 and l % 2 == 0),
        ("h+l=4n", lambda h, k, l: (h+l) % 4 == 0),
        ("-h+l=3n", lambda h, k, l: (-h+l) % 3 == 0),
        ("h+l=2n", lambda h, k, l: (h+l) % 2 == 0),
        ("h=2n", lambda h, k, l: h % 2 == 0),
        ("l=2n", lambda h, k, l: l % 2 == 0),
    ],
    "hk0": [
        ("h=2n,k=2n,h+k=4n",
         lambda h, k, l: h % 2 == 0 and k % 2 == 0 and (h+k) % 4 == 0),
        ("h=2n,k=2n", lambda h, k, l: h % 2 == 0 and k % 2 == 0),
        ("h+k=4n", lambda h, k, l: (h+k) % 4 == 0),
        ("-h+k=3n", lambda h, k, l: (-h+k) % 3 == 0),
        ("h+k=2n", lambda h, k, l: (h+k) % 2 == 0),
        ("h=2n", lambda h, k, l: h % 2 == 0),
        ("k=2n", lambda h, k, l: k % 2 == 0),
    ],
    "hhl": [
        ("2h+l=4n,h+l=2n",
         lambda h, k, l: (2*h+l) % 4 == 0 and (h+l) % 2 == 0),
        ("2h+l=4n", lambda h, k, l: (2*h+l) % 4 == 0),
        ("h+l=2n", lambda h, k, l: (h+l) % 2 == 0),
        ("l=6n", lambda h, k, l: l % 6 == 0),
        ("l=3n", lambda h, k, l: l % 3 == 0),
        ("l=2n", lambda h, k, l: l % 2 == 0),
    ],
    "h00": [
        ("h=4n", lambda h, k, l: h % 4 == 0),
        ("h=3n", lambda h, k, l: h % 3 == 0),
        ("h=2n", lambda h, k, l: h % 2 == 0),
    ],
    "0k0": [
        ("k=4n", lambda h, k, l: k % 4 == 0),
        ("k=3n", lambda h, k, l: k % 3 == 0),
        ("k=2n", lambda h, k, l: k % 2 == 0),
    ],
    "00l": [
        ("l=6n", lambda h, k, l: l % 6 == 0),
        ("l=4n", lambda h, k, l: l % 4 == 0),
        ("l=3n", lambda h, k, l: l % 3 == 0),
        ("l=2n", lambda h, k, l: l % 2 == 0),
    ],
}

_SUBSET_ORDER = ["hkl", "0kl", "h0l", "hk0", "hhl", "h00", "0k0", "00l"]


def _find_condition(subset_name, rots, trans):
    """Determine the symbolic condition for a reflection subset, or None."""
    indices = _gen_subset(subset_name)
    absent = []
    allowed = []
    for h, k, l in indices:
        if _is_absent(h, k, l, rots, trans):
            absent.append((h, k, l))
        else:
            allowed.append((h, k, l))

    if not absent:
        return None

    candidates = _COND_CANDIDATES.get(subset_name, [])
    for cond_str, cond_fn in candidates:
        ok = True
        # Absent reflections must NOT satisfy the presence condition
        for h, k, l in absent:
            if cond_fn(h, k, l):
                ok = False
                break
        if not ok:
            continue
        # Allowed reflections must satisfy the presence condition
        for h, k, l in allowed:
            if not cond_fn(h, k, l):
                ok = False
                break
        if ok:
            return cond_str

    return None


def _cmd_derive(args):
    sg = int(args[0])
    if sg < 1 or sg > 230:
        print(f"Invalid space group: {sg}", file=sys.stderr)
        sys.exit(1)
    rots, trans = _get_ops(sg)
    conditions = []
    for subset in _SUBSET_ORDER:
        cond = _find_condition(subset, rots, trans)
        if cond is not None:
            conditions.append({
                "reflection_type": subset,
                "condition": cond,
            })
    print(json.dumps({"conditions": conditions}))


# ===================================================================
# Command: check-transformed
# ===================================================================
def _cmd_check_transformed(args):
    sg = int(args[0])
    P = np.array(json.loads(args[1]), dtype=np.float64)
    P_inv = np.linalg.inv(P)
    rots, trans = _get_ops(sg)

    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        hp = float(parts[0])
        kp = float(parts[1])
        lp = float(parts[2])
        hkl_new = np.array([hp, kp, lp])
        # (a',b',c') = (a,b,c)P  =>  h_old = h_new @ P^{-1}
        hkl_old = hkl_new @ P_inv
        hkl_int = np.rint(hkl_old).astype(int)
        if not np.allclose(hkl_old, hkl_int, atol=1e-6):
            print("absent")
            continue
        h, k, l = int(hkl_int[0]), int(hkl_int[1]), int(hkl_int[2])
        if h == 0 and k == 0 and l == 0:
            print("absent")
        else:
            print("absent" if _is_absent(h, k, l, rots, trans) else "allowed")


# ===================================================================
# Main dispatcher
# ===================================================================
def main():
    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  refcond.py check  <SG> <h> <k> <l>\n"
            "  refcond.py batch-check <SG>        (stdin: h k l per line)\n"
            "  refcond.py identify <crystal_system> (stdin: h k l status)\n"
            "  refcond.py derive <SG>\n"
            "  refcond.py check-transformed <SG> '<P_json>' (stdin: h k l)",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "check":
        _cmd_check(rest)
    elif cmd == "batch-check":
        _cmd_batch_check(rest)
    elif cmd == "identify":
        _cmd_identify(rest)
    elif cmd == "derive":
        _cmd_derive(rest)
    elif cmd == "check-transformed":
        _cmd_check_transformed(rest)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
