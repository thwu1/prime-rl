"""
Tests for the multi-tier DDSketch metric aggregation pipeline.
Verifies sketch correctness, per-tier SLA compliance (accuracy and memory),
tier configuration validity, and end-to-end pipeline output.
"""

import json
import sqlite3
import os
import sys
import math
import subprocess
from collections import defaultdict


def _get_sla_config():
    with open('/app/sla_config.json') as f:
        return json.load(f)


def _get_tier_config():
    with open('/app/output/tier_config.json') as f:
        return json.load(f)


def _exact_percentile(values, q):
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 0:
        return 0
    idx = int(math.ceil(q * n)) - 1
    idx = max(0, min(idx, n - 1))
    return sorted_vals[idx]


def _ensure_pipeline():
    if not os.path.exists('/app/output/results.json'):
        subprocess.run(
            ['python3', '/app/pipeline.py'],
            capture_output=True, text=True, cwd='/app'
        )


class TestTierConfig:
    """Verify that per-tier configuration exists and is structurally valid."""

    def test_tier_config_exists(self):
        assert os.path.exists('/app/output/tier_config.json'), \
            "Per-tier configuration not found at /app/output/tier_config.json"

    def test_tier_config_has_all_tiers(self):
        tc = _get_tier_config()
        sla = _get_sla_config()
        expected = set(sla['service_tiers'].keys())
        actual = set(tc.keys())
        assert expected == actual, \
            f"Missing tiers: {expected - actual}, extra: {actual - expected}"

    def test_tier_config_has_required_fields(self):
        tc = _get_tier_config()
        for tier, config in tc.items():
            assert 'alpha' in config, f"Missing 'alpha' for tier {tier}"
            assert 'max_num_bins' in config, f"Missing 'max_num_bins' for tier {tier}"
            assert isinstance(config['alpha'], (int, float)), \
                f"alpha must be numeric for {tier}"
            assert isinstance(config['max_num_bins'], int), \
                f"max_num_bins must be int for {tier}"
            assert 0 < config['alpha'] < 1, \
                f"alpha must be in (0,1) for {tier}, got {config['alpha']}"
            assert config['max_num_bins'] > 0, \
                f"max_num_bins must be positive for {tier}"


class TestAccuracySLA:
    """Verify that configured alpha does not exceed per-tier SLA limit."""

    def test_alpha_within_sla(self):
        tc = _get_tier_config()
        sla = _get_sla_config()
        for tier, config in tc.items():
            max_err = sla['service_tiers'][tier]['sla']['accuracy']['max_relative_error']
            assert config['alpha'] <= max_err, (
                f"Tier {tier}: alpha={config['alpha']} exceeds "
                f"max_relative_error={max_err}"
            )


class TestMemoryBudget:
    """Verify that per-tier memory usage stays within SLA limits."""

    def test_per_tier_memory_limits(self):
        tc = _get_tier_config()
        sla = _get_sla_config()
        bytes_per_bin = sla['constraints']['bytes_per_bin']

        for tier, config in tc.items():
            max_allowed = sla['service_tiers'][tier]['sla']['resources'][
                'max_memory_bytes_per_sketch'
            ]
            actual_bytes = config['max_num_bins'] * bytes_per_bin
            assert actual_bytes <= max_allowed, (
                f"Tier {tier}: memory {actual_bytes}B exceeds limit "
                f"{max_allowed}B (max_num_bins={config['max_num_bins']}, "
                f"bytes_per_bin={bytes_per_bin})"
            )

    def test_bins_sufficient_for_data_range(self):
        """Configured bins should cover the actual data range at the chosen alpha."""
        tc = _get_tier_config()
        conn = sqlite3.connect('/app/data/metrics.db')
        c = conn.cursor()

        for tier, config in tc.items():
            alpha = config['alpha']
            gamma = (1 + alpha) / (1 - alpha)

            c.execute(
                'SELECT MIN(latency_ms), MAX(latency_ms) '
                'FROM latency_samples WHERE service_tier = ?',
                (tier,)
            )
            min_val, max_val = c.fetchone()
            bins_needed = math.ceil(
                math.log(max_val / min_val) / math.log(gamma)
            )
            # Must have enough bins, or rely on collapse (max_num_bins can be
            # less, but collapse must be implemented)
            assert config['max_num_bins'] >= 10, (
                f"Tier {tier}: max_num_bins={config['max_num_bins']} is "
                f"unreasonably small (need ~{bins_needed} for data range)"
            )

        conn.close()


