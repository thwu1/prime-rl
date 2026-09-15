# ERNIEKit Training Configuration Validation Rules & Algorithms

## 1. Validation Rules

The validator checks configs against 13 rules. Each violation is reported with its rule ID.

### Rule: TP_POWER_OF_TWO
`tensor_parallel_degree` must be a power of 2 (1, 2, 4, 8, 16, ...).

### Rule: PP_POSITIVE
`pipeline_parallel_degree` must be an integer >= 1.

### Rule: PARALLEL_PRODUCT
`tensor_parallel_degree * pipeline_parallel_degree * sharding_parallel_degree` must be <= `num_gpus`, and `num_gpus` must be evenly divisible by this product. The implicit data parallel degree is `num_gpus / (TP * PP * sharding_parallel_degree)`.

### Rule: PP_SEG_METHOD
When `pipeline_parallel_degree > 1`, `pp_seg_method` must be present and must be a list of integers with exactly `pipeline_parallel_degree + 1` elements. The elements must be strictly increasing, the first element must be 0, and the last element must equal the model's `num_layers` (from the model registry).

### Rule: FP8_HADAMARD
When `compute_type` is `"fp8"`, the field `apply_hadamard` must be present and set to `True`. FP8 QAT uses Hadamard matrices for stable tensor-wise static quantization.

### Rule: FP8_OPTIM
When `compute_type` is `"fp8"`, both `tensorwise_offload_optimizer` and `use_lowprecision_moment` must be present and set to `True`. FP8 training stores parameters in FP8 while optimizer moments use BF16, with all optimizer states offloaded to pinned CPU memory.

### Rule: AMP_DISJOINT
`amp_custom_white_list` and `amp_custom_black_list` must have no common elements. An operator cannot be simultaneously whitelisted and blacklisted for mixed precision.

### Rule: SHARDING_VALID
`sharding` must be exactly one of: `"stage1"`, `"stage2"`, `"stage3"` (case-sensitive).

### Rule: MOE_GROUP
For Mixture-of-Experts models (where `is_moe` is `true` in the model registry), the config field `moe_group` must be present and non-empty.

### Rule: LR_SCHEDULER
`lr_scheduler_type` must be one of: `"cosine"`, `"linear"`, `"constant"`, `"constant_with_warmup"`.

### Rule: FP16_OPT_LEVEL
`fp16_opt_level` must be one of: `"O1"`, `"O2"`.

### Rule: BATCH_POSITIVE
`batch_size` must be a positive integer (> 0). If `gradient_accumulation_steps` is present, it must also be a positive integer (> 0).

### Rule: OPTIMIZER_VALID
If `optim` is present, it must be one of: `"adamw"`, `"adamw_custom"`, `"sgd"`.

---

## 2. Validator Output Formats

### validate mode
Output JSON to stdout:
```json
{
    "config_file": "<path>",
    "model": "<model_name>",
    "num_gpus": <N>,
    "violations": [
        {"rule": "<RULE_ID>", "message": "<human-readable description>"}
    ],
    "num_violations": <count>
}
```

### fix mode
Write a corrected YAML config to the path specified by `--output`. The fix strategy for each rule:

| Rule | Fix |
|------|-----|
| TP_POWER_OF_TWO | Round up to next power of 2 |
| PP_POSITIVE | Set to 1 |
| SHARDING_VALID | Set to "stage1" |
| FP16_OPT_LEVEL | Set to "O2" |
| LR_SCHEDULER | Set to "cosine" |
| OPTIMIZER_VALID | Set to "adamw" |
| BATCH_POSITIVE | Set any non-positive value to 1 |
| MOE_GROUP | Set to "mp" |
| FP8_HADAMARD | Set apply_hadamard to True |
| FP8_OPTIM | Set both tensorwise_offload_optimizer and use_lowprecision_moment to True |
| PARALLEL_PRODUCT | Reduce sharding_parallel_degree to 1, then reduce pipeline_parallel_degree, then halve tensor_parallel_degree, repeating until TP*PP*s <= num_gpus and num_gpus % (TP*PP*s) == 0 |
| PP_SEG_METHOD | Auto-generate uniform layer distribution: boundaries at [0, k, 2k, ...] where k = ceil(num_layers/PP), capped at num_layers |
| AMP_DISJOINT | Remove overlapping entries from amp_custom_white_list (keep them in black_list) |

