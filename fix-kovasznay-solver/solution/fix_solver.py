"""
Fix four bugs in /app/kovasznay.py:

1. Viscosity coefficient: Re -> 1/Re  (nu = 1/Re, not Re)
2. Pressure coupling sign: + -> -     (integration by parts of grad(p).v)
3. Missing right-boundary BC:         (x = 1.5 Dirichlet condition)
4. Picard velocity update:            (u_n must be refreshed each iteration)
"""

with open("/app/kovasznay.py", "r") as f:
    code = f.read()

# ---------- Fix 1: viscous diffusion coefficient ----------
# The kinematic viscosity is nu = 1/Re, not Re.
code = code.replace(
    "Re * ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx",
    "(1.0 / Re) * ufl.inner(ufl.grad(u), ufl.grad(v)) * ufl.dx",
)

# ---------- Fix 2: pressure-velocity coupling sign ----------
# From the weak form:  integral of grad(p).v  =  - integral of p div(v)
# The sign must be negative (consistent with the continuity term).
code = code.replace(
    "    + ufl.inner(p, ufl.div(v)) * ufl.dx",
    "    - ufl.inner(p, ufl.div(v)) * ufl.dx",
)

# ---------- Fix 3: add missing right-boundary Dirichlet BC ----------
# The domain is [-0.5, 1.5]^2 and all four edges need exact-solution BCs.
code = code.replace(
    "dofs_top = fem.locate_dofs_topological((W0, V_collapsed), fdim, facets_top)",
    (
        "dofs_top = fem.locate_dofs_topological((W0, V_collapsed), fdim, facets_top)\n"
        "\n"
        "facets_right = mesh.locate_entities_boundary(domain, fdim, lambda x: np.isclose(x[0], 1.5))\n"
        "dofs_right = fem.locate_dofs_topological((W0, V_collapsed), fdim, facets_right)"
    ),
)

code = code.replace(
    "    fem.dirichletbc(u_D, dofs_top, W0),\n]",
    "    fem.dirichletbc(u_D, dofs_top, W0),\n"
    "    fem.dirichletbc(u_D, dofs_right, W0),\n]",
)

# ---------- Fix 4: update convecting velocity in Picard loop ----------
# After each solve, u_n must be set to the velocity component of w_h
# so the next iteration linearises around the latest solution.
code = code.replace(
    "    w_prev.x.array[:] = w_h.x.array\n    n_iters = iteration + 1",
    (
        "    w_prev.x.array[:] = w_h.x.array\n"
        "    u_n_collapsed = w_h.sub(0).collapse()\n"
        "    u_n.x.array[:] = u_n_collapsed.x.array\n"
        "    n_iters = iteration + 1"
    ),
)

# ---------- Verify all fixes were applied ----------
assert "(1.0 / Re) * ufl.inner(ufl.grad(u), ufl.grad(v))" in code, \
    "Fix 1 (viscosity coefficient) failed to apply"
assert "    - ufl.inner(p, ufl.div(v)) * ufl.dx" in code, \
    "Fix 2 (pressure coupling sign) failed to apply"
assert "facets_right" in code, \
    "Fix 3 (right boundary BC) failed to apply"
assert "u_n_collapsed = w_h.sub(0).collapse()" in code, \
    "Fix 4 (Picard velocity update) failed to apply"

with open("/app/kovasznay.py", "w") as f:
    f.write(code)

print("All 4 bugs fixed in /app/kovasznay.py")
