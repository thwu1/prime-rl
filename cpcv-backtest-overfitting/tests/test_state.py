
"""
Tests for leakage-free cross-validation backtesting pipeline.
Verifies Makefile integration, split correctness, temporal leakage
freedom, embargo enforcement, and overfitting probability output.
"""

import pytest
import json
import numpy as np
import pandas as pd
import subprocess
import os
import shutil
import sqlite3
from math import comb
from itertools import combinations as combs


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Clean results then run the pipeline via Makefile to ensure make works."""
    if os.path.exists('/app/results'):
        shutil.rmtree('/app/results')
    os.makedirs('/app/results', exist_ok=True)

    result = subprocess.run(
        ["make", "-C", "/app", "all"],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        pytest.fail(
            f"make all failed (exit {result.returncode}).\n"
            f"stdout (last 800 chars): {result.stdout[-800:]}\n"
            f"stderr (last 800 chars): {result.stderr[-800:]}"
        )
    if not os.path.exists('/app/results/cpcv_splits.json'):
        pytest.fail("make all succeeded but /app/results/cpcv_splits.json was not produced")
    if not os.path.exists('/app/results/pbo_result.json'):
        pytest.fail("make all succeeded but /app/results/pbo_result.json was not produced")


@pytest.fixture(scope="session")
def config():
    import yaml
    with open('/app/data/config.yaml') as f:
        raw = yaml.safe_load(f)
    return {
        'n_groups': raw['cross_validation']['n_groups'],
        'n_test_groups': raw['cross_validation']['n_test_groups'],
        'pct_embargo': raw['cross_validation']['pct_embargo'],
        'max_depths': raw['classifier']['max_depths'],
        'n_estimators': raw['classifier']['n_estimators'],
        'random_state': raw['random_state'],
    }


@pytest.fixture(scope="session")
def t1():
    conn = sqlite3.connect('/app/data/market.db')
    rows = conn.execute(
        'SELECT obs_id, event_start, event_end FROM event_windows ORDER BY obs_id'
    ).fetchall()
    conn.close()
    starts = pd.to_datetime([r[1] for r in rows])
    ends = pd.to_datetime([r[2] for r in rows])
    return pd.Series(ends.values, index=starts, name='t1')


@pytest.fixture(scope="session")
def splits():
    with open('/app/results/cpcv_splits.json') as f:
        return json.load(f)


@pytest.fixture(scope="session")
def pbo_result():
    with open('/app/results/pbo_result.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Makefile integration tests
# ---------------------------------------------------------------------------

class TestMakefileIntegration:
    """Pipeline must be orchestrated through Make."""

    def test_makefile_exists(self):
        assert os.path.exists('/app/Makefile'), \
            "Makefile must exist at /app/Makefile"

    def test_makefile_modified(self):
        with open('/app/Makefile') as f:
            content = f.read()
        assert 'not yet implemented' not in content.lower(), \
            "Makefile still contains stub message — must be implemented"


# ---------------------------------------------------------------------------
# Split structure tests
# ---------------------------------------------------------------------------

class TestSplitCount:
    """Cross-validation must produce the correct number of splits."""

    def test_number_of_splits(self, config, splits):
        N = config['n_groups']
        k = config['n_test_groups']
        expected = comb(N, k)
        assert len(splits) == expected, \
            f"Expected C({N},{k})={expected} splits, got {len(splits)}"

    def test_each_split_has_required_keys(self, splits):
        for i, split in enumerate(splits):
            assert 'train' in split, f"Split {i} missing 'train'"
            assert 'test' in split, f"Split {i} missing 'test'"
            assert 'test_groups' in split, f"Split {i} missing 'test_groups'"

    def test_test_groups_size(self, config, splits):
        k = config['n_test_groups']
        for i, split in enumerate(splits):
            assert len(split['test_groups']) == k, \
                f"Split {i}: expected {k} test groups, got {len(split['test_groups'])}"

    def test_test_groups_valid_range(self, config, splits):
        N = config['n_groups']
        for i, split in enumerate(splits):
            assert all(0 <= g < N for g in split['test_groups']), \
                f"Split {i}: invalid group indices {split['test_groups']}"

    def test_all_combinations_present(self, config, splits):
        N = config['n_groups']
        k = config['n_test_groups']
        expected_combos = {c for c in combs(range(N), k)}
        actual_combos = {tuple(sorted(s['test_groups'])) for s in splits}
        missing = expected_combos - actual_combos
        extra = actual_combos - expected_combos
        assert actual_combos == expected_combos, \
            f"Missing: {missing}, Extra: {extra}"


# ---------------------------------------------------------------------------
# Temporal leakage tests
# ---------------------------------------------------------------------------

class TestTemporalLeakage:
    """Training observations must not have labels overlapping test periods."""

    def test_no_information_leakage(self, config, splits, t1):
        """No training observation's event window should overlap any
        test group's event time span."""
        n = len(t1)
        n_groups = config['n_groups']
        groups = np.array_split(np.arange(n), n_groups)

        idx_times = t1.index.values
        t1_times = t1.values

        for split_idx, split in enumerate(splits):
            train_set = set(split['train'])
            test_groups = split['test_groups']

            for g in test_groups:
                g_indices = groups[g]
                g_start = idx_times[g_indices[0]]
                g_t1_max = t1_times[g_indices].max()

                for i in train_set:
                    obs_start = idx_times[i]
                    obs_end = t1_times[i]
                    overlaps = (obs_start <= g_t1_max) and (obs_end >= g_start)
                    assert not overlaps, (
                        f"LEAKAGE split {split_idx}: train obs {i} "
                        f"[{obs_start}, {obs_end}] overlaps "
                        f"test group {g} [{g_start}, {g_t1_max}]"
                    )

    def test_train_test_disjoint(self, splits):
        for i, split in enumerate(splits):
            overlap = set(split['train']) & set(split['test'])
            assert len(overlap) == 0, \
                f"Split {i}: {len(overlap)} indices in both train and test"

    def test_non_empty_splits(self, splits):
        for i, split in enumerate(splits):
            assert len(split['train']) > 0, f"Split {i}: empty training set"
            assert len(split['test']) > 0, f"Split {i}: empty test set"

    def test_boundary_observations_removed(self, config, splits, t1):
        """Temporal overlap handling should remove some training observations
        at group boundaries where label windows cross into test periods."""
        n = len(t1)
        n_groups = config['n_groups']
        n_test_groups = config['n_test_groups']
        n_train_groups = n_groups - n_test_groups
        groups = np.array_split(np.arange(n), n_groups)

        some_removal = any(
            len(s['train']) < n * n_train_groups / n_groups
            for s in splits
        )
        assert some_removal, \
            "No observations removed: all training sets at maximum unpurged size"


