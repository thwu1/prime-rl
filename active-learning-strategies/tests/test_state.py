"""Tests for active learning query strategies, stopping criteria, and pipeline.

"""

import json
import os
import subprocess
import sys

import numpy as np
import pytest
from scipy.stats import entropy as scipy_entropy
from sklearn.metrics import cohen_kappa_score, pairwise_distances

# ---------------------------------------------------------------------------
# Data generation helpers (must mirror pipeline.py exactly)
# ---------------------------------------------------------------------------

def gen_proba(seed=42, n_samples=50, n_classes=4):
    rng = np.random.RandomState(seed)
    alpha = rng.uniform(0.1, 2.0, size=n_classes)
    return rng.dirichlet(alpha, size=n_samples)


def gen_embeddings(seed=42, n_samples=50, n_dims=16):
    return np.random.RandomState(seed).randn(n_samples, n_dims)


def gen_mc_proba(seed=42, n_samples=50, n_mc=10, n_classes=4):
    rng = np.random.RandomState(seed)
    base = rng.dirichlet(np.ones(n_classes), size=n_samples)
    proba_mc = np.zeros((n_samples, n_mc, n_classes))
    for t in range(n_mc):
        noise = rng.normal(0, 0.1, size=(n_samples, n_classes))
        noisy = np.clip(base + noise, 1e-6, None)
        proba_mc[:, t, :] = noisy / noisy.sum(axis=1, keepdims=True)
    return proba_mc


