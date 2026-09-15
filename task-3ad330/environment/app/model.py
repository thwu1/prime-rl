"""
Simple transformer model built on MLA for integration testing.

"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from glm5_config import GLM5Config
from utils import RMSNorm, RotaryEmbedding, make_causal_mask
from mla_attention import MLAttention


class FeedForward(nn.Module):
    """SwiGLU feed-forward network."""

    def __init__(self, hidden_size: int, intermediate_size: int):
        super().__init__()
        self.gate_proj = nn.Linear(hidden_size, intermediate_size, bias=False)
        self.up_proj = nn.Linear(hidden_size, intermediate_size, bias=False)
        self.down_proj = nn.Linear(intermediate_size, hidden_size, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class TransformerBlock(nn.Module):
    """Pre-norm transformer block with MLA + SwiGLU."""

    def __init__(self, config: GLM5Config, layer_idx: int):
        super().__init__()
        self.input_layernorm = RMSNorm(config.hidden_size, config.rms_norm_eps)
        self.attention = MLAttention(config, layer_idx)
        self.post_attention_layernorm = RMSNorm(
            config.hidden_size, config.rms_norm_eps
        )
        self.mlp = FeedForward(config.hidden_size, config.dense_intermediate_size)

    def forward(
        self,
        hidden_states: torch.Tensor,
        attention_mask: torch.Tensor,
        position_embeddings: tuple,
        past_key_value=None,
        use_cache: bool = False,
    ):
        residual = hidden_states
        hidden_states = self.input_layernorm(hidden_states)
        hidden_states, cache = self.attention(
            hidden_states,
            attention_mask,
            position_embeddings,
            past_key_value,
            use_cache,
        )
        hidden_states = residual + hidden_states

        residual = hidden_states
        hidden_states = self.post_attention_layernorm(hidden_states)
        hidden_states = self.mlp(hidden_states)
        hidden_states = residual + hidden_states

        return hidden_states, cache


class SimpleGLM5(nn.Module):
    """Minimal causal LM using MLA attention blocks."""

    def __init__(self, config: GLM5Config):
        super().__init__()
        self.config = config
        self.embed_tokens = nn.Embedding(config.vocab_size, config.hidden_size)
        self.layers = nn.ModuleList(
            [TransformerBlock(config, i) for i in range(config.num_hidden_layers)]
        )
        self.norm = RMSNorm(config.hidden_size, config.rms_norm_eps)
        self.lm_head = nn.Linear(config.hidden_size, config.vocab_size, bias=False)
        self.rotary_emb = RotaryEmbedding(config.qk_rope_head_dim, config.rope_theta)

    def forward(
        self,
        input_ids: torch.Tensor,
        labels: torch.Tensor | None = None,
        past_key_values: list | None = None,
        use_cache: bool = False,
    ):
        B, S = input_ids.shape
        hidden_states = self.embed_tokens(input_ids)

        # Determine past length for position ids and mask
        past_len = 0
        if past_key_values is not None and past_key_values[0] is not None:
            past_len = past_key_values[0][0].shape[2]

        position_ids = torch.arange(
            past_len, past_len + S, device=input_ids.device
        ).unsqueeze(0)
        position_embeddings = self.rotary_emb(hidden_states, position_ids)

        total_len = past_len + S
        attention_mask = make_causal_mask(
            S, total_len, hidden_states.dtype, hidden_states.device
        )

        new_caches: list = []
        for i, layer in enumerate(self.layers):
            past_kv = past_key_values[i] if past_key_values is not None else None
            hidden_states, cache = layer(
                hidden_states,
                attention_mask,
                position_embeddings,
                past_kv,
                use_cache,
            )
            new_caches.append(cache)

        hidden_states = self.norm(hidden_states)
        logits = self.lm_head(hidden_states)

        loss = None
        if labels is not None:
            loss = F.cross_entropy(
                logits.view(-1, self.config.vocab_size), labels.view(-1)
            )

        cache_out = new_caches if use_cache else None
        return loss, logits, cache_out