# ---------------------------------------------------------------------------
# Embargo tests
# ---------------------------------------------------------------------------

class TestEmbargo:
    """After each test group, buffer observations must be excluded."""

    def test_embargo_applied(self, config, splits, t1):
        n = len(t1)
        n_groups = config['n_groups']
        pct_embargo = config['pct_embargo']
        embargo_size = int(n * pct_embargo)

        if embargo_size == 0:
            pytest.skip("Embargo size is 0")

        groups = np.array_split(np.arange(n), n_groups)

        for split_idx, split in enumerate(splits):
            train_set = set(split['train'])
            test_groups = split['test_groups']

            for g in test_groups:
                g_end = int(groups[g][-1]) + 1
                for j in range(g_end, min(g_end + embargo_size, n)):
                    assert j not in train_set, (
                        f"Split {split_idx}: obs {j} in embargo zone "
                        f"after test group {g} (range {g_end}-"
                        f"{min(g_end + embargo_size, n) - 1}) "
                        f"but found in training set"
                    )


# ---------------------------------------------------------------------------
# Test coverage
# ---------------------------------------------------------------------------

class TestTestCoverage:
    """Each observation must appear in the correct number of test folds."""

    def test_observation_test_frequency(self, config, splits, t1):
        N = config['n_groups']
        k = config['n_test_groups']
        expected_count = comb(N - 1, k - 1)
        n = len(t1)

        obs_count = np.zeros(n, dtype=int)
        for split in splits:
            for i in split['test']:
                obs_count[i] += 1

        wrong = np.where(obs_count != expected_count)[0]
        assert len(wrong) == 0, (
            f"Expected each obs in {expected_count} test folds. "
            f"{len(wrong)} obs have wrong count. "
            f"Unique counts: {dict(zip(*np.unique(obs_count, return_counts=True)))}"
        )


# ---------------------------------------------------------------------------
# Overfitting result tests
# ---------------------------------------------------------------------------

class TestOverfittingResult:
    """Overfitting probability result must be correctly formatted and reasonable."""

    def test_result_keys(self, pbo_result):
        assert 'pbo' in pbo_result, "Missing 'pbo' key"
        assert 'num_splits' in pbo_result, "Missing 'num_splits' key"
        assert 'num_strategies' in pbo_result, "Missing 'num_strategies' key"

    def test_pbo_range(self, pbo_result):
        pbo = pbo_result['pbo']
        assert isinstance(pbo, (int, float)), \
            f"pbo must be numeric, got {type(pbo).__name__}"
        assert 0.0 <= pbo <= 1.0, f"pbo must be in [0,1], got {pbo}"

    def test_num_splits(self, config, pbo_result):
        N = config['n_groups']
        k = config['n_test_groups']
        assert pbo_result['num_splits'] == comb(N, k), \
            f"Expected {comb(N, k)} splits, got {pbo_result['num_splits']}"

    def test_num_strategies(self, config, pbo_result):
        expected = len(config['max_depths'])
        assert pbo_result['num_strategies'] == expected, \
            f"Expected {expected} strategies, got {pbo_result['num_strategies']}"
