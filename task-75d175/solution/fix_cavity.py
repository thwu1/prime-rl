#!/usr/bin/env python3
"""
Fix all five errors in the broken OpenFOAM lid-driven cavity case.

Error 1 (blockMeshDict): Vertices 2 and 3 are swapped, creating a bowtie
    pattern in the hex block that produces negative cell volumes.
    Fix: Swap them back to correct ordering.

Error 2 (fvSchemes): div(phi,U) uses 'Gauss linear' which is an unbounded
    central differencing scheme. With the SIMPLE algorithm, this causes
    divergence because it can produce values outside the physical range.
    Fix: Use 'Gauss linearUpwind grad(U)' which is bounded.

Error 3 (fvSolution): Relaxation factors are set to 1.0 for both U and p,
    meaning no under-relaxation / no damping in the SIMPLE algorithm.
    Fix: Set p=0.3, U=0.7 (standard SIMPLE values).

Error 4 (fvSolution): The SIMPLE block is missing pRefCell and pRefValue.
    Since all pressure BCs are zeroGradient (pure Neumann), the pressure
    equation has no unique solution without a reference point.
    Fix: Add pRefCell 0 and pRefValue 0.

Error 5 (transportProperties): Kinematic viscosity nu is set to 1e-06
    (viscosity of water), giving Re = U*L/nu = 1*0.1/1e-6 = 100,000.
    The case should be Re=100 (laminar).
    Fix: Set nu = 0.001 so Re = 1*0.1/0.001 = 100.
"""

import re
import os

CASE_DIR = "/app/cavity"


def fix_blockmeshdict():
    """Fix Error 1: swap vertices 2 and 3 back to correct positions."""
    path = os.path.join(CASE_DIR, "system", "blockMeshDict")
    with open(path) as f:
        content = f.read()

    old_vertices = """vertices
(
    (0 0 0)
    (0.1 0 0)
    (0 0.1 0)
    (0.1 0.1 0)
    (0 0 0.01)
    (0.1 0 0.01)
    (0.1 0.1 0.01)
    (0 0.1 0.01)
);"""

    new_vertices = """vertices
(
    (0 0 0)
    (0.1 0 0)
    (0.1 0.1 0)
    (0 0.1 0)
    (0 0 0.01)
    (0.1 0 0.01)
    (0.1 0.1 0.01)
    (0 0.1 0.01)
);"""

    content = content.replace(old_vertices, new_vertices)

    with open(path, "w") as f:
        f.write(content)

    print("Fixed blockMeshDict: corrected vertex ordering")


def fix_fvschemes():
    """Fix Error 2: change unbounded div scheme to bounded."""
    path = os.path.join(CASE_DIR, "system", "fvSchemes")
    with open(path) as f:
        content = f.read()

    content = content.replace(
        "div(phi,U)      Gauss linear;",
        "div(phi,U)      Gauss linearUpwind grad(U);"
    )

    with open(path, "w") as f:
        f.write(content)

    print("Fixed fvSchemes: changed div(phi,U) to bounded linearUpwind")


def fix_fvsolution():
    """Fix Errors 3 and 4: relaxation factors and pressure reference."""
    path = os.path.join(CASE_DIR, "system", "fvSolution")
    with open(path) as f:
        content = f.read()

    # Fix Error 3: relaxation factors
    content = content.replace(
        "p               1.0;",
        "p               0.3;"
    )
    content = content.replace(
        "U               1.0;",
        "U               0.7;"
    )

    # Fix Error 4: add pRefCell and pRefValue to SIMPLE block
    content = content.replace(
        "nNonOrthogonalCorrectors 0;",
        "nNonOrthogonalCorrectors 0;\n    pRefCell        0;\n    pRefValue       0;"
    )

    with open(path, "w") as f:
        f.write(content)

    print("Fixed fvSolution: relaxation factors and pressure reference")


def fix_transport_properties():
    """Fix Error 5: correct kinematic viscosity for Re=100."""
    path = os.path.join(CASE_DIR, "constant", "transportProperties")
    with open(path) as f:
        content = f.read()

    content = content.replace(
        "nu              [0 2 -1 0 0 0 0] 1e-06;",
        "nu              [0 2 -1 0 0 0 0] 0.001;"
    )

    with open(path, "w") as f:
        f.write(content)

    print("Fixed transportProperties: nu=0.001 for Re=100")


if __name__ == "__main__":
    fix_blockmeshdict()
    fix_fvschemes()
    fix_fvsolution()
    fix_transport_properties()
    print("\nAll five errors fixed successfully.")
