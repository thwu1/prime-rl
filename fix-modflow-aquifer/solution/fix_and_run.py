#!/usr/bin/env python3
"""
Fix broken TWRI MODFLOW 6 model, evaluate baseline physics and water budget,
design a constrained supplemental well field, and run the augmented simulation.


Diagnosed defects:
1. IMS solver: OUTER_MAXIMUM=2 and DVCLOSE=1e-15 are pathologically restrictive
   — model cannot converge with 2 outer iterations and sub-femtometer closure.
2. NPF K33: Confining layers 2 and 4 have K33=1.0 ft/s instead of the TWRI
   reference values (~1e-8 and ~5e-7 ft/s). K33=1.0 is 8+ orders of magnitude
   too high for a confining unit, effectively removing vertical resistance and
   destroying the multi-aquifer flow structure.
3. CHD boundaries: Constant heads applied to confining layer 2 instead of
   aquifer layer 3. The TWRI benchmark specifies CHD (h=0) along the western
   edge of aquifers 1 and 3, not confining units.
"""

import os
import re
import csv
import json
import subprocess

MODEL_DIR = "/app/model"
RESULTS_DIR = "/app/results"


# ==================================================================
# Phase 1: Diagnose and repair model defects
# ==================================================================

def fix_ims():
    """Repair IMS solver — relax convergence criteria to physically
    reasonable values consistent with the TWRI benchmark."""
    path = os.path.join(MODEL_DIR, "ex-gwf-twri01.ims")
    with open(path, 'w') as f:
        f.write("BEGIN OPTIONS\n")
        f.write("END OPTIONS\n\n")
        f.write("BEGIN NONLINEAR\n")
        f.write("  OUTER_DVCLOSE  1.0e-09\n")
        f.write("  OUTER_MAXIMUM  50\n")
        f.write("END NONLINEAR\n\n")
        f.write("BEGIN LINEAR\n")
        f.write("  INNER_MAXIMUM  100\n")
        f.write("  INNER_DVCLOSE  1.0e-09\n")
        f.write("  INNER_RCLOSE  1.0e-06 strict\n")
        f.write("END LINEAR\n")


def fix_npf():
    """Repair NPF — set K33 for confining layers to TWRI reference values.
    Layer 2 (upper confining): K33 = K = 1.0e-8 ft/s
    Layer 4 (lower confining): K33 = K = 5.0e-7 ft/s
    Aquifer layers: K33 = K (isotropic)."""
    path = os.path.join(MODEL_DIR, "ex-gwf-twri01.npf")
    with open(path, 'w') as f:
        f.write("BEGIN OPTIONS\n")
        f.write("  SAVE_SPECIFIC_DISCHARGE\n")
        f.write("END OPTIONS\n\n")
        f.write("BEGIN GRIDDATA\n")
        f.write("  ICELLTYPE  LAYERED\n")
        f.write("    CONSTANT  1\n")
        f.write("    CONSTANT  0\n")
        f.write("    CONSTANT  0\n")
        f.write("    CONSTANT  0\n")
        f.write("    CONSTANT  0\n")
        f.write("  K  LAYERED\n")
        f.write("    CONSTANT  1.0e-03\n")
        f.write("    CONSTANT  1.0e-08\n")
        f.write("    CONSTANT  1.0e-04\n")
        f.write("    CONSTANT  5.0e-07\n")
        f.write("    CONSTANT  2.0e-04\n")
        f.write("  K33  LAYERED\n")
        f.write("    CONSTANT  1.0e-03\n")
        f.write("    CONSTANT  1.0e-08\n")
        f.write("    CONSTANT  1.0e-04\n")
        f.write("    CONSTANT  5.0e-07\n")
        f.write("    CONSTANT  2.0e-04\n")
        f.write("END GRIDDATA\n")


def fix_chd():
    """Repair CHD — move constant head boundaries from confining layer 2
    to aquifer layer 3, keeping layer 1 entries intact."""
    path = os.path.join(MODEL_DIR, "ex-gwf-twri01.chd")
    lines = ["BEGIN OPTIONS", "END OPTIONS", "",
             "BEGIN DIMENSIONS", "  MAXBOUND  30", "END DIMENSIONS", "",
             "BEGIN PERIOD 1"]
    for r in range(1, 16):
        lines.append(f"  1  {r}  1  0.00000000")
    for r in range(1, 16):
        lines.append(f"  3  {r}  1  0.00000000")
    lines.append("END PERIOD 1")
    lines.append("")
    with open(path, 'w') as f:
        f.write('\n'.join(lines))


def run_simulation():
    """Execute MODFLOW 6 and verify normal termination."""
    result = subprocess.run(["mf6"], cwd=MODEL_DIR,
                            capture_output=True, text=True)
    print(result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout)
    if result.returncode != 0:
        print("STDERR:", result.stderr)
        raise RuntimeError("MODFLOW 6 simulation failed")
    lst_path = os.path.join(MODEL_DIR, "mfsim.lst")
    with open(lst_path) as f:
        content = f.read()
    if "Normal termination" not in content:
        raise RuntimeError("Simulation did not achieve normal termination")
    print("Simulation completed with normal termination.")


