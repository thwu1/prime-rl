"""Basic 2D geometry primitives for curve flattening."""

import math


class Vec2:
    """2D vector with basic arithmetic operations."""

    __slots__ = ('x', 'y')

    def __init__(self, x=0.0, y=0.0):
        self.x = float(x)
        self.y = float(y)

    def __add__(self, other):
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar):
        return Vec2(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar):
        return Vec2(self.x * scalar, self.y * scalar)

    def __neg__(self):
        return Vec2(-self.x, -self.y)

    def __eq__(self, other):
        if not isinstance(other, Vec2):
            return NotImplemented
        return self.x == other.x and self.y == other.y

    def __repr__(self):
        return f"Vec2({self.x}, {self.y})"

    def dot(self, other):
        return self.x * other.x + self.y * other.y

    def cross(self, other):
        return self.x * other.y - self.y * other.x

    def length_squared(self):
        return self.x * self.x + self.y * self.y

    def length(self):
        return math.sqrt(self.length_squared())

    def normalize(self):
        l = self.length()
        if l < 1e-12:
            return Vec2(0, 0)
        return Vec2(self.x / l, self.y / l)

    def atan2(self):
        """Return atan2(y, x)."""
        return math.atan2(self.y, self.x)

    def is_nan(self):
        return math.isnan(self.x) or math.isnan(self.y)


def eval_cubic(p0, p1, p2, p3, t):
    """Evaluate cubic Bezier at parameter t. Returns Vec2."""
    m = 1.0 - t
    mm = m * m
    mt = m * t
    tt = t * t
    return p0 * (mm * m) + (p1 * (3.0 * mm) + p2 * (3.0 * mt) + p3 * tt) * t


def point_to_segment_dist(pt, a, b):
    """Minimum distance from Vec2 pt to line segment defined by tuples a, b."""
    ab = Vec2(b[0] - a[0], b[1] - a[1])
    ap = Vec2(pt.x - a[0], pt.y - a[1])
    ab_len_sq = ab.length_squared()
    if ab_len_sq < 1e-20:
        return ap.length()
    t = max(0.0, min(1.0, ap.dot(ab) / ab_len_sq))
    proj = Vec2(a[0] + t * ab.x, a[1] + t * ab.y)
    return (pt - proj).length()


def max_error_to_polyline(p0, p1, p2, p3, polyline, n_samples=200):
    """Compute maximum distance from sampled cubic points to polyline.

    polyline is a list of (x, y) tuples.
    """
    max_err = 0.0
    for i in range(n_samples + 1):
        t = i / n_samples
        pt = eval_cubic(p0, p1, p2, p3, t)
        min_dist = float('inf')
        for j in range(len(polyline) - 1):
            d = point_to_segment_dist(pt, polyline[j], polyline[j + 1])
            min_dist = min(min_dist, d)
        if min_dist < float('inf'):
            max_err = max(max_err, min_dist)
    return max_err
