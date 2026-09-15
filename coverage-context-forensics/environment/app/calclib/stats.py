"""Statistical functions."""

import math


def mean(data):
    """Compute arithmetic mean."""
    if not data:
        raise ValueError("Cannot compute mean of empty list")
    return sum(data) / len(data)


def variance(data, population=False):
    """Compute variance."""
    if len(data) < 2 and not population:
        raise ValueError("Need at least 2 data points for sample variance")
    if not data:
        raise ValueError("Cannot compute variance of empty list")
    m = mean(data)
    squared_diffs = [(x - m) ** 2 for x in data]
    if population:
        return sum(squared_diffs) / len(data)
    else:
        return sum(squared_diffs) / (len(data) - 1)


def percentile(data, p):
    """Compute the p-th percentile (0-100)."""
    if not data:
        raise ValueError("Cannot compute percentile of empty list")
    if p < 0 or p > 100:
        raise ValueError(f"Percentile must be between 0 and 100, got {p}")
    sorted_data = sorted(data)
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    idx = (p / 100) * (n - 1)
    lower = int(math.floor(idx))
    upper = int(math.ceil(idx))
    if lower == upper:
        return sorted_data[lower]
    weight = idx - lower
    return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight


def detect_outliers(data, threshold=1.5):
    """Detect outliers using IQR method."""
    if len(data) < 4:
        return []
    q1 = percentile(data, 25)
    q3 = percentile(data, 75)
    iqr = q3 - q1
    if iqr == 0:
        return []
    lower_bound = q1 - threshold * iqr
    upper_bound = q3 + threshold * iqr
    return [x for x in data if x < lower_bound or x > upper_bound]


def correlation(x, y):
    """Compute Pearson correlation coefficient."""
    if len(x) != len(y):
        raise ValueError("Lists must have same length")
    if len(x) < 2:
        raise ValueError("Need at least 2 data points")
    mx = mean(x)
    my = mean(y)
    numerator = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    denom_x = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    denom_y = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return numerator / (denom_x * denom_y)
