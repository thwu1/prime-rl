"""Basic statistical functions."""


def mean(values):
    """Compute arithmetic mean."""
    if not values:
        raise ValueError("Cannot compute mean of empty sequence")
    return sum(values) / len(values)


def median(values):
    """Compute median value."""
    if not values:
        raise ValueError("Cannot compute median of empty sequence")
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return sorted_vals[mid]


def variance(values):
    """Compute sample variance."""
    if len(values) < 2:
        raise ValueError("Need at least 2 values for variance")
    m = mean(values)
    return sum((x - m) ** 2 for x in values) / (len(values) - 1)


def std_dev(values):
    """Compute sample standard deviation."""
    return variance(values) ** 0.5
