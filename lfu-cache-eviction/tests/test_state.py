"""
Tests for cache eviction benchmark system.

Verifies correctness, performance, and determinism of the adaptive
eviction policy across diverse workload patterns.

"""

import pytest
import json
import sys
import os
import subprocess

sys.path.insert(0, '/app')


@pytest.fixture
def results():
    path = '/app/results.json'
    assert os.path.exists(path), (
        "results.json not found - run 'python3 /app/benchmark.py' first"
    )
    with open(path) as f:
        return json.load(f)


class TestResultsStructure:
    SCENARIOS = [
        'zipfian_standard', 'zipfian_moderate',
        'temporal_locality', 'uniform', 'scan_mixed',
    ]
    POLICIES = ['random', 'fifo', 'adaptive_s5', 'adaptive_s10']

    def test_results_exist(self):
        assert os.path.exists('/app/results.json')

    def test_all_scenarios_present(self, results):
        for s in self.SCENARIOS:
            assert s in results, f"Missing scenario: {s}"

    def test_all_policies_present(self, results):
        for s in self.SCENARIOS:
            for p in self.POLICIES:
                assert p in results[s], f"Missing {p} in {s}"

    def test_valid_hit_ratios(self, results):
        for s in self.SCENARIOS:
            for p in self.POLICIES:
                hr = results[s][p]['hit_ratio']
                assert 0.0 <= hr <= 1.0, f"Invalid hit_ratio {hr} for {p}/{s}"


class TestAdaptivePerformance:
    def test_beats_random_zipfian_standard(self, results):
        r = results['zipfian_standard']
        adaptive = r['adaptive_s5']['hit_ratio']
        baseline = r['random']['hit_ratio']
        assert adaptive > baseline * 1.10, (
            f"zipfian_standard: adaptive={adaptive:.4f} vs "
            f"random={baseline:.4f} (need >1.10x)"
        )

    def test_beats_random_zipfian_moderate(self, results):
        r = results['zipfian_moderate']
        adaptive = r['adaptive_s5']['hit_ratio']
        baseline = r['random']['hit_ratio']
        assert adaptive > baseline * 1.15, (
            f"zipfian_moderate: adaptive={adaptive:.4f} vs "
            f"random={baseline:.4f} (need >1.15x)"
        )

    def test_beats_random_temporal(self, results):
        r = results['temporal_locality']
        adaptive = r['adaptive_s5']['hit_ratio']
        baseline = r['random']['hit_ratio']
        assert adaptive > baseline * 1.10, (
            f"temporal: adaptive={adaptive:.4f} vs "
            f"random={baseline:.4f} (need >1.10x)"
        )

    def test_not_terrible_uniform(self, results):
        r = results['uniform']
        adaptive = r['adaptive_s5']['hit_ratio']
        baseline = r['random']['hit_ratio']
        assert adaptive >= baseline * 0.80, (
            f"uniform: adaptive={adaptive:.4f} vs "
            f"random={baseline:.4f} (need >=0.80x)"
        )

    def test_more_samples_not_much_worse(self, results):
        for scenario in results:
            s5 = results[scenario]['adaptive_s5']['hit_ratio']
            s10 = results[scenario]['adaptive_s10']['hit_ratio']
            assert s10 >= s5 - 0.03, (
                f"{scenario}: s10={s10:.4f} much worse than s5={s5:.4f}"
            )


class TestCorrectnessProperties:
    def test_clock_wrap_consistency(self):
        """Idle time must be accurate across clock wrap boundary."""
        from engine import CacheEntry, CLOCK_MAX

        entry_nowrap = CacheEntry("a", 100)
        idle_nowrap = entry_nowrap.idle_time(600)

        entry_wrap = CacheEntry("b", CLOCK_MAX - 200)
        idle_wrap = entry_wrap.idle_time(300)

        assert abs(idle_nowrap - idle_wrap) <= 1, (
            f"Idle time wrong across wrap: nowrap={idle_nowrap}, wrap={idle_wrap}"
        )

    def test_clock_wrap_ordering(self):
        """Older entry must have higher idle time even across wrap."""
        from engine import CacheEntry, CLOCK_MAX

        old_entry = CacheEntry("old", CLOCK_MAX - 1000)
        new_entry = CacheEntry("new", CLOCK_MAX - 100)
        current = 500

        old_idle = old_entry.idle_time(current)
        new_idle = new_entry.idle_time(current)
        assert old_idle > new_idle, (
            f"Order wrong: old_idle={old_idle}, new_idle={new_idle}"
        )

    def test_cache_size_invariant(self):
        """Cache must never exceed max_entries."""
        from engine import CacheEngine
        from policies import AdaptivePolicy
        from workloads import zipfian_workload

        engine = CacheEngine(50, AdaptivePolicy, seed=42, samples=5)
        trace = zipfian_workload(10000, 500, seed=42)
        for key in trace:
            engine.access(key)
            assert len(engine.store) <= 50

    def test_frequency_bounded(self):
        """Frequency counter must not grow without bound."""
        from engine import CacheEngine
        from policies import AdaptivePolicy

        engine = CacheEngine(10, AdaptivePolicy, seed=42, samples=5)
        for _ in range(10000):
            engine.access("hot_key")

        entry = engine.store.get("hot_key")
        assert entry is not None
        assert entry.frequency <= 255, (
            f"Unbounded frequency: {entry.frequency}"
        )


class TestDeterminism:
    def test_temporal_workload_determinism(self):
        """Same seed must produce same trace."""
        from workloads import temporal_locality_workload
        t1 = temporal_locality_workload(5000, 500, seed=99)
        t2 = temporal_locality_workload(5000, 500, seed=99)
        assert t1 == t2, "temporal_locality_workload not deterministic"

    def test_benchmark_reproducibility(self):
        """Re-running benchmark must match saved results."""
        with open('/app/results.json') as f:
            saved = json.load(f)

        result = subprocess.run(
            ['python3', '/app/benchmark.py'],
            capture_output=True, text=True, cwd='/app'
        )
        assert result.returncode == 0, f"Benchmark failed: {result.stderr}"

        with open('/app/results.json') as f:
            fresh = json.load(f)

        for scenario in saved:
            for policy in saved[scenario]:
                s_hr = saved[scenario][policy]['hit_ratio']
                f_hr = fresh[scenario][policy]['hit_ratio']
                assert s_hr == f_hr, (
                    f"Non-deterministic {scenario}/{policy}: "
                    f"saved={s_hr}, fresh={f_hr}"
                )