# ==================================================================
# Phase 2: Evaluate corrected baseline model
# ==================================================================

def evaluate_budget():
    """Extract and evaluate the volumetric water budget from the
    listing file or cell-by-cell budget file."""
    import numpy as np
    import flopy

    # Primary method: read budget from cell-by-cell file
    cbc_path = os.path.join(MODEL_DIR, "ex-gwf-twri01.cbc")
    cbc = flopy.utils.CellBudgetFile(cbc_path)

    total_in = 0.0
    total_out = 0.0

    for record_name in cbc.get_unique_record_names():
        name = record_name.strip()
        try:
            data_list = cbc.get_data(text=name)
        except Exception:
            continue
        for data in data_list:
            if isinstance(data, np.recarray):
                if 'q' in data.dtype.names:
                    q = data['q']
                else:
                    continue
            elif isinstance(data, np.ndarray):
                q = data.flatten()
            else:
                continue
            total_in += float(q[q > 0].sum())
            total_out += float(np.abs(q[q < 0]).sum())

    if (total_in + total_out) > 0:
        pct_disc = 100.0 * (total_in - total_out) / (
            (total_in + total_out) / 2.0)
    else:
        pct_disc = 0.0

    budget = {
        "total_inflow_ft3ps": round(total_in, 6),
        "total_outflow_ft3ps": round(total_out, 6),
        "percent_discrepancy": round(pct_disc, 6),
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "budget_analysis.json"), 'w') as f:
        json.dump(budget, f, indent=2)

    print(f"Budget: IN={total_in:.4f} ft³/s, OUT={total_out:.4f} ft³/s, "
          f"discrepancy={pct_disc:.6f}%")


def evaluate_physics():
    """Assess physical behavior of the corrected baseline model."""
    import numpy as np
    import flopy

    hds_path = os.path.join(MODEL_DIR, "ex-gwf-twri01.hds")
    hds = flopy.utils.HeadFile(hds_path)
    head = hds.get_data()

    max_l1 = float(np.max(head[0]))
    max_l5 = float(np.max(head[4]))
    center_l1 = float(head[0, 7, 7])  # row 8, col 8 (0-indexed)
    center_l5 = float(head[4, 7, 7])

    # Check drain activity via budget file
    drains_active = False
    try:
        cbc_path = os.path.join(MODEL_DIR, "ex-gwf-twri01.cbc")
        cbc = flopy.utils.CellBudgetFile(cbc_path)
        for record_name in cbc.get_unique_record_names():
            if "DRN" in record_name.strip().upper():
                drn_data = cbc.get_data(text=record_name.strip())
                for rec in drn_data:
                    if isinstance(rec, np.recarray) and 'q' in rec.dtype.names:
                        if np.any(rec['q'] < 0):
                            drains_active = True
                    elif isinstance(rec, np.ndarray):
                        if np.any(rec < 0):
                            drains_active = True
                    if drains_active:
                        break
            if drains_active:
                break
    except Exception as e:
        print(f"Warning reading DRN budget: {e}")
        # Fallback: check if heads exceed drain elevations
        drain_elevs = {2: 0, 3: 0, 4: 10, 5: 20, 6: 30, 7: 50, 8: 70,
                       9: 90, 10: 100}
        for col_1idx, elev in drain_elevs.items():
            if head[0, 7, col_1idx - 1] > elev:
                drains_active = True
                break

    assessment = {
        "max_head_layer1": round(max_l1, 4),
        "max_head_layer5": round(max_l5, 4),
        "head_at_center_l1": round(center_l1, 4),
        "head_at_center_l5": round(center_l5, 4),
        "vertical_gradient_positive": bool(center_l1 > center_l5),
        "drains_removing_water": drains_active,
    }

    with open(os.path.join(RESULTS_DIR, "model_assessment.json"), 'w') as f:
        json.dump(assessment, f, indent=2)

    print(f"Assessment: max_L1={max_l1:.2f}, max_L5={max_l5:.2f}")
    print(f"  center_L1={center_l1:.2f}, center_L5={center_l5:.2f}")
    print(f"  vertical_gradient_positive={center_l1 > center_l5}")
    print(f"  drains_active={drains_active}")


# ==================================================================
# Phase 3: Design and run augmented well field
# ==================================================================

