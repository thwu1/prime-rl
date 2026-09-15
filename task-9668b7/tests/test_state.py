"""
Tests for HLS Design Space Exploration Analyzer.

Verifies shared library integration, configuration expansion, Pareto analysis,
hypervolume computation, exclusive contributions, greedy reduction, and the
full CLI pipeline.
"""


import pytest
import sys
import os
import json
import subprocess
import ctypes

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# Shared Library Integration Tests
# ---------------------------------------------------------------------------

class TestSharedLibraryIntegration:
    def test_library_file_exists(self):
        """The compiled shared library must be present."""
        assert os.path.exists('/app/libhls_cost.so'), "libhls_cost.so not found"

    def test_header_file_exists(self):
        """The C header must be present for reference."""
        assert os.path.exists('/app/hls_cost.h'), "hls_cost.h not found"

    def test_no_python_cost_model(self):
        """No Python cost model file should exist — the C library must be used."""
        assert not os.path.exists('/app/cost_model.py'), \
            "cost_model.py must not exist; use the C shared library instead"

    def test_analyzer_uses_ctypes(self):
        """The analyzer module must use ctypes to call the shared library."""
        import inspect
        import dse_analyzer
        source = inspect.getsource(dse_analyzer)
        assert 'ctypes' in source, \
            "dse_analyzer.py must use ctypes to interface with the C library"
        assert 'libhls_cost' in source, \
            "dse_analyzer.py must load libhls_cost.so"

    def test_library_loadable_and_callable(self):
        """The shared library must expose hls_evaluate and hls_evaluate_batch."""
        lib = ctypes.CDLL('/app/libhls_cost.so')
        assert hasattr(lib, 'hls_evaluate')
        assert hasattr(lib, 'hls_evaluate_batch')


# ---------------------------------------------------------------------------
# Configuration Expansion Tests
# ---------------------------------------------------------------------------

class TestConfigExpansion:
    def test_expand_config_count(self):
        """Constraint-aware expansion must produce exactly 2592 configurations."""
        import yaml
        from dse_analyzer import expand_configurations

        with open('/app/dse_config.yaml', 'r') as f:
            config = yaml.safe_load(f)

        configs = expand_configurations(config)
        assert len(configs) == 2592, f"Expected 2592 configs, got {len(configs)}"

    def test_expand_config_constraint_enforcement(self):
        """When enable_pipeline is false, pipeline_ii must equal the default (1)."""
        import yaml
        from dse_analyzer import expand_configurations

        with open('/app/dse_config.yaml', 'r') as f:
            config = yaml.safe_load(f)

        configs = expand_configurations(config)

        for c in configs:
            if not c['enable_pipeline']:
                assert c['pipeline_ii'] == 1, (
                    f"pipeline_ii should be 1 when pipeline disabled, got {c['pipeline_ii']}"
                )

    def test_expand_config_active_constraint(self):
        """When enable_pipeline is true, pipeline_ii must appear with both values."""
        import yaml
        from dse_analyzer import expand_configurations

        with open('/app/dse_config.yaml', 'r') as f:
            config = yaml.safe_load(f)

        configs = expand_configurations(config)
        pipeline_on = [c for c in configs if c['enable_pipeline']]

        ii_values = set(c['pipeline_ii'] for c in pipeline_on)
        assert ii_values == {1, 2}, f"Expected pipeline_ii {{1, 2}}, got {ii_values}"


# ---------------------------------------------------------------------------
# Cost Model Evaluation Test
# ---------------------------------------------------------------------------

