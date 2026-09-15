"""
Tests for RISC-V Pipeline Hazard and Cache Microarchitecture Analysis.

"""
import json
import os
import pytest

RESULTS_PATH = "/app/results.json"

# ─── Reference Answers ───────────────────────────────────────────────────────

EXPECTED_GEOMETRY = {
    "dm-4k": {"linebytelen": 32, "offsetlen": 5, "numsets": 128, "setlen": 7, "settop": 12, "taglen": 22, "total_bytes": 4096},
    "2w-4k": {"linebytelen": 32, "offsetlen": 5, "numsets": 128, "setlen": 7, "settop": 12, "taglen": 22, "total_bytes": 8192},
    "4w-4k": {"linebytelen": 32, "offsetlen": 5, "numsets": 128, "setlen": 7, "settop": 12, "taglen": 22, "total_bytes": 16384},
    "2w-2k-narrow": {"linebytelen": 16, "offsetlen": 4, "numsets": 128, "setlen": 7, "settop": 11, "taglen": 23, "total_bytes": 4096},
    "2w-1k": {"linebytelen": 32, "offsetlen": 5, "numsets": 32, "setlen": 5, "settop": 10, "taglen": 24, "total_bytes": 2048},
    "8w-1k": {"linebytelen": 32, "offsetlen": 5, "numsets": 32, "setlen": 5, "settop": 10, "taglen": 24, "total_bytes": 8192},
}

EXPECTED_SIMULATION = {
    "dm-4k": {"hits": 7, "misses": 43, "miss_rate": 0.86, "evictions": 30, "conflict_misses": 18},
    "2w-4k": {"hits": 14, "misses": 36, "miss_rate": 0.72, "evictions": 19, "conflict_misses": 11},
    "4w-4k": {"hits": 19, "misses": 31, "miss_rate": 0.62, "evictions": 12, "conflict_misses": 6},
    "2w-2k-narrow": {"hits": 12, "misses": 38, "miss_rate": 0.76, "evictions": 20, "conflict_misses": 11},
    "2w-1k": {"hits": 14, "misses": 36, "miss_rate": 0.72, "evictions": 22, "conflict_misses": 11},
    "8w-1k": {"hits": 23, "misses": 27, "miss_rate": 0.54, "evictions": 7, "conflict_misses": 2},
}

EXPECTED_HAZARD = {
    "structural-stall": {
        "cycles": [
            {"StallF": 1, "StallD": 1, "StallE": 0, "StallM": 0, "StallW": 0, "FlushD": 0, "FlushE": 1, "FlushM": 0, "FlushW": 0}
        ]
    },
    "branch-mispredict": {
        "cycles": [
            {"StallF": 0, "StallD": 0, "StallE": 0, "StallM": 0, "StallW": 0, "FlushD": 1, "FlushE": 1, "FlushM": 0, "FlushW": 0}
        ]
    },
    "div-busy": {
        "cycles": [
            {"StallF": 1, "StallD": 1, "StallE": 1, "StallM": 0, "StallW": 0, "FlushD": 0, "FlushE": 0, "FlushM": 1, "FlushW": 0},
            {"StallF": 1, "StallD": 1, "StallE": 1, "StallM": 0, "StallW": 0, "FlushD": 0, "FlushE": 0, "FlushM": 1, "FlushW": 0},
            {"StallF": 0, "StallD": 0, "StallE": 0, "StallM": 0, "StallW": 0, "FlushD": 0, "FlushE": 0, "FlushM": 0, "FlushW": 0},
        ]
    },
    "bp-wrong-during-div": {
        "cycles": [
            {"StallF": 1, "StallD": 1, "StallE": 1, "StallM": 0, "StallW": 0, "FlushD": 1, "FlushE": 0, "FlushM": 1, "FlushW": 0}
        ]
    },
    "wfi-interrupted-trap": {
        "cycles": [
            {"StallF": 0, "StallD": 0, "StallE": 0, "StallM": 0, "StallW": 0, "FlushD": 1, "FlushE": 1, "FlushM": 1, "FlushW": 0}
        ]
    },
    "csr-write-fence": {
        "cycles": [
            {"StallF": 0, "StallD": 0, "StallE": 0, "StallM": 0, "StallW": 0, "FlushD": 1, "FlushE": 1, "FlushM": 1, "FlushW": 0}
        ]
    },
    "ifu-stall-with-trap": {
        "cycles": [
            {"StallF": 0, "StallD": 0, "StallE": 0, "StallM": 0, "StallW": 0, "FlushD": 1, "FlushE": 1, "FlushM": 1, "FlushW": 1}
        ]
    },
    "multi-hazard": {
        "cycles": [
            {"StallF": 1, "StallD": 1, "StallE": 1, "StallM": 1, "StallW": 1, "FlushD": 1, "FlushE": 1, "FlushM": 0, "FlushW": 0}
        ]
    },
}


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# ─── Structural Tests ────────────────────────────────────────────────────────

