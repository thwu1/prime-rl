import pytest
from calclib.batch import batch_classify, batch_fibonacci, aggregate_results


class TestBatchClassify:
    def test_basic(self):
        result = batch_classify([7, 8, 0, -3], n_workers=2)
        assert result == ["positive_prime", "positive_even", "zero", "negative_odd"]

    def test_single_worker(self):
        result = batch_classify([2, 4], n_workers=1)
        assert result == ["positive_prime", "positive_even"]

    def test_empty(self):
        assert batch_classify([]) == []

    def test_single_item(self):
        assert batch_classify([5], n_workers=2) == ["positive_prime"]

    def test_invalid_workers(self):
        with pytest.raises(ValueError):
            batch_classify([1], n_workers=0)


class TestBatchFibonacci:
    def test_basic(self):
        result = batch_fibonacci([(5, "iterative"), (3, "recursive")], n_workers=2)
        assert result == [[0, 1, 1, 2, 3], [0, 1, 1]]

    def test_single_worker(self):
        result = batch_fibonacci([(4, "iterative")], n_workers=1)
        assert result == [[0, 1, 1, 2]]

    def test_empty(self):
        assert batch_fibonacci([]) == []


class TestAggregateResults:
    def test_sum(self):
        results = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        assert aggregate_results(results, "sum") == {"a": 4, "b": 6}

    def test_mean(self):
        results = [{"a": 2, "b": 4}, {"a": 4, "b": 8}]
        assert aggregate_results(results, "mean") == {"a": 3.0, "b": 6.0}

    def test_max(self):
        results = [{"a": 1}, {"a": 5}, {"a": 3}]
        assert aggregate_results(results, "max") == {"a": 5}

    def test_min(self):
        results = [{"a": 10}, {"a": 5}]
        assert aggregate_results(results, "min") == {"a": 5}

    def test_empty(self):
        assert aggregate_results([]) == {}

    def test_unknown_op(self):
        with pytest.raises(ValueError):
            aggregate_results([{"a": 1}], "median")

    def test_partial_keys(self):
        results = [{"a": 1, "b": 2}, {"a": 3}]
        agg = aggregate_results(results, "sum")
        assert agg["a"] == 4
        assert agg["b"] == 2
