
import json
import math
import os
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Reference cache simulator (known-correct Python implementation)
# ---------------------------------------------------------------------------

class CacheLine:
    __slots__ = ['valid', 'dirty', 'tag', 'last_used']

    def __init__(self):
        self.valid = False
        self.dirty = False
        self.tag = 0
        self.last_used = 0


class CacheSimulator:
    def __init__(self, capacity, block_size, associativity):
        self.capacity = capacity
        self.block_size = block_size
        self.associativity = associativity
        self.n_sets = capacity // (block_size * associativity)
        self.n_offset_bits = int(math.log2(block_size))
        self.n_index_bits = int(math.log2(self.n_sets)) if self.n_sets > 1 else 0

        self.sets = [
            [CacheLine() for _ in range(associativity)]
            for _ in range(self.n_sets)
        ]

        self.hits = 0
        self.misses = 0
        self.writebacks = 0
        self.n_stores = 0
        self.n_loads = 0
        self.time = 0

    def _get_tag(self, addr):
        return addr >> (self.n_offset_bits + self.n_index_bits)

    def _get_index(self, addr):
        if self.n_index_bits == 0:
            return 0
        return (addr >> self.n_offset_bits) & ((1 << self.n_index_bits) - 1)

    def access(self, op, addr):
        self.time += 1
        tag = self._get_tag(addr)
        index = self._get_index(addr)
        is_write = (op == 'w')

        if is_write:
            self.n_stores += 1
        else:
            self.n_loads += 1

        cache_set = self.sets[index]

        # Check for hit
        for line in cache_set:
            if line.valid and line.tag == tag:
                self.hits += 1
                line.last_used = self.time
                if is_write:
                    line.dirty = True
                return True

        # Miss
        self.misses += 1

        # Find victim: prefer first invalid (lowest way index)
        victim = None
        for line in cache_set:
            if not line.valid:
                victim = line
                break

        if victim is None:
            # True LRU: evict the line with smallest last_used
            victim = min(cache_set, key=lambda l: l.last_used)

        # Writeback if evicting a dirty line
        if victim.valid and victim.dirty:
            self.writebacks += 1

        # Install new line
        victim.valid = True
        victim.tag = tag
        victim.dirty = is_write
        victim.last_used = self.time

        return False

    def run_trace(self, trace_path):
        with open(trace_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    self.access(parts[0], int(parts[1], 16))

    def stats(self):
        total = self.hits + self.misses
        hit_rate = round(self.hits / total * 100, 2) if total > 0 else 0.0
        miss_rate = round(self.misses / total * 100, 2) if total > 0 else 0.0
        bus_to_cache = self.misses * self.block_size
        cache_to_bus_wb = self.writebacks * self.block_size
        total_traffic_wb = bus_to_cache + cache_to_bus_wb
        cache_to_bus_wt = self.n_stores * 4
        total_traffic_wt = bus_to_cache + cache_to_bus_wt
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writebacks": self.writebacks,
            "hit_rate": hit_rate,
            "miss_rate": miss_rate,
            "n_stores": self.n_stores,
            "bus_to_cache": bus_to_cache,
            "cache_to_bus_wb": cache_to_bus_wb,
            "total_traffic_wb": total_traffic_wb,
            "cache_to_bus_wt": cache_to_bus_wt,
            "total_traffic_wt": total_traffic_wt,
        }


def run_sim(trace_path, capacity, block_size, assoc):
    sim = CacheSimulator(capacity, block_size, assoc)
    sim.run_trace(trace_path)
    return sim.stats()


# ---------------------------------------------------------------------------
# Binary output parser
# ---------------------------------------------------------------------------

def parse_binary_output(stdout):
    """Parse key-value output from the cachesim binary."""
    stats = {}
    for line in stdout.strip().split('\n'):
        parts = line.split()
        if len(parts) == 2:
            key = parts[0]
            try:
                if '.' in parts[1]:
                    stats[key] = float(parts[1])
                else:
                    stats[key] = int(parts[1])
            except ValueError:
                pass
    return stats