class TestPipeline:
    """Verify end-to-end pipeline execution and output accuracy."""

    def test_pipeline_runs(self):
        if os.path.exists('/app/output/results.json'):
            os.remove('/app/output/results.json')

        result = subprocess.run(
            ['python3', '/app/pipeline.py'],
            capture_output=True, text=True, cwd='/app'
        )
        assert result.returncode == 0, \
            f"Pipeline failed with stderr:\n{result.stderr}"
        assert os.path.exists('/app/output/results.json'), \
            "Output file not created"

    def test_output_structure(self):
        _ensure_pipeline()
        with open('/app/output/results.json') as f:
            results = json.load(f)

        assert len(results) > 0, "No windows in results"

        sla = _get_sla_config()
        tiers = list(sla['service_tiers'].keys())
        percentiles = [str(p) for p in sla['constraints']['percentiles']]

        for window_id, window_data in results.items():
            for tier in tiers:
                assert tier in window_data, \
                    f"Missing tier {tier} in window {window_id}"
                for p in percentiles:
                    assert p in window_data[tier], \
                        f"Missing percentile {p} for {tier} in window {window_id}"
                    assert isinstance(window_data[tier][p], (int, float)), \
                        f"Percentile {p} for {tier} in window {window_id} " \
                        f"is not numeric"
                    assert window_data[tier][p] > 0, \
                        f"Percentile {p} for {tier} in window {window_id} " \
                        f"should be positive"

    def test_all_windows_present(self):
        _ensure_pipeline()

        sla = _get_sla_config()
        window_size = sla['constraints']['window_size_sec']

        conn = sqlite3.connect('/app/data/metrics.db')
        c = conn.cursor()
        c.execute('SELECT DISTINCT CAST(timestamp / ? AS INTEGER) FROM latency_samples',
                  (window_size,))
        expected_windows = {str(row[0]) for row in c.fetchall()}
        conn.close()

        with open('/app/output/results.json') as f:
            results = json.load(f)

        result_windows = set(results.keys())
        assert expected_windows == result_windows, (
            f"Missing windows: {expected_windows - result_windows}, "
            f"Extra windows: {result_windows - expected_windows}"
        )

    def test_per_tier_accuracy(self):
        """All percentiles per tier satisfy the tier's relative-error SLA."""
        _ensure_pipeline()
        sla = _get_sla_config()
        tc = _get_tier_config()

        with open('/app/output/results.json') as f:
            results = json.load(f)

        conn = sqlite3.connect('/app/data/metrics.db')
        c = conn.cursor()
        window_size = sla['constraints']['window_size_sec']

        for tier in sla['service_tiers'].keys():
            max_err = sla['service_tiers'][tier]['sla']['accuracy'][
                'max_relative_error'
            ]
            tolerance = max_err + 0.015

            c.execute(
                'SELECT timestamp, latency_ms FROM latency_samples '
                'WHERE service_tier = ? ORDER BY timestamp',
                (tier,)
            )
            rows = c.fetchall()

            windows = defaultdict(list)
            for ts, latency in rows:
                window_id = int(ts / window_size)
                windows[window_id].append(latency)

            errors = []
            for window_id, values in windows.items():
                if len(values) < 10:
                    continue
                wid = str(window_id)
                if wid not in results or tier not in results[wid]:
                    continue

                for p_str, sketch_val in results[wid][tier].items():
                    p = float(p_str)
                    exact_val = _exact_percentile(values, p)
                    if exact_val == 0:
                        continue
                    rel_err = abs(sketch_val - exact_val) / exact_val
                    if rel_err > tolerance:
                        errors.append(
                            f"Tier {tier}, window {window_id}, p{p}: "
                            f"sketch={sketch_val:.4f}, exact={exact_val:.4f}, "
                            f"rel_err={rel_err:.6f} > {tolerance}"
                        )

            assert len(errors) == 0, (
                f"Accuracy SLA violated for tier {tier} "
                f"({len(errors)} violations):\n"
                + "\n".join(errors[:10])
            )

        conn.close()


