
import pytest
import json
import sys
import os

sys.path.insert(0, "/app")
from kernel_sim.grid import TileGrid
from kernel_sim.cache_model import L2CacheModel
from kernel_sim.scheduler import TileScheduler
from kernel_sim.hardware import HardwareConfig


# ── Cache Model (bug fix verification) ──────────────────────────────────────


class TestCacheModelWorkingSet:
    """Verify working_set counts UNIQUE stripes, not total references."""

    def test_same_row_tiles(self):
        cache = L2CacheModel(1)
        # 3 tiles in same row: 1 unique row + 3 unique cols = 4
        assert cache.working_set([(0, 0), (0, 1), (0, 2)]) == 4

    def test_same_col_tiles(self):
        cache = L2CacheModel(1)
        # 3 tiles in same col: 3 unique rows + 1 unique col = 4
        assert cache.working_set([(0, 0), (1, 0), (2, 0)]) == 4

    def test_diagonal(self):
        cache = L2CacheModel(1)
        assert cache.working_set([(0, 0), (1, 1), (2, 2)]) == 6

    def test_single_tile(self):
        cache = L2CacheModel(1)
        assert cache.working_set([(5, 3)]) == 2

    def test_duplicate_tiles(self):
        cache = L2CacheModel(1)
        # Duplicates must not inflate count
        assert cache.working_set([(0, 0), (0, 0), (0, 0)]) == 2

    def test_full_3x3(self):
        cache = L2CacheModel(1)
        tiles = [(i, j) for i in range(3) for j in range(3)]
        assert cache.working_set(tiles) == 6  # 3 rows + 3 cols


class TestCacheModelDramLoads:
    """Validates against the classic Triton matmul tutorial L2 example."""

    def test_row_major_9x9_first_9(self):
        grid = TileGrid(9, 9, 9, 1, 1, 1)
        cache = L2CacheModel(grid.k_tiles)
        rm_tiles = grid.naive_schedule()[:9]
        # Row 0, all 9 cols: 1 + 9 = 10 stripes, x 9 k-tiles = 90
        assert all(t[0] == 0 for t in rm_tiles)
        assert cache.dram_loads(rm_tiles) == 90

    def test_grouped_9x9_first_9(self):
        grid = TileGrid(9, 9, 9, 1, 1, 1)
        cache = L2CacheModel(grid.k_tiles)
        gr_tiles = grid.grouped_schedule(3)[:9]
        rows = {t[0] for t in gr_tiles}
        cols = {t[1] for t in gr_tiles}
        assert rows == {0, 1, 2}
        assert cols == {0, 1, 2}
        # 3 + 3 = 6 stripes, x 9 = 54
        assert cache.dram_loads(gr_tiles) == 54

    def test_cache_improvement_ratio(self):
        grid = TileGrid(9, 9, 9, 1, 1, 1)
        cache = L2CacheModel(grid.k_tiles)
        rm = cache.dram_loads(grid.naive_schedule()[:9])
        gr = cache.dram_loads(grid.grouped_schedule(3)[:9])
        assert gr < rm
        assert gr / rm == pytest.approx(0.6, abs=0.01)


# ── Grouped Tile Scheduling ────────────────────────────────────────────────


