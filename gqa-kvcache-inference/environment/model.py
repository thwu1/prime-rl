
"""
Transformer model with Grouped Query Attention (GQA) and Rotary Position Embeddings (RoPE).
Uses SwiGLU feed-forward and RMSNorm.
"""
import math
import torch
import torch.nn as nn


MODEL_CONFIG = {
    "vocab_size": 512,
    "context_length": 256,
    "emb_dim": 128,
    "n_heads": 8,
    "n_kv_groups": 2,
    "n_layers": 4,
    "hidden_dim": 512,
    "rope_base": 10000.0,
}


class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        rms = torch.sqrt(x.pow(2).mean(dim=-1, keepdim=True) + self.eps)
        return x / rms * self.weight


class FeedForward(nn.Module):
    """SwiGLU feed-forward network."""
    def __init__(self, cfg):
        super().__init__()
        self.gate_proj = nn.Linear(cfg["emb_dim"], cfg["hidden_dim"], bias=False)
        self.up_proj = nn.Linear(cfg["emb_dim"], cfg["hidden_dim"], bias=False)
        self.down_proj = nn.Linear(cfg["hidden_dim"], cfg["emb_dim"], bias=False)

    def forward(self, x):
        return self.down_proj(nn.functional.silu(self.gate_proj(x)) * self.up_proj(x))


def compute_rope(head_dim, theta_base, context_length):
    """Precompute cos and sin tables for Rotary Position Embeddings."""
    assert head_dim % 2 == 0, "head_dim must be even"
    inv_freq = 1.0 / (theta_base ** (torch.arange(0, head_dim, 2).float() / head_dim))
    positions = torch.arange(context_length).float()
    angles = positions.unsqueeze(1) * inv_freq.unsqueeze(0)  # (context_length, head_dim/2)
    angles = torch.cat([angles, angles], dim=1)  # (context_length, head_dim)
    return torch.cos(angles), torch.sin(angles)


def apply_rope(x, cos, sin):
    """Apply rotary position embeddings using split-halves style."""
    batch_size, num_heads, seq_len, head_dim = x.shape
    assert head_dim % 2 == 0
    x1 = x[..., :head_dim // 2]
    x2 = x[..., head_dim // 2:]
    cos = cos[:seq_len, :].unsqueeze(0).unsqueeze(0)  # (1, 1, seq_len, head_dim)
    sin = sin[:seq_len, :].unsqueeze(0).unsqueeze(0)
    rotated = torch.cat((-x2, x1), dim=-1)
    return (x * cos) + (rotated * sin)


class GroupedQueryAttention(nn.Module):
    """
    Grouped Query Attention: keys and values use fewer heads (n_kv_groups)
    than queries (n_heads). Each KV group serves (n_heads // n_kv_groups) query heads.
    """
    def __init__(self, cfg):
        super().__init__()
        emb_dim = cfg["emb_dim"]
        n_heads = cfg["n_heads"]
        n_kv_groups = cfg["n_kv_groups"]

        assert emb_dim % n_heads == 0
        assert n_heads % n_kv_groups == 0

        self.head_dim = emb_dim // n_heads
        self.n_heads = n_heads
        self.n_kv_groups = n_kv_groups
        self.group_size = n_heads // n_kv_groups

        self.W_query = nn.Linear(emb_dim, emb_dim, bias=False)
        self.W_key = nn.Linear(emb_dim, n_kv_groups * self.head_dim, bias=False)
        self.W_value = nn.Linear(emb_dim, n_kv_groups * self.head_dim, bias=False)
        self.out_proj = nn.Linear(emb_dim, emb_dim, bias=False)

    def forward(self, x, cos, sin, mask):
        b, seq_len, _ = x.shape

        q = self.W_query(x).view(b, seq_len, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.W_key(x).view(b, seq_len, self.n_kv_groups, self.head_dim).transpose(1, 2)
        v = self.W_value(x).view(b, seq_len, self.n_kv_groups, self.head_dim).transpose(1, 2)

        q = apply_rope(q, cos, sin)
        k = apply_rope(k, cos, sin)

        # Expand KV groups to match query head count
        k = k.repeat_interleave(self.group_size, dim=1)
        v = v.repeat_interleave(self.group_size, dim=1)

        attn_scores = q @ k.transpose(2, 3) / math.sqrt(self.head_dim)
        attn_scores = attn_scores.masked_fill(mask[:seq_len, :seq_len], float('-inf'))
        attn_weights = torch.softmax(attn_scores, dim=-1)

        context = (attn_weights @ v).transpose(1, 2).reshape(b, seq_len, -1)
        return self.out_proj(context)


class TransformerBlock(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.attn = GroupedQueryAttention(cfg)
        self.ff = FeedForward(cfg)
        self.norm1 = RMSNorm(cfg["emb_dim"])
        self.norm2 = RMSNorm(cfg["emb_dim"])

    def forward(self, x, cos, sin, mask):
        x = x + self.attn(self.norm1(x), cos, sin, mask)
        x = x + self.ff(self.norm2(x))
        return x


class LLMModel(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.tok_emb = nn.Embedding(cfg["vocab_size"], cfg["emb_dim"])
        self.layers = nn.ModuleList(
            [TransformerBlock(cfg) for _ in range(cfg["n_layers"])]
        )
        self.norm = RMSNorm(cfg["emb_dim"])
        self.out_head = nn.Linear(cfg["emb_dim"], cfg["vocab_size"], bias=False)

        cos, sin = compute_rope(
            cfg["emb_dim"] // cfg["n_heads"],
            cfg["rope_base"],
            cfg["context_length"],
        )
        self.register_buffer("cos", cos)
        self.register_buffer("sin", sin)

    def forward(self, input_ids):
        b, seq_len = input_ids.shape
        x = self.tok_emb(input_ids)
        mask = torch.triu(
            torch.ones(seq_len, seq_len, device=x.device, dtype=torch.bool),
            diagonal=1,
        )
        for layer in self.layers:
            x = layer(x, self.cos, self.sin, mask)
        x = self.norm(x)
        return self.out_head(x)


def generate_simple(model, input_ids, max_new_tokens):
    """Non-cached autoregressive generation (recomputes all KV pairs each step)."""
    model.eval()
    with torch.no_grad():
        for _ in range(max_new_tokens):
            input_cond = input_ids[:, -model.cfg["context_length"]:]
            logits = model(input_cond)
            next_token = logits[:, -1, :].argmax(dim=-1, keepdim=True)
            input_ids = torch.cat([input_ids, next_token], dim=1)
    return input_ids
