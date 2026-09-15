"""
"""

import sys
import os
import json
import math
import pytest

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# Test: results.json existence and structure
# ---------------------------------------------------------------------------

class TestResultsJson:

    def test_file_exists(self):
        assert os.path.exists('/app/results.json'), \
            "results.json not found. Run: python3 /app/predict.py"

    def test_valid_json(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_all_workloads_present(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        expected_keys = [
            "(4096,4096,4096)", "(2048,4096,1024)", "(1024,1024,8192)",
            "(768,2048,4096)", "(512,512,512)", "(256,8192,256)",
        ]
        for key in expected_keys:
            assert key in data, f"Missing workload {key}"

    def test_six_configs_per_workload(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for key, configs in data.items():
            assert len(configs) == 6, \
                f"Workload {key}: expected 6 configs, got {len(configs)}"


# ---------------------------------------------------------------------------
# Test: shared memory calculations
# ---------------------------------------------------------------------------

class TestSharedMemory:
    """Verify shared memory values are correct for each config."""

    def _get_configs_by_id(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        configs = data["(4096,4096,4096)"]
        by_id = {c['config_id']: c for c in configs}
        return by_id

    @pytest.mark.parametrize("config_id,expected_smem", [
        (0, 98304), (1, 147456), (2, 262144),
        (3, 196608), (4, 65536), (5, 65536),
    ])
    def test_shared_mem(self, config_id, expected_smem):
        by_id = self._get_configs_by_id()
        assert config_id in by_id, f"config_id {config_id} not found"
        actual = by_id[config_id]['shared_mem_bytes']
        assert actual == expected_smem, \
            f"Config {config_id}: shared_mem expected {expected_smem}, got {actual}"


# ---------------------------------------------------------------------------
# Test: occupancy and validity
# ---------------------------------------------------------------------------

class TestOccupancy:

    EXPECTED = {
        0: (1, True),
        1: (1, True),
        2: (0, False),
        3: (0, False),
        4: (2, True),
        5: (2, True),
    }

    def _get_configs_by_id(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        configs = data["(4096,4096,4096)"]
        return {c['config_id']: c for c in configs}

    @pytest.mark.parametrize("config_id,expected_occ,expected_valid", [
        (0, 1, True), (1, 1, True), (2, 0, False),
        (3, 0, False), (4, 2, True), (5, 2, True),
    ])
    def test_occupancy(self, config_id, expected_occ, expected_valid):
        by_id = self._get_configs_by_id()
        c = by_id[config_id]
        assert c['occupancy'] == expected_occ, \
            f"Config {config_id}: occupancy expected {expected_occ}, got {c['occupancy']}"
        assert c['is_valid'] == expected_valid, \
            f"Config {config_id}: is_valid expected {expected_valid}, got {c['is_valid']}"


# ---------------------------------------------------------------------------
# Test: sort order — configs ranked descending by attainable_tflops
# ---------------------------------------------------------------------------

class TestSortOrder:

    def test_descending_tflops(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for key, configs in data.items():
            tflops = [c['performance']['attainable_tflops'] for c in configs]
            for i in range(len(tflops) - 1):
                assert tflops[i] >= tflops[i + 1], \
                    f"{key}: not sorted descending at index {i}: " \
                    f"{tflops[i]:.4f} < {tflops[i + 1]:.4f}"

    def test_invalid_at_bottom(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for key, configs in data.items():
            saw_invalid = False
            for c in configs:
                if not c['is_valid']:
                    saw_invalid = True
                elif saw_invalid:
                    pytest.fail(
                        f"{key}: valid config (id={c['config_id']}) "
                        f"appears after invalid config")

    def test_best_config_4096(self):
        """For 4096^3, config 5 (64x64 tiles) should rank first."""
        with open('/app/results.json') as f:
            data = json.load(f)
        best = data["(4096,4096,4096)"][0]
        assert best['config_id'] == 5, \
            f"Expected config_id 5 as best for 4096^3, got {best['config_id']}"

    def test_best_config_512(self):
        """For 512^3, config 5 (64x64 tiles) should rank first."""
        with open('/app/results.json') as f:
            data = json.load(f)
        best = data["(512,512,512)"][0]
        assert best['config_id'] == 5, \
            f"Expected config_id 5 as best for 512^3, got {best['config_id']}"


# ---------------------------------------------------------------------------
# Test: performance values — roofline model correctness
# ---------------------------------------------------------------------------

class TestPerformance:

    def _get_perf(self, workload_key, config_id):
        with open('/app/results.json') as f:
            data = json.load(f)
        configs = data[workload_key]
        for c in configs:
            if c['config_id'] == config_id:
                return c
        pytest.fail(f"config_id {config_id} not found in {workload_key}")

    def test_total_flops_4096(self):
        c = self._get_perf("(4096,4096,4096)", 0)
        expected = 2.0 * 4096 ** 3
        assert c['performance']['total_flops'] == expected

    def test_total_bytes_4096(self):
        """total_bytes must account for reads of A, B and write of C."""
        c = self._get_perf("(4096,4096,4096)", 0)
        expected = (4096 * 4096 + 4096 * 4096 + 4096 * 4096) * 2
        assert c['performance']['total_bytes'] == expected, \
            f"total_bytes: expected {expected}, got {c['performance']['total_bytes']}"

    def test_total_bytes_256_8192(self):
        c = self._get_perf("(256,8192,256)", 5)
        M, N, K = 256, 8192, 256
        expected = (M * K + K * N + M * N) * 2
        assert c['performance']['total_bytes'] == expected, \
            f"total_bytes: expected {expected}, got {c['performance']['total_bytes']}"

    def test_arithmetic_intensity_4096(self):
        c = self._get_perf("(4096,4096,4096)", 5)
        expected_ai = (2.0 * 4096 ** 3) / ((3 * 4096 ** 2) * 2)
        actual_ai = c['performance']['arithmetic_intensity']
        assert abs(actual_ai - expected_ai) / expected_ai < 1e-6, \
            f"AI: expected {expected_ai:.4f}, got {actual_ai:.4f}"

    def test_compute_bound_4096(self):
        c = self._get_perf("(4096,4096,4096)", 5)
        assert c['performance']['is_compute_bound'] is True

    def test_memory_bound_256_8192(self):
        """(256,8192,256) with config 5 has AI < ridge point -> memory-bound."""
        c = self._get_perf("(256,8192,256)", 5)
        assert c['performance']['is_compute_bound'] is False, \
            "Expected memory-bound for (256,8192,256) config 5"

    def test_compute_bound_256_8192_config1(self):
        """(256,8192,256) config 1 uses only 64 SMs -> compute-bound despite low AI."""
        c = self._get_perf("(256,8192,256)", 1)
        assert c['performance']['is_compute_bound'] is True

    def test_wave_utilization_bounded(self):
        """Wave utilization must never exceed 1.0."""
        with open('/app/results.json') as f:
            data = json.load(f)
        for key, configs in data.items():
            for c in configs:
                wu = c['performance']['wave_utilization']
                assert wu <= 1.0 + 1e-9, \
                    f"{key} config {c['config_id']}: " \
                    f"wave_utilization={wu:.6f} exceeds 1.0"

    def test_attainable_below_peak(self):
        """Attainable TFLOPS must not exceed peak (312 TFLOPS for A100)."""
        with open('/app/results.json') as f:
            data = json.load(f)
        for key, configs in data.items():
            for c in configs:
                tflops = c['performance']['attainable_tflops']
                assert tflops <= 312.0 + 1e-6, \
                    f"{key} config {c['config_id']}: " \
                    f"attainable_tflops={tflops:.4f} exceeds peak 312.0"

    def test_attainable_tflops_4096_config5(self):
        c = self._get_perf("(4096,4096,4096)", 5)
        expected = 312.0 * 4096 / (math.ceil(4096 / 108) * 108)
        actual = c['performance']['attainable_tflops']
        assert abs(actual - expected) / expected < 0.001, \
            f"attainable_tflops: expected {expected:.4f}, got {actual:.4f}"

    def test_attainable_tflops_4096_config0(self):
        c = self._get_perf("(4096,4096,4096)", 0)
        expected = 312.0 * 1024 / (math.ceil(1024 / 108) * 108)
        actual = c['performance']['attainable_tflops']
        assert abs(actual - expected) / expected < 0.001, \
            f"attainable_tflops: expected {expected:.4f}, got {actual:.4f}"

    def test_attainable_tflops_2048_4096_config1(self):
        c = self._get_perf("(2048,4096,1024)", 1)
        expected = 312.0 * 256 / (math.ceil(256 / 108) * 108)
        actual = c['performance']['attainable_tflops']
        assert abs(actual - expected) / expected < 0.001, \
            f"attainable_tflops: expected {expected:.4f}, got {actual:.4f}"

    def test_invalid_config_zero_tflops(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for key, configs in data.items():
            for c in configs:
                if not c['is_valid']:
                    assert c['performance']['attainable_tflops'] == 0.0, \
                        f"{key} config {c['config_id']}: " \
                        f"invalid config should have 0 TFLOPS"


# ---------------------------------------------------------------------------
# Test: schedule info
# ---------------------------------------------------------------------------

class TestScheduleInfo:

    def _get_config(self, workload_key, config_id):
        with open('/app/results.json') as f:
            data = json.load(f)
        for c in data[workload_key]:
            if c['config_id'] == config_id:
                return c
        pytest.fail(f"config_id {config_id} not found")

    def test_schedule_present_for_valid(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        for key, configs in data.items():
            for c in configs:
                if c['is_valid']:
                    assert c['schedule_info'] is not None, \
                        f"{key} config {c['config_id']}: " \
                        f"schedule_info missing for valid config"

    def test_num_tiles_4096(self):
        c = self._get_config("(4096,4096,4096)", 5)
        s = c['schedule_info']
        assert s['num_pid_m'] == 64
        assert s['num_pid_n'] == 64
        assert s['num_tiles'] == 4096

    def test_active_sms_capped(self):
        c = self._get_config("(512,512,512)", 0)
        s = c['schedule_info']
        assert s['num_tiles'] == 16
        assert s['active_sms'] == 16  # min(108, 16) = 16

    def test_tiles_per_sm_max(self):
        c = self._get_config("(4096,4096,4096)", 5)
        s = c['schedule_info']
        expected_max = math.ceil(4096 / 108)
        assert s['tiles_per_sm_max'] == expected_max

    def test_768_schedule(self):
        """768/128=6 tile rows -- partial group edge case."""
        c = self._get_config("(768,2048,4096)", 0)
        s = c['schedule_info']
        assert s['num_pid_m'] == 6
        assert s['num_pid_n'] == 16
        assert s['num_tiles'] == 96
        assert s['active_sms'] == 96


# ---------------------------------------------------------------------------
# Test: tile scheduler correctness (direct module test)
# ---------------------------------------------------------------------------

class TestTileScheduler:

    def test_first_tile(self):
        from modules.tile_scheduler import compute_tile_position
        assert compute_tile_position(0, 32, 32, 8) == (0, 0)

    def test_within_first_group(self):
        from modules.tile_scheduler import compute_tile_position
        assert compute_tile_position(7, 32, 32, 8) == (7, 0)

    def test_column_wrap(self):
        from modules.tile_scheduler import compute_tile_position
        assert compute_tile_position(8, 32, 32, 8) == (0, 1)

    def test_second_group(self):
        from modules.tile_scheduler import compute_tile_position
        assert compute_tile_position(256, 32, 32, 8) == (8, 0)

    def test_small_grid_partial_group(self):
        """num_pid_m=4 < GROUP_SIZE_M=8: the single group has only 4 rows."""
        from modules.tile_scheduler import compute_tile_position
        assert compute_tile_position(0, 4, 4, 8) == (0, 0)
        assert compute_tile_position(3, 4, 4, 8) == (3, 0)
        assert compute_tile_position(4, 4, 4, 8) == (0, 1)
        assert compute_tile_position(7, 4, 4, 8) == (3, 1)

    def test_768_partial_group(self):
        """num_pid_m=6 < GROUP_SIZE_M=8: group has only 6 rows."""
        from modules.tile_scheduler import compute_tile_position
        pm, pn = compute_tile_position(6, 6, 16, 8)
        assert 0 <= pm < 6, f"pid_m={pm} out of range [0, 6)"
        assert 0 <= pn < 16, f"pid_n={pn} out of range [0, 16)"
        assert (pm, pn) == (0, 1)

    def test_all_positions_in_bounds(self):
        """Every tile position must be within the grid."""
        from modules.tile_scheduler import compute_tile_position
        num_pid_m, num_pid_n = 6, 16
        for tile_id in range(num_pid_m * num_pid_n):
            pm, pn = compute_tile_position(tile_id, num_pid_m, num_pid_n, 8)
            assert 0 <= pm < num_pid_m, \
                f"tile {tile_id}: pid_m={pm} out of [0, {num_pid_m})"
            assert 0 <= pn < num_pid_n, \
                f"tile {tile_id}: pid_n={pn} out of [0, {num_pid_n})"

    def test_bijection(self):
        """Tile position mapping must be a bijection (each position exactly once)."""
        from modules.tile_scheduler import compute_tile_position
        num_pid_m, num_pid_n = 6, 16
        num_tiles = num_pid_m * num_pid_n
        seen = set()
        for tile_id in range(num_tiles):
            pos = compute_tile_position(tile_id, num_pid_m, num_pid_n, 8)
            seen.add(pos)
        assert len(seen) == num_tiles, \
            f"Expected {num_tiles} unique positions, got {len(seen)}"

    def test_bijection_small(self):
        from modules.tile_scheduler import compute_tile_position
        num_pid_m, num_pid_n = 4, 4
        num_tiles = 16
        seen = set()
        for tile_id in range(num_tiles):
            pos = compute_tile_position(tile_id, num_pid_m, num_pid_n, 8)
            assert 0 <= pos[0] < num_pid_m
            assert 0 <= pos[1] < num_pid_n
            seen.add(pos)
        assert len(seen) == num_tiles

    def test_bijection_256_8192(self):
        """num_pid_m=2 with GROUP_SIZE_M=8 -- extreme partial group."""
        from modules.tile_scheduler import compute_tile_position
        num_pid_m, num_pid_n = 2, 64
        num_tiles = num_pid_m * num_pid_n
        seen = set()
        for tile_id in range(num_tiles):
            pm, pn = compute_tile_position(tile_id, num_pid_m, num_pid_n, 8)
            assert 0 <= pm < num_pid_m, \
                f"tile {tile_id}: pid_m={pm} out of [0, {num_pid_m})"
            assert 0 <= pn < num_pid_n
            seen.add((pm, pn))
        assert len(seen) == num_tiles


# ---------------------------------------------------------------------------
# Test: direct function tests (anti-bypass)
# ---------------------------------------------------------------------------

class TestDirectFunctions:
    """Directly test module functions to ensure they are implemented,
    not just the JSON output."""

    def test_compute_shared_memory_config0(self):
        from modules.resource_model import compute_shared_memory
        # Config 0: BLOCK_M=128, BLOCK_N=128, BLOCK_K=64, stages=3
        # A: 128*64*2 = 16384, B: 64*128*2 = 16384, total per stage = 32768
        # 3 stages: 98304
        assert compute_shared_memory(128, 128, 64, 3) == 98304

    def test_compute_shared_memory_config5(self):
        from modules.resource_model import compute_shared_memory
        # Config 5: BLOCK_M=64, BLOCK_N=64, BLOCK_K=64, stages=4
        # A: 64*64*2 = 8192, B: 64*64*2 = 8192, total per stage = 16384
        # 4 stages: 65536
        assert compute_shared_memory(64, 64, 64, 4) == 65536

    def test_compute_shared_memory_asymmetric(self):
        from modules.resource_model import compute_shared_memory
        # Config 1: BLOCK_M=128, BLOCK_N=256, BLOCK_K=64, stages=3
        # A: 128*64*2 = 16384, B: 64*256*2 = 32768, total per stage = 49152
        # 3 stages: 147456
        assert compute_shared_memory(128, 256, 64, 3) == 147456

    def test_compute_occupancy_valid(self):
        from modules.resource_model import compute_occupancy
        gpu = {
            'shared_mem_per_sm': 167936,
            'max_shared_mem_per_block': 167936,
            'max_warps_per_sm': 64,
            'max_blocks_per_sm': 32,
        }
        # 98304 bytes: blocks_by_smem=1, blocks_by_warps=16, blocks_by_limit=32
        assert compute_occupancy(98304, 4, gpu) == 1

    def test_compute_occupancy_higher(self):
        from modules.resource_model import compute_occupancy
        gpu = {
            'shared_mem_per_sm': 167936,
            'max_shared_mem_per_block': 167936,
            'max_warps_per_sm': 64,
            'max_blocks_per_sm': 32,
        }
        # 65536 bytes: blocks_by_smem=2, blocks_by_warps=8, blocks_by_limit=32
        assert compute_occupancy(65536, 8, gpu) == 2

    def test_compute_occupancy_invalid(self):
        from modules.resource_model import compute_occupancy
        gpu = {
            'shared_mem_per_sm': 167936,
            'max_shared_mem_per_block': 167936,
            'max_warps_per_sm': 64,
            'max_blocks_per_sm': 32,
        }
        # 262144 > 167936: exceeds max per block
        assert compute_occupancy(262144, 4, gpu) == 0

    def test_build_persistent_schedule_basic(self):
        from modules.analyzer import build_persistent_schedule
        s = build_persistent_schedule(4096, 4096, 64, 64, 8, 108)
        assert s['num_pid_m'] == 64
        assert s['num_pid_n'] == 64
        assert s['num_tiles'] == 4096
        assert s['active_sms'] == 108
        assert s['tiles_per_sm_max'] == math.ceil(4096 / 108)

    def test_build_persistent_schedule_small(self):
        from modules.analyzer import build_persistent_schedule
        s = build_persistent_schedule(512, 512, 128, 128, 8, 108)
        assert s['num_pid_m'] == 4
        assert s['num_pid_n'] == 4
        assert s['num_tiles'] == 16
        assert s['active_sms'] == 16

    def test_roofline_sm_utilization_effect(self):
        """When few tiles exist, SM utilization drops and shifts the
        compute-bound threshold. This tests that the implementation
        accounts for SM utilization in the roofline model."""
        from modules.roofline import roofline_estimate
        gpu = {'num_sms': 108, 'fp16_peak_tflops': 312.0, 'memory_bw_gbps': 2039.0}
        # (256,8192,256) config 1 (128x256): 2*32=64 tiles, 64 active SMs
        # SM util = 64/108 = 0.593, makes it compute-bound despite low AI
        config_low_tiles = {'BLOCK_M': 128, 'BLOCK_N': 256}
        perf1 = roofline_estimate(256, 8192, 256, config_low_tiles, gpu)
        assert perf1['is_compute_bound'] is True, \
            "Config with 64 tiles should be compute-bound (low SM util)"

        # Same workload, config 5 (64x64): 4*128=512 tiles, 108 active SMs
        # SM util = 1.0, memory-bound due to low AI
        config_high_tiles = {'BLOCK_M': 64, 'BLOCK_N': 64}
        perf2 = roofline_estimate(256, 8192, 256, config_high_tiles, gpu)
        assert perf2['is_compute_bound'] is False, \
            "Config with 512 tiles should be memory-bound (full SM util)"

    def test_generate_results_reads_from_db(self):
        """Verify generate_results works with the actual database."""
        from modules.analyzer import generate_results
        results = generate_results('/app/profiling.db')
        assert isinstance(results, dict)
        assert "(4096,4096,4096)" in results
        assert len(results) == 6
        for key, configs in results.items():
            assert len(configs) == 6, f"{key}: expected 6 configs"

    def test_expected_output_match(self):
        """Full output must match the reference expected_output.json."""
        with open('/app/results.json') as f:
            actual = json.load(f)
        with open('/app/expected_output.json') as f:
            expected = json.load(f)
        for wk in expected:
            assert wk in actual, f"Missing workload {wk}"
            for i, (ec, ac) in enumerate(zip(expected[wk], actual[wk])):
                assert ec['config_id'] == ac['config_id'], \
                    f"{wk}[{i}]: config_id mismatch {ec['config_id']} vs {ac['config_id']}"
                assert ec['shared_mem_bytes'] == ac['shared_mem_bytes'], \
                    f"{wk} config {ec['config_id']}: shared_mem_bytes mismatch"
                assert ec['is_valid'] == ac['is_valid'], \
                    f"{wk} config {ec['config_id']}: is_valid mismatch"
                for pk in ec['performance']:
                    ev = ec['performance'][pk]
                    av = ac['performance'][pk]
                    if isinstance(ev, bool):
                        assert ev == av, \
                            f"{wk} config {ec['config_id']}: {pk} mismatch {ev} vs {av}"
                    elif isinstance(ev, (int, float)) and ev != 0:
                        assert abs(ev - av) / abs(ev) < 1e-6, \
                            f"{wk} config {ec['config_id']}: {pk} mismatch {ev} vs {av}"
                    else:
                        assert ev == av, \
                            f"{wk} config {ec['config_id']}: {pk} mismatch {ev} vs {av}"
