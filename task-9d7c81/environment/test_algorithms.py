"""Test suite for algorithms module."""
import sys
sys.path.insert(0, '/app/src')
from algorithms import binary_search, gcd, is_prime, nth_fibonacci


def test_bsearch_found_middle():
    assert binary_search([1, 3, 5, 7, 9], 5) == 2


def test_bsearch_found_first():
    assert binary_search([1, 3, 5, 7, 9], 1) == 0


def test_bsearch_found_last():
    assert binary_search([1, 3, 5, 7, 9], 9) == 4


def test_bsearch_not_found():
    assert binary_search([1, 3, 5, 7, 9], 4) == -1


def test_bsearch_empty():
    assert binary_search([], 1) == -1


def test_bsearch_single_found():
    assert binary_search([42], 42) == 0


def test_bsearch_single_not_found():
    assert binary_search([42], 7) == -1


def test_gcd_basic():
    assert gcd(12, 8) == 4


def test_gcd_coprime():
    assert gcd(7, 13) == 1


def test_gcd_equal():
    assert gcd(5, 5) == 5


def test_gcd_one():
    assert gcd(1, 100) == 1


def test_prime_two():
    assert is_prime(2) is True


def test_prime_three():
    assert is_prime(3) is True


def test_prime_composites():
    assert is_prime(0) is False
    assert is_prime(1) is False
    assert is_prime(4) is False


def test_prime_large():
    assert is_prime(97) is True


def test_prime_large_composite():
    assert is_prime(91) is False


def test_prime_even():
    assert is_prime(100) is False


def test_fib_zero():
    assert nth_fibonacci(0) == 0


def test_fib_one():
    assert nth_fibonacci(1) == 1


def test_fib_small():
    assert nth_fibonacci(5) == 5
    assert nth_fibonacci(10) == 55


def test_fib_negative():
    assert nth_fibonacci(-1) == 0