class TestEvaluation:
    def test_evaluate_baseline_config(self):
        """Evaluation via the C library must produce correct metrics for baseline."""
        from dse_analyzer import evaluate_all

        configs = [{
            'clock_period_ns': 5.0,
            'enable_pipeline': False,
            'pipeline_ii': 1,
            'enable_dataflow': False,
            'unroll_factor': 1,
            'array_partition_factor': 1,
            'allocation_limit_add': 0,
            'dsp_full_reg': False,
            'vivado_strategy': 'Default'
        }]

        results = evaluate_all(configs)
        assert len(results) == 1
        m = results[0]['metrics']

        assert m['area_luts'] == pytest.approx(500.0, abs=0.01)
        assert m['latency_ns'] == pytest.approx(5000.0, abs=0.01)
        assert m['power_mw'] == pytest.approx(10.0, abs=0.01)

    def test_evaluate_complex_config(self):
        """Evaluation with multiple active directives must produce expected metrics."""
        from dse_analyzer import evaluate_all

        configs = [{
            'clock_period_ns': 3.3,
            'enable_pipeline': True,
            'pipeline_ii': 2,
            'enable_dataflow': True,
            'unroll_factor': 4,
            'array_partition_factor': 2,
            'allocation_limit_add': 1,
            'dsp_full_reg': True,
            'vivado_strategy': 'Performance_Explore'
        }]

        results = evaluate_all(configs)
        assert len(results) == 1
        m = results[0]['metrics']

        assert m['area_luts'] == pytest.approx(4238.52, abs=0.1)
        assert m['latency_ns'] > 0
        assert m['power_mw'] > 0


# ---------------------------------------------------------------------------
# Pareto Front Tests
# ---------------------------------------------------------------------------

class TestParetoFront:
    def test_pareto_front_with_dominated(self):
        """Test Pareto front extraction with known dominated points."""
        from dse_analyzer import pareto_front

        points = [
            {'x': 1, 'y': 4, 'z': 6},   # 0: non-dominated
            {'x': 2, 'y': 2, 'z': 5},   # 1: non-dominated
            {'x': 4, 'y': 1, 'z': 4},   # 2: non-dominated
            {'x': 3, 'y': 3, 'z': 3},   # 3: non-dominated
            {'x': 2, 'y': 3, 'z': 7},   # 4: dominated by point 1
            {'x': 5, 'y': 5, 'z': 8},   # 5: dominated by point 3
        ]

        front = pareto_front(points, ['x', 'y', 'z'])
        assert sorted(front) == [0, 1, 2, 3]

    def test_pareto_front_all_non_dominated(self):
        """When all points trade off, all should be on the front."""
        from dse_analyzer import pareto_front

        points = [
            {'a': 1, 'b': 3},
            {'a': 2, 'b': 2},
            {'a': 3, 'b': 1},
        ]

        front = pareto_front(points, ['a', 'b'])
        assert sorted(front) == [0, 1, 2]

    def test_pareto_front_single_point(self):
        """A single point is always on the Pareto front."""
        from dse_analyzer import pareto_front

        points = [{'x': 5, 'y': 5, 'z': 5}]
        front = pareto_front(points, ['x', 'y', 'z'])
        assert front == [0]


# ---------------------------------------------------------------------------
# Non-dominated Sorting Tests
# ---------------------------------------------------------------------------

class TestNonDominatedSort:
    def test_multi_rank_sorting(self):
        """Test non-dominated sorting assigns correct ranks across 4 fronts."""
        from dse_analyzer import non_dominated_sort

        points = [
            {'x': 1, 'y': 3},   # 0: rank 1
            {'x': 3, 'y': 1},   # 1: rank 1
            {'x': 2, 'y': 2},   # 2: rank 1
            {'x': 2, 'y': 3},   # 3: rank 2 (dominated by 0)
            {'x': 3, 'y': 3},   # 4: rank 3
            {'x': 4, 'y': 4},   # 5: rank 4
        ]

        ranks = non_dominated_sort(points, ['x', 'y'])
        assert ranks[0] == 1
        assert ranks[1] == 1
        assert ranks[2] == 1
        assert ranks[3] == 2
        assert ranks[4] == 3
        assert ranks[5] == 4


# ---------------------------------------------------------------------------
# Hypervolume Tests
# ---------------------------------------------------------------------------

