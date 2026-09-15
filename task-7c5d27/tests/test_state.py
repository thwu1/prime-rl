
"""Tests for MESI cache coherence simulator outputs."""

import json
import os
import sys
import math
import pytest

sys.path.insert(0, '/tests')
from reference_sim import MESISimulator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path) as f:
        return json.load(f)


def run_reference(trace_path, num_cores, cache_size, associativity, line_size):
    sim = MESISimulator(num_cores, cache_size, associativity, line_size)
    sim.run_trace(trace_path)
    return sim.get_stats()


# ---------------------------------------------------------------------------
# Test 0: Sanity-check the reference implementation against hand-traced values
# ---------------------------------------------------------------------------

class TestReferenceValidation:
    """Verify the reference simulator itself is correct using the hand-traced test vector."""

    def test_reference_on_test_vector(self):
        ref = run_reference('/app/traces/test_vector.trace',
                            num_cores=2, cache_size=64, associativity=1, line_size=32)
        c0 = ref['per_core'][0]
        c1 = ref['per_core'][1]

        assert c0['hits'] == 1
        assert c0['misses'] == 3
        assert c0['evictions'] == 1
        assert c0['writebacks'] == 1
        assert c0['invalidations_received'] == 0
        assert c0['upgrades'] == 1

        assert c1['hits'] == 0
        assert c1['misses'] == 2
        assert c1['evictions'] == 0
        assert c1['writebacks'] == 0
        assert c1['invalidations_received'] == 1
        assert c1['upgrades'] == 0

        assert ref['total_hits'] == 1
        assert ref['total_misses'] == 5
        assert ref['bus_transactions'] == 6
        assert ref['total_invalidations'] == 1
        assert ref['memory_reads'] == 5
        assert ref['memory_writes'] == 1


# ---------------------------------------------------------------------------
# Test 1: Output files exist and have correct schema
# ---------------------------------------------------------------------------

class TestOutputFormat:

    def test_stats_json_exists(self):
        assert os.path.exists('/app/output/stats.json'), \
            "stats.json not found at /app/output/stats.json"

    def test_min_size_json_exists(self):
        assert os.path.exists('/app/output/min_size.json'), \
            "min_size.json not found at /app/output/min_size.json"

    def test_stats_schema(self):
        stats = load_json('/app/output/stats.json')
        assert 'config' in stats
        assert stats['config']['num_cores'] == 4
        assert stats['config']['cache_size'] == 2048
        assert stats['config']['associativity'] == 4
        assert stats['config']['line_size'] == 64
        assert 'per_core' in stats
        assert len(stats['per_core']) == 4
        for core in stats['per_core']:
            for key in ('core_id', 'hits', 'misses', 'hit_rate',
                        'evictions', 'writebacks', 'invalidations_received', 'upgrades'):
                assert key in core, f"Missing key '{key}' in per_core entry"
        for key in ('total_hits', 'total_misses', 'overall_miss_rate',
                     'bus_transactions', 'total_invalidations',
                     'memory_reads', 'memory_writes'):
            assert key in stats, f"Missing top-level key '{key}'"

    def test_min_size_schema(self):
        ms = load_json('/app/output/min_size.json')
        assert 'min_cache_size_bytes' in ms
        assert 'miss_rate_at_min' in ms
        assert 'miss_rate_at_half' in ms
        assert ms['min_cache_size_bytes'] in (512, 1024, 2048, 4096, 8192, 16384, 32768)


# ---------------------------------------------------------------------------
# Test 2: Baseline statistics correctness
# ---------------------------------------------------------------------------

