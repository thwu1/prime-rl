"""Auto-generated region checker."""

def _check_classify_simple_0(x):
    return (x > 99)

def _eval_classify_simple_0(x):
    return 100

def _check_classify_simple_1(x):
    return (not x > 99) and (x > 20)

def _eval_classify_simple_1(x):
    return x + 9

def _check_classify_simple_2(x):
    return (not x > 99) and (not x > 20) and (x > -2)

def _eval_classify_simple_2(x):
    return 103

def _check_classify_simple_3(x):
    return (not x > 99) and (not x > 20) and (not x > -2)

def _eval_classify_simple_3(x):
    return 99

def _check_quadrant_0(x, y):
    return (x > 0) and (y > 0)

def _eval_quadrant_0(x, y):
    return x + y

def _check_quadrant_1(x, y):
    return (x > 0) and (not y > 0)

def _eval_quadrant_1(x, y):
    return x - y

def _check_quadrant_2(x, y):
    return (not x > 0) and (y > 0)

def _eval_quadrant_2(x, y):
    return y - x

def _check_quadrant_3(x, y):
    return (not x > 0) and (not y > 0)

def _eval_quadrant_3(x, y):
    return -(x + y)

def _check_tricky_0(x):
    return (x > 10) and (not x < 5)

def _eval_tricky_0(x):
    return x * 2

def _check_tricky_1(x):
    return (not x > 10) and (not x > 15)

def _eval_tricky_1(x):
    return x + 1

def _check_complex_classify_0(x, y):
    return (x + y > 10) and (x > 0 and y > 0)

def _eval_complex_classify_0(x, y):
    return 1

def _check_complex_classify_1(x, y):
    return (x + y > 10) and (not (x > 0 and y > 0)) and (x > 10)

def _eval_complex_classify_1(x, y):
    return 2

def _check_complex_classify_2(x, y):
    return (x + y > 10) and (not (x > 0 and y > 0)) and (not x > 10) and (y > 10)

def _eval_complex_classify_2(x, y):
    return 3

def _check_complex_classify_3(x, y):
    return (not x + y > 10) and (x - y > 5)

def _eval_complex_classify_3(x, y):
    return 5

def _check_complex_classify_4(x, y):
    return (not x + y > 10) and (not x - y > 5)

def _eval_complex_classify_4(x, y):
    return 6

def _check_nested_let_0(x, y):
    return (x - y > 0) and (x + y > 0)

def _eval_nested_let_0(x, y):
    return x - y + (x + y)

def _check_nested_let_1(x, y):
    return (x - y > 0) and (not x + y > 0)

def _eval_nested_let_1(x, y):
    return x - y - (x + y)

def _check_nested_let_2(x, y):
    return (not x - y > 0) and (x + y > 0)

def _eval_nested_let_2(x, y):
    return x + y - (x - y)

def _check_nested_let_3(x, y):
    return (not x - y > 0) and (not x + y > 0)

def _eval_nested_let_3(x, y):
    return -(x - y + (x + y))

def _check_range_check_0(x, y):
    return (x > y) and (not y > x) and (not y == x)

def _eval_range_check_0(x, y):
    return x - y

def _check_range_check_1(x, y):
    return (not x > y) and (x == y) and (not x > y)

def _eval_range_check_1(x, y):
    return 0

def _check_range_check_2(x, y):
    return (not x > y) and (not x == y) and (not x > y) and (not x == y)

def _eval_range_check_2(x, y):
    return y - x

_registry = {
    "classify_simple": [{"check": _check_classify_simple_0, "evaluate": _eval_classify_simple_0}, {"check": _check_classify_simple_1, "evaluate": _eval_classify_simple_1}, {"check": _check_classify_simple_2, "evaluate": _eval_classify_simple_2}, {"check": _check_classify_simple_3, "evaluate": _eval_classify_simple_3}],
    "quadrant": [{"check": _check_quadrant_0, "evaluate": _eval_quadrant_0}, {"check": _check_quadrant_1, "evaluate": _eval_quadrant_1}, {"check": _check_quadrant_2, "evaluate": _eval_quadrant_2}, {"check": _check_quadrant_3, "evaluate": _eval_quadrant_3}],
    "tricky": [{"check": _check_tricky_0, "evaluate": _eval_tricky_0}, {"check": _check_tricky_1, "evaluate": _eval_tricky_1}],
    "complex_classify": [{"check": _check_complex_classify_0, "evaluate": _eval_complex_classify_0}, {"check": _check_complex_classify_1, "evaluate": _eval_complex_classify_1}, {"check": _check_complex_classify_2, "evaluate": _eval_complex_classify_2}, {"check": _check_complex_classify_3, "evaluate": _eval_complex_classify_3}, {"check": _check_complex_classify_4, "evaluate": _eval_complex_classify_4}],
    "nested_let": [{"check": _check_nested_let_0, "evaluate": _eval_nested_let_0}, {"check": _check_nested_let_1, "evaluate": _eval_nested_let_1}, {"check": _check_nested_let_2, "evaluate": _eval_nested_let_2}, {"check": _check_nested_let_3, "evaluate": _eval_nested_let_3}],
    "range_check": [{"check": _check_range_check_0, "evaluate": _eval_range_check_0}, {"check": _check_range_check_1, "evaluate": _eval_range_check_1}, {"check": _check_range_check_2, "evaluate": _eval_range_check_2}],
}

def num_regions(func_name):
    return len(_registry[func_name])

def check_region(func_name, region_idx, **kwargs):
    return _registry[func_name][region_idx]["check"](**kwargs)

def evaluate_region(func_name, region_idx, **kwargs):
    return _registry[func_name][region_idx]["evaluate"](**kwargs)
