
"""Process map generation and parsing.

A process map encodes the assignment of MPI-style rank IDs to compute nodes.
The text format is: "node0:0,1,...,ppn-1;node1:ppn,...,2*ppn-1;..."
where each node gets a contiguous block of ranks distributed as evenly as possible.
"""


def generate_procmap(nprocs, nnodes):
    """Generate a process map string mapping ranks to nodes.

    Distributes nprocs ranks across nnodes nodes as evenly as possible.
    Nodes with lower indices receive the extra ranks when nprocs is not
    evenly divisible by nnodes.

    Args:
        nprocs: Total number of processes (ranks 0 to nprocs-1)
        nnodes: Number of compute nodes

    Returns:
        Process map string in "node0:r0,r1,...;node1:r2,r3,..." format
    """
    if nprocs <= 0 or nnodes <= 0:
        raise ValueError("nprocs and nnodes must be positive integers")
    if nnodes > nprocs:
        raise ValueError(
            f"Cannot distribute {nprocs} processes across {nnodes} nodes "
            f"(more nodes than processes)"
        )

    base_ppn = nprocs // nnodes
    remainder = nprocs % nnodes

    parts = []
    rank = 0
    for node_idx in range(nnodes):
        ppn = base_ppn + (1 if node_idx < remainder else 0)
        ranks = list(range(rank, rank + ppn))
        rank_str = ",".join(str(r) for r in ranks)
        parts.append(f"node{node_idx}:{rank_str}")
        rank += ppn

    return ";".join(parts)


def parse_procmap(procmap_str):
    """Parse a process map string into a dictionary.

    Args:
        procmap_str: Process map in "node0:r0,r1,...;node1:..." format

    Returns:
        Dictionary mapping node names to lists of rank integers:
        {"node0": [0, 1, ...], "node1": [128, 129, ...], ...}
    """
    if not procmap_str:
        raise ValueError("Empty process map string")

    result = {}
    for part in procmap_str.split(";"):
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"Malformed segment (no ':'): {part[:80]}")

        node_name, rank_str = part.split(":", 1)
        if not rank_str:
            raise ValueError(f"Empty rank list for node {node_name}")

        ranks = [int(r) for r in rank_str.split(",")]
        result[node_name] = ranks

    return result


def get_procmap_summary(procmap_str):
    """Get a summary of a process map without full parsing.

    Returns total process count and node count by scanning separators.
    More efficient than full parsing for quick validation.
    """
    if not procmap_str:
        return {"nprocs": 0, "nnodes": 0}

    segments = procmap_str.split(";")
    nnodes = len([s for s in segments if s])
    nprocs = 0
    for seg in segments:
        if not seg:
            continue
        _, rank_str = seg.split(":", 1)
        nprocs += rank_str.count(",") + 1

    return {"nprocs": nprocs, "nnodes": nnodes}
