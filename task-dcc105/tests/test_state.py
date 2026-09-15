
import pytest
import json
import csv
import os
import math


def enthalpy(T, a=4.18, b=0.00062):
    return a * T + b * T ** 2


def parse_reconciled_csv(filepath):
    results = {}
    with open(filepath, "r") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        for row in reader:
            if not row or not row[0].strip():
                continue
            name = row[0].strip()
            results[name] = {
                "measured": float(row[1].strip()),
                "reconciled": float(row[2].strip()),
                "measured_hwci": float(row[3].strip()),
                "reconciled_hwci": float(row[4].strip()),
                "local_test_value": float(row[5].strip()),
                "local_test_result": row[6].strip().upper(),
            }
    return results


EXPECTED_VARS = [
    "m1", "m2", "m3", "m4", "m5", "m6",
    "m7", "m8", "m9", "m10", "m11", "m12",
    "T1", "T2", "T3", "T7", "T8", "T9", "T10", "T11",
]

# m3 has bias +2.5 kg/s, m12 has bias +2.8 kg/s
FAULTY_SENSORS = {"m3", "m12"}

NON_FAULTY = [v for v in EXPECTED_VARS if v not in FAULTY_SENSORS]


class TestOutputFilesExist:
    def test_reconciled_values_csv_exists(self):
        assert os.path.exists("/app/reconciled_values.csv"), (
            "reconciled_values.csv not found"
        )

    def test_test_results_json_exists(self):
        assert os.path.exists("/app/test_results.json"), (
            "test_results.json not found"
        )


class TestReconciledCSVFormat:
    def test_has_all_variables(self):
        results = parse_reconciled_csv("/app/reconciled_values.csv")
        for v in EXPECTED_VARS:
            assert v in results, f"Variable {v} missing from reconciled_values.csv"

    def test_has_twenty_data_rows(self):
        results = parse_reconciled_csv("/app/reconciled_values.csv")
        assert len(results) == 20, f"Expected 20 variables, got {len(results)}"

    def test_measured_values_match_input(self):
        results = parse_reconciled_csv("/app/reconciled_values.csv")
        expected_measured = {
            "m1": 25.32, "m2": 14.87, "m3": 42.50, "m4": 15.18,
            "m5": 11.85, "m6": 13.22, "m7": 15.09, "m8": 12.15,
            "m9": 12.88, "m10": 2.08, "m11": 42.35, "m12": 44.80,
            "T1": 180.6, "T2": 174.3, "T3": 178.5, "T7": 80.4,
            "T8": 89.5, "T9": 85.3, "T10": 20.2, "T11": 81.2,
        }
        for v, expected in expected_measured.items():
            actual = results[v]["measured"]
            assert abs(actual - expected) < 0.01, (
                f"Measured value for {v}: expected {expected}, got {actual}"
            )


