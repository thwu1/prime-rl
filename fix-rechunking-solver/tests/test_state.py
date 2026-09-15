"""
Tests for the rechunking evaluation system.

Verifies correctness of individual algorithmic components in rechunker.py,
cost_model.py, and zarr_inspector.py, integration through the full pipeline,
and the generated evaluation_report.json output.

"""

import json
import sys
from math import prod

import pytest

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# rechunker.py unit tests
# ---------------------------------------------------------------------------

class TestSharedChunks:
    """Shared (intermediate) chunks must be compatible with both layouts."""

    def test_basic_2d(self):
        from rechunker import _calculate_shared_chunks
        assert _calculate_shared_chunks((20, 5), (4, 25)) == (4, 5)

    def test_symmetric_swap(self):
        from rechunker import _calculate_shared_chunks
        assert _calculate_shared_chunks((100, 1), (1, 100)) == (1, 1)

    def test_identical(self):
        from rechunker import _calculate_shared_chunks
        assert _calculate_shared_chunks((50, 50, 50), (50, 50, 50)) == (50, 50, 50)

    def test_one_larger(self):
        from rechunker import _calculate_shared_chunks
        assert _calculate_shared_chunks((10, 200), (100, 20)) == (10, 20)


class TestCountIntermediateChunks:
    """LCM-based intermediate chunk counting."""

    def test_coprime_chunks(self):
        from rechunker import _count_intermediate_chunks
        assert _count_intermediate_chunks(5, 7, 20) == 6

    def test_divisible_chunks(self):
        from rechunker import _count_intermediate_chunks
        assert _count_intermediate_chunks(4, 6, 24) == 8

    def test_same_chunks(self):
        from rechunker import _count_intermediate_chunks
        assert _count_intermediate_chunks(10, 10, 100) == 10

    def test_one_to_many(self):
        from rechunker import _count_intermediate_chunks
        assert _count_intermediate_chunks(1, 50, 200) == 200

    def test_large_target(self):
        from rechunker import _count_intermediate_chunks
        assert _count_intermediate_chunks(100, 20, 100) == 5


class TestStageChunks:
    """Multi-stage intermediate chunks must use appropriate spacing."""

    def test_two_stages(self):
        from rechunker import calculate_stage_chunks
        result = calculate_stage_chunks((1000000, 1), (1, 1000000), 2)
        assert result == [(1000, 1000)]

    def test_three_stages(self):
        from rechunker import calculate_stage_chunks
        result = calculate_stage_chunks((1000000, 1), (1, 1000000), 3)
        assert result == [(10000, 100), (100, 10000)]

    def test_single_stage_empty(self):
        from rechunker import calculate_stage_chunks
        result = calculate_stage_chunks((100,), (50,), 1)
        assert result == []


class TestConsolidateChunks:
    """Memory-aware chunk consolidation."""

    def test_headroom_truncation(self):
        from rechunker import consolidate_chunks
        result = consolidate_chunks((100, 100), (10, 7), 8, 3000)
        assert result == (10, 35)

    def test_simple_2d(self):
        from rechunker import consolidate_chunks
        result = consolidate_chunks((100, 200), (10, 20), 8, 32000)
        assert result == (20, 200)

    def test_with_none_limits(self):
        from rechunker import consolidate_chunks
        result = consolidate_chunks((500, 500), (500, 5), 8, 40000, [None, 500])
        assert result == (500, 10)

    def test_never_exceeds_memory(self):
        from rechunker import consolidate_chunks
        max_mem = 3000
        result = consolidate_chunks((100, 100), (10, 7), 8, max_mem)
        assert 8 * prod(result) <= max_mem


# ---------------------------------------------------------------------------
# cost_model.py unit tests
# ---------------------------------------------------------------------------

class TestPlanIOOps:
    """Total I/O operations across plan stages."""

    def test_single_stage_2d(self):
        from cost_model import calculate_plan_io_ops
        plan = [((100, 40), (20, 40), (20, 200))]
        assert calculate_plan_io_ops(plan, (100, 200)) == 25

    def test_identity_1d(self):
        from cost_model import calculate_plan_io_ops
        plan = [((400,), (400,), (400,))]
        assert calculate_plan_io_ops(plan, (10000,)) == 25

    def test_spectral_plan(self):
        from cost_model import calculate_plan_io_ops
        plan = [((500, 10), (10, 10), (10, 500))]
        assert calculate_plan_io_ops(plan, (500, 500)) == 2500

    def test_multi_stage_sum(self):
        from cost_model import calculate_plan_io_ops
        plan_a = [((400,), (400,), (400,))]
        plan_b = [((400,), (400,), (400,)), ((400,), (400,), (400,))]
        ops_a = calculate_plan_io_ops(plan_a, (10000,))
        ops_b = calculate_plan_io_ops(plan_b, (10000,))
        assert ops_b == 2 * ops_a