def gen_pred_history(seed=42, n_samples=30, n_classes=4, n_steps=6):
    rng = np.random.RandomState(seed)
    base = rng.randint(0, n_classes, size=n_samples)
    history = [base.copy()]
    for step in range(1, n_steps):
        prev = history[-1].copy()
        n_changes = max(0, n_samples // (step + 1))
        idx = rng.choice(n_samples, size=n_changes, replace=False)
        prev[idx] = rng.randint(0, n_classes, size=n_changes)
        history.append(prev)
    return history


# ---------------------------------------------------------------------------
# Reference implementations
# ---------------------------------------------------------------------------

def _ref_cosine_dist(a, b):
    sim = a @ b.T
    na = np.linalg.norm(a, axis=1)[:, np.newaxis]
    nb = np.linalg.norm(b, axis=1)[np.newaxis, :]
    sim = np.clip(sim / (na * nb), -1.0, 1.0)
    return np.arccos(sim) / np.pi


def ref_least_confidence(proba, n):
    return np.sort(np.argpartition(np.amax(proba, axis=1), n)[:n])


def ref_breaking_ties(proba, n):
    margins = np.array([np.sort(r)[-1] - np.sort(r)[-2] for r in proba])
    return np.sort(np.argpartition(margins, n)[:n])


def ref_prediction_entropy(proba, n):
    ent = np.array([scipy_entropy(r) for r in proba])
    return np.sort(np.argpartition(-ent, n)[:n])


def ref_bald(proba_mc, n, eps=1e-8):
    p_mean = np.mean(proba_mc, axis=1)
    h_model = -np.sum(p_mean * np.log2(p_mean + eps), axis=-1)
    h_expected = -np.mean(
        np.sum(proba_mc * np.log2(proba_mc + eps), axis=-1), axis=1
    )
    scores = h_model - h_expected
    return np.sort(np.argpartition(-scores, n)[:n])


def ref_greedy_coreset(emb, idx_u, idx_l, n, metric="cosine"):
    if metric == "cosine":
        dist_fn = _ref_cosine_dist
    else:
        dist_fn = lambda a, b: pairwise_distances(a, b, metric="euclidean")
    selected = []
    for _ in range(n):
        if selected:
            sel_global = idx_u[np.array(selected)]
            idx_s = np.concatenate([idx_l, sel_global]).astype(np.int64)
        else:
            idx_s = idx_l.astype(np.int64)
        d = dist_fn(emb[idx_u], emb[idx_s])
        min_d = np.amin(d, axis=1)
        for s in selected:
            min_d[s] = -np.inf
        selected.append(int(np.argmax(min_d)))
    return np.sort(np.array(selected))


def ref_lightweight_coreset(emb, n, metric="cosine", seed=None):
    rng = np.random.RandomState(seed)
    centroid = np.mean(emb, axis=0, keepdims=True)
    if metric == "cosine":
        dists = _ref_cosine_dist(emb, centroid).ravel()
    else:
        dists = pairwise_distances(emb, centroid, metric="euclidean").ravel()
    dsq = np.square(dists)
    p = 0.5 / emb.shape[0] + 0.5 * dsq / dsq.sum()
    p = p / p.sum()
    return np.sort(rng.choice(emb.shape[0], n, replace=False, p=p))


def ref_kappa_stop(hist, nc, ws=3, kt=0.99):
    decisions, kappas, last = [], [], None
    labels = np.arange(nc)
    for preds in hist:
        if last is None:
            last = preds
            decisions.append(False)
            continue
        k = (
            1.0
            if np.array_equal(preds, last)
            else cohen_kappa_score(preds, last, labels=labels)
        )
        kappas.append(k)
        last = preds
        if len(kappas) < ws:
            decisions.append(False)
        else:
            decisions.append(bool(np.mean(kappas[-ws:]) >= kt))
    return decisions


def ref_uncertainty_stop(proba, indices, nc, thresh=0.05):
    ent = np.apply_along_axis(scipy_entropy, 1, proba[indices])
    return bool(np.mean(ent / np.log(nc)) < thresh)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _app_on_path():
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    yield


# ---------------------------------------------------------------------------
# Query strategy tests
# ---------------------------------------------------------------------------

class TestLeastConfidence:
    def test_basic(self):
        from strategies import least_confidence
        proba = gen_proba()
        np.testing.assert_array_equal(
            least_confidence(proba, 5), ref_least_confidence(proba, 5)
        )

    def test_n10_alt_seed(self):
        from strategies import least_confidence
        proba = gen_proba(seed=99)
        np.testing.assert_array_equal(
            least_confidence(proba, 10), ref_least_confidence(proba, 10)
        )

    def test_output_shape_and_bounds(self):
        from strategies import least_confidence
        proba = gen_proba()
        result = least_confidence(proba, 5)
        assert result.shape == (5,)
        assert len(set(result.tolist())) == 5
        assert np.all(result >= 0) and np.all(result < 50)


class TestBreakingTies:
    def test_basic(self):
        from strategies import breaking_ties
        proba = gen_proba()
        np.testing.assert_array_equal(
            breaking_ties(proba, 5), ref_breaking_ties(proba, 5)
        )

    def test_n10_alt_seed(self):
        from strategies import breaking_ties
        proba = gen_proba(seed=99)
        np.testing.assert_array_equal(
            breaking_ties(proba, 10), ref_breaking_ties(proba, 10)
        )

    def test_selects_uncertain_not_confident(self):
        """Selected samples must have SMALL margins (high uncertainty)."""
        from strategies import breaking_ties
        proba = gen_proba()
        result = breaking_ties(proba, 5)
        margins = np.array([np.sort(r)[-1] - np.sort(r)[-2] for r in proba])
        assert np.mean(margins[result]) < np.mean(
            np.delete(margins, result)
        ), "breaking_ties should select samples with SMALL margins"


class TestPredictionEntropy:
    def test_basic(self):
        from strategies import prediction_entropy
        proba = gen_proba()
        np.testing.assert_array_equal(
            prediction_entropy(proba, 5), ref_prediction_entropy(proba, 5)
        )

    def test_n10_alt_seed(self):
        from strategies import prediction_entropy
        proba = gen_proba(seed=99)
        np.testing.assert_array_equal(
            prediction_entropy(proba, 10), ref_prediction_entropy(proba, 10)
        )


class TestBALD:
    def test_basic(self):
        from strategies import bald_scores
        mc = gen_mc_proba()
        np.testing.assert_array_equal(bald_scores(mc, 5), ref_bald(mc, 5))

    def test_n10_alt_seed(self):
        from strategies import bald_scores
        mc = gen_mc_proba(seed=99)
        np.testing.assert_array_equal(bald_scores(mc, 10), ref_bald(mc, 10))

    def test_scores_nonneg(self):
        """BALD = H[mean] - E[H] should be >= 0 for any valid probability."""
        from strategies import bald_scores
        mc = gen_mc_proba()
        result = bald_scores(mc, 5)
        assert result.shape == (5,)
        assert len(set(result.tolist())) == 5


class TestCosineDistance:
    def test_identity(self):
        """Distance of a vector to itself should be ~0."""
        from strategies import _cosine_distance
        v = np.array([[1.0, 2.0, 3.0]])
        d = _cosine_distance(v, v)
        np.testing.assert_allclose(d, 0.0, atol=1e-10)

    def test_orthogonal(self):
        """Orthogonal vectors should have cosine distance 0.5."""
        from strategies import _cosine_distance
        a = np.array([[1.0, 0.0]])
        b = np.array([[0.0, 1.0]])
        d = _cosine_distance(a, b)
        np.testing.assert_allclose(d, 0.5, atol=1e-10)

    def test_opposite(self):
        """Anti-parallel vectors should have cosine distance 1.0."""
        from strategies import _cosine_distance
        a = np.array([[1.0, 0.0]])
        b = np.array([[-1.0, 0.0]])
        d = _cosine_distance(a, b)
        np.testing.assert_allclose(d, 1.0, atol=1e-10)

    def test_pairwise_shape(self):
        from strategies import _cosine_distance
        a = np.random.randn(5, 8)
        b = np.random.randn(3, 8)
        d = _cosine_distance(a, b)
        assert d.shape == (5, 3)

    def test_matches_reference(self):
        from strategies import _cosine_distance
        rng = np.random.RandomState(7)
        a = rng.randn(10, 8)
        b = rng.randn(6, 8)
        np.testing.assert_allclose(
            _cosine_distance(a, b), _ref_cosine_dist(a, b), atol=1e-12
        )


class TestGreedyCoreset:
    def test_cosine(self):
        from strategies import greedy_coreset
        emb = gen_embeddings()
        idx_l, idx_u = np.arange(10), np.arange(10, 50)
        np.testing.assert_array_equal(
            greedy_coreset(emb, idx_u, idx_l, 5, distance_metric="cosine"),
            ref_greedy_coreset(emb, idx_u, idx_l, 5, metric="cosine"),
        )

    def test_euclidean(self):
        from strategies import greedy_coreset
        emb = gen_embeddings()
        idx_l, idx_u = np.arange(10), np.arange(10, 50)
        np.testing.assert_array_equal(
            greedy_coreset(emb, idx_u, idx_l, 5, distance_metric="euclidean"),
            ref_greedy_coreset(emb, idx_u, idx_l, 5, metric="euclidean"),
        )

    def test_unique_within_bounds(self):
        from strategies import greedy_coreset
        emb = gen_embeddings()
        idx_l, idx_u = np.arange(10), np.arange(10, 50)
        result = greedy_coreset(emb, idx_u, idx_l, 5)
        assert len(set(result.tolist())) == 5
        assert np.all(result >= 0) and np.all(result < 40)

    def test_cosine_alt_seed(self):
        from strategies import greedy_coreset
        emb = gen_embeddings(seed=77)
        idx_l, idx_u = np.arange(8), np.arange(8, 50)
        np.testing.assert_array_equal(
            greedy_coreset(emb, idx_u, idx_l, 4, distance_metric="cosine"),
            ref_greedy_coreset(emb, idx_u, idx_l, 4, metric="cosine"),
        )


class TestLightweightCoreset:
    def test_cosine(self):
        from strategies import lightweight_coreset
        emb = gen_embeddings()
        np.testing.assert_array_equal(
            lightweight_coreset(emb, 5, distance_metric="cosine", seed=42),
            ref_lightweight_coreset(emb, 5, metric="cosine", seed=42),
        )

    def test_euclidean(self):
        from strategies import lightweight_coreset
        emb = gen_embeddings()
        np.testing.assert_array_equal(
            lightweight_coreset(emb, 5, distance_metric="euclidean", seed=42),
            ref_lightweight_coreset(emb, 5, metric="euclidean", seed=42),
        )

    def test_different_seed(self):
        from strategies import lightweight_coreset
        emb = gen_embeddings()
        r1 = lightweight_coreset(emb, 5, seed=42)
        r2 = lightweight_coreset(emb, 5, seed=99)
        assert not np.array_equal(r1, r2)


# ---------------------------------------------------------------------------
# Stopping criteria tests
# ---------------------------------------------------------------------------

class TestKappaAverage:
    def test_decisions(self):
        from stopping import kappa_average_stop
        hist = gen_pred_history()
        result = kappa_average_stop(hist, 4, window_size=3, kappa_threshold=0.99)
        expected = ref_kappa_stop(hist, 4, ws=3, kt=0.99)
        assert result == expected

    def test_first_is_false(self):
        from stopping import kappa_average_stop
        hist = gen_pred_history()
        result = kappa_average_stop(hist, 4)
        assert result[0] is False

    def test_perfect_agreement_stops(self):
        from stopping import kappa_average_stop
        preds = np.array([0, 1, 2, 3, 0, 1, 2, 3])
        hist = [preds.copy() for _ in range(5)]
        result = kappa_average_stop(hist, 4, window_size=3, kappa_threshold=0.99)
        assert result[0] is False
        assert result[-1] is True

    def test_length_matches_history(self):
        from stopping import kappa_average_stop
        hist = gen_pred_history()
        result = kappa_average_stop(hist, 4)
        assert len(result) == len(hist)


class TestOverallUncertainty:
    def test_stop_when_certain(self):
        from stopping import overall_uncertainty_stop
        proba = np.zeros((20, 4))
        proba[:, 0] = 0.9997
        proba[:, 1:] = 0.0001
        assert overall_uncertainty_stop(proba, np.arange(20), 4, threshold=0.05) is True

    def test_continue_when_uncertain(self):
        from stopping import overall_uncertainty_stop
        proba = np.ones((20, 4)) / 4
        assert overall_uncertainty_stop(proba, np.arange(20), 4, threshold=0.05) is False

    def test_with_generated_data(self):
        from stopping import overall_uncertainty_stop
        proba = gen_proba()
        indices = np.arange(10, 50)
        result = overall_uncertainty_stop(proba, indices, 4, threshold=0.05)
        expected = ref_uncertainty_stop(proba, indices, 4, thresh=0.05)
        assert result == expected

    def test_subset_indices(self):
        from stopping import overall_uncertainty_stop
        proba = gen_proba()
        indices = np.array([15, 20, 25, 30, 35])
        result = overall_uncertainty_stop(proba, indices, 4, threshold=0.05)
        expected = ref_uncertainty_stop(proba, indices, 4, thresh=0.05)
        assert result == expected


class TestClassificationChange:
    def test_identical_stops(self):
        from stopping import classification_change_stop
        pred = np.array([0, 1, 2, 3, 0])
        assert classification_change_stop(pred, pred, threshold=0.0) is True

    def test_different_continues(self):
        from stopping import classification_change_stop
        pred1 = np.array([0, 1, 2, 3, 0])
        pred2 = np.array([1, 0, 3, 2, 1])
        assert classification_change_stop(pred1, pred2, threshold=0.0) is False

    def test_threshold(self):
        from stopping import classification_change_stop
        pred1 = np.array([0, 1, 2, 3, 0, 1, 2, 3, 0, 1])
        pred2 = np.array([0, 1, 2, 3, 0, 1, 2, 3, 1, 0])
        assert classification_change_stop(pred2, pred1, threshold=0.2) is True


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------

class TestPipeline:
    @pytest.fixture(autouse=True)
    def _run_pipeline(self):
        result = subprocess.run(
            ["python3", "/app/pipeline.py"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self._pipeline_rc = result.returncode
        self._pipeline_stderr = result.stderr

    def test_pipeline_succeeds(self):
        assert (
            self._pipeline_rc == 0
        ), f"pipeline.py failed with:\n{self._pipeline_stderr}"

    def test_strategy_rankings_correct(self):
        assert os.path.isfile("/app/results/strategy_rankings.json")
        with open("/app/results/strategy_rankings.json") as f:
            data = json.load(f)

        proba = gen_proba()
        emb = gen_embeddings()
        mc = gen_mc_proba()
        idx_l, idx_u = np.arange(10), np.arange(10, 50)

        assert data["least_confidence"] == ref_least_confidence(proba, 5).tolist()
        assert data["breaking_ties"] == ref_breaking_ties(proba, 5).tolist()
        assert data["prediction_entropy"] == ref_prediction_entropy(proba, 5).tolist()
        assert data["bald"] == ref_bald(mc, 5).tolist()
        assert data["greedy_coreset"] == ref_greedy_coreset(
            emb, idx_u, idx_l, 5, metric="cosine"
        ).tolist()
        assert data["lightweight_coreset"] == ref_lightweight_coreset(
            emb, 5, metric="cosine", seed=123
        ).tolist()

    def test_stopping_decisions_correct(self):
        assert os.path.isfile("/app/results/stopping_decisions.json")
        with open("/app/results/stopping_decisions.json") as f:
            data = json.load(f)

        hist = gen_pred_history()
        proba = gen_proba()
        idx_u = np.arange(10, 50)

        assert data["kappa_average"] == ref_kappa_stop(hist, 4, ws=3, kt=0.99)
        assert data["overall_uncertainty"] == ref_uncertainty_stop(
            proba, idx_u, 4, thresh=0.05
        )
        pred_last = hist[-1]
        pred_prev = hist[-2]
        unchanged = np.equal(pred_last, pred_prev)
        expected_change = bool(unchanged.sum() >= pred_last.shape[0])
        assert data["classification_change"] == expected_change


class TestValidation:
    @pytest.fixture(autouse=True)
    def _run_pipeline(self):
        result = subprocess.run(
            ["python3", "/app/pipeline.py"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self._pipeline_rc = result.returncode
        self._pipeline_stderr = result.stderr

    def test_pipeline_succeeds_for_validation(self):
        assert (
            self._pipeline_rc == 0
        ), f"pipeline.py failed with:\n{self._pipeline_stderr}"

    def test_validation_file_exists(self):
        assert os.path.isfile("/app/results/validation.json"), \
            "validation.json not produced"

    def test_all_criteria_match(self):
        with open("/app/results/validation.json") as f:
            data = json.load(f)
        assert data["all_match"] is True, \
            f"Not all stopping criteria agree with small-text library: {data}"

    def test_kappa_average_match(self):
        with open("/app/results/validation.json") as f:
            data = json.load(f)
        assert data["kappa_average_match"] is True, \
            "Custom kappa_average_stop disagrees with small-text KappaAverage"

    def test_overall_uncertainty_match(self):
        with open("/app/results/validation.json") as f:
            data = json.load(f)
        assert data["overall_uncertainty_match"] is True, \
            "Custom overall_uncertainty_stop disagrees with small-text OverallUncertainty"

    def test_classification_change_match(self):
        with open("/app/results/validation.json") as f:
            data = json.load(f)
        assert data["classification_change_match"] is True, \
            "Custom classification_change_stop disagrees with small-text ClassificationChange"
