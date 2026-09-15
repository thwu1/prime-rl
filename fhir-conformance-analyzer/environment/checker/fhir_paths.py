
"""FHIR path traversal utilities for conformance checking."""


def element_exists(obj, parts):
    """Check if a dot-separated element path exists in a FHIR resource.

    Handles traversal into nested objects and arrays. For arrays,
    checks if any element in the array satisfies the remaining path.

    Args:
        obj: Current position in the resource tree (dict, list, or scalar).
        parts: Remaining path segments to traverse.

    Returns:
        True if the path resolves to a non-None value in at least one branch.
    """
    if not parts:
        return obj is not None

    key = parts[0]
    rest = parts[1:]

    if isinstance(obj, dict):
        if key not in obj:
            return False
        val = obj[key]
        if not rest:
            return val is not None
        return element_exists(val, rest)
    elif isinstance(obj, list):
        return any(element_exists(item, parts) for item in obj)

    return False


def path_has_value(obj, parts, target):
    """Check if traversing a path through nested objects/arrays reaches a target value.

    Used primarily for discriminator matching — e.g., checking if
    category.coding.code == "laboratory" for an Observation resource.

    Args:
        obj: Current position in the resource tree.
        parts: Remaining path segments.
        target: Expected value at the end of the path.

    Returns:
        True if any traversal branch reaches the target value.
    """
    if not parts:
        return obj == target

    key = parts[0]
    rest = parts[1:]

    if isinstance(obj, dict):
        if key in obj:
            return path_has_value(obj[key], rest, target)
        return False
    elif isinstance(obj, list):
        return any(path_has_value(item, parts, target) for item in obj)

    return False
