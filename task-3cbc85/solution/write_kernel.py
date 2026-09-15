#!/usr/bin/env python3
"""Generate the scaled dot-product attention kernel for VecTor-16.


This script programmatically generates the assembly kernel by computing
memory layout offsets, register allocation, and instruction sequences for
each phase of the attention computation.
"""

import os
import math

# Architecture parameters
D_K = 32           # head dimension
SEQ_LEN = 8        # sequence length (KV cache size)
VLEN = 16          # vector register length
TILES = D_K // VLEN  # = 2 tiles per vector

# Memory layout (must match memory_layout.md and test expectations)
Q_ADDR = 0                                    # 0-31
K_ADDR = Q_ADDR + D_K                         # 32-287
V_ADDR = K_ADDR + SEQ_LEN * D_K               # 288-543
N_VALID_ADDR = V_ADDR + SEQ_LEN * D_K         # 544
OUTPUT_ADDR = 560                              # 560-591 (16-aligned)
SCRATCH_ADDR = 592                             # 592+ (scores/attn scratch)

# Verify all critical addresses are VLEN-aligned
for name, addr in [("Q", Q_ADDR), ("K", K_ADDR), ("V", V_ADDR),
                   ("OUTPUT", OUTPUT_ADDR), ("SCRATCH", SCRATCH_ADDR)]:
    assert addr % VLEN == 0, f"{name} at {addr} not {VLEN}-aligned"
for i in range(SEQ_LEN):
    assert (K_ADDR + i * D_K) % VLEN == 0, f"K[{i}] not aligned"
    assert (V_ADDR + i * D_K) % VLEN == 0, f"V[{i}] not aligned"


def gen_dot_products():
    """Phase 1: score[i] = dot(Q, K[i]) for i=0..SEQ_LEN-1.

    Register allocation:
      v6, v7: Q tiles (loaded once, persist across loop)
      v1: K[i] tile (reloaded each iteration)
      v2: element-wise product
      s0: dot product accumulator
      s1: reduction result / counter increment
      s14: loop limit (SEQ_LEN)
      s15: loop counter
      a0: Q base address
      a1: K pointer (advances by D_K each iteration)
      a3: scores write pointer (advances by 1 each iteration)
    """
    lines = ["# ===== Phase 1: Compute attention scores ====="]
    lines.append(f"ASET a0, {Q_ADDR}")
    lines.append(f"ASET a1, {K_ADDR}")
    lines.append(f"ASET a3, {SCRATCH_ADDR}")

    # Pre-load Q tiles into persistent registers
    for t in range(TILES):
        lines.append(f"VLOAD v{6 + t}, a0, {t * VLEN}")

    lines.append("SSET s15, 0.0")
    lines.append(f"SSET s14, {float(SEQ_LEN)}")

    lines.append("LABEL dot_loop")
    lines.append("SSET s0, 0.0")
    for t in range(TILES):
        lines.append(f"VLOAD v1, a1, {t * VLEN}")
        lines.append(f"VMUL v2, v{6 + t}, v1")
        lines.append("VREDSUM s1, v2")
        lines.append("SADD s0, s0, s1")
    lines.append("SSTORE s0, a3, 0")
    lines.append(f"AADD a1, a1, {D_K}")
    lines.append("AADD a3, a3, 1")
    lines.append("SSET s1, 1.0")
    lines.append("SADD s15, s15, s1")
    lines.append("JLT s15, s14, dot_loop")

    return lines


