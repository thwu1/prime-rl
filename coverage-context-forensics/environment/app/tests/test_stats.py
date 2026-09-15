import pytest
from calclib.stats import mean, variance, percentile, detect_outliers, correlation


class TestMean:
    def test_basic(self):
        assert mean([1, 2, 3, 4, 5]) == 3.0

    def test_single(self):
        assert mean([42]) == 42.0

    def test_empty(self):
        with pytest.raises(ValueError):
            mean([])


class TestVariance:
    def test_sample_variance(self):
        assert variance([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(4.571, rel=1e-2)

    def test_population_variance(self):
        assert variance([2, 4, 4, 4, 5, 5, 7, 9], population=True) == pytest.approx(4.0, rel=1e-2)

    def test_too_few_for_sample(self):
        with pytest.raises(ValueError):
            variance([1])

    def test_empty(self):
        with pytest.raises(ValueError):
            variance([])


class TestPercentile:
    def test_median(self):
        assert percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_q1(self):
        assert percentile([1, 2, 3, 4, 5, 6, 7, 8], 25) == pytest.approx(2.75)

    def test_single_element(self):
        assert percentile([5], 50) == 5

    def test_exact_index(self):
        assert percentile([10, 20, 30], 50) == 20

    def test_empty(self):
        with pytest.raises(ValueError):
            percentile([], 50)

    def test_out_of_range(self):
        with pytest.raises(ValueError):
            percentile([1, 2, 3], 101)


class TestDetectOutliers:
    def test_with_outliers(self):
        data = [1, 2, 2, 3, 3, 3, 4, 4, 5, 100]
        outliers = detect_outliers(data)
        assert 100 in outliers

    def test_no_outliers(self):
        data = [1, 2, 3, 4, 5]
        assert detect_outliers(data) == []

    def test_too_few_elements(self):
        assert detect_outliers([1, 2, 3]) == []

    def test_zero_iqr(self):
        assert detect_outliers([5, 5, 5, 5, 5]) == []


class TestCorrelation:
    def test_perfect_positive(self):
        assert correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)

    def test_perfect_negative(self):
        assert correlation([1, 2, 3], [6, 4, 2]) == pytest.approx(-1.0)

    def test_no_correlation(self):
        assert correlation([1, 2, 3], [5, 5, 5]) == 0.0

    def test_different_lengths(self):
        with pytest.raises(ValueError):
            correlation([1, 2], [1, 2, 3])

    def test_too_few(self):
        with pytest.raises(ValueError):
            correlation([1], [2])
