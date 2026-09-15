from program import lcs


def test_empty():
    assert lcs("", "abc") == ""
    assert lcs("abc", "") == ""


def test_identical():
    assert lcs("abc", "abc") == "abc"


def test_no_common():
    assert lcs("abc", "xyz") == ""


def test_subsequence():
    result = lcs("abcde", "ace")
    assert result == "ace"


def test_longer():
    result = lcs("AGGTAB", "GXTXAYB")
    assert result == "GTAB"


def test_single_char():
    assert lcs("a", "a") == "a"
    assert lcs("a", "b") == ""


def test_complex():
    result = lcs("ABCBDAB", "BDCABA")
    assert len(result) == 4
