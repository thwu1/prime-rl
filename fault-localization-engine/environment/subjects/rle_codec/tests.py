from source import rle_encode, rle_decode


def test_encode_empty():
    assert rle_encode([]) == []


def test_encode_single():
    assert rle_encode([1]) == [(1, 1)]


def test_encode_all_same():
    assert rle_encode([3, 3, 3, 3]) == [(3, 4)]


def test_decode_basic():
    assert rle_decode([(5, 3)]) == [5, 5, 5]


def test_decode_multi():
    assert rle_decode([(1, 2), (2, 3)]) == [1, 1, 2, 2, 2]


def test_encode_no_repeats():
    assert rle_encode([1, 2, 3]) == [(1, 1), (2, 1), (3, 1)]


def test_encode_mixed():
    assert rle_encode([1, 1, 2, 3, 3]) == [(1, 2), (2, 1), (3, 2)]


def test_roundtrip():
    data = [1, 1, 2, 3, 3, 3]
    assert rle_decode(rle_encode(data)) == data
