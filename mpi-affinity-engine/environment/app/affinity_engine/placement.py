"""MPI rank placement algorithms."""

from dataclasses import dataclass, field
from typing import Dict, List
from .topology import Topology, Core


@dataclass
class PlacementResult:
    """Result of placing MPI ranks onto a hardware topology."""
    rank_cores: Dict[int, List[Core]] = field(default_factory=dict)

    def get_rank_cores(self, rank: int) -> List[Core]:
        return self.rank_cores.get(rank, [])

    def get_rank_logical_cpus(self, rank: int) -> List[int]:
        cpus = []
        for core in self.get_rank_cores(rank):
            cpus.extend(core.logical_ids)
        return sorted(cpus)

    @property
    def num_ranks(self) -> int:
        return len(self.rank_cores)


def place_compact(topology: Topology, num_ranks: int,
                  cores_per_rank: int) -> PlacementResult:
    """Place ranks compactly, filling each NUMA domain before moving to next.

    Cores are assigned to ranks maintaining NUMA locality — each rank's cores
    should ideally come from the same NUMA domain.
    """
    total_cores = topology.num_physical_cores
    needed = num_ranks * cores_per_rank
    if needed > total_cores:
        raise ValueError(
            f"Requested {needed} cores ({num_ranks} ranks x {cores_per_rank} "
            f"cores/rank) but only {total_cores} physical cores available"
        )

    # Collect all cores and sort by physical ID for deterministic ordering
    all_cores = topology.get_all_cores()
    all_cores.sort(key=lambda c: c.physical_id)

    result = PlacementResult()
    for rank in range(num_ranks):
        start = rank * cores_per_rank
        end = start + cores_per_rank
        result.rank_cores[rank] = all_cores[start:end]

    return result


def place_scatter(topology: Topology, num_ranks: int,
                  cores_per_rank: int) -> PlacementResult:
    """Place ranks in round-robin across sockets for maximum memory bandwidth.

    Distributes ranks evenly across sockets, then across NUMA nodes within
    each socket, to maximize aggregate memory bandwidth.
    """
    total_cores = topology.num_physical_cores
    needed = num_ranks * cores_per_rank
    if needed > total_cores:
        raise ValueError(
            f"Requested {needed} cores ({num_ranks} ranks x {cores_per_rank} "
            f"cores/rank) but only {total_cores} physical cores available"
        )

    # Scatter distribution not yet implemented
    raise NotImplementedError("Scatter placement policy not yet implemented")


def place_ranks(topology: Topology, num_ranks: int, cores_per_rank: int,
                policy: str = 'compact') -> PlacementResult:
    """Place MPI ranks on topology according to the given policy."""
    if policy == 'compact':
        return place_compact(topology, num_ranks, cores_per_rank)
    elif policy == 'scatter':
        return place_scatter(topology, num_ranks, cores_per_rank)
    else:
        raise ValueError(f"Unknown placement policy: {policy}")