class TestMemoryUtilization:
    """Memory utilization ratio computation."""

    def test_single_stage(self):
        from cost_model import calculate_memory_utilization
        plan = [((100, 40), (20, 40), (20, 200))]
        result = calculate_memory_utilization(plan, 8, 32000)
        assert result == pytest.approx(0.2)

    def test_full_utilization(self):
        from cost_model import calculate_memory_utilization
        plan = [((100,), (100,), (100,))]
        result = calculate_memory_utilization(plan, 8, 800)
        assert result == pytest.approx(1.0)

    def test_result_in_unit_range(self):
        from cost_model import calculate_memory_utilization
        plan = [((500, 10), (10, 10), (10, 500))]
        result = calculate_memory_utilization(plan, 8, 40000)
        assert 0.0 < result <= 1.0


class TestPlanCost:
    """Weighted cost score computation."""

    def test_known_values(self):
        from cost_model import calculate_plan_cost
        result = calculate_plan_cost(100, 0.5, 10000)
        assert result == pytest.approx(0.157)

    def test_perfect_utilization_zero_io(self):
        from cost_model import calculate_plan_cost
        result = calculate_plan_cost(0, 1.0, 1000)
        assert result == pytest.approx(0.0)

    def test_worst_case(self):
        from cost_model import calculate_plan_cost
        result = calculate_plan_cost(1000, 0.0, 1000)
        assert result == pytest.approx(1.0)

    def test_lower_is_better(self):
        from cost_model import calculate_plan_cost
        cost_good = calculate_plan_cost(10, 0.8, 10000)
        cost_bad = calculate_plan_cost(1000, 0.1, 10000)
        assert cost_good < cost_bad


# ---------------------------------------------------------------------------
# Integration tests for rechunking_plan
# ---------------------------------------------------------------------------

class TestFullPlan:
    """Integration tests for the full rechunking_plan pipeline."""

    def test_grid_2d_plan(self):
        from rechunker import rechunking_plan
        read, inter, write = rechunking_plan(
            shape=(100, 200), source_chunks=(100, 10),
            target_chunks=(10, 200), itemsize=8, max_mem=32000,
        )
        assert read == (100, 40)
        assert inter == (20, 40)
        assert write == (20, 200)

    def test_spectral_intermediate(self):
        from rechunker import rechunking_plan
        read, inter, write = rechunking_plan(
            shape=(500, 500), source_chunks=(500, 5),
            target_chunks=(5, 500), itemsize=8, max_mem=40000,
        )
        assert inter == (10, 10)

    def test_pressure_1d_consolidation(self):
        from rechunker import rechunking_plan
        read, inter, write = rechunking_plan(
            shape=(10000,), source_chunks=(50,),
            target_chunks=(200,), itemsize=4, max_mem=2000,
        )
        assert read == (400,)
        assert inter == (400,)
        assert write == (400,)

    def test_plan_respects_memory(self):
        from rechunker import rechunking_plan
        max_mem = 32000
        read, inter, write = rechunking_plan(
            shape=(100, 200), source_chunks=(100, 10),
            target_chunks=(10, 200), itemsize=8, max_mem=max_mem,
        )
        assert 8 * prod(read) <= max_mem
        assert 8 * prod(write) <= max_mem

    def test_intermediate_fits_both_layouts(self):
        from rechunker import rechunking_plan
        read, inter, write = rechunking_plan(
            shape=(100, 200), source_chunks=(100, 10),
            target_chunks=(10, 200), itemsize=8, max_mem=32000,
        )
        for ic, rc in zip(inter, read):
            assert ic <= rc, f"Intermediate chunk {ic} exceeds read chunk {rc}"
        for ic, wc in zip(inter, write):
            assert ic <= wc, f"Intermediate chunk {ic} exceeds write chunk {wc}"


# ---------------------------------------------------------------------------
# Strategy optimization tests
# ---------------------------------------------------------------------------