class TestStructure:
    def test_has_cache_geometry(self, results):
        assert "cache_geometry" in results, "Missing 'cache_geometry' section"

    def test_has_cache_simulation(self, results):
        assert "cache_simulation" in results, "Missing 'cache_simulation' section"

    def test_has_hazard_analysis(self, results):
        assert "hazard_analysis" in results, "Missing 'hazard_analysis' section"

    def test_all_configs_present_geometry(self, results):
        for name in EXPECTED_GEOMETRY:
            assert name in results["cache_geometry"], f"Missing config '{name}' in cache_geometry"

    def test_all_configs_present_simulation(self, results):
        for name in EXPECTED_SIMULATION:
            assert name in results["cache_simulation"], f"Missing config '{name}' in cache_simulation"

    def test_all_scenarios_present(self, results):
        for name in EXPECTED_HAZARD:
            assert name in results["hazard_analysis"], f"Missing scenario '{name}' in hazard_analysis"


# ─── Cache Geometry Tests ────────────────────────────────────────────────────

class TestCacheGeometry:
    @pytest.mark.parametrize("config_name", list(EXPECTED_GEOMETRY.keys()))
    def test_geometry_fields(self, results, config_name):
        actual = results["cache_geometry"][config_name]
        expected = EXPECTED_GEOMETRY[config_name]
        for field, exp_val in expected.items():
            assert field in actual, f"{config_name}: missing field '{field}'"
            assert actual[field] == exp_val, (
                f"{config_name}.{field}: expected {exp_val}, got {actual[field]}"
            )


# ─── Cache Simulation Tests ─────────────────────────────────────────────────

class TestCacheSimulation:
    @pytest.mark.parametrize("config_name", list(EXPECTED_SIMULATION.keys()))
    def test_hits(self, results, config_name):
        actual = results["cache_simulation"][config_name]
        expected = EXPECTED_SIMULATION[config_name]
        assert actual["hits"] == expected["hits"], (
            f"{config_name} hits: expected {expected['hits']}, got {actual['hits']}"
        )

    @pytest.mark.parametrize("config_name", list(EXPECTED_SIMULATION.keys()))
    def test_misses(self, results, config_name):
        actual = results["cache_simulation"][config_name]
        expected = EXPECTED_SIMULATION[config_name]
        assert actual["misses"] == expected["misses"], (
            f"{config_name} misses: expected {expected['misses']}, got {actual['misses']}"
        )

    @pytest.mark.parametrize("config_name", list(EXPECTED_SIMULATION.keys()))
    def test_miss_rate(self, results, config_name):
        actual = results["cache_simulation"][config_name]
        expected = EXPECTED_SIMULATION[config_name]
        assert abs(actual["miss_rate"] - expected["miss_rate"]) < 0.0001, (
            f"{config_name} miss_rate: expected {expected['miss_rate']}, got {actual['miss_rate']}"
        )

    @pytest.mark.parametrize("config_name", list(EXPECTED_SIMULATION.keys()))
    def test_evictions(self, results, config_name):
        actual = results["cache_simulation"][config_name]
        expected = EXPECTED_SIMULATION[config_name]
        assert actual["evictions"] == expected["evictions"], (
            f"{config_name} evictions: expected {expected['evictions']}, got {actual['evictions']}"
        )

    @pytest.mark.parametrize("config_name", list(EXPECTED_SIMULATION.keys()))
    def test_conflict_misses(self, results, config_name):
        actual = results["cache_simulation"][config_name]
        expected = EXPECTED_SIMULATION[config_name]
        assert actual["conflict_misses"] == expected["conflict_misses"], (
            f"{config_name} conflict_misses: expected {expected['conflict_misses']}, got {actual['conflict_misses']}"
        )

    @pytest.mark.parametrize("config_name", list(EXPECTED_SIMULATION.keys()))
    def test_hits_plus_misses_equals_50(self, results, config_name):
        actual = results["cache_simulation"][config_name]
        total = actual["hits"] + actual["misses"]
        assert total == 50, f"{config_name}: hits + misses = {total}, expected 50"


