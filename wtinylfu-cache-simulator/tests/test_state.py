
import json
import os
import subprocess
import tempfile
import random
import pytest


# ============================================================
# Python reference implementation of W-TinyLFU
# ============================================================

RESET_MASK = 0x7777777777777777
ONE_MASK = 0x1111111111111111
MIN_SKETCH_SIZE = 256


def ceiling_power_of_two(x):
    if x <= 1:
        return 1
    n = x - 1
    n |= n >> 1
    n |= n >> 2
    n |= n >> 4
    n |= n >> 8
    n |= n >> 16
    return n + 1


def spread(x):
    x = x & 0xFFFFFFFF
    x ^= (x >> 17)
    x = (x * 0xed5ad4bb) & 0xFFFFFFFF
    x ^= (x >> 11)
    x = (x * 0xac4c1b51) & 0xFFFFFFFF
    x ^= (x >> 15)
    return x


def rehash(x):
    x = x & 0xFFFFFFFF
    x = (x * 0x31848bab) & 0xFFFFFFFF
    x ^= (x >> 14)
    return x


class RefSketch:
    def __init__(self, maximum_size):
        maximum = max(maximum_size, MIN_SKETCH_SIZE)
        n = ceiling_power_of_two(maximum)
        self.table = [0] * n
        self.sample_size = min(10 * maximum, 0x7FFFFFFF)
        self.block_mask = (n >> 3) - 1
        self.size = 0

    def frequency(self, key):
        bh = spread(key & 0xFFFFFFFF)
        ch = rehash(bh)
        block = (bh & self.block_mask) << 3
        freq = 0x7FFFFFFF
        for i in range(4):
            h = ch >> (i * 8)
            idx = (h >> 1) & 15
            off = h & 1
            slot = block + off + (i * 2)
            c = (self.table[slot] >> (idx * 4)) & 0xF
            freq = min(freq, c)
        return freq

    def increment(self, key):
        bh = spread(key & 0xFFFFFFFF)
        ch = rehash(bh)
        block = (bh & self.block_mask) << 3
        added = False
        for i in range(4):
            h = ch >> (i * 8)
            idx = (h >> 1) & 15
            off = h & 1
            slot = block + off + (i * 2)
            offset = idx * 4
            mask = 0xF << offset
            if (self.table[slot] & mask) != mask:
                self.table[slot] += (1 << offset)
                added = True
        if added:
            self.size += 1
            if self.size == self.sample_size:
                self._reset()

    def _reset(self):
        count = 0
        for i in range(len(self.table)):
            count += bin(self.table[i] & ONE_MASK).count('1')
            self.table[i] = (self.table[i] >> 1) & RESET_MASK
        self.size = (self.size - (count >> 2)) >> 1


class RefCache:
    WINDOW = 0
    PROBATION = 1
    PROTECTED = 2

    def __init__(self, max_size, pct_main, pct_prot):
        self.max_size = max_size
        max_main = int(max_size * pct_main)
        self.max_protected = int(max_main * pct_prot)
        self.max_window = max_size - max_main
        self.sketch = RefSketch(max_size)
        self.data = {}
        self.window = []
        self.probation = []
        self.protected_list = []
        self.size_window = 0
        self.size_protected = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def access(self, key):
        if key not in self.data:
            self._on_miss(key)
        else:
            st = self.data[key]
            if st == self.WINDOW:
                self._on_window_hit(key)
            elif st == self.PROBATION:
                self._on_probation_hit(key)
            else:
                self._on_protected_hit(key)

    def _on_miss(self, key):
        self.misses += 1
        self.sketch.increment(int(key))
        self.data[key] = self.WINDOW
        self.window.append(key)
        self.size_window += 1
        self._evict()

    def _on_window_hit(self, key):
        self.hits += 1
        self.sketch.increment(int(key))
        self.window.remove(key)
        self.window.append(key)

    def _on_probation_hit(self, key):
        self.hits += 1
        self.sketch.increment(int(key))
        self.probation.remove(key)
        self.data[key] = self.PROTECTED
        self.protected_list.append(key)
        self.size_protected += 1
        if self.size_protected > self.max_protected:
            demote = self.protected_list.pop(0)
            self.data[demote] = self.PROBATION
            self.probation.append(demote)
            self.size_protected -= 1

    def _on_protected_hit(self, key):
        self.hits += 1
        self.sketch.increment(int(key))
        self.protected_list.remove(key)
        self.protected_list.append(key)

    def _evict(self):
        if self.size_window <= self.max_window:
            return
        candidate_key = self.window.pop(0)
        self.size_window -= 1
        self.data[candidate_key] = self.PROBATION
        self.probation.append(candidate_key)
        if len(self.data) > self.max_size:
            victim_key = self.probation[0]
            cf = self.sketch.frequency(int(candidate_key))
            vf = self.sketch.frequency(int(victim_key))
            evict_key = victim_key if cf > vf else candidate_key
            self.probation.remove(evict_key)
            del self.data[evict_key]
            self.evictions += 1

    def result(self):
        return {
            'hit_count': self.hits,
            'miss_count': self.misses,
            'eviction_count': self.evictions,
            'cache_size': len(self.data),
            'window_keys': sorted(self.window),
            'probation_keys': sorted(self.probation),
            'protected_keys': sorted(self.protected_list),
        }


