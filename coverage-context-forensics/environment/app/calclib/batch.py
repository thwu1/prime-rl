"""Batch processing using multiprocessing."""

import multiprocessing
from calclib.core import classify_number, fibonacci


def _worker_classify(n):
    """Worker function for parallel classification."""
    return classify_number(n)


def _worker_fibonacci(args):
    """Worker function for parallel fibonacci."""
    n, method = args
    return fibonacci(n, method)


def batch_classify(numbers, n_workers=2):
    """Classify a list of numbers in parallel."""
    if not numbers:
        return []
    if n_workers <= 0:
        raise ValueError("n_workers must be positive")
    if n_workers == 1 or len(numbers) == 1:
        return [classify_number(n) for n in numbers]
    effective = min(n_workers, len(numbers))
    with multiprocessing.Pool(processes=effective) as pool:
        results = pool.map(_worker_classify, numbers)
    return results


def batch_fibonacci(specs, n_workers=2):
    """Compute fibonacci sequences in parallel."""
    if not specs:
        return []
    if n_workers <= 0:
        raise ValueError("n_workers must be positive")
    if n_workers == 1 or len(specs) == 1:
        return [fibonacci(n, method) for n, method in specs]
    effective = min(n_workers, len(specs))
    with multiprocessing.Pool(processes=effective) as pool:
        results = pool.map(_worker_fibonacci, specs)
    return results


def aggregate_results(results, operation="sum"):
    """Aggregate a list of result dictionaries."""
    if not results:
        return {}
    all_keys = set()
    for r in results:
        all_keys.update(r.keys())
    aggregated = {}
    for key in sorted(all_keys):
        values = [r[key] for r in results if key in r]
        if not values:
            continue
        if operation == "sum":
            aggregated[key] = sum(values)
        elif operation == "mean":
            aggregated[key] = sum(values) / len(values)
        elif operation == "max":
            aggregated[key] = max(values)
        elif operation == "min":
            aggregated[key] = min(values)
        else:
            raise ValueError(f"Unknown operation: {operation}")
    return aggregated
