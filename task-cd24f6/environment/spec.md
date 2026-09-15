# IOPDDL Graph Scheduling Cost Model Specification

## Overview

You must evaluate execution schedules for computational DAGs on an AI accelerator with a three-tier memory hierarchy. Given a problem (graph + hardware specs) and a solution (schedule), compute the total execution latency.

## Memory Hierarchy

- **Slow Memory**: Infinite capacity, limited bandwidth. All graph inputs start here; all graph outputs must end here. Transfer time = `size / slow_memory_bandwidth`.
- **Fast Memory**: Finite capacity (`fast_memory_capacity`), infinite internal bandwidth (0 time cost to access data already here). All computation reads/writes from fast memory.
- **Ephemeral**: When ops are grouped in a subgraph, intermediate tensors flow directly between ops without touching fast memory. Zero capacity, zero transfer cost.

## Operations

Two types:
- **Pointwise**: Element-wise operation on one input tensor producing one output tensor (same dimensions).
- **MatMul**: Matrix multiplication. `inputs[0]` is LHS (Left-Hand Side), `inputs[1]` is RHS. For `C = A @ B`: A has height H_A and width K; B has height K and width W_B; output C has height H_A and width W_B. The inner/reduction dimension is K = LHS.width = RHS.height.

## Execution Granularity

Each subgraph has a granularity tuple `[w, h, k]`:
- `w, h`: Spatial granularity. Output slices are `w` wide, `h` tall.
- `k`: Reduction depth for MatMul. For Pointwise, k is ignored (treated as 1).

### Input Slice Shapes (per the granularity)

- **Pointwise input**: width=w, height=h (same as output)
- **MatMul LHS**: width=k, height=h
- **MatMul RHS**: width=w, height=k
- **Output** (all types): width=w, height=h

## Tiling

For an output tensor of width W and height H:
- `n_w = ceil(W / w)`, `n_h = ceil(H / h)` → `n_spatial = n_w × n_h` spatial tiles
- Tile grid: `n_h` rows × `n_w` columns
- Tile index in raster order: `tile(row, col) = row * n_w + col`

For MatMul ops with inner dimension K:
- `n_k = ceil(K / k)` reduction steps

For a subgraph, `n_k = max(n_k across all MatMul ops)`, or 1 if all Pointwise.

## Traversal Order

The `traversal_orders` field specifies a permutation of tile indices `[0, 1, ..., n_spatial-1]`. If null, use raster order (row-major: `[0, 1, 2, ..., n_spatial-1]`).

## Execution Iteration

For each spatial tile (in traversal order), execute `n_k` reduction steps. Total steps = `n_spatial × n_k`.

## Compute Cost

Per step, for each op in the subgraph:
- **Pointwise**: `base_cost` (always full cost; sub-native spatial granularity is padded)
- **MatMul**: `base_cost × min(k, native_k) / native_k` where `native_k = native_granularity[0]` (proportional to reduction depth; no spatial padding waste for reduction)

The `native_granularity` is `[nw, nh]` and `native_k = nw = nh` (all three native dimensions are equal).

Total compute per step = sum of per-op compute costs.

**Important**: Pointwise ops execute at every step (including all k-steps). MatMul ops also execute at every step. The compute cost formula above already accounts for the k-scaling.

## Working Set (OOM Check)

For each op in the subgraph, the working set is the sum of all its input slice sizes plus its output slice size. Use the slice shapes defined above (MatMul LHS: h×k, MatMul RHS: k×w, Pointwise input: w×h, output: w×h). If any single op's working set exceeds `fast_memory_capacity`, the solution is OOM-invalid.

Note: Ephemeral tensors still require physical space during the producing op's execution. Count them as the producing op's output.

## Data Transfer Model

At each step, data may need to be loaded from slow memory into fast memory (mem_in) or evicted from fast memory to slow memory (mem_out).

### Tensor Classification

For a subgraph:
- **Boundary inputs**: Tensors consumed by ops in the subgraph but NOT produced by any op in the subgraph.
- **Boundary outputs**: Tensors produced by ops in the subgraph but NOT consumed by any op in the subgraph.
- **Ephemeral**: Tensors both produced and consumed within the subgraph. Zero transfer cost.

### MatMul Data Reuse (Intra-Subgraph)

