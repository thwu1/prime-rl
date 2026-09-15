"""Tests for the parallel statistics computation pipeline and multi-architecture layout design.

Verifies that:
- The pipeline produces correct output files
- Statistics match independent sequential Welford computation
- Accumulator combine works correctly for equal/unequal groups
- Warp reduction handles full and partial warps
- Bank conflict detection is accurate
- Design report evaluates layouts across both architectures and identifies
  the optimal cross-architecture struct layout with justification
"""


import json
import math
import os
import sys

sys.path.insert(0, '/app')

TOLERANCE_REL = 1e-9
TOLERANCE_ABS = 1e-12


class ReferenceAccumulator:
    """Independent reference implementation of sequential Welford for all moments."""

    def __init__(self):
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.m3 = 0.0
        self.m4 = 0.0

    def update(self, x):
        n1 = self.count
        self.count += 1
        n = self.count
        delta = x - self.mean
        delta_n = delta / n
        delta_n2 = delta_n * delta_n
        term1 = delta * delta_n * n1

        self.m4 += (term1 * delta_n2 * (n * n - 3 * n + 3)
                    + 6 * delta_n2 * self.m2
                    - 4 * delta_n * self.m3)
        self.m3 += term1 * delta_n * (n - 2) - 3 * delta_n * self.m2
        self.m2 += term1
        self.mean += delta_n

    def finalize(self):
        if self.count < 2:
            return {'count': self.count, 'mean': self.mean,
                    'variance': 0.0, 'skewness': 0.0, 'kurtosis': 0.0}
        variance = self.m2 / self.count
        if abs(self.m2) < 1e-30:
            return {'count': self.count, 'mean': self.mean,
                    'variance': variance, 'skewness': 0.0, 'kurtosis': 0.0}
        skewness = (self.count ** 0.5 * self.m3) / (self.m2 ** 1.5)
        kurtosis = (self.count * self.m4) / (self.m2 * self.m2) - 3.0
        return {'count': self.count, 'mean': self.mean,
                'variance': variance, 'skewness': skewness, 'kurtosis': kurtosis}


def load_dataset(filepath):
    values = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                values.append(float(line))
    return values


def compute_reference(data):
    acc = ReferenceAccumulator()
    for x in data:
        acc.update(x)
    return acc.finalize()


def close_enough(actual, expected):
    """Check if actual is close enough to expected using combined tolerance."""
    if abs(expected) < TOLERANCE_ABS:
        return abs(actual - expected) < TOLERANCE_ABS
    return abs(actual - expected) / abs(expected) < TOLERANCE_REL


# --- Pipeline output tests ---


class TestPipelineOutput:

    def test_statistics_file_exists(self):
        assert os.path.exists('/app/output/statistics.json'), \
            "statistics.json not found -- ensure parallel_reduce.py has been run"

    def test_bank_analysis_file_exists(self):
        assert os.path.exists('/app/output/bank_analysis.json'), \
            "bank_analysis.json not found -- ensure parallel_reduce.py has been run"

    def test_statistics_accuracy_uniform(self):
        self._check_dataset('uniform')

    def test_statistics_accuracy_normal(self):
        self._check_dataset('normal')

    def test_statistics_accuracy_skewed(self):
        self._check_dataset('skewed')

    def test_statistics_accuracy_bimodal(self):
        self._check_dataset('bimodal')

    def _check_dataset(self, name):
        with open('/app/output/statistics.json', 'r') as f:
            results = json.load(f)

        assert name in results, f"Missing results for dataset '{name}'"

        data = load_dataset(f'/app/data/{name}.csv')
        expected = compute_reference(data)
        actual = results[name]

        assert actual['count'] == expected['count'], \
            f"{name}: count {actual['count']} != {expected['count']}"

        for key in ['mean', 'variance', 'skewness', 'kurtosis']:
            assert close_enough(actual[key], expected[key]), \
                f"{name}.{key}: {actual[key]} vs {expected[key]} " \
                f"(err={abs(actual[key] - expected[key])})"


# --- Direct accumulator combine tests ---


