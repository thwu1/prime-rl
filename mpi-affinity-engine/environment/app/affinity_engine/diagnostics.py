"""Diagnostic checks for MPI placement configurations."""

from typing import List, Dict
from .topology import Topology
from .placement import PlacementResult


def check_numa_locality(topology: Topology,
                        placement: PlacementResult) -> List[Dict]:
    """Check if any rank's cores span multiple NUMA domains.

    Returns list of warnings for ranks with cross-NUMA placement.
    """
    warnings = []
    for rank in range(placement.num_ranks):
        cores = placement.get_rank_cores(rank)
        if not cores:
            continue

        # Check if cores span multiple memory domains
        domain_ids = set(c.socket_id for c in cores)
        if len(domain_ids) > 1:
            warnings.append({
                'rank': rank,
                'type': 'cross_numa',
                'message': f'Rank {rank} cores span multiple NUMA domains: '
                          f'{sorted(domain_ids)}',
                'severity': 'warning'
            })

    return warnings


def check_oversubscription(topology: Topology,
                           placement: PlacementResult) -> List[Dict]:
    """Check if any physical core is assigned to multiple ranks."""
    warnings = []
    core_to_ranks = {}

    for rank in range(placement.num_ranks):
        cores = placement.get_rank_cores(rank)
        for core in cores:
            if core.physical_id not in core_to_ranks:
                core_to_ranks[core.physical_id] = []
            core_to_ranks[core.physical_id].append(rank)

    for core_id, ranks in core_to_ranks.items():
        if len(ranks) > 1:
            warnings.append({
                'core': core_id,
                'type': 'oversubscription',
                'message': f'Physical core {core_id} assigned to '
                          f'multiple ranks: {ranks}',
                'severity': 'error',
                'ranks': ranks
            })

    return warnings


def check_ht_consistency(topology: Topology,
                         placement: PlacementResult,
                         include_ht: bool = True) -> List[Dict]:
    """Check HyperThreading consistency in placement."""
    warnings = []

    if not topology.ht_enabled:
        return warnings

    if not include_ht:
        return warnings

    for rank in range(placement.num_ranks):
        cores = placement.get_rank_cores(rank)
        ht_cores = [c for c in cores if c.ht_enabled]
        non_ht_cores = [c for c in cores if not c.ht_enabled]

        if ht_cores and non_ht_cores:
            warnings.append({
                'rank': rank,
                'type': 'ht_inconsistency',
                'message': f'Rank {rank} has mixed HT/non-HT cores',
                'severity': 'info'
            })

    return warnings


def generate_report(topology: Topology, num_ranks: int,
                    threads_per_rank: int,
                    placement: PlacementResult,
                    include_ht: bool = True) -> str:
    """Generate a comprehensive diagnostic report."""
    lines = []
    lines.append('=' * 60)
    lines.append('MPI Placement Diagnostic Report')
    lines.append('=' * 60)
    lines.append('')

    lines.append('Hardware Topology:')
    lines.append(f'  Name: {topology.name}')
    lines.append(f'  Sockets: {topology.num_sockets}')
    lines.append(f'  NUMA Nodes: {topology.num_numa_nodes}')
    lines.append(f'  Physical Cores: {topology.num_physical_cores}')
    lines.append(f'  Logical CPUs: {topology.num_logical_cpus}')
    lines.append(f'  HyperThreading: '
                 f'{"Enabled" if topology.ht_enabled else "Disabled"}')
    lines.append('')

    lines.append('Job Configuration:')
    lines.append(f'  MPI Ranks: {num_ranks}')
    lines.append(f'  Threads per Rank: {threads_per_rank}')
    lines.append(f'  Total Threads: {num_ranks * threads_per_rank}')
    lines.append('')

    lines.append('Rank Placement:')
    for rank in range(num_ranks):
        cores = placement.get_rank_cores(rank)
        cpus = placement.get_rank_logical_cpus(rank)
        numa_nodes = set(c.numa_node_id for c in cores)
        sockets = set(c.socket_id for c in cores)

        lines.append(f'  Rank {rank}:')
        lines.append(f'    Physical Cores: {[c.physical_id for c in cores]}')
        lines.append(f'    Logical CPUs: {cpus}')
        lines.append(f'    NUMA Nodes: {sorted(numa_nodes)}')
        lines.append(f'    Sockets: {sorted(sockets)}')
    lines.append('')

    all_warnings = []
    all_warnings.extend(check_numa_locality(topology, placement))
    all_warnings.extend(check_oversubscription(topology, placement))
    all_warnings.extend(check_ht_consistency(topology, placement, include_ht))

    if all_warnings:
        lines.append('Diagnostics:')
        for w in all_warnings:
            lines.append(f'  [{w["severity"].upper()}] {w["message"]}')
    else:
        lines.append('Diagnostics: No issues found')
    lines.append('')

    return '\n'.join(lines)
