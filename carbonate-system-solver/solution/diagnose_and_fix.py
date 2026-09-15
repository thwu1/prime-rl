#!/usr/bin/env python3
"""Diagnose and fix bugs in the carbonate solver.

Uses PyCO2SYS as a reference oracle and the Octave validation script
to systematically identify coefficient errors in the equilibrium
constant parameterizations.

"""

import subprocess
import re
import sys
import os
import numpy as np

sys.path.insert(0, "/app")


def get_octave_constants(T, S, P=0):
    """Run the Octave validation script and parse output."""
    if P > 0:
        eval_str = f"T={T}; S={S}; P={P}; run('/app/validate_constants.m')"
    else:
        eval_str = f"T={T}; S={S}; run('/app/validate_constants.m')"

    result = subprocess.run(
        ["octave", "--no-gui", "--eval", eval_str],
        capture_output=True, text=True, timeout=30
    )
    constants = {}
    for line in result.stdout.split("\n"):
        m = re.match(r"(\w+)\s*=\s*([-+]?[\d.]+[eE][-+]?\d+)", line.strip())
        if m:
            constants[m.group(1)] = float(m.group(2))
    return constants


def compare_constants():
    """Compare solver constants against Octave reference."""
    from carbonate_solver import (
        K1K2_LDK00, KB_D90, KW_M95, KSO4_D90, KF_DR79
    )

    discrepancies = []
    test_conditions = [(25, 35), (2, 34.7), (15, 34.5)]

    for T, S in test_conditions:
        TK = T + 273.15
        ref = get_octave_constants(T, S)

        K1, K2 = K1K2_LDK00(TK, S)
        KB = KB_D90(TK, S)
        KW = KW_M95(TK, S)
        KSO4 = KSO4_D90(TK, S)
        KF = KF_DR79(TK, S)

        checks = [
            ("K1", K1, ref.get("K1")),
            ("K2", K2, ref.get("K2")),
            ("KB", KB, ref.get("KB")),
            ("KW", KW, ref.get("KW")),
            ("KSO4", KSO4, ref.get("KSO4")),
            ("KF", KF, ref.get("KF")),
        ]

        for name, solver_val, ref_val in checks:
            if ref_val is not None and abs(ref_val) > 1e-30:
                rel_diff = abs(solver_val - ref_val) / abs(ref_val)
                if rel_diff > 1e-6:
                    discrepancies.append(
                        f"  {name} at T={T},S={S}: solver={solver_val:.10e}, "
                        f"ref={ref_val:.10e}, rel_diff={rel_diff:.2e}"
                    )

    return discrepancies


def check_pressure_corrections():
    """Check pressure correction coefficients via Octave output."""
    ref = get_octave_constants(2, 34.7, P=3000)
    # The Octave output includes K1_p, KW_p etc.
    # We can compare pressure-corrected constants but the pH scale
    # conversion makes direct comparison complex. Instead, we parse
    # the printed coefficients from the Octave output.

    result = subprocess.run(
        ["octave", "--no-gui", "--eval",
         "T=2; S=34.7; P=3000; run('/app/validate_constants.m')"],
        capture_output=True, text=True, timeout=30
    )

    # Look for KW dK coefficient
    for line in result.stdout.split("\n"):
        if "KW:" in line and "dK" in line:
            # Should contain 0.0794
            print(f"  Octave KW pressure correction: {line.strip()}")


def fix_solver():
    """Apply fixes to the solver based on diagnosed bugs."""
    solver_path = "/app/carbonate_solver.py"
    with open(solver_path, "r") as f:
        code = f.read()

    fixes_applied = []

    # Bug 1: K1K2_LDK00 has 3663.86 instead of correct 3633.86
    if "3663.86" in code:
        code = code.replace("3663.86", "3633.86")
        fixes_applied.append("K1: 3663.86 -> 3633.86 (Lueker et al. 2000)")

    # Bug 2: KF_DR79 has 1.225 instead of correct 1.525
    if "1.225 * sqrtI" in code:
        code = code.replace("1.225 * sqrtI", "1.525 * sqrtI")
        fixes_applied.append("KF: 1.225 -> 1.525 (Dickson & Riley 1979)")

    # Bug 3: PC_KW has 0.0714 instead of correct 0.0794
    # Must use specific context to avoid also changing PC_KP3 which correctly has 0.0714
    old_kw = "((-25.60, 0.2324, -0.0036246), (-5.13, 0.0714))"
    new_kw = "((-25.60, 0.2324, -0.0036246), (-5.13, 0.0794))"
    if old_kw in code:
        code = code.replace(old_kw, new_kw)
        fixes_applied.append("PC_KW deltaK: 0.0714 -> 0.0794 (Millero 1995)")

    with open(solver_path, "w") as f:
        f.write(code)

    return fixes_applied


def verify_fix():
    """Verify the fix by comparing against PyCO2SYS."""
    import PyCO2SYS as pyco2

    # Reload the fixed solver
    if "carbonate_solver" in sys.modules:
        del sys.modules["carbonate_solver"]
    sys.path.insert(0, "/app")
    import carbonate_solver

    test_cases = [
        (2350.0, 1950.0, 1, 2, 28.0, 36.0, 0.0, 0.0, 0.0),
        (2300.0, 2050.0, 1, 2, 15.0, 34.5, 0.0, 5.0, 0.5),
        (2400.0, 2250.0, 1, 2, 2.0, 34.7, 4000.0, 50.0, 2.0),
    ]

    pyco2_type_map = {1: 1, 2: 2, 3: 3, 4: 5, 5: 6, 6: 7}

    all_pass = True
    for par1, par2, pt1, pt2, T, S, P, Si, PO4 in test_cases:
        result = carbonate_solver.solve(par1, par2, pt1, pt2, T, S, P, Si, PO4)

        ref = pyco2.sys(
            par1=par1, par2=par2,
            par1_type=pyco2_type_map[pt1],
            par2_type=pyco2_type_map[pt2],
            salinity=S, temperature=T, pressure=P,
            total_silicate=Si, total_phosphate=PO4,
            opt_k_carbonic=10, opt_k_bisulfate=1,
            opt_k_fluoride=1, opt_pH_scale=1,
            opt_total_borate=1,
        )

        ref_pH = float(ref["pH_total"].flat[0]) if hasattr(ref["pH_total"], "flat") else float(ref["pH_total"])
        if abs(result["pH"] - ref_pH) > 5e-4:
            print(f"  FAIL: pH diff = {abs(result['pH'] - ref_pH):.6f} at T={T},P={P}")
            all_pass = False
        else:
            print(f"  OK: T={T},S={S},P={P} pH diff = {abs(result['pH'] - ref_pH):.2e}")

    return all_pass


if __name__ == "__main__":
    print("=== Diagnosing carbonate solver bugs ===")

    print("\n--- Comparing 1-atm constants against Octave reference ---")
    discrep = compare_constants()
    for d in discrep:
        print(d)

    print("\n--- Checking pressure correction coefficients ---")
    check_pressure_corrections()

    print("\n--- Applying fixes ---")
    fixes = fix_solver()
    for f in fixes:
        print(f"  Fixed: {f}")

    print("\n--- Verifying fixes against PyCO2SYS ---")
    ok = verify_fix()
    if ok:
        print("\nAll verification checks passed.")
    else:
        print("\nWARNING: Some checks failed!")
        sys.exit(1)
