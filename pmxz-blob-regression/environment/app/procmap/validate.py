
"""Process map validation utilities.

Provides functions for validating process map strings and serialized data
without performing full deserialization.
"""


def validate_procmap_string(procmap_str):
    """Validate a process map string for structural correctness.

    Checks:
    - Non-empty input
    - Valid node:ranks;node:ranks format
    - All ranks are non-negative integers
    - No duplicate ranks
    - Contiguous rank space (0 to N-1 with no gaps)

    Args:
        procmap_str: Process map string to validate

    Returns:
        Dictionary with nprocs, nnodes, and node list

    Raises:
        ValueError: If validation fails
    """
    if not procmap_str:
        raise ValueError("Empty process map string")

    all_ranks = []
    node_names = set()

    parts = procmap_str.split(";")
    for part in parts:
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"Invalid segment (missing ':'): {part[:80]}")

        node_name, rank_str = part.split(":", 1)

        if node_name in node_names:
            raise ValueError(f"Duplicate node name: {node_name}")
        node_names.add(node_name)

        if not rank_str:
            raise ValueError(f"Empty rank list for node {node_name}")

        try:
            ranks = [int(r) for r in rank_str.split(",")]
        except ValueError as e:
            raise ValueError(f"Invalid rank number on {node_name}: {e}")

        for r in ranks:
            if r < 0:
                raise ValueError(f"Negative rank {r} on {node_name}")

        all_ranks.extend(ranks)

    # Check for duplicate ranks across all nodes
    rank_set = set(all_ranks)
    if len(rank_set) != len(all_ranks):
        seen = set()
        dupes = []
        for r in all_ranks:
            if r in seen:
                dupes.append(r)
            seen.add(r)
        raise ValueError(f"Duplicate ranks: {sorted(dupes)[:10]}")

    # Check contiguity: ranks should be 0..N-1
    expected = set(range(len(all_ranks)))
    if rank_set != expected:
        missing = sorted(expected - rank_set)[:10]
        extra = sorted(rank_set - expected)[:10]
        raise ValueError(
            f"Non-contiguous ranks: missing={missing}, extra={extra}"
        )

    return {
        "nprocs": len(all_ranks),
        "nnodes": len(node_names),
        "nodes": sorted(node_names),
    }


def validate_serialized_data(data):
    """Validate serialized process map data at the format level.

    Performs quick structural checks without full deserialization
    or decompression.

    Args:
        data: Serialized bytes to validate

    Returns:
        Dictionary with format and size information

    Raises:
        ValueError: If the data is structurally invalid
    """
    if not data:
        raise ValueError("Empty serialized data")

    if len(data) < 4:
        raise ValueError(f"Data too short ({len(data)} bytes)")

    if data[:4] == b"raw:":
        try:
            data[4:].decode('utf-8')
        except UnicodeDecodeError as e:
            raise ValueError(f"Raw payload is not valid UTF-8: {e}")
        return {"format": "raw", "payload_size": len(data) - 4}

    elif data[:4] == b"PMXZ":
        if len(data) < 9:
            raise ValueError(
                f"Blob too short for header: {len(data)} bytes, need >= 9"
            )
        version = data[4]
        if version > 2:
            raise ValueError(f"Unsupported blob version: {version}")
        return {
            "format": "blob",
            "version": version,
            "payload_size": len(data) - 9,
        }

    else:
        raise ValueError(f"Unknown format header: {data[:4].hex()}")
