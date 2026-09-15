
import sys
import os
import json

import numpy as np
import pytest

sys.path.insert(0, '/app')


class TestC2STImplementation:
    """Verify the agent's C2ST implementation."""

    def test_c2st_identical_distributions(self):
        from metrics import c2st
        rng = np.random.RandomState(42)
        X = rng.randn(1000, 2)
        Y = rng.randn(1000, 2)
        score = c2st(X, Y, seed=42)
        assert isinstance(score, (float, np.floating)), "c2st must return a float"
        assert 0.45 <= float(score) <= 0.58, (
            f"C2ST on identical distributions should be ~0.5, got {score:.4f}"
        )

    def test_c2st_different_distributions(self):
        from metrics import c2st
        rng = np.random.RandomState(42)
        X = rng.randn(1000, 2)
        Y = rng.randn(1000, 2) + 5.0
        score = c2st(X, Y, seed=42)
        assert float(score) > 0.9, (
            f"C2ST on very different distributions should be >0.9, got {score:.4f}"
        )

    def test_c2st_higher_dim(self):
        from metrics import c2st
        rng = np.random.RandomState(99)
        X = rng.randn(800, 5)
        Y = rng.randn(800, 5) + 2.0
        score = c2st(X, Y, seed=99)
        assert float(score) > 0.85, (
            f"C2ST on shifted 5D distributions should be >0.85, got {score:.4f}"
        )


class TestMMDImplementation:
    """Verify the agent's MMD implementation."""

    def test_mmd_identical_distributions(self):
        from metrics import mmd
        rng = np.random.RandomState(42)
        X = rng.randn(500, 2)
        Y = rng.randn(500, 2)
        score = mmd(X, Y)
        assert isinstance(score, (float, np.floating)), "mmd must return a float"
        assert abs(float(score)) < 0.1, (
            f"MMD on identical distributions should be ~0, got {score:.6f}"
        )

    def test_mmd_different_distributions(self):
        from metrics import mmd
        rng = np.random.RandomState(42)
        X = rng.randn(500, 2)
        Y = rng.randn(500, 2) + 5.0
        score = mmd(X, Y)
        assert float(score) > 0.5, (
            f"MMD on shifted distributions should be notably positive, got {score:.6f}"
        )

    def test_mmd_is_unbiased(self):
        """Unbiased estimator can be negative for similar distributions."""
        from metrics import mmd
        rng = np.random.RandomState(7)
        X = rng.randn(200, 2)
        Y = rng.randn(200, 2)
        score = mmd(X, Y)
        # Unbiased estimator has zero expectation under H0;
        # just check it's close to zero (could be slightly negative)
        assert -0.15 <= float(score) <= 0.15, (
            f"MMD on identical distributions should be near 0, got {score:.6f}"
        )


class TestPosteriorFiles:
    """Verify posterior sample files exist and have correct format."""

    @pytest.mark.parametrize("obs_num", [1, 2, 3])
    def test_posterior_file_exists(self, obs_num):
        path = f'/app/results/posterior_{obs_num}.npy'
        assert os.path.exists(path), f"Missing {path}"

    @pytest.mark.parametrize("obs_num", [1, 2, 3])
    def test_posterior_shape(self, obs_num):
        arr = np.load(f'/app/results/posterior_{obs_num}.npy')
        assert arr.ndim == 2, f"Expected 2D array, got {arr.ndim}D"
        assert arr.shape[1] == 2, f"Expected 2 columns, got {arr.shape[1]}"
        assert arr.shape[0] >= 5000, f"Need >= 5000 samples, got {arr.shape[0]}"

    @pytest.mark.parametrize("obs_num", [1, 2, 3])
    def test_posterior_in_prior_bounds(self, obs_num):
        arr = np.load(f'/app/results/posterior_{obs_num}.npy')
        assert np.all(arr >= -1.0) and np.all(arr <= 1.0), (
            "All posterior samples must be within prior bounds [-1, 1]^2"
        )


class TestPosteriorQuality:
    """Verify posterior quality using an independent reference C2ST."""

    @staticmethod
    def _reference_c2st(X, Y, seed=42):
        """Reference C2ST for quality verification."""
        from sklearn.neural_network import MLPClassifier
        from sklearn.model_selection import KFold, cross_val_score

        X_mean = np.mean(X, axis=0)
        X_std = np.std(X, axis=0)
        X_std = np.where(X_std > 0, X_std, 1.0)
        Xn = (X - X_mean) / X_std
        Yn = (Y - X_mean) / X_std

        ndim = Xn.shape[1]
        clf = MLPClassifier(
            activation='relu',
            hidden_layer_sizes=(10 * ndim, 10 * ndim),
            max_iter=10000,
            solver='adam',
            random_state=seed,
        )
        data = np.concatenate([Xn, Yn])
        target = np.concatenate([np.zeros(Xn.shape[0]), np.ones(Yn.shape[0])])
        shuffle = KFold(n_splits=5, shuffle=True, random_state=seed)
        scores = cross_val_score(clf, data, target, cv=shuffle, scoring='accuracy')
        return float(np.mean(scores))

    @pytest.mark.parametrize("obs_num", [1, 2, 3])
    def test_posterior_quality(self, obs_num):
        """C2ST of agent's posterior vs reference must be < 0.65."""
        ref = np.loadtxt(
            f'/app/data/reference_posterior_{obs_num}.csv',
            delimiter=',', skiprows=1,
        )
        posterior = np.load(f'/app/results/posterior_{obs_num}.npy')

        n = min(5000, len(ref), len(posterior))
        score = self._reference_c2st(posterior[:n], ref[:n], seed=42)
        assert score < 0.65, (
            f"Observation {obs_num}: C2ST = {score:.4f}, must be < 0.65"
        )


class TestResultsFile:
    """Verify the metrics.json results file."""

    def test_metrics_json_exists(self):
        assert os.path.exists('/app/results/metrics.json'), (
            "Missing /app/results/metrics.json"
        )

    def test_metrics_json_format(self):
        with open('/app/results/metrics.json') as f:
            results = json.load(f)
        for i in range(1, 4):
            key = f'obs_{i}'
            assert key in results, f"Missing key: {key}"
            assert 'c2st' in results[key], f"Missing 'c2st' in {key}"
            val = results[key]['c2st']
            assert isinstance(val, (int, float)), (
                f"c2st value must be numeric, got {type(val)}"
            )
            assert 0.0 <= val <= 1.0, f"c2st must be in [0, 1], got {val}"
