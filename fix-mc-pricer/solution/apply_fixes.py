"""Apply the five corrections to the Monte Carlo pricing engine.

Bug 1 – sobol.py: Gray-code enumeration uses rightmost_zero_bit(i)
        instead of rightmost_zero_bit(i - 1), producing a sequence that
        violates the stratification property of Sobol points.

Bug 2 – norm_inv.py: tail-region computation uses sqrt(-log(u)) instead
        of sqrt(-2 * log(u)), giving wrong quantiles outside the central
        95 % of the distribution.

Bug 3 – gbm_paths.py: drift term is r * dt rather than
        (r - 0.5 * sigma**2) * dt, missing the Ito correction required
        under the risk-neutral measure.

Bug 4 – payoffs.py: Asian-option arithmetic average incorrectly includes
        S0 in the sum, biasing the average toward the initial price.

Bug 5 – mc_pricer.py: antithetic variates are formed as (1 - z) instead
        of (-z), confusing the uniform-antithetic with the normal-
        antithetic and introducing a positive-mean bias.
"""
import pathlib

APP = pathlib.Path("/app")


def _patch(filename, old, new):
    p = APP / filename
    src = p.read_text()
    if old not in src:
        raise RuntimeError(f"{filename}: pattern not found:\n  {old!r}")
    src = src.replace(old, new, 1)
    p.write_text(src)


# Fix 1 – Sobol Gray-code index
_patch(
    "sobol.py",
    "c = _rightmost_zero_bit(i)",
    "c = _rightmost_zero_bit(i - 1)",
)

# Fix 2 – inverse-normal tail formula (lower & upper)
_patch(
    "norm_inv.py",
    "q = math.sqrt(-math.log(u))",
    "q = math.sqrt(-2.0 * math.log(u))",
)
_patch(
    "norm_inv.py",
    "q = math.sqrt(-math.log(1.0 - u))",
    "q = math.sqrt(-2.0 * math.log(1.0 - u))",
)

# Fix 3 – GBM Ito drift correction
_patch(
    "gbm_paths.py",
    "drift = r * dt",
    "drift = (r - 0.5 * sigma ** 2) * dt",
)

# Fix 4 – Asian option average (exclude S0)
_patch(
    "payoffs.py",
    "avg = (S0 + sum(path)) / (len(path) + 1)",
    "avg = sum(path) / len(path)",
)

# Fix 5 – antithetic variates: negate normals
_patch(
    "mc_pricer.py",
    "anti_normals = [1.0 - z for z in normals]",
    "anti_normals = [-z for z in normals]",
)

print("All 5 bugs fixed successfully.")
