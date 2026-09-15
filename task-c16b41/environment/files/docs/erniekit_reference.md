# ERNIEKit Configuration Reference

Excerpts from ERNIEKit and PaddlePaddle documentation relevant to training configuration.

## Distributed Training Parameters

| Parameter | Type | Description |
| --- | --- | --- |
| `tensor_parallel_degree` | int | Tensor parallelism degree. Splits model tensor operations across GPUs along the hidden dimension. Requires efficient inter-GPU communication via NVLink/NVSwitch — GPU interconnect topologies operate most efficiently when process group sizes are powers of two. |
| `pipeline_parallel_degree` | int | Pipeline parallelism degree. Partitions model layers into sequential stages processed in a pipelined fashion. |
| `pp_seg_method` | list[int] | Pipeline stage layer boundaries. Defines the start/end layer indices for each pipeline stage. When pipeline parallelism is active, this list determines how layers are distributed across stages. |
| `sharding_parallel_degree` | int | Sharding parallelism degree for ZeRO-style memory optimization. |
| `sharding` | str | Sharding strategy: `stage1` (shard optimizer states only), `stage2` (shard optimizer states + gradients), `stage3` (shard optimizer states + gradients + parameters). |
| `sequence_parallel` | bool | Enable sequence parallelism to reduce activation memory when using tensor parallelism. |
| `moe_group` | str | MoE expert communication group. Set to `"mp"` for training Mixture-of-Experts models. Controls expert routing and all-to-all communication patterns in distributed MoE training. |

**Parallelism Constraint**: In distributed training, the total GPU count must be partitioned across parallelism dimensions: `tensor_parallel_degree × pipeline_parallel_degree × sharding_parallel_degree × data_parallel_degree = num_gpus`. Data parallelism is determined implicitly from the remaining GPUs.

## Memory Optimization

| Parameter | Type | Description |
| --- | --- | --- |
| `recompute` | bool | Enable gradient checkpointing (recomputation) to reduce activation memory at the cost of additional compute. |
| `offload_optim` | bool | Offload optimizer states to CPU pinned memory to reduce GPU memory usage. |

## Mixed Precision Training

| Parameter | Type | Description |
| --- | --- | --- |
| `compute_type` | str | Training precision mode: `"bf16"` (BFloat16) or `"fp8"` (FP8 quantization-aware training). |
| `fp16_opt_level` | str | AMP optimization level. `"O1"` keeps a float32 master copy of all parameters; `"O2"` converts model parameters to float16/bfloat16 for reduced memory. |
| `amp_custom_white_list` | list[str] | Operators forced to execute in low precision under AMP O2 mode. |
| `amp_custom_black_list` | list[str] | Operators forced to remain in float32 under AMP O2 mode. An operator cannot simultaneously appear in both the whitelist and blacklist — the lists must be mutually exclusive. |

## Training Hyperparameters

| Parameter | Type | Description |
| --- | --- | --- |
| `batch_size` | int | Per-device micro-batch size for training. |
| `gradient_accumulation_steps` | int | Number of forward/backward passes before each optimizer step. Effectively multiplies the batch size. |
| `learning_rate` | float | Peak learning rate for the optimizer. |
| `lr_scheduler_type` | str | Learning rate schedule. Supported values: `cosine`, `linear`, `constant`, `constant_with_warmup`. |
| `warmup_steps` | int | Number of warmup steps for the learning rate scheduler. |
| `weight_decay` | float | AdamW optimizer weight decay coefficient. |
| `optim` | str | Optimizer selection. ERNIEKit supports: `adamw` (standard AdamW), `adamw_custom` (fused AdamW with custom CUDA kernels), `sgd` (stochastic gradient descent). |

## FP8 Quantization-Aware Training (QAT)

ERNIEKit's FP8 QAT methodology enables training large models (e.g., ERNIE-4.5-300B-A47B) on significantly fewer GPUs (16 instead of 96) while maintaining model quality and producing models that support efficient tensor-wise static FP8 inference.

### Hadamard Transform

FP8 QAT introduces a **Hadamard matrix** to ensure stable convergence in tensor-wise static quantization. Block-diagonal Hadamard matrices handle varying tensor shapes. This transform is essential for FP8 training stability — without it, tensor-wise quantization produces unstable gradients.

### FP8 Memory Model

In FP8 QAT:
- **Parameters** are stored in FP8 format (1 byte per parameter instead of 2 bytes for BF16).
- **Optimizer moments** use BF16 precision for numerical stability.
- **All optimizer states** (master weights, first moments, second moments) are offloaded to CPU pinned memory, eliminating their GPU memory footprint during training.

Both optimizer offloading and low-precision moments are integral to the FP8 training methodology and must be enabled together.

| Parameter | Type | Description |
| --- | --- | --- |
| `apply_hadamard` | bool | Enable Hadamard transform for FP8 tensor-wise quantization stability. |
| `use_lowprecision_moment` | bool | Store optimizer first/second moments in BF16 instead of FP32. Reduces per-parameter optimizer storage from 12 bytes to 8 bytes (master_weight: 4B, moment1: 2B, moment2: 2B). |
| `tensorwise_offload_optimizer` | bool | Offload all optimizer states to CPU pinned memory. Required for FP8 training to fit large models in GPU memory. |