class TestAccumulatorCombine:

    def test_combine_equal_groups(self):
        from simulator.accumulator import WelfordAccumulator

        data = [float(i) for i in range(100)]

        a = WelfordAccumulator()
        for x in data[:50]:
            a.update(x)

        b = WelfordAccumulator()
        for x in data[50:]:
            b.update(x)

        combined = WelfordAccumulator.combine(a, b)
        actual = combined.finalize()

        expected = compute_reference(data)

        assert actual['count'] == 100
        for key in ['mean', 'variance', 'skewness', 'kurtosis']:
            assert close_enough(actual[key], expected[key]), \
                f"equal_groups.{key}: {actual[key]} vs {expected[key]}"

    def test_combine_unequal_groups(self):
        from simulator.accumulator import WelfordAccumulator

        data = [float(i * i - 3 * i + 7) for i in range(200)]

        a = WelfordAccumulator()
        for x in data[:30]:
            a.update(x)

        b = WelfordAccumulator()
        for x in data[30:]:
            b.update(x)

        combined = WelfordAccumulator.combine(a, b)
        actual = combined.finalize()

        expected = compute_reference(data)

        assert actual['count'] == 200
        for key in ['mean', 'variance', 'skewness', 'kurtosis']:
            assert close_enough(actual[key], expected[key]), \
                f"unequal_groups.{key}: {actual[key]} vs {expected[key]}"

    def test_combine_with_empty(self):
        from simulator.accumulator import WelfordAccumulator

        a = WelfordAccumulator()
        for x in [1.0, 2.0, 3.0]:
            a.update(x)

        b = WelfordAccumulator()  # empty

        combined_ab = WelfordAccumulator.combine(a, b)
        assert combined_ab.count == 3
        assert close_enough(combined_ab.mean, 2.0)

        combined_ba = WelfordAccumulator.combine(b, a)
        assert combined_ba.count == 3
        assert close_enough(combined_ba.mean, 2.0)

    def test_combine_chain(self):
        """Combine four groups sequentially and verify result."""
        from simulator.accumulator import WelfordAccumulator

        data = [float(x) for x in [3, 7, 1, 9, 5, 2, 8, 4, 6, 0,
                                     11, 13, 15, 12, 14, 10, 17, 19, 16, 18]]

        groups = [data[:5], data[5:10], data[10:15], data[15:]]
        accs = []
        for group in groups:
            acc = WelfordAccumulator()
            for x in group:
                acc.update(x)
            accs.append(acc)

        result = accs[0]
        for i in range(1, len(accs)):
            result = WelfordAccumulator.combine(result, accs[i])

        actual = result.finalize()
        expected = compute_reference(data)

        assert actual['count'] == len(data)
        for key in ['mean', 'variance', 'skewness', 'kurtosis']:
            assert close_enough(actual[key], expected[key]), \
                f"chain.{key}: {actual[key]} vs {expected[key]}"


# --- Warp reduction tests ---


class TestWarpReduce:

    def test_full_warp(self):
        from simulator.accumulator import WelfordAccumulator
        from simulator.warp import warp_reduce

        data = [float(i) for i in range(32)]
        accs = []
        for x in data:
            a = WelfordAccumulator()
            a.update(x)
            accs.append(a)

        result = warp_reduce(accs, WelfordAccumulator.combine, warp_size=32)
        actual = result.finalize()
        expected = compute_reference(data)

        assert actual['count'] == 32
        assert close_enough(actual['mean'], expected['mean']), \
            f"full_warp mean: {actual['mean']} vs {expected['mean']}"
        assert close_enough(actual['variance'], expected['variance']), \
            f"full_warp variance: {actual['variance']} vs {expected['variance']}"

    def test_partial_warp(self):
        """Fewer than warp_size elements -- padding must not corrupt results."""
        from simulator.accumulator import WelfordAccumulator
        from simulator.warp import warp_reduce

        data = [float(i * 7 + 3) for i in range(20)]  # 20 < 32
        accs = []
        for x in data:
            a = WelfordAccumulator()
            a.update(x)
            accs.append(a)

        result = warp_reduce(accs, WelfordAccumulator.combine, warp_size=32)
        actual = result.finalize()
        expected = compute_reference(data)

        assert actual['count'] == 20, \
            f"partial_warp count: {actual['count']} (expected 20)"
        assert close_enough(actual['mean'], expected['mean']), \
            f"partial_warp mean: {actual['mean']} vs {expected['mean']}"
        assert close_enough(actual['variance'], expected['variance']), \
            f"partial_warp variance: {actual['variance']} vs {expected['variance']}"

    def test_single_element_warp(self):
        from simulator.accumulator import WelfordAccumulator
        from simulator.warp import warp_reduce

        acc = WelfordAccumulator()
        acc.update(42.0)

        result = warp_reduce([acc], WelfordAccumulator.combine, warp_size=32)
        assert result.count == 1
        assert close_enough(result.mean, 42.0)


# --- Bank conflict tests ---


