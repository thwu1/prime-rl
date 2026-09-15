
import json
import os
import pytest

RESULTS_PATH = "/app/results.json"

EXPECTED_SIMULATIONS = {
    "sim1": {
        "total_accesses": 200, "loads": 134, "stores": 66,
        "hits": 81, "misses": 119, "hit_rate": 0.405, "miss_rate": 0.595,
        "writebacks": 18,
        "bytes_bus_to_cache": 7616, "bytes_cache_to_bus": 1152,
        "bytes_total_traffic": 8768,
    },
    "sim2": {
        "total_accesses": 200, "loads": 134, "stores": 66,
        "hits": 111, "misses": 89, "hit_rate": 0.555, "miss_rate": 0.445,
        "writebacks": 9,
        "bytes_bus_to_cache": 5696, "bytes_cache_to_bus": 576,
        "bytes_total_traffic": 6272,
    },
    "sim3": {
        "total_accesses": 200, "loads": 134, "stores": 66,
        "hits": 130, "misses": 70, "hit_rate": 0.65, "miss_rate": 0.35,
        "writebacks": 0,
        "bytes_bus_to_cache": 4480, "bytes_cache_to_bus": 0,
        "bytes_total_traffic": 4480,
    },
    "sim4": {
        "total_accesses": 2000, "loads": 1483, "stores": 517,
        "hits": 937, "misses": 1063, "hit_rate": 0.4685, "miss_rate": 0.5315,
        "writebacks": 377,
        "bytes_bus_to_cache": 68032, "bytes_cache_to_bus": 24128,
        "bytes_total_traffic": 92160,
    },
    "sim5": {
        "total_accesses": 2000, "loads": 1483, "stores": 517,
        "hits": 1361, "misses": 639, "hit_rate": 0.6805, "miss_rate": 0.3195,
        "writebacks": 218,
        "bytes_bus_to_cache": 40896, "bytes_cache_to_bus": 13952,
        "bytes_total_traffic": 54848,
    },
    "sim6": {
        "total_accesses": 2000, "loads": 1483, "stores": 517,
        "hits": 1260, "misses": 740, "hit_rate": 0.63, "miss_rate": 0.37,
        "writebacks": 264,
        "bytes_bus_to_cache": 23680, "bytes_cache_to_bus": 8448,
        "bytes_total_traffic": 32128,
    },
}

EXPECTED_SD_SMALL = {
    "inf": 50, "0": 11, "1": 19, "2": 12, "3": 15, "4": 11,
    "5": 5, "6": 8, "7": 6, "8": 4, "9": 5, "11": 1, "14": 1,
    "16": 2, "19": 30, "43": 1, "45": 1, "46": 3, "47": 3,
    "48": 5, "49": 7,
}

EXPECTED_SD_MEDIUM_SPOT = {
    "inf": 128, "0": 80, "1": 87, "2": 90, "3": 87,
    "4": 83, "5": 98, "6": 94, "7": 97,
    "127": 372,
}

EXPECTED_PREDICTIONS_SMALL = {
    "4": 0.715, "8": 0.565, "16": 0.51, "32": 0.35,
}

EXPECTED_PREDICTIONS_MEDIUM = {
    "8": 0.642, "16": 0.533, "32": 0.3635, "64": 0.32, "128": 0.064,
}

EXPECTED_OPTIMIZATION = {
    "best_cache_size": 8192,
    "best_block_size": 32,
    "best_associativity": 1,
    "best_cost": 8192,
    "achieved_miss_rate": 0.064,
}


@pytest.fixture(scope="session")
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "The analyzer must produce /app/results.json."
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    def test_top_level_keys(self, results):
        for key in ["simulations", "stack_distance",
                     "miss_rate_predictions", "optimize"]:
            assert key in results, f"Missing top-level key: {key}"

    def test_simulation_ids_present(self, results):
        sims = results["simulations"]
        for sid in ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"]:
            assert sid in sims, f"Missing simulation result: {sid}"

    def test_stack_distance_ids_present(self, results):
        sd = results["stack_distance"]
        for sid in ["sd_small", "sd_medium"]:
            assert sid in sd, f"Missing stack distance result: {sid}"

    def test_prediction_ids_present(self, results):
        preds = results["miss_rate_predictions"]
        for pid in ["pred_small", "pred_medium"]:
            assert pid in preds, f"Missing prediction result: {pid}"

    def test_optimize_ids_present(self, results):
        opt = results["optimize"]
        assert "opt1" in opt, "Missing optimization result: opt1"


