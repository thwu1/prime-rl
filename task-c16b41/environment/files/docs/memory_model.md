# Per-GPU Memory Estimation Model

This document specifies the mathematical model for estimating per-GPU memory usage during distributed training.

## Input Parameters

- `TP` = `tensor_parallel_degree`
- `PP` = `pipeline_parallel_degree`
- `s` = `sharding_parallel_degree`
- `total_params` = `total_params_billions` x 1e9 (from model registry)
- `seq_len` = `max_seq_len` (from config)
- `B` = `batch_size` (from config)
- `H` = `hidden_dim` (from model registry)
- `L` = `num_layers` (from model registry)

## Formula

```
params_per_gpu = total_params / (TP * PP)

# Parameter storage (GB)
param_bytes = 1 if compute_type == "fp8" else 2   # FP8 = 1 byte, BF16 = 2 bytes
P_mem = params_per_gpu * param_bytes / 1e9

# Gradient storage (GB) — gradients always stored in BF16
G_mem_raw = params_per_gpu * 2 / 1e9

# Optimizer storage (GB)
if tensorwise_offload_optimizer == True or offload_optim == True:
    optim_bytes_per_param = 0
elif use_lowprecision_moment == True:
    optim_bytes_per_param = 8    # master_weight(4) + moment1(2) + moment2(2)
else:
    optim_bytes_per_param = 12   # master_weight(4) + moment1(4) + moment2(4)

O_mem_raw = params_per_gpu * optim_bytes_per_param / 1e9

# Apply sharding reduction
if sharding == "stage1":
    O_mem = O_mem_raw / s
    G_mem = G_mem_raw
    # P_mem unchanged
elif sharding == "stage2":
    O_mem = O_mem_raw / s
    G_mem = G_mem_raw / s
    # P_mem unchanged
elif sharding == "stage3":
    O_mem = O_mem_raw / s
    G_mem = G_mem_raw / s
    P_mem = P_mem / s

# Activation memory (GB)
layers_per_stage = ceil(L / PP)
act_bytes_per_layer = seq_len * B * H * 24

if sequence_parallel == True and TP > 1:
    act_bytes_per_layer = act_bytes_per_layer / TP

if recompute == True:
    A_mem = act_bytes_per_layer * 2 / 1e9
else:
    A_mem = act_bytes_per_layer * layers_per_stage / 1e9

# Total per-GPU memory
total_memory_gb = P_mem + G_mem + O_mem + A_mem
```
