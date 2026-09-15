#!/usr/bin/env python3

"""Verification tests for multi-objective OoO processor design space analysis.

All expected values are independently recomputed from the raw simulation
data in /app/sim_output/ using the correct power formula, so no hardcoded
answers leak into the environment.
"""

import json
import math
import os
import re
import sys

import pytest
import yaml

sys.path.insert(0, "/app")
from arch_model import compute_area


# ---------------------------------------------------------------------------
# Correct power model (for independent verification)
# ---------------------------------------------------------------------------

def correct_compute_power(width, rob_size, num_int_regs, num_fp_regs,
                          avg_ipc, avg_l1_miss_rate, temperature=350):
    """Power model with both bugs fixed."""
    V, f = 0.9, 1.0
    activity = (avg_ipc / width) * (1.0 + 0.1 * width)
    stall_factor = 1.0 / (1.0 + 2.0 * avg_l1_miss_rate)
    C_eff = 0.5 * (rob_size + 2.0 * width * width)
    dynamic = C_eff * V * V * f * activity * stall_factor
    area = compute_area(width, rob_size, num_int_regs, num_fp_regs)
    k = 0.002
    temp_factor = math.exp(k * (temperature - 300))
    leakage = 0.001 * area * temp_factor
    return round(dynamic + leakage, 4)


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def parse_all_stats():
    """Parse all gem5-format stats files and return config data."""
    sim_dir = "/app/sim_output"
    configs = {}

    for config_id in sorted(os.listdir(sim_dir)):
        stats_path = os.path.join(sim_dir, config_id, "stats.txt")
        if not os.path.isfile(stats_path):
            continue

        with open(stats_path) as fp:
            content = fp.read()

        sections = re.split(
            r"---------- Begin Simulation Statistics \[(\w+)\] ----------",
            content,
        )

        ipcs = {}
        l1_miss_rates = {}
        width = rob = num_int = num_fp = None

        for idx in range(1, len(sections), 2):
            wl = sections[idx]
            block = sections[idx + 1]
            stats = {}
            for line in block.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("---"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    stats[parts[0]] = parts[-1]

            insts = int(stats["system.cpu.committedInsts"])
            cycles = int(stats["system.cpu.numCycles"])
            ipcs[wl] = insts / cycles

            l1_h = int(stats[
                "board.cache_hierarchy.ruby_system."
                "l1_controllers0.L1Dcache.m_demand_hits"
            ])
            l1_m = int(stats[
                "board.cache_hierarchy.ruby_system."
                "l1_controllers0.L1Dcache.m_demand_misses"
            ])
            l1_miss_rates[wl] = l1_m / (l1_h + l1_m)

            if width is None:
                width = int(stats["system.cpu.fetchWidth"])
                rob = int(stats["system.cpu.numROBEntries"])
                num_int = int(stats["system.cpu.numPhysIntRegs"])
                num_fp = int(stats["system.cpu.numPhysFloatRegs"])

        configs[config_id] = {
            "width": width,
            "rob_size": rob,
            "num_int_regs": num_int,
            "num_fp_regs": num_fp,
            "ipcs": ipcs,
            "l1_miss_rates": l1_miss_rates,
        }

    return configs


def load_constraints():
    with open("/app/constraints.yaml") as fp:
        return yaml.safe_load(fp)


def compute_expected():
    """Independently recompute all expected results from raw data."""
    configs = parse_all_stats()
    constraints = load_constraints()
    weights = constraints["workload_weights"]
    baseline_id = constraints["baseline_config"]
    temperature = constraints["temperature_kelvin"]
    scenarios = constraints["budget_scenarios"]
    workloads = sorted(weights.keys())

    # 1. Area scores
    area_scores = {}
    for cid, cfg in configs.items():
        area_scores[cid] = compute_area(
            cfg["width"], cfg["rob_size"],
            cfg["num_int_regs"], cfg["num_fp_regs"],
        )

    # 2. Power estimates
    power_estimates = {}
    for cid, cfg in configs.items():
        product = 1.0
        for wl in workloads:
            product *= cfg["ipcs"][wl]
        avg_ipc = product ** (1.0 / len(workloads))
        avg_miss = sum(cfg["l1_miss_rates"][wl] for wl in workloads) / len(workloads)
        power_estimates[cid] = correct_compute_power(
            cfg["width"], cfg["rob_size"],
            cfg["num_int_regs"], cfg["num_fp_regs"],
            avg_ipc, avg_miss, temperature,
        )

    # 3. Weighted performance
    baseline_ipcs = configs[baseline_id]["ipcs"]
    weighted_perf = {}
    for cid, cfg in configs.items():
        log_sum = 0.0
        for wl in workloads:
            speedup = cfg["ipcs"][wl] / baseline_ipcs[wl]
            log_sum += weights[wl] * math.log(speedup)
        weighted_perf[cid] = round(math.exp(log_sum), 6)

    # 4. 3-objective Pareto front
    cids = list(configs.keys())
    pareto = []
    for cid in cids:
        dominated = False
        for other in cids:
            if other == cid:
                continue
            if (
                area_scores[other] <= area_scores[cid]
                and power_estimates[other] <= power_estimates[cid]
                and weighted_perf[other] >= weighted_perf[cid]
                and (
                    area_scores[other] < area_scores[cid]
                    or power_estimates[other] < power_estimates[cid]
                    or weighted_perf[other] > weighted_perf[cid]
                )
            ):
                dominated = True
                break
        if not dominated:
            pareto.append(cid)
    pareto.sort(key=lambda x: (area_scores[x], power_estimates[x]))

    # 5. Bottleneck identification
    grid = {
        "width": sorted(set(c["width"] for c in configs.values())),
        "rob_size": sorted(set(c["rob_size"] for c in configs.values())),
        "num_int_regs": sorted(set(c["num_int_regs"] for c in configs.values())),
        "num_fp_regs": sorted(set(c["num_fp_regs"] for c in configs.values())),
    }
    bcfg = configs[baseline_id]
    base_params = {
        "width": bcfg["width"],
        "rob_size": bcfg["rob_size"],
        "num_int_regs": bcfg["num_int_regs"],
        "num_fp_regs": bcfg["num_fp_regs"],
    }

    bottlenecks = {}
    for wl in workloads:
        base_ipc = baseline_ipcs[wl]
        best_param = None
        best_delta = -1.0
        for param in ["width", "rob_size", "num_int_regs", "num_fp_regs"]:
            vals = grid[param]
            idx = vals.index(base_params[param])
            if idx + 1 >= len(vals):
                continue
            nxt = vals[idx + 1]
            tp = dict(base_params)
            tp[param] = nxt
            test_cid = (
                f"w{tp['width']}_r{tp['rob_size']}"
                f"_i{tp['num_int_regs']}_f{tp['num_fp_regs']}"
            )
            delta = configs[test_cid]["ipcs"][wl] - base_ipc
            if delta > best_delta:
                best_delta = delta
                best_param = param
        bottlenecks[wl] = best_param

    # 6. Scenario optimal
    scenario_optimal = {}
    for name, sc in scenarios.items():
        mx_area = sc["max_area"]
        mx_power = sc["max_power"]
        best_cid = None
        best_perf = -1.0
        best_a = float("inf")
        best_p = float("inf")
        for cid in configs:
            if area_scores[cid] <= mx_area and power_estimates[cid] <= mx_power:
                p = weighted_perf[cid]
                a = area_scores[cid]
                pw = power_estimates[cid]
                if (
                    p > best_perf
                    or (p == best_perf and a < best_a)
                    or (p == best_perf and a == best_a and pw < best_p)
                ):
                    best_perf = p
                    best_cid = cid
                    best_a = a
                    best_p = pw
        scenario_optimal[name] = best_cid

    return {
        "area_scores": area_scores,
        "power_estimates": power_estimates,
        "weighted_perf": weighted_perf,
        "pareto_front": pareto,
        "bottlenecks": bottlenecks,
        "scenario_optimal": scenario_optimal,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected():
    return compute_expected()


# ---------------------------------------------------------------------------
# Tests: structural checks
# ---------------------------------------------------------------------------

class TestResultsStructure:
    def test_required_keys(self, results):
        for key in ["area_scores", "power_estimates", "weighted_perf",
                     "pareto_front", "bottlenecks", "scenario_optimal"]:
            assert key in results, f"Missing top-level key: {key}"

    def test_config_count(self, results, expected):
        assert len(results["area_scores"]) == len(expected["area_scores"]), (
            f"Expected {len(expected['area_scores'])} configs, "
            f"got {len(results['area_scores'])}"
        )


# ---------------------------------------------------------------------------
# Tests: area scores
# ---------------------------------------------------------------------------

class TestAreaScores:
    def test_baseline_area(self, results):
        assert results["area_scores"]["w4_r32_i64_f64"] == 976

    def test_max_area(self, results):
        exp = compute_area(12, 256, 256, 256)
        assert results["area_scores"]["w12_r256_i256_f256"] == exp

    def test_all_areas(self, results, expected):
        for cid, exp_area in expected["area_scores"].items():
            assert cid in results["area_scores"], f"Missing config: {cid}"
            assert results["area_scores"][cid] == exp_area, (
                f"Area mismatch for {cid}: "
                f"got {results['area_scores'][cid]}, expected {exp_area}"
            )


# ---------------------------------------------------------------------------
# Tests: power estimates
# ---------------------------------------------------------------------------

class TestPowerEstimates:
    def test_config_count(self, results, expected):
        assert len(results["power_estimates"]) == len(expected["power_estimates"])

    def test_baseline_power_reasonable(self, results):
        p = results["power_estimates"]["w4_r32_i64_f64"]
        assert 5.0 < p < 15.0, f"Baseline power {p} out of expected range"

    def test_power_increases_with_area(self, results):
        """Larger configs should generally have higher power."""
        p_small = results["power_estimates"]["w4_r32_i64_f64"]
        p_large = results["power_estimates"]["w12_r256_i256_f256"]
        assert p_large > p_small

    def test_all_powers(self, results, expected):
        for cid, exp in expected["power_estimates"].items():
            assert cid in results["power_estimates"], f"Missing {cid}"
            got = results["power_estimates"][cid]
            assert abs(got - exp) < 0.05, (
                f"Power mismatch for {cid}: got {got}, expected {exp}"
            )


# ---------------------------------------------------------------------------
# Tests: weighted performance
# ---------------------------------------------------------------------------

class TestWeightedPerf:
    def test_baseline_is_one(self, results):
        assert abs(results["weighted_perf"]["w4_r32_i64_f64"] - 1.0) < 1e-6

    def test_max_config_gt_one(self, results):
        assert results["weighted_perf"]["w12_r256_i256_f256"] > 1.0

    def test_all_weighted(self, results, expected):
        for cid, exp_g in expected["weighted_perf"].items():
            assert cid in results["weighted_perf"], f"Missing config: {cid}"
            got = results["weighted_perf"][cid]
            assert abs(got - exp_g) < 1e-4, (
                f"Weighted perf mismatch for {cid}: "
                f"got {got:.6f}, expected {exp_g:.6f}"
            )


# ---------------------------------------------------------------------------
# Tests: Pareto frontier (3-objective)
# ---------------------------------------------------------------------------

class TestParetoFront:
    def test_baseline_in_pareto(self, results):
        assert "w4_r32_i64_f64" in results["pareto_front"]

    def test_sorted_by_area(self, results):
        areas = [results["area_scores"][c] for c in results["pareto_front"]]
        assert areas == sorted(areas), "Pareto front must be sorted by area"

    def test_no_dominated_in_pareto(self, results):
        pf = results["pareto_front"]
        a = results["area_scores"]
        p = results["power_estimates"]
        g = results["weighted_perf"]
        for c1 in pf:
            for c2 in pf:
                if c1 == c2:
                    continue
                assert not (
                    a[c2] <= a[c1]
                    and p[c2] <= p[c1]
                    and g[c2] >= g[c1]
                    and (a[c2] < a[c1] or p[c2] < p[c1] or g[c2] > g[c1])
                ), f"{c1} is dominated by {c2} but both are in Pareto set"

    def test_all_non_pareto_are_dominated(self, results):
        pf_set = set(results["pareto_front"])
        a = results["area_scores"]
        p = results["power_estimates"]
        g = results["weighted_perf"]
        for cid in a:
            if cid in pf_set:
                continue
            dominated = any(
                a[pc] <= a[cid]
                and p[pc] <= p[cid]
                and g[pc] >= g[cid]
                and (a[pc] < a[cid] or p[pc] < p[cid] or g[pc] > g[cid])
                for pc in pf_set
            )
            assert dominated, (
                f"{cid} (area={a[cid]}, power={p[cid]:.4f}, "
                f"perf={g[cid]:.6f}) is not dominated by any Pareto member"
            )

    def test_pareto_set_matches(self, results, expected):
        assert set(results["pareto_front"]) == set(expected["pareto_front"]), (
            f"Pareto set mismatch.\n"
            f"Got:      {sorted(results['pareto_front'])}\n"
            f"Expected: {sorted(expected['pareto_front'])}"
        )


# ---------------------------------------------------------------------------
# Tests: bottleneck identification
# ---------------------------------------------------------------------------

class TestBottlenecks:
    def test_workload_keys(self, results):
        expected_wls = {"bfs", "bubble_sort", "matrix_multiply", "nqueens"}
        assert set(results["bottlenecks"].keys()) == expected_wls

    def test_valid_parameter_names(self, results):
        valid = {"width", "rob_size", "num_int_regs", "num_fp_regs"}
        for wl, param in results["bottlenecks"].items():
            assert param in valid, f"Invalid bottleneck '{param}' for {wl}"

    def test_all_bottlenecks(self, results, expected):
        for wl in expected["bottlenecks"]:
            assert results["bottlenecks"][wl] == expected["bottlenecks"][wl], (
                f"Bottleneck mismatch for {wl}: "
                f"got {results['bottlenecks'][wl]}, "
                f"expected {expected['bottlenecks'][wl]}"
            )


# ---------------------------------------------------------------------------
# Tests: scenario-optimal configurations
# ---------------------------------------------------------------------------

class TestScenarioOptimal:
    def test_scenario_keys(self, results):
        assert set(results["scenario_optimal"].keys()) == {
            "mobile", "laptop", "desktop", "server"
        }

    def test_configs_exist(self, results):
        for sc, cid in results["scenario_optimal"].items():
            assert cid in results["area_scores"], (
                f"Scenario {sc} optimal config '{cid}' not in area_scores"
            )

    def test_constraints_satisfied(self, results):
        constraints = load_constraints()
        for sc_name, sc in constraints["budget_scenarios"].items():
            cid = results["scenario_optimal"][sc_name]
            assert results["area_scores"][cid] <= sc["max_area"], (
                f"{sc_name}: config {cid} area "
                f"{results['area_scores'][cid]} exceeds {sc['max_area']}"
            )
            assert results["power_estimates"][cid] <= sc["max_power"], (
                f"{sc_name}: config {cid} power "
                f"{results['power_estimates'][cid]} exceeds {sc['max_power']}"
            )

    def test_truly_optimal(self, results):
        """No other feasible config has strictly higher weighted_perf."""
        constraints = load_constraints()
        for sc_name, sc in constraints["budget_scenarios"].items():
            opt_cid = results["scenario_optimal"][sc_name]
            opt_perf = results["weighted_perf"][opt_cid]
            opt_area = results["area_scores"][opt_cid]
            for cid, area in results["area_scores"].items():
                if area <= sc["max_area"] and results["power_estimates"][cid] <= sc["max_power"]:
                    p = results["weighted_perf"][cid]
                    a = results["area_scores"][cid]
                    assert p <= opt_perf + 1e-9 or (
                        abs(p - opt_perf) < 1e-9 and a >= opt_area
                    ), (
                        f"Scenario {sc_name}: config {cid} "
                        f"(perf={p:.6f}, area={a}) beats optimal {opt_cid} "
                        f"(perf={opt_perf:.6f}, area={opt_area})"
                    )

    def test_all_scenarios(self, results, expected):
        for sc in expected["scenario_optimal"]:
            assert results["scenario_optimal"][sc] == expected["scenario_optimal"][sc], (
                f"Scenario {sc} mismatch: "
                f"got {results['scenario_optimal'][sc]}, "
                f"expected {expected['scenario_optimal'][sc]}"
            )
