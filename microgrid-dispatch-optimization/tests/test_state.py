
import json
import os
import pytest
from pulp import *


def load_data():
    with open("/app/data/microgrid_stochastic.json") as f:
        return json.load(f)


def solve_reference_rp():
    """Independently solve the stochastic MILP to get reference metrics."""
    data = load_data()
    T = data["planning_horizon_hours"]
    S = data["num_scenarios"]
    sp = data["system"]
    rp = data["risk_parameters"]
    scens = data["scenarios"]
    a, lam = rp["alpha"], rp["risk_weight"]
    px, py = sp["electrolyzer_pwl_input_kw"], sp["electrolyzer_pwl_output_kwh"]
    K = len(px) - 1
    probs = [scens[s]["probability"] for s in range(S)]
    fci = 1.0 / sp["fuel_cell_efficiency"]
    dg = sp["battery_degradation_cost_per_kwh"]
    dr = sp["demand_charge_rate"]

    m = LpProblem("ref", LpMinimize)

    eon = [LpVariable(f"re{t}", cat="Binary") for t in range(T)]

    so = {}; wi = {}; bc = {}; bd = {}; bs = {}
    gi = {}; ge = {}; fc = {}; h2 = {}
    ei = {}; hp = {}; sw = {}; sl = {}; pk = {}

    for s in range(S):
        ts = scens[s]["time_series"]
        pk[s] = LpVariable(f"rpk{s}", 0)
        for t in range(T):
            so[t, s] = LpVariable(f"rso{t}_{s}", 0, sp["solar_capacity_kw"] * ts[t]["solar_cf"])
            wi[t, s] = LpVariable(f"rwi{t}_{s}", 0, sp["wind_capacity_kw"] * ts[t]["wind_cf"])
            bc[t, s] = LpVariable(f"rbc{t}_{s}", 0, sp["battery_max_power_kw"])
            bd[t, s] = LpVariable(f"rbd{t}_{s}", 0, sp["battery_max_power_kw"])
            bs[t, s] = LpVariable(f"rbs{t}_{s}", 0, sp["battery_capacity_kwh"])
            gi[t, s] = LpVariable(f"rgi{t}_{s}", 0, sp["grid_import_max_kw"])
            ge[t, s] = LpVariable(f"rge{t}_{s}", 0, sp["grid_export_max_kw"])
            fc[t, s] = LpVariable(f"rfc{t}_{s}", 0, sp["fuel_cell_max_output_kw"])
            h2[t, s] = LpVariable(f"rh2{t}_{s}", 0, sp["h2_tank_capacity_kwh"])
            ei[t, s] = LpVariable(f"rei{t}_{s}", 0, sp["electrolyzer_max_input_kw"])
            hp[t, s] = LpVariable(f"rhp{t}_{s}", 0)
            for k in range(K):
                sw[t, s, k] = LpVariable(f"rsw{t}_{s}_{k}", cat="Binary")
                sl[t, s, k] = LpVariable(f"rsl{t}_{s}_{k}", 0, 1)

    eta = LpVariable("reta")
    u = [LpVariable(f"ru{s}", 0) for s in range(S)]

    c = {}
    for s in range(S):
        ts = scens[s]["time_series"]
        c[s] = (
            lpSum(ts[t]["grid_import_price"] * gi[t, s] - ts[t]["grid_export_price"] * ge[t, s]
                  for t in range(T))
            + dr * pk[s]
            + dg * lpSum(bc[t, s] + bd[t, s] for t in range(T))
        )

    m += (1 - lam) * lpSum(probs[s] * c[s] for s in range(S)) + lam * (
        eta + lpSum(probs[s] * u[s] for s in range(S)) / (1 - a)
    )

    for s in range(S):
        m += u[s] >= c[s] - eta

    for s in range(S):
        ts = scens[s]["time_series"]
        for t in range(T):
            m += (so[t, s] + wi[t, s] + bd[t, s] + fc[t, s] + gi[t, s]
                  == ts[t]["demand_kw"] + bc[t, s] + ei[t, s] + ge[t, s])
            ps = sp["battery_initial_soc_kwh"] if t == 0 else bs[t - 1, s]
            m += bs[t, s] == ps + sp["battery_charge_efficiency"] * bc[t, s] - bd[t, s]
            ph = sp["h2_initial_level_kwh"] if t == 0 else h2[t - 1, s]
            m += h2[t, s] == ph + hp[t, s] - fci * fc[t, s]
            m += pk[s] >= gi[t, s]
            if t >= 1:
                m += gi[t, s] - gi[t - 1, s] <= sp["grid_ramp_rate_kw_per_hour"]
                m += gi[t - 1, s] - gi[t, s] <= sp["grid_ramp_rate_kw_per_hour"]
            m += ((sp["grid_import_max_kw"] - gi[t, s])
                  + (sp["battery_max_power_kw"] - bd[t, s])
                  >= sp["reserve_fraction"] * ts[t]["demand_kw"])
            m += lpSum(sw[t, s, k] for k in range(K)) == eon[t]
            for k in range(K):
                m += sl[t, s, k] <= sw[t, s, k]
            m += ei[t, s] == lpSum(
                px[k] * sw[t, s, k] + (px[k + 1] - px[k]) * sl[t, s, k] for k in range(K))
            m += hp[t, s] == lpSum(
                py[k] * sw[t, s, k] + (py[k + 1] - py[k]) * sl[t, s, k] for k in range(K))
        m += bs[T - 1, s] >= sp["battery_initial_soc_kwh"]
        m += h2[T - 1, s] >= sp["h2_initial_level_kwh"]

    mu, md = sp["electrolyzer_min_uptime_hours"], sp["electrolyzer_min_downtime_hours"]
    ist = sp["electrolyzer_initial_state"]
    for t in range(T):
        prev = ist if t == 0 else eon[t - 1]
        for j in range(1, mu):
            if t + j < T:
                m += eon[t + j] >= eon[t] - prev
        for j in range(1, md):
            if t + j < T:
                m += eon[t + j] <= 1 - (prev - eon[t])

    m.solve(PULP_CBC_CMD(msg=0, gapRel=0.005, timeLimit=150))
    assert m.status == 1, f"Reference solve failed: {LpStatus[m.status]}"

    sc = [value(c[s]) for s in range(S)]
    ec = sum(probs[s] * sc[s] for s in range(S))
    cv = value(eta) + sum(probs[s] * value(u[s]) for s in range(S)) / (1 - a)

    rf = []
    for s in range(S):
        ts = scens[s]["time_series"]
        td = sum(ts[t]["demand_kw"] for t in range(T))
        tr = sum(value(so[t, s]) + value(wi[t, s]) for t in range(T))
        rf.append(tr / td if td > 0 else 0)

    return {
        "stochastic_objective": value(m.objective),
        "expected_cost": ec,
        "cvar_cost": cv,
        "var_cost": value(eta),
        "worst_scenario_cost": max(sc),
        "best_scenario_cost": min(sc),
        "total_electrolyzer_on_hours": sum(int(round(value(eon[t]))) for t in range(T)),
        "expected_renewable_fraction": sum(probs[s] * rf[s] for s in range(S)),
    }


