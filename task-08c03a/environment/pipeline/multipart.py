"""Multi-dimensional partition key utilities."""

from typing import List, Tuple, Dict, Set
from itertools import product


def encode_partition_key(dimensions: List[str], values: Tuple[str, ...]) -> str:
    """Encode a multi-dimensional partition key as a single string."""
    if not dimensions:
        raise ValueError("dimensions cannot be empty")
    if len(dimensions) != len(values):
        raise ValueError(
            f"len(dimensions)={len(dimensions)} != len(values)={len(values)}"
        )
    escaped = []
    for v in values:
        v = v.replace("\\", "\\\\")
        v = v.replace("|", "\\|")
        escaped.append(v)
    return "|".join(escaped)


def decode_partition_key(dimensions: List[str], encoded_key: str) -> Dict[str, str]:
    """Decode an encoded partition key back to dimension values."""
    parts: List[str] = []
    current: List[str] = []
    i = 0
    while i < len(encoded_key):
        ch = encoded_key[i]
        if ch == "\\" and i + 1 < len(encoded_key):
            nxt = encoded_key[i + 1]
            if nxt == "|":
                current.append("|")
                i += 2
            elif nxt == "\\":
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
    dimensions: List[str], dimension_values: Dict[str, List[str]]
) -> List[str]:
    """Generate all possible encoded partition keys."""
    for dim in dimensions:
        if dim not in dimension_values:
            raise ValueError(f"Dimension '{dim}' not in dimension_values")
    value_lists = [dimension_values[dim] for dim in dimensions]
    keys = [encode_partition_key(dimensions, combo) for combo in product(*value_lists)]
    return sorted(keys)


def filter_keys_by_dimension(
    dimensions: List[str], keys: List[str], filters: Dict[str, Set[str]]
) -> List[str]:
    """Filter encoded partition keys by dimension value constraints."""
    result = []
    for key in keys:
        decoded = decode_partition_key(dimensions, key)
        if all(decoded.get(d) in allowed for d, allowed in filters.items()):
            result.append(key)
    return result


def project_keys(
    dimensions: List[str], keys: List[str], target_dimensions: List[str]
) -> List[str]:
    """Project encoded partition keys onto a subset of dimensions."""
    for td in target_dimensions:
        if td not in dimensions:
            raise ValueError(f"Target dimension '{td}' not in dimensions")
    projected = set()
    for key in keys:
        decoded = decode_partition_key(dimensions, key)
        vals = tuple(decoded[td] for td in target_dimensions)
        projected.add(encode_partition_key(target_dimensions, vals))
    return sorted(projected)
