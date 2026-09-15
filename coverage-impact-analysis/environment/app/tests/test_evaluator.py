import pytest
from src.evaluator import Evaluator, EvalError


class TestEvaluator:
    def test_literal_int(self):
        e = Evaluator()
        assert e.evaluate(42) == 42

    def test_literal_float(self):
        e = Evaluator()
        assert e.evaluate(3.14) == 3.14

    def test_variable(self):
        e = Evaluator(variables={'x': 10})
        assert e.evaluate('x') == 10

    def test_string_number(self):
        e = Evaluator()
        assert e.evaluate('3.14') == 3.14

    def test_unknown_variable(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="Unknown variable"):
            e.evaluate('undefined')

    def test_addition(self):
        e = Evaluator()
        assert e.evaluate(['+', 3, 4]) == 7

    def test_subtraction(self):
        e = Evaluator()
        assert e.evaluate(['-', 10, 3]) == 7

    def test_multiplication(self):
        e = Evaluator()
        assert e.evaluate(['*', 6, 7]) == 42

    def test_division(self):
        e = Evaluator()
        assert e.evaluate(['/', 10, 2]) == 5.0

    def test_modulo(self):
        e = Evaluator()
        assert e.evaluate(['%', 10, 3]) == 1

    def test_division_by_zero_safe(self):
        e = Evaluator(safe_mode=True)
        assert e.evaluate(['/', 1, 0]) == float('inf')

    def test_division_by_zero_unsafe(self):
        e = Evaluator(safe_mode=False)
        with pytest.raises(EvalError, match="Division by zero"):
            e.evaluate(['/', 1, 0])

    def test_power_safe_large_exponent(self):
        e = Evaluator(safe_mode=True)
        with pytest.raises(EvalError, match="Exponent too large"):
            e.evaluate(['**', 2, 200])

    def test_power_unsafe_large_exponent(self):
        e = Evaluator(safe_mode=False)
        result = e.evaluate(['**', 2, 200])
        assert result == 2 ** 200

    def test_power_safe_small_exponent(self):
        e = Evaluator(safe_mode=True)
        assert e.evaluate(['**', 2, 10]) == 1024

    def test_let_expression(self):
        e = Evaluator()
        result = e.evaluate(['let', 'x', 5, ['+', 'x', 1]])
        assert result == 6

    def test_let_restores_variable(self):
        e = Evaluator(variables={'x': 100})
        result = e.evaluate(['let', 'x', 5, 'x'])
        assert result == 5
        assert e.variables['x'] == 100

    def test_let_removes_new_variable(self):
        e = Evaluator()
        e.evaluate(['let', 'tmp', 42, 'tmp'])
        assert 'tmp' not in e.variables

    def test_if_true(self):
        e = Evaluator()
        assert e.evaluate(['if', 1, 42, 99]) == 42

    def test_if_false_with_else(self):
        e = Evaluator()
        assert e.evaluate(['if', 0, 42, 99]) == 99

    def test_if_false_no_else(self):
        e = Evaluator()
        assert e.evaluate(['if', 0, 42]) == 0

    def test_call_abs(self):
        e = Evaluator()
        assert e.evaluate(['call', 'abs', -5]) == 5

    def test_call_sqrt(self):
        e = Evaluator()
        assert e.evaluate(['call', 'sqrt', 16]) == 4.0

    def test_call_ceil(self):
        e = Evaluator()
        assert e.evaluate(['call', 'ceil', 3.2]) == 4

    def test_call_floor(self):
        e = Evaluator()
        assert e.evaluate(['call', 'floor', 3.8]) == 3

    def test_call_unknown_function(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="Unknown function"):
            e.evaluate(['call', 'nonexistent'])

    def test_call_function_error(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="Function error"):
            e.evaluate(['call', 'sqrt', -1])

    def test_empty_expression(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="Empty expression"):
            e.evaluate([])

    def test_invalid_type(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="Invalid expression type"):
            e.evaluate({})

    def test_operator_wrong_args(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="requires 2 arguments"):
            e.evaluate(['+', 1])

    def test_unknown_operator(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="Unknown operator"):
            e.evaluate(['??', 1, 2])

    def test_let_invalid_name(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="must be a string"):
            e.evaluate(['let', 123, 5, 'x'])

    def test_let_wrong_length(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="let requires"):
            e.evaluate(['let', 'x', 5])

    def test_if_wrong_length(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="if requires"):
            e.evaluate(['if', 1])

    def test_call_no_args(self):
        e = Evaluator()
        with pytest.raises(EvalError, match="call requires"):
            e.evaluate(['call'])
