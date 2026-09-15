"""Tests for the semivalue data valuation framework.

Verifies weight function correctness, sampler behavior, OOB evaluator,
LOO evaluator, ensemble detection, stability analysis, pipeline integration,
and noisy label detection quality.
"""


import json
import os
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, "/app")

NOISE_RATE = 0.2
RANDOM_SEED = 42


# ---------------------------------------------------------------------------
# Test group 1: Weight function mathematical correctness (no pipeline needed)
# ---------------------------------------------------------------------------


def test_shapley_weights():
    """Shapley weights must be uniform 1/n."""
    from valuation.evaluators import ShapleyEvaluator

    ev = ShapleyEvaluator()
    for n in [5, 10, 50, 100]:
        w = ev.compute_weights(n)
        assert w.shape == (n,), f"Wrong shape for n={n}"
        assert np.allclose(w, 1.0 / n), f"Shapley weights not uniform for n={n}"
        assert np.isclose(w.sum(), 1.0), f"Shapley weights don't sum to 1 for n={n}"


def test_beta_shapley_weights():
    """Beta Shapley weights must match the Beta-function formula."""
    from scipy.special import beta as beta_fn

    from valuation.evaluators import BetaShapleyEvaluator

    ev = BetaShapleyEvaluator(alpha=4, beta=1)

    for n in [10, 50]:
        w = ev.compute_weights(n)
        assert w.shape == (n,), f"Wrong shape for n={n}"
        assert np.isclose(w.sum(), 1.0), f"Weights don't sum to 1 for n={n}"

        # Reference: w(j) proportional to Beta(j+beta, n-j-1+alpha) / Beta(j+1, n-j)
        expected = np.array(
            [
                beta_fn(j + 1, n - (j + 1) + 4) / beta_fn(j + 1, n - j)
                for j in range(n)
            ]
        )
        expected /= expected.sum()
        assert np.allclose(w, expected, atol=1e-10), (
            f"Beta Shapley weights don't match reference formula for n={n}.\n"
            f"Got:      {w[:5]}...\n"
            f"Expected: {expected[:5]}..."
        )


def test_banzhaf_weights():
    """Banzhaf weights must follow binomial coefficient (Pascal's triangle)."""
    from math import comb

    from valuation.evaluators import BanzhafEvaluator

    ev = BanzhafEvaluator()

    for n in [5, 10, 50]:
        w = ev.compute_weights(n)
        assert w.shape == (n,), f"Wrong shape for n={n}"
        assert np.isclose(w.sum(), 1.0), f"Weights don't sum to 1 for n={n}"

        # Reference: w(j) proportional to C(n-1, j)
        expected = np.array([comb(n - 1, j) for j in range(n)], dtype=float)
        expected /= expected.sum()
        assert np.allclose(w, expected, atol=1e-10), (
            f"Banzhaf weights don't match reference for n={n}.\n"
            f"Got:      {w[:5]}...\n"
            f"Expected: {expected[:5]}..."
        )


# ---------------------------------------------------------------------------
# Test group 2: Sampler behavior (no pipeline needed)
# ---------------------------------------------------------------------------


def test_sampler_no_premature_truncation():
    """Verify that truncation does not fire when marginal contributions are consistent.

    With a utility whose marginal contribution is constant and significant,
    the truncation heuristic should never trigger, because contributions
    are never 'negligible'.
    """
    from valuation.sampler import PermutationSampler

    n = 30
    call_count = [0]

    def constant_marginal_utility(indices):
        call_count[0] += 1
        return len(indices) / n

    sampler = PermutationSampler(
        n, mc_epochs=5, min_cardinality=3, min_samples=100, random_state=42
    )
    sampler.set_utility(constant_marginal_utility)
    sampler.compute_marginal_contributions()

    # With constant marginal contribution (1/n per step), truncation should
    # never fire.  Expected calls: 5 * (1 baseline + 27 steps) = 140.
    # A buggy truncation that fires on significant changes would yield ~55.
    assert call_count[0] >= 100, (
        f"Only {call_count[0]} utility evaluations in 5 epochs (expected ~140). "
        f"The sampler may be truncating permutations prematurely when "
        f"marginal contributions are still significant."
    )