# ─── Hazard Analysis Tests ──────────────────────────────────────────────────

class TestHazardAnalysis:
    @pytest.mark.parametrize("scenario_name", list(EXPECTED_HAZARD.keys()))
    def test_cycle_count(self, results, scenario_name):
        actual = results["hazard_analysis"][scenario_name]
        expected = EXPECTED_HAZARD[scenario_name]
        assert len(actual["cycles"]) == len(expected["cycles"]), (
            f"{scenario_name}: expected {len(expected['cycles'])} cycles, got {len(actual['cycles'])}"
        )

    @pytest.mark.parametrize("scenario_name", list(EXPECTED_HAZARD.keys()))
    def test_stall_signals(self, results, scenario_name):
        actual_cycles = results["hazard_analysis"][scenario_name]["cycles"]
        expected_cycles = EXPECTED_HAZARD[scenario_name]["cycles"]
        stall_signals = ["StallF", "StallD", "StallE", "StallM", "StallW"]
        for ci, (act, exp) in enumerate(zip(actual_cycles, expected_cycles)):
            for sig in stall_signals:
                assert act[sig] == exp[sig], (
                    f"{scenario_name} cycle {ci} {sig}: expected {exp[sig]}, got {act[sig]}"
                )

    @pytest.mark.parametrize("scenario_name", list(EXPECTED_HAZARD.keys()))
    def test_flush_signals(self, results, scenario_name):
        actual_cycles = results["hazard_analysis"][scenario_name]["cycles"]
        expected_cycles = EXPECTED_HAZARD[scenario_name]["cycles"]
        flush_signals = ["FlushD", "FlushE", "FlushM", "FlushW"]
        for ci, (act, exp) in enumerate(zip(actual_cycles, expected_cycles)):
            for sig in flush_signals:
                assert act[sig] == exp[sig], (
                    f"{scenario_name} cycle {ci} {sig}: expected {exp[sig]}, got {act[sig]}"
                )

    def test_bp_wrong_div_key_insight(self, results):
        """Verifies the critical corner case: BPWrongE during DivBusyE."""
        scenario = results["hazard_analysis"]["bp-wrong-during-div"]
        cycle = scenario["cycles"][0]
        assert cycle["FlushD"] == 1, "FlushD should be 1 in bp-wrong-during-div"
        assert cycle["FlushE"] == 0, "FlushE should be 0 in bp-wrong-during-div"
        assert cycle["StallE"] == 1, "StallE should be 1 in bp-wrong-during-div"

    def test_wfi_key_insight(self, results):
        """Verifies WFI interrupted trap behavior."""
        scenario = results["hazard_analysis"]["wfi-interrupted-trap"]
        cycle = scenario["cycles"][0]
        assert cycle["FlushW"] == 0, "FlushW should be 0 in wfi-interrupted-trap"
        assert cycle["FlushD"] == 1, "FlushD should be 1 in wfi-interrupted-trap"
        assert cycle["FlushM"] == 1, "FlushM should be 1 in wfi-interrupted-trap"

    def test_ifu_stall_suppressed_by_trap(self, results):
        """IFU stall behavior when trap is active."""
        scenario = results["hazard_analysis"]["ifu-stall-with-trap"]
        cycle = scenario["cycles"][0]
        assert cycle["StallW"] == 0, "StallW should be 0 in ifu-stall-with-trap"
        assert cycle["FlushW"] == 1, "FlushW should be 1 in ifu-stall-with-trap"