class TestFindOptimalStageCount:
    """Tests for the strategy optimizer."""

    def test_pressure_1d_optimal_is_single_stage(self):
        from cost_model import find_optimal_stage_count
        stages, plan, cost = find_optimal_stage_count(
            shape=(10000,), source_chunks=(50,),
            target_chunks=(200,), itemsize=4, max_mem=2000,
        )
        assert stages == 1

    def test_spectral_benefits_from_multistage(self):
        from cost_model import find_optimal_stage_count
        stages, plan, cost = find_optimal_stage_count(
            shape=(500, 500), source_chunks=(500, 5),
            target_chunks=(5, 500), itemsize=8, max_mem=40000,
        )
        assert stages > 1

    def test_optimal_cost_not_worse_than_single(self):
        from cost_model import (
            calculate_plan_io_ops, calculate_memory_utilization,
            calculate_plan_cost, find_optimal_stage_count,
        )
        from rechunker import rechunking_plan
        shape = (100, 200)
        plan_single = rechunking_plan(
            shape=shape, source_chunks=(100, 10),
            target_chunks=(10, 200), itemsize=8, max_mem=32000,
        )
        io = calculate_plan_io_ops([plan_single], shape)
        util = calculate_memory_utilization([plan_single], 8, 32000)
        single_cost = calculate_plan_cost(io, util, prod(shape))

        _, _, opt_cost = find_optimal_stage_count(
            shape=shape, source_chunks=(100, 10),
            target_chunks=(10, 200), itemsize=8, max_mem=32000,
        )
        assert opt_cost <= single_cost + 1e-9

    def test_returns_valid_plan(self):
        from cost_model import find_optimal_stage_count
        stages, plan, cost = find_optimal_stage_count(
            shape=(500, 500), source_chunks=(500, 5),
            target_chunks=(5, 500), itemsize=8, max_mem=40000,
        )
        assert stages >= 1
        assert len(plan) == stages
        assert cost > 0
        for pre, inter, post in plan:
            assert all(c > 0 for c in pre)
            assert all(c > 0 for c in inter)
            assert all(c > 0 for c in post)


# ---------------------------------------------------------------------------
# Zarr inspection tests
# ---------------------------------------------------------------------------

class TestZarrInspection:
    """Tests for Zarr store metadata extraction."""

    def test_grid_2d_metadata(self):
        from zarr_inspector import extract_store_metadata
        meta = extract_store_metadata('/app/zarr_stores/grid_2d')
        assert meta['shape'] == [100, 200]
        assert meta['source_chunks'] == [100, 10]
        assert meta['itemsize'] == 8

    def test_spectral_metadata(self):
        from zarr_inspector import extract_store_metadata
        meta = extract_store_metadata('/app/zarr_stores/spectral')
        assert meta['shape'] == [500, 500]
        assert meta['source_chunks'] == [500, 5]
        assert meta['itemsize'] == 8

    def test_climate_3d_metadata(self):
        from zarr_inspector import extract_store_metadata
        meta = extract_store_metadata('/app/zarr_stores/climate_3d')
        assert meta['shape'] == [365, 180, 360]
        assert meta['source_chunks'] == [1, 180, 360]
        assert meta['itemsize'] == 4

    def test_pressure_1d_metadata(self):
        from zarr_inspector import extract_store_metadata
        meta = extract_store_metadata('/app/zarr_stores/pressure_1d')
        assert meta['shape'] == [10000]
        assert meta['source_chunks'] == [50]
        assert meta['itemsize'] == 4

    def test_all_stores_found(self):
        from zarr_inspector import extract_all_metadata
        meta = extract_all_metadata('/app/zarr_stores')
        assert len(meta) == 5
        assert set(meta.keys()) == {
            'grid_2d', 'spectral', 'climate_3d',
            'pressure_1d', 'velocity_2d',
        }


# ---------------------------------------------------------------------------
# Access cost tests
# ---------------------------------------------------------------------------

class TestAccessCost:
    """Tests for access cost computation."""

    def test_exact_fit(self):
        from zarr_inspector import compute_access_cost
        assert compute_access_cost([100], [1000], [1.0]) == 10

    def test_partial_chunk_needs_full_read(self):
        from zarr_inspector import compute_access_cost
        assert compute_access_cost([100], [1000], [0.15]) == 2

    def test_2d_partial_chunks(self):
        from zarr_inspector import compute_access_cost
        assert compute_access_cost([70, 70], [500, 500], [0.15, 0.15]) == 4

    def test_subchunk_access_reads_one(self):
        from zarr_inspector import compute_access_cost
        assert compute_access_cost([400], [10000], [0.01]) == 1

    def test_climate_spatial_slice_source(self):
        from zarr_inspector import compute_access_cost
        assert compute_access_cost(
            [1, 180, 360], [365, 180, 360], [0.003, 1.0, 1.0]
        ) == 2

    def test_climate_spatial_slice_target(self):
        from zarr_inspector import compute_access_cost
        assert compute_access_cost(
            [365, 10, 70], [365, 180, 360], [0.003, 1.0, 1.0]
        ) == 108