For MatMul boundary inputs, the hardware tracks which data strips are resident in fast memory:

**LHS (row-band loading for split-K):**
- For a spatial tile at row `r`, the LHS needs the full row-band: height=h, width=K (the full inner dimension, NOT just k). This row-band is loaded ONCE per spatial tile and stays resident across all k-steps within that tile.
- Between spatial tiles: if the new tile has the same row index as the previous tile, the LHS row-band is **reused** (0 load cost). Otherwise, it's **reloaded** from slow memory.

**RHS (per-step streaming):**
- For each step, the RHS needs a k-strip: height=k, width=w. This changes every step (different k-slice or different column), so it is **always loaded fresh** from slow memory.

### Pointwise Data Reuse

Pointwise boundary inputs use a slice of w×h per tile. Each spatial tile needs a unique slice, so Pointwise inputs are **always loaded fresh** for each spatial tile. Within k-steps of the same spatial tile, Pointwise inputs are already resident.

### Retained Tensors

`tensors_to_retain[i]` specifies output tensors from subgraph `i` that remain in fast memory after the subgraph completes. At the start of the next subgraph (subgraph `i+1`):
- Retained tensors are already in fast memory → no load cost when used as boundary inputs
- They occupy fast memory capacity

### Output Eviction

Each spatial tile produces an output slice (h×w). The output is evicted to slow memory after the **last k-step** of that spatial tile. If the output tensor is retained, it is NOT evicted (stays in fast memory).

## Latency Calculation

For each step:
```
mem_in_time = sum(loaded_sizes) / slow_memory_bandwidth
mem_out_time = sum(evicted_sizes) / slow_memory_bandwidth
compute_time = sum(per_op_compute)
step_latency = max(compute_time, mem_in_time + mem_out_time)
```

Subgraph latency = sum of all step latencies.
Total latency = sum of all subgraph latencies.

## Input Format (Problem JSON)

```json
{
  "widths": [W0, W1, ...],       // width of tensor[i]
  "heights": [H0, H1, ...],      // height of tensor[i]
  "inputs": [[t0, t1], ...],     // inputs[k] = tensor indices consumed by Op[k]
                                  // For MatMul: [LHS_index, RHS_index]
  "outputs": [[t0], ...],        // outputs[k] = tensor indices produced by Op[k]
  "base_costs": [C0, C1, ...],   // base_costs[k] = compute cost of Op[k]
  "op_types": ["MatMul", "Pointwise", ...],
  "fast_memory_capacity": 25000,
  "slow_memory_bandwidth": 10,
  "native_granularity": [128, 128]
}
```

A tensor is a **graph input** if no op produces it. A tensor is a **graph output** if no op consumes it.

## Output Format (Solution JSON)

```json
{
  "subgraphs": [[0, 1], [2]],
  "granularities": [[64, 64, 128], [128, 128, 1]],
  "tensors_to_retain": [[1], []],
  "traversal_orders": [[0, 1, 3, 2], null],
  "subgraph_latencies": [2048.0, 1024.0]
}
```

## Validation Requirements

1. Every op must appear in at least one subgraph.
2. No OOM: per-op working set must fit in fast_memory_capacity.

## Worked Examples

### Example 1: Baseline (Two Pointwise Ops)

Problem:
```json
{"widths":[128,128,128],"heights":[128,128,128],"inputs":[[0],[1]],"outputs":[[1],[2]],"base_costs":[1000,100],"op_types":["Pointwise","Pointwise"],"fast_memory_capacity":35000,"slow_memory_bandwidth":10,"native_granularity":[128,128]}
```

**Strategy A** (separate): subgraphs=[[0],[1]], gran=[[128,128,1],[128,128,1]], retain=[[],[]], trav=[null,null]
- Subgraph 0: Load T0 (16384/10=1638.4), compute=1000, evict T1 (1638.4). Lat=max(1000, 3276.8)=3276.8
- Subgraph 1: Load T1 (1638.4), compute=100, evict T2 (1638.4). Lat=max(100, 3276.8)=3276.8
- **Total: 6553.6**

**Strategy B** (fused): subgraphs=[[0,1]], gran=[[128,128,1]], retain=[[]], trav=[null]
- Load T0 (1638.4), compute=1100, evict T2 (1638.4). T1 is ephemeral. Lat=max(1100, 3276.8)=3276.8
- **Total: 3276.8**