@pytest.fixture(scope="module")
def reference():
    return solve_reference_rp()


@pytest.fixture(scope="module")
def agent():
    path = "/app/results/solution.json"
    assert os.path.exists(path), f"Solution file not found at {path}"
    with open(path) as f:
        return json.load(f)


class TestSolutionFormat:
    def test_file_exists(self):
        assert os.path.exists("/app/results/solution.json"), "solution.json not found"

    def test_valid_json(self):
        with open("/app/results/solution.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    REQUIRED = [
        "stochastic_objective", "expected_cost", "cvar_cost", "var_cost",
        "ev_objective", "eev_cost", "vss", "worst_scenario_cost",
        "best_scenario_cost", "total_electrolyzer_on_hours",
        "expected_renewable_fraction",
    ]

    def test_all_keys_present(self, agent):
        for key in self.REQUIRED:
            assert key in agent, f"Missing required key: {key}"

    def test_values_are_numeric(self, agent):
        for key in self.REQUIRED:
            val = agent[key]
            assert isinstance(val, (int, float)), f"{key} must be numeric, got {type(val)}"


class TestStructuralInvariants:
    """Properties that must hold for ANY correct solution, regardless of solver."""

    def test_objective_decomposition(self, agent):
        """stochastic_objective == (1-lambda)*expected_cost + lambda*cvar_cost."""
        data = load_data()
        lam = data["risk_parameters"]["risk_weight"]
        expected_obj = (1 - lam) * agent["expected_cost"] + lam * agent["cvar_cost"]
        rel_err = abs(agent["stochastic_objective"] - expected_obj) / max(abs(expected_obj), 1)
        assert rel_err < 0.02, (
            f"Objective decomposition error: "
            f"obj={agent['stochastic_objective']:.2f}, "
            f"(1-lam)*E+lam*CVaR={expected_obj:.2f}, err={rel_err:.4f}"
        )

    def test_var_leq_cvar(self, agent):
        """VaR <= CVaR always holds."""
        assert agent["var_cost"] <= agent["cvar_cost"] + 1.0, (
            f"VaR ({agent['var_cost']:.2f}) > CVaR ({agent['cvar_cost']:.2f})"
        )

    def test_vss_nonnegative(self, agent):
        """VSS should be non-negative (stochastic programming should help or tie)."""
        assert agent["vss"] >= -2.0, f"VSS should be >= 0, got {agent['vss']:.2f}"

    def test_vss_equals_difference(self, agent):
        """VSS must equal eev_cost - expected_cost."""
        expected_vss = agent["eev_cost"] - agent["expected_cost"]
        assert abs(agent["vss"] - expected_vss) < 1.0, (
            f"VSS ({agent['vss']:.2f}) != eev-exp ({expected_vss:.2f})"
        )

    def test_eev_geq_expected(self, agent):
        """EEV expected cost >= stochastic expected cost."""
        assert agent["eev_cost"] >= agent["expected_cost"] - 2.0, (
            f"EEV ({agent['eev_cost']:.2f}) < expected ({agent['expected_cost']:.2f})"
        )

    def test_worst_geq_expected(self, agent):
        """Worst scenario cost >= expected cost."""
        assert agent["worst_scenario_cost"] >= agent["expected_cost"] - 1.0

    def test_best_leq_expected(self, agent):
        """Best scenario cost <= expected cost."""
        assert agent["best_scenario_cost"] <= agent["expected_cost"] + 1.0

    def test_worst_geq_best(self, agent):
        assert agent["worst_scenario_cost"] >= agent["best_scenario_cost"] - 0.1

    def test_renewable_fraction_bounds(self, agent):
        assert 0 <= agent["expected_renewable_fraction"] <= 1.0

    def test_electrolyzer_hours_bounds(self, agent):
        data = load_data()
        T = data["planning_horizon_hours"]
        h = agent["total_electrolyzer_on_hours"]
        assert isinstance(h, int), f"total_electrolyzer_on_hours must be int, got {type(h)}"
        assert 0 <= h <= T, f"ON hours {h} out of range [0, {T}]"

    def test_positive_costs(self, agent):
        """All cost metrics should be positive for this problem setup."""
        assert agent["expected_cost"] > 0, "Expected cost should be positive"
        assert agent["worst_scenario_cost"] > 0, "Worst cost should be positive"
        assert agent["ev_objective"] > 0, "EV objective should be positive"


