# Excerpted from flash-attention benchmarks/benchmark_flash_attention.py
# FLOPs calculation for attention operations.

import math


def flops(batch, seqlen, headdim, nheads, causal, mode="fwd"):
    assert mode in ["fwd", "bwd", "fwd_bwd"]
    f = 4 * batch * seqlen**2 * nheads * headdim // (2 if causal else 1)
    return f if mode == "fwd" else (2.5 * f if mode == "bwd" else 3.5 * f)


def efficiency(flop, time):
    return (flop / time / 10**12) if not math.isnan(time) else 0.0
