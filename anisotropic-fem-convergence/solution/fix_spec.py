#!/usr/bin/env python3
"""
Diagnose and fix the forcing function error in problem_spec.py.

Numerically computes -div(K grad u) + c*u at interior points and
compares with the provided forcing function to detect inconsistencies.
Then analytically derives the correct forcing and patches the file.

"""
import numpy as np
import sys

sys.path.insert(0, '/app')
from problem_spec import diffusion_tensor, reaction, exact_solution, forcing


def numerical_neg_div_Kgu(x0, y0, h=1e-5):
    """Compute -div(K grad u) + c*u numerically via finite differences."""
    u = exact_solution

    def kgrad_comp(x, y, comp):
        K = diffusion_tensor(x, y)
        ux = (u(x + h, y) - u(x - h, y)) / (2 * h)
        uy = (u(x, y + h) - u(x, y - h)) / (2 * h)
        return K[comp, 0] * ux + K[comp, 1] * uy

    dFx_dx = (kgrad_comp(x0 + h, y0, 0) - kgrad_comp(x0 - h, y0, 0)) / (2 * h)
    dFy_dy = (kgrad_comp(x0, y0 + h, 1) - kgrad_comp(x0, y0 - h, 1)) / (2 * h)

    return -(dFx_dx + dFy_dy) + reaction(x0, y0) * u(x0, y0)


# Step 1: Diagnose the inconsistency
print("=== Diagnosing PDE consistency ===")
test_points = [(0.25, 0.75), (0.3, 0.4), (0.7, 0.3), (0.5, 0.5)]
has_error = False

for x, y in test_points:
    num_f = numerical_neg_div_Kgu(x, y)
    ana_f = forcing(x, y)
    rel_err = abs(num_f - ana_f) / (abs(num_f) + 1e-15)
    status = "OK" if rel_err < 0.005 else "MISMATCH"
    print(f"  ({x:.2f}, {y:.2f}): numerical={num_f:.8f}, provided={ana_f:.8f}, "
          f"rel_err={rel_err:.6f} [{status}]")
    if rel_err >= 0.005:
        has_error = True

if not has_error:
    print("No forcing function error detected.")
    sys.exit(0)

# Step 2: Analytically derive the correct forcing
# u = sin(pi*x)*sin(pi*y), K = [[1+x^2, xy/2], [xy/2, 1+y^2]], c = 1
#
# grad u = [pi*cx*sy, pi*sx*cy]
#
# K grad u = [(1+x^2)*pi*cx*sy + (xy/2)*pi*sx*cy,
#             (xy/2)*pi*cx*sy + (1+y^2)*pi*sx*cy]
#
# d/dx(flux_x):
#   d/dx[(1+x^2)*pi*cx*sy] = 2x*pi*cx*sy - (1+x^2)*pi^2*sx*sy
#   d/dx[(xy/2)*pi*sx*cy]  = (y/2)*pi*sx*cy + (xy/2)*pi^2*cx*cy
#
# d/dy(flux_y):
#   d/dy[(xy/2)*pi*cx*sy]  = (x/2)*pi*cx*sy + (xy/2)*pi^2*cx*cy  (CROSS TERM 2)
#   d/dy[(1+y^2)*pi*sx*cy] = 2y*pi*sx*cy - (1+y^2)*pi^2*sx*sy
#
# Collecting terms:
#   sx*sy coefficient: -(1+x^2)*pi^2 - (1+y^2)*pi^2 = -pi^2*(2+x^2+y^2)
#   cx*sy coefficient: 2*pi*x + (1/2)*pi*x = (5/2)*pi*x = 2.5*pi*x
#   sx*cy coefficient: (1/2)*pi*y + 2*pi*y = (5/2)*pi*y = 2.5*pi*y
#   cx*cy coefficient: (xy/2)*pi^2 + (xy/2)*pi^2 = xy*pi^2
#
# Therefore: -div(K grad u) = pi^2*(2+x^2+y^2)*sx*sy - 2.5*pi*x*cx*sy
#                              - 2.5*pi*y*sx*cy - xy*pi^2*cx*cy
#
# f = -div(K grad u) + c*u = (pi^2*(2+x^2+y^2) + 1)*sx*sy - 2.5*pi*x*cx*sy
#                             - 2.5*pi*y*sx*cy - xy*pi^2*cx*cy

print("\n=== Fixing forcing function ===")
print("Identified error: coefficient on x*cos(pi*x)*sin(pi*y) term is 2.0, should be 2.5")

# Step 3: Patch problem_spec.py
with open('/app/problem_spec.py', 'r') as f:
    content = f.read()

# Fix the coefficient: 2.0 -> 2.5
content = content.replace('- 2.0 * pi * x * cx * sy', '- 2.5 * pi * x * cx * sy', 1)

with open('/app/problem_spec.py', 'w') as f:
    f.write(content)

print("Patched /app/problem_spec.py: changed coefficient 2.0 -> 2.5")

# Step 4: Verify the fix
print("\n=== Verifying fix ===")
# Reload module
if 'problem_spec' in sys.modules:
    del sys.modules['problem_spec']
from problem_spec import forcing as fixed_forcing

for x, y in test_points:
    num_f = numerical_neg_div_Kgu(x, y)
    ana_f = fixed_forcing(x, y)
    rel_err = abs(num_f - ana_f) / (abs(num_f) + 1e-15)
    print(f"  ({x:.2f}, {y:.2f}): numerical={num_f:.8f}, fixed={ana_f:.8f}, "
          f"rel_err={rel_err:.6f}")
    assert rel_err < 0.001, f"Fix verification failed at ({x}, {y})"

print("\nForcing function fix verified successfully.")