class TestSketchCorrectness:
    """Verify DDSketch core operations are correctly implemented."""

    def test_merge_correctness(self):
        sys.path.insert(0, '/app')
        import importlib
        if 'sketch' in sys.modules:
            importlib.reload(sys.modules['sketch'])
        from sketch import DDSketch

        import random
        random.seed(789)

        s1 = DDSketch(alpha=0.01, max_num_bins=2048)
        s2 = DDSketch(alpha=0.01, max_num_bins=2048)
        single = DDSketch(alpha=0.01, max_num_bins=2048)

        vals1 = [random.lognormvariate(2, 0.5) for _ in range(500)]
        vals2 = [random.lognormvariate(2, 0.5) for _ in range(500)]

        for v in vals1:
            s1.add(v)
            single.add(v)
        for v in vals2:
            s2.add(v)
            single.add(v)

        s1.merge(s2)

        for q in [0.5, 0.9, 0.95, 0.99]:
            assert s1.quantile(q) == single.quantile(q), \
                f"Merge mismatch at q={q}"

    def test_collapse_preserves_count(self):
        sys.path.insert(0, '/app')
        import importlib
        if 'sketch' in sys.modules:
            importlib.reload(sys.modules['sketch'])
        from sketch import DDSketch

        import random
        random.seed(321)

        s = DDSketch(alpha=0.01, max_num_bins=20)
        values = [random.lognormvariate(2, 1) for _ in range(1000)]
        for v in values:
            s.add(v)

        assert s.count == len(values), \
            f"Collapse lost count: expected {len(values)}, got {s.count}"
        assert len(s.store) <= s.max_num_bins, \
            f"Too many bins: {len(s.store)} > {s.max_num_bins}"

    def test_quantile_accuracy(self):
        sys.path.insert(0, '/app')
        import importlib
        if 'sketch' in sys.modules:
            importlib.reload(sys.modules['sketch'])
        from sketch import DDSketch

        import random
        random.seed(654)

        alpha = 0.01
        s = DDSketch(alpha=alpha, max_num_bins=2048)
        values = [random.lognormvariate(3, 0.8) for _ in range(5000)]
        for v in values:
            s.add(v)

        sorted_vals = sorted(values)
        n = len(sorted_vals)

        for q in [0.5, 0.9, 0.95, 0.99, 0.999]:
            sketch_val = s.quantile(q)
            idx = max(0, min(int(math.ceil(q * n)) - 1, n - 1))
            exact_val = sorted_vals[idx]
            if exact_val > 0:
                rel_err = abs(sketch_val - exact_val) / exact_val
                assert rel_err <= alpha + 0.005, (
                    f"q={q}: sketch={sketch_val:.4f}, "
                    f"exact={exact_val:.4f}, rel_err={rel_err:.6f}"
                )

    def test_count_tracking(self):
        sys.path.insert(0, '/app')
        import importlib
        if 'sketch' in sys.modules:
            importlib.reload(sys.modules['sketch'])
        from sketch import DDSketch

        s = DDSketch(alpha=0.01)
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 100.0, 0.5, 0.01]
        for v in values:
            s.add(v)
        assert s.count == len(values), \
            f"Count mismatch: expected {len(values)}, got {s.count}"

    def test_extreme_quantiles(self):
        sys.path.insert(0, '/app')
        import importlib
        if 'sketch' in sys.modules:
            importlib.reload(sys.modules['sketch'])
        from sketch import DDSketch

        s = DDSketch(alpha=0.01)
        values = [1.0, 5.0, 10.0, 50.0, 100.0]
        for v in values:
            s.add(v)
        assert s.quantile(0) == min(values), "p0 should return min value"
        assert s.quantile(1) == max(values), "p1 should return max value"

    def test_merge_count_preserved(self):
        sys.path.insert(0, '/app')
        import importlib
        if 'sketch' in sys.modules:
            importlib.reload(sys.modules['sketch'])
        from sketch import DDSketch

        s1 = DDSketch(alpha=0.01)
        s2 = DDSketch(alpha=0.01)

        for v in [1.0, 2.0, 3.0]:
            s1.add(v)
        for v in [4.0, 5.0]:
            s2.add(v)

        s1.merge(s2)
        assert s1.count == 5, f"Expected count 5 after merge, got {s1.count}"
        assert s1.min_value == 1.0, f"Expected min 1.0, got {s1.min_value}"
        assert s1.max_value == 5.0, f"Expected max 5.0, got {s1.max_value}"

    def test_collapse_quantile_accuracy(self):
        """Collapse should preserve reasonable quantile accuracy."""
        sys.path.insert(0, '/app')
        import importlib
        if 'sketch' in sys.modules:
            importlib.reload(sys.modules['sketch'])
        from sketch import DDSketch

        import random
        random.seed(555)

        alpha = 0.01
        s = DDSketch(alpha=alpha, max_num_bins=50)
        values = [random.lognormvariate(2, 0.5) for _ in range(2000)]
        for v in values:
            s.add(v)

        sorted_vals = sorted(values)
        n = len(sorted_vals)

        for q in [0.5, 0.9, 0.95, 0.99]:
            sketch_val = s.quantile(q)
            idx = max(0, min(int(math.ceil(q * n)) - 1, n - 1))
            exact_val = sorted_vals[idx]
            if exact_val > 0:
                rel_err = abs(sketch_val - exact_val) / exact_val
                assert rel_err < 0.20, (
                    f"q={q}: sketch={sketch_val:.4f}, "
                    f"exact={exact_val:.4f}, rel_err={rel_err:.4f} — "
                    f"collapse may be corrupting bucket mapping"
                )
