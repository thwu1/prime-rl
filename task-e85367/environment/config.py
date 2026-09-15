
"""
Tiny GLM-5-style model configuration for CPU testing.
All dimensions are scaled down from the full 744B model.
"""

CONFIG = {
    # Core dimensions
    "hidden_size": 256,
    "num_attention_heads": 4,

    # MLA (Multi-Latent Attention) compression ranks
    "q_lora_rank": 128,       # Query compression bottleneck
    "kv_lora_rank": 64,       # KV compression bottleneck

    # Head dimensions
    "qk_rope_head_dim": 16,   # RoPE-applied portion of Q/K heads
    "qk_nope_head_dim": 48,   # Non-RoPE portion of Q/K heads
    "qk_head_dim": 64,        # Total Q/K head dim (= nope + rope)
    "v_head_dim": 64,         # Value head dimension
    "num_key_value_heads": 4,  # MLA uses same count as query heads

    # DSA (Dynamic Sparse Attention) indexer
    "index_n_heads": 2,       # Lightweight scoring heads
    "index_head_dim": 32,     # Dimension per scoring head
    "index_topk": 8,          # Max tokens selected per query position

    # Normalization and positional encoding
    "rms_norm_eps": 1e-5,
    "rope_theta": 10000.0,
    "max_position_embeddings": 2048,

    # Bias
    "attention_bias": False,
}