# ---------------------------------------------------------------------------
# Alignment score tests
# ---------------------------------------------------------------------------

class TestAlignmentScore:
    """Tests for chunk alignment score computation."""

    def test_perfect_alignment(self):
        from zarr_inspector import compute_chunk_alignment_score
        result = compute_chunk_alignment_score([100], [100], [1.0])
        assert result == pytest.approx(1.0)

    def test_poor_alignment(self):
        from zarr_inspector import compute_chunk_alignment_score
        result = compute_chunk_alignment_score([10], [500], [1.0])
        assert result == pytest.approx(0.02)

    def test_weighted_2d(self):
        from zarr_inspector import compute_chunk_alignment_score
        result = compute_chunk_alignment_score(
            [20, 200], [100, 200], [0.01, 1.0]
        )
        assert result == pytest.approx(1.002 / 1.01, rel=1e-4)

    def test_result_in_unit_range(self):
        from zarr_inspector import compute_chunk_alignment_score
        result = compute_chunk_alignment_score(
            [10, 500], [500, 500], [0.002, 1.0]
        )
        assert 0.0 <= result <= 1.0

    def test_low_alignment(self):
        from zarr_inspector import compute_chunk_alignment_score
        result = compute_chunk_alignment_score(
            [10, 500], [500, 500], [1.0, 0.002]
        )
        assert result == pytest.approx(0.022 / 1.002, rel=1e-4)


# ---------------------------------------------------------------------------
# Evaluation report tests
# ---------------------------------------------------------------------------

