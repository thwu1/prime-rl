"""
GLM-5 Multi-Latent Attention with Dynamic Sparse Attention — reference solution.

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

    MLA uses asymmetric LoRA-style compression for queries (higher rank)
    and key-values (lower rank), with partial RoPE applied only to a
    subset of head dimensions.

    DSA uses a lightweight multi-head indexer to score and select the
    top-k most relevant positions for each query, creating a sparse
    attention mask.
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

        # === MLA Query Projections (two-stage LoRA) ===
        self.q_a_proj = nn.Linear(config.hidden_size, config.q_lora_rank, bias=False)
        self.q_a_layernorm = RMSNorm(config.q_lora_rank, eps=config.rms_norm_eps)
        self.q_b_proj = nn.Linear(
            config.q_lora_rank, self.num_heads * self.qk_head_dim, bias=False
        )

        # === MLA Key-Value Projections (shared compression) ===
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

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------

    def forward(
        self, hidden_states, position_ids=None, past_key_values=None, use_cache=False
    ):
        bsz, seq_len, _ = hidden_states.shape

        # Auto-generate position_ids if not provided
        if position_ids is None:
            past_len = (
                past_key_values[0].shape[2] if past_key_values is not None else 0
            )
            position_ids = (
                torch.arange(past_len, past_len + seq_len, device=hidden_states.device)
                .unsqueeze(0)
                .expand(bsz, -1)
            )

        # ===================== MLA Query Path =====================
        q_compressed = self.q_a_proj(hidden_states)  # [B, S, q_lora_rank]
        q_compressed = self.q_a_layernorm(q_compressed)  # [B, S, q_lora_rank]

        q = self.q_b_proj(q_compressed)  # [B, S, H * qk_head_dim]
        q = q.view(bsz, seq_len, self.num_heads, self.qk_head_dim)
        q = q.transpose(1, 2)  # [B, H, S, qk_head_dim]

        q_nope, q_pe = q.split(
            [self.qk_nope_head_dim, self.qk_rope_head_dim], dim=-1
        )

        # ===================== MLA KV Path ========================
        kv_combined = self.kv_a_proj_with_mqa(
            hidden_states
        )  # [B, S, kv_lora_rank + rope_dim]
        kv_compressed, k_pe_raw = kv_combined.split(
            [self.kv_lora_rank, self.qk_rope_head_dim], dim=-1
        )

        kv_compressed = self.kv_a_layernorm(kv_compressed)  # [B, S, kv_lora_rank]
        kv = self.kv_b_proj(kv_compressed)  # [B, S, H * (nope + v)]
        kv = kv.view(
            bsz, seq_len, self.num_heads, self.qk_nope_head_dim + self.v_head_dim
        )

        k_nope, v = kv.split([self.qk_nope_head_dim, self.v_head_dim], dim=-1)
        k_nope = k_nope.transpose(1, 2)  # [B, H, S, nope]
        v = v.transpose(1, 2)  # [B, H, S, v]

        # ===================== RoPE ===============================
        # Shared positional key expanded to all heads
        k_pe = k_pe_raw.unsqueeze(1).expand(
            -1, self.num_heads, -1, -1
        )  # [B, H, S, rope]

        cos, sin = self.rotary_emb(position_ids)
        q_pe = apply_rotary_pos_emb(q_pe, cos, sin, unsqueeze_dim=1)
        k_pe = apply_rotary_pos_emb(k_pe, cos, sin, unsqueeze_dim=1)

        # ===================== Reassemble Q, K ====================
        q = torch.cat([q_nope, q_pe], dim=-1)  # [B, H, S, qk_head_dim]
        k = torch.cat([k_nope, k_pe], dim=-1)  # [B, H, S, qk_head_dim]

        # ===================== KV Cache ===========================
        if past_key_values is not None:
            past_k, past_v = past_key_values
            k = torch.cat([past_k, k], dim=2)
            v = torch.cat([past_v, v], dim=2)

        new_cache = (k, v) if use_cache else None
        total_seq_len = k.shape[2]

        # ===================== DSA Mask ===========================
        if total_seq_len > self.config.index_topk:
            dsa_mask = self._compute_dsa_mask(
                q_compressed, hidden_states, position_ids, seq_len, total_seq_len, bsz
            )
        else:
            dsa_mask = None

        # ===================== Attention ==========================
        scale = self.qk_head_dim ** -0.5
        attn_weights = torch.matmul(q, k.transpose(-2, -1)) * scale  # [B,H,S,T]

        # Causal mask
        causal_mask = torch.full(
            (seq_len, total_seq_len),
            float("-inf"),
            device=q.device,
            dtype=q.dtype,
        )
        causal_mask = torch.triu(causal_mask, diagonal=total_seq_len - seq_len + 1)
        attn_weights = attn_weights + causal_mask.unsqueeze(0).unsqueeze(0)

        # DSA mask (broadcast over heads)
        if dsa_mask is not None:
            attn_weights = attn_weights + dsa_mask.unsqueeze(1)

        attn_weights = F.softmax(attn_weights, dim=-1)

        # ===================== Output =============================
        attn_output = torch.matmul(attn_weights, v)  # [B, H, S, v_head_dim]
        attn_output = attn_output.transpose(1, 2).contiguous()
        attn_output = attn_output.reshape(bsz, seq_len, self.num_heads * self.v_head_dim)
        output = self.o_proj(attn_output)

        return output, attn_weights, new_cache

    # ------------------------------------------------------------------
    # DSA Indexer
    # ------------------------------------------------------------------

    def _compute_dsa_mask(
        self, q_compressed, hidden_states, position_ids, seq_len, total_seq_len, bsz
    ):
        cfg = self.config
        rope_dim = cfg.index_head_dim // 2

        # ============ Indexer Queries ============
        dsa_q = self.dsa_wq_b(q_compressed)  # [B, S, n_heads * head_dim]
        dsa_q = dsa_q.view(bsz, seq_len, cfg.index_n_heads, cfg.index_head_dim)
        dsa_q_nope, dsa_q_rope = dsa_q.split([rope_dim, rope_dim], dim=-1)

        # ============ Indexer Keys ===============
        dsa_k = self.dsa_wk(hidden_states)  # [B, S, head_dim]
        dsa_k = self.dsa_k_norm(dsa_k)
        dsa_k_nope, dsa_k_rope = dsa_k.split([rope_dim, rope_dim], dim=-1)

        # ============ RoPE ========================
        cos, sin = self.dsa_rotary_emb(position_ids)

        # Queries: [B, S, n_heads, rope_dim] — unsqueeze_dim=2
        dsa_q_rope = apply_rotary_pos_emb(dsa_q_rope, cos, sin, unsqueeze_dim=2)

        # Keys: [B, S, rope_dim] — add head dim for RoPE, then remove
        dsa_k_rope = dsa_k_rope.unsqueeze(2)  # [B, S, 1, rope_dim]
        dsa_k_rope = apply_rotary_pos_emb(dsa_k_rope, cos, sin, unsqueeze_dim=2)
        dsa_k_rope = dsa_k_rope.squeeze(2)  # [B, S, rope_dim]

        # ============ Reassemble ==================
        dsa_q = torch.cat([dsa_q_nope, dsa_q_rope], dim=-1)  # [B,S,n_heads,head_dim]
        dsa_k = torch.cat([dsa_k_nope, dsa_k_rope], dim=-1)  # [B,S,head_dim]

        # ============ Update DSA Key Cache ========
        if seq_len > 1 or self._dsa_key_cache is None:
            self._dsa_key_cache = dsa_k
        else:
            self._dsa_key_cache = torch.cat([self._dsa_key_cache, dsa_k], dim=1)

        all_keys = self._dsa_key_cache  # [B, T, head_dim]

        # ============ Per-head Scoring ============
        scale = cfg.index_head_dim ** -0.5
        # scores[b, s, t, n] = sum_d dsa_q[b,s,n,d] * all_keys[b,t,d]
        scores = torch.einsum("bsnd,btd->bstn", dsa_q, all_keys) * scale
        scores = F.relu(scores)

        # ============ Head Weighting ==============
        weights = self.dsa_weights_proj(hidden_states)  # [B, S, n_heads]
        weights = weights * (cfg.index_n_heads ** -0.5)

        # ============ Combine =====================
        index_scores = torch.einsum("bstn,bsn->bst", scores, weights)  # [B, S, T]

        # ============ Top-K =======================
        topk_indices = index_scores.topk(cfg.index_topk, dim=-1).indices

        # ============ Build Mask ==================
        dsa_mask = torch.full(
            (bsz, seq_len, total_seq_len),
            float("-inf"),
            device=hidden_states.device,
            dtype=hidden_states.dtype,
        )
        dsa_mask.scatter_(-1, topk_indices, 0.0)

        return dsa_mask
