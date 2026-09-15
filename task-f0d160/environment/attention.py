"""Transformer Attention Kernel Performance Analysis

Computes FLOPs, memory access, and arithmetic intensity for
multi-head, grouped-query, and multi-query attention variants.
"""
import math


DTYPE_BYTES_MAP = {
    "fp16": 2,
    "bf16": 2,
    "fp32": 4,
    "fp8": 1,
}


class AttentionAnalyzer:
    """Analyzes attention kernel performance characteristics."""

    def _get_dtype_bytes(self, dtype_str):
        """Map dtype string to byte width."""
        return DTYPE_BYTES_MAP[dtype_str]

    def compute_flops(self, scenario):
        """Compute total floating-point operations for attention.

        Attention consists of two matrix multiplications:
        1) QK^T: (b, h, lq, d) x (b, h, d, lkv) -> scores
        2) scores x V: (b, h, lq, lkv) x (b, h, lkv, d) -> output

        Each element of the output matrices requires d multiply-accumulate
        operations along the contraction dimension.
        """
        b = scenario["batch_size"]
        h = scenario["n_heads"]
        lq = scenario["seq_len_q"]
        lkv = scenario["seq_len_kv"]
        d = scenario["d_head"]
        # QK^T matmul: b * h * lq * lkv multiply-accumulate ops, each over d
        qk_ops = b * h * lq * lkv * d
        # Score-value matmul: b * h * lq * d multiply-accumulate ops, each over lkv
        sv_ops = b * h * lq * d * lkv
        return qk_ops + sv_ops

    def compute_memory_bytes(self, scenario):
        """Compute total HBM bytes accessed for one attention layer.

        Reads Q, K, V from HBM and writes output O back.
        All tensors use the specified dtype precision.
        """
        b = scenario["batch_size"]
        h = scenario["n_heads"]
        h_kv = scenario["n_kv_heads"]
        lq = scenario["seq_len_q"]
        lkv = scenario["seq_len_kv"]
        d = scenario["d_head"]
        dtype_bytes = self._get_dtype_bytes(scenario["dtype"])
        # Q tensor: one per query head
        q_bytes = b * h * lq * d * dtype_bytes
        # K tensor: one per attention head
        k_bytes = b * h * lkv * d * dtype_bytes
        # V tensor: one per attention head
        v_bytes = b * h * lkv * d * dtype_bytes
        # Output tensor: one per query head
        o_bytes = b * h * lq * d * dtype_bytes
        return q_bytes + k_bytes + v_bytes + o_bytes

    def analyze(self, scenario, roofline):
        """Run full performance analysis for a single attention scenario."""
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
        """Find minimum sequence length where prefill becomes compute-bound.

        For prefill, seq_len_q = seq_len_kv = L with batch_size = 1.
        Returns the smallest integer L such that the attention kernel's
        arithmetic intensity meets or exceeds the hardware ridge point.
        """
        h = params["n_heads"]
        h_kv = params["n_kv_heads"]
        d = params["d_head"]
        dtype_bytes = self._get_dtype_bytes(params["dtype"])
        ridge = roofline.ridge_point()
        # Solve for L where AI(L) >= ridge
        critical_L = int(ridge * dtype_bytes * 2)
        return critical_L

    def group_size_sweep(self, params, roofline):
        """Compute decode-phase arithmetic intensity across GQA group sizes.

        For each group size g (where g = n_heads / n_kv_heads), compute
        the arithmetic intensity during autoregressive decoding (seq_len_q=1).
        """
        h = params["n_heads"]
        d = params["d_head"]
        dtype_str = params["dtype"]
        lkv = params["seq_len_kv"]
        result = {}
        for g in range(1, h + 1):
            h_kv = h // g
            scenario = {
                "batch_size": 1,
                "n_heads": h,
                "n_kv_heads": h_kv,
                "seq_len_q": 1,
                "seq_len_kv": lkv,
                "d_head": d,
                "dtype": dtype_str,
            }
            analysis = self.analyze(scenario, roofline)
            result[str(g)] = analysis["arithmetic_intensity"]
        return result
