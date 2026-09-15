"""Intel MPI environment variable configuration generator."""

from .topology import Topology
from .placement import PlacementResult
from .affinity import generate_mask, mask_to_hex, mask_to_list


def compute_pin_domain_size(topology: Topology, num_ranks: int,
                            mode: str = 'auto') -> int:
    """Compute the I_MPI_PIN_DOMAIN size for the given mode.

    Modes:
        'auto': Automatically divide available cores among ranks
        'omp': Set domain size to OMP_NUM_THREADS (returned as None)
        'socket': One domain per socket
        'numa': One domain per NUMA node
        'core': One core per domain
    """
    if mode == 'socket':
        return topology.sockets[0].num_physical_cores
    elif mode == 'numa':
        first_numa = topology.sockets[0].numa_nodes[0]
        return first_numa.num_physical_cores
    elif mode == 'core':
        return 1
    elif mode == 'auto':
        # Divide total CPU resources evenly among ranks
        return topology.num_logical_cpus // num_ranks
    elif mode == 'omp':
        return None
    else:
        raise ValueError(f"Unknown domain mode: {mode}")


def generate_env_script(topology: Topology, num_ranks: int,
                        threads_per_rank: int,
                        placement: PlacementResult,
                        domain_mode: str = 'auto',
                        placement_policy: str = 'compact') -> str:
    """Generate a shell script setting Intel MPI environment variables."""

    lines = ['#!/bin/bash', '# Intel MPI Environment Configuration',
             f'# Generated for: {topology.name}', '']

    # Basic MPI pinning
    lines.append('# Enable process pinning')
    lines.append('export I_MPI_PIN=1')
    lines.append('')

    # Pin domain
    domain_size = compute_pin_domain_size(topology, num_ranks, domain_mode)
    if domain_size is not None:
        lines.append(f'# Pin domain: {domain_mode} mode')
        lines.append(f'export I_MPI_PIN_DOMAIN={domain_size}')
    else:
        lines.append('export I_MPI_PIN_DOMAIN=omp')
    lines.append('')

    # Pin order
    if placement_policy == 'compact':
        lines.append('export I_MPI_PIN_ORDER=compact')
    elif placement_policy == 'scatter':
        lines.append('export I_MPI_PIN_ORDER=scatter')
    lines.append('')

    # OpenMP settings
    lines.append('# OpenMP Configuration')
    lines.append(f'export OMP_NUM_THREADS={threads_per_rank}')
    lines.append('export OMP_PROC_BIND=close')
    lines.append('export OMP_PLACES=cores')
    lines.append('')

    # KMP settings for Intel compiler
    lines.append('# Intel OpenMP Runtime')
    if threads_per_rank > 1:
        lines.append('export KMP_AFFINITY=granularity=fine,compact')
    lines.append('')

    # Processor list
    lines.append('# Per-rank processor assignments')
    for rank in range(num_ranks):
        cpu_list = placement.get_rank_logical_cpus(rank)
        cpu_str = ','.join(str(c) for c in cpu_list)
        lines.append(f'# Rank {rank}: CPUs {cpu_str}')
    lines.append('')

    # Debug
    lines.append('# Debug output')
    lines.append('export I_MPI_DEBUG=4')
    lines.append('')

    # Stack size
    lines.append('# Stack size for threaded applications')
    lines.append('ulimit -s unlimited')
    lines.append('')

    return '\n'.join(lines)
