"""Solver for the NF4 reverse engineering task.

Reverse-engineers the NormalFloat quantization format construction,
discovers alpha = 929/960, extends to NF6/NF8, and computes
quantization errors.
"""

import json
import os
from scipy.stats import norm
from scipy.optimize import minimize_scalar

RESULTS_DIR = "/app/results"
os.makedirs(RESULTS_DIR, exist_ok=True)

Q = norm.ppf  # quantile function (inverse CDF) of N(0,1)


# ── Step 1: Reverse-engineer NF4 ─────────────────────────────────

def construct_nfn(n_bits, alpha):
    """
    Construct the NFn codebook.

    Layout: (N/2 - 1) negative values, zero, N/2 positive values.
    Negative values use evenly-spaced probabilities from alpha down to just
    above 0.5.  Positive values use evenly-spaced probabilities from just
    above 0.5 up to alpha.  All values are normalised by Q(alpha) so that
    the codebook spans [-1, 1].
    """
    N = 2 ** n_bits
    n_neg = N // 2 - 1
    n_pos = N // 2

    Z = Q(alpha)
    delta_neg = (alpha - 0.5) / n_neg
    delta_pos = (alpha - 0.5) / n_pos

    codebook = [0.0] * N
    for i in range(n_neg):
        codebook[i] = -Q(alpha - i * delta_neg) / Z
    codebook[n_neg] = 0.0
    for i in range(n_pos):
        codebook[n_neg + 1 + i] = Q(0.5 + (i + 1) * delta_pos) / Z

    return codebook


# Load published NF4 values
with open("/app/nf4_published.json") as f:
    nf4_published = json.load(f)


# Find alpha by minimising the max deviation from published values
def objective(alpha):
    if alpha <= 0.5 or alpha >= 1.0:
        return 1e10
    try:
        cb = construct_nfn(4, alpha)
        return max(abs(a - b) for a, b in zip(cb, nf4_published))
    except Exception:
        return 1e10


result = minimize_scalar(objective, bounds=(0.9, 0.999), method="bounded")
alpha_opt = result.x

# Verify it matches 929/960
alpha_frac_num = 929
alpha_frac_den = 960
alpha_exact = alpha_frac_num / alpha_frac_den
assert abs(alpha_opt - alpha_exact) < 1e-5, (
    f"Optimised alpha {alpha_opt} doesn't match 929/960 = {alpha_exact}"
)

alpha = alpha_exact
print(f"Discovered alpha = {alpha_frac_num}/{alpha_frac_den} = {alpha}")


# ── Step 2: Write alpha ──────────────────────────────────────────

with open(os.path.join(RESULTS_DIR, "alpha.txt"), "w") as f:
    f.write("929/960")


# ── Step 3: Write construction.py ─────────────────────────────────

construction_src = '''\
"""NormalFloat quantization codebook construction."""
from scipy.stats import norm

Q = norm.ppf


def construct_nfn(n_bits: int, alpha: float) -> list[float]:
    """Return the sorted NFn codebook for the given bit width and alpha.

    Layout: (N/2 - 1) negative values, zero, N/2 positive values,
    where N = 2**n_bits.  Values are normalised to [-1, 1].
    """
    N = 2 ** n_bits
    n_neg = N // 2 - 1
    n_pos = N // 2

    Z = Q(alpha)
    delta_neg = (alpha - 0.5) / n_neg
    delta_pos = (alpha - 0.5) / n_pos

    codebook = [0.0] * N
    for i in range(n_neg):
        codebook[i] = -Q(alpha - i * delta_neg) / Z
    codebook[n_neg] = 0.0
    for i in range(n_pos):
        codebook[n_neg + 1 + i] = Q(0.5 + (i + 1) * delta_pos) / Z

    return codebook
'''

with open(os.path.join(RESULTS_DIR, "construction.py"), "w") as f:
    f.write(construction_src)


# ── Step 4: Generate codebooks ────────────────────────────────────

nf4 = construct_nfn(4, alpha)
nf6 = construct_nfn(6, alpha)
nf8 = construct_nfn(8, alpha)

with open(os.path.join(RESULTS_DIR, "nf4_reproduced.json"), "w") as f:
    json.dump(nf4, f)

with open(os.path.join(RESULTS_DIR, "nf6_values.json"), "w") as f:
    json.dump(nf6, f)

with open(os.path.join(RESULTS_DIR, "nf8_values.json"), "w") as f:
    json.dump(nf8, f)

# Verify NF4 reproduction
max_nf4_err = max(abs(a - b) for a, b in zip(nf4, nf4_published))
print(f"NF4 max reproduction error: {max_nf4_err:.2e}")


# ── Step 5: Block quantization and error computation ──────────────

with open("/app/weights.json") as f:
    weights = json.load(f)

BLOCK_SIZE = 64


def quantize_block(block, codebook):
    """Quantize a block using absmax scaling."""
    scale = max(abs(x) for x in block)
    if scale == 0.0:
        zero_idx = len(codebook) // 2 - 1
        return [zero_idx] * len(block), scale
    indices = []
    for x in block:
        normalised = x / scale
        best_idx = 0
        best_dist = abs(normalised - codebook[0])
        for j in range(1, len(codebook)):
            d = abs(normalised - codebook[j])
            if d < best_dist:
                best_dist = d
                best_idx = j
        indices.append(best_idx)
    return indices, scale


def compute_mse(weights, codebook, block_size=BLOCK_SIZE):
    """Mean squared quantization error with block-wise absmax scaling."""
    total_err = 0.0
    n = len(weights)
    for start in range(0, n, block_size):
        block = weights[start:start + block_size]
        indices, scale = quantize_block(block, codebook)
        for i, idx in enumerate(indices):
            reconstructed = codebook[idx] * scale
            total_err += (block[i] - reconstructed) ** 2
    return total_err / n


def uniform_codebook(n_bits):
    """Uniform quantization codebook spanning [-1, 1]."""
    N = 2 ** n_bits
    return [-1.0 + 2.0 * i / (N - 1) for i in range(N)]


errors = {
    "nf4": compute_mse(weights, nf4),
    "nf6": compute_mse(weights, nf6),
    "nf8": compute_mse(weights, nf8),
    "uniform4": compute_mse(weights, uniform_codebook(4)),
    "uniform6": compute_mse(weights, uniform_codebook(6)),
    "uniform8": compute_mse(weights, uniform_codebook(8)),
}

with open(os.path.join(RESULTS_DIR, "quantization_errors.json"), "w") as f:
    json.dump(errors, f)

print("Quantization errors:")
for k, v in sorted(errors.items()):
    print(f"  {k}: {v:.8f}")

print("\nDone. All results written to /app/results/")
