#!/usr/bin/env python3
"""
Fix bugs in the 3D frame eigenvalue buckling analysis pipeline.

Bug 1 (local_geometric_stiffness_3D):
    Eight transverse-rotation coupling terms in the geometric stiffness
    matrix use the coefficient Fx2/6 instead of the correct Fx2/10. The
    correct coefficient 1/10 comes from the integral of the product of
    Hermite cubic shape function derivatives for the consistent geometric
    stiffness formulation: integral_0^L N_i'(x) * N_j(x) dx = L/10 for
    the specific pairs (transverse displacement at one node, rotation at
    same or other node). The value 1/6 corresponds to a different integral
    (moment-torsion coupling terms involving My, Mz) and was likely a
    copy-paste error.

    Affected positions (upper triangle, before symmetrization):
        [1,5], [1,11], [2,4], [2,10], [4,8], [5,7], [7,11], [8,10]

    Fix: replace 'Fx2 / 6.0' with 'Fx2 / 10.0' globally in the function.
    This is safe because no correct term in the function uses 'Fx2 / 6.0' --
    the moment-dependent terms that correctly use /6.0 all have expressions
    like '(Mz1 + Mz2) / 6.0', not 'Fx2 / 6.0'.

Bug 2 (compute_element_forces):
    The transformation from global to local coordinates uses Gamma.T instead
    of Gamma. The transformation matrix Gamma is constructed as:
        gamma = [ex; ey; ez]  (rows = local axes in global coords)
    so u_local = gamma * u_global (matrix-vector product maps global to local).
    Using Gamma.T = kron(I4, gamma.T) instead maps local to global, which
    produces incorrect element internal forces. This bug is masked when gamma
    happens to be symmetric (e.g., beams along z with local_z=[1,0,0]) but
    manifests for general beam orientations.

    Fix: change 'Gamma.T @ u_dofs_global' to 'Gamma @ u_dofs_global'.
"""

with open('/app/buckling_analysis.py', 'r') as f:
    content = f.read()

# Count occurrences before fix for verification
bug1_count = content.count('Fx2 / 6.0')
bug2_count = content.count('Gamma.T @ u_dofs_global')

assert bug1_count == 8, f"Expected 8 occurrences of 'Fx2 / 6.0', found {bug1_count}"
assert bug2_count == 1, f"Expected 1 occurrence of 'Gamma.T @ u_dofs_global', found {bug2_count}"

# Bug 1: Fix geometric stiffness coupling coefficients
content = content.replace('Fx2 / 6.0', 'Fx2 / 10.0')

# Bug 2: Fix transformation direction in force recovery
content = content.replace(
    'u_local = Gamma.T @ u_dofs_global',
    'u_local = Gamma @ u_dofs_global'
)

with open('/app/buckling_analysis.py', 'w') as f:
    f.write(content)

# Verify fixes were applied correctly
with open('/app/buckling_analysis.py', 'r') as f:
    fixed = f.read()

assert 'Fx2 / 6.0' not in fixed, "Bug 1 not fully fixed"
assert 'Gamma.T @ u_dofs_global' not in fixed, "Bug 2 not fully fixed"
assert fixed.count('Fx2 / 10.0') == 8, "Wrong number of Fx2/10.0 terms after fix"
assert 'Gamma @ u_dofs_global' in fixed, "Missing corrected transformation"

print("Both bugs fixed successfully.")
print(f"  Bug 1: Changed {bug1_count} coefficient terms (Fx2/6 -> Fx2/10)")
print(f"  Bug 2: Corrected transformation direction (Gamma.T -> Gamma)")
