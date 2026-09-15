# CUDA Occupancy Model Specification

This document specifies the exact algorithm for computing CUDA GPU occupancy
and finding optimal launch configurations. Your implementation must match
these semantics precisely.

## 1. Occupancy Calculation

Given a kernel's resource requirements and a GPU's architectural limits,
compute how many thread blocks can execute concurrently on a single
Streaming Multiprocessor (SM).

### Inputs

- `block_size`: number of threads per block (must be a positive multiple of `warp_size`)
- `registers_per_thread`: number of registers used by each thread (from compiler output)
- `shared_mem_bytes`: total shared memory per block in bytes (static + dynamic)
- GPU architecture parameters (from `gpu_specs.json`)

### Algorithm

1. **Warps per block**:
   ```
   warps_per_block = ceil(block_size / warp_size)
   ```

2. **Block limit from warps/threads**:
   ```
   blocks_by_warps = floor(max_warps_per_sm / warps_per_block)
   ```

3. **Block limit from architecture max**:
   ```
   blocks_by_max = max_blocks_per_sm
   ```

4. **Block limit from registers**:
   If `registers_per_thread > 0`:
   ```
   regs_per_warp = ceil(registers_per_thread * warp_size / register_alloc_granularity)
                   * register_alloc_granularity
   regs_per_block = regs_per_warp * warps_per_block
   blocks_by_regs = floor(total_registers_per_sm / regs_per_block)
   ```
   If `registers_per_thread == 0`: registers do not limit (treat as unlimited).

5. **Block limit from shared memory**:
   If `shared_mem_bytes > 0`:
   ```
   smem_per_block = ceil(shared_mem_bytes / shared_mem_alloc_granularity)
                    * shared_mem_alloc_granularity
   blocks_by_smem = floor(total_shared_mem_per_sm_bytes / smem_per_block)
   ```
   If `shared_mem_bytes == 0`: shared memory does not limit (treat as unlimited).

6. **Active blocks**:
   ```
   active_blocks = min(blocks_by_warps, blocks_by_max, blocks_by_regs, blocks_by_smem)
   ```
   where only the applicable limits are included (unlimited resources are excluded
   from the minimum computation).

7. **Active warps and occupancy**:
   ```
   active_warps = active_blocks * warps_per_block
   occupancy = active_warps / max_warps_per_sm
   ```

### Limiting Resource

The **limiting resource** is the constraint that yields the minimum number
of active blocks. When multiple resources tie at the same minimum value,
use this priority order (highest priority first):

1. `registers`
2. `shared_memory`
3. `warps`
4. `blocks`

Resources that are not applicable (e.g., shared memory when `shared_mem_bytes == 0`)
are never reported as limiting.

## 2. Variable Shared Memory

Some kernels use dynamic shared memory that depends on the block size.
These kernels specify a `shared_mem_formula` string containing a Python
expression with two variables:

- `block_size`: the number of threads per block
- `warp_size`: the GPU's warp size (always 32)

The formula must be evaluated for each candidate block size during the
optimal block size search. Only integer arithmetic operators are used
(`+`, `-`, `*`, `//`).

For kernels with `shared_mem_type == "fixed"`, the `shared_mem_bytes`
field gives the constant shared memory usage.

## 3. Optimal Block Size Search

For each kernel on each GPU, find the block size that maximizes occupancy.

### Algorithm

1. Enumerate all candidate block sizes: multiples of `warp_size` from
   `warp_size` to `max_threads_per_block` inclusive.

2. For each candidate block size:
   - Compute shared memory bytes (evaluate formula if variable, or use fixed value)
   - Compute occupancy using the algorithm in Section 1

3. Select the **largest** block size that achieves the **maximum** occupancy.
   (Among block sizes with equal maximum occupancy, prefer the largest one.)

## 4. Output Format

Your tool must produce `/app/results.json` with this structure:

```json
{
  "analysis": {
    "<kernel_id>": {
      "<gpu_id>": {
        "block_size": <int>,
        "active_blocks_per_sm": <int>,
        "active_warps_per_sm": <int>,
        "occupancy": <float>,
        "limiting_resource": "<string>"
      }
    }
  },
  "optimal": {
    "<kernel_id>": {
      "<gpu_id>": {
        "optimal_block_size": <int>,
        "optimal_occupancy": <float>
      }
    }
  }
}
```

Where:
- `analysis` contains occupancy results using each kernel's `default_block_size`
- `optimal` contains the best block size found by the search algorithm
- `occupancy` and `optimal_occupancy` are floating-point values in [0.0, 1.0]
- `limiting_resource` is one of: `"registers"`, `"shared_memory"`, `"warps"`, `"blocks"`
