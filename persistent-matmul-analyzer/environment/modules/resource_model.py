
import math


def compute_shared_memory(block_m, block_n, block_k, num_stages, dtype_bytes=2):
    """Calculate shared memory for pipelined matmul tile configuration."""
    a_tile = block_m * block_k * dtype_bytes
    b_tile = block_m * block_n * dtype_bytes
    return (a_tile + b_tile) * num_stages


def compute_occupancy(shared_mem_per_block, num_warps, gpu_specs):
    """Compute maximum concurrent thread blocks per SM."""
    if shared_mem_per_block > gpu_specs['max_shared_mem_per_block']:
        return 0
    if shared_mem_per_block > 0:
        blocks_by_smem = math.ceil(gpu_specs['shared_mem_per_sm'] / shared_mem_per_block)
    else:
        blocks_by_smem = gpu_specs['max_blocks_per_sm']
    blocks_by_warps = gpu_specs['max_warps_per_sm'] // num_warps
    blocks_by_limit = gpu_specs['max_blocks_per_sm']
    return min(blocks_by_smem, blocks_by_warps, blocks_by_limit)
