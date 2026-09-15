from codebase.analysis.stats import mean_val, std_dev, correlate


def test_mean():
    assert mean_val([1, 2, 3]) == 2.0


def test_std_dev():
    result = std_dev([2, 4, 4, 4, 5, 5, 7, 9])
    assert abs(result - 2.0) < 0.01


def test_correlate_perfect():
    assert abs(correlate([1, 2, 3], [2, 4, 6]) - 1.0) < 0.01
