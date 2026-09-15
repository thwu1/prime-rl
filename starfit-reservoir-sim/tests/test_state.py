
import csv
import json
import math
import os

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

M3PS_TO_MCM_DAY = 86400.0 / 1e6


def read_cascade_csv(filepath):
    """Read cascade results CSV grouped by reservoir_id."""
    results = {0: [], 1: [], 2: []}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            res_id = int(row["reservoir_id"])
            entry = {"date": row["date"]}
            for k, v in row.items():
                if k not in ("date", "reservoir_id"):
                    entry[k] = float(v)
            results[res_id].append(entry)
    return results


def read_routed_csv(filepath):
    """Read routed flows CSV grouped by reach_id."""
    results = {0: [], 1: []}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            reach_id = int(row["reach_id"])
            entry = {"date": row["date"]}
            for k, v in row.items():
                if k not in ("date", "reach_id"):
                    entry[k] = float(v)
            results[reach_id].append(entry)
    return results


def read_performance():
    with open("/app/output/performance.json") as f:
        return json.load(f)


def read_cascade_params():
    import netCDF4 as nc
    ds = nc.Dataset("/app/data/cascade.nc", "r")
    init = [float(x) for x in ds.variables["initial_storage_MCM"][:]]
    caps = [float(x) for x in ds.variables["GRanD_CAP_MCM"][:]]
    demand = float(ds.getncattr("demand_target_cms"))
    lateral = []
    for r in range(3):
        lateral.append([float(x) for x in ds.variables["inflow_cms"][r, :]])
    ds.close()
    return init, caps, demand, lateral


# ---------------------------------------------------------------------------
# Tests: Output file existence
# ---------------------------------------------------------------------------

class TestOutputFiles:
    def test_cascade_independent_csv(self):
        assert os.path.exists("/app/output/cascade_independent.csv"), \
            "cascade_independent.csv missing"

    def test_cascade_coordinated_csv(self):
        assert os.path.exists("/app/output/cascade_coordinated.csv"), \
            "cascade_coordinated.csv missing"

    def test_routed_flows_independent_csv(self):
        assert os.path.exists("/app/output/routed_flows_independent.csv"), \
            "routed_flows_independent.csv missing"

    def test_routed_flows_coordinated_csv(self):
        assert os.path.exists("/app/output/routed_flows_coordinated.csv"), \
            "routed_flows_coordinated.csv missing"

    def test_performance_json(self):
        assert os.path.exists("/app/output/performance.json"), \
            "performance.json missing"


# ---------------------------------------------------------------------------
# Tests: CSV format
# ---------------------------------------------------------------------------

class TestCascadeFormat:
    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    def test_row_count(self, policy):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        for res_id in [0, 1, 2]:
            assert len(results[res_id]) == 730, (
                f"Reservoir {res_id} ({policy}): expected 730 rows, "
                f"got {len(results[res_id])}"
            )

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    def test_required_columns(self, policy):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        required = {
            "date", "storage_MCM", "release_cms", "spill_cms",
            "outflow_cms", "availability_status", "total_inflow_cms",
        }
        for row in results[0][:1]:
            missing = required - set(row.keys())
            assert not missing, f"Missing columns: {missing}"


# ---------------------------------------------------------------------------
# Tests: Per-reservoir mass balance
# ---------------------------------------------------------------------------

class TestPerReservoirMassBalance:
    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("res_id", [0, 1, 2])
    def test_mass_balance(self, policy, res_id):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        init_storage, caps, _, _ = read_cascade_params()

        res = results[res_id]
        total_in = sum(r["total_inflow_cms"] * M3PS_TO_MCM_DAY for r in res)
        total_out = sum(r["outflow_cms"] * M3PS_TO_MCM_DAY for r in res)
        ds = res[-1]["storage_MCM"] - init_storage[res_id]

        err = abs(total_in - total_out - ds)
        rel_err = err / total_in if total_in > 0 else 0
        assert rel_err < 1e-8, (
            f"Mass balance error for reservoir {res_id} ({policy}): "
            f"{rel_err:.2e}"
        )


# ---------------------------------------------------------------------------
# Tests: Daily mass balance per reservoir
# ---------------------------------------------------------------------------

class TestDailyMassBalance:
    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("res_id", [0, 1, 2])
    def test_daily_balance(self, policy, res_id):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        init_storage, _, _, _ = read_cascade_params()

        res = results[res_id]
        prev_storage = init_storage[res_id]

        for i, row in enumerate(res):
            in_mcm = row["total_inflow_cms"] * M3PS_TO_MCM_DAY
            out_mcm = row["outflow_cms"] * M3PS_TO_MCM_DAY
            delta = row["storage_MCM"] - prev_storage

            err = abs(in_mcm - out_mcm - delta)
            assert err < 1e-8, (
                f"Daily mass balance error on {row['date']} for "
                f"reservoir {res_id} ({policy}): {err:.2e}"
            )
            prev_storage = row["storage_MCM"]


