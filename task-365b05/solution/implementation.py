"""
Transformer Language Model and Training Utilities — Corrected Implementation

All components implemented using raw torch.Tensor operations.
Only torch.nn.Parameter, torch.nn.Module, torch.nn.ModuleList,
and torch.optim.Optimizer (base class) are used from torch.nn/optim.
"""

import math
from typing import Iterable

import torch
import torch.nn as nn
from torch import Tensor


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def softmax(x: Tensor, dim: int) -> Tensor:
    x_max = x.max(dim=dim, keepdim=True).values
    exp_x = torch.exp(x - x_max)
    return exp_x / exp_x.sum(dim=dim, keepdim=True)


def cross_entropy(logits: Tensor, targets: Tensor) -> Tensor:
    logits_max = logits.max(dim=-1, keepdim=True).values
    shifted = logits - logits_max
    log_sum_exp = torch.log(torch.exp(shifted).sum(dim=-1))
    target_logits = shifted[torch.arange(logits.shape[0], device=logits.device), targets]
    return -(target_logits - log_sum_exp).mean()


def silu(x: Tensor) -> Tensor:
    return x * torch.sigmoid(x)


def rms_norm(x: Tensor, weight: Tensor, eps: float = 1e-5) -> Tensor:
    rms = torch.sqrt(torch.mean(x ** 2, dim=-1, keepdim=True) + eps)
    return (x / rms) * weight


def rope(x: Tensor, positions: Tensor, theta: float, d_k: int) -> Tensor:
    freqs = 1.0 / (theta ** (torch.arange(0, d_k, 2, dtype=x.dtype, device=x.device) / d_k))
    angles = positions.unsqueeze(-1).float() * freqs
    cos_a = torch.cos(angles)
    sin_a = torch.sin(angles)
    x1 = x[..., 0::2]
    x2 = x[..., 1::2]
    out1 = x1 * cos_a - x2 * sin_a
    out2 = x1 * sin_a + x2 * cos_a
    return torch.stack([out1, out2], dim=-1).flatten(-2)


def scaled_dot_product_attention(
    Q: Tensor, K: Tensor, V: Tensor, mask: Tensor | None = None
) -> Tensor:
    d_k = Q.shape[-1]
    scores = torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(d_k)
    if mask is not None:
        scores = scores.masked_fill(mask, float("-inf"))
    weights = softmax(scores, dim=-1)
    return torch.matmul(weights, V)


# ---------------------------------------------------------------------------
# Transformer LM
# ---------------------------------------------------------------------------

class TransformerLM(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        context_length: int,
        d_model: int,
        num_layers: int,
        num_heads: int,
        d_ff: int,
        theta: float = 10000.0,
        eps: float = 1e-5,
    ):
        super().__init__()
        self.vocab_size = vocab_size
        self.context_length = context_length
        self.d_model = d_model
        self.num_layers = num_layers
        self.num_heads = num_heads
        self.d_ff = d_ff
        self.theta = theta
        self.eps = eps
        self.d_k = d_model // num_heads
        assert d_model % num_heads == 0

        self.token_embeddings = nn.Parameter(torch.randn(vocab_size, d_model) * 0.02)

        self.layers = nn.ModuleList()
        for _ in range(num_layers):
            block = nn.Module()
            block.q_proj = nn.Parameter(torch.randn(d_model, d_model) * 0.02)
            block.k_proj = nn.Parameter(torch.randn(d_model, d_model) * 0.02)
            block.v_proj = nn.Parameter(torch.randn(d_model, d_model) * 0.02)
            block.o_proj = nn.Parameter(torch.randn(d_model, d_model) * 0.02)
            block.w1 = nn.Parameter(torch.randn(d_ff, d_model) * 0.02)
            block.w2 = nn.Parameter(torch.randn(d_model, d_ff) * 0.02)
            block.w3 = nn.Parameter(torch.randn(d_ff, d_model) * 0.02)
            block.ln1_weight = nn.Parameter(torch.ones(d_model))
            block.ln2_weight = nn.Parameter(torch.ones(d_model))
            self.layers.append(block)

        self.ln_final_weight = nn.Parameter(torch.ones(d_model))
        self.lm_head = nn.Parameter(torch.randn(vocab_size, d_model) * 0.02)

    def forward(self, token_ids: Tensor) -> Tensor:
        batch_size, seq_len = token_ids.shape
        x = self.token_embeddings[token_ids]

        causal_mask = torch.triu(
            torch.ones(seq_len, seq_len, dtype=torch.bool, device=x.device), diagonal=1
        )

        positions = torch.arange(seq_len, device=x.device).unsqueeze(0).expand(batch_size, -1)

        for block in self.layers:
            normed = rms_norm(x, block.ln1_weight, self.eps)
            Q = normed @ block.q_proj.T
            K = normed @ block.k_proj.T
            V = normed @ block.v_proj.T

            Q = Q.view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
            K = K.view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
            V = V.view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)

            head_positions = positions.unsqueeze(1).expand(-1, self.num_heads, -1)
            Q = rope(Q, head_positions, self.theta, self.d_k)
            K = rope(K, head_positions, self.theta, self.d_k)

            attn_out = scaled_dot_product_attention(Q, K, V, mask=causal_mask)
            attn_out = attn_out.transpose(1, 2).contiguous().view(batch_size, seq_len, self.d_model)
            attn_out = attn_out @ block.o_proj.T
            x = x + attn_out

            normed = rms_norm(x, block.ln2_weight, self.eps)
            gate = silu(normed @ block.w1.T)
            up = normed @ block.w3.T
            ffn_out = (gate * up) @ block.w2.T
            x = x + ffn_out

        x = rms_norm(x, self.ln_final_weight, self.eps)
        logits = x @ self.lm_head.T
        return logits


