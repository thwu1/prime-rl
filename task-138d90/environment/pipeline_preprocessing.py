"""Data preprocessing for the evaluation pipeline.

Handles range filtering and ground truth quality filtering
for 3D object detection evaluation.
"""


def filter_by_range(entries, max_range):
    """Remove entries beyond max_range from the ego-vehicle origin.

    Computes range as the maximum absolute coordinate and excludes
    entries at or beyond the threshold.

    Args:
        entries: List of dicts with 'tx', 'ty', 'tz' fields.
        max_range: Maximum range in meters (exclusive).

    Returns:
        Filtered list of entries within range.
    """
    filtered = []
    for entry in entries:
        dist = max(abs(entry['tx']), abs(entry['ty']), abs(entry['tz']))
        if dist < max_range:
            filtered.append(entry)
    return filtered


def filter_zero_interior(gt_entries):
    """Remove ground truth entries with zero interior LiDAR points."""
    return [g for g in gt_entries if g.get('num_interior_pts', 1) > 0]
