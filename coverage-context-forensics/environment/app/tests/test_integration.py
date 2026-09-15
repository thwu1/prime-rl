import pytest
from calclib.core import safe_divide, classify_number, fibonacci
from calclib.stats import mean, variance, detect_outliers
from calclib.batch import batch_classify, batch_fibonacci, aggregate_results


class TestIntegration:
    def test_fibonacci_stats(self):
        fibs = fibonacci(10)
        m = mean(fibs)
        v = variance(fibs)
        assert m > 0
        assert v > 0

    def test_batch_classify_and_stats(self):
        numbers = list(range(-5, 20))
        results = batch_classify(numbers, n_workers=2)
        assert len(results) == 25
        primes = [n for n, r in zip(numbers, results) if r == "positive_prime"]
        assert 2 in primes
        assert 7 in primes

    def test_classify_and_divide(self):
        result = safe_divide(10, 3, mode="float")
        category = classify_number(result)
        assert category == "positive_float"

    def test_outlier_in_fibonacci(self):
        fibs = fibonacci(15)
        data = fibs + [10000]
        outliers = detect_outliers(data)
        assert 10000 in outliers

    def test_batch_fib_aggregate(self):
        specs = [(5, "iterative"), (8, "iterative"), (10, "iterative")]
        results = batch_fibonacci(specs, n_workers=2)
        stats_list = []
        for seq in results:
            if len(seq) >= 2:
                stats_list.append({"mean": mean(seq), "length": float(len(seq))})
        agg = aggregate_results(stats_list, "mean")
        assert "mean" in agg
        assert "length" in agg