class TestOptimality:
    """Compare agent solution to independently computed reference."""

    def test_objective_matches_reference(self, agent, reference):
        rel_err = abs(agent["stochastic_objective"] - reference["stochastic_objective"]) / max(
            abs(reference["stochastic_objective"]), 1
        )
        assert rel_err < 0.03, (
            f"Stochastic objective mismatch: agent={agent['stochastic_objective']:.2f}, "
            f"ref={reference['stochastic_objective']:.2f}, rel_err={rel_err:.4f}"
        )

    def test_expected_cost_matches_reference(self, agent, reference):
        rel_err = abs(agent["expected_cost"] - reference["expected_cost"]) / max(
            abs(reference["expected_cost"]), 1
        )
        assert rel_err < 0.03, (
            f"Expected cost mismatch: agent={agent['expected_cost']:.2f}, "
            f"ref={reference['expected_cost']:.2f}, rel_err={rel_err:.4f}"
        )

    def test_cvar_matches_reference(self, agent, reference):
        rel_err = abs(agent["cvar_cost"] - reference["cvar_cost"]) / max(
            abs(reference["cvar_cost"]), 1
        )
        assert rel_err < 0.05, (
            f"CVaR mismatch: agent={agent['cvar_cost']:.2f}, "
            f"ref={reference['cvar_cost']:.2f}, rel_err={rel_err:.4f}"
        )

    def test_worst_scenario_near_reference(self, agent, reference):
        rel_err = abs(agent["worst_scenario_cost"] - reference["worst_scenario_cost"]) / max(
            abs(reference["worst_scenario_cost"]), 1
        )
        assert rel_err < 0.10, (
            f"Worst scenario mismatch: agent={agent['worst_scenario_cost']:.2f}, "
            f"ref={reference['worst_scenario_cost']:.2f}, rel_err={rel_err:.4f}"
        )

    def test_renewable_fraction_near_reference(self, agent, reference):
        diff = abs(agent["expected_renewable_fraction"] - reference["expected_renewable_fraction"])
        assert diff < 0.05, (
            f"Renewable fraction mismatch: agent={agent['expected_renewable_fraction']:.4f}, "
            f"ref={reference['expected_renewable_fraction']:.4f}, diff={diff:.4f}"
        )


class TestEVAndVSS:
    """Verify the EV/VSS computation is consistent."""

    def test_ev_objective_positive(self, agent):
        assert agent["ev_objective"] > 0, "EV objective should be positive"

    def test_ev_leq_expected(self, agent):
        """EV objective (deterministic mean) should generally be <= expected stochastic cost."""
        assert agent["ev_objective"] <= agent["expected_cost"] + 5.0, (
            f"EV objective ({agent['ev_objective']:.2f}) unexpectedly higher "
            f"than stochastic expected cost ({agent['expected_cost']:.2f})"
        )

    def test_vss_magnitude_reasonable(self, agent):
        """VSS should be a modest fraction of expected cost (not astronomically large)."""
        if agent["expected_cost"] > 10:
            ratio = agent["vss"] / agent["expected_cost"]
            assert ratio < 0.30, (
                f"VSS ({agent['vss']:.2f}) is {ratio:.1%} of expected cost - "
                f"suspiciously large"
            )
