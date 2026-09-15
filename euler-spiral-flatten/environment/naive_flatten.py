"""Naive recursive subdivision curve flattener for reference/comparison."""

from geometry import Vec2


def _is_flat(p0, p1, p2, p3, tolerance):
    """Check if cubic is flat enough to approximate with a line."""
    d = p3 - p0
    d_len = d.length()
    if d_len < 1e-12:
        return (p1 - p0).length() < tolerance and (p2 - p0).length() < tolerance
    nx = -d.y / d_len
    ny = d.x / d_len
    d1 = abs((p1.x - p0.x) * nx + (p1.y - p0.y) * ny)
    d2 = abs((p2.x - p0.x) * nx + (p2.y - p0.y) * ny)
    return max(d1, d2) <= tolerance


def _subdivide(p0, p1, p2, p3):
    """Subdivide cubic at t=0.5 using de Casteljau."""
    m01 = (p0 + p1) * 0.5
    m12 = (p1 + p2) * 0.5
    m23 = (p2 + p3) * 0.5
    m012 = (m01 + m12) * 0.5
    m123 = (m12 + m23) * 0.5
    mid = (m012 + m123) * 0.5
    return (p0, m01, m012, mid), (mid, m123, m23, p3)


def flatten_cubic_naive(p0, p1, p2, p3, tolerance=0.25, max_depth=20):
    """Flatten cubic using naive recursive subdivision."""
    result = [(p0.x, p0.y)]
    _flatten_recursive(p0, p1, p2, p3, tolerance, max_depth, 0, result)
    return result


def _flatten_recursive(p0, p1, p2, p3, tolerance, max_depth, depth, result):
    if _is_flat(p0, p1, p2, p3, tolerance) or depth >= max_depth:
        result.append((p3.x, p3.y))
        return
    left, right = _subdivide(p0, p1, p2, p3)
    _flatten_recursive(*left, tolerance, max_depth, depth + 1, result)
    _flatten_recursive(*right, tolerance, max_depth, depth + 1, result)
