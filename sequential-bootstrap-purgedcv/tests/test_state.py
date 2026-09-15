
import pytest
import json
import os
import sys
import subprocess
import importlib

sys.path.insert(0, '/app')


@pytest.fixture(scope="session")
def pipeline_results():
    """Run the pipeline and load results."""
    result = subprocess.run(
        ['python3', '/app/run.py'],
        capture_output=True, text=True, cwd='/app',
        timeout=300
    )
    assert result.returncode == 0, \
        f"Pipeline failed (exit {result.returncode}).\nstderr: {result.stderr}"

    assert os.path.exists('/app/results.json'), \
        "Pipeline did not produce /app/results.json"

    with open('/app/results.json') as f:
        return json.load(f)


class TestResultsStructure:
    """Verify results.json has correct structure and types."""

    def test_required_keys(self, pipeline_results):
        required = [
            'original_cv_score', 'corrected_cv_score', 'leakage_ratio',
            'corrected_sampling_uniqueness', 'baseline_sampling_uniqueness',
            'n_informative_in_top10'
        ]
        for key in required:
            assert key in pipeline_results, f"Missing required key: {key}"

    def test_numeric_types(self, pipeline_results):
        for key in ['original_cv_score', 'corrected_cv_score', 'leakage_ratio',
                     'corrected_sampling_uniqueness', 'baseline_sampling_uniqueness']:
            assert isinstance(pipeline_results[key], (int, float)), \
                f"{key} must be numeric, got {type(pipeline_results[key])}"

    def test_informative_is_int(self, pipeline_results):
        assert isinstance(pipeline_results['n_informative_in_top10'], int), \
            "n_informative_in_top10 must be int"


class TestEvaluationCorrectness:
    """Verify the corrected evaluation produces honest metrics."""

    def test_corrected_more_conservative(self, pipeline_results):
        """Corrected CV must yield a lower (more negative) score."""
        orig = pipeline_results['original_cv_score']
        corr = pipeline_results['corrected_cv_score']
        assert corr < orig, \
            f"Corrected ({corr:.4f}) must be lower than original ({orig:.4f})"

    def test_meaningful_difference(self, pipeline_results):
        """Correction must produce a meaningful gap, not a trivial one."""
        diff = pipeline_results['original_cv_score'] - pipeline_results['corrected_cv_score']
        assert diff > 0.02, \
            f"Difference ({diff:.4f}) too small — correction appears insufficient"

    def test_leakage_ratio_above_one(self, pipeline_results):
        """Leakage ratio must exceed 1.0."""
        assert pipeline_results['leakage_ratio'] > 1.0, \
            f"Leakage ratio ({pipeline_results['leakage_ratio']:.4f}) must exceed 1.0"

    def test_leakage_ratio_consistent(self, pipeline_results):
        """Leakage ratio must match abs(corrected) / abs(original)."""
        orig = pipeline_results['original_cv_score']
        corr = pipeline_results['corrected_cv_score']
        expected = abs(corr) / abs(orig)
        actual = pipeline_results['leakage_ratio']
        assert abs(actual - expected) < 0.15, \
            f"Leakage ratio ({actual:.4f}) inconsistent with scores " \
            f"(expected ~{expected:.4f})"

    def test_leakage_ratio_bounds(self, pipeline_results):
        """Leakage ratio must be in a reasonable range."""
        r = pipeline_results['leakage_ratio']
        assert 1.02 < r < 15.0, \
            f"Leakage ratio ({r:.4f}) outside reasonable bounds (1.02, 15.0)"

    def test_corrected_score_range(self, pipeline_results):
        """Corrected score should be in a realistic range for this data."""
        score = pipeline_results['corrected_cv_score']
        assert -2.0 < score < -0.3, \
            f"Corrected score ({score:.4f}) outside realistic range (-2.0, -0.3)"

    def test_original_score_range(self, pipeline_results):
        """Original (inflated) score should be in the expected range."""
        score = pipeline_results['original_cv_score']
        assert -0.8 < score < -0.1, \
            f"Original score ({score:.4f}) outside expected range (-0.8, -0.1)"


