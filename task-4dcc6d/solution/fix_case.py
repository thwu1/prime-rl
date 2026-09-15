#!/usr/bin/env python3
"""
Fix all five configuration bugs in the backward-facing step OpenFOAM case.

Bug 1 (fvSchemes): div(phi,U), div(phi,k), div(phi,epsilon) all use unbounded
       'Gauss linear' — must be replaced with bounded schemes.
Bug 2 (fvSolution): All relaxation factors are 1.0 (no damping) — must be reduced
       to physically appropriate values for the SIMPLE algorithm.
Bug 3 (0/k): Inlet turbulent kinetic energy is zero — causes division by zero
       in the k-epsilon model.
Bug 4 (0/epsilon): Inlet turbulent dissipation rate is zero — causes division by
       zero in the epsilon transport equation.
Bug 5 (0/p): Inlet pressure uses fixedValue (over-constraining the pressure field)
       — must be changed to zeroGradient for a velocity-driven inlet.

"""

import re
import os

CASE_DIR = "/app/backwardStep"


def fix_fv_schemes():
    """Bug 1: Replace unbounded Gauss linear with bounded convection schemes."""
    path = os.path.join(CASE_DIR, "system", "fvSchemes")
    with open(path) as f:
        content = f.read()

    # Momentum: use second-order bounded linearUpwind
    content = content.replace(
        "div(phi,U)      Gauss linear;",
        "div(phi,U)      Gauss linearUpwind grad(U);",
    )
    # Turbulence scalars: use first-order upwind (guaranteed bounded)
    content = content.replace(
        "div(phi,k)      Gauss linear;",
        "div(phi,k)      Gauss upwind;",
    )
    content = content.replace(
        "div(phi,epsilon) Gauss linear;",
        "div(phi,epsilon) Gauss upwind;",
    )

    with open(path, "w") as f:
        f.write(content)
    print("Fixed fvSchemes: bounded convection schemes applied")


def fix_fv_solution():
    """Bug 2: Set physically appropriate relaxation factors."""
    path = os.path.join(CASE_DIR, "system", "fvSolution")
    with open(path) as f:
        content = f.read()

    # With consistent=yes (SIMPLEC), higher factors are possible
    # p=0.9, U=0.9, turbulence=0.7 are standard SIMPLEC values
    # But conservative SIMPLE values also work: p=0.3, U=0.7
    content = re.sub(r"(p\s+)1\.0(;)", r"\g<1>0.3\2", content)
    content = re.sub(r"(U\s+)1\.0(;)", r"\g<1>0.7\2", content)
    content = re.sub(r"(k\s+)1\.0(;)", r"\g<1>0.7\2", content)
    content = re.sub(r"(epsilon\s+)1\.0(;)", r"\g<1>0.7\2", content)

    with open(path, "w") as f:
        f.write(content)
    print("Fixed fvSolution: relaxation factors set to stable values")


def fix_k_inlet():
    """Bug 3: Set physically reasonable turbulent kinetic energy at inlet.

    k = 3/2 * (U * I)^2 where U=1 m/s, I=0.05 (5% turbulence intensity)
    k = 1.5 * (1 * 0.05)^2 = 0.00375 m^2/s^2
    """
    path = os.path.join(CASE_DIR, "0", "k")
    with open(path) as f:
        content = f.read()

    content = re.sub(
        r"(inlet\s*\{[^}]*?value\s+uniform\s+)0(\s*;)",
        r"\g<1>0.00375\2",
        content,
        flags=re.DOTALL,
    )

    with open(path, "w") as f:
        f.write(content)
    print("Fixed 0/k: inlet k set to 0.00375 m^2/s^2")


def fix_epsilon_inlet():
    """Bug 4: Set physically reasonable turbulent dissipation at inlet.

    epsilon = C_mu^0.75 * k^1.5 / l
    where C_mu=0.09, k=0.00375, l=0.07*D_h=0.07*0.1=0.007
    epsilon = 0.1643 * 0.000230 / 0.007 ≈ 0.0054 m^2/s^3
    """
    path = os.path.join(CASE_DIR, "0", "epsilon")
    with open(path) as f:
        content = f.read()

    content = re.sub(
        r"(inlet\s*\{[^}]*?value\s+uniform\s+)0(\s*;)",
        r"\g<1>0.0054\2",
        content,
        flags=re.DOTALL,
    )

    with open(path, "w") as f:
        f.write(content)
    print("Fixed 0/epsilon: inlet epsilon set to 0.0054 m^2/s^3")


def fix_p_inlet():
    """Bug 5: Change inlet pressure from fixedValue to zeroGradient.

    For a velocity-driven inlet, pressure must float freely (zeroGradient).
    Using fixedValue at both inlet and outlet over-constrains the pressure
    field and prevents the SIMPLE algorithm from converging.
    """
    path = os.path.join(CASE_DIR, "0", "p")
    with open(path) as f:
        content = f.read()

    # Change type from fixedValue to zeroGradient in the inlet block only
    content = re.sub(
        r"(inlet\s*\{[^}]*?type\s+)fixedValue",
        r"\1zeroGradient",
        content,
        flags=re.DOTALL,
    )

    with open(path, "w") as f:
        f.write(content)
    print("Fixed 0/p: inlet pressure changed to zeroGradient")


if __name__ == "__main__":
    fix_fv_schemes()
    fix_fv_solution()
    fix_k_inlet()
    fix_epsilon_inlet()
    fix_p_inlet()
    print("\nAll 5 bugs fixed. Case ready for solver run.")
