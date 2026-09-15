import math

from codebase.core import check_type, check_positive, round_val
from codebase.transforms import scale, normalize_value


def distance(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return round_val(math.sqrt(dx * dx + dy * dy))


def triangle_area(a, b, c):
    check_positive(a)
    check_positive(b)
    check_positive(c)
    s = (a + b + c) / 2
    return round_val(math.sqrt(s * (s - a) * (s - b) * (s - c)))


def point_in_rect(px, py, x1, y1, x2, y2):
    nx = normalize_value(px, min(x1, x2), max(x1, x2))
    ny = normalize_value(py, min(y1, y2), max(y1, y2))
    return 0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0


def scale_point(point, factor):
    check_type(factor, (int, float))
    return (scale(point[0], factor), scale(point[1], factor))