# ---------------------------------------------------------------------------
# AdamW optimizer
# ---------------------------------------------------------------------------

class AdamW(torch.optim.Optimizer):
    def __init__(
        self,
        params,
        lr: float = 1e-3,
        betas: tuple = (0.9, 0.999),
        eps: float = 1e-8,
        weight_decay: float = 0.01,
    ):
        defaults = dict(lr=lr, betas=betas, eps=eps, weight_decay=weight_decay)
        super().__init__(params, defaults)

    def step(self, closure=None):
        loss = None
        if closure is not None:
            loss = closure()

        for group in self.param_groups:
            lr = group["lr"]
            beta1, beta2 = group["betas"]
            eps = group["eps"]
            weight_decay = group["weight_decay"]

            for p in group["params"]:
                if p.grad is None:
                    continue

                grad = p.grad.data
                state = self.state[p]
                if len(state) == 0:
                    state["step"] = 0
                    state["exp_avg"] = torch.zeros_like(p.data)
                    state["exp_avg_sq"] = torch.zeros_like(p.data)

                state["step"] += 1
                t = state["step"]
                exp_avg = state["exp_avg"]
                exp_avg_sq = state["exp_avg_sq"]

                exp_avg.mul_(beta1).add_(grad, alpha=1 - beta1)
                exp_avg_sq.mul_(beta2).addcmul_(grad, grad, value=1 - beta2)

                bias_correction1 = 1 - beta1 ** t
                bias_correction2 = 1 - beta2 ** t
                step_size = lr / bias_correction1

                p.data.mul_(1 - lr * weight_decay)

                denom = (exp_avg_sq.sqrt() / math.sqrt(bias_correction2)).add_(eps)
                p.data.addcdiv_(exp_avg, denom, value=-step_size)

        return loss


# ---------------------------------------------------------------------------
# Learning rate schedule
# ---------------------------------------------------------------------------

def get_cosine_schedule(
    it: int,
    max_learning_rate: float,
    min_learning_rate: float,
    warmup_iters: int,
    cosine_cycle_iters: int,
) -> float:
    if it < warmup_iters:
        return max_learning_rate * it / warmup_iters
    elif it < cosine_cycle_iters:
        progress = (it - warmup_iters) / (cosine_cycle_iters - warmup_iters)
        return min_learning_rate + 0.5 * (max_learning_rate - min_learning_rate) * (
            1 + math.cos(math.pi * progress)
        )
    else:
        return min_learning_rate


# ---------------------------------------------------------------------------
# Gradient clipping
# ---------------------------------------------------------------------------

def gradient_clipping(parameters: Iterable[torch.nn.Parameter], max_l2_norm: float) -> None:
    params = [p for p in parameters if p.grad is not None]
    if not params:
        return
    total_norm = torch.sqrt(sum(torch.sum(p.grad.data ** 2) for p in params))
    if total_norm > max_l2_norm:
        scale = max_l2_norm / total_norm
        for p in params:
            p.grad.data.mul_(scale)
