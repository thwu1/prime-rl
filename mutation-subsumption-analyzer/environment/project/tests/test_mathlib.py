import sys
sys.path.insert(0, '/app/project/src')
from mathlib import *
import pytest


def test_gcd_basic():
    assert gcd(12, 8) == 4
    assert gcd(54, 24) == 6


def test_gcd_coprime():
    assert gcd(7, 13) == 1


def test_gcd_zero():
    assert gcd(5, 0) == 5
    assert gcd(0, 7) == 7


def test_gcd_negative():
    assert gcd(-12, 8) == 4


def test_lcm_basic():
    assert lcm(4, 6) == 12
    assert lcm(3, 5) == 15


def test_lcm_zero():
    assert lcm(0, 5) == 0
    assert lcm(7, 0) == 0


def test_is_prime_small():
    assert is_prime(2) == True
    assert is_prime(3) == True
    assert is_prime(5) == True


def test_is_prime_composite():
    assert is_prime(4) == False
    assert is_prime(9) == False
    assert is_prime(15) == False


def test_is_prime_edge():
    assert is_prime(-1) == False
    assert is_prime(0) == False
    assert is_prime(1) == False


def test_is_prime_large():
    assert is_prime(97) == True
    assert is_prime(100) == False


def test_fibonacci_base():
    assert fibonacci(0) == 0
    assert fibonacci(1) == 1


def test_fibonacci_sequence():
    assert fibonacci(10) == 55
    assert fibonacci(5) == 5


def test_fibonacci_error():
    with pytest.raises(ValueError):
        fibonacci(-1)


def test_binary_search_found():
    assert binary_search([1, 3, 5, 7, 9], 5) == 2
    assert binary_search([1, 3, 5, 7, 9], 7) == 3


def test_binary_search_not_found():
    assert binary_search([1, 3, 5, 7, 9], 4) == -1
    assert binary_search([1, 3, 5, 7, 9], 6) == -1


def test_binary_search_empty():
    assert binary_search([], 1) == -1


def test_binary_search_edges():
    assert binary_search([1, 3, 5, 7, 9], 1) == 0
    assert binary_search([1, 3, 5, 7, 9], 9) == 4


def test_insertion_sort_basic():
    assert insertion_sort([3, 1, 4, 1, 5]) == [1, 1, 3, 4, 5]


def test_insertion_sort_empty():
    assert insertion_sort([]) == []


def test_insertion_sort_sorted():
    assert insertion_sort([1, 2, 3]) == [1, 2, 3]


def test_insertion_sort_reverse():
    assert insertion_sort([5, 4, 3, 2, 1]) == [1, 2, 3, 4, 5]


def test_clamp_in_range():
    assert clamp(5, 0, 10) == 5


def test_clamp_below():
    assert clamp(-5, 0, 10) == 0


def test_clamp_above():
    assert clamp(15, 0, 10) == 10


def test_weighted_average_basic():
    assert weighted_average([10, 20], [1, 1]) == 15.0
    assert weighted_average([10, 20], [1, 3]) == 17.5


def test_weighted_average_error():
    with pytest.raises(ValueError):
        weighted_average([1, 2], [1])
    with pytest.raises(ValueError):
        weighted_average([1, 2], [-1, 1])


def test_weighted_average_zero_weight():
    assert weighted_average([10, 20], [0, 0]) == 0


def test_is_sorted_ascending():
    assert is_sorted([1, 2, 3]) == True
    assert is_sorted([3, 1, 2]) == False


def test_is_sorted_descending():
    assert is_sorted([3, 2, 1], ascending=False) == True
    assert is_sorted([1, 2, 3], ascending=False) == False


def test_is_sorted_empty():
    assert is_sorted([]) == True
    assert is_sorted([1]) == True