def design_wells():
    """Design new extraction wells satisfying all constraints:
    - Total extraction >= 20 ft³/s
    - 3-8 wells
    - No individual rate > 7 ft³/s
    - Aquifer layers only (1, 3, 5)
    - At least 2 distinct layers

    Strategy: Distribute 4 wells across 3 aquifer layers at moderate rates
    (5 ft³/s each). Place wells in the interior domain away from the CHD
    boundary (column 1) for pumping efficiency and away from existing
    wells to minimize interference drawdown."""

    new_wells = [
        (1, 3, 12, -5.0),   # Layer 1, northeast quadrant
        (3, 7, 14, -5.0),   # Layer 3, east-center
        (5, 12, 4, -5.0),   # Layer 5, southwest quadrant
        (5, 14, 10, -5.0),  # Layer 5, south-center
    ]
    # Verification: 4 wells, total 20 ft³/s, max 5.0 < 7.0, layers {1,3,5}

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "well_design.csv"), 'w',
              newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["layer", "row", "col", "rate"])
        for w in new_wells:
            writer.writerow(w)

    print(f"Designed {len(new_wells)} new wells, "
          f"total extraction = {sum(abs(w[3]) for w in new_wells):.1f} ft³/s")
    return new_wells


def update_model_wells(new_wells):
    """Add new wells to the WEL package file, updating MAXBOUND."""
    original_wells = [
        (5, 5, 11, -5.0), (3, 4, 6, -5.0), (3, 6, 12, -5.0),
        (1, 9, 8, -5.0), (1, 9, 10, -5.0), (1, 9, 12, -5.0),
        (1, 9, 14, -5.0), (1, 11, 8, -5.0), (1, 11, 10, -5.0),
        (1, 11, 12, -5.0), (1, 11, 14, -5.0), (1, 13, 8, -5.0),
        (1, 13, 10, -5.0), (1, 13, 12, -5.0), (1, 13, 14, -5.0),
    ]
    all_wells = original_wells + list(new_wells)

    path = os.path.join(MODEL_DIR, "ex-gwf-twri01.wel")
    with open(path, 'w') as f:
        f.write("BEGIN OPTIONS\n")
        f.write("END OPTIONS\n\n")
        f.write("BEGIN DIMENSIONS\n")
        f.write(f"  MAXBOUND  {len(all_wells)}\n")
        f.write("END DIMENSIONS\n\n")
        f.write("BEGIN PERIOD 1\n")
        for w in all_wells:
            f.write(f"  {w[0]}  {w[1]}  {w[2]}  {w[3]:.8f}\n")
        f.write("END PERIOD 1\n")

    print(f"Updated WEL: {len(original_wells)} original + "
          f"{len(new_wells)} new = {len(all_wells)} total wells")


def clean_outputs():
    """Remove prior simulation output files before re-running."""
    for fname in ["mfsim.lst", "ex-gwf-twri01.hds", "ex-gwf-twri01.cbc",
                   "ex-gwf-twri01.lst"]:
        path = os.path.join(MODEL_DIR, fname)
        if os.path.exists(path):
            os.remove(path)


def extract_heads():
    """Read binary head file from augmented simulation and write CSV.
    Also verify no heads are below layer bottom elevations."""
    import numpy as np
    import flopy

    hds_path = os.path.join(MODEL_DIR, "ex-gwf-twri01.hds")
    hds = flopy.utils.HeadFile(hds_path)
    head = hds.get_data()
    nlay, nrow, ncol = head.shape

    with open(os.path.join(RESULTS_DIR, "heads.csv"), 'w',
              newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["layer", "row", "col", "head"])
        for k in range(nlay):
            for i in range(nrow):
                for j in range(ncol):
                    writer.writerow([k + 1, i + 1, j + 1,
                                     f"{head[k, i, j]:.6f}"])

    print(f"Wrote {nlay * nrow * ncol} head values to heads.csv")

    # Verify constraint: no head below layer bottom
    bottoms = [-150.0, -200.0, -300.0, -350.0, -450.0]
    all_ok = True
    for k in range(nlay):
        min_h = float(np.min(head[k]))
        if min_h < bottoms[k]:
            print(f"VIOLATION: Layer {k+1} min head {min_h:.2f} < "
                  f"bottom {bottoms[k]}")
            all_ok = False
        else:
            print(f"Layer {k+1}: min head {min_h:.2f} >= "
                  f"bottom {bottoms[k]} OK")
    if all_ok:
        print("All layers pass dry-cell check.")


# ==================================================================
# Main execution
# ==================================================================

if __name__ == "__main__":
    os.makedirs(RESULTS_DIR, exist_ok=True)

    print("=" * 60)
    print("Phase 1: Diagnosing and repairing model defects")
    print("=" * 60)
    fix_ims()
    fix_npf()
    fix_chd()

    print("\n" + "=" * 60)
    print("Phase 2: Running and evaluating corrected baseline")
    print("=" * 60)
    run_simulation()
    evaluate_budget()
    evaluate_physics()

    print("\n" + "=" * 60)
    print("Phase 3: Designing and running augmented well field")
    print("=" * 60)
    new_wells = design_wells()
    update_model_wells(new_wells)
    clean_outputs()
    run_simulation()
    extract_heads()

    print("\n" + "=" * 60)
    print("All phases complete.")
    print("=" * 60)