def test_sampler_gr_statistic():
    """Verify the GR statistic satisfies its theoretical lower bound.

    The standard potential scale reduction factor is always
    >= sqrt((m-1)/m) where m is samples per chain. With the correct
    formula (addition of B/(W*m)), this holds. With a sign error
    (subtraction), the statistic can fall below this bound.
    """
    from valuation.sampler import PermutationSampler

    sampler = PermutationSampler(5, mc_epochs=100, min_samples=10)

    # Use fixed random data so the test is deterministic
    rng = np.random.RandomState(123)
    sampler.increment_stack = rng.randn(100, 5)

    gr = sampler._compute_gr_statistic(num_chains=10)
    # m = 100 / 10 = 10 samples per chain
    # Theoretical lower bound: sqrt(9/10) approx 0.9487
    assert np.isfinite(gr), "GR statistic must be finite"
    assert gr >= 0.94, (
        f"GR statistic is {gr:.4f}, below theoretical lower bound ~0.949. "
        f"Check the convergence diagnostic formula."
    )


def test_sampler_convergence_not_premature():
    """With a tight GR threshold, the sampler should not stop too early."""
    from valuation.sampler import PermutationSampler

    n = 15
    rs_data = np.random.RandomState(99)
    point_values = rs_data.randn(n)

    def utility(indices):
        return np.mean(point_values[indices]) if len(indices) > 0 else 0.0

    sampler = PermutationSampler(
        n,
        mc_epochs=500,
        min_cardinality=2,
        min_samples=20,
        gr_threshold=1.005,
        random_state=42,
    )
    sampler.set_utility(utility)
    sampler.compute_marginal_contributions()

    epochs_run = len(sampler.increment_stack)
    assert epochs_run > 30, (
        f"Sampler ran only {epochs_run} epochs with GR threshold 1.005. "
        f"A correct GR formula produces values > 1 that decrease slowly, "
        f"requiring many epochs to drop below 1.005."
    )


# ---------------------------------------------------------------------------
# Test group 3: OOB evaluator (no pipeline needed)
# ---------------------------------------------------------------------------


def test_oob_evaluator_shape():
    """OOB evaluator must return one value per training point."""
    from sklearn.neighbors import KNeighborsClassifier

    from valuation.oob import DataOOBEvaluator

    rng = np.random.RandomState(42)
    n = 40
    x = rng.randn(n, 5)
    y = (x[:, 0] > 0).astype(int)
    x_val = rng.randn(10, 5)
    y_val = (x_val[:, 0] > 0).astype(int)

    ev = DataOOBEvaluator(num_models=50, sample_fraction=0.7, random_state=42)
    vals = ev.evaluate(
        x, y, x_val, y_val, lambda: KNeighborsClassifier(n_neighbors=3)
    )

    assert vals.shape == (n,), f"Expected shape ({n},), got {vals.shape}"
    assert np.all(np.isfinite(vals)), "OOB values must be finite"


def test_oob_values_bounded():
    """OOB values must be in [0, 1]."""
    from sklearn.neighbors import KNeighborsClassifier

    from valuation.oob import DataOOBEvaluator

    rng = np.random.RandomState(42)
    n = 40
    x = rng.randn(n, 5)
    y = (x[:, 0] > 0).astype(int)
    x_val = rng.randn(10, 5)
    y_val = (x_val[:, 0] > 0).astype(int)

    ev = DataOOBEvaluator(num_models=50, sample_fraction=0.7, random_state=42)
    vals = ev.evaluate(
        x, y, x_val, y_val, lambda: KNeighborsClassifier(n_neighbors=3)
    )

    assert np.all(vals >= 0), f"OOB values contain negatives: min={vals.min():.4f}"
    assert np.all(vals <= 1), f"OOB values exceed 1: max={vals.max():.4f}"


