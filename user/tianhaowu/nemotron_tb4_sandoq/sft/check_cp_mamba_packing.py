"""Check that CP Mamba respects packed-sequence boundaries (run with torchrun, 4 GPUs).

A small random NemotronH Mamba layer processes one packed row of three sequences. The CP path
(all-to-all head partitioning with the full cu_seqlens) must match the non-CP varlen path for the
output and for the input / parameter gradients. Also checks that dropping cu_seqlens in the CP path
leaks state across boundaries, so the comparison can tell the two apart.
"""

import os

import torch
import torch.distributed as dist

from prime_rl.trainer.models.layers.ulysses_attn import update_ulysses_params
from prime_rl.trainer.models.nemotron_h.configuration_nemotron_h import NemotronHConfig
from prime_rl.trainer.models.nemotron_h.modeling_nemotron_h import NemotronHMambaLayer
from prime_rl.utils.cp import shard_for_cp


def main() -> None:
    dist.init_process_group("nccl")
    rank, world = dist.get_rank(), dist.get_world_size()
    torch.cuda.set_device(int(os.environ["LOCAL_RANK"]))
    torch.manual_seed(0)

    config = NemotronHConfig(
        hidden_size=512,
        layers_block_type=["mamba"],
        mamba_num_heads=16,
        mamba_n_groups=8,
        mamba_head_dim=32,
        ssm_state_size=32,
        mamba_chunk_size=64,
        num_attention_heads=8,
        num_key_value_heads=2,
        head_dim=64,
    )
    config._attn_implementation = "flash_attention_2"
    layer = NemotronHMambaLayer(config, layer_idx=0).cuda().to(torch.bfloat16)
    for param in layer.parameters():
        dist.broadcast(param.data, 0)

    seq_len = 1024
    cu_seqlens = torch.tensor([0, 300, 700, seq_len], dtype=torch.int32, device="cuda")
    x = torch.randn(1, seq_len, config.hidden_size, device="cuda", dtype=torch.bfloat16)
    dist.broadcast(x, 0)
    grad_out = torch.randn_like(x)
    dist.broadcast(grad_out, 0)

    x_ref = x.clone().requires_grad_()
    ref = layer(x_ref, cu_seqlens=cu_seqlens, max_seqlen=400)
    ref.backward(grad_out)
    ref_param_grads = {n: p.grad.clone() for n, p in layer.named_parameters() if p.grad is not None}
    layer.zero_grad()

    layer.set_context_parallel_attributes(dist.group.WORLD, rank, world)
    update_ulysses_params(cu_seqlens, 400)
    x_local = shard_for_cp(x, rank, world).clone().requires_grad_()
    out_local = layer(x_local)
    out_local.backward(shard_for_cp(grad_out, rank, world))
    cp_param_grads = {}
    for n, p in layer.named_parameters():
        if p.grad is not None:
            grad = p.grad.clone()
            dist.all_reduce(grad)
            cp_param_grads[n] = grad

    def rel(a, b):
        return ((a.float() - b.float()).norm() / b.float().norm().clamp_min(1e-12)).item()

    out_err = rel(out_local, shard_for_cp(ref, rank, world))
    in_grad_err = rel(x_local.grad, shard_for_cp(x_ref.grad, rank, world))
    param_errs = {n: rel(cp_param_grads[n], g) for n, g in ref_param_grads.items()}

    update_ulysses_params(torch.tensor([0, seq_len], dtype=torch.int32, device="cuda"), seq_len)
    with torch.no_grad():
        leaky = layer(shard_for_cp(x, rank, world))
    leak_err = rel(leaky, shard_for_cp(ref, rank, world))

    errs = torch.tensor([out_err, in_grad_err, max(param_errs.values()), leak_err], device="cuda")
    dist.all_reduce(errs, op=dist.ReduceOp.MAX)
    if rank == 0:
        print(f"packed CP vs varlen: output rel err={errs[0]:.2e}  input-grad rel err={errs[1]:.2e}  "
              f"max param-grad rel err={errs[2]:.2e}")
        print(f"CP without boundaries vs varlen: output rel err={errs[3]:.2e} (should be large)")
        worst = max(param_errs, key=param_errs.get)
        print(f"worst param grad on rank 0: {worst} {param_errs[worst]:.2e}")
        ok = errs[0] < 2e-2 and errs[1] < 2e-2 and errs[2] < 3e-2 and errs[3] > 1e-2 and errs[3] > 10 * errs[0]
        print("PASS" if ok else "FAIL")
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