class TestMassBalanceConstraints:
    """Reconciled values must satisfy all mass balance equations."""

    def test_constraint_1_boiler_header(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        residual = r["m1"]["reconciled"] + r["m2"]["reconciled"] - r["m3"]["reconciled"]
        assert abs(residual) < 0.01, f"m1+m2-m3 = {residual}"

    def test_constraint_2_distributor(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        residual = (
            r["m3"]["reconciled"]
            - r["m4"]["reconciled"]
            - r["m5"]["reconciled"]
            - r["m6"]["reconciled"]
        )
        assert abs(residual) < 0.01, f"m3-m4-m5-m6 = {residual}"

    def test_constraint_3_process_a(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        residual = r["m4"]["reconciled"] - r["m7"]["reconciled"]
        assert abs(residual) < 0.01, f"m4-m7 = {residual}"

    def test_constraint_4_process_b(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        residual = r["m5"]["reconciled"] - r["m8"]["reconciled"]
        assert abs(residual) < 0.01, f"m5-m8 = {residual}"

    def test_constraint_5_process_c(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        residual = r["m6"]["reconciled"] - r["m9"]["reconciled"]
        assert abs(residual) < 0.01, f"m6-m9 = {residual}"

    def test_constraint_6_return_header(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        residual = (
            r["m7"]["reconciled"]
            + r["m8"]["reconciled"]
            + r["m9"]["reconciled"]
            + r["m10"]["reconciled"]
            - r["m11"]["reconciled"]
        )
        assert abs(residual) < 0.01, f"m7+m8+m9+m10-m11 = {residual}"

    def test_constraint_7_pump(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        residual = r["m11"]["reconciled"] - r["m12"]["reconciled"]
        assert abs(residual) < 0.01, f"m11-m12 = {residual}"


class TestEnergyBalanceConstraints:
    """Reconciled values must satisfy nonlinear energy balance equations."""

    def test_constraint_8_boiler_header_energy(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        m1 = r["m1"]["reconciled"]
        m2 = r["m2"]["reconciled"]
        m3 = r["m3"]["reconciled"]
        T1 = r["T1"]["reconciled"]
        T2 = r["T2"]["reconciled"]
        T3 = r["T3"]["reconciled"]
        residual = m1 * enthalpy(T1) + m2 * enthalpy(T2) - m3 * enthalpy(T3)
        assert abs(residual) < 1.0, (
            f"Energy balance at boiler header residual = {residual}"
        )

    def test_constraint_9_return_header_energy(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        m7 = r["m7"]["reconciled"]
        m8 = r["m8"]["reconciled"]
        m9 = r["m9"]["reconciled"]
        m10 = r["m10"]["reconciled"]
        m11 = r["m11"]["reconciled"]
        T7 = r["T7"]["reconciled"]
        T8 = r["T8"]["reconciled"]
        T9 = r["T9"]["reconciled"]
        T10 = r["T10"]["reconciled"]
        T11 = r["T11"]["reconciled"]
        residual = (
            m7 * enthalpy(T7)
            + m8 * enthalpy(T8)
            + m9 * enthalpy(T9)
            + m10 * enthalpy(T10)
            - m11 * enthalpy(T11)
        )
        assert abs(residual) < 1.0, (
            f"Energy balance at return header residual = {residual}"
        )


class TestFaultySensorDetection:
    """m3 (biased +2.5 kg/s) and m12 (biased +2.8 kg/s) must be detected."""

    def test_m3_flagged_as_faulty(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        assert r["m3"]["local_test_result"] == "FALSE", (
            f"m3 should fail local test (faulty). "
            f"Test value = {r['m3']['local_test_value']}"
        )

    def test_m12_flagged_as_faulty(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        assert r["m12"]["local_test_result"] == "FALSE", (
            f"m12 should fail local test (faulty). "
            f"Test value = {r['m12']['local_test_value']}"
        )

    def test_m3_local_test_exceeds_threshold(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        assert r["m3"]["local_test_value"] > 1.96, (
            f"m3 local test = {r['m3']['local_test_value']}, expected > 1.96"
        )

    def test_m12_local_test_exceeds_threshold(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        assert r["m12"]["local_test_value"] > 1.96, (
            f"m12 local test = {r['m12']['local_test_value']}, expected > 1.96"
        )

    def test_m3_reconciled_corrected_toward_true(self):
        """Reconciled m3 should be near 40.0 (true), not 42.50 (measured)."""
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        m3 = r["m3"]["reconciled"]
        assert abs(m3 - 40.0) < 1.5, (
            f"Reconciled m3 = {m3}, expected near 40.0"
        )

    def test_m12_reconciled_corrected_toward_true(self):
        """Reconciled m12 should be near 42.0 (true), not 44.80 (measured)."""
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        m12 = r["m12"]["reconciled"]
        assert abs(m12 - 42.0) < 1.5, (
            f"Reconciled m12 = {m12}, expected near 42.0"
        )


class TestNonFaultySensors:
    """All 18 non-faulty sensors must pass the local test."""

    def test_non_faulty_sensors_pass(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        for v in NON_FAULTY:
            assert r[v]["local_test_result"] == "TRUE", (
                f"Non-faulty sensor {v} incorrectly flagged. "
                f"Test value = {r[v]['local_test_value']}"
            )


class TestUncertaintyReduction:
    """Reconciled HWCI must be no larger than measured HWCI."""

    def test_reconciled_hwci_not_increased(self):
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        for v in EXPECTED_VARS:
            rec = r[v]["reconciled_hwci"]
            meas = r[v]["measured_hwci"]
            assert rec <= meas + 1e-6, (
                f"{v}: reconciled HWCI {rec} > measured HWCI {meas}"
            )

    def test_some_uncertainties_actually_reduced(self):
        """At least half of reconciled HWCIs should be strictly smaller."""
        r = parse_reconciled_csv("/app/reconciled_values.csv")
        reduced_count = sum(
            1 for v in EXPECTED_VARS
            if r[v]["reconciled_hwci"] < r[v]["measured_hwci"] - 1e-6
        )
        assert reduced_count >= 10, (
            f"Only {reduced_count}/20 uncertainties reduced, expected >= 10"
        )


class TestGlobalTestAndJSON:
    def test_json_has_global_test(self):
        with open("/app/test_results.json") as f:
            data = json.load(f)
        gt = data["global_test"]
        assert "J_star" in gt
        assert "chi_square_critical" in gt
        assert "degrees_of_freedom" in gt
        assert "result" in gt

    def test_degrees_of_freedom_is_nine(self):
        with open("/app/test_results.json") as f:
            data = json.load(f)
        assert data["global_test"]["degrees_of_freedom"] == 9

    def test_chi_square_critical_value(self):
        with open("/app/test_results.json") as f:
            data = json.load(f)
        crit = data["global_test"]["chi_square_critical"]
        assert abs(crit - 16.919) < 0.1, (
            f"chi2(9,0.95) should be ~16.919, got {crit}"
        )

    def test_faulty_sensors_in_json(self):
        with open("/app/test_results.json") as f:
            data = json.load(f)
        faulty = set(data["faulty_sensors"])
        assert "m3" in faulty, f"m3 not in faulty_sensors: {faulty}"
        assert "m12" in faulty, f"m12 not in faulty_sensors: {faulty}"

    def test_no_false_positives_in_json(self):
        with open("/app/test_results.json") as f:
            data = json.load(f)
        faulty = set(data["faulty_sensors"])
        unexpected = faulty - FAULTY_SENSORS
        assert len(unexpected) == 0, (
            f"Unexpected sensors flagged as faulty: {unexpected}"
        )

    def test_convergence(self):
        with open("/app/test_results.json") as f:
            data = json.load(f)
        assert data["converged"] is True, "Algorithm did not converge"

    def test_j_star_positive(self):
        with open("/app/test_results.json") as f:
            data = json.load(f)
        assert data["global_test"]["J_star"] > 0, "J* should be positive"
