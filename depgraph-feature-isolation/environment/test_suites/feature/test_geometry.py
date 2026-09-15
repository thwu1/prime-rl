from codebase.analysis.geometry import distance, triangle_area, point_in_rect, scale_point


def test_distance_basic():
    assert distance((0, 0), (3, 4)) == 5.0


def test_distance_same_point():
    assert distance((1, 1), (1, 1)) == 0.0


def test_triangle_area():
    assert triangle_area(3, 4, 5) == 6.0


def test_point_in_rect_inside():
    assert point_in_rect(5, 5, 0, 0, 10, 10) == True


def test_point_in_rect_outside():
    assert point_in_rect(15, 5, 0, 0, 10, 10) == False


def test_scale_point():
    assert scale_point((1, 2), 3) == (3, 6)
