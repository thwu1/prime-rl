"""Small causal language model for testing loss normalization strategies."""

import math
import torch
import torch.nn as nn


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization."""

    def __init__(self, dim, eps=1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x):
        rms = torch.rsqrt(x.float().pow(2).mean(-1, keepdim=True) + self.eps)
        return (x.float() * rms).to(x.dtype) * self.weight


class FeedForward(nn.Module):
    """SwiGLU-style feed-forward network."""

    def __init__(self, dim, hidden_dim):
        super().__init__()
        self.gate = nn.Linear(dim, hidden_dim, bias=False)
        self.up = nn.Linear(dim, hidden_dim, bias=False)
        self.down = nn.Linear(hidden_dim, dim, bias=False)

    def forward(self, x):
        return self.down(nn.functional.silu(self.gate(x)) * self.up(x))


class TransformerBlock(nn.Module):
    """Pre-norm transformer block with SwiGLU FFN."""

    def __init__(self, dim, hidden_dim):
        super().__init__()
        self.norm = RMSNorm(dim)
        self.ffn = FeedForward(dim, hidden_dim)

    def forward(self, x):
        return x + self.ffn(self.norm(x))


class SmallCausalLM(nn.Module):
    """Small causal LM for loss normalization experiments.

    Intentionally simple (no attention) for CPU speed while exhibiting
    realistic training dynamics with variable-length sequences.
    """

    def __init__(self, vocab_size=512, dim=96, hidden_dim=192, n_layers=2):
        super().__init__()
        self.dim = dim
        self.embedding = nn.Embedding(vocab_size, dim)
        self.layers = nn.ModuleList(
            [TransformerBlock(dim, hidden_dim) for _ in range(n_layers)]
        )
        self.norm = RMSNorm(dim)
        self.lm_head = nn.Linear(dim, vocab_size, bias=False)

        self.apply(self._init_weights)

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, input_ids):
        x = self.embedding(input_ids) * math.sqrt(self.dim)
        for layer in self.layers:
            x = layer(x)
        x = self.norm(x)
        return self.lm_head(x)
