from program import merge_sort


def test_empty():
    assert merge_sort([]) == []


def test_single():
    assert merge_sort([1]) == [1]


def test_sorted():
    assert merge_sort([1, 2, 3]) == [1, 2, 3]


def test_reversed():
    assert merge_sort([3, 2, 1]) == [1, 2, 3]


def test_duplicates():
    assert merge_sort([3, 1, 2, 1]) == [1, 1, 2, 3]


def test_negative():
    assert merge_sort([-3, 0, 5, -1]) == [-3, -1, 0, 5]


def test_large():
    import random
    random.seed(42)
    arr = [random.randint(-100, 100) for _ in range(50)]
    assert merge_sort(arr) == sorted(arr)
