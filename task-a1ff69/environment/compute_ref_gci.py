#!/usr/bin/env python3
"""
Compute reference GCI metrics from LULESH reference outputs.
Runs during Docker build to generate ground truth for testing.
Uses the same Celik et al. (2008) iterative apparent-order procedure
that the agent is expected to implement.
"""
import re
import json
import math
import sys


def parse_energy(filepath):
    with open(filepath) as f:
        text = f.read()
    m = re.search(
        r"Final Origin Energy\s*=\s*([+-]?\d+\.?\d*[eE][+-]?\d+)", text
    )
    if m:
        return float(m.group(1))
    return None


def compute_apparent_order(f1, f2, f3, r21, r32):
    """
    Celik et al. (2008) iterative apparent-order procedure.
    Grid 1 = finest, grid 3 = coarsest.
    r21 = h2/h1, r32 = h3/h2 (both > 1).
    Returns (p, f_ext, ea21) or (None, None, None) on failure.
    """
    eps32 = f3 - f2
    eps21 = f2 - f1
    if abs(eps21) < 1e-30 or abs(eps32) < 1e-30:
        return None, None, None
    s = 1.0 if (eps32 / eps21) > 0 else -1.0
    try:
        p = abs(math.log(abs(eps32 / eps21))) / math.log(r21)
    except (ValueError, ZeroDivisionError):
        return None, None, None
    p = max(0.01, min(p, 20.0))
    for _ in range(200):
        p_old = p
        try:
            numer = r21**p - s
            denom = r32**p - s
            if abs(denom) < 1e-30 or numer / denom <= 0:
                break
            q = math.log(numer / denom)
            p = abs(math.log(abs(eps32 / eps21)) + q) / math.log(r21)
            p = max(0.01, min(p, 20.0))
        except (ValueError, ZeroDivisionError, OverflowError):
            break
        if abs(p - p_old) < 1e-12:
            break
    try:
        f_ext = (r21**p * f1 - f2) / (r21**p - 1.0)
    except (ZeroDivisionError, OverflowError):
        f_ext = f1
    if abs(f1) > 1e-30:
        ea21 = abs((f1 - f2) / f1)
    else:
        ea21 = abs(f1 - f2)
    return p, f_ext, ea21


def compute_gci(ea, r, p, Fs=1.25):
    try:
        return Fs * ea / (r**p - 1.0)
    except (ZeroDivisionError, OverflowError):
        return float('inf')


def main():
    mesh_sizes = [8, 12, 16, 20]
    energies = {}
    for s in mesh_sizes:
        path = f"/reference/convergence/output_s{s}_i50.txt"
        e = parse_energy(path)
        if e is None:
            print(f"ERROR: Could not parse energy from {path}", file=sys.stderr)
            sys.exit(1)
        energies[s] = e

    sorted_sizes = sorted(mesh_sizes, reverse=True)

    # Triplet A: sizes 20, 16, 12
    sA = sorted_sizes[0:3]
    fA = [energies[s] for s in sA]
    hA = [1.0 / s for s in sA]
    rA_21 = hA[1] / hA[0]
    rA_32 = hA[2] / hA[1]
    pA, f_ext_A, ea_A = compute_apparent_order(fA[0], fA[1], fA[2], rA_21, rA_32)

    # Triplet B: sizes 16, 12, 8
    sB = sorted_sizes[1:4]
    fB = [energies[s] for s in sB]
    hB = [1.0 / s for s in sB]
    rB_21 = hB[1] / hB[0]
    rB_32 = hB[2] / hB[1]
    pB, f_ext_B, ea_B = compute_apparent_order(fB[0], fB[1], fB[2], rB_21, rB_32)

    if pA is not None and pB is not None:
        conv_order = (pA + pB) / 2.0
    elif pA is not None:
        conv_order = pA
    elif pB is not None:
        conv_order = pB
    else:
        conv_order = 0.0

    if pA is not None and ea_A is not None:
        gci_fine = compute_gci(ea_A, rA_21, pA)
    else:
        gci_fine = float('inf')

    if pB is not None and ea_B is not None:
        gci_coarse = compute_gci(ea_B, rB_21, pB)
    else:
        gci_coarse = float('inf')

    richardson = f_ext_A if f_ext_A is not None else energies[sorted_sizes[0]]

    if (f_ext_A is not None and f_ext_B is not None
            and abs(f_ext_B) > 1e-30):
        asym_ratio = f_ext_A / f_ext_B
    else:
        asym_ratio = float('inf')

    order_ok = conv_order >= 0.8
    asym_ok = 0.9 <= asym_ratio <= 1.1
    assessment = "verified" if (order_ok and asym_ok) else "not_verified"

    report = {
        "mesh_sizes": mesh_sizes,
        "energies": {str(s): energies[s] for s in mesh_sizes},
        "convergence_order": round(conv_order, 6),
        "gci_fine": gci_fine,
        "gci_coarse": gci_coarse,
        "asymptotic_ratio": round(asym_ratio, 6),
        "richardson_estimate": richardson,
        "assessment": assessment
    }

    with open("/reference/gci_reference.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Reference GCI report generated:")
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
