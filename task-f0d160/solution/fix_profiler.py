#!/usr/bin/env python3
"""
Fix all bugs in the GPU attention kernel performance profiler.

Bugs span C (roofline_core.c) and Python (attention.py, kv_cache.py).
After running this script, libroofline.so must be rebuilt with make.

"""

# Fix 1: roofline_core.c
# Bug A: gb_to_bytes uses 1073741824.0 (GiB = 1024^3) instead of 1e9 (GB)
# Bug B: achievable_flops uses addition instead of fmin()
ROOFLINE_C_FIXED = '''\
#include <math.h>

double gb_to_bytes(double gb) {
    return gb * 1e9;
}

double achievable_flops(double arithmetic_intensity,
                        double bandwidth_bytes,
                        double peak_flops) {
    double mem_bound = arithmetic_intensity * bandwidth_bytes;
    return fmin(mem_bound, peak_flops);
}

double compute_ridge_point(double peak_flops, double bandwidth_bytes) {
    return peak_flops / bandwidth_bytes;
}
'''

# Fix 2: attention.py
# Bug C: FMA counted as 1 FLOP instead of 2 (missing factor of 2)
# Bug D: K/V memory uses n_heads instead of n_kv_heads
# Bug E: critical prefill formula is wrong (missing (h+h_kv)/(2*h) terms)
# Bug F: group size sweep includes non-divisor group sizes
ATTENTION_FIXED = '''\
"""Transformer Attention Kernel Performance Analysis"""
import math

DTYPE_BYTES_MAP = {"fp16": 2, "bf16": 2, "fp32": 4, "fp8": 1}


class AttentionAnalyzer:
    def _get_dtype_bytes(self, dtype_str):
        return DTYPE_BYTES_MAP[dtype_str]

    def compute_flops(self, scenario):
        b = scenario["batch_size"]
        h = scenario["n_heads"]
        lq = scenario["seq_len_q"]
        lkv = scenario["seq_len_kv"]
        d = scenario["d_head"]
        # Each multiply-add counts as 2 FLOPs
        qk_ops = 2 * b * h * lq * lkv * d
        sv_ops = 2 * b * h * lq * lkv * d
        return qk_ops + sv_ops

    def compute_memory_bytes(self, scenario):
        b = scenario["batch_size"]
        h = scenario["n_heads"]
        h_kv = scenario["n_kv_heads"]
        lq = scenario["seq_len_q"]
        lkv = scenario["seq_len_kv"]
        d = scenario["d_head"]
        dtype_bytes = self._get_dtype_bytes(scenario["dtype"])
        q_bytes = b * h * lq * d * dtype_bytes
        k_bytes = b * h_kv * lkv * d * dtype_bytes
        v_bytes = b * h_kv * lkv * d * dtype_bytes
        o_bytes = b * h * lq * d * dtype_bytes
        return q_bytes + k_bytes + v_bytes + o_bytes

    def analyze(self, scenario, roofline):
        flops = self.compute_flops(scenario)
        mem_bytes = self.compute_memory_bytes(scenario)
        ai = flops / mem_bytes
        return {
            "attention_flops": flops,
            "attention_memory_bytes": mem_bytes,
            "arithmetic_intensity": ai,
            "roofline_tflops": roofline.achievable_tflops(ai),
            "is_memory_bound": roofline.is_memory_bound(ai),
        }

    def find_critical_prefill_length(self, params, roofline):
        h = params["n_heads"]
        h_kv = params["n_kv_heads"]
        d = params["d_head"]
        dtype_bytes = self._get_dtype_bytes(params["dtype"])
        ridge = roofline.ridge_point()
        # For prefill: lq=lkv=L, b=1
        # AI(L) = 2*h*L / (dtype*(h + h_kv))
        # Solve AI >= ridge => L >= ridge*dtype*(h+h_kv)/(2*h)
        min_L_exact = ridge * dtype_bytes * (h + h_kv) / (2 * h)
        return math.ceil(min_L_exact)

    def group_size_sweep(self, params, roofline):
        h = params["n_heads"]
        d = params["d_head"]
        dtype_str = params["dtype"]
        lkv = params["seq_len_kv"]
        result = {}
        for g in range(1, h + 1):
            if h % g != 0:
                continue
            h_kv = h // g
            scenario = {
                "batch_size": 1, "n_heads": h, "n_kv_heads": h_kv,
                "seq_len_q": 1, "seq_len_kv": lkv, "d_head": d, "dtype": dtype_str,
            }
            analysis = self.analyze(scenario, roofline)
            result[str(g)] = analysis["arithmetic_intensity"]
        return result
'''

# Fix 3: kv_cache.py
# Bug G: missing factor of 2 (only counts K, not K+V)
KV_CACHE_FIXED = '''\
"""KV Cache Memory Estimation for Transformer Models"""

DTYPE_BYTES_MAP = {"fp16": 2, "bf16": 2, "fp32": 4, "fp8": 1}


class KVCacheEstimator:
    def estimate(self, scenario):
        b = scenario["batch_size"]
        h_kv = scenario["n_kv_heads"]
        lkv = scenario["seq_len_kv"]
        d = scenario["d_head"]
        n_layers = scenario["n_layers"]
        dtype_bytes = DTYPE_BYTES_MAP[scenario["dtype"]]
        # Factor of 2 for both key and value tensors
        return 2 * b * n_layers * h_kv * lkv * d * dtype_bytes
'''

if __name__ == "__main__":
    with open("/app/roofline_core.c", "w") as f:
        f.write(ROOFLINE_C_FIXED)
    print("Fixed roofline_core.c")

    with open("/app/attention.py", "w") as f:
        f.write(ATTENTION_FIXED)
    print("Fixed attention.py")

    with open("/app/kv_cache.py", "w") as f:
        f.write(KV_CACHE_FIXED)
    print("Fixed kv_cache.py")

    print("All bugs fixed. Rebuild libroofline.so with: cd /app && make clean && make")