class TestHypervolume:
    def test_hypervolume_3d_symmetric(self):
        """Symmetric 3-point case. Analytically verified: HV = 19."""
        from dse_analyzer import hypervolume_3d

        points = [(1, 1, 3), (1, 3, 1), (3, 1, 1)]
        ref = (4, 4, 4)

        hv = hypervolume_3d(points, ref)
        assert hv == pytest.approx(19.0, abs=1e-6)

    def test_hypervolume_3d_asymmetric(self):
        """Asymmetric 3-point case. Analytically verified: HV = 55."""
        from dse_analyzer import hypervolume_3d

        points = [(1, 3, 5), (2, 1, 4), (5, 2, 1)]
        ref = (6, 6, 6)

        hv = hypervolume_3d(points, ref)
        assert hv == pytest.approx(55.0, abs=1e-6)

    def test_hypervolume_single_point(self):
        """Single point: HV is the box volume to the reference."""
        from dse_analyzer import hypervolume_3d

        points = [(2, 3, 4)]
        ref = (5, 5, 5)

        hv = hypervolume_3d(points, ref)
        expected = (5 - 2) * (5 - 3) * (5 - 4)  # 6.0
        assert hv == pytest.approx(expected, abs=1e-6)

    def test_hypervolume_point_beyond_ref(self):
        """Points outside the reference box contribute zero volume."""
        from dse_analyzer import hypervolume_3d

        points = [(10, 10, 10)]
        ref = (5, 5, 5)

        hv = hypervolume_3d(points, ref)
        assert hv == pytest.approx(0.0, abs=1e-6)

    def test_hypervolume_collinear_z(self):
        """Two points sharing the same z-value (tests degenerate slab handling)."""
        from dse_analyzer import hypervolume_3d

        points = [(1, 3, 2), (3, 1, 2)]
        ref = (5, 5, 5)

        hv = hypervolume_3d(points, ref)
        assert hv == pytest.approx(36.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Exclusive Contribution Tests
# ---------------------------------------------------------------------------

class TestExclusiveContributions:
    def test_contributions_asymmetric(self):
        """Exclusive contributions for the asymmetric 3-point case.

        Full HV = 55.
        HV without P1 = 52 -> contrib(P1) = 3
        HV without P2 = 32 -> contrib(P2) = 23
        HV without P3 = 43 -> contrib(P3) = 12
        """
        from dse_analyzer import exclusive_contributions

        points = [(1, 3, 5), (2, 1, 4), (5, 2, 1)]
        ref = (6, 6, 6)

        contribs = exclusive_contributions(points, ref)

        assert contribs[0] == pytest.approx(3.0, abs=1e-6)
        assert contribs[1] == pytest.approx(23.0, abs=1e-6)
        assert contribs[2] == pytest.approx(12.0, abs=1e-6)

    def test_contributions_single_point(self):
        """A single point's contribution equals the total hypervolume."""
        from dse_analyzer import exclusive_contributions

        points = [(2, 3, 4)]
        ref = (5, 5, 5)

        contribs = exclusive_contributions(points, ref)
        expected_hv = (5 - 2) * (5 - 3) * (5 - 4)
        assert contribs[0] == pytest.approx(expected_hv, abs=1e-6)


# ---------------------------------------------------------------------------
# Greedy Reduction Tests
# ---------------------------------------------------------------------------

class TestGreedyReduce:
    def test_reduce_to_2(self):
        """Reducing 3 points to 2 removes the minimum contributor (P1, contrib=3)."""
        from dse_analyzer import greedy_reduce

        points = [(1, 3, 5), (2, 1, 4), (5, 2, 1)]
        ref = (6, 6, 6)

        keep = greedy_reduce(points, ref, 2)
        assert len(keep) == 2
        assert sorted(keep) == [1, 2]

    def test_reduce_noop(self):
        """If max_k >= number of points, return all indices."""
        from dse_analyzer import greedy_reduce

        points = [(1, 1, 1), (2, 2, 2)]
        ref = (5, 5, 5)

        keep = greedy_reduce(points, ref, 5)
        assert sorted(keep) == [0, 1]

    def test_reduce_to_1(self):
        """Reducing to 1 point should keep the one with largest contribution."""
        from dse_analyzer import greedy_reduce

        points = [(1, 3, 5), (2, 1, 4), (5, 2, 1)]
        ref = (6, 6, 6)

        keep = greedy_reduce(points, ref, 1)
        assert len(keep) == 1
        assert keep == [1]


# ---------------------------------------------------------------------------
# Full Pipeline Integration Tests
# ---------------------------------------------------------------------------

class TestFullPipeline:
    @classmethod
    def setup_class(cls):
        """Run the full pipeline once and cache results."""
        result = subprocess.run(
            ['python3', '/app/dse_analyzer.py',
             '--config', '/app/dse_config.yaml',
             '--output', '/tmp/test_full_results.json'],
            capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, f"Pipeline failed: {result.stderr}"

        with open('/tmp/test_full_results.json', 'r') as f:
            cls.data = json.load(f)

    def test_output_has_required_keys(self):
        """Output JSON must contain all required top-level keys."""
        required = ['total_configurations', 'num_pareto_optimal', 'num_ranks',
                     'pareto_front', 'hypervolume', 'reference_point']
        for key in required:
            assert key in self.data, f"Missing key: {key}"

    def test_total_configurations(self):
        """Must report exactly 2592 configurations after constraint pruning."""
        assert self.data['total_configurations'] == 2592

    def test_pareto_front_nonempty(self):
        """Pareto front must have at least one point."""
        assert self.data['num_pareto_optimal'] > 0
        assert len(self.data['pareto_front']) == self.data['num_pareto_optimal']

    def test_pareto_front_entry_structure(self):
        """Each Pareto front entry must have config, metrics, and contribution."""
        for entry in self.data['pareto_front']:
            assert 'config' in entry
            assert 'metrics' in entry
            assert 'contribution' in entry
            for obj in ['area_luts', 'latency_ns', 'power_mw']:
                assert obj in entry['metrics'], f"Missing metric: {obj}"

    def test_multiple_ranks(self):
        """Non-dominated sorting must produce more than one rank."""
        assert self.data['num_ranks'] > 1

    def test_pareto_validity(self):
        """No point on the Pareto front should dominate another."""
        front = self.data['pareto_front']
        objectives = ['area_luts', 'latency_ns', 'power_mw']

        for i, a in enumerate(front):
            for j, b in enumerate(front):
                if i == j:
                    continue
                am, bm = a['metrics'], b['metrics']
                all_leq = all(am[o] <= bm[o] for o in objectives)
                any_lt = any(am[o] < bm[o] for o in objectives)
                assert not (all_leq and any_lt), (
                    f"Point {i} dominates point {j} on the Pareto front"
                )

    def test_hypervolume_positive_and_bounded(self):
        """Hypervolume must be positive and less than the reference box volume."""
        hv = self.data['hypervolume']
        assert hv > 0, "Hypervolume must be positive"

        ref = self.data['reference_point']
        max_vol = ref['area_luts'] * ref['latency_ns'] * ref['power_mw']
        assert hv < max_vol, "Hypervolume exceeds theoretical maximum"

    def test_contributions_sum_consistency(self):
        """Each contribution must be non-negative and <= total hypervolume."""
        hv = self.data['hypervolume']
        for entry in self.data['pareto_front']:
            c = entry['contribution']
            assert c >= -1e-6, f"Negative contribution: {c}"
            assert c <= hv + 1e-6, f"Contribution {c} exceeds total HV {hv}"


class TestGreedyReductionPipeline:
    def test_max_points_produces_reduced_front(self):
        """Running with --max-points 5 must produce a reduced_front of size 5."""
        result = subprocess.run(
            ['python3', '/app/dse_analyzer.py',
             '--config', '/app/dse_config.yaml',
             '--output', '/tmp/test_reduced_results.json',
             '--max-points', '5'],
            capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, f"Pipeline failed: {result.stderr}"

        with open('/tmp/test_reduced_results.json', 'r') as f:
            data = json.load(f)

        assert 'reduced_front' in data, "Missing reduced_front in output"
        assert len(data['reduced_front']) == 5

        # Reduced front points must be a subset of the full front
        full_keys = {json.dumps(p['metrics'], sort_keys=True)
                     for p in data['pareto_front']}
        for p in data['reduced_front']:
            key = json.dumps(p['metrics'], sort_keys=True)
            assert key in full_keys, "Reduced front point not found in full front"
