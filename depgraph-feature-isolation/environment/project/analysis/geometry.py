import math
from project.core import check_positive, check_type, round_val
from project.transforms.numeric import scale, normalize_value


def distance(p1, p2):
    """Compute Euclidean distance between two 2D points."""
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return round_val(math.sqrt(dx ** 2 + dy ** 2))


def triangle_area(a, b, c):
    """Compute area of a triangle with sides a, b, c using Heron's formula."""
    check_positive(a)
    check_positive(b)
    check_positive(c)
    s = (a + b + c) / 2
    return round_val(math.sqrt(s * (s - a) * (s - b) * (s - c)))


def point_in_rect(px, py, x1, y1, x2, y2):
    """Check if point (px, py) is inside the rectangle (x1, y1)-(x2, y2)."""
    nx = normalize_value(px, x1, x2)
    ny = normalize_value(py, y1, y2)
    return 0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0


def scale_point(point, factor):
    """Scale a 2D point by a numeric factor."""
    check_type(factor, (int, float))
    return (scale(point[0], factor), scale(point[1], factor))
