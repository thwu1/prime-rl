"""KV Cache Memory Estimation for Transformer Models

Estimates the total GPU memory required to store the key-value
cache across all transformer layers during inference.
"""


DTYPE_BYTES_MAP = {
    "fp16": 2,
    "bf16": 2,
    "fp32": 4,
    "fp8": 1,
}


class KVCacheEstimator:
    """Estimates KV cache memory requirements."""

    def estimate(self, scenario):
        """Estimate total KV cache memory in bytes.

        The KV cache stores projected key and value tensors from
        previous tokens to avoid recomputation during autoregressive
        decoding. Memory is allocated across all layers and batch elements.

        Args:
            scenario: dict with model and sequence parameters.

        Returns:
            Total KV cache size in bytes.
        """
        b = scenario["batch_size"]
        h_kv = scenario["n_kv_heads"]
        lkv = scenario["seq_len_kv"]
        d = scenario["d_head"]
        n_layers = scenario["n_layers"]
        dtype_bytes = DTYPE_BYTES_MAP[scenario["dtype"]]
        # Cache stores tensors of shape [batch, n_kv_heads, seq_len, d_head]
        # for each layer in the specified precision
        return b * n_layers * h_kv * lkv * d * dtype_bytes
