from ..core.validation import check_type


def mean_val(values):
    check_type(values, list)
    if not values:
        return 0.0
    return sum(values) / len(values)


def std_dev(values):
    m = mean_val(values)
    if not values:
        return 0.0
    variance = sum((x - m) ** 2 for x in values) / len(values)
    return variance ** 0.5


def correlate(xs, ys):
    check_type(xs, list)
    check_type(ys, list)
    if len(xs) != len(ys):
        raise ValueError("Lists must have same length")
    mx = mean_val(xs)
    my = mean_val(ys)
    sx = std_dev(xs)
    sy = std_dev(ys)
    if sx == 0 or sy == 0:
        return 0.0
    n = len(xs)
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n
    return cov / (sx * sy)
