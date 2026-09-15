"""CPU affinity mask generation for MPI ranks."""

from typing import List
from .topology import Core
from .placement import PlacementResult


def generate_mask(cores: List[Core], include_ht_siblings: bool = True) -> int:
    """Generate a CPU affinity bitmask for the given cores.

    Args:
        cores: List of Core objects to include in the mask
        include_ht_siblings: If True, include HyperThread sibling logical CPUs

    Returns:
        Integer bitmask where bit N is set if logical CPU N is included
    """
    mask = 0
    for core in cores:
        mask |= (1 << core.primary_logical_id)
    return mask


def mask_to_hex(mask: int) -> str:
    """Convert integer mask to hex string."""
    if mask == 0:
        return '0x0'
    return hex(mask)


def mask_to_list(mask: int) -> List[int]:
    """Convert bitmask to sorted list of CPU IDs."""
    cpus = []
    bit = 0
    temp = mask
    while temp:
        if temp & 1:
            cpus.append(bit)
        temp >>= 1
        bit += 1
    return cpus


def generate_rank_masks(placement: PlacementResult,
                        include_ht: bool = True) -> dict:
    """Generate affinity masks for all ranks in a placement.

    Returns dict mapping rank -> {mask, mask_hex, cpu_list}
    """
    result = {}
    for rank in range(placement.num_ranks):
        cores = placement.get_rank_cores(rank)
        mask = generate_mask(cores, include_ht_siblings=include_ht)
        result[rank] = {
            'mask': mask,
            'mask_hex': mask_to_hex(mask),
            'cpu_list': mask_to_list(mask)
        }
    return result