class TestSimulationExact:
    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_total_accesses(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert actual["total_accesses"] == expected["total_accesses"]

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_loads(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert actual["loads"] == expected["loads"]

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_stores(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert actual["stores"] == expected["stores"]

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_hits(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert actual["hits"] == expected["hits"], (
            f"{sim_id}: expected hits={expected['hits']}, got {actual['hits']}")

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_misses(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert actual["misses"] == expected["misses"], (
            f"{sim_id}: expected misses={expected['misses']}, "
            f"got {actual['misses']}")

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_writebacks(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert actual["writebacks"] == expected["writebacks"], (
            f"{sim_id}: expected writebacks={expected['writebacks']}, "
            f"got {actual['writebacks']}")

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_hit_rate(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert abs(actual["hit_rate"] - expected["hit_rate"]) < 1e-5, (
            f"{sim_id}: expected hit_rate={expected['hit_rate']}, "
            f"got {actual['hit_rate']}")

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_miss_rate(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert abs(actual["miss_rate"] - expected["miss_rate"]) < 1e-5, (
            f"{sim_id}: expected miss_rate={expected['miss_rate']}, "
            f"got {actual['miss_rate']}")

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_traffic_bus_to_cache(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert actual["bytes_bus_to_cache"] == expected["bytes_bus_to_cache"]

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_traffic_cache_to_bus(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert actual["bytes_cache_to_bus"] == expected["bytes_cache_to_bus"]

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_traffic_total(self, results, sim_id):
        actual = results["simulations"][sim_id]
        expected = EXPECTED_SIMULATIONS[sim_id]
        assert actual["bytes_total_traffic"] == expected["bytes_total_traffic"]


class TestSimulationConsistency:
    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_hits_plus_misses_equals_total(self, results, sim_id):
        s = results["simulations"][sim_id]
        assert s["hits"] + s["misses"] == s["total_accesses"]

    @pytest.mark.parametrize("sim_id",
                             ["sim1", "sim2", "sim3", "sim4", "sim5", "sim6"])
    def test_loads_plus_stores_equals_total(self, results, sim_id):
        s = results["simulations"][sim_id]
        assert s["loads"] + s["stores"] == s["total_accesses"]


class TestStackDistanceSmall:
    def test_total_accesses(self, results):
        sd = results["stack_distance"]["sd_small"]
        assert sd["total_accesses"] == 200

    def test_histogram_sum_equals_total(self, results):
        sd = results["stack_distance"]["sd_small"]
        total = sum(sd["histogram"].values())
        assert total == sd["total_accesses"]

    def test_cold_misses(self, results):
        h = results["stack_distance"]["sd_small"]["histogram"]
        assert h.get("inf", 0) == 50, (
            f"Expected 50 cold misses (inf), got {h.get('inf', 0)}")

    @pytest.mark.parametrize("dist,count", list(EXPECTED_SD_SMALL.items()))
    def test_histogram_entry(self, results, dist, count):
        h = results["stack_distance"]["sd_small"]["histogram"]
        actual = h.get(str(dist), 0)
        assert actual == count, (
            f"sd_small histogram[{dist}]: expected {count}, got {actual}")

    def test_no_extra_entries(self, results):
        h = results["stack_distance"]["sd_small"]["histogram"]
        expected_keys = {str(k) for k in EXPECTED_SD_SMALL.keys()}
        actual_keys = {k for k, v in h.items() if v > 0}
        extra = actual_keys - expected_keys
        assert not extra, f"Unexpected histogram entries: {extra}"


class TestStackDistanceMedium:
    def test_total_accesses(self, results):
        sd = results["stack_distance"]["sd_medium"]
        assert sd["total_accesses"] == 2000

    def test_histogram_sum(self, results):
        sd = results["stack_distance"]["sd_medium"]
        total = sum(sd["histogram"].values())
        assert total == 2000

    @pytest.mark.parametrize("dist,count",
                             list(EXPECTED_SD_MEDIUM_SPOT.items()))
    def test_spot_check(self, results, dist, count):
        h = results["stack_distance"]["sd_medium"]["histogram"]
        actual = h.get(str(dist), 0)
        assert actual == count, (
            f"sd_medium histogram[{dist}]: expected {count}, got {actual}")


class TestMissRatePredictions:
    @pytest.mark.parametrize("nb,expected_mr",
                             list(EXPECTED_PREDICTIONS_SMALL.items()))
    def test_pred_small(self, results, nb, expected_mr):
        preds = results["miss_rate_predictions"]["pred_small"]
        actual = preds[str(nb)]
        assert abs(actual - expected_mr) < 1e-5, (
            f"pred_small[{nb}]: expected {expected_mr}, got {actual}")

    @pytest.mark.parametrize("nb,expected_mr",
                             list(EXPECTED_PREDICTIONS_MEDIUM.items()))
    def test_pred_medium(self, results, nb, expected_mr):
        preds = results["miss_rate_predictions"]["pred_medium"]
        actual = preds[str(nb)]
        assert abs(actual - expected_mr) < 1e-5, (
            f"pred_medium[{nb}]: expected {expected_mr}, got {actual}")


class TestOptimization:
    def test_best_cache_size(self, results):
        opt = results["optimize"]["opt1"]
        assert opt["best_cache_size"] == EXPECTED_OPTIMIZATION["best_cache_size"]

    def test_best_block_size(self, results):
        opt = results["optimize"]["opt1"]
        assert opt["best_block_size"] == EXPECTED_OPTIMIZATION["best_block_size"]

    def test_best_associativity(self, results):
        opt = results["optimize"]["opt1"]
        assert opt["best_associativity"] == \
            EXPECTED_OPTIMIZATION["best_associativity"]

    def test_best_cost(self, results):
        opt = results["optimize"]["opt1"]
        assert opt["best_cost"] == EXPECTED_OPTIMIZATION["best_cost"]

    def test_achieved_miss_rate(self, results):
        opt = results["optimize"]["opt1"]
        assert abs(opt["achieved_miss_rate"] -
                   EXPECTED_OPTIMIZATION["achieved_miss_rate"]) < 1e-5

    def test_meets_target(self, results):
        opt = results["optimize"]["opt1"]
        assert opt["achieved_miss_rate"] <= 0.10, (
            f"Optimal config miss_rate {opt['achieved_miss_rate']} "
            f"exceeds target 0.10")
