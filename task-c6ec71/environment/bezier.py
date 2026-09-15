"""Bézier curve types and basic operations."""

import math


class Point:
    __slots__ = ('x', 'y')

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)

    def __add__(self, other):
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, s):
        return Point(self.x * s, self.y * s)

    def __rmul__(self, s):
        return Point(self.x * s, self.y * s)

    def __neg__(self):
        return Point(-self.x, -self.y)

    def dot(self, other):
        return self.x * other.x + self.y * other.y

    def norm_sq(self):
        return self.x * self.x + self.y * self.y

    def norm(self):
        return math.sqrt(self.norm_sq())

    def __repr__(self):
        return f"Point({self.x}, {self.y})"


class QuadBez:
    """Quadratic Bézier curve defined by three control points."""
    __slots__ = ('p0', 'p1', 'p2')

    def __init__(self, p0, p1, p2):
        self.p0 = p0
        self.p1 = p1
        self.p2 = p2

    def eval_at(self, t):
        mt = 1.0 - t
        return mt * mt * self.p0 + 2.0 * mt * t * self.p1 + t * t * self.p2

    def deriv_at(self, t):
        """First derivative at parameter t."""
        mt = 1.0 - t
        return 2.0 * (mt * (self.p1 - self.p0) + t * (self.p2 - self.p1))

    def speed_at(self, t):
        """Magnitude of the derivative at parameter t."""
        d = self.deriv_at(t)
        return d.norm()

    def subdivide(self, t=0.5):
        """De Casteljau subdivision. Returns two QuadBez curves."""
        m01 = (1 - t) * self.p0 + t * self.p1
        m12 = (1 - t) * self.p1 + t * self.p2
        mid = (1 - t) * m01 + t * m12
        return QuadBez(self.p0, m01, mid), QuadBez(mid, m12, self.p2)

    @property
    def chord_len(self):
        return (self.p2 - self.p0).norm()

    @property
    def polygon_len(self):
        return (self.p1 - self.p0).norm() + (self.p2 - self.p1).norm()

    def __repr__(self):
        return f"QuadBez({self.p0}, {self.p1}, {self.p2})"


class CubicBez:
    """Cubic Bézier curve defined by four control points."""
    __slots__ = ('p0', 'p1', 'p2', 'p3')

    def __init__(self, p0, p1, p2, p3):
        self.p0 = p0
        self.p1 = p1
        self.p2 = p2
        self.p3 = p3

    def eval_at(self, t):
        mt = 1.0 - t
        return (mt ** 3 * self.p0 + 3.0 * mt * mt * t * self.p1
                + 3.0 * mt * t * t * self.p2 + t ** 3 * self.p3)

    def deriv_at(self, t):
        """First derivative at parameter t."""
        mt = 1.0 - t
        return (3.0 * mt * mt * (self.p1 - self.p0)
                + 6.0 * mt * t * (self.p2 - self.p1)
                + 3.0 * t * t * (self.p3 - self.p2))

    def second_deriv_at(self, t):
        """Second derivative at parameter t."""
        mt = 1.0 - t
        return (6.0 * (mt * (self.p2 - 2.0 * self.p1 + self.p0)
                       + t * (self.p3 - 2.0 * self.p2 + self.p1)))

    def speed_at(self, t):
        d = self.deriv_at(t)
        return d.norm()

    def subdivide(self, t=0.5):
        """De Casteljau subdivision. Returns two CubicBez curves."""
        m01 = (1 - t) * self.p0 + t * self.p1
        m12 = (1 - t) * self.p1 + t * self.p2
        m23 = (1 - t) * self.p2 + t * self.p3
        m012 = (1 - t) * m01 + t * m12
        m123 = (1 - t) * m12 + t * m23
        mid = (1 - t) * m012 + t * m123
        return (CubicBez(self.p0, m01, m012, mid),
                CubicBez(mid, m123, m23, self.p3))

    @property
    def chord_len(self):
        return (self.p3 - self.p0).norm()

    @property
    def polygon_len(self):
        return ((self.p1 - self.p0).norm() + (self.p2 - self.p1).norm()
                + (self.p3 - self.p2).norm())

    def control_points_x(self):
        return [self.p0.x, self.p1.x, self.p2.x, self.p3.x]

    def control_points_y(self):
        return [self.p0.y, self.p1.y, self.p2.y, self.p3.y]

    def __repr__(self):
        return f"CubicBez({self.p0}, {self.p1}, {self.p2}, {self.p3})"


def make_quad(px, py):
    """Construct a QuadBez from coordinate lists."""
    return QuadBez(Point(px[0], py[0]), Point(px[1], py[1]), Point(px[2], py[2]))


def make_cubic(px, py):
    """Construct a CubicBez from coordinate lists."""
    return CubicBez(Point(px[0], py[0]), Point(px[1], py[1]),
                    Point(px[2], py[2]), Point(px[3], py[3]))
