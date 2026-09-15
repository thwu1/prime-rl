import sys
sys.path.insert(0, '/app')
from target.mathlib import (abs_val, clamp, linear_search, is_sorted,
                            dot_product, mean, variance, gcd, is_leap_year,
                            is_valid_triangle)


def test_abs_val_positive():
    assert abs_val(5) == 5


def test_abs_val_negative():
    assert abs_val(-3) == 3


def test_clamp_within():
    assert clamp(5, 0, 10) == 5


def test_clamp_below():
    assert clamp(-5, 0, 10) == 0


def test_linear_search_found():
    assert linear_search([1, 2, 3, 4, 5], 3) == 2


def test_linear_search_not_found():
    assert linear_search([1, 2, 3], 7) == -1


def test_is_sorted_true():
    assert is_sorted([1, 2, 3, 4]) == True


def test_dot_product():
    assert dot_product([1, 2, 3], [4, 5, 6]) == 32


def test_mean():
    assert mean([2, 4, 6]) == 4.0


def test_variance():
    result = variance([2, 4, 6, 8])
    assert abs(result - 20.0 / 3.0) < 0.001


def test_gcd():
    assert gcd(12, 8) == 4


def test_is_leap_year():
    assert is_leap_year(2000) == True
    assert is_leap_year(1900) == False


def test_is_valid_triangle():
    assert is_valid_triangle(3, 4, 5) == True