def gen_scale():
    """Phase 2: score[i] /= sqrt(d_k).

    Uses SSQRT to compute sqrt(d_k), then SDIV for each score.
    This matches the reference implementation's division exactly.

    Register allocation:
      s0: temp (loaded score)
      s1: counter increment
      s13: sqrt(d_k)
      s14: loop limit
      s15: loop counter
      a3: scores pointer
    """
    lines = ["# ===== Phase 2: Scale scores by 1/sqrt(d_k) ====="]
    lines.append(f"ASET a3, {SCRATCH_ADDR}")
    lines.append(f"SSET s13, {float(D_K)}")
    lines.append("SSQRT s13, s13")
    lines.append("SSET s15, 0.0")
    lines.append(f"SSET s14, {float(SEQ_LEN)}")

    lines.append("LABEL scale_loop")
    lines.append("SLOAD s0, a3, 0")
    lines.append("SDIV s0, s0, s13")
    lines.append("SSTORE s0, a3, 0")
    lines.append("AADD a3, a3, 1")
    lines.append("SSET s1, 1.0")
    lines.append("SADD s15, s15, s1")
    lines.append("JLT s15, s14, scale_loop")

    return lines


def gen_causal_mask():
    """Phase 3: score[i] = -inf for i >= n_valid.

    Uses conditional jump (JLT) to skip masking for valid positions.

    Register allocation:
      s1: counter increment
      s10: -infinity constant
      s12: n_valid (loaded from memory)
      s14: loop limit
      s15: loop counter (compared against s12)
      a3: scores pointer
      a4: config memory pointer
    """
    lines = ["# ===== Phase 3: Apply causal mask ====="]
    lines.append(f"ASET a4, {N_VALID_ADDR}")
    lines.append("SLOAD s12, a4, 0")
    lines.append(f"ASET a3, {SCRATCH_ADDR}")
    lines.append("SSET s10, -inf")
    lines.append("SSET s15, 0.0")
    lines.append(f"SSET s14, {float(SEQ_LEN)}")

    lines.append("LABEL mask_loop")
    lines.append("JLT s15, s12, mask_skip")
    lines.append("SSTORE s10, a3, 0")
    lines.append("LABEL mask_skip")
    lines.append("AADD a3, a3, 1")
    lines.append("SSET s1, 1.0")
    lines.append("SADD s15, s15, s1")
    lines.append("JLT s15, s14, mask_loop")

    return lines


def gen_softmax():
    """Phase 4: Numerically stable softmax.

    Three passes over the scores array:
    1. Find max score (SMAX loop)
    2. Compute exp(score - max) for each, accumulate sum (SEXP loop)
    3. Normalize: attn[i] = exp[i] / sum (SDIV loop)

    Handles masked positions correctly:
    - max(-inf, x) = x, so masked scores don't affect the max
    - exp(-inf - max) = exp(-inf) = 0.0 (via safe_exp saturation)
    - 0.0 / sum = 0.0, so masked positions get zero attention weight

    Register allocation:
      s0: max value (persists across pass 1 → pass 2)
      s1: sum of exp values (persists across pass 2 → pass 3)
      s2: temp (score, shifted score, exp value)
      s3: counter increment (passes 2, 3)
      s14: loop limit
      s15: loop counter
      a3: scores pointer (reset each pass)
    """
    lines = ["# ===== Phase 4: Numerically stable softmax ====="]

    # Pass 1: Find max
    lines.append("# -- Pass 1: Find max score --")
    lines.append(f"ASET a3, {SCRATCH_ADDR}")
    lines.append("SLOAD s0, a3, 0")
    lines.append("AADD a3, a3, 1")
    lines.append("SSET s15, 1.0")
    lines.append(f"SSET s14, {float(SEQ_LEN)}")

    lines.append("LABEL max_loop")
    lines.append("SLOAD s1, a3, 0")
    lines.append("SMAX s0, s0, s1")
    lines.append("AADD a3, a3, 1")
    lines.append("SSET s2, 1.0")
    lines.append("SADD s15, s15, s2")
    lines.append("JLT s15, s14, max_loop")

    # Pass 2: Compute exp(score - max) and accumulate sum
    lines.append("# -- Pass 2: Compute exp(score - max) and sum --")
    lines.append(f"ASET a3, {SCRATCH_ADDR}")
    lines.append("SSET s1, 0.0")
    lines.append("SSET s15, 0.0")

    lines.append("LABEL exp_loop")
    lines.append("SLOAD s2, a3, 0")
    lines.append("SSUB s2, s2, s0")
    lines.append("SEXP s2, s2")
    lines.append("SSTORE s2, a3, 0")
    lines.append("SADD s1, s1, s2")
    lines.append("AADD a3, a3, 1")
    lines.append("SSET s3, 1.0")
    lines.append("SADD s15, s15, s3")
    lines.append("JLT s15, s14, exp_loop")

    # Pass 3: Normalize
    lines.append("# -- Pass 3: Normalize --")
    lines.append(f"ASET a3, {SCRATCH_ADDR}")
    lines.append("SSET s15, 0.0")

    lines.append("LABEL norm_loop")
    lines.append("SLOAD s2, a3, 0")
    lines.append("SDIV s2, s2, s1")
    lines.append("SSTORE s2, a3, 0")
    lines.append("AADD a3, a3, 1")
    lines.append("SSET s3, 1.0")
    lines.append("SADD s15, s15, s3")
    lines.append("JLT s15, s14, norm_loop")

    return lines