# ---------------------------------------------------------------------------
# Tests: Storage bounds
# ---------------------------------------------------------------------------

class TestStorageBounds:
    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("res_id", [0, 1, 2])
    def test_non_negative_storage(self, policy, res_id):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        for row in results[res_id]:
            assert row["storage_MCM"] >= -1e-12, (
                f"Negative storage for res {res_id} on {row['date']}: "
                f"{row['storage_MCM']}"
            )

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("res_id", [0, 1, 2])
    def test_storage_within_capacity(self, policy, res_id):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        _, caps, _, _ = read_cascade_params()
        for row in results[res_id]:
            assert row["storage_MCM"] <= caps[res_id] + 1e-10, (
                f"Storage exceeds capacity for res {res_id} on "
                f"{row['date']}: {row['storage_MCM']:.6f} > {caps[res_id]}"
            )


# ---------------------------------------------------------------------------
# Tests: Spill consistency
# ---------------------------------------------------------------------------

class TestSpillConsistency:
    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("res_id", [0, 1, 2])
    def test_spill_implies_full(self, policy, res_id):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        _, caps, _, _ = read_cascade_params()
        for row in results[res_id]:
            if row["spill_cms"] > 1e-12:
                assert abs(row["storage_MCM"] - caps[res_id]) < 1e-8, (
                    f"Spill without full storage for res {res_id} on "
                    f"{row['date']}: storage={row['storage_MCM']:.6f}, "
                    f"cap={caps[res_id]}"
                )


# ---------------------------------------------------------------------------
# Tests: Outflow decomposition
# ---------------------------------------------------------------------------

class TestOutflowDecomposition:
    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("res_id", [0, 1, 2])
    def test_outflow_equals_release_plus_spill(self, policy, res_id):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        for row in results[res_id]:
            expected = row["release_cms"] + row["spill_cms"]
            assert abs(row["outflow_cms"] - expected) < 1e-10, (
                f"outflow != release + spill for res {res_id} on "
                f"{row['date']}: {row['outflow_cms']} != {expected}"
            )


# ---------------------------------------------------------------------------
# Tests: Non-negative flows
# ---------------------------------------------------------------------------

class TestNonNegativeFlows:
    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("res_id", [0, 1, 2])
    def test_release(self, policy, res_id):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        for row in results[res_id]:
            assert row["release_cms"] >= -1e-12, (
                f"Negative release for res {res_id} on {row['date']}"
            )

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("res_id", [0, 1, 2])
    def test_outflow(self, policy, res_id):
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        for row in results[res_id]:
            assert row["outflow_cms"] >= -1e-12, (
                f"Negative outflow for res {res_id} on {row['date']}"
            )


# ---------------------------------------------------------------------------
# Tests: Routing volume conservation and physics
# ---------------------------------------------------------------------------

class TestRoutingVolume:
    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("reach_id", [0, 1])
    def test_volume_conservation(self, policy, reach_id):
        """Total routed volume should approximately equal input volume."""
        routed = read_routed_csv(
            f"/app/output/routed_flows_{policy}.csv"
        )
        total_in = sum(
            r["inflow_cms"] * M3PS_TO_MCM_DAY for r in routed[reach_id]
        )
        total_out = sum(
            r["outflow_cms"] * M3PS_TO_MCM_DAY for r in routed[reach_id]
        )
        rel_diff = abs(total_in - total_out) / total_in if total_in > 0 else 0
        assert rel_diff < 0.01, (
            f"Routing volume imbalance for reach {reach_id} ({policy}): "
            f"{rel_diff:.4f}"
        )

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("reach_id", [0, 1])
    def test_non_negative_routed_flow(self, policy, reach_id):
        routed = read_routed_csv(
            f"/app/output/routed_flows_{policy}.csv"
        )
        for row in routed[reach_id]:
            assert row["outflow_cms"] >= -1e-12, (
                f"Negative routed flow for reach {reach_id} on "
                f"{row['date']}"
            )

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("reach_id", [0, 1])
    def test_routing_attenuation(self, policy, reach_id):
        """Peak routed outflow should not exceed peak inflow."""
        routed = read_routed_csv(
            f"/app/output/routed_flows_{policy}.csv"
        )
        peak_in = max(r["inflow_cms"] for r in routed[reach_id])
        peak_out = max(r["outflow_cms"] for r in routed[reach_id])
        assert peak_out <= peak_in + 1e-6, (
            f"Routing amplification for reach {reach_id}: "
            f"peak_out={peak_out:.4f} > peak_in={peak_in:.4f}"
        )

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    @pytest.mark.parametrize("reach_id", [0, 1])
    def test_routed_row_count(self, policy, reach_id):
        routed = read_routed_csv(
            f"/app/output/routed_flows_{policy}.csv"
        )
        assert len(routed[reach_id]) == 730, (
            f"Reach {reach_id} ({policy}): expected 730 rows, "
            f"got {len(routed[reach_id])}"
        )


