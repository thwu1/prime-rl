"""
Custom Transformer model for sequence-to-sequence copy task.

Uses non-standard operations defined in ops.py.
DO NOT MODIFY THIS FILE.

"""

import math
import torch
import torch.nn as nn

from ops import (
    log_softmax,
    rms_norm,
    scaled_dot_attention,
    sinusoidal_pe,
    make_causal_mask,
)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


class TokenEmbedding(nn.Module):
    def __init__(self, vocab_size: int, d_model: int):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, d_model)
        self.scale = math.sqrt(d_model)

    def forward(self, x):
        return self.emb(x) * self.scale


class RMSNormLayer(nn.Module):
    """Root-mean-square normalization — NOT the standard LayerNorm.

    No mean centering, no bias term.
    """

    def __init__(self, d_model: int, eps: float = 1e-6):
        super().__init__()
        self.gain = nn.Parameter(torch.ones(d_model))
        self.eps = eps

    def forward(self, x):
        return rms_norm(x, self.gain, self.eps)


class MultiHeadAttention(nn.Module):
    def __init__(self, d_model: int, n_heads: int):
        super().__init__()
        assert d_model % n_heads == 0
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_k = d_model // n_heads

        # Temperature: cube-root of d_k (NOT the standard square-root).
        self.tau = self.d_k ** (1.0 / 3.0)

        self.W_q = nn.Linear(d_model, d_model, bias=False)
        self.W_k = nn.Linear(d_model, d_model, bias=False)
        self.W_v = nn.Linear(d_model, d_model, bias=False)
        self.W_o = nn.Linear(d_model, d_model, bias=False)

    def forward(self, query, key, value, mask=None):
        B = query.size(0)
        L_q = query.size(1)
        L_k = key.size(1)

        Q = self.W_q(query).view(B, L_q, self.n_heads, self.d_k).transpose(1, 2)
        K = self.W_k(key).view(B, L_k, self.n_heads, self.d_k).transpose(1, 2)
        V = self.W_v(value).view(B, L_k, self.n_heads, self.d_k).transpose(1, 2)

        if mask is not None and mask.dim() == 3:
            mask = mask.unsqueeze(1)

        out = scaled_dot_attention(Q, K, V, mask, self.tau)

        out = out.transpose(1, 2).contiguous().view(B, L_q, self.d_model)
        return self.W_o(out)


class FeedForward(nn.Module):
    def __init__(self, d_model: int, d_ff: int, dropout: float = 0.1):
        super().__init__()
        self.w1 = nn.Linear(d_model, d_ff)
        self.w2 = nn.Linear(d_ff, d_model)
        self.drop = nn.Dropout(dropout)

    def forward(self, x):
        return self.w2(self.drop(torch.relu(self.w1(x))))


# ---------------------------------------------------------------------------
# Encoder / Decoder layers  (pre-norm residual)
# ---------------------------------------------------------------------------


class EncoderLayer(nn.Module):
    def __init__(self, d_model, n_heads, d_ff, dropout=0.1):
        super().__init__()
        self.self_attn = MultiHeadAttention(d_model, n_heads)
        self.ff = FeedForward(d_model, d_ff, dropout)
        self.norm1 = RMSNormLayer(d_model)
        self.norm2 = RMSNormLayer(d_model)
        self.drop1 = nn.Dropout(dropout)
        self.drop2 = nn.Dropout(dropout)

    def forward(self, x, src_mask):
        h = self.norm1(x)
        x = x + self.drop1(self.self_attn(h, h, h, src_mask))
        x = x + self.drop2(self.ff(self.norm2(x)))
        return x


