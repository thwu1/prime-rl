#!/usr/bin/env python3
"""
Derive and write the correct MLAttention implementation for GLM-5.

Reads the config to determine exact projection dimensions, then generates
the complete MLA module and writes it to /app/mla_attention.py.

"""

import sys

sys.path.insert(0, "/app")
from glm5_config import GLM5Config

config = GLM5Config()

# Derive all projection dimensions from config
q_a_in = config.hidden_size
q_a_out = config.q_lora_rank
q_b_in = config.q_lora_rank
q_b_out = config.num_attention_heads * config.qk_head_dim

kv_a_in = config.hidden_size
kv_a_out = config.kv_lora_rank + config.qk_rope_head_dim

kv_b_in = config.kv_lora_rank
kv_b_out = config.num_attention_heads * (config.qk_nope_head_dim + config.v_head_dim)

o_in = config.num_attention_heads * config.v_head_dim
o_out = config.hidden_size

print(f"Derived MLA projection dimensions from config:")
print(f"  q_a_proj:            {q_a_in} -> {q_a_out}")
print(f"  q_b_proj:            {q_b_in} -> {q_b_out}")
print(f"  kv_a_proj_with_mqa:  {kv_a_in} -> {kv_a_out}")
print(f"  kv_b_proj:           {kv_b_in} -> {kv_b_out}")
print(f"  o_proj:              {o_in} -> {o_out}")

implementation = '''"""
Multi-Latent Attention (MLA) module for GLM-5.

"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from glm5_config import GLM5Config
from utils import RMSNorm, apply_rotary_pos_emb


class MLAttention(nn.Module):
    """Multi-Latent Attention with compressed queries and key-values."""

    def __init__(self, config: GLM5Config, layer_idx: int = 0):
        super().__init__()
        self.layer_idx = layer_idx
        self.config = config
        self.hidden_size = config.hidden_size
        self.num_heads = config.num_attention_heads
        self.qk_nope_head_dim = config.qk_nope_head_dim
        self.qk_rope_head_dim = config.qk_rope_head_dim
        self.qk_head_dim = config.qk_head_dim
        self.v_head_dim = config.v_head_dim
        self.q_lora_rank = config.q_lora_rank
        self.kv_lora_rank = config.kv_lora_rank

        # Query LoRA compression: hidden -> q_lora_rank -> num_heads * qk_head_dim
        self.q_a_proj = nn.Linear(self.hidden_size, self.q_lora_rank, bias=False)
        self.q_a_layernorm = RMSNorm(self.q_lora_rank, config.rms_norm_eps)
        self.q_b_proj = nn.Linear(
            self.q_lora_rank, self.num_heads * self.qk_head_dim, bias=False
        )

        # Shared KV compression: hidden -> (kv_lora_rank + qk_rope_head_dim)
        self.kv_a_proj_with_mqa = nn.Linear(
            self.hidden_size, self.kv_lora_rank + self.qk_rope_head_dim, bias=False
        )
        self.kv_a_layernorm = RMSNorm(self.kv_lora_rank, config.rms_norm_eps)
        # KV expansion: kv_lora_rank -> num_heads * (qk_nope_head_dim + v_head_dim)
        self.kv_b_proj = nn.Linear(
            self.kv_lora_rank,
            self.num_heads * (self.qk_nope_head_dim + self.v_head_dim),
            bias=False,
        )

        # Output projection
        self.o_proj = nn.Linear(
            self.num_heads * self.v_head_dim, self.hidden_size, bias=False
        )

        self.scaling = self.qk_head_dim ** -0.5

    def forward(
        self,
        hidden_states,
        attention_mask=None,
        position_embeddings=None,
        past_key_value=None,
        use_cache=False,
    ):
        B, S, _ = hidden_states.shape

        # ---- Query path: compress -> normalize -> expand -> split ----
        q = self.q_a_proj(hidden_states)          # [B, S, q_lora_rank]
        q = self.q_a_layernorm(q)
        q = self.q_b_proj(q)                      # [B, S, H * qk_head_dim]
        q = q.view(B, S, self.num_heads, self.qk_head_dim)
        q_nope, q_pe = q.split(
            [self.qk_nope_head_dim, self.qk_rope_head_dim], dim=-1
        )

        # ---- KV path: compress -> split latent/rope -> norm -> expand -> split ----
        kv_compressed = self.kv_a_proj_with_mqa(hidden_states)
        k_compressed, k_pe = kv_compressed.split(
            [self.kv_lora_rank, self.qk_rope_head_dim], dim=-1
        )
        k_compressed = self.kv_a_layernorm(k_compressed)  # [B, S, kv_lora_rank]
        kv_expanded = self.kv_b_proj(k_compressed)
        kv_expanded = kv_expanded.view(
            B, S, self.num_heads, self.qk_nope_head_dim + self.v_head_dim
        )
        k_nope, v = kv_expanded.split(
            [self.qk_nope_head_dim, self.v_head_dim], dim=-1
        )

        # ---- Apply RoPE to rope portions only ----
        cos, sin = position_embeddings
        q_pe = apply_rotary_pos_emb(q_pe, cos, sin, unsqueeze_dim=2)
        # k_pe is single-head: [B, S, rope_dim] -> [B, S, 1, rope_dim]
        k_pe = k_pe.unsqueeze(2)
        k_pe = apply_rotary_pos_emb(k_pe, cos, sin, unsqueeze_dim=2)
        # Broadcast to all heads
        k_pe = k_pe.expand(-1, -1, self.num_heads, -1)

        # ---- Assemble full Q and K ----
        q = torch.cat([q_nope, q_pe], dim=-1)  # [B, S, H, qk_head_dim]
        k = torch.cat([k_nope, k_pe], dim=-1)  # [B, S, H, qk_head_dim]

        # Transpose to [B, H, S, D] for attention
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)

        # ---- KV cache ----
        if past_key_value is not None:
            k = torch.cat([past_key_value[0], k], dim=2)
            v = torch.cat([past_key_value[1], v], dim=2)
        cache = (k, v) if use_cache else None

        # ---- Scaled dot-product attention ----
        attn_weights = torch.matmul(q, k.transpose(-2, -1)) * self.scaling
        if attention_mask is not None:
            attn_weights = attn_weights + attention_mask
        attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).to(
            q.dtype
        )
        attn_output = torch.matmul(attn_weights, v)  # [B, H, S, v_head_dim]

        # ---- Output projection ----
        attn_output = attn_output.transpose(1, 2).contiguous()
        attn_output = attn_output.view(B, S, self.num_heads * self.v_head_dim)
        attn_output = self.o_proj(attn_output)

        return attn_output, cache
'''

with open("/app/mla_attention.py", "w") as f:
    f.write(implementation)

print("MLA implementation written to /app/mla_attention.py")
