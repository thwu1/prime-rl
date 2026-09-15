#!/usr/bin/env python3
"""
Grid Convergence Index (GCI) verification framework for LULESH.
Implements the Celik et al. (2008) iterative apparent-order procedure
for non-uniform refinement ratios, computes GCI uncertainty bands,
evaluates asymptotic convergence regime, and writes a JSON report.
"""
import subprocess
import json
import re
import math
import sys


def run_lulesh(size, iters):
    """Run LULESH and return parsed output metrics."""
    result = subprocess.run(
        ['./lulesh2.0', '-s', str(size), '-i', str(iters)],
        capture_output=True, text=True, cwd='/app'
    )
    output = result.stdout + result.stderr
    metrics = {}
    for key, pattern in [
        ('final_energy', r'Final Origin Energy\s*=\s*([+-]?\d+\.?\d*[eE][+-]?\d+)'),
        ('max_abs_diff', r'MaxAbsDiff\s*=\s*([+-]?\d+\.?\d*[eE][+-]?\d+)'),
        ('total_abs_diff', r'TotalAbsDiff\s*=\s*([+-]?\d+\.?\d*[eE][+-]?\d+)'),
        ('max_rel_diff', r'MaxRelDiff\s*=\s*([+-]?\d+\.?\d*[eE][+-]?\d+)'),
    ]:
        m = re.search(pattern, output)
        if m:
            metrics[key] = float(m.group(1))
    return metrics


def compute_apparent_order(f1, f2, f3, r21, r32):
    """
    Compute apparent order of convergence using the Celik et al. (2008)
    iterative procedure for non-uniform refinement ratios.

    Convention: grid 1 = finest, grid 3 = coarsest.
    f1, f2, f3: solution values on grids 1, 2, 3
    r21 = h2/h1 > 1 (medium-to-fine spacing ratio)
    r32 = h3/h2 > 1 (coarse-to-medium spacing ratio)

    Returns: (p, f_ext, ea21)
        p = apparent order of convergence
        f_ext = Richardson-extrapolated value
        ea21 = approximate relative error on finest pair
    """
    eps32 = f3 - f2
    eps21 = f2 - f1

    if abs(eps21) < 1e-30 or abs(eps32) < 1e-30:
        return None, None, None

    s = 1.0 if (eps32 / eps21) > 0 else -1.0

    # Initial guess assuming uniform refinement
    try:
        p = abs(math.log(abs(eps32 / eps21))) / math.log(r21)
    except (ValueError, ZeroDivisionError):
        return None, None, None

    # Clamp initial guess to avoid numerical issues
    p = max(0.01, min(p, 20.0))

    # Iterative refinement of apparent order
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

    # Richardson extrapolation from finest pair
    try:
        f_ext = (r21**p * f1 - f2) / (r21**p - 1.0)
    except (ZeroDivisionError, OverflowError):
        f_ext = f1

    # Approximate relative error on finest pair
    if abs(f1) > 1e-30:
        ea21 = abs((f1 - f2) / f1)
    else:
        ea21 = abs(f1 - f2)

    return p, f_ext, ea21


def compute_gci(ea, r, p, Fs=1.25):
    """Compute Grid Convergence Index for a grid pair."""
    try:
        return Fs * ea / (r**p - 1.0)
    except (ZeroDivisionError, OverflowError):
        return float('inf')


def main():
    mesh_sizes = [8, 12, 16, 20]
    energies = {}

    print("Running LULESH simulations for GCI analysis...")
    for s in mesh_sizes:
        metrics = run_lulesh(s, 50)
        if 'final_energy' not in metrics:
            print(f"ERROR: Failed to get energy for size {s}", file=sys.stderr)
            sys.exit(1)
        energies[s] = metrics['final_energy']
        print(f"  size={s}: energy={metrics['final_energy']:.15e}")

    # Grid spacings: h = 1/s (larger s = finer mesh = smaller h)
    # Sort finest first
    sorted_sizes = sorted(mesh_sizes, reverse=True)  # [20, 16, 12, 8]

    # --- Triplet A: grids at sizes 20, 16, 12 ---
    sA = sorted_sizes[0:3]  # [20, 16, 12]
    fA = [energies[s] for s in sA]
    hA = [1.0 / s for s in sA]
    rA_21 = hA[1] / hA[0]  # h_medium / h_fine = (1/16)/(1/20) = 20/16 = 1.25
    rA_32 = hA[2] / hA[1]  # h_coarse / h_medium = (1/12)/(1/16) = 16/12

    pA, f_ext_A, ea_A = compute_apparent_order(fA[0], fA[1], fA[2], rA_21, rA_32)
    print(f"\nTriplet A (sizes {sA}): p={pA}, f_ext={f_ext_A}")

    # --- Triplet B: grids at sizes 16, 12, 8 ---
    sB = sorted_sizes[1:4]  # [16, 12, 8]
    fB = [energies[s] for s in sB]
    hB = [1.0 / s for s in sB]
    rB_21 = hB[1] / hB[0]  # (1/12)/(1/16) = 16/12
    rB_32 = hB[2] / hB[1]  # (1/8)/(1/12) = 12/8 = 1.5

    pB, f_ext_B, ea_B = compute_apparent_order(fB[0], fB[1], fB[2], rB_21, rB_32)
    print(f"Triplet B (sizes {sB}): p={pB}, f_ext={f_ext_B}")

    # --- Average convergence order ---
    if pA is not None and pB is not None:
        conv_order = (pA + pB) / 2.0
    elif pA is not None:
        conv_order = pA
    elif pB is not None:
        conv_order = pB
    else:
        conv_order = 0.0

    # --- GCI for finest pair (from triplet A: sizes 20 & 16) ---
    if pA is not None and ea_A is not None:
        gci_fine = compute_gci(ea_A, rA_21, pA)
    else:
        gci_fine = float('inf')

    # --- GCI for coarser pair (from triplet B: sizes 16 & 12) ---
    if pB is not None and ea_B is not None:
        gci_coarse = compute_gci(ea_B, rB_21, pB)
    else:
        gci_coarse = float('inf')

    # --- Richardson extrapolation (from finest triplet) ---
    richardson = f_ext_A if f_ext_A is not None else energies[sorted_sizes[0]]

    # --- Asymptotic ratio: consistency of extrapolated values from two triplets ---
    if (f_ext_A is not None and f_ext_B is not None
            and abs(f_ext_B) > 1e-30):
        asym_ratio = f_ext_A / f_ext_B
    else:
        asym_ratio = float('inf')

    # --- Assessment ---
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

    report_path = '/app/gci_report.json'
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n=== GCI Verification Report ===")
    print(f"  Convergence order (avg): {conv_order:.4f}")
    print(f"    Triplet A order:       {pA:.4f}" if pA else "    Triplet A order: N/A")
    print(f"    Triplet B order:       {pB:.4f}" if pB else "    Triplet B order: N/A")
    print(f"  GCI (fine, 20→16):       {gci_fine:.6e}")
    print(f"  GCI (coarse, 16→12):     {gci_coarse:.6e}")
    print(f"  Asymptotic ratio:        {asym_ratio:.6f}")
    print(f"  Richardson estimate:     {richardson:.15e}")
    print(f"  Assessment:              {assessment}")
    print(f"  Report written to:       {report_path}")


if __name__ == '__main__':
    main()