# ---------------------------------------------------------------------------
# Tests: Performance metrics
# ---------------------------------------------------------------------------

class TestPerformanceMetrics:
    def test_required_keys(self):
        perf = read_performance()
        for policy in ["independent", "coordinated"]:
            assert policy in perf, f"Missing policy '{policy}'"
            required = {
                "reliability", "resilience", "vulnerability",
                "system_mass_balance_relative_error",
            }
            missing = required - set(perf[policy].keys())
            assert not missing, f"Missing keys for {policy}: {missing}"

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    def test_reliability_range(self, policy):
        perf = read_performance()
        r = perf[policy]["reliability"]
        assert 0.0 <= r <= 1.0, f"Reliability out of range: {r}"

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    def test_resilience_range(self, policy):
        perf = read_performance()
        r = perf[policy]["resilience"]
        assert 0.0 <= r <= 1.0, f"Resilience out of range: {r}"

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    def test_vulnerability_range(self, policy):
        perf = read_performance()
        v = perf[policy]["vulnerability"]
        assert 0.0 <= v <= 1.0, f"Vulnerability out of range: {v}"

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    def test_system_mass_balance(self, policy):
        perf = read_performance()
        err = perf[policy]["system_mass_balance_relative_error"]
        assert err < 1e-6, (
            f"System mass balance error for {policy}: {err:.2e}"
        )

    def test_coordinated_reliability_at_least_independent(self):
        perf = read_performance()
        r_ind = perf["independent"]["reliability"]
        r_coord = perf["coordinated"]["reliability"]
        assert r_coord >= r_ind, (
            f"Coordinated reliability ({r_coord:.4f}) should be >= "
            f"independent ({r_ind:.4f})"
        )

    def test_coordinated_vulnerability_not_worse(self):
        perf = read_performance()
        v_ind = perf["independent"]["vulnerability"]
        v_coord = perf["coordinated"]["vulnerability"]
        assert v_coord <= v_ind + 0.01, (
            f"Coordinated vulnerability ({v_coord:.4f}) should be <= "
            f"independent ({v_ind:.4f}) + 0.01"
        )


# ---------------------------------------------------------------------------
# Tests: Cascade inflow consistency
# ---------------------------------------------------------------------------

class TestCascadeConsistency:
    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    def test_reservoir1_inflow_matches_lateral_plus_routed(self, policy):
        """Reservoir 1 total inflow = lateral_1 + routed from reach 0."""
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        routed = read_routed_csv(
            f"/app/output/routed_flows_{policy}.csv"
        )
        _, _, _, lateral = read_cascade_params()

        for i, (res_row, route_row) in enumerate(
            zip(results[1], routed[0])
        ):
            expected = lateral[1][i] + route_row["outflow_cms"]
            assert abs(res_row["total_inflow_cms"] - expected) < 1e-8, (
                f"Reservoir 1 inflow mismatch on {res_row['date']}: "
                f"got {res_row['total_inflow_cms']:.6f}, "
                f"expected {expected:.6f}"
            )

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    def test_reservoir2_inflow_matches_lateral_plus_routed(self, policy):
        """Reservoir 2 total inflow = lateral_2 + routed from reach 1."""
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        routed = read_routed_csv(
            f"/app/output/routed_flows_{policy}.csv"
        )
        _, _, _, lateral = read_cascade_params()

        for i, (res_row, route_row) in enumerate(
            zip(results[2], routed[1])
        ):
            expected = lateral[2][i] + route_row["outflow_cms"]
            assert abs(res_row["total_inflow_cms"] - expected) < 1e-8, (
                f"Reservoir 2 inflow mismatch on {res_row['date']}: "
                f"got {res_row['total_inflow_cms']:.6f}, "
                f"expected {expected:.6f}"
            )

    @pytest.mark.parametrize("policy", ["independent", "coordinated"])
    def test_reservoir0_inflow_matches_lateral(self, policy):
        """Reservoir 0 total inflow = lateral_0 (no upstream)."""
        results = read_cascade_csv(f"/app/output/cascade_{policy}.csv")
        _, _, _, lateral = read_cascade_params()

        for i, row in enumerate(results[0]):
            assert abs(row["total_inflow_cms"] - lateral[0][i]) < 1e-8, (
                f"Reservoir 0 inflow mismatch on {row['date']}: "
                f"got {row['total_inflow_cms']:.6f}, "
                f"expected {lateral[0][i]:.6f}"
            )
