"""
GLM-5 Multi-Latent Attention with Dynamic Sparse Attention — skeleton.

All projections and parameters are defined in __init__.

"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from config import GLM5Config
from rope import RotaryEmbedding, apply_rotary_pos_emb
from rmsnorm import RMSNorm


class MLADSAAttention(nn.Module):
    """
    Multi-Latent Attention with Dynamic Sparse Attention.

    All layer parameters and projections are defined in __init__.
    """

    def __init__(self, config: GLM5Config):
        super().__init__()
        self.config = config
        self.num_heads = config.num_attention_heads
        self.qk_head_dim = config.qk_head_dim
        self.qk_nope_head_dim = config.qk_nope_head_dim
        self.qk_rope_head_dim = config.qk_rope_head_dim
        self.v_head_dim = config.v_head_dim
        self.q_lora_rank = config.q_lora_rank
        self.kv_lora_rank = config.kv_lora_rank

        # === Query Projections (two-stage) ===
        self.q_a_proj = nn.Linear(config.hidden_size, config.q_lora_rank, bias=False)
        self.q_a_layernorm = RMSNorm(config.q_lora_rank, eps=config.rms_norm_eps)
        self.q_b_proj = nn.Linear(
            config.q_lora_rank, self.num_heads * self.qk_head_dim, bias=False
        )

        # === Key-Value Projections (shared compression) ===
        self.kv_a_proj_with_mqa = nn.Linear(
            config.hidden_size,
            config.kv_lora_rank + config.qk_rope_head_dim,
            bias=False,
        )
        self.kv_a_layernorm = RMSNorm(config.kv_lora_rank, eps=config.rms_norm_eps)
        self.kv_b_proj = nn.Linear(
            config.kv_lora_rank,
            self.num_heads * (self.qk_nope_head_dim + self.v_head_dim),
            bias=False,
        )

        # === Output Projection ===
        self.o_proj = nn.Linear(
            self.num_heads * self.v_head_dim, config.hidden_size, bias=False
        )

        # === DSA Indexer Projections ===
        self.dsa_wq_b = nn.Linear(
            config.q_lora_rank,
            config.index_n_heads * config.index_head_dim,
            bias=False,
        )
        self.dsa_wk = nn.Linear(config.hidden_size, config.index_head_dim, bias=False)
        self.dsa_k_norm = nn.LayerNorm(config.index_head_dim, eps=1e-6)
        self.dsa_weights_proj = nn.Linear(
            config.hidden_size, config.index_n_heads, bias=False
        )

        # === Rotary Embeddings ===
        self.rotary_emb = RotaryEmbedding(
            config.qk_rope_head_dim, config.max_position_embeddings, config.rope_theta
        )
        self.dsa_rotary_emb = RotaryEmbedding(
            config.index_head_dim // 2,
            config.max_position_embeddings,
            config.rope_theta,
        )

        # === Internal State ===
        self._dsa_key_cache = None

    def forward(
        self, hidden_states, position_ids=None, past_key_values=None, use_cache=False
    ):
        """
        Forward pass.

        Args:
            hidden_states: [batch, seq_len, hidden_size]
            position_ids: [batch, seq_len] position indices (auto-generated if None)
            past_key_values: optional (keys, values) cache tuple
            use_cache: whether to return updated cache

        Returns:
            output: [batch, seq_len, hidden_size]
            attn_weights: [batch, num_heads, seq_len, total_seq_len]
            cache: (keys, values) tuple if use_cache else None
        """
        raise NotImplementedError("forward")

    def _compute_dsa_mask(
        self, q_compressed, hidden_states, position_ids, seq_len, total_seq_len, bsz
    ):
        """
        Compute the dynamic sparse attention mask.

        Args:
            q_compressed: [batch, seq_len, q_lora_rank]
            hidden_states: [batch, seq_len, hidden_size]
            position_ids: [batch, seq_len]
            seq_len: current sequence length
            total_seq_len: total key sequence length (including cache)
            bsz: batch size

        Returns:
            mask: [batch, seq_len, total_seq_len] — additive mask
                  (-inf for blocked positions, 0.0 for allowed)
        """
        raise NotImplementedError("_compute_dsa_mask")