class DecoderLayer(nn.Module):
    def __init__(self, d_model, n_heads, d_ff, dropout=0.1):
        super().__init__()
        self.self_attn = MultiHeadAttention(d_model, n_heads)
        self.cross_attn = MultiHeadAttention(d_model, n_heads)
        self.ff = FeedForward(d_model, d_ff, dropout)
        self.norm1 = RMSNormLayer(d_model)
        self.norm2 = RMSNormLayer(d_model)
        self.norm3 = RMSNormLayer(d_model)
        self.drop1 = nn.Dropout(dropout)
        self.drop2 = nn.Dropout(dropout)
        self.drop3 = nn.Dropout(dropout)

    def forward(self, x, memory, src_mask, tgt_mask):
        h = self.norm1(x)
        x = x + self.drop1(self.self_attn(h, h, h, tgt_mask))
        h = self.norm2(x)
        x = x + self.drop2(self.cross_attn(h, memory, memory, src_mask))
        x = x + self.drop3(self.ff(self.norm3(x)))
        return x


# ---------------------------------------------------------------------------
# Full model
# ---------------------------------------------------------------------------


class CopyTransformer(nn.Module):
    # Non-standard constants (discoverable only by reading this file)
    PE_BASE = 5000.0  # frequency base for positional encoding
    DECODER_WINDOW = 12  # sliding-window width for decoder self-attention

    def __init__(
        self,
        vocab_size=12,
        d_model=64,
        n_heads=4,
        d_ff=256,
        n_layers=2,
        max_len=30,
        dropout=0.1,
        pad_idx=0,
    ):
        super().__init__()
        self.pad_idx = pad_idx
        self.d_model = d_model

        self.src_embed = TokenEmbedding(vocab_size, d_model)
        self.tgt_embed = TokenEmbedding(vocab_size, d_model)

        self.register_buffer(
            "pe", sinusoidal_pe(max_len, d_model, self.PE_BASE)
        )

        self.enc_layers = nn.ModuleList(
            [EncoderLayer(d_model, n_heads, d_ff, dropout) for _ in range(n_layers)]
        )
        self.dec_layers = nn.ModuleList(
            [DecoderLayer(d_model, n_heads, d_ff, dropout) for _ in range(n_layers)]
        )

        self.final_norm = RMSNormLayer(d_model)
        self.out_proj = nn.Linear(d_model, vocab_size, bias=False)
        self.dropout = nn.Dropout(dropout)

    # -- masks --

    def _src_mask(self, src):
        return (src != self.pad_idx).unsqueeze(1).unsqueeze(2)

    def _tgt_mask(self, tgt):
        causal = make_causal_mask(tgt.size(1), self.DECODER_WINDOW).to(tgt.device)
        pad = (tgt != self.pad_idx).unsqueeze(1).unsqueeze(2)
        return causal & pad

    # -- forward --

    def encode(self, src, src_mask):
        x = self.dropout(self.src_embed(src) + self.pe[: src.size(1)])
        for layer in self.enc_layers:
            x = layer(x, src_mask)
        return x

    def decode(self, tgt, memory, src_mask, tgt_mask):
        x = self.dropout(self.tgt_embed(tgt) + self.pe[: tgt.size(1)])
        for layer in self.dec_layers:
            x = layer(x, memory, src_mask, tgt_mask)
        return self.final_norm(x)

    def forward(self, src, tgt):
        src_mask = self._src_mask(src)
        tgt_mask = self._tgt_mask(tgt)
        memory = self.encode(src, src_mask)
        dec_out = self.decode(tgt, memory, src_mask, tgt_mask)
        return self.out_proj(dec_out)

    @torch.no_grad()
    def greedy_decode(self, src, max_len, bos_idx=1):
        self.eval()
        src_mask = self._src_mask(src)
        memory = self.encode(src, src_mask)
        ys = torch.full(
            (src.size(0), 1), bos_idx, dtype=torch.long, device=src.device
        )
        for _ in range(max_len - 1):
            tgt_mask = make_causal_mask(ys.size(1), self.DECODER_WINDOW).to(
                src.device
            )
            dec_out = self.decode(ys, memory, src_mask, tgt_mask)
            logits = self.out_proj(dec_out[:, -1:])
            lp = log_softmax(logits, dim=-1)
            ys = torch.cat([ys, lp.argmax(dim=-1)], dim=1)
        return ys
