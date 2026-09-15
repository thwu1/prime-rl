
"""
Skeleton for MLAWithDSA implementation.
Implement this class in /app/mla_dsa_attention.py.

Use utilities from /app/utils.py (RMSNorm, apply_rotary_pos_emb).

Required module attributes (use these exact names for all nn.Linear and RMSNorm):

    MLA Query path:
        q_a_proj      : Linear(hidden_size -> q_lora_rank, bias=attention_bias)
        q_a_layernorm : RMSNorm(q_lora_rank, rms_norm_eps)
        q_b_proj      : Linear(q_lora_rank -> num_attention_heads * qk_head_dim, bias=attention_bias)

    MLA KV path:
        kv_a_proj      : Linear(hidden_size -> kv_lora_rank + qk_rope_head_dim, bias=attention_bias)
        kv_a_layernorm : RMSNorm(kv_lora_rank, rms_norm_eps)
        kv_b_proj      : Linear(kv_lora_rank -> num_attention_heads * (qk_nope_head_dim + v_head_dim), bias=attention_bias)

    Output:
        o_proj : Linear(num_attention_heads * v_head_dim -> hidden_size, bias=attention_bias)

    DSA Indexer:
        idx_wq           : Linear(q_lora_rank -> index_n_heads * index_head_dim, bias=attention_bias)
        idx_wk           : Linear(hidden_size -> index_head_dim, bias=attention_bias)
        idx_k_norm       : RMSNorm(index_head_dim, rms_norm_eps)
        idx_weights_proj : Linear(hidden_size -> index_n_heads, bias=attention_bias)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from utils import RMSNorm, apply_rotary_pos_emb


class MLAWithDSA(nn.Module):
    """
    Multi-Latent Attention with Dynamic Sparse Attention.

    Args:
        config: dict — model configuration (see /app/config.py)
        layer_idx: int — layer index (default 0)

    forward(hidden_states, position_ids, cos, sin,
            attention_mask=None, past_key_values=None, use_cache=False)

        hidden_states : [B, S, hidden_size]
        position_ids  : [B, S] integer positions
        cos, sin      : [B, S, qk_rope_head_dim] from compute_rope_embeddings()
        attention_mask : [B, 1, S, T] causal mask (0=attend, -inf=block), or None
        past_key_values: dict with keys "key","value","idx_key", or None
        use_cache      : bool

        Returns: (output [B, S, hidden_size], updated past_key_values or None)

    _compute_dsa_mask(q_compressed, hidden_states, cos, sin,
                      attention_mask, past_key_values, use_cache)

        q_compressed : [B, S, q_lora_rank] — normalized compressed query
        Returns: (sparse_mask [B, 1, S, T], updated past_key_values)
    """

    def __init__(self, config, layer_idx=0):
        super().__init__()
        raise NotImplementedError("Implement the full MLAWithDSA module")

    def _compute_dsa_mask(self, q_compressed, hidden_states, cos, sin,
                          attention_mask, past_key_values, use_cache):
        raise NotImplementedError

    def forward(self, hidden_states, position_ids, cos, sin,
                attention_mask=None, past_key_values=None, use_cache=False):
        raise NotImplementedError