**Strategy C** (fused, sub-native 64x64): subgraphs=[[0,1]], gran=[[64,64,1]], retain=[[]], trav=[null]
- 4 tiles. Each: load T0 slice (409.6), compute=1100, evict T2 slice (409.6). Lat=max(1100, 819.2)=1100
- **Total: 4400.0**

### Example 3: Diamond Graph with Retention

Problem:
```json
{"widths":[128,128,128,128],"heights":[128,128,128,128],"inputs":[[0],[1],[1,2]],"outputs":[[1],[2],[3]],"base_costs":[1500,1500,1500],"op_types":["Pointwise","Pointwise","Pointwise"],"fast_memory_capacity":50000,"slow_memory_bandwidth":10,"native_granularity":[128,128]}
```

**Selective Residency**: subgraphs=[[0],[1,2]], gran=[[128,128,1],[128,128,1]], retain=[[1],[]], trav=[null,null]
- Sub0: Load T0 (1638.4), compute=1500, T1 retained (no evict). Lat=max(1500,1638.4)=1638.4
- Sub1: T1 in memory (0 load), compute=3000, T2 ephemeral, evict T3 (1638.4). Lat=max(3000,1638.4)=3000
- **Total: 4638.4**

### Example 4: MatMul with Traversal Reuse

Problem:
```json
{"widths":[128,128,128],"heights":[128,128,128],"inputs":[[0,1]],"outputs":[[2]],"base_costs":[1500],"op_types":["MatMul"],"fast_memory_capacity":25000,"slow_memory_bandwidth":10,"native_granularity":[128,128]}
```

Granularity [64,64,128]. 4 spatial tiles (2×2). K=128, k=128, n_k=1.
LHS row-strip: 64×128=8192. RHS col-strip: 128×64=8192. Output tile: 64×64=4096.

**Raster** [0,1,2,3] = (0,0),(0,1),(1,0),(1,1):
- (0,0): Load LHS0+RHS0 (16384), evict out (4096). Lat=max(1500,2048)=2048
- (0,1): Reuse LHS0, load RHS1 (8192), evict (4096). Lat=max(1500,1228.8)=1500
- (1,0): Load LHS1+RHS0 (16384), evict (4096). Lat=max(1500,2048)=2048
- (1,1): Reuse LHS1, load RHS1 (8192), evict (4096). Lat=max(1500,1228.8)=1500
- **Total: 7096.0**

**Zigzag** [0,1,3,2] = (0,0),(0,1),(1,1),(1,0):
- (0,0): 2048. (0,1): Reuse LHS0, load RHS1: 1500. (1,1): Load LHS1, reuse RHS1: 1500. (1,0): Reuse LHS1, load RHS0: 1500.
- **Total: 6548.0**

### Example 5: Chained MatMul with Split-K

Problem:
```json
{"widths":[128,128,128,128,128],"heights":[128,128,128,128,128],"inputs":[[0,1],[3,2]],"outputs":[[3],[4]],"base_costs":[2000,2000],"op_types":["MatMul","MatMul"],"fast_memory_capacity":45000,"slow_memory_bandwidth":10,"native_granularity":[128,128]}
```

**Strategy A** [128,128,128] → OOM. Op0 needs LHS(128×128)+RHS(128×128)+Out(128×128)=49152 > 45000.

**Strategy B** [128,128,32]: subgraphs=[[0,1]], n_k=ceil(128/32)=4. T3 ephemeral.
Working set: T0 full (128×128=16384) + T1 strip (128×32=4096) + T2 strip (32×128=4096) + T4 accum (128×128=16384) = 40960 < 45000.
Compute per step: 2000×32/128 + 2000×32/128 = 500+500 = 1000.

- Step 1: Load T0(16384)+T1strip(4096)+T2strip(4096)=24576. Time=2457.6. Lat=max(1000,2457.6)=2457.6
- Step 2: Reuse T0, load T1+T2 strips(8192). Time=819.2. Lat=max(1000,819.2)=1000
- Step 3: Same as step 2. Lat=1000
- Step 4: Load T1+T2 strips(8192), evict T4(16384). Time=2457.6. Lat=max(1000,2457.6)=2457.6
- **Total: 6915.2**
