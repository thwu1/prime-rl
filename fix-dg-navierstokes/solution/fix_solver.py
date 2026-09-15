#!/usr/bin/env python3
"""
Fix the four bugs in /app/solver.py.


Bug 1  Pressure function space
       Wrong:   ("Lagrange", k)
       Correct: ("Discontinuous Lagrange", k)
       Reason:  For the div-conforming DG method with Raviart-Thomas
                velocity, we need div(V_h) = Q_h.  RT_{k+1} has
                div(RT_{k+1}) = DG_k, NOT CG_k.  Using continuous
                Lagrange for pressure breaks exact mass conservation.

Bug 2  MUMPS singular-system handling
       Missing: mat_mumps_icntl_24 = 1  and  mat_mumps_icntl_25 = 0
       Reason:  The saddle-point system is singular because pressure is
                determined only up to a constant.  MUMPS must be told
                to detect and handle null pivots; without these options
                the LU factorisation fails on the zero pivot.

Bug 3  SIP penalty parameter
       Wrong:   alpha = 1.0
       Correct: alpha = 6.0 * k**2
       Reason:  The Symmetric Interior Penalty method requires a
                sufficiently large penalty (scaling with k^2) for
                coercivity of the bilinear form on the DG space.
                Too-small penalty leads to an ill-posed discrete
                problem with spurious oscillations and degraded accuracy.

Bug 4  Upwind flux direction
       Wrong:   u_uw = lmbda("+") * u("-") + lmbda("-") * u("+")
       Correct: u_uw = lmbda("+") * u("+") + lmbda("-") * u("-")
       Reason:  lmbda("+") == 1 means flow goes from + to - side, so
                the upwind value is u("+"), not u("-").  The buggy code
                takes the DOWNwind value, reversing the convective
                stabilisation and causing large velocity errors.
"""

import sys

SOLVER_PATH = "/app/solver.py"

with open(SOLVER_PATH, "r") as f:
    code = f.read()

# Track fixes applied
fixes = 0

# ---- Bug 1: pressure function space ----
old_Q = 'Q = fem.functionspace(msh, ("Lagrange", k))'
new_Q = 'Q = fem.functionspace(msh, ("Discontinuous Lagrange", k))'
if old_Q in code:
    code = code.replace(old_Q, new_Q)
    fixes += 1
    print("Fixed Bug 1: pressure function space -> DG_k")
else:
    print("Bug 1 pattern not found (may already be fixed)")

# ---- Bug 2: MUMPS singular-system options ----
old_mumps = (
    '"mat_mumps_icntl_14": 80,       # Increase MUMPS working memory\n'
    '    "ksp_error_if_not_converged": 1,'
)
new_mumps = (
    '"mat_mumps_icntl_14": 80,       # Increase MUMPS working memory\n'
    '    "mat_mumps_icntl_24": 1,       # Detect null pivots\n'
    '    "mat_mumps_icntl_25": 0,       # Handle null-pivot rows\n'
    '    "ksp_error_if_not_converged": 1,'
)
if old_mumps in code:
    code = code.replace(old_mumps, new_mumps)
    fixes += 1
    print("Fixed Bug 2: added MUMPS icntl_24/25 options")
else:
    print("Bug 2 pattern not found (may already be fixed)")

# ---- Bug 3: SIP penalty parameter ----
old_alpha = "alpha = fem.Constant(msh, default_real_type(1.0))"
new_alpha = "alpha = fem.Constant(msh, default_real_type(6.0 * k**2))"
if old_alpha in code:
    code = code.replace(old_alpha, new_alpha)
    fixes += 1
    print("Fixed Bug 3: SIP penalty alpha -> 6*k^2")
else:
    print("Bug 3 pattern not found (may already be fixed)")

# ---- Bug 4: upwind flux direction ----
old_uw = 'u_uw = lmbda("+") * u("-") + lmbda("-") * u("+")'
new_uw = 'u_uw = lmbda("+") * u("+") + lmbda("-") * u("-")'
if old_uw in code:
    code = code.replace(old_uw, new_uw)
    fixes += 1
    print("Fixed Bug 4: upwind flux direction corrected")
else:
    print("Bug 4 pattern not found (may already be fixed)")

with open(SOLVER_PATH, "w") as f:
    f.write(code)

print(f"\n{fixes} bug(s) fixed in {SOLVER_PATH}")
if fixes < 4:
    print("WARNING: Not all bugs were found -- check solver manually")