class TestSamplingCorrectness:
    """Verify corrected sampling achieves higher uniqueness."""

    def test_corrected_uniqueness_higher(self, pipeline_results):
        """Corrected sampling must achieve higher uniqueness than baseline."""
        corr = pipeline_results['corrected_sampling_uniqueness']
        base = pipeline_results['baseline_sampling_uniqueness']
        assert corr > base, \
            f"Corrected ({corr:.4f}) must exceed baseline ({base:.4f})"

    def test_uniqueness_in_valid_range(self, pipeline_results):
        """Uniqueness values must be in (0, 1]."""
        for key in ['corrected_sampling_uniqueness', 'baseline_sampling_uniqueness']:
            val = pipeline_results[key]
            assert 0.0 < val <= 1.0, \
                f"{key} ({val:.4f}) outside valid range (0, 1]"


class TestFeatureImportance:
    """Verify feature importance identifies informative features."""

    def test_informative_count(self, pipeline_results):
        """At least 3 of the top-10 features must be informative."""
        n = pipeline_results['n_informative_in_top10']
        assert n >= 3, f"Only {n} informative features in top 10 (need >= 3)"

    def test_informative_bound(self, pipeline_results):
        """Count must be in valid range [0, 10]."""
        n = pipeline_results['n_informative_in_top10']
        assert 0 <= n <= 10, f"n_informative_in_top10 ({n}) out of range [0, 10]"


class TestReproducibility:
    """Verify pipeline produces deterministic results."""

    def test_deterministic_output(self, pipeline_results):
        """Running the pipeline twice must give consistent scores."""
        result = subprocess.run(
            ['python3', '/app/run.py'],
            capture_output=True, text=True, cwd='/app',
            timeout=300
        )
        assert result.returncode == 0, f"Second run failed: {result.stderr}"

        with open('/app/results.json') as f:
            second = json.load(f)

        for key in ['corrected_cv_score', 'original_cv_score']:
            v1 = pipeline_results[key]
            v2 = second[key]
            assert abs(v1 - v2) < 0.01, \
                f"{key} not deterministic: {v1:.4f} vs {v2:.4f}"


class TestCVStructure:
    """Verify the corrected CV prevents temporal label overlap."""

    def test_no_label_leakage(self, pipeline_results):
        """Training label spans must not overlap with the test period."""
        import numpy as np
        import pandas as pd

        from pipeline.data_generator import generate_dataset

        # Generate a small validation dataset
        X, y, t1, _ = generate_dataset(
            seed=99, n_samples=100, ar_coef=0.98,
            label_horizon=10, n_informative=3, n_redundant=2, n_noise=3
        )

        # Reload the evaluator module to pick up agent's changes
        try:
            mod = importlib.import_module('pipeline.evaluator')
            importlib.reload(mod)
        except ImportError:
            pytest.skip("Could not import pipeline.evaluator")

        # Search for a custom CV class (not standard sklearn)
        standard = {'KFold', 'StratifiedKFold', 'GroupKFold',
                     'BaseCrossValidator', '_BaseKFold'}
        cv_cls = None
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and hasattr(obj, 'split') and name not in standard:
                cv_cls = obj
                break

        if cv_cls is None:
            pytest.skip("No custom CV splitter found in pipeline.evaluator")

        # Try to instantiate with common signatures
        splitter = None
        for kwargs in [
            dict(n_splits=3, t1=t1, pct_embargo=0.01),
            dict(n_splits=3, t1=t1, pct_embargo=0.0),
            dict(n_splits=3, t1=t1),
        ]:
            try:
                splitter = cv_cls(**kwargs)
                break
            except (TypeError, ValueError):
                continue

        if splitter is None:
            pytest.skip(f"Could not instantiate {cv_cls.__name__}")

        # Verify no label overlap in any fold
        for fold_i, (train_idx, test_idx) in enumerate(splitter.split(X)):
            test_start = X.index[test_idx[0]]
            test_max_t1 = t1.iloc[test_idx].max()

            for ti in train_idx:
                obs_end = t1.iloc[ti]
                obs_start = X.index[ti]

                is_before = obs_end <= test_start
                is_after = obs_start >= test_max_t1

                assert is_before or is_after, \
                    f"Fold {fold_i}: training obs at {obs_start} with label " \
                    f"end {obs_end} overlaps test [{test_start}, {test_max_t1}]"