def test_oob_distinguishes_noise():
    """OOB evaluator must assign lower values to mislabeled points."""
    from sklearn.neighbors import KNeighborsClassifier

    from valuation.oob import DataOOBEvaluator

    rng = np.random.RandomState(42)
    n_train = 60
    x = rng.randn(n_train, 6)
    y_clean = (x[:, 0] + 0.5 * x[:, 1] > 0).astype(int)

    # Flip first 12 labels
    noisy_count = 12
    y_noisy = y_clean.copy()
    y_noisy[:noisy_count] = 1 - y_noisy[:noisy_count]

    x_val = rng.randn(15, 6)
    y_val = (x_val[:, 0] + 0.5 * x_val[:, 1] > 0).astype(int)

    ev = DataOOBEvaluator(num_models=100, sample_fraction=0.7, random_state=42)
    vals = ev.evaluate(
        x[:50], y_noisy[:50], x_val, y_val,
        lambda: KNeighborsClassifier(n_neighbors=3),
    )

    noisy_mean = np.mean(vals[:noisy_count])
    clean_mean = np.mean(vals[noisy_count:])
    assert clean_mean > noisy_mean, (
        f"Clean points ({clean_mean:.4f}) should have higher OOB accuracy "
        f"than noisy points ({noisy_mean:.4f}). "
        f"Verify the evaluator computes per-point prediction accuracy on "
        f"training features, not aggregate model quality."
    )


# ---------------------------------------------------------------------------
# Test group 4: LOO evaluator (no pipeline needed)
# ---------------------------------------------------------------------------


def test_loo_correct_values():
    """LOO evaluator must compute U(D) - U(D\\{i}) correctly."""
    from valuation.loo import LeaveOneOutEvaluator

    n = 15
    rng = np.random.RandomState(42)
    point_values = rng.randn(n)

    def utility(indices):
        if len(indices) == 0:
            return 0.0
        return np.mean(point_values[list(indices)])

    ev = LeaveOneOutEvaluator()
    values = ev.compute_loo_values(utility, n)

    # Reference: LOO value = utility(all) - utility(all except i)
    full_utility = utility(list(range(n)))
    expected = np.zeros(n)
    for i in range(n):
        leave_out = [j for j in range(n) if j != i]
        expected[i] = full_utility - utility(leave_out)

    assert values.shape == (n,), f"Expected shape ({n},), got {values.shape}"
    assert np.allclose(values, expected, atol=1e-10), (
        f"LOO values don't match expected U(D) - U(D\\{{i}}).\n"
        f"Got:      {values[:5]}\n"
        f"Expected: {expected[:5]}"
    )


def test_loo_nonzero_values():
    """LOO values must not all be zero for a non-trivial utility."""
    from valuation.loo import LeaveOneOutEvaluator

    n = 10
    rng = np.random.RandomState(55)
    point_values = rng.randn(n) * 5  # Large spread to ensure non-zero LOO

    def utility(indices):
        if len(indices) == 0:
            return 0.0
        return np.mean(point_values[list(indices)])

    ev = LeaveOneOutEvaluator()
    values = ev.compute_loo_values(utility, n)

    assert not np.allclose(values, 0.0), (
        "LOO values are all zero. The evaluator must compute actual "
        "leave-one-out differences, not return a zero vector."
    )
    assert np.all(np.isfinite(values)), "LOO values must be finite"


# ---------------------------------------------------------------------------
# Test group 5: Ensemble detection (no pipeline needed)
# ---------------------------------------------------------------------------


def test_ensemble_borda_count():
    """Borda count must select points with lowest aggregate rank."""
    from valuation.detector import NoisyLabelDetector

    detector = NoisyLabelDetector()
    n = 10

    # Points 0-2 have clearly lowest values in both evaluators
    eval_a = np.array([-0.5, -0.3, -0.1, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5])
    eval_b = np.array([-0.4, -0.25, -0.05, 0.08, 0.12, 0.18, 0.22, 0.32, 0.38, 0.48])

    evaluator_results = {"a": eval_a, "b": eval_b}
    detected = detector.ensemble_detect(evaluator_results, 0.3, n)

    detected_set = set(detected.tolist())
    assert 0 in detected_set, (
        "Point 0 (worst in both rankings) not detected by ensemble. "
        "Check that Borda count selects points with lowest rank sum."
    )
    assert 1 in detected_set, (
        "Point 1 (second-worst in both rankings) not detected by ensemble."
    )
    assert 2 in detected_set, (
        "Point 2 (third-worst in both rankings) not detected by ensemble."
    )


