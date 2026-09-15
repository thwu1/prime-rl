"""
Multi-Latent Attention (MLA) module for GLM-5.

MLA replaces standard multi-head attention with a compressed-latent design:

  Query path
  ----------
  hidden_states  -->  q_a_proj  -->  RMSNorm  -->  q_b_proj  -->  reshape to
  [B, S, hidden]    [B, S, q_lora_rank]          [B, S, H * qk_head_dim]
                                                       |
                                               split along last dim
                                               into q_nope and q_pe

  Key-Value path
  --------------
  hidden_states  -->  kv_a_proj_with_mqa  -->  split  -->  ...
  [B, S, hidden]    [B, S, kv_lora_rank + qk_rope_head_dim]
                          |                       |
                    k_compressed            k_pe (RoPE key stream,
                    [B, S, kv_lora_rank]     single-head, shared across
                          |                  all attention heads)
                      RMSNorm
                          |
                      kv_b_proj
                    [B, S, H * (qk_nope_head_dim + v_head_dim)]
                          |
                       reshape
                    [B, S, H, qk_nope_head_dim + v_head_dim]
                          |
                       split
                   k_nope     value

  Rotary position embedding is applied ONLY to q_pe and k_pe (the rope
  portions).  k_pe is a single-head stream that must be broadcast to all
  heads before concatenation with k_nope.

  Full keys are assembled as  cat(k_nope, k_pe_broadcast)  along the head
  dimension, giving  [B, S, H, qk_head_dim].

  Attention is standard scaled dot-product (scale = 1/sqrt(qk_head_dim))
  with a causal mask.  Output is projected back to hidden_size via o_proj.

  KV cache stores the fully assembled keys  [B, H, S, qk_head_dim]
  and values  [B, H, S, v_head_dim].

See glm5_config.py for all dimension parameters.

"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from glm5_config import GLM5Config
from utils import RMSNorm, apply_rotary_pos_emb


class MLAttention(nn.Module):
    """
    Multi-Latent Attention with compressed queries and key-values.

    Implement __init__ and forward.  The docstring above describes the
    data-flow; glm5_config.py provides all dimension constants.
    """

    def __init__(self, config: GLM5Config, layer_idx: int = 0):
        super().__init__()
        self.layer_idx = layer_idx
        self.config = config
        # TODO: define projection layers and normalization
        raise NotImplementedError(
            "Implement MLAttention.__init__  — define all projection layers "
            "and normalization.  See the module docstring and glm5_config.py."
        )

    def forward(
        self,
        hidden_states: torch.Tensor,
        attention_mask: torch.Tensor | None = None,
        position_embeddings: tuple[torch.Tensor, torch.Tensor] | None = None,
        past_key_value: tuple[torch.Tensor, torch.Tensor] | None = None,
        use_cache: bool = False,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor] | None]:
        """
        Args:
            hidden_states:      [batch, seq_len, hidden_size]
            attention_mask:     [1, 1, seq_len, total_len]  (0 = attend, -inf = mask)
            position_embeddings:(cos, sin) each [batch, seq_len, qk_rope_head_dim]
            past_key_value:     (cached_keys, cached_values) or None
            use_cache:          whether to return the updated cache

        Returns:
            (output, cache)
              output : [batch, seq_len, hidden_size]
              cache  : (keys, values) if use_cache else None
                       keys  : [batch, num_heads, total_len, qk_head_dim]
                       values: [batch, num_heads, total_len, v_head_dim]
        """
        # TODO: implement the forward pass
        raise NotImplementedError(
            "Implement MLAttention.forward  — see the module docstring."
        )
