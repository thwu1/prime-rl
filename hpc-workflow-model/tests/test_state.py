"""

Tests for HPC Procurement Benchmark Evaluation.
Independently parses raw benchmark data, cleans outliers, and computes
all expected values to compare against agent output.
"""

import csv
import json
import math
import os
import re
import statistics
import pytest

RESULT_PATH = "/app/results/evaluation.json"
DATA_DIR = "/data"
BENCHMARK_DIR = os.path.join(DATA_DIR, "benchmark_data")

SYSTEMS = ["pinnacle", "horizon", "nexus", "vanguard", "summit_x"]
BENCHMARKS = [
    "stencil3d", "sparse_matvec", "global_fft",
    "deep_train", "genome_search", "mol_dynamics",
]

REL_TOL_TIGHT = 1e-2   # for cleaned times and speedups
REL_TOL_LOOSE = 5e-2   # for composite scores (method-dependent)


# ============================================================
# Data loading and parsing (mirrors what agent must do)
# ============================================================

def load_workload_specs():
    with open(os.path.join(DATA_DIR, "workload_specs.json")) as f:
        return json.load(f)


def load_system_specs():
    with open(os.path.join(DATA_DIR, "system_specs.json")) as f:
        return json.load(f)


def load_procurement_requirements():
    with open(os.path.join(DATA_DIR, "procurement_requirements.json")) as f:
        return json.load(f)


def parse_pinnacle():
    """Parse pinnacle CSV (times in seconds, header has trailing space)."""
    results = {}
    path = os.path.join(BENCHMARK_DIR, "pinnacle", "results.csv")
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bm = row["benchmark"].strip()
            time_key = [k for k in row.keys() if k.strip().startswith("time_s")][0]
            t = float(row[time_key].strip())
            if bm not in results:
                results[bm] = []
            results[bm].append(t)
    return results


def parse_horizon():
    """Parse horizon JSONL (times in MILLISECONDS, exclude errors)."""
    results = {}
    path = os.path.join(BENCHMARK_DIR, "horizon", "benchmark_log.jsonl")
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("status") != "success":
                continue
            bm = entry["benchmark"]
            t = entry["runtime"] / 1000.0  # ms -> seconds
            if bm not in results:
                results[bm] = []
            results[bm].append(t)
    return results


