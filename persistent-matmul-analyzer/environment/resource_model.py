"""Hardware resource calculations for GPU matmul kernels.

Computes shared memory requirements and SM occupancy for
different kernel tile configurations.
"""


def compute_shared_memory(block_m, block_n, block_k, num_stages, dtype_bytes=2):
    """Calculate total shared memory for a pipelined matmul tile configuration.

    Each pipeline stage holds one tile of each input matrix:
      A tile: block_m x block_k elements
      B tile: block_k x block_n elements
    Total = (A_tile + B_tile) * dtype_bytes * num_stages
    """
    a_tile = block_m * block_k * dtype_bytes
    b_tile = block_m * block_n * dtype_bytes
    return (a_tile + b_tile) * num_stages


def compute_occupancy(shared_mem_per_block, num_warps, gpu_config):
    """Calculate max concurrent blocks per SM given resource constraints.

    Returns 0 if the configuration exceeds per-block shared memory limit.
    """
    if shared_mem_per_block > gpu_config['max_shared_mem_per_block']:
        return 0

    if shared_mem_per_block > 0:
        blocks_by_smem = gpu_config['shared_mem_per_sm'] // shared_mem_per_block
    else:
        blocks_by_smem = gpu_config['max_blocks_per_sm']

    blocks_by_warps = gpu_config['max_warps_per_sm'] // num_warps
    blocks_by_limit = gpu_config['max_blocks_per_sm']

    return min(blocks_by_smem, blocks_by_warps, blocks_by_limit)
