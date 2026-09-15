#!/usr/bin/env python3
"""

Solution: reverse-engineer NF4 codebook, design Lloyd-Max optimal quantizer,
evaluate and compare both approaches, find optimal NF4 alpha.
"""
import numpy as np
from scipy.stats import norm
from scipy.optimize import minimize_scalar
import json
import struct
import os

# =====================================================================
# Step 1: Parse the binary format
# =====================================================================
with open('/app/quantized_data.bin', 'rb') as f:
    raw = f.read()

with open('/app/metadata.json') as f:
    meta = json.load(f)

n_weights = meta['n_weights']
block_size = meta['block_size']
n_blocks = n_weights // block_size

n_weights_hdr, block_size_hdr = struct.unpack_from('<II', raw, 0)
assert n_weights_hdr == n_weights
assert block_size_hdr == block_size

offset = 8
scales = np.frombuffer(raw, dtype=np.float32, count=n_blocks, offset=offset).copy()
offset += n_blocks * 4
packed = np.frombuffer(raw, dtype=np.uint8, count=n_weights // 2, offset=offset).copy()

indices = np.zeros(n_weights, dtype=np.uint8)
for i in range(len(packed)):
    indices[2 * i] = packed[i] & 0x0F
    indices[2 * i + 1] = (packed[i] >> 4) & 0x0F

weights = np.fromfile('/app/original_weights.bin', dtype=np.float32)
assert len(weights) == n_weights

weights_f64 = weights.astype(np.float64)
scale_expanded = np.repeat(scales, block_size)

print(f"Parsed: {n_weights} weights, {n_blocks} blocks of {block_size}")
print(f"Index range: {indices.min()} to {indices.max()}")

# =====================================================================
# Step 2: QLoRA NF4 codebook construction
# =====================================================================
def codebook_from_alpha(a):
    """Construct the 16-element NF4 codebook for a given alpha."""
    Q = norm.ppf
    try:
        Z = Q(a)
    except Exception:
        return None
    if not np.isfinite(Z) or Z <= 0:
        return None
    d1 = (a - 0.5) / 7
    d2 = (a - 0.5) / 8
    cb = np.zeros(16, dtype=np.float64)
    for i in range(7):
        v = a - i * d1
        if v <= 0 or v >= 1:
            return None
        cb[i] = -Q(v) / Z
    for i in range(8):
        v = 0.5 + (i + 1) * d2
        if v <= 0 or v >= 1:
            return None
        cb[i + 8] = Q(v) / Z
    return cb

# =====================================================================
# Step 3: Recover alpha via MSE minimization + consistency check
# =====================================================================
scale_exp_f64 = scale_expanded.astype(np.float64)

def recon_mse(a):
    cb = codebook_from_alpha(a)
    if cb is None:
        return 1e10
    deq = cb[indices] * scale_exp_f64
    return float(np.mean((weights_f64 - deq) ** 2))

print("Stage A: Coarse grid search for alpha...")
alphas_coarse = np.linspace(0.90, 0.999, 500)
mses_coarse = [recon_mse(a) for a in alphas_coarse]
best_idx = int(np.argmin(mses_coarse))
alpha_coarse = alphas_coarse[best_idx]
print(f"  Coarse best: alpha={alpha_coarse:.6f}")

result = minimize_scalar(recon_mse,
                         bounds=(max(0.9, alpha_coarse - 0.01),
                                 min(0.999, alpha_coarse + 0.01)),
                         method='bounded', options={'xatol': 1e-14})
alpha_mse = result.x
print(f"  Refined: alpha={alpha_mse:.10f}")

# Nearest-neighbor consistency verification
nonzero_mask = scale_expanded != 0
normed_all = np.zeros(n_weights, dtype=np.float32)
normed_all[nonzero_mask] = weights[nonzero_mask] / scale_expanded[nonzero_mask]
nonzero_count = int(np.sum(nonzero_mask))

def count_consistent(a):
    cb = codebook_from_alpha(a)
    if cb is None:
        return 0
    cb32 = cb.astype(np.float32)
    dists = np.abs(normed_all[:, None] - cb32[None, :])
    nearest = np.argmin(dists, axis=1).astype(np.uint8)
    return int(np.sum((nearest == indices) & nonzero_mask))

print("Stage B: Nearest-neighbor consistency refinement...")
search_r = 0.005
alphas_fine = np.linspace(max(0.9, alpha_mse - search_r),
                          min(0.999, alpha_mse + search_r), 500)
best_con = 0
best_candidates = []
for a in alphas_fine:
    c = count_consistent(a)
    if c > best_con:
        best_con = c
        best_candidates = [a]
    elif c == best_con:
        best_candidates.append(a)

if best_con >= nonzero_count - 10:
    alpha = float(np.median(best_candidates))
    print(f"  Consistency: {best_con}/{nonzero_count}")
else:
    print("  Expanding search range...")
    alphas_wide = np.linspace(0.90, 0.999, 2000)
    best_con = 0
    best_candidates = []
    for a in alphas_wide:
        c = count_consistent(a)
        if c > best_con:
            best_con = c
            best_candidates = [a]
        elif c == best_con:
            best_candidates.append(a)
    alpha = float(np.median(best_candidates))

codebook_f64 = codebook_from_alpha(alpha)
codebook = codebook_f64.astype(np.float32)
print(f"Recovered alpha = {alpha:.10f}")

# =====================================================================
# Step 4: NF4 dequantize and compute error metrics
# =====================================================================
dequantized = codebook[indices] * scale_expanded

errors = weights - dequantized
mse = float(np.mean(errors ** 2))
max_abs_err = float(np.max(np.abs(errors)))
sig_power = float(np.mean(weights ** 2))
sqnr_db = float(10 * np.log10(sig_power / mse)) if mse > 0 else float('inf')

print(f"NF4: MSE={mse:.6e}, max_err={max_abs_err:.6e}, SQNR={sqnr_db:.2f} dB")

# =====================================================================
# Step 5: Lloyd-Max optimal quantizer design
# =====================================================================
def lloyd_max(data, n_levels=16, max_iter=500, tol=1e-10):
    """Iterative Lloyd-Max optimal scalar quantizer.
    Returns sorted reconstruction levels that satisfy the centroid condition."""
    qs = np.linspace(1 / (n_levels + 1), n_levels / (n_levels + 1), n_levels)
    levels = np.quantile(data, qs)

    for it in range(max_iter):
        dists = np.abs(data[:, None] - levels[None, :])
        assign = np.argmin(dists, axis=1)

        new_levels = np.empty_like(levels)
        for j in range(n_levels):
            mask = assign == j
            if np.sum(mask) > 0:
                new_levels[j] = np.mean(data[mask])
            else:
                new_levels[j] = levels[j]

        if np.max(np.abs(new_levels - levels)) < tol:
            print(f"  Lloyd-Max converged in {it + 1} iterations")
            break
        levels = new_levels

    return np.sort(levels)

# Normalize all weights using stored per-block scales
nz = scale_expanded != 0
normed_f64 = np.zeros(n_weights, dtype=np.float64)
normed_f64[nz] = weights_f64[nz] / scale_expanded[nz].astype(np.float64)
normed_nz = normed_f64[nz]

print("Running Lloyd-Max optimization on normalized weights...")
lm_cb_f64 = lloyd_max(normed_nz)
lm_cb_f32 = lm_cb_f64.astype(np.float32)
print(f"Lloyd-Max codebook: {lm_cb_f32}")

# Dequantize with Lloyd-Max codebook + per-block scaling
lm_deq = np.zeros(n_weights, dtype=np.float32)
for b in range(n_blocks):
    s, e = b * block_size, (b + 1) * block_size
    block = weights[s:e]
    sc = scales[b]
    if sc == 0:
        continue
    normed_block = block / sc
    dists = np.abs(normed_block[:, None] - lm_cb_f32[None, :])
    idx = np.argmin(dists, axis=1)
    lm_deq[s:e] = lm_cb_f32[idx] * sc

lm_errors = weights - lm_deq
lm_mse = float(np.mean(lm_errors ** 2))
lm_max_abs_err = float(np.max(np.abs(lm_errors)))
lm_sqnr = float(10 * np.log10(sig_power / lm_mse)) if lm_mse > 0 else float('inf')

print(f"Lloyd-Max: MSE={lm_mse:.6e}, max_err={lm_max_abs_err:.6e}, SQNR={lm_sqnr:.2f} dB")

# =====================================================================
# Step 6: Comparison evaluation
# =====================================================================
if mse < lm_mse:
    mse_winner = 'nf4'
    mse_improvement_pct = (lm_mse - mse) / lm_mse * 100
else:
    mse_winner = 'lloyd_max'
    mse_improvement_pct = (mse - lm_mse) / mse * 100

sqnr_winner = 'nf4' if sqnr_db > lm_sqnr else 'lloyd_max'

print(f"MSE winner: {mse_winner} ({mse_improvement_pct:.2f}% improvement)")
print(f"SQNR winner: {sqnr_winner}")

# =====================================================================
# Step 7: Find optimal NF4 alpha via grid search
# =====================================================================
def compute_mse_requant(a):
    cb = codebook_from_alpha(a)
    if cb is None:
        return float('inf')
    cb32 = cb.astype(np.float32)
    total_se = 0.0
    for b in range(n_blocks):
        s, e = b * block_size, (b + 1) * block_size
        block = weights[s:e]
        sc = float(np.max(np.abs(block)))
        if sc == 0:
            continue
        normed = block / sc
        dists = np.abs(normed[:, None] - cb32[None, :])
        idx = np.argmin(dists, axis=1)
        deq = cb32[idx] * sc
        total_se += float(np.sum((block - deq) ** 2))
    return total_se / n_weights

print("Searching for optimal NF4 alpha (coarse)...")
best_alpha = alpha
best_mse_opt = compute_mse_requant(alpha)
for ac in np.linspace(0.90, 0.998, 200):
    m = compute_mse_requant(ac)
    if m < best_mse_opt:
        best_mse_opt = m
        best_alpha = float(ac)

print(f"Refining around {best_alpha:.4f}...")
for ac in np.linspace(max(0.90, best_alpha - 0.005),
                      min(0.998, best_alpha + 0.005), 200):
    m = compute_mse_requant(ac)
    if m < best_mse_opt:
        best_mse_opt = m
        best_alpha = float(ac)

print(f"Optimal alpha = {best_alpha:.6f}, MSE = {best_mse_opt:.6e}")

# =====================================================================
# Step 8: Write all output files
# =====================================================================
os.makedirs('/app/output', exist_ok=True)

with open('/app/output/codebook.json', 'w') as f:
    json.dump(sorted(codebook.tolist()), f)

with open('/app/output/alpha.txt', 'w') as f:
    f.write(f'{alpha:.10f}\n')

dequantized.tofile('/app/output/dequantized.bin')

with open('/app/output/error_metrics.json', 'w') as f:
    json.dump({'mse': mse, 'max_abs_error': max_abs_err, 'sqnr_db': sqnr_db}, f)

with open('/app/output/lloyd_max_codebook.json', 'w') as f:
    json.dump(sorted(lm_cb_f32.tolist()), f)

lm_deq.tofile('/app/output/lloyd_max_dequantized.bin')

with open('/app/output/lloyd_max_metrics.json', 'w') as f:
    json.dump({'mse': lm_mse, 'max_abs_error': lm_max_abs_err,
               'sqnr_db': lm_sqnr}, f)

with open('/app/output/comparison.json', 'w') as f:
    json.dump({
        'nf4_mse': mse,
        'lloyd_max_mse': lm_mse,
        'nf4_sqnr_db': sqnr_db,
        'lloyd_max_sqnr_db': lm_sqnr,
        'mse_winner': mse_winner,
        'mse_improvement_pct': mse_improvement_pct,
        'sqnr_winner': sqnr_winner
    }, f)

with open('/app/output/optimal_alpha.txt', 'w') as f:
    f.write(f'{best_alpha:.6f}\n')

print("Solution complete. All results written to /app/output/")
