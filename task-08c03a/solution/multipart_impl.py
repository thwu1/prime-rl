"""Multi-dimensional partition key utilities — solution implementation."""

from typing import List, Tuple, Dict, Set
from itertools import product


def encode_partition_key(dimensions: List[str], values: Tuple[str, ...]) -> str:
    if not dimensions:
        raise ValueError("dimensions cannot be empty")
    if len(dimensions) != len(values):
        raise ValueError(
            f"len(dimensions)={len(dimensions)} != len(values)={len(values)}"
        )

    escaped_parts = []
    for v in values:
        # Escape backslashes first, then pipes
        v = v.replace("\\", "\\\\")
        v = v.replace("|", "\\|")
        escaped_parts.append(v)
    return "|".join(escaped_parts)


def decode_partition_key(dimensions: List[str], encoded_key: str) -> Dict[str, str]:
    parts: List[str] = []
    current: List[str] = []
    i = 0
    while i < len(encoded_key):
        ch = encoded_key[i]
        if ch == "\\" and i + 1 < len(encoded_key):
            next_ch = encoded_key[i + 1]
            if next_ch == "|":
                current.append("|")
                i += 2
            elif next_ch == "\\":
                current.append("\\")
                i += 2
            else:
                current.append(ch)
                i += 1
        elif ch == "|":
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(ch)
            i += 1
    parts.append("".join(current))

    if len(parts) != len(dimensions):
        raise ValueError(
            f"Decoded {len(parts)} values but expected {len(dimensions)} dimensions"
        )
    return dict(zip(dimensions, parts))


def generate_all_keys(
    dimensions: List[str],
    dimension_values: Dict[str, List[str]],
) -> List[str]:
    for dim in dimensions:
        if dim not in dimension_values:
            raise ValueError(f"Dimension '{dim}' not in dimension_values")

    value_lists = [dimension_values[dim] for dim in dimensions]
    keys = []
    for combo in product(*value_lists):
        keys.append(encode_partition_key(dimensions, combo))
    return sorted(keys)


def filter_keys_by_dimension(
    dimensions: List[str],
    keys: List[str],
    filters: Dict[str, Set[str]],
) -> List[str]:
    result = []
    for key in keys:
        decoded = decode_partition_key(dimensions, key)
        match = True
        for dim, allowed in filters.items():
            if decoded.get(dim) not in allowed:
                match = False
                break
        if match:
            result.append(key)
    return result


def project_keys(
    dimensions: List[str],
    keys: List[str],
    target_dimensions: List[str],
) -> List[str]:
    for td in target_dimensions:
        if td not in dimensions:
            raise ValueError(f"Target dimension '{td}' not in dimensions")

    projected: set = set()
    for key in keys:
        decoded = decode_partition_key(dimensions, key)
        target_values = tuple(decoded[td] for td in target_dimensions)
        projected.add(encode_partition_key(target_dimensions, target_values))
    return sorted(projected)