Fix order: apply simple field fixes first (SHARDING_VALID, FP16_OPT_LEVEL, LR_SCHEDULER, OPTIMIZER_VALID, BATCH_POSITIVE, MOE_GROUP, FP8_HADAMARD, FP8_OPTIM), then TP_POWER_OF_TWO, then PP_POSITIVE, then PARALLEL_PRODUCT, then PP_SEG_METHOD, then AMP_DISJOINT.

---

## 3. Memory Estimation Formula

Given a config and model specification, compute per-GPU memory usage in GB.

### Parameters
- `TP` = tensor_parallel_degree
- `PP` = pipeline_parallel_degree
- `s` = sharding_parallel_degree
- `total_params` = total_params_billions * 1e9 (raw parameter count)
- `seq_len` = max_seq_len from config
- `B` = batch_size from config
- `H` = hidden_dim from model registry
- `L` = num_layers from model registry

### Computation

```
params_per_gpu = total_params / (TP * PP)

# Parameter storage (GB)
param_bytes = 1 if compute_type == "fp8" else 2   # fp8 vs bf16
P_mem = params_per_gpu * param_bytes / 1e9

# Gradient storage (GB) — gradients always in bf16
G_mem_raw = params_per_gpu * 2 / 1e9

# Optimizer storage (GB)
if tensorwise_offload_optimizer == True or offload_optim == True:
    optim_bytes_per_param = 0
elif use_lowprecision_moment == True:
    optim_bytes_per_param = 8    # master_weight(4) + moment1(2) + moment2(2)
else:
    optim_bytes_per_param = 12   # master_weight(4) + moment1(4) + moment2(4)

O_mem_raw = params_per_gpu * optim_bytes_per_param / 1e9

# Apply sharding
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

# Total
total_memory_gb = P_mem + G_mem + O_mem + A_mem
```

### estimate mode output
Output JSON to stdout:
```json
{
    "param_memory_gb": <float>,
    "grad_memory_gb": <float>,
    "optim_memory_gb": <float>,
    "activation_memory_gb": <float>,
    "total_memory_gb": <float>
}
```

---

## 4. Parallelism Planner Algorithm

Given hardware constraints and model spec, find the optimal parallelism configuration.

### Inputs
- `model_name`: key into model registry
- `num_gpus`: total available GPUs
- `gpu_mem_gb`: memory per GPU in GB
- `seq_len`: sequence length
- `batch_size`: micro-batch size
- `compute_type`: "fp8" or "bf16"

### Algorithm

1. Load model spec from `/app/models.json`.

2. Enumerate all valid `(TP, PP, s)` tuples where:
   - `TP` is a power of 2 and `TP >= 1`
   - `PP >= 1`
   - `s >= 1`
   - `TP * PP * s <= num_gpus`
   - `num_gpus % (TP * PP * s) == 0`

3. For each candidate, set config parameters:
   - `sequence_parallel = (TP > 1)`
   - `recompute = True`
   - `sharding = "stage1"`
   - If `compute_type == "fp8"`: set `apply_hadamard=True`, `use_lowprecision_moment=True`, `tensorwise_offload_optimizer=True`
   - If `compute_type == "bf16"`: set `offload_optim=False` initially

4. Compute memory estimate using the formula in Section 3.

5. First pass (bf16 only, no offload): collect all candidates that fit in `gpu_mem_gb`.

6. If no candidates fit AND compute_type is "bf16", second pass: set `offload_optim=True` (O_mem=0) and recheck all candidates.

7. For fp8: always use tensorwise_offload_optimizer, so only one pass needed.

8. Among all fitting candidates, compute cost:
   ```
   cost = 3 * TP + 2 * PP + s
   ```
   Select the candidate with minimum cost. Break ties by smallest `(TP, PP, s)` lexicographically.

9. Generate pp_seg_method for the chosen PP:
   - If `PP == 1`: omit pp_seg_method
   - If `PP > 1`: uniform layer split. For each stage `i` (0-indexed), boundary = `min(i * ceil(L/PP), L)`. Result is a list of `PP + 1` integers from 0 to L.

10. If model is MoE, set `moe_group = "mp"`.

### plan mode output
Write a complete YAML training config to the file specified by `--output`.

---

## 5. CLI Interfaces

### validator.py

```
python3 /app/validator.py validate <config_path> --model <model_name> --num-gpus <N>
python3 /app/validator.py fix <config_path> --model <model_name> --num-gpus <N> --output <output_path>
```

### planner.py

```
python3 /app/planner.py estimate <config_path> --model <model_name>
python3 /app/planner.py plan --model <model_name> --num-gpus <N> --gpu-mem-gb <M> --seq-len <L> --batch-size <B> --compute-type <type> --output <output_path>
```
