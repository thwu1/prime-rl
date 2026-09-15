from source import find_second_largest


def test_basic():
    assert find_second_largest([1, 2, 3]) == 2


def test_reverse_order():
    assert find_second_largest([3, 2, 1]) == 2


def test_negative():
    assert find_second_largest([-1, -2, -3]) == -2


def test_single_element():
    assert find_second_largest([5]) is None


def test_empty():
    assert find_second_largest([]) is None


def test_duplicates_of_max():
    assert find_second_largest([5, 5, 3]) == 3


def test_all_same():
    assert find_second_largest([7, 7, 7]) is None


def test_two_same():
    assert find_second_largest([4, 4]) is None