class TestReportExistence:
    """Tests for the generated /app/evaluation_report.json."""

    def test_file_exists_and_valid(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        assert 'arrays' in data

    def test_array_count(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        assert len(data['arrays']) == 5


class TestReportStructure:
    """Report structure and required fields."""

    def test_plan_fields(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        required_keys = {
            'name', 'shape', 'source_chunks', 'read_chunks',
            'int_chunks', 'write_chunks', 'io_ops', 'mem_utilization',
            'cost', 'optimal_stages', 'optimal_cost',
            'access_pattern_analysis',
        }
        for arr in data['arrays']:
            assert required_keys.issubset(arr.keys()), \
                f"Missing keys in {arr.get('name')}"

    def test_access_pattern_fields(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        ap_keys = {'source_cost', 'target_cost', 'alignment_score',
                    'improvement_ratio'}
        for arr in data['arrays']:
            for pattern_name, ap in arr['access_pattern_analysis'].items():
                assert ap_keys.issubset(ap.keys()), \
                    f"Missing AP keys for {arr['name']}/{pattern_name}"


class TestReportPlanValues:
    """Specific rechunking plan values in the report."""

    def test_grid_2d_values(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        g = arrays['grid_2d']
        assert g['source_chunks'] == [100, 10]
        assert g['read_chunks'] == [100, 40]
        assert g['int_chunks'] == [20, 40]
        assert g['write_chunks'] == [20, 200]
        assert g['io_ops'] == 25

    def test_spectral_values(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        s = arrays['spectral']
        assert s['source_chunks'] == [500, 5]
        assert s['read_chunks'] == [500, 10]
        assert s['int_chunks'] == [10, 10]
        assert s['write_chunks'] == [10, 500]
        assert s['io_ops'] == 2500

    def test_climate_3d_values(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        c = arrays['climate_3d']
        assert c['source_chunks'] == [1, 180, 360]
        assert c['read_chunks'] == [4, 180, 360]
        assert c['int_chunks'] == [4, 10, 70]
        assert c['write_chunks'] == [365, 10, 70]
        assert c['io_ops'] == 9936

    def test_pressure_1d_values(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        p = arrays['pressure_1d']
        assert p['source_chunks'] == [50]
        assert p['read_chunks'] == [400]
        assert p['write_chunks'] == [400]
        assert p['io_ops'] == 25


class TestReportConstraints:
    """Structural invariants for all plans in the report."""

    def test_memory_constraints_satisfied(self):
        with open('/app/evaluation_report.json') as f:
            report = json.load(f)
        with open('/app/arrays.json') as f:
            config = json.load(f)

        cfg_by_name = {a['name']: a for a in config['arrays']}
        for arr in report['arrays']:
            from zarr_inspector import extract_store_metadata
            meta = extract_store_metadata(
                f"/app/zarr_stores/{arr['name']}"
            )
            itemsize = meta['itemsize']
            max_mem = cfg_by_name[arr['name']]['max_mem']
            read_mem = itemsize * prod(arr['read_chunks'])
            write_mem = itemsize * prod(arr['write_chunks'])
            assert read_mem <= max_mem, \
                f"Read chunks exceed max_mem for {arr['name']}"
            assert write_mem <= max_mem, \
                f"Write chunks exceed max_mem for {arr['name']}"

    def test_intermediate_within_both_layouts(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        for arr in data['arrays']:
            for ic, rc in zip(arr['int_chunks'], arr['read_chunks']):
                assert ic <= rc, \
                    f"Int {ic} > read {rc} for {arr['name']}"
            for ic, wc in zip(arr['int_chunks'], arr['write_chunks']):
                assert ic <= wc, \
                    f"Int {ic} > write {wc} for {arr['name']}"

    def test_mem_utilization_in_range(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        for arr in data['arrays']:
            assert 0.0 < arr['mem_utilization'] <= 1.0, \
                f"Utilization out of range for {arr['name']}"

    def test_cost_is_positive(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        for arr in data['arrays']:
            assert arr['cost'] > 0

    def test_optimal_not_worse_than_single_stage(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        for arr in data['arrays']:
            assert arr['optimal_cost'] <= arr['cost'] + 1e-6, \
                f"Optimal cost worse than single-stage for {arr['name']}"
            assert arr['optimal_stages'] >= 1


class TestReportOptimalStrategies:
    """Optimal strategy selection tests."""

    def test_spectral_multistage_optimal(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        assert arrays['spectral']['optimal_stages'] > 1

    def test_pressure_1d_single_stage_optimal(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        assert arrays['pressure_1d']['optimal_stages'] == 1


class TestReportAccessPatterns:
    """Access pattern analysis values in the report."""

    def test_grid_2d_row_extract(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        ap = arrays['grid_2d']['access_pattern_analysis']['row_extract']
        assert ap['source_cost'] == 20
        assert ap['target_cost'] == 1
        assert ap['improvement_ratio'] == pytest.approx(20.0)
        assert ap['alignment_score'] == pytest.approx(
            1.002 / 1.01, abs=1e-4
        )

    def test_grid_2d_column_extract(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        ap = arrays['grid_2d']['access_pattern_analysis']['column_extract']
        assert ap['source_cost'] == 1
        assert ap['target_cost'] == 5
        assert ap['improvement_ratio'] == pytest.approx(0.2)

    def test_spectral_mode_access(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        ap = arrays['spectral']['access_pattern_analysis']['mode_access']
        assert ap['source_cost'] == 100
        assert ap['target_cost'] == 1
        assert ap['improvement_ratio'] == pytest.approx(100.0)

    def test_spectral_freq_scan(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        ap = arrays['spectral']['access_pattern_analysis']['freq_scan']
        assert ap['source_cost'] == 1
        assert ap['target_cost'] == 50
        assert ap['improvement_ratio'] == pytest.approx(0.02)

    def test_climate_time_series(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        ap = arrays['climate_3d']['access_pattern_analysis']['time_series']
        assert ap['source_cost'] == 365
        assert ap['target_cost'] == 1
        assert ap['improvement_ratio'] == pytest.approx(365.0)

    def test_climate_spatial_slice(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        ap = arrays['climate_3d']['access_pattern_analysis']['spatial_slice']
        assert ap['source_cost'] == 2
        assert ap['target_cost'] == 108
        assert ap['improvement_ratio'] == pytest.approx(2.0 / 108, abs=1e-3)

    def test_pressure_full_read(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        ap = arrays['pressure_1d']['access_pattern_analysis']['full_read']
        assert ap['source_cost'] == 200
        assert ap['target_cost'] == 25
        assert ap['improvement_ratio'] == pytest.approx(8.0)

    def test_velocity_tile_access(self):
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        arrays = {a['name']: a for a in data['arrays']}
        ap = arrays['velocity_2d']['access_pattern_analysis']['tile_access']
        assert ap['source_cost'] == 1
        assert ap['target_cost'] == 1
        assert ap['improvement_ratio'] == pytest.approx(1.0)
        assert ap['alignment_score'] == pytest.approx(0.6, abs=1e-4)

    def test_alignment_scores_bounded(self):
        """All alignment scores must be in [0, 1]."""
        with open('/app/evaluation_report.json') as f:
            data = json.load(f)
        for arr in data['arrays']:
            for pname, ap in arr['access_pattern_analysis'].items():
                assert 0.0 <= ap['alignment_score'] <= 1.0, \
                    f"Alignment out of range for {arr['name']}/{pname}"