def gen_weighted_sum():
    """Phase 5: output = sum_i(attn[i] * V[i]).

    For each V[i], load its tiles, multiply each by the scalar attn[i],
    and accumulate into vector register accumulators.

    Register allocation:
      v0: temporary (V tile, then scaled)
      v4, v5: output accumulators (tile 0, tile 1)
      s0: attention weight (scalar)
      s1: counter increment
      s14: loop limit
      s15: loop counter
      a3: attn weights pointer
      a5: V pointer (advances by D_K each iteration)
      a6: output base address
    """
    lines = ["# ===== Phase 5: Weighted sum of value vectors ====="]
    lines.append(f"ASET a3, {SCRATCH_ADDR}")
    lines.append(f"ASET a5, {V_ADDR}")
    lines.append(f"ASET a6, {OUTPUT_ADDR}")

    # Initialize accumulators to zero
    lines.append("SSET s0, 0.0")
    lines.append("VFILL v4, s0")
    lines.append("VCOPY v5, v4")

    lines.append("SSET s15, 0.0")
    lines.append(f"SSET s14, {float(SEQ_LEN)}")

    lines.append("LABEL wsum_loop")
    lines.append("SLOAD s0, a3, 0")
    for t in range(TILES):
        lines.append(f"VLOAD v0, a5, {t * VLEN}")
        lines.append("VMULS v0, v0, s0")
        lines.append(f"VADD v{4 + t}, v{4 + t}, v0")
    lines.append("AADD a3, a3, 1")
    lines.append(f"AADD a5, a5, {D_K}")
    lines.append("SSET s1, 1.0")
    lines.append("SADD s15, s15, s1")
    lines.append("JLT s15, s14, wsum_loop")

    # Store output
    for t in range(TILES):
        lines.append(f"VSTORE v{4 + t}, a6, {t * VLEN}")

    return lines


def generate_full_kernel():
    """Assemble the complete attention kernel."""
    lines = [
        "# Scaled Dot-Product Attention with Causal Masking",
        f"# d_k={D_K}, seq_len={SEQ_LEN}, VLEN={VLEN}, tiles={TILES}",
        f"# Memory: Q@{Q_ADDR} K@{K_ADDR} V@{V_ADDR} "
        f"n_valid@{N_VALID_ADDR} out@{OUTPUT_ADDR} scratch@{SCRATCH_ADDR}",
        "",
    ]

    lines += gen_dot_products()
    lines.append("")
    lines += gen_scale()
    lines.append("")
    lines += gen_causal_mask()
    lines.append("")
    lines += gen_softmax()
    lines.append("")
    lines += gen_weighted_sum()
    lines.append("")
    lines.append("HALT")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    os.makedirs('/app/kernels', exist_ok=True)
    kernel = generate_full_kernel()
    with open('/app/kernels/attention.asm', 'w') as f:
        f.write(kernel)
    line_count = len(kernel.strip().split('\n'))
    print(f"Kernel written to /app/kernels/attention.asm ({line_count} lines)")
