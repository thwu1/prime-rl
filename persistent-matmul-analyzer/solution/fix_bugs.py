#!/usr/bin/env python3
"""
Fix all bugs in the GPU performance analyzer modules.

"""


def fix_tile_scheduler():
    """Bug 1: pid_n uses group_size_m instead of actual_group_size as divisor.
    This causes incorrect tile positions for partial groups where
    num_pid_m is not a multiple of group_size_m."""
    with open('/app/modules/tile_scheduler.py') as f:
        content = f.read()
    content = content.replace(
        '(tile_id % num_pid_in_group) // group_size_m',
        '(tile_id % num_pid_in_group) // actual_group_size'
    )
    with open('/app/modules/tile_scheduler.py', 'w') as f:
        f.write(content)


def fix_shared_memory():
    """Bug 2: B-tile shared memory uses block_m * block_n instead of
    block_k * block_n. In a matmul, the B tile loaded into shared memory
    has dimensions BLOCK_K x BLOCK_N (reduction dim x output columns),
    not BLOCK_M x BLOCK_N."""
    with open('/app/modules/resource_model.py') as f:
        content = f.read()
    content = content.replace(
        'b_tile = block_m * block_n * dtype_bytes',
        'b_tile = block_k * block_n * dtype_bytes'
    )
    with open('/app/modules/resource_model.py', 'w') as f:
        f.write(content)


def fix_occupancy():
    """Bug 3: Occupancy calculation uses math.ceil() instead of floor
    division (//) for blocks_by_smem. Floor division is correct because
    you cannot fit a partial thread block — the number of blocks that
    fit in shared memory must be truncated, not rounded up."""
    with open('/app/modules/resource_model.py') as f:
        content = f.read()
    content = content.replace(
        "blocks_by_smem = math.ceil(gpu_specs['shared_mem_per_sm'] / shared_mem_per_block)",
        "blocks_by_smem = gpu_specs['shared_mem_per_sm'] // shared_mem_per_block"
    )
    with open('/app/modules/resource_model.py', 'w') as f:
        f.write(content)


def fix_roofline():
    """Bug 4: Roofline compute ceiling does not account for SM utilization.
    When num_tiles < num_sms, not all SMs are active, reducing effective
    compute capacity. The compute ceiling must be scaled by
    sm_util = active_sms / num_sms."""
    with open('/app/modules/roofline.py') as f:
        content = f.read()
    content = content.replace(
        '    compute_ceiling = peak_flops\n',
        '    sm_util = active_sms / gpu_specs[\'num_sms\']\n'
        '    compute_ceiling = peak_flops * sm_util\n'
    )
    with open('/app/modules/roofline.py', 'w') as f:
        f.write(content)


if __name__ == '__main__':
    fix_tile_scheduler()
    fix_shared_memory()
    fix_occupancy()
    fix_roofline()
    print("All bugs fixed.")