class TestGroupedTileId:

    def test_4x4_group2(self):
        grid = TileGrid(4, 4, 1, 1, 1, 1)
        expected = {
            0: (0, 0), 1: (1, 0), 2: (0, 1), 3: (1, 1),
            4: (0, 2), 5: (1, 2), 6: (0, 3), 7: (1, 3),
            8: (2, 0), 9: (3, 0), 10: (2, 1), 11: (3, 1),
            12: (2, 2), 13: (3, 2), 14: (2, 3), 15: (3, 3),
        }
        for pid, exp in expected.items():
            assert grid.grouped_tile_id(pid, 2) == exp, f"pid={pid}"

    def test_9x9_group3(self):
        grid = TileGrid(9, 9, 9, 1, 1, 1)
        cases = {
            0: (0, 0), 1: (1, 0), 2: (2, 0),
            3: (0, 1), 4: (1, 1), 5: (2, 1),
            27: (3, 0), 28: (4, 0), 29: (5, 0),
            54: (6, 0), 80: (8, 8),
        }
        for pid, exp in cases.items():
            assert grid.grouped_tile_id(pid, 3) == exp, f"pid={pid}"

    def test_last_group_smaller(self):
        grid = TileGrid(3, 3, 1, 1, 1, 1)
        # GROUP_SIZE_M=2 on 3 rows: last group has 1 row
        assert grid.grouped_tile_id(6, 2) == (2, 0)
        assert grid.grouped_tile_id(7, 2) == (2, 1)
        assert grid.grouped_tile_id(8, 2) == (2, 2)

    def test_group_size_1_is_row_major(self):
        grid = TileGrid(4, 4, 1, 1, 1, 1)
        assert grid.grouped_tile_id(0, 1) == (0, 0)
        assert grid.grouped_tile_id(1, 1) == (0, 1)
        assert grid.grouped_tile_id(4, 1) == (1, 0)
        assert grid.grouped_tile_id(15, 1) == (3, 3)

    def test_group_ge_rows(self):
        grid = TileGrid(4, 4, 1, 1, 1, 1)
        # GROUP_SIZE_M >= num_pid_m: single group, column-major
        assert grid.grouped_tile_id(0, 4) == (0, 0)
        assert grid.grouped_tile_id(1, 4) == (1, 0)
        assert grid.grouped_tile_id(4, 4) == (0, 1)
        assert grid.grouped_tile_id(15, 4) == (3, 3)

    def test_rectangular_6x4_group3(self):
        grid = TileGrid(6, 4, 1, 1, 1, 1)
        assert grid.grouped_tile_id(0, 3) == (0, 0)
        assert grid.grouped_tile_id(2, 3) == (2, 0)
        assert grid.grouped_tile_id(3, 3) == (0, 1)
        assert grid.grouped_tile_id(11, 3) == (2, 3)
        assert grid.grouped_tile_id(12, 3) == (3, 0)
        assert grid.grouped_tile_id(23, 3) == (5, 3)


class TestTileSchedule:

    @pytest.mark.parametrize("g", [1, 2, 4])
    def test_covers_all_4x4(self, g):
        grid = TileGrid(4, 4, 1, 1, 1, 1)
        tiles = grid.grouped_schedule(g)
        assert len(tiles) == 16
        assert set(tiles) == {(i, j) for i in range(4) for j in range(4)}

    def test_3x3_group2_order(self):
        grid = TileGrid(3, 3, 1, 1, 1, 1)
        tiles = grid.grouped_schedule(2)
        assert len(tiles) == 9
        assert tiles[0] == (0, 0)
        assert tiles[1] == (1, 0)
        assert tiles[6] == (2, 0)

    def test_9x9_group3(self):
        grid = TileGrid(9, 9, 9, 1, 1, 1)
        tiles = grid.grouped_schedule(3)
        assert len(tiles) == 81
        assert set(tiles) == {(i, j) for i in range(9) for j in range(9)}
        assert tiles[:3] == [(0, 0), (1, 0), (2, 0)]
        assert tiles[3:6] == [(0, 1), (1, 1), (2, 1)]

    def test_consistency(self):
        """grouped_schedule must equal sequential grouped_tile_id calls."""
        for m, n, g in [(5, 7, 3), (8, 4, 2), (10, 10, 5)]:
            grid = TileGrid(m, n, 1, 1, 1, 1)
            tiles = grid.grouped_schedule(g)
            for pid, tile in enumerate(tiles):
                assert tile == grid.grouped_tile_id(pid, g), (
                    f"Mismatch at pid={pid} for {m}x{n}, g={g}"
                )


# ── Persistent Schedule ─────────────────────────────────────────────────────


