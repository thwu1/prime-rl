import math
import pytest
from calclib.core import safe_divide, classify_number, is_prime, fibonacci


class TestSafeDivide:
    def test_basic_float_division(self):
        assert safe_divide(10, 3) == pytest.approx(3.333, rel=1e-2)

    def test_zero_dividend_float(self):
        result = safe_divide(0, 0)
        assert math.isnan(result)

    def test_positive_divide_by_zero(self):
        assert safe_divide(5, 0) == float('inf')

    def test_negative_divide_by_zero(self):
        assert safe_divide(-5, 0) == float('-inf')

    def test_int_mode(self):
        assert safe_divide(10, 3, mode="int") == 3

    def test_int_mode_divide_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            safe_divide(5, 0, mode="int")

    def test_safe_mode(self):
        assert safe_divide(10, 3, mode="safe") == pytest.approx(3.333, rel=1e-2)

    def test_safe_mode_divide_by_zero(self):
        assert safe_divide(5, 0, mode="safe") == 0

    def test_unknown_mode(self):
        with pytest.raises(ValueError):
            safe_divide(1, 1, mode="unknown")

    def test_unknown_mode_zero_divisor(self):
        with pytest.raises(ValueError):
            safe_divide(1, 0, mode="unknown")


class TestClassifyNumber:
    def test_zero(self):
        assert classify_number(0) == "zero"

    def test_positive_prime(self):
        assert classify_number(7) == "positive_prime"

    def test_positive_even(self):
        assert classify_number(8) == "positive_even"

    def test_positive_odd(self):
        assert classify_number(9) == "positive_odd"

    def test_negative_even(self):
        assert classify_number(-4) == "negative_even"

    def test_negative_odd(self):
        assert classify_number(-3) == "negative_odd"

    def test_nan(self):
        assert classify_number(float('nan')) == "nan"

    def test_positive_infinity(self):
        assert classify_number(float('inf')) == "positive_infinity"

    def test_negative_infinity(self):
        assert classify_number(float('-inf')) == "negative_infinity"

    def test_positive_float(self):
        assert classify_number(3.14) == "positive_float"

    def test_negative_float(self):
        assert classify_number(-2.5) == "negative_float"

    def test_invalid_type(self):
        with pytest.raises(TypeError):
            classify_number("hello")


class TestIsPrime:
    def test_small_primes(self):
        assert is_prime(2)
        assert is_prime(3)
        assert is_prime(5)

    def test_non_primes(self):
        assert not is_prime(0)
        assert not is_prime(1)
        assert not is_prime(4)
        assert not is_prime(9)

    def test_negative(self):
        assert not is_prime(-5)


class TestFibonacci:
    def test_empty(self):
        assert fibonacci(0) == []

    def test_single(self):
        assert fibonacci(1) == [0]

    def test_iterative(self):
        assert fibonacci(7) == [0, 1, 1, 2, 3, 5, 8]

    def test_recursive(self):
        assert fibonacci(6, method="recursive") == [0, 1, 1, 2, 3, 5]

    def test_closed_form(self):
        assert fibonacci(6, method="closed") == [0, 1, 1, 2, 3, 5]

    def test_unknown_method(self):
        with pytest.raises(ValueError):
            fibonacci(5, method="unknown")
