import math
from project.analysis.geometry import distance, triangle_area, point_in_rect, scale_point


def test_distance_basic():
    assert abs(distance((0, 0), (3, 4)) - 5.0) < 0.01


def test_distance_same_point():
    assert distance((1, 1), (1, 1)) == 0.0


def test_triangle_area():
    area = triangle_area(3, 4, 5)
    assert abs(area - 6.0) < 0.01


def test_point_in_rect_inside():
    assert point_in_rect(5, 5, 0, 0, 10, 10) is True


def test_point_in_rect_outside():
    assert point_in_rect(15, 5, 0, 0, 10, 10) is False


def test_scale_point():
    assert scale_point((1, 2), 3) == (3, 6)
