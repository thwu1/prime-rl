import os
import socket

import pytest
import torch
import torch.distributed as dist
import torch.multiprocessing as mp

from prime_rl.trainer.models.layers.ulysses_attn import ulysses_flash_attn_varlen_func


def reference_varlen_attn(q, k, v, cu_seqlens_q, cu_seqlens_k, max_seqlen_q, max_seqlen_k, causal=True):
    """GQA causal varlen attention with flash-attn's [S, H, D] calling convention."""
    group = q.shape[1] // k.shape[1]
    k = k.repeat_interleave(group, dim=1)
    v = v.repeat_interleave(group, dim=1)
    out = torch.empty_like(q)
    bounds = cu_seqlens_q.tolist()
    for start, end in zip(bounds[:-1], bounds[1:]):
        out[start:end] = torch.nn.functional.scaled_dot_product_attention(
            q[start:end].transpose(0, 1), k[start:end].transpose(0, 1), v[start:end].transpose(0, 1), is_causal=causal
        ).transpose(0, 1)
    return out


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _worker(rank, cp_size, port, num_heads, num_kv_heads, results):
    os.environ["MASTER_ADDR"] = "127.0.0.1"
    os.environ["MASTER_PORT"] = str(port)
    dist.init_process_group("gloo", rank=rank, world_size=cp_size)
    torch.manual_seed(0)
    seq_len, head_dim = 64, 16
    cu_seqlens = torch.tensor([0, 24, 64], dtype=torch.int32)
    q = torch.randn(seq_len, num_heads, head_dim, dtype=torch.float64, requires_grad=True)
    k = torch.randn(seq_len, num_kv_heads, head_dim, dtype=torch.float64, requires_grad=True)
    v = torch.randn(seq_len, num_kv_heads, head_dim, dtype=torch.float64, requires_grad=True)
    grad_out = torch.randn(seq_len, num_heads, head_dim, dtype=torch.float64)

    ref = reference_varlen_attn(q, k, v, cu_seqlens, cu_seqlens, seq_len, seq_len)
    ref_grads = torch.autograd.grad(ref, (q, k, v), grad_out)

    shard = slice(rank * seq_len // cp_size, (rank + 1) * seq_len // cp_size)
    q_local, k_local, v_local = (t[shard].detach().requires_grad_() for t in (q, k, v))
    out_local = ulysses_flash_attn_varlen_func(
        reference_varlen_attn,
        q_local,
        k_local,
        v_local,
        cu_seqlens,
        cu_seqlens,
        seq_len,
        seq_len,
        causal=True,
        cp_group=dist.group.WORLD,
        cp_size=cp_size,
    )
    out_local.backward(grad_out[shard])

    # K/V grads for this sequence shard are complete locally: the all-to-all backward
    # returns every head-rank's contribution for the positions this rank owns.
    results[rank] = (
        torch.allclose(out_local, ref[shard], atol=1e-10),
        torch.allclose(q_local.grad, ref_grads[0][shard], atol=1e-10),
        torch.allclose(k_local.grad, ref_grads[1][shard], atol=1e-10),
        torch.allclose(v_local.grad, ref_grads[2][shard], atol=1e-10),
    )
    dist.destroy_process_group()


@pytest.mark.parametrize(
    ("cp_size", "num_heads", "num_kv_heads"),
    [(2, 8, 2), (4, 8, 2), (8, 8, 2), (4, 8, 1)],
)
def test_ulysses_matches_full_attention(cp_size, num_heads, num_kv_heads):
    results = mp.Manager().dict()
    mp.spawn(_worker, args=(cp_size, _free_port(), num_heads, num_kv_heads, results), nprocs=cp_size)
    assert all(all(checks) for checks in results.values()), dict(results)