class TestBaselineStats:
    """Compare agent output against reference for workload.trace with baseline config."""

    @pytest.fixture(scope='class')
    def ref_stats(self):
        return run_reference('/app/traces/workload.trace',
                             num_cores=4, cache_size=2048,
                             associativity=4, line_size=64)

    @pytest.fixture(scope='class')
    def agent_stats(self):
        return load_json('/app/output/stats.json')

    def test_total_hits(self, ref_stats, agent_stats):
        assert agent_stats['total_hits'] == ref_stats['total_hits']

    def test_total_misses(self, ref_stats, agent_stats):
        assert agent_stats['total_misses'] == ref_stats['total_misses']

    def test_overall_miss_rate(self, ref_stats, agent_stats):
        assert abs(agent_stats['overall_miss_rate'] - ref_stats['overall_miss_rate']) < 1e-6

    def test_bus_transactions(self, ref_stats, agent_stats):
        assert agent_stats['bus_transactions'] == ref_stats['bus_transactions']

    def test_total_invalidations(self, ref_stats, agent_stats):
        assert agent_stats['total_invalidations'] == ref_stats['total_invalidations']

    def test_memory_reads(self, ref_stats, agent_stats):
        assert agent_stats['memory_reads'] == ref_stats['memory_reads']

    def test_memory_writes(self, ref_stats, agent_stats):
        assert agent_stats['memory_writes'] == ref_stats['memory_writes']

    def test_per_core_hits(self, ref_stats, agent_stats):
        for i in range(4):
            assert agent_stats['per_core'][i]['hits'] == ref_stats['per_core'][i]['hits'], \
                f"Core {i} hits mismatch"

    def test_per_core_misses(self, ref_stats, agent_stats):
        for i in range(4):
            assert agent_stats['per_core'][i]['misses'] == ref_stats['per_core'][i]['misses'], \
                f"Core {i} misses mismatch"

    def test_per_core_evictions(self, ref_stats, agent_stats):
        for i in range(4):
            assert agent_stats['per_core'][i]['evictions'] == ref_stats['per_core'][i]['evictions'], \
                f"Core {i} evictions mismatch"

    def test_per_core_writebacks(self, ref_stats, agent_stats):
        for i in range(4):
            assert agent_stats['per_core'][i]['writebacks'] == ref_stats['per_core'][i]['writebacks'], \
                f"Core {i} writebacks mismatch"

    def test_per_core_invalidations(self, ref_stats, agent_stats):
        for i in range(4):
            assert agent_stats['per_core'][i]['invalidations_received'] == \
                ref_stats['per_core'][i]['invalidations_received'], \
                f"Core {i} invalidations_received mismatch"

    def test_per_core_upgrades(self, ref_stats, agent_stats):
        for i in range(4):
            assert agent_stats['per_core'][i]['upgrades'] == ref_stats['per_core'][i]['upgrades'], \
                f"Core {i} upgrades mismatch"

    def test_consistency_hits_plus_misses(self, agent_stats):
        total_accesses = agent_stats['total_hits'] + agent_stats['total_misses']
        per_core_sum = sum(c['hits'] + c['misses'] for c in agent_stats['per_core'])
        assert total_accesses == per_core_sum
        assert total_accesses == 8000  # 4 phases x 2000 accesses

    def test_consistency_miss_rate(self, agent_stats):
        expected_rate = agent_stats['total_misses'] / (
            agent_stats['total_hits'] + agent_stats['total_misses'])
        assert abs(agent_stats['overall_miss_rate'] - expected_rate) < 1e-6


# ---------------------------------------------------------------------------
# Test 3: Design-space exploration (min_size.json)
# ---------------------------------------------------------------------------

class TestMinSize:

    @pytest.fixture(scope='class')
    def agent_result(self):
        return load_json('/app/output/min_size.json')

    def test_miss_rate_below_threshold(self, agent_result):
        """Verify the claimed min size achieves <10% miss rate."""
        size = agent_result['min_cache_size_bytes']
        ref = run_reference('/app/traces/workload.trace',
                            num_cores=4, cache_size=size,
                            associativity=4, line_size=64)
        assert ref['overall_miss_rate'] < 0.10, \
            f"Miss rate {ref['overall_miss_rate']:.4f} at size {size} is not < 0.10"

    def test_half_size_above_threshold(self, agent_result):
        """Verify that half the min size does NOT achieve <10% miss rate."""
        size = agent_result['min_cache_size_bytes']
        if size <= 512:
            pytest.skip("Minimum is 512, no smaller size to check")
        half = size // 2
        ref = run_reference('/app/traces/workload.trace',
                            num_cores=4, cache_size=half,
                            associativity=4, line_size=64)
        assert ref['overall_miss_rate'] >= 0.10, \
            f"Miss rate {ref['overall_miss_rate']:.4f} at size {half} is < 0.10, " \
            f"so {size} is not the minimum"

    def test_miss_rate_at_min_matches(self, agent_result):
        """Verify reported miss_rate_at_min is accurate."""
        size = agent_result['min_cache_size_bytes']
        ref = run_reference('/app/traces/workload.trace',
                            num_cores=4, cache_size=size,
                            associativity=4, line_size=64)
        assert abs(agent_result['miss_rate_at_min'] - ref['overall_miss_rate']) < 1e-4

    def test_miss_rate_at_half_matches(self, agent_result):
        """Verify reported miss_rate_at_half is accurate."""
        size = agent_result['min_cache_size_bytes']
        if size <= 512:
            assert agent_result['miss_rate_at_half'] == 1.0
            return
        half = size // 2
        ref = run_reference('/app/traces/workload.trace',
                            num_cores=4, cache_size=half,
                            associativity=4, line_size=64)
        assert abs(agent_result['miss_rate_at_half'] - ref['overall_miss_rate']) < 1e-4
