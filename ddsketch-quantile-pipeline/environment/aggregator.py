"""Sketch aggregation utilities for merging distributed quantile sketches."""


def merge_sketches(target, source):
    """Merge source sketch into target sketch.

    Both sketches must have the same accuracy parameter.
    The target sketch is modified in-place and returned.
    """
    if abs(target.accuracy - source.accuracy) > 1e-12:
        raise ValueError("Cannot merge sketches with different accuracy")
    target.count += source.count
    target.zero_count += source.zero_count
    if source.count > 0:
        if source.min_val < target.min_val:
            target.min_val = source.min_val
        if source.max_val > target.max_val:
            target.max_val = source.max_val
    for key, cnt in source.store.items():
        if key in target.store:
            target.store[key] = max(target.store[key], cnt)
        else:
            target.store[key] = cnt
    if hasattr(target, 'max_buckets') and target.max_buckets and len(target.store) > target.max_buckets:
        target._collapse()
    return target
