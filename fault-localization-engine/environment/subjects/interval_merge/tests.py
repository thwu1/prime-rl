from source import merge_intervals


def test_empty():
    assert merge_intervals([]) == []


def test_single():
    assert merge_intervals([(1, 5)]) == [(1, 5)]


def test_no_overlap():
    assert merge_intervals([(1, 2), (4, 5)]) == [(1, 2), (4, 5)]


def test_overlap():
    assert merge_intervals([(1, 4), (2, 6)]) == [(1, 6)]


def test_contained():
    assert merge_intervals([(1, 10), (3, 5)]) == [(1, 10)]


def test_adjacent():
    assert merge_intervals([(1, 3), (3, 5)]) == [(1, 5)]


def test_multiple_adjacent():
    assert merge_intervals([(1, 2), (2, 3), (3, 4)]) == [(1, 4)]


def test_mixed():
    assert merge_intervals([(1, 3), (3, 6), (8, 10), (10, 12)]) == [(1, 6), (8, 12)]
