
import json
import os
import csv
import pytest


def load_analysis():
    path = "/app/results/analysis.json"
    assert os.path.isfile(path), f"Output file not found at {path}"
    with open(path) as f:
        return json.load(f)


def load_network():
    with open("/app/data/network.json") as f:
        return json.load(f)


def load_config():
    with open("/app/data/config.json") as f:
        return json.load(f)


def load_demands():
    rows = []
    with open("/app/data/demand_scenarios.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Reference values (pre-computed via two-stage stochastic MILP with CVaR)
# ---------------------------------------------------------------------------

# Cost-minimizing solution (lambda=0, no risk control)
REF_CM_OPENED = [0, 1, 2, 3]
REF_CM_TOTAL_COST = 3264.0015
REF_CM_EXPECTED_TRANSPORT = 3034.0015
REF_CM_FIXED = 230

# Risk-aware solution (lambda=0.5, alpha=0.95)
REF_RA_OPENED = [0, 1, 2, 3, 5]
REF_RA_TOTAL_COST = 5410.9896
REF_RA_EXPECTED_TRANSPORT = 2898.5596
REF_RA_FIXED = 380
REF_RA_TAIL_RISK = 4264.86
REF_RA_RISK_THRESHOLD = 4172.07

# Comparison
REF_FACILITIES_DIFFER = True
REF_ADDITIONAL = [5]
REF_COST_CHANGE_PCT = -4.4641  # expected transport cost DECREASES
REF_TAIL_RISK_CHANGE_PCT = -21.4468  # tail risk DECREASES (negative = reduction)


class TestOutputStructure:
    """Verify the output file exists and has required top-level keys."""

    def test_output_file_exists(self):
        assert os.path.isfile("/app/results/analysis.json")

    def test_top_level_keys(self):
        sol = load_analysis()
        for key in ["cost_minimizing", "risk_aware", "comparison"]:
            assert key in sol, f"Missing top-level key: {key}"

    def test_cost_minimizing_fields(self):
        sol = load_analysis()
        cm = sol["cost_minimizing"]
        for f in ["opened_facilities", "total_cost", "expected_transport_cost", "fixed_cost"]:
            assert f in cm, f"cost_minimizing missing field: {f}"

    def test_risk_aware_fields(self):
        sol = load_analysis()
        ra = sol["risk_aware"]
        for f in ["opened_facilities", "total_cost", "expected_transport_cost",
                   "fixed_cost", "tail_risk_value", "risk_threshold"]:
            assert f in ra, f"risk_aware missing field: {f}"

    def test_comparison_fields(self):
        sol = load_analysis()
        cmp = sol["comparison"]
        for f in ["facilities_differ", "additional_facilities_in_risk_plan",
                   "expected_cost_change_pct", "tail_risk_change_pct"]:
            assert f in cmp, f"comparison missing field: {f}"


class TestCostMinimizing:
    """Verify the cost-minimizing (risk-neutral) solution."""

    def test_opened_facilities(self):
        sol = load_analysis()
        opened = sorted(sol["cost_minimizing"]["opened_facilities"])
        assert opened == REF_CM_OPENED, (
            f"Expected {REF_CM_OPENED}, got {opened}"
        )

    def test_total_cost(self):
        sol = load_analysis()
        val = sol["cost_minimizing"]["total_cost"]
        rel_err = abs(val - REF_CM_TOTAL_COST) / REF_CM_TOTAL_COST
        assert rel_err < 0.01, (
            f"Total cost {val} differs from {REF_CM_TOTAL_COST} by {rel_err*100:.2f}%"
        )

    def test_expected_transport_cost(self):
        sol = load_analysis()
        val = sol["cost_minimizing"]["expected_transport_cost"]
        rel_err = abs(val - REF_CM_EXPECTED_TRANSPORT) / REF_CM_EXPECTED_TRANSPORT
        assert rel_err < 0.01, (
            f"Expected transport {val} differs from {REF_CM_EXPECTED_TRANSPORT} by {rel_err*100:.2f}%"
        )

    def test_fixed_cost(self):
        sol = load_analysis()
        val = sol["cost_minimizing"]["fixed_cost"]
        assert abs(val - REF_CM_FIXED) < 1, (
            f"Fixed cost {val} != expected {REF_CM_FIXED}"
        )

    def test_cost_decomposition(self):
        """fixed + expected_transport should equal total_cost for risk-neutral."""
        sol = load_analysis()
        cm = sol["cost_minimizing"]
        reconstructed = cm["fixed_cost"] + cm["expected_transport_cost"]
        rel_err = abs(reconstructed - cm["total_cost"]) / cm["total_cost"]
        assert rel_err < 0.01, (
            f"Cost decomposition failed: {cm['fixed_cost']} + {cm['expected_transport_cost']} "
            f"= {reconstructed} vs {cm['total_cost']}"
        )


class TestRiskAware:
    """Verify the risk-aware solution."""

    def test_opened_facilities(self):
        sol = load_analysis()
        opened = sorted(sol["risk_aware"]["opened_facilities"])
        assert opened == REF_RA_OPENED, (
            f"Expected {REF_RA_OPENED}, got {opened}"
        )

    def test_total_cost(self):
        sol = load_analysis()
        val = sol["risk_aware"]["total_cost"]
        rel_err = abs(val - REF_RA_TOTAL_COST) / REF_RA_TOTAL_COST
        assert rel_err < 0.01, (
            f"Total cost {val} differs from {REF_RA_TOTAL_COST} by {rel_err*100:.2f}%"
        )

    def test_expected_transport_cost(self):
        sol = load_analysis()
        val = sol["risk_aware"]["expected_transport_cost"]
        rel_err = abs(val - REF_RA_EXPECTED_TRANSPORT) / REF_RA_EXPECTED_TRANSPORT
        assert rel_err < 0.01, (
            f"Expected transport {val} differs from {REF_RA_EXPECTED_TRANSPORT} by {rel_err*100:.2f}%"
        )

    def test_fixed_cost(self):
        sol = load_analysis()
        val = sol["risk_aware"]["fixed_cost"]
        assert abs(val - REF_RA_FIXED) < 1, (
            f"Fixed cost {val} != expected {REF_RA_FIXED}"
        )

    def test_tail_risk_value(self):
        sol = load_analysis()
        val = sol["risk_aware"]["tail_risk_value"]
        rel_err = abs(val - REF_RA_TAIL_RISK) / REF_RA_TAIL_RISK
        assert rel_err < 0.01, (
            f"Tail risk {val} differs from {REF_RA_TAIL_RISK} by {rel_err*100:.2f}%"
        )

    def test_risk_threshold(self):
        sol = load_analysis()
        val = sol["risk_aware"]["risk_threshold"]
        rel_err = abs(val - REF_RA_RISK_THRESHOLD) / REF_RA_RISK_THRESHOLD
        assert rel_err < 0.01, (
            f"Risk threshold {val} differs from {REF_RA_RISK_THRESHOLD} by {rel_err*100:.2f}%"
        )

    def test_tail_risk_geq_threshold(self):
        """Tail risk should be >= the threshold (CVaR >= VaR)."""
        sol = load_analysis()
        ra = sol["risk_aware"]
        assert ra["tail_risk_value"] >= ra["risk_threshold"] - 1.0, (
            f"Tail risk {ra['tail_risk_value']} < threshold {ra['risk_threshold']}"
        )

    def test_risk_aware_opens_more(self):
        """Risk-aware solution should open at least as many facilities."""
        sol = load_analysis()
        cm_count = len(sol["cost_minimizing"]["opened_facilities"])
        ra_count = len(sol["risk_aware"]["opened_facilities"])
        assert ra_count >= cm_count, (
            f"Risk-aware opens {ra_count} facilities vs cost-minimizing {cm_count}"
        )


class TestComparison:
    """Verify the comparison section."""

    def test_facilities_differ(self):
        sol = load_analysis()
        assert sol["comparison"]["facilities_differ"] == REF_FACILITIES_DIFFER

    def test_additional_facilities(self):
        sol = load_analysis()
        additional = sorted(sol["comparison"]["additional_facilities_in_risk_plan"])
        assert additional == REF_ADDITIONAL, (
            f"Expected additional facilities {REF_ADDITIONAL}, got {additional}"
        )

    def test_expected_cost_change_direction(self):
        """Risk-aware expected transport cost should be lower (negative change)."""
        sol = load_analysis()
        pct = sol["comparison"]["expected_cost_change_pct"]
        assert pct < 0, (
            f"Expected cost change should be negative (reduction), got {pct}%"
        )

    def test_expected_cost_change_magnitude(self):
        sol = load_analysis()
        pct = sol["comparison"]["expected_cost_change_pct"]
        assert abs(pct - REF_COST_CHANGE_PCT) < 2.0, (
            f"Expected cost change {pct}% differs from {REF_COST_CHANGE_PCT}% by more than 2pp"
        )

    def test_tail_risk_change_direction(self):
        """Tail risk should decrease (negative change) in risk-aware plan."""
        sol = load_analysis()
        pct = sol["comparison"]["tail_risk_change_pct"]
        assert pct < -5, (
            f"Tail risk change should show significant reduction (< -5%), got {pct}%"
        )

    def test_tail_risk_change_magnitude(self):
        sol = load_analysis()
        pct = sol["comparison"]["tail_risk_change_pct"]
        assert abs(pct - REF_TAIL_RISK_CHANGE_PCT) < 5.0, (
            f"Tail risk change {pct}% differs from {REF_TAIL_RISK_CHANGE_PCT}% by more than 5pp"
        )


class TestFeasibility:
    """Verify basic feasibility constraints."""

    def test_cm_budget(self):
        sol = load_analysis()
        config = load_config()
        opened = sol["cost_minimizing"]["opened_facilities"]
        net = load_network()
        total = sum(net["facilities"]["opening_costs"][j] for j in opened)
        assert total <= config["capital_budget"], (
            f"Cost-minimizing fixed cost {total} exceeds budget {config['capital_budget']}"
        )

    def test_ra_budget(self):
        sol = load_analysis()
        config = load_config()
        opened = sol["risk_aware"]["opened_facilities"]
        net = load_network()
        total = sum(net["facilities"]["opening_costs"][j] for j in opened)
        assert total <= config["capital_budget"], (
            f"Risk-aware fixed cost {total} exceeds budget {config['capital_budget']}"
        )

    def test_valid_facility_indices(self):
        sol = load_analysis()
        net = load_network()
        n_fac = net["facilities"]["count"]
        for plan_name in ["cost_minimizing", "risk_aware"]:
            opened = sol[plan_name]["opened_facilities"]
            for j in opened:
                assert 0 <= j < n_fac, (
                    f"{plan_name}: facility index {j} out of range [0, {n_fac})"
                )

    def test_cm_objective_consistency(self):
        """Risk-neutral total cost = fixed + expected transport."""
        sol = load_analysis()
        cm = sol["cost_minimizing"]
        expected = cm["fixed_cost"] + cm["expected_transport_cost"]
        assert abs(expected - cm["total_cost"]) / cm["total_cost"] < 0.02

    def test_ra_objective_decomposition(self):
        """Risk-aware total = fixed + expected_transport + weight * tail_risk_value."""
        sol = load_analysis()
        ra = sol["risk_aware"]
        config = load_config()
        weight = config["risk_cost_weight"]
        reconstructed = ra["fixed_cost"] + ra["expected_transport_cost"] + weight * ra["tail_risk_value"]
        rel_err = abs(reconstructed - ra["total_cost"]) / ra["total_cost"]
        assert rel_err < 0.02, (
            f"Risk-aware objective decomposition: {ra['fixed_cost']} + {ra['expected_transport_cost']} "
            f"+ {weight} * {ra['tail_risk_value']} = {reconstructed} vs {ra['total_cost']}, "
            f"err {rel_err*100:.2f}%"
        )