class TestPersistentSchedule:

    def test_basic(self):
        sched = TileScheduler(3)
        assert sched.persistent_schedule(10) == {
            0: [0, 3, 6, 9], 1: [1, 4, 7], 2: [2, 5, 8]
        }

    def test_more_sms_than_tiles(self):
        sched = TileScheduler(10)
        result = sched.persistent_schedule(3)
        assert result == {0: [0], 1: [1], 2: [2]}
        for sm_id in range(3, 10):
            assert sm_id not in result

    def test_equal_sms_and_tiles(self):
        sched = TileScheduler(4)
        assert sched.persistent_schedule(4) == {0: [0], 1: [1], 2: [2], 3: [3]}

    def test_single_sm(self):
        sched = TileScheduler(1)
        assert sched.persistent_schedule(5) == {0: [0, 1, 2, 3, 4]}

    def test_all_tiles_assigned(self):
        sched = TileScheduler(13)
        result = sched.persistent_schedule(100)
        all_tiles = sorted(t for ts in result.values() for t in ts)
        assert all_tiles == list(range(100))


# ── Hardware ─────────────────────────────────────────────────────────────────


class TestBytesInFlight:

    def test_h100(self):
        hw = HardwareConfig("/app/configs/h100.json")
        # 3.35 TB/s * 400 ns = 1,340,000 bytes
        assert abs(hw.bytes_in_flight() - 1340000.0) < 1.0

    def test_consistent_with_config(self):
        hw = HardwareConfig("/app/configs/h100.json")
        expected = hw.bandwidth_bytes_per_sec * hw.memory_latency_sec
        assert hw.bytes_in_flight() == pytest.approx(expected)


# ── Optimal Group Size ───────────────────────────────────────────────────────


class TestOptimalGroupSize:

    def test_9x9_window9(self):
        grid = TileGrid(9, 9, 9, 1, 1, 1)
        cache = L2CacheModel(grid.k_tiles)
        sched = TileScheduler(9)
        assert sched.find_optimal_group_size(grid, cache, [1, 3, 9]) == 3

    def test_trivial_window1(self):
        grid = TileGrid(4, 4, 1, 1, 1, 1)
        cache = L2CacheModel(1)
        sched = TileScheduler(1)
        # Window=1: every ordering has max pressure 2. Smallest wins.
        assert sched.find_optimal_group_size(grid, cache, [1, 2, 4]) == 1

    def test_smallest_on_tie(self):
        grid = TileGrid(4, 4, 1, 1, 1, 1)
        cache = L2CacheModel(1)
        sched = TileScheduler(16)
        # Window covers all tiles: all orderings give WS=8. Smallest wins.
        assert sched.find_optimal_group_size(grid, cache, [1, 2, 4]) == 1

    def test_single_candidate(self):
        grid = TileGrid(8, 8, 1, 1, 1, 1)
        cache = L2CacheModel(1)
        sched = TileScheduler(8)
        assert sched.find_optimal_group_size(grid, cache, [4]) == 4


# ── Analysis JSON ────────────────────────────────────────────────────────────


class TestAnalysisJson:

    @pytest.fixture(scope="class")
    def data(self):
        path = "/app/analysis.json"
        assert os.path.exists(path), "analysis.json not found at /app/analysis.json"
        with open(path) as f:
            return json.load(f)

    def test_required_keys(self, data):
        required = [
            "num_pid_m", "num_pid_n", "k_tiles", "total_tiles",
            "bytes_in_flight", "optimal_group_size",
            "row_major_max_pressure", "optimal_max_pressure",
        ]
        for key in required:
            assert key in data, f"Missing key: {key}"

    def test_grid_dimensions(self, data):
        assert data["num_pid_m"] == 32
        assert data["num_pid_n"] == 32
        assert data["k_tiles"] == 32
        assert data["total_tiles"] == 1024

    def test_bytes_in_flight(self, data):
        assert abs(data["bytes_in_flight"] - 1340000.0) < 1.0

    def test_optimal_group_size(self, data):
        assert data["optimal_group_size"] == 8

    def test_row_major_pressure(self, data):
        assert data["row_major_max_pressure"] == 38

    def test_optimal_pressure(self, data):
        assert data["optimal_max_pressure"] == 34

    def test_optimal_beats_baseline(self, data):
        assert data["optimal_max_pressure"] < data["row_major_max_pressure"]