class TestBankConflicts:

    def test_bank_calculation_basic(self):
        """Verify word-addressed bank mapping."""
        from simulator.shared_memory import SharedMemorySimulator

        sim = SharedMemorySimulator(num_banks=32, bank_width_bytes=4)

        # Byte address 0 -> word 0 -> bank 0
        assert sim.get_bank(0) == 0
        # Byte address 4 -> word 1 -> bank 1
        assert sim.get_bank(4) == 1
        # Byte address 8 -> word 2 -> bank 2
        assert sim.get_bank(8) == 2
        # Byte address 124 -> word 31 -> bank 31
        assert sim.get_bank(124) == 31
        # Byte address 128 -> word 32 -> bank 0 (wraps)
        assert sim.get_bank(128) == 0

    def test_no_conflicts_unit_stride(self):
        """32 threads accessing consecutive 4-byte words: zero conflicts."""
        from simulator.shared_memory import SharedMemorySimulator

        sim = SharedMemorySimulator(num_banks=32, bank_width_bytes=4)
        addresses = [i * 4 for i in range(32)]
        assert sim.count_conflicts(addresses) == 0

    def test_stride_two_conflicts(self):
        """Stride-2 word access: 16 conflicts (2-way on 16 banks)."""
        from simulator.shared_memory import SharedMemorySimulator

        sim = SharedMemorySimulator(num_banks=32, bank_width_bytes=4)
        # Each thread accesses every other word (stride = 8 bytes = 2 words)
        addresses = [i * 8 for i in range(32)]
        conflicts = sim.count_conflicts(addresses)
        assert conflicts == 16, f"Expected 16 conflicts, got {conflicts}"

    def test_40byte_struct_has_conflicts(self):
        """40-byte struct: stride 10 words, gcd(10,32)=2, expect conflicts."""
        from simulator.shared_memory import SharedMemorySimulator

        sim = SharedMemorySimulator(num_banks=32, bank_width_bytes=4)

        struct_size = 40
        # Check field at offset 0
        addresses = [i * struct_size for i in range(32)]
        conflicts = sim.count_conflicts(addresses)
        assert conflicts == 16, f"Expected 16 conflicts for 40-byte struct, got {conflicts}"

    def test_44byte_struct_no_conflicts(self):
        """44-byte struct: stride 11 words, gcd(11,32)=1, zero conflicts."""
        from simulator.shared_memory import SharedMemorySimulator

        sim = SharedMemorySimulator(num_banks=32, bank_width_bytes=4)

        struct_size = 44
        for field_offset in [0, 8, 16, 24, 32]:
            addresses = [i * struct_size + field_offset for i in range(32)]
            conflicts = sim.count_conflicts(addresses)
            assert conflicts == 0, \
                f"44-byte struct offset {field_offset}: expected 0 conflicts, got {conflicts}"

    def test_optimal_padding(self):
        """Find minimum padding for 40-byte struct to be conflict-free."""
        from simulator.shared_memory import SharedMemorySimulator

        sim = SharedMemorySimulator(num_banks=32, bank_width_bytes=4)

        field_offsets = [0, 8, 16, 24, 32]
        result = sim.find_optimal_padding(40, field_offsets, 32)

        assert result['optimal_padding_bytes'] == 4, \
            f"Expected 4 bytes padding, got {result['optimal_padding_bytes']}"
        assert result['padded_struct_size_bytes'] == 44
        assert result['conflicts_eliminated'] is True

    def test_bank_analysis_output(self):
        """Verify the bank analysis output file has correct values."""
        if not os.path.exists('/app/output/bank_analysis.json'):
            return  # skip if pipeline hasn't been run

        with open('/app/output/bank_analysis.json', 'r') as f:
            analysis = json.load(f)

        assert analysis['struct_size_bytes'] == 40
        # 5 fields x 16 conflicts each = 80 total
        assert analysis['total_conflicts_per_warp'] == 80, \
            f"Expected 80 total conflicts, got {analysis['total_conflicts_per_warp']}"
        assert analysis['padding']['optimal_padding_bytes'] == 4
        assert analysis['padding']['padded_struct_size_bytes'] == 44
        assert analysis['padding']['conflicts_eliminated'] is True

    def test_44byte_conflicts_on_33_banks(self):
        """44-byte struct has catastrophic conflicts on 33-bank architecture."""
        from simulator.shared_memory import SharedMemorySimulator

        sim = SharedMemorySimulator(num_banks=33, bank_width_bytes=4)

        struct_size = 44
        addresses = [i * struct_size for i in range(32)]
        conflicts = sim.count_conflicts(addresses)
        # stride=11 words, gcd(11,33)=11, only 3 banks used
        # 32 threads across 3 banks: 11+11+10 -> conflicts = 10+10+9 = 29
        assert conflicts == 29, \
            f"Expected 29 conflicts for 44-byte struct on 33 banks, got {conflicts}"

    def test_52byte_no_conflicts_both_archs(self):
        """52-byte struct: stride 13, coprime to both 32 and 33."""
        from simulator.shared_memory import SharedMemorySimulator

        for num_banks in [32, 33]:
            sim = SharedMemorySimulator(num_banks=num_banks, bank_width_bytes=4)
            struct_size = 52
            for field_offset in [0, 8, 16, 24, 32]:
                addresses = [i * struct_size + field_offset for i in range(32)]
                conflicts = sim.count_conflicts(addresses)
                assert conflicts == 0, \
                    f"52-byte struct offset {field_offset} on {num_banks} banks: " \
                    f"expected 0 conflicts, got {conflicts}"