# ============================================================
# Helper to run Java simulator
# ============================================================

def run_sim(trace, max_size, pct_main, pct_prot):
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', delete=False, dir='/tmp'
    ) as f:
        for k in trace:
            f.write(f"{k}\n")
        path = f.name
    try:
        r = subprocess.run(
            ['java', '-cp', '/app/bin', 'wtinylfu.CacheSimulator',
             path, str(max_size), str(pct_main), str(pct_prot)],
            capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0, (
            f"Simulator failed (exit {r.returncode}):\n"
            f"stdout: {r.stdout[:500]}\nstderr: {r.stderr[:500]}"
        )
        return json.loads(r.stdout)
    finally:
        os.unlink(path)


def compare(java_out, ref_out):
    for field in ['hit_count', 'miss_count', 'eviction_count', 'cache_size']:
        assert java_out[field] == ref_out[field], (
            f"{field}: java={java_out[field]} != ref={ref_out[field]}"
        )
    for field in ['window_keys', 'probation_keys', 'protected_keys']:
        assert java_out[field] == ref_out[field], (
            f"{field} differ:\n  java={java_out[field][:20]}...\n"
            f"  ref={ref_out[field][:20]}..."
        )


def run_ref(trace, max_size, pct_main, pct_prot):
    ref = RefCache(max_size, pct_main, pct_prot)
    for k in trace:
        ref.access(k)
    return ref.result()


# ============================================================
# Tests
# ============================================================

class TestWTinyLfuSimulator:

    def test_basic_execution(self):
        """Simulator runs on an empty trace without error."""
        out = run_sim([], 10, 0.99, 0.8)
        assert out['hit_count'] == 0
        assert out['miss_count'] == 0
        assert out['eviction_count'] == 0
        assert out['cache_size'] == 0

    def test_trivial_all_unique(self):
        """All unique keys: 100% misses."""
        trace = list(range(1, 21))
        out = run_sim(trace, 10, 0.99, 0.8)
        assert out['hit_count'] == 0
        assert out['miss_count'] == 20
        assert out['eviction_count'] == 10
        assert out['cache_size'] == 10
        total_keys = (
            len(out['window_keys']) +
            len(out['probation_keys']) +
            len(out['protected_keys'])
        )
        assert total_keys == 10
        assert len(out['protected_keys']) == 0

    def test_trivial_single_key(self):
        """Same key repeated: 1 miss then all hits."""
        trace = [42] * 50
        out = run_sim(trace, 5, 0.99, 0.8)
        assert out['hit_count'] == 49
        assert out['miss_count'] == 1
        assert out['eviction_count'] == 0
        assert out['cache_size'] == 1
        assert out['window_keys'] == [42]

    def test_reference_small(self):
        """Small deterministic trace vs Python reference."""
        trace = [1, 2, 3, 4, 5, 1, 6, 2, 3, 1, 7, 8, 9, 10, 5, 5, 5, 2, 3, 4]
        ms, pm, pp = 10, 0.99, 0.8
        java_out = run_sim(trace, ms, pm, pp)
        ref_out = run_ref(trace, ms, pm, pp)
        compare(java_out, ref_out)

    def test_reference_medium(self):
        """Medium trace with hot/cold keys vs Python reference."""
        random.seed(12345)
        trace = []
        for _ in range(2000):
            if random.random() < 0.7:
                trace.append(random.randint(1, 30))
            else:
                trace.append(random.randint(31, 200))
        ms, pm, pp = 30, 0.99, 0.8
        java_out = run_sim(trace, ms, pm, pp)
        ref_out = run_ref(trace, ms, pm, pp)
        compare(java_out, ref_out)

    def test_reference_large_with_reset(self):
        """Large trace that triggers sketch reset, vs Python reference."""
        random.seed(99999)
        trace = []
        for _ in range(5000):
            r = random.random()
            if r < 0.5:
                trace.append(random.randint(1, 20))
            elif r < 0.8:
                trace.append(random.randint(21, 100))
            else:
                trace.append(random.randint(101, 500))
        ms, pm, pp = 50, 0.99, 0.8
        java_out = run_sim(trace, ms, pm, pp)
        ref_out = run_ref(trace, ms, pm, pp)
        compare(java_out, ref_out)

    def test_reference_different_config(self):
        """Different cache configuration (larger window, smaller protected)."""
        random.seed(77777)
        trace = []
        for _ in range(1500):
            if random.random() < 0.6:
                trace.append(random.randint(1, 15))
            else:
                trace.append(random.randint(16, 80))
        ms, pm, pp = 20, 0.8, 0.5
        java_out = run_sim(trace, ms, pm, pp)
        ref_out = run_ref(trace, ms, pm, pp)
        compare(java_out, ref_out)

    def test_cache_size_one(self):
        """Edge case: cache with capacity 1."""
        trace = [1, 2, 1, 3, 1, 2, 3, 1, 4, 5, 1, 1, 2]
        ms, pm, pp = 1, 0.99, 0.8
        java_out = run_sim(trace, ms, pm, pp)
        ref_out = run_ref(trace, ms, pm, pp)
        compare(java_out, ref_out)

    def test_zero_window(self):
        """With percent_main=1.0, window has zero capacity."""
        random.seed(11111)
        trace = [random.randint(1, 50) for _ in range(500)]
        ms, pm, pp = 20, 1.0, 0.8
        java_out = run_sim(trace, ms, pm, pp)
        ref_out = run_ref(trace, ms, pm, pp)
        compare(java_out, ref_out)
        assert len(java_out['window_keys']) == 0

    def test_large_trace_many_resets(self):
        """Large trace triggering many sketch resets."""
        random.seed(42424)
        trace = [random.randint(1, 1000) for _ in range(20000)]
        ms, pm, pp = 100, 0.99, 0.8
        java_out = run_sim(trace, ms, pm, pp)
        ref_out = run_ref(trace, ms, pm, pp)
        compare(java_out, ref_out)

    def test_high_contention_small_cache(self):
        """High contention: many keys competing for few cache slots."""
        random.seed(33333)
        trace = []
        for _ in range(3000):
            r = random.random()
            if r < 0.3:
                trace.append(random.randint(1, 5))
            elif r < 0.6:
                trace.append(random.randint(6, 20))
            else:
                trace.append(random.randint(21, 500))
        ms, pm, pp = 8, 0.99, 0.8
        java_out = run_sim(trace, ms, pm, pp)
        ref_out = run_ref(trace, ms, pm, pp)
        compare(java_out, ref_out)

    def test_invariants_multiple_configs(self):
        """Structural invariants hold across varied configurations."""
        random.seed(54321)
        configs = [
            (20, 0.99, 0.8),
            (10, 0.8, 0.5),
            (50, 0.95, 0.9),
            (15, 0.9, 0.7),
        ]
        for ms, pm, pp in configs:
            trace = [random.randint(1, 100) for _ in range(500)]
            out = run_sim(trace, ms, pm, pp)

            assert out['hit_count'] + out['miss_count'] == len(trace), (
                f"Config ({ms},{pm},{pp}): "
                f"hits({out['hit_count']})+misses({out['miss_count']}) != {len(trace)}"
            )
            assert out['cache_size'] == out['miss_count'] - out['eviction_count'], (
                f"Config ({ms},{pm},{pp}): "
                f"cache_size({out['cache_size']}) != "
                f"misses({out['miss_count']})-evictions({out['eviction_count']})"
            )
            assert out['cache_size'] <= ms, (
                f"Config ({ms},{pm},{pp}): cache_size({out['cache_size']}) > {ms}"
            )
            total_keys = (
                len(out['window_keys']) +
                len(out['probation_keys']) +
                len(out['protected_keys'])
            )
            assert total_keys == out['cache_size'], (
                f"Config ({ms},{pm},{pp}): "
                f"segment sum({total_keys}) != cache_size({out['cache_size']})"
            )
            # No duplicate keys across segments
            all_keys = (
                out['window_keys'] + out['probation_keys'] + out['protected_keys']
            )
            assert len(all_keys) == len(set(all_keys)), (
                f"Config ({ms},{pm},{pp}): duplicate keys across segments"
            )
