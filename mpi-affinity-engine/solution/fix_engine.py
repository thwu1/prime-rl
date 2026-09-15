#!/usr/bin/env python3
"""Fix all bugs in the MPI affinity configuration engine.

"""

import os
import sys


def read_file(path):
    """Read file with existence check."""
    if not os.path.exists(path):
        print(f"ERROR: {path} not found", file=sys.stderr)
        print(f"Contents of /app/: {os.listdir('/app/')}", file=sys.stderr)
        if os.path.isdir('/app/affinity_engine'):
            print(f"Contents of /app/affinity_engine/: "
                  f"{os.listdir('/app/affinity_engine/')}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return f.read()


def apply_fix(content, old, new, label):
    """Replace old with new in content, warn if not found."""
    if old not in content:
        print(f"WARNING: Pattern not found for '{label}' - "
              f"may already be fixed", file=sys.stderr)
        return content
    result = content.replace(old, new, 1)
    print(f"  Applied: {label}")
    return result


def fix_placement():
    """Fix compact placement and implement scatter placement."""
    path = '/app/affinity_engine/placement.py'
    content = read_file(path)

    # Fix 1: Remove global sort by physical_id in compact placement.
    # The sort destroys NUMA-local ordering on topologies with interleaved
    # core IDs (AMD EPYC NPS2: NUMA 0 has cores 0,2,4,6; NUMA 1 has 1,3,5,7).
    # get_all_cores() iterates socket -> NUMA node order, which is correct.
    content = apply_fix(content,
        '    all_cores.sort(key=lambda c: c.physical_id)\n',
        '',
        'remove physical_id sort')

    # Fix 2: Implement scatter placement (round-robin across sockets).
    scatter_old = ('    # Scatter distribution not yet implemented\n'
                   '    raise NotImplementedError('
                   '"Scatter placement policy not yet implemented")')

    scatter_new = """    num_sockets = topology.num_sockets

    # Build per-socket core pools ordered by NUMA node, then physical_id
    socket_pools = []
    for socket in topology.sockets:
        pool = []
        for numa_node in socket.numa_nodes:
            sorted_cores = sorted(numa_node.cores, key=lambda c: c.physical_id)
            pool.extend(sorted_cores)
        socket_pools.append(pool)

    # Track consumption offset per socket
    socket_offsets = [0] * num_sockets

    result = PlacementResult()
    for rank in range(num_ranks):
        socket_idx = rank % num_sockets
        offset = socket_offsets[socket_idx]
        pool = socket_pools[socket_idx]
        result.rank_cores[rank] = pool[offset:offset + cores_per_rank]
        socket_offsets[socket_idx] += cores_per_rank

    return result"""

    content = apply_fix(content, scatter_old, scatter_new, 'scatter placement')

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed: placement.py")


def fix_affinity():
    """Fix affinity mask generation to include HT siblings."""
    path = '/app/affinity_engine/affinity.py'
    content = read_file(path)

    # Fix 3: When include_ht_siblings is True, include all logical IDs
    # of each core in the mask, not just the primary one. The bug is that
    # the function ignores its include_ht_siblings parameter entirely.
    old_loop = '        mask |= (1 << core.primary_logical_id)\n'

    new_loop = ('        if include_ht_siblings:\n'
                '            for lid in core.logical_ids:\n'
                '                mask |= (1 << lid)\n'
                '        else:\n'
                '            mask |= (1 << core.primary_logical_id)\n')

    content = apply_fix(content, old_loop, new_loop, 'HT sibling masks')

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed: affinity.py")


def fix_env_generator():
    """Fix domain size computation to use physical cores, not logical CPUs."""
    path = '/app/affinity_engine/env_generator.py'
    content = read_file(path)

    # Fix 4: I_MPI_PIN_DOMAIN auto mode must divide physical cores (not
    # logical CPUs) among ranks. Using logical CPUs doubles the domain
    # size on HT systems, causing domains to overlap across NUMA boundaries.
    content = apply_fix(content,
        'topology.num_logical_cpus // num_ranks',
        'topology.num_physical_cores // num_ranks',
        'auto domain physical cores')

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed: env_generator.py")


def fix_diagnostics():
    """Fix NUMA locality check to use numa_node_id, not socket_id."""
    path = '/app/affinity_engine/diagnostics.py'
    content = read_file(path)

    # Fix 5: The NUMA locality checker must compare numa_node_id, not
    # socket_id. On multi-NPS systems (multiple NUMA nodes per socket),
    # checking socket_id misses cross-NUMA placements within the same socket.
    content = apply_fix(content,
        'domain_ids = set(c.socket_id for c in cores)',
        'domain_ids = set(c.numa_node_id for c in cores)',
        'NUMA locality check')

    with open(path, 'w') as f:
        f.write(content)
    print("Fixed: diagnostics.py")


if __name__ == '__main__':
    fix_placement()
    fix_affinity()
    fix_env_generator()
    fix_diagnostics()
    print("\nAll bugs fixed successfully.")