# --- Design report tests ---


class TestDesignReport:

    def _load_report(self):
        with open('/app/output/design_report.json', 'r') as f:
            return json.load(f)

    def test_report_exists(self):
        assert os.path.exists('/app/output/design_report.json'), \
            "design_report.json not found"

    def test_required_keys(self):
        data = self._load_report()
        assert 'layouts_evaluated' in data, "Missing 'layouts_evaluated' key"
        assert 'cross_arch_optimal' in data, "Missing 'cross_arch_optimal' key"
        assert 'ranking' in data, "Missing 'ranking' key"

    def test_minimum_layouts_evaluated(self):
        data = self._load_report()
        assert len(data['layouts_evaluated']) >= 6, \
            f"Expected >= 6 layouts, got {len(data['layouts_evaluated'])}"

    def test_layout_entry_structure(self):
        data = self._load_report()
        required_keys = {'name', 'padding_bytes', 'total_struct_size',
                         'conflicts_by_arch', 'memory_overhead_percent'}
        for i, layout in enumerate(data['layouts_evaluated']):
            missing = required_keys - set(layout.keys())
            assert not missing, \
                f"Layout {i} missing keys: {missing}"

    def test_conflicts_both_architectures(self):
        data = self._load_report()
        arch_names = {'gpu_ampere', 'accel_custom'}
        for i, layout in enumerate(data['layouts_evaluated']):
            actual_archs = set(layout['conflicts_by_arch'].keys())
            assert actual_archs == arch_names, \
                f"Layout {i}: expected archs {arch_names}, got {actual_archs}"

    def test_includes_soa_variant(self):
        data = self._load_report()
        has_soa = any(
            'soa' in str(l.get('name', '')).lower()
            for l in data['layouts_evaluated']
        )
        assert has_soa, "Must include at least one SoA layout variant"

    def test_cross_arch_optimal_padding(self):
        data = self._load_report()
        opt = data['cross_arch_optimal']
        assert opt['padding_bytes'] == 12, \
            f"Expected optimal padding 12, got {opt['padding_bytes']}"
        assert opt['padded_struct_size'] == 52, \
            f"Expected optimal struct size 52, got {opt['padded_struct_size']}"

    def test_cross_arch_optimal_conflict_free(self):
        data = self._load_report()
        opt = data['cross_arch_optimal']
        for arch_name, conflicts in opt['conflicts_by_arch'].items():
            assert conflicts == 0, \
                f"Optimal layout has {conflicts} conflicts on {arch_name}"

    def test_cross_arch_optimal_overhead(self):
        data = self._load_report()
        overhead = data['cross_arch_optimal']['memory_overhead_percent']
        assert abs(overhead - 30.0) < 0.1, \
            f"Expected ~30% overhead, got {overhead}"

    def test_cross_arch_optimal_justification(self):
        data = self._load_report()
        just = data['cross_arch_optimal'].get('justification', '')
        assert len(just) >= 50, \
            f"Justification must explain reasoning (got {len(just)} chars)"

    def test_naive_solution_evaluated(self):
        """Report must include 4-byte padding and show it fails on 33-bank arch."""
        data = self._load_report()
        found = False
        for layout in data['layouts_evaluated']:
            if layout['padding_bytes'] == 4 and layout['total_struct_size'] == 44:
                accel_conflicts = layout['conflicts_by_arch'].get('accel_custom', 0)
                assert accel_conflicts > 0, \
                    "S=44 must show non-zero conflicts on accel_custom architecture"
                found = True
                break
        assert found, "Report must include evaluation of 4-byte padding (S=44)"

    def test_ranking_length(self):
        data = self._load_report()
        assert len(data['ranking']) >= 6, \
            f"Ranking must have >= 6 entries, got {len(data['ranking'])}"

    def test_ranking_first_is_conflict_free(self):
        """First-ranked layout should have minimal total conflicts."""
        data = self._load_report()
        first_name = data['ranking'][0]
        first_layout = next(
            (l for l in data['layouts_evaluated'] if l['name'] == first_name),
            None
        )
        assert first_layout is not None, \
            f"First-ranked layout '{first_name}' not found in layouts_evaluated"
        total = sum(first_layout['conflicts_by_arch'].values())
        assert total == 0, \
            f"First-ranked layout should have 0 total conflicts, got {total}"
