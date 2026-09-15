
"""
KV-cached autoregressive generation for a GQA+RoPE transformer.

Implements efficient inference by caching key-value pairs from previous
positions, avoiding redundant recomputation during autoregressive decoding.
Handles the asymmetry between query heads (n_heads=8) and KV heads
(n_kv_groups=2) inherent in Grouped Query Attention, and correctly tracks
absolute positions for Rotary Position Embeddings across prefill and
decode phases.
"""

import math
import torch


class KVCache:
    """Per-layer key-value cache for autoregressive generation."""

    def __init__(self, n_layers):
        self.n_layers = n_layers
        self._cache = {}

    def update(self, layer_idx, new_keys, new_values):
        """
        Append new K,V to the cache for a given layer and return the full K,V.

        Args:
            layer_idx: transformer layer index
            new_keys:   (batch, n_kv_groups, new_len, head_dim) — post-RoPE
            new_values: (batch, n_kv_groups, new_len, head_dim)

        Returns:
            (full_keys, full_values) with all cached entries concatenated
        """
        if layer_idx in self._cache:
            prev_k, prev_v = self._cache[layer_idx]
            keys = torch.cat([prev_k, new_keys], dim=2)
            values = torch.cat([prev_v, new_values], dim=2)
        else:
            keys, values = new_keys, new_values
        self._cache[layer_idx] = (keys, values)
        return keys, values

    def reset(self):
        self._cache.clear()


def _apply_rope_at_pos(x, cos, sin, start_pos):
    """
    Apply Rotary Position Embeddings starting at absolute position start_pos.

    Unlike the base model's apply_rope (which always starts at position 0),
    this slices cos/sin at the correct offset so that tokens processed during
    the decode phase receive the right positional encoding.
    """
    _, _, seq_len, head_dim = x.shape
    half = head_dim // 2
    x1 = x[..., :half]
    x2 = x[..., half:]
    c = cos[start_pos:start_pos + seq_len, :].unsqueeze(0).unsqueeze(0)
    s = sin[start_pos:start_pos + seq_len, :].unsqueeze(0).unsqueeze(0)
    rotated = torch.cat((-x2, x1), dim=-1)
    return (x * c) + (rotated * s)


def _cached_layer_forward(layer, x, cos, sin, start_pos, kv_cache, layer_idx):
    """Forward one transformer block with KV caching."""
    b, seq_len, _ = x.shape
    attn = layer.attn

    # Pre-attention normalization
    x_norm = layer.norm1(x)

    # Project Q, K, V
    q = attn.W_query(x_norm).view(b, seq_len, attn.n_heads, attn.head_dim).transpose(1, 2)
    k = attn.W_key(x_norm).view(b, seq_len, attn.n_kv_groups, attn.head_dim).transpose(1, 2)
    v = attn.W_value(x_norm).view(b, seq_len, attn.n_kv_groups, attn.head_dim).transpose(1, 2)

    # Apply RoPE at the correct absolute positions
    q = _apply_rope_at_pos(q, cos, sin, start_pos)
    k = _apply_rope_at_pos(k, cos, sin, start_pos)

    # Update cache with post-RoPE keys and values
    # Cache stores (batch, n_kv_groups, cached_len, head_dim) — NOT n_heads
    k_all, v_all = kv_cache.update(layer_idx, k, v)
    total_len = k_all.shape[2]

    # Expand KV groups to match query head count for attention
    k_exp = k_all.repeat_interleave(attn.group_size, dim=1)
    v_exp = v_all.repeat_interleave(attn.group_size, dim=1)

    # Scaled dot-product attention
    scores = q @ k_exp.transpose(2, 3) / math.sqrt(attn.head_dim)

    # Causal mask: only needed during prefill (seq_len > 1).
    # During single-token decode, the new token can attend to all cached
    # positions (it is the latest token, so no future positions exist).
    if seq_len > 1:
        causal_mask = torch.triu(
            torch.ones(seq_len, total_len, device=x.device, dtype=torch.bool),
            diagonal=total_len - seq_len + 1,
        )
        scores = scores.masked_fill(causal_mask, float("-inf"))

    weights = torch.softmax(scores, dim=-1)
    context = (weights @ v_exp).transpose(1, 2).reshape(b, seq_len, -1)
    attn_out = attn.out_proj(context)

    # Residual connections + feed-forward
    x = x + attn_out
    x = x + layer.ff(layer.norm2(x))
    return x


def _cached_model_forward(model, input_ids, kv_cache, start_pos):
    """Full model forward pass with KV caching."""
    x = model.tok_emb(input_ids)
    for idx, layer in enumerate(model.layers):
        x = _cached_layer_forward(
            layer, x, model.cos, model.sin, start_pos, kv_cache, idx
        )
    x = model.norm(x)
    return model.out_head(x)


def generate_cached(model, input_ids, max_new_tokens, kv_cache=None):
    """
    Autoregressive generation with KV caching.

    Produces token-for-token identical output to generate_simple but avoids
    recomputing key-value pairs for previously processed tokens.

    Args:
        model:          LLMModel instance
        input_ids:      (batch, prompt_len) tensor of token IDs
        max_new_tokens: number of new tokens to generate
        kv_cache:       optional pre-existing KVCache (for advanced usage)

    Returns:
        (batch, prompt_len + max_new_tokens) tensor of token IDs
    """
    if max_new_tokens == 0:
        return input_ids

    model.eval()
    if kv_cache is None:
        kv_cache = KVCache(model.cfg["n_layers"])

    with torch.no_grad():
        # ── Prefill: process the entire prompt in one pass ──
        prompt_len = input_ids.shape[1]
        logits = _cached_model_forward(model, input_ids, kv_cache, start_pos=0)
        next_token = logits[:, -1, :].argmax(dim=-1, keepdim=True)
        input_ids = torch.cat([input_ids, next_token], dim=1)

        # ── Decode: generate remaining tokens one at a time ──
        for step in range(max_new_tokens - 1):
            pos = prompt_len + step
            logits = _cached_model_forward(model, next_token, kv_cache, start_pos=pos)
            next_token = logits[:, -1, :].argmax(dim=-1, keepdim=True)
            input_ids = torch.cat([input_ids, next_token], dim=1)

    return input_ids