# ---------------------------------------------------------------------------
# Test group 6: Pipeline integration (creates dataset and runs pipeline)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pipeline_results():
    """Create dataset, run the pipeline, return (noisy_indices, results_dict)."""
    from sklearn.datasets import load_digits

    rs = np.random.RandomState(RANDOM_SEED)
    digits = load_digits()
    X, y = digits.data, digits.target

    idx = rs.permutation(len(X))
    X, y = X[idx], y[idx]

    x_train = X[:100]
    y_train_clean = y[:100].copy()
    x_valid = X[100:130]
    y_valid = y[100:130]

    # Inject label noise
    n_noisy = int(len(x_train) * NOISE_RATE)
    noisy_idx = rs.choice(len(x_train), n_noisy, replace=False)
    y_train = y_train_clean.copy()
    for i in noisy_idx:
        others = [lab for lab in range(10) if lab != y_train_clean[i]]
        y_train[i] = rs.choice(others)

    os.makedirs("/app/data", exist_ok=True)
    np.savez(
        "/app/data/dataset.npz",
        x_train=x_train,
        y_train=y_train,
        x_valid=x_valid,
        y_valid=y_valid,
    )

    # Run the pipeline
    result = subprocess.run(
        ["python3", "/app/pipeline.py"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Pipeline failed with exit code {result.returncode}.\n"
        f"stdout:\n{result.stdout[-2000:]}\n"
        f"stderr:\n{result.stderr[-2000:]}"
    )

    assert os.path.exists("/app/results.json"), "results.json was not created"
    with open("/app/results.json") as f:
        results = json.load(f)

    return noisy_idx, results


def test_pipeline_runs(pipeline_results):
    """Pipeline must complete without errors."""
    _, results = pipeline_results
    assert results is not None


def test_output_format(pipeline_results):
    """Results JSON must have the correct structure."""
    _, results = pipeline_results

    for key in ["shapley", "beta_shapley", "banzhaf", "loo", "data_oob"]:
        assert key in results, f"Missing top-level key: {key}"
        entry = results[key]
        assert "data_values" in entry, f"Missing 'data_values' in {key}"
        assert "detected_indices" in entry, f"Missing 'detected_indices' in {key}"

        values = entry["data_values"]
        assert isinstance(values, list), f"data_values in {key} is not a list"
        assert len(values) == 100, (
            f"data_values in {key} has length {len(values)}, expected 100"
        )

        indices = entry["detected_indices"]
        assert isinstance(indices, list), f"detected_indices in {key} is not a list"
        assert indices == sorted(indices), f"detected_indices in {key} not sorted"

    for key in ["ensemble", "convergence", "stability", "removal_validation"]:
        assert key in results, f"Missing top-level key: {key}"


def test_data_values_reasonable(pipeline_results):
    """Data values must be finite and not uniformly zero."""
    _, results = pipeline_results

    for key in ["shapley", "beta_shapley", "banzhaf", "loo"]:
        values = np.array(results[key]["data_values"])
        assert np.all(np.isfinite(values)), f"Non-finite data values in {key}"
        assert not np.allclose(values, 0.0), f"All-zero data values in {key}"
        assert np.std(values) > 1e-10, f"Data values in {key} have no variance"


def test_oob_output_valid(pipeline_results):
    """OOB values in pipeline output must be in [0, 1]."""
    _, results = pipeline_results

    oob = results["data_oob"]
    values = np.array(oob["data_values"])
    assert len(values) == 100, f"data_oob has {len(values)} values, expected 100"
    assert np.all(np.isfinite(values)), "Non-finite OOB values in pipeline output"
    assert np.all(values >= 0), f"OOB values contain negatives: min={values.min()}"
    assert np.all(values <= 1), f"OOB values exceed 1: max={values.max()}"


def test_convergence_in_output(pipeline_results):
    """Convergence diagnostics must be present and valid."""
    _, results = pipeline_results

    assert "convergence" in results, "Missing convergence key in results"
    conv = results["convergence"]
    assert "gr_statistic" in conv, "Missing gr_statistic in convergence"
    assert "epochs_run" in conv, "Missing epochs_run in convergence"
    assert isinstance(conv["gr_statistic"], (int, float))
    assert conv["gr_statistic"] >= 0.94, (
        f"GR statistic {conv['gr_statistic']:.4f} below theoretical lower bound"
    )
    assert conv["epochs_run"] > 0


def test_stability_analysis(pipeline_results):
    """Stability analysis must show meaningful split-half correlation."""
    _, results = pipeline_results

    assert "stability" in results, "Missing 'stability' key in results"
    stab = results["stability"]
    assert "split_half_correlation" in stab, (
        "Missing 'split_half_correlation' in stability"
    )
    corr = stab["split_half_correlation"]
    assert isinstance(corr, (int, float)), "split_half_correlation must be numeric"
    assert np.isfinite(corr), "split_half_correlation must be finite"
    assert corr > 0.3, (
        f"Split-half correlation is {corr:.4f}, need > 0.3. "
        f"Compute Spearman rank correlation between mean per-point marginal "
        f"increments from first and second halves of permutation epochs."
    )


def test_detection_quality(pipeline_results):
    """At least one evaluator must achieve F1 >= 0.25 on noisy label detection."""
    noisy_indices, results = pipeline_results
    noisy_set = set(noisy_indices.tolist())

    best_f1 = 0.0
    details = {}

    for name in ["shapley", "beta_shapley", "banzhaf", "loo", "data_oob"]:
        res = results[name]
        detected = set(res["detected_indices"])
        if len(detected) == 0:
            details[name] = 0.0
            continue

        tp = len(detected & noisy_set)
        fp = len(detected - noisy_set)
        fn = len(noisy_set - detected)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        details[name] = f1
        best_f1 = max(best_f1, f1)

    assert best_f1 >= 0.25, (
        f"Best F1 across evaluators is {best_f1:.3f} (need >= 0.25). "
        f"Per-evaluator F1: {details}"
    )


def test_ensemble_output_format(pipeline_results):
    """Ensemble detection must have correct structure."""
    _, results = pipeline_results

    assert "ensemble" in results, "Missing 'ensemble' key"
    ens = results["ensemble"]
    assert "detected_indices" in ens, "Missing 'detected_indices' in ensemble"
    assert "method" in ens, "Missing 'method' in ensemble"
    assert ens["method"] == "borda_count", (
        f"Ensemble method must be 'borda_count', got '{ens['method']}'"
    )
    indices = ens["detected_indices"]
    assert isinstance(indices, list), "ensemble detected_indices is not a list"
    assert indices == sorted(indices), "ensemble detected_indices not sorted"
    assert all(isinstance(i, int) for i in indices), (
        "ensemble detected_indices contains non-integer values"
    )


def test_ensemble_f1(pipeline_results):
    """Ensemble detection must achieve F1 >= 0.20."""
    noisy_indices, results = pipeline_results
    noisy_set = set(noisy_indices.tolist())
    detected = set(results["ensemble"]["detected_indices"])

    if len(detected) == 0:
        f1 = 0.0
    else:
        tp = len(detected & noisy_set)
        fp = len(detected - noisy_set)
        fn = len(noisy_set - detected)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

    assert f1 >= 0.20, (
        f"Ensemble F1 = {f1:.3f}, need >= 0.20. "
        f"Check Borda count rank aggregation selects points with lowest "
        f"aggregate rank (most consistently low-valued)."
    )


def test_removal_validation_schema(pipeline_results):
    """Removal validation must have correct structure and valid values."""
    _, results = pipeline_results

    assert "removal_validation" in results, "Missing 'removal_validation' key"
    rv = results["removal_validation"]
    assert "original_accuracy" in rv, "Missing 'original_accuracy'"
    assert "cleaned_accuracy" in rv, "Missing 'cleaned_accuracy'"
    assert isinstance(rv["original_accuracy"], (int, float))
    assert isinstance(rv["cleaned_accuracy"], (int, float))
    assert 0 <= rv["original_accuracy"] <= 1, (
        f"original_accuracy {rv['original_accuracy']} out of [0,1]"
    )
    assert 0 <= rv["cleaned_accuracy"] <= 1, (
        f"cleaned_accuracy {rv['cleaned_accuracy']} out of [0,1]"
    )


def test_removal_improves_accuracy(pipeline_results):
    """Removing detected noisy points must improve validation accuracy."""
    _, results = pipeline_results
    rv = results["removal_validation"]
    assert rv["cleaned_accuracy"] > rv["original_accuracy"], (
        f"Cleaned accuracy ({rv['cleaned_accuracy']:.4f}) must exceed "
        f"original accuracy ({rv['original_accuracy']:.4f}). "
        f"Verify that removal validation trains the cleaned model on "
        f"the non-detected subset and evaluates on the validation set."
    )