def run_binary(trace, capacity, block_size, assoc):
    """Run the cachesim binary and return parsed stats."""
    result = subprocess.run(
        ['/app/cachesim', trace, str(capacity), str(block_size), str(assoc)],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"cachesim exited with code {result.returncode}: {result.stderr}"
    )
    return parse_binary_output(result.stdout)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INT_FIELDS = [
    'hits', 'misses', 'writebacks', 'n_stores',
    'bus_to_cache', 'cache_to_bus_wb', 'total_traffic_wb',
    'cache_to_bus_wt', 'total_traffic_wt',
]
FLOAT_FIELDS = ['hit_rate']


def assert_int(actual, expected, field):
    assert int(actual[field]) == expected[field], (
        f"{field}: expected {expected[field]}, got {actual[field]}"
    )


def assert_float(actual, expected, field, tol=0.02):
    assert abs(float(actual[field]) - expected[field]) < tol, (
        f"{field}: expected {expected[field]}, got {actual[field]}"
    )


def check_full_stats(actual, expected):
    for f in INT_FIELDS:
        assert_int(actual, expected, f)
    for f in FLOAT_FIELDS:
        assert_float(actual, expected, f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def answers():
    path = '/app/answers.json'
    assert os.path.exists(path), "answers.json not found at /app/answers.json"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Binary Tests — verify the cachesim binary itself is correct
# ---------------------------------------------------------------------------

class TestBinary:
    """Verify the cachesim binary produces correct results."""

    def test_binary_exists(self):
        assert os.path.isfile('/app/cachesim'), "/app/cachesim not found"
        assert os.access('/app/cachesim', os.X_OK), "/app/cachesim not executable"

    def test_reference_trace(self):
        stats = run_binary('/app/traces/trace_ref.txt', 64, 32, 1)
        expected = run_sim('/app/traces/trace_ref.txt', 64, 32, 1)
        for f in INT_FIELDS:
            assert_int(stats, expected, f)
        for f in FLOAT_FIELDS:
            assert_float(stats, expected, f)

    def test_binary_trace_a_direct(self):
        stats = run_binary('/app/traces/trace_a.txt', 512, 32, 1)
        expected = run_sim('/app/traces/trace_a.txt', 512, 32, 1)
        for f in INT_FIELDS:
            assert_int(stats, expected, f)

    def test_binary_trace_b_4way(self):
        """Test with 4-way associativity to verify LRU and dirty-bit logic."""
        stats = run_binary('/app/traces/trace_b.txt', 4096, 64, 4)
        expected = run_sim('/app/traces/trace_b.txt', 4096, 64, 4)
        for f in INT_FIELDS:
            assert_int(stats, expected, f)

    def test_binary_trace_c_8way(self):
        """Test with 8-way associativity (fully associative for 2048B/32B)."""
        stats = run_binary('/app/traces/trace_c.txt', 2048, 32, 8)
        expected = run_sim('/app/traces/trace_c.txt', 2048, 32, 8)
        for f in INT_FIELDS:
            assert_int(stats, expected, f)

    def test_binary_write_through_stats(self):
        """Specifically verify write-through traffic formula."""
        stats = run_binary('/app/traces/trace_ref.txt', 64, 32, 1)
        assert stats['cache_to_bus_wt'] == 4, (
            f"cache_to_bus_wt should be n_stores*4=4, got {stats['cache_to_bus_wt']}"
        )
        assert stats['total_traffic_wt'] == 132, (
            f"total_traffic_wt should be 132, got {stats['total_traffic_wt']}"
        )


# ---------------------------------------------------------------------------
# Answer Tests — verify answers.json
# ---------------------------------------------------------------------------

class TestQ1:
    def test_q1(self, answers):
        expected = run_sim('/app/traces/trace_a.txt', 512, 32, 1)
        check_full_stats(answers['q1'], expected)


class TestQ2:
    def test_q2(self, answers):
        expected = run_sim('/app/traces/trace_b.txt', 4096, 64, 4)
        check_full_stats(answers['q2'], expected)


class TestQ3:
    def test_q3_associativity_results(self, answers):
        q3 = answers['q3']
        assert 'results' in q3, "q3 missing 'results' key"
        assert 'best_associativity' in q3, "q3 missing 'best_associativity' key"

        best_miss_rate = float('inf')
        best_a = None
        for a in [1, 2, 4, 8]:
            expected = run_sim('/app/traces/trace_c.txt', 2048, 32, a)
            key = str(a)
            assert key in q3['results'], f"Missing associativity {a} in q3.results"
            r = q3['results'][key]
            assert abs(float(r['miss_rate']) - expected['miss_rate']) < 0.02, (
                f"A={a} miss_rate: expected {expected['miss_rate']}, got {r['miss_rate']}"
            )
            assert int(r['total_traffic_wb']) == expected['total_traffic_wb'], (
                f"A={a} total_traffic_wb: expected {expected['total_traffic_wb']}, "
                f"got {r['total_traffic_wb']}"
            )
            if expected['miss_rate'] < best_miss_rate:
                best_miss_rate = expected['miss_rate']
                best_a = a

        assert int(q3['best_associativity']) == best_a, (
            f"best_associativity: expected {best_a}, got {q3['best_associativity']}"
        )


class TestQ4:
    def test_q4_amat(self, answers):
        q4 = answers['q4']
        configs = [
            (256, 16, 1),
            (512, 32, 1),
            (512, 32, 2),
            (1024, 32, 2),
            (1024, 64, 4),
        ]
        assert 'configs' in q4, "q4 missing 'configs' key"
        assert len(q4['configs']) == 5, f"q4.configs has {len(q4['configs'])} entries, expected 5"
        assert 'best_config_index' in q4, "q4 missing 'best_config_index' key"

        best_amat = float('inf')
        best_idx = None
        for i, (c, b, a) in enumerate(configs):
            s = run_sim('/app/traces/trace_a.txt', c, b, a)
            total = s['hits'] + s['misses']
            miss_frac = s['misses'] / total if total > 0 else 0
            expected_amat = round(1 + miss_frac * 100, 2)
            actual_amat = float(q4['configs'][i]['amat'])
            assert abs(actual_amat - expected_amat) < 0.02, (
                f"Config {i} (C={c},B={b},A={a}) AMAT: "
                f"expected {expected_amat}, got {actual_amat}"
            )
            if expected_amat < best_amat:
                best_amat = expected_amat
                best_idx = i

        assert int(q4['best_config_index']) == best_idx, (
            f"best_config_index: expected {best_idx}, got {q4['best_config_index']}"
        )


class TestQ5:
    def test_q5_min_traffic(self, answers):
        q5 = answers['q5']
        assert 'best_config' in q5, "q5 missing 'best_config' key"
        assert 'min_traffic' in q5, "q5 missing 'min_traffic' key"

        best_traffic = float('inf')
        best_config = None
        # Iterate in tie-breaking order: smallest C, then B, then A
        for c in [512, 1024, 2048, 4096]:
            for b in [16, 32, 64]:
                for a in [1, 2, 4]:
                    s = run_sim('/app/traces/trace_b.txt', c, b, a)
                    t = s['total_traffic_wb']
                    if t < best_traffic:
                        best_traffic = t
                        best_config = (c, b, a)

        ac = q5['best_config']
        assert int(ac['capacity']) == best_config[0], (
            f"capacity: expected {best_config[0]}, got {ac['capacity']}"
        )
        assert int(ac['block_size']) == best_config[1], (
            f"block_size: expected {best_config[1]}, got {ac['block_size']}"
        )
        assert int(ac['associativity']) == best_config[2], (
            f"associativity: expected {best_config[2]}, got {ac['associativity']}"
        )
        assert int(q5['min_traffic']) == best_traffic, (
            f"min_traffic: expected {best_traffic}, got {q5['min_traffic']}"
        )
