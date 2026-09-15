
"""
Complete implementation of MLAWithDSA (Multi-Latent Attention with Dynamic Sparse Attention).
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from utils import RMSNorm, apply_rotary_pos_emb


class MLAWithDSA(nn.Module):
    """Multi-Latent Attention with Dynamic Sparse Attention for GLM-5-style models."""

    def __init__(self, config, layer_idx=0):
        super().__init__()
        self.layer_idx = layer_idx
        self.hidden_size = config["hidden_size"]
        self.num_heads = config["num_attention_heads"]
        self.q_lora_rank = config["q_lora_rank"]
        self.kv_lora_rank = config["kv_lora_rank"]
        self.qk_rope_head_dim = config["qk_rope_head_dim"]
        self.qk_nope_head_dim = config["qk_nope_head_dim"]
        self.qk_head_dim = config["qk_head_dim"]
        self.v_head_dim = config["v_head_dim"]
        self.idx_n_heads = config["index_n_heads"]
        self.idx_head_dim = config["index_head_dim"]
        self.idx_topk = config["index_topk"]
        self.rms_norm_eps = config["rms_norm_eps"]
        bias = config.get("attention_bias", False)

        # ---- MLA Query Path ----
        self.q_a_proj = nn.Linear(self.hidden_size, self.q_lora_rank, bias=bias)
        self.q_a_layernorm = RMSNorm(self.q_lora_rank, self.rms_norm_eps)
        self.q_b_proj = nn.Linear(
            self.q_lora_rank, self.num_heads * self.qk_head_dim, bias=bias
        )

        # ---- MLA KV Path ----
        self.kv_a_proj = nn.Linear(
            self.hidden_size, self.kv_lora_rank + self.qk_rope_head_dim, bias=bias
        )
        self.kv_a_layernorm = RMSNorm(self.kv_lora_rank, self.rms_norm_eps)
        self.kv_b_proj = nn.Linear(
            self.kv_lora_rank,
            self.num_heads * (self.qk_nope_head_dim + self.v_head_dim),
            bias=bias,
        )

        # ---- Output Projection ----
        self.o_proj = nn.Linear(
            self.num_heads * self.v_head_dim, self.hidden_size, bias=bias
        )

        # ---- DSA Indexer ----
        self.idx_wq = nn.Linear(
            self.q_lora_rank, self.idx_n_heads * self.idx_head_dim, bias=bias
        )
        self.idx_wk = nn.Linear(self.hidden_size, self.idx_head_dim, bias=bias)
        self.idx_k_norm = RMSNorm(self.idx_head_dim, self.rms_norm_eps)
        self.idx_weights_proj = nn.Linear(
            self.hidden_size, self.idx_n_heads, bias=bias
        )

        # Scaling factors
        self.attn_scale = self.qk_head_dim ** -0.5
        self.idx_scale = self.idx_head_dim ** -0.5

    def _compute_dsa_mask(self, q_compressed, hidden_states, cos, sin,
                          attention_mask, past_key_values, use_cache):
        """Compute DSA sparse attention mask via lightweight indexer."""
        B, S, _ = hidden_states.shape

        # ---- Indexer Query (from compressed query) ----
        idx_q = self.idx_wq(q_compressed)  # [B, S, n_idx * d_idx]
        idx_q = idx_q.view(B, S, self.idx_n_heads, self.idx_head_dim)
        idx_q_pe = idx_q[..., : self.qk_rope_head_dim]
        idx_q_nope = idx_q[..., self.qk_rope_head_dim :]
        idx_q_pe = apply_rotary_pos_emb(idx_q_pe, cos, sin)
        idx_q = torch.cat([idx_q_pe, idx_q_nope], dim=-1)

        # ---- Indexer Key (from hidden states) ----
        idx_k = self.idx_k_norm(self.idx_wk(hidden_states))  # [B, S, d_idx]
        idx_k_pe = idx_k[..., : self.qk_rope_head_dim]
        idx_k_nope = idx_k[..., self.qk_rope_head_dim :]
        idx_k_pe = apply_rotary_pos_emb(idx_k_pe.unsqueeze(2), cos, sin).squeeze(2)
        idx_k = torch.cat([idx_k_pe, idx_k_nope], dim=-1)

        # ---- Update Indexer Key Cache ----
        if use_cache:
            if past_key_values is not None and "idx_key" in past_key_values:
                idx_k_full = torch.cat([past_key_values["idx_key"], idx_k], dim=1)
            else:
                idx_k_full = idx_k
            if past_key_values is None:
                past_key_values = {}
            past_key_values["idx_key"] = idx_k_full
        else:
            idx_k_full = idx_k

        T = idx_k_full.shape[1]

        # ---- Per-Head Scoring ----
        scores = (
            torch.einsum("bshd,btd->bsht", idx_q.float(), idx_k_full.float())
            * self.idx_scale
        )
        scores = F.relu(scores)

        # ---- Weighted Sum Across Heads ----
        weights = self.idx_weights_proj(hidden_states).float() * (
            self.idx_n_heads ** -0.5
        )
        index_scores = torch.einsum("bsht,bsh->bst", scores, weights)

        # ---- Causal Masking Before Top-K ----
        if attention_mask is not None:
            causal_for_idx = attention_mask[:, 0, :, :T]  # [B, S, T]
            index_scores = index_scores + causal_for_idx

        # ---- Deterministic Top-K Selection ----
        actual_topk = min(self.idx_topk, T)
        topk_indices = index_scores.topk(actual_topk, dim=-1).indices

        # ---- Build Sparse Mask ----
        sparse_mask = torch.full(
            (B, S, T),
            float("-inf"),
            dtype=hidden_states.dtype,
            device=hidden_states.device,
        )
        sparse_mask.scatter_(-1, topk_indices, 0.0)
        sparse_mask = sparse_mask.unsqueeze(1)  # [B, 1, S, T]

        return sparse_mask, past_key_values

    def forward(self, hidden_states, position_ids, cos, sin,
                attention_mask=None, past_key_values=None, use_cache=False):
        B, S, _ = hidden_states.shape

        # ========== MLA Query Path ==========
        q_compressed = self.q_a_proj(hidden_states)
        q_compressed = self.q_a_layernorm(q_compressed)

        q = self.q_b_proj(q_compressed)  # [B, S, n_h * d_qk]
        q = q.view(B, S, self.num_heads, self.qk_head_dim)
        q_nope = q[..., : self.qk_nope_head_dim]
        q_rope = q[..., self.qk_nope_head_dim :]
        q_rope = apply_rotary_pos_emb(q_rope, cos, sin)
        q = torch.cat([q_nope, q_rope], dim=-1)
        q = q.transpose(1, 2)  # [B, n_h, S, d_qk]

        # ========== MLA KV Path ==========
        kv_combined = self.kv_a_proj(hidden_states)  # [B, S, r_kv + d_rope]
        kv_compressed = kv_combined[..., : self.kv_lora_rank]
        k_pe_raw = kv_combined[..., self.kv_lora_rank :]

        kv_compressed = self.kv_a_layernorm(kv_compressed)
        kv_expanded = self.kv_b_proj(kv_compressed)
        kv_expanded = kv_expanded.view(
            B, S, self.num_heads, self.qk_nope_head_dim + self.v_head_dim
        )
        k_nope = kv_expanded[..., : self.qk_nope_head_dim]
        v = kv_expanded[..., self.qk_nope_head_dim :]

        # Broadcast K_pe_raw across heads and apply RoPE
        k_pe = apply_rotary_pos_emb(
            k_pe_raw.unsqueeze(2).expand(-1, -1, self.num_heads, -1), cos, sin
        )
        k = torch.cat([k_nope, k_pe], dim=-1)  # [B, S, n_h, d_qk]

        k = k.transpose(1, 2)  # [B, n_h, S, d_qk]
        v = v.transpose(1, 2)  # [B, n_h, S, d_v]

        # ========== KV Cache ==========
        if use_cache:
            if past_key_values is not None and "key" in past_key_values:
                k = torch.cat([past_key_values["key"], k], dim=2)
                v = torch.cat([past_key_values["value"], v], dim=2)
            if past_key_values is None:
                past_key_values = {}
            past_key_values["key"] = k
            past_key_values["value"] = v

        # ========== DSA Sparse Mask ==========
        dsa_mask, past_key_values = self._compute_dsa_mask(
            q_compressed, hidden_states, cos, sin,
            attention_mask, past_key_values, use_cache,
        )

        # ========== Combined Mask ==========
        T = k.shape[2]
        if attention_mask is not None:
            combined_mask = attention_mask[:, :, :, :T] + dsa_mask
        else:
            combined_mask = dsa_mask

        # ========== Scaled Dot-Product Attention ==========
        attn_weights = torch.matmul(q, k.transpose(-2, -1)) * self.attn_scale
        attn_weights = attn_weights + combined_mask
        attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).to(
            q.dtype
        )
        attn_output = torch.matmul(attn_weights, v)  # [B, n_h, S, d_v]

        # ========== Output Projection ==========
        attn_output = attn_output.transpose(1, 2).contiguous().reshape(B, S, -1)
        output = self.o_proj(attn_output)

        if not use_cache:
            past_key_values = None

        return output, past_key_values