def parse_nexus():
    """Parse nexus custom text log (filter non-data lines)."""
    results = {}
    path = os.path.join(BENCHMARK_DIR, "nexus", "execution.log")
    pattern = re.compile(
        r"benchmark=(\S+)\s+trial=(\d+)\s+time=([\d.]+)s\s+STATUS=OK"
    )
    with open(path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                bm = m.group(1)
                t = float(m.group(3))
                if bm not in results:
                    results[bm] = []
                results[bm].append(t)
    return results


def parse_vanguard():
    """Parse vanguard TSV (handle duplicate entries — keep last)."""
    raw = {}
    path = os.path.join(BENCHMARK_DIR, "vanguard", "perf_data.tsv")
    with open(path) as f:
        header = f.readline()
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            bm = parts[0]
            trial = int(parts[1])
            t = float(parts[2])
            raw[(bm, trial)] = t

    results = {}
    for (bm, trial), t in raw.items():
        if bm not in results:
            results[bm] = []
        results[bm].append(t)
    return results


def parse_summit_x():
    """Parse summit_x CSV (throughput in GFLOP/s — convert to time)."""
    workload = load_workload_specs()
    raw_tp = {}
    path = os.path.join(BENCHMARK_DIR, "summit_x", "throughput_results.csv")
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bm = row["benchmark"].strip()
            tp = float(row["throughput_gflops"].strip())
            if bm not in raw_tp:
                raw_tp[bm] = []
            raw_tp[bm].append(tp)

    results = {}
    for bm, tp_list in raw_tp.items():
        total_flops = workload[bm]["total_flops"]
        results[bm] = [total_flops / (tp * 1e9) for tp in tp_list]
    return results


PARSERS = {
    "pinnacle": parse_pinnacle,
    "horizon": parse_horizon,
    "nexus": parse_nexus,
    "vanguard": parse_vanguard,
    "summit_x": parse_summit_x,
}


def iqr_clean(values):
    """Remove outliers using IQR method (1.5 * IQR rule)."""
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    q1_idx = (n - 1) * 0.25
    q3_idx = (n - 1) * 0.75

    def interpolate(idx):
        low = int(math.floor(idx))
        high = int(math.ceil(idx))
        if low == high:
            return sorted_vals[low]
        frac = idx - low
        return sorted_vals[low] * (1 - frac) + sorted_vals[high] * frac

    q1 = interpolate(q1_idx)
    q3 = interpolate(q3_idx)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    cleaned = [v for v in values if lower <= v <= upper]
    removed = len(values) - len(cleaned)
    return cleaned, removed


# ============================================================
# Expected values computation
# ============================================================

@pytest.fixture(scope="module")
def expected():
    """Independently compute all expected values from raw data."""
    workload = load_workload_specs()
    sys_specs = load_system_specs()
    proc = load_procurement_requirements()
    ref_times = proc["reference_system"]["benchmark_times_s"]
    budget = proc["budget_usd"]
    power_limit = proc["power_envelope_kw"]
    perf_threshold = proc["performance_requirement"]["threshold_fraction"]

    # Parse and clean all data
    cleaned_perf = {}
    for sys_name in SYSTEMS:
        raw = PARSERS[sys_name]()
        cleaned_perf[sys_name] = {}
        for bm in BENCHMARKS:
            if bm not in raw:
                continue
            cleaned, n_removed = iqr_clean(raw[bm])
            median_time = statistics.median(cleaned)
            cleaned_perf[sys_name][bm] = {
                "median_time_s": median_time,
                "num_valid_trials": len(cleaned),
                "num_outliers_removed": n_removed,
            }

    # Speedups
    speedups = {}
    for sys_name in SYSTEMS:
        speedups[sys_name] = {}
        for bm in BENCHMARKS:
            if bm in cleaned_perf[sys_name]:
                sys_time = cleaned_perf[sys_name][bm]["median_time_s"]
                speedups[sys_name][bm] = ref_times[bm] / sys_time

    # Composite scores — weighted arithmetic mean
    composite_arith = {}
    for sys_name in SYSTEMS:
        total_weight = 0.0
        weighted_sum = 0.0
        for bm in BENCHMARKS:
            if bm in speedups[sys_name]:
                w = workload[bm]["priority_weight"]
                weighted_sum += w * speedups[sys_name][bm]
                total_weight += w
        if total_weight > 0:
            composite_arith[sys_name] = weighted_sum / total_weight
        else:
            composite_arith[sys_name] = 0.0

    # Also compute geometric mean for tolerance comparison
    composite_geom = {}
    for sys_name in SYSTEMS:
        total_weight = 0.0
        log_sum = 0.0
        for bm in BENCHMARKS:
            if bm in speedups[sys_name] and speedups[sys_name][bm] > 0:
                w = workload[bm]["priority_weight"]
                log_sum += w * math.log(speedups[sys_name][bm])
                total_weight += w
        if total_weight > 0:
            composite_geom[sys_name] = math.exp(log_sum / total_weight)
        else:
            composite_geom[sys_name] = 0.0

    # Feasibility
    feasibility = {}
    for sys_name in SYSTEMS:
        spec = sys_specs[sys_name]
        nodes = spec["node_count"]
        total_cost = nodes * spec["cost_per_node_usd"]
        total_power = nodes * spec["power_per_node_kw"]

        budget_ok = total_cost <= budget
        power_ok = total_power <= power_limit

        perf_ok = True
        for bm in BENCHMARKS:
            if bm not in cleaned_perf[sys_name]:
                perf_ok = False
                break
            max_time = ref_times[bm] / perf_threshold
            if cleaned_perf[sys_name][bm]["median_time_s"] > max_time:
                perf_ok = False
                break

        feasibility[sys_name] = {
            "budget_ok": budget_ok,
            "power_ok": power_ok,
            "performance_ok": perf_ok,
            "feasible": budget_ok and power_ok and perf_ok,
        }

    feasible_systems = [s for s in SYSTEMS if feasibility[s]["feasible"]]

    # Cost-efficiency
    cost_millions = {}
    cost_efficiency_arith = {}
    cost_efficiency_geom = {}
    for sys_name in feasible_systems:
        spec = sys_specs[sys_name]
        cm = spec["node_count"] * spec["cost_per_node_usd"] / 1e6
        cost_millions[sys_name] = cm
        cost_efficiency_arith[sys_name] = composite_arith[sys_name] / cm
        cost_efficiency_geom[sys_name] = composite_geom[sys_name] / cm

    # Pareto optimal (minimize cost, maximize composite)
    def compute_pareto(composite_dict, cost_dict, sys_list):
        pareto = []
        for s in sys_list:
            dominated = False
            for t in sys_list:
                if t == s:
                    continue
                t_cost = cost_dict[t]
                s_cost = cost_dict[s]
                t_comp = composite_dict[t]
                s_comp = composite_dict[s]
                if (t_cost <= s_cost and t_comp >= s_comp and
                        (t_cost < s_cost or t_comp > s_comp)):
                    dominated = True
                    break
            if not dominated:
                pareto.append(s)
        return sorted(pareto)

    pareto_arith = compute_pareto(composite_arith, cost_millions, feasible_systems)
    pareto_geom = compute_pareto(composite_geom, cost_millions, feasible_systems)

    ranking_arith = sorted(
        feasible_systems, key=lambda s: cost_efficiency_arith[s], reverse=True
    )
    ranking_geom = sorted(
        feasible_systems, key=lambda s: cost_efficiency_geom[s], reverse=True
    )

    return {
        "cleaned_perf": cleaned_perf,
        "speedups": speedups,
        "composite_arith": composite_arith,
        "composite_geom": composite_geom,
        "feasibility": feasibility,
        "feasible_systems": feasible_systems,
        "pareto_arith": pareto_arith,
        "pareto_geom": pareto_geom,
        "cost_efficiency_arith": cost_efficiency_arith,
        "cost_efficiency_geom": cost_efficiency_geom,
        "ranking_arith": ranking_arith,
        "ranking_geom": ranking_geom,
        "recommendation_arith": ranking_arith[0] if ranking_arith else None,
        "recommendation_geom": ranking_geom[0] if ranking_geom else None,
    }


@pytest.fixture(scope="module")
def result():
    assert os.path.exists(RESULT_PATH), f"Output file {RESULT_PATH} does not exist"
    with open(RESULT_PATH) as f:
        return json.load(f)


def _get_field(data, *keys):
    """Try multiple possible field names, return first match."""
    for k in keys:
        if k in data:
            return data[k]
    return None


# ============================================================
# Structure tests
# ============================================================

class TestOutputStructure:
    def test_output_file_exists(self):
        assert os.path.exists(RESULT_PATH), "evaluation.json not found"

    def test_top_level_keys(self, result):
        required = {
            "cleaned_performance", "speedups", "composite_scores",
            "feasibility", "pareto_optimal", "cost_efficiency",
            "ranking", "recommendation"
        }
        actual = set(result.keys())
        missing = required - actual
        assert not missing, f"Missing top-level keys: {missing}"

    def test_all_systems_in_cleaned_performance(self, result):
        for sys_name in SYSTEMS:
            assert sys_name in result["cleaned_performance"], (
                f"Missing system {sys_name} in cleaned_performance"
            )

    def test_all_systems_in_feasibility(self, result):
        for sys_name in SYSTEMS:
            assert sys_name in result["feasibility"], (
                f"Missing system {sys_name} in feasibility"
            )


# ============================================================
# Cleaned performance tests
# ============================================================

class TestCleanedPerformance:
    @pytest.mark.parametrize("sys_name", ["pinnacle", "horizon", "vanguard", "summit_x"])
    @pytest.mark.parametrize("bm", BENCHMARKS)
    def test_median_time(self, result, expected, sys_name, bm):
        """Cleaned median time should match expected."""
        if bm not in expected["cleaned_perf"][sys_name]:
            pytest.skip(f"{sys_name} has no {bm} data")
        exp = expected["cleaned_perf"][sys_name][bm]["median_time_s"]
        got_data = result["cleaned_performance"][sys_name].get(bm, {})
        if not got_data:
            pytest.fail(f"Missing cleaned_performance entry for {sys_name}/{bm}")
        got = _get_field(got_data, "median_time_s", "median_time", "time_s",
                         "median", "representative_time_s")
        assert got is not None, f"Missing time field for {sys_name}/{bm}"
        assert math.isclose(got, exp, rel_tol=REL_TOL_TIGHT), (
            f"{sys_name}/{bm} median_time: got {got}, expected {exp}"
        )

    def test_nexus_missing_deep_train(self, result, expected):
        """Nexus should not have valid deep_train results."""
        nexus_data = result["cleaned_performance"].get("nexus", {})
        if "deep_train" in nexus_data:
            dt = nexus_data["deep_train"]
            if isinstance(dt, dict):
                time_val = _get_field(dt, "median_time_s", "median_time", "time_s",
                                      "median", "representative_time_s")
                if time_val is not None:
                    assert time_val == 0 or time_val is None, (
                        "Nexus deep_train should be missing/null/zero"
                    )

    def test_horizon_unit_conversion(self, result, expected):
        """Horizon times should be in seconds (not milliseconds)."""
        got_data = result["cleaned_performance"]["horizon"].get("stencil3d", {})
        got = _get_field(got_data, "median_time_s", "median_time", "time_s",
                         "median", "representative_time_s")
        assert got is not None, "Missing horizon stencil3d median"
        assert got < 100, (
            f"Horizon stencil3d median={got} — likely in ms, not seconds"
        )

    def test_summit_x_throughput_conversion(self, result, expected):
        """Summit_x times should be derived from throughput data."""
        exp = expected["cleaned_perf"]["summit_x"]["stencil3d"]["median_time_s"]
        got_data = result["cleaned_performance"]["summit_x"].get("stencil3d", {})
        got = _get_field(got_data, "median_time_s", "median_time", "time_s",
                         "median", "representative_time_s")
        assert got is not None, "Missing summit_x stencil3d median"
        assert math.isclose(got, exp, rel_tol=REL_TOL_TIGHT), (
            f"summit_x stencil3d: got {got}, expected {exp}"
        )


# ============================================================
# Speedup tests
# ============================================================

class TestSpeedups:
    @pytest.mark.parametrize("sys_name", ["pinnacle", "horizon", "vanguard", "summit_x"])
    @pytest.mark.parametrize("bm", BENCHMARKS)
    def test_speedup_value(self, result, expected, sys_name, bm):
        if bm not in expected["speedups"][sys_name]:
            pytest.skip(f"{sys_name} has no {bm}")
        exp = expected["speedups"][sys_name][bm]
        sys_speedups = result["speedups"].get(sys_name, {})
        got = sys_speedups.get(bm)
        assert got is not None, f"Missing speedup for {sys_name}/{bm}"
        assert math.isclose(got, exp, rel_tol=REL_TOL_TIGHT), (
            f"speedup[{sys_name}][{bm}]: got {got}, expected {exp}"
        )


# ============================================================
# Composite score tests
# ============================================================

class TestCompositeScores:
    @pytest.mark.parametrize("sys_name", ["pinnacle", "horizon", "vanguard", "summit_x"])
    def test_composite_score(self, result, expected, sys_name):
        got = result["composite_scores"].get(sys_name)
        if got is None:
            pytest.fail(f"Missing composite_scores for {sys_name}")
        exp_a = expected["composite_arith"][sys_name]
        exp_g = expected["composite_geom"][sys_name]
        ok = (math.isclose(got, exp_a, rel_tol=REL_TOL_LOOSE) or
              math.isclose(got, exp_g, rel_tol=REL_TOL_LOOSE))
        assert ok, (
            f"composite[{sys_name}]: got {got}, "
            f"expected ~{exp_a:.4f} (arithmetic) or ~{exp_g:.4f} (geometric)"
        )


# ============================================================
# Feasibility tests
# ============================================================

class TestFeasibility:
    @pytest.mark.parametrize("sys_name", SYSTEMS)
    def test_feasibility_verdict(self, result, expected, sys_name):
        exp_feasible = expected["feasibility"][sys_name]["feasible"]
        got_data = result["feasibility"][sys_name]
        got_feasible = _get_field(got_data, "feasible", "overall_feasible",
                                  "is_feasible", "overall")
        assert got_feasible is not None, f"Missing feasibility for {sys_name}"
        assert got_feasible == exp_feasible, (
            f"feasibility[{sys_name}]: got {got_feasible}, expected {exp_feasible}"
        )

    def test_nexus_infeasible(self, result):
        """Nexus should be infeasible (CPU-only, no deep_train)."""
        got = result["feasibility"]["nexus"]
        feasible = _get_field(got, "feasible", "overall_feasible", "is_feasible")
        assert feasible is False, "Nexus should be infeasible"

    def test_feasible_set(self, result, expected):
        """Correct set of systems should be feasible."""
        exp_feasible = set(expected["feasible_systems"])
        got_feasible = set()
        for sys_name in SYSTEMS:
            got_data = result["feasibility"][sys_name]
            if _get_field(got_data, "feasible", "overall_feasible", "is_feasible"):
                got_feasible.add(sys_name)
        assert got_feasible == exp_feasible, (
            f"Feasible set: got {got_feasible}, expected {exp_feasible}"
        )


# ============================================================
# Pareto optimality tests
# ============================================================

class TestParetoOptimal:
    def test_pareto_set(self, result, expected):
        got = sorted(result["pareto_optimal"])
        ok = (got == expected["pareto_arith"] or got == expected["pareto_geom"])
        assert ok, (
            f"pareto_optimal: got {got}, expected {expected['pareto_arith']} "
            f"or {expected['pareto_geom']}"
        )

    def test_pareto_subset_of_feasible(self, result, expected):
        """All Pareto-optimal systems should be feasible."""
        feasible = set(expected["feasible_systems"])
        for s in result["pareto_optimal"]:
            assert s in feasible, f"Pareto system {s} is not feasible"

    def test_pareto_nonempty(self, result):
        assert len(result["pareto_optimal"]) >= 1, "Pareto set should not be empty"


# ============================================================
# Ranking tests
# ============================================================

class TestRanking:
    def test_ranking_order(self, result, expected):
        got = result["ranking"]
        ok = (got == expected["ranking_arith"] or got == expected["ranking_geom"])
        assert ok, (
            f"ranking: got {got}, expected {expected['ranking_arith']} "
            f"or {expected['ranking_geom']}"
        )

    def test_ranking_only_feasible(self, result, expected):
        """Ranking should only contain feasible systems."""
        feasible = set(expected["feasible_systems"])
        for s in result["ranking"]:
            assert s in feasible, f"Ranked system {s} is not feasible"

    def test_ranking_length(self, result, expected):
        """Ranking should contain all feasible systems."""
        exp_len = len(expected["feasible_systems"])
        got_len = len(result["ranking"])
        assert got_len == exp_len, (
            f"Ranking length: got {got_len}, expected {exp_len}"
        )


# ============================================================
# Recommendation test
# ============================================================

class TestRecommendation:
    def test_recommendation(self, result, expected):
        got = result["recommendation"]
        valid = {expected["recommendation_arith"], expected["recommendation_geom"]}
        assert got in valid, (
            f"recommendation: got '{got}', expected one of {valid}"
        )


# ============================================================
# Consistency tests
# ============================================================

class TestConsistency:
    def test_recommendation_is_top_ranked(self, result):
        """Recommendation should be the top-ranked system."""
        assert result["recommendation"] == result["ranking"][0], (
            f"Recommendation '{result['recommendation']}' != "
            f"top-ranked '{result['ranking'][0]}'"
        )

    def test_pareto_includes_recommendation(self, result):
        """Recommended system should be Pareto-optimal."""
        assert result["recommendation"] in result["pareto_optimal"], (
            f"Recommendation '{result['recommendation']}' not in Pareto set"
        )

    def test_cost_efficiency_for_feasible(self, result, expected):
        """Cost efficiency should have entries for all feasible systems."""
        feasible = set(expected["feasible_systems"])
        ce_keys = set(result["cost_efficiency"].keys())
        missing = feasible - ce_keys
        assert not missing, f"cost_efficiency missing: {missing}"

    def test_speedups_positive(self, result):
        """All speedups should be positive."""
        for sys_name, bms in result["speedups"].items():
            for bm, val in bms.items():
                if isinstance(val, (int, float)):
                    assert val > 0, (
                        f"speedup[{sys_name}][{bm}] = {val} should be > 0"
                    )

    def test_summit_x_highest_composite(self, result, expected):
        """Summit_x should have the highest composite score among feasible."""
        feasible = expected["feasible_systems"]
        scores = {s: result["composite_scores"].get(s, 0) for s in feasible}
        best = max(scores, key=scores.get)
        assert best == "summit_x", (
            f"Expected summit_x to have highest composite, got {best}"
        )

    def test_horizon_dominated_by_pinnacle(self, result, expected):
        """Horizon should not be in the Pareto set (dominated by pinnacle)."""
        assert "horizon" not in result["pareto_optimal"], (
            "Horizon should be dominated by pinnacle (lower cost, higher composite)"
        )
