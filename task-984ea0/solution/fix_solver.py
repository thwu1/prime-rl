"""Apply all four fixes to the buggy CNS1D solver.

Bug 1: GAMMA = 1.4 should be 5/3 (monatomic ideal gas, not diatomic).
Bug 2: Energy flux viscous stress uses (zeta + eta/3) but sigma' = (zeta + 4*eta/3)*dv_dx.
Bug 3: Periodic ghost cells use x[:,-1:] and x[:,:1] (boundary points that coincide)
        instead of x[:,-2:-1] and x[:,1:2] (true periodic neighbors on vertex grid).
Bug 4: Pressure gradient central difference uses /dx instead of /(2*dx).
"""

with open("/app/solver.py", "r") as f:
    code = f.read()

# Fix 1: Correct ratio of specific heats for monatomic ideal gas
code = code.replace("GAMMA = 1.4", "GAMMA = 5.0 / 3.0")

# Fix 2: Correct viscous stress coefficient in energy flux
# The viscous stress tensor is sigma' = (zeta + 4*eta/3) * dv_dx
# The momentum equation correctly uses (eta + zeta + eta/3) = (4*eta/3 + zeta) for d2v/dx2
# but the energy flux incorrectly uses (zeta + eta/3) instead of (zeta + 4*eta/3)
code = code.replace(
    "Vx * (zeta + eta / 3) * dv_dx",
    "Vx * (zeta + 4 * eta / 3) * dv_dx",
)

# Fix 3: Correct periodic ghost cell padding for vertex-centered grid
# On a vertex-centered periodic grid, x[0] and x[N-1] are the same physical point.
# The left ghost cell should be x[N-2] (neighbor), not x[N-1] (=x[0], same point).
# The right ghost cell should be x[1] (neighbor), not x[0] (=x[N-1], same point).
code = code.replace("x[:, -1:]", "x[:, -2:-1]")
code = code.replace("x[:, :1]", "x[:, 1:2]")

# Fix 4: Correct central difference denominator for pressure gradient
# Central difference (f[i+1] - f[i-1]) has stride 2*dx, not dx
code = code.replace(
    "pressure_pad[:, :-2]) / dx",
    "pressure_pad[:, :-2]) / (2 * dx)",
)

with open("/app/solver.py", "w") as f:
    f.write(code)

print("Applied all fixes to /app/solver.py")
