"""
Independent verification for stochastic facility location with tail-risk task.
Solves all required problems from scratch and compares with agent output.
"""

import csv
import json
import os
import shutil
import pytest
import pulp

_counter = [0]


def _ensure_data():
    """Ensure data files exist in /app/data/, copying from backup if needed."""
    if not os.path.exists("/app/data/facilities.csv"):
        os.makedirs("/app/data", exist_ok=True)
        if os.path.isdir("/opt/task_instance"):
            for fn in os.listdir("/opt/task_instance"):
                src = f"/opt/task_instance/{fn}"
                if os.path.isfile(src):
                    shutil.copy2(src, f"/app/data/{fn}")


def _load_instance():
    """Load instance data from CSV/JSON files in /app/data/."""
    _ensure_data()
    with open("/app/data/facilities.csv") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    n_fac = len(rows)
    f_costs = [float(r["fixed_cost"]) for r in rows]
    caps = [float(r["capacity"]) for r in rows]

    with open("/app/data/shipping_costs.csv") as f:
        reader = csv.DictReader(f)
        cust_cols = [c for c in reader.fieldnames if c != "facility_id"]
        t_costs = []
        for row in reader:
            t_costs.append([float(row[c]) for c in cust_cols])
    n_cust = len(cust_cols)

    with open("/app/data/demand_scenarios.csv") as f:
        reader = csv.DictReader(f)
        dem_cols = [c for c in reader.fieldnames if c != "scenario_id"]
        demands = []
        for row in reader:
            demands.append([float(row[c]) for c in dem_cols])
    n_scen = len(demands)

    with open("/app/data/parameters.json") as f:
        params = json.load(f)

    if params.get("scenario_weighting") == "equiprobable":
        probs = [1.0 / n_scen] * n_scen
    else:
        raise ValueError("Unknown scenario_weighting")

    return {
        "n_facilities": n_fac,
        "n_customers": n_cust,
        "n_scenarios": n_scen,
        "alpha": params["tail_quantile"],
        "risk_weight": params["risk_weight"],
        "unmet_penalty": params["shortage_penalty_per_unit"],
        "facility_costs": f_costs,
        "facility_capacities": caps,
        "transport_costs": t_costs,
        "demand_scenarios": demands,
        "scenario_probabilities": probs,
    }


def _solve_fl(n_fac, n_cust, f_costs, caps, t_costs, demands_list, probs_list,
              penalty, risk_weight=0.0, alpha=0.95, fixed_facilities=None):
    """Solve stochastic capacitated facility location (independent verifier)."""
    _counter[0] += 1
    p = f"v{_counter[0]}_"
    n_scen = len(demands_list)

    prob = pulp.LpProblem(f"V_{_counter[0]}", pulp.LpMinimize)

    y = [pulp.LpVariable(f"{p}y_{i}", cat="Binary") for i in range(n_fac)]

    if fixed_facilities is not None:
        for i in range(n_fac):
            if i in fixed_facilities:
                prob += y[i] == 1
            else:
                prob += y[i] == 0

    x = [[[pulp.LpVariable(f"{p}x_{i}_{j}_{s}", lowBound=0)
            for s in range(n_scen)]
           for j in range(n_cust)]
          for i in range(n_fac)]

    u = [[pulp.LpVariable(f"{p}u_{j}_{s}", lowBound=0)
          for s in range(n_scen)]
         for j in range(n_cust)]

    Q = []
    for s in range(n_scen):
        q = pulp.lpSum(t_costs[i][j] * x[i][j][s]
                       for i in range(n_fac) for j in range(n_cust)) \
            + penalty * pulp.lpSum(u[j][s] for j in range(n_cust))
        Q.append(q)

    fac_cost_expr = pulp.lpSum(f_costs[i] * y[i] for i in range(n_fac))
    exp_cost_expr = pulp.lpSum(probs_list[s] * Q[s] for s in range(n_scen))

    if risk_weight > 1e-12:
        eta = pulp.LpVariable(f"{p}eta")
        zv = [pulp.LpVariable(f"{p}z_{s}", lowBound=0) for s in range(n_scen)]
        cvar_expr = eta + (1.0 / (1.0 - alpha)) * pulp.lpSum(
            probs_list[s] * zv[s] for s in range(n_scen))
        prob += fac_cost_expr + (1.0 - risk_weight) * exp_cost_expr \
                + risk_weight * cvar_expr
        for s in range(n_scen):
            prob += zv[s] >= Q[s] - eta
    else:
        eta = None
        zv = None
        prob += fac_cost_expr + exp_cost_expr

    for i in range(n_fac):
        for s in range(n_scen):
            prob += pulp.lpSum(x[i][j][s] for j in range(n_cust)) <= caps[i] * y[i]

    for j in range(n_cust):
        for s in range(n_scen):
            prob += pulp.lpSum(x[i][j][s] for i in range(n_fac)) + u[j][s] >= demands_list[s][j]

    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=120)
    prob.solve(solver)
    assert prob.status == 1, f"Solver status {prob.status}"

    open_facs = sorted([i for i in range(n_fac) if pulp.value(y[i]) > 0.5])
    obj_val = pulp.value(prob.objective)

    sc_costs = []
    for s in range(n_scen):
        sc = sum(t_costs[i][j] * pulp.value(x[i][j][s])
                 for i in range(n_fac) for j in range(n_cust)) \
             + penalty * sum(pulp.value(u[j][s]) for j in range(n_cust))
        sc_costs.append(sc)

    fc = sum(f_costs[i] for i in open_facs)
    ec = sum(probs_list[s] * sc_costs[s] for s in range(n_scen))

    result = {
        "objective_value": obj_val,
        "facilities_open": open_facs,
        "facility_cost": fc,
        "expected_second_stage_cost": ec,
        "scenario_costs": sc_costs,
    }

    if risk_weight > 1e-12 and eta is not None:
        eta_v = pulp.value(eta)
        cvar_v = eta_v + (1.0 / (1.0 - alpha)) * sum(
            probs_list[s] * pulp.value(zv[s]) for s in range(n_scen))
        result["var_value"] = eta_v
        result["cvar_value"] = cvar_v

    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def instance():
    return _load_instance()


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference(instance):
    """Independently compute all reference values."""
    d = instance
    common = dict(n_fac=d["n_facilities"], n_cust=d["n_customers"],
                  f_costs=d["facility_costs"], caps=d["facility_capacities"],
                  t_costs=d["transport_costs"], penalty=d["unmet_penalty"])
    demands = d["demand_scenarios"]
    probs = d["scenario_probabilities"]
    n_scen = d["n_scenarios"]

    rp = _solve_fl(demands_list=demands, probs_list=probs,
                   risk_weight=0.0, **common)

    ra = _solve_fl(demands_list=demands, probs_list=probs,
                   risk_weight=d["risk_weight"], alpha=d["alpha"], **common)

    mean_dem = [[sum(demands[s][j] * probs[s] for s in range(n_scen))
                 for j in range(d["n_customers"])]]
    ev = _solve_fl(demands_list=mean_dem, probs_list=[1.0],
                   risk_weight=0.0, **common)
    eev = _solve_fl(demands_list=demands, probs_list=probs,
                    risk_weight=0.0,
                    fixed_facilities=set(ev["facilities_open"]), **common)
    vss = eev["objective_value"] - rp["objective_value"]

    ws_total = 0.0
    for s in range(n_scen):
        ws_s = _solve_fl(demands_list=[demands[s]], probs_list=[1.0],
                         risk_weight=0.0, **common)
        ws_total += probs[s] * ws_s["objective_value"]
    evpi = rp["objective_value"] - ws_total

    return {"rp": rp, "ra": ra, "vss": vss, "evpi": evpi}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rel_err(actual, expected, min_denom=1.0):
    return abs(actual - expected) / max(abs(expected), min_denom)


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_risk_neutral_present(self, results):
        assert "risk_neutral" in results

    def test_risk_averse_present(self, results):
        assert "risk_averse" in results

    def test_vss_present(self, results):
        assert "vss" in results

    def test_evpi_present(self, results):
        assert "evpi" in results

    def test_risk_neutral_keys(self, results):
        rn = results["risk_neutral"]
        for key in ["objective_value", "facilities_open", "facility_cost",
                     "expected_second_stage_cost", "scenario_costs"]:
            assert key in rn, f"Missing risk_neutral.{key}"

    def test_risk_averse_keys(self, results):
        ra = results["risk_averse"]
        for key in ["objective_value", "facilities_open", "facility_cost",
                     "expected_second_stage_cost", "var_value", "cvar_value",
                     "scenario_costs"]:
            assert key in ra, f"Missing risk_averse.{key}"

    def test_scenario_counts(self, results, instance):
        n = instance["n_scenarios"]
        assert len(results["risk_neutral"]["scenario_costs"]) == n
        assert len(results["risk_averse"]["scenario_costs"]) == n


# ---------------------------------------------------------------------------
# Risk-neutral tests
# ---------------------------------------------------------------------------

class TestRiskNeutral:
    def test_objective(self, results, reference):
        assert rel_err(results["risk_neutral"]["objective_value"],
                       reference["rp"]["objective_value"]) < 0.005

    def test_facility_cost_consistent(self, results, instance):
        rn = results["risk_neutral"]
        expected_fc = sum(instance["facility_costs"][i]
                         for i in rn["facilities_open"])
        assert abs(rn["facility_cost"] - expected_fc) < 0.01

    def test_expected_cost_consistent(self, results, instance):
        rn = results["risk_neutral"]
        probs = instance["scenario_probabilities"]
        recomputed = sum(probs[s] * rn["scenario_costs"][s]
                         for s in range(instance["n_scenarios"]))
        assert rel_err(rn["expected_second_stage_cost"], recomputed) < 0.005

    def test_objective_decomposition(self, results):
        rn = results["risk_neutral"]
        recomputed = rn["facility_cost"] + rn["expected_second_stage_cost"]
        assert rel_err(rn["objective_value"], recomputed) < 0.005


# ---------------------------------------------------------------------------
# Risk-averse tests
# ---------------------------------------------------------------------------

class TestRiskAverse:
    def test_objective(self, results, reference):
        assert rel_err(results["risk_averse"]["objective_value"],
                       reference["ra"]["objective_value"]) < 0.005

    def test_cvar_value(self, results, reference):
        assert rel_err(results["risk_averse"]["cvar_value"],
                       reference["ra"]["cvar_value"]) < 0.01

    def test_var_value(self, results, reference):
        assert rel_err(results["risk_averse"]["var_value"],
                       reference["ra"]["var_value"], min_denom=10.0) < 0.02

    def test_facility_cost_consistent(self, results, instance):
        ra = results["risk_averse"]
        expected_fc = sum(instance["facility_costs"][i]
                         for i in ra["facilities_open"])
        assert abs(ra["facility_cost"] - expected_fc) < 0.01

    def test_cvar_geq_var(self, results):
        ra = results["risk_averse"]
        assert ra["cvar_value"] >= ra["var_value"] - 0.01

    def test_risk_averse_geq_risk_neutral(self, results):
        assert results["risk_averse"]["objective_value"] >= \
               results["risk_neutral"]["objective_value"] - 0.01

    def test_objective_decomposition(self, results, instance):
        ra = results["risk_averse"]
        lam = instance["risk_weight"]
        recomputed = ra["facility_cost"] \
                     + (1.0 - lam) * ra["expected_second_stage_cost"] \
                     + lam * ra["cvar_value"]
        assert rel_err(ra["objective_value"], recomputed) < 0.005


# ---------------------------------------------------------------------------
# VSS / EVPI tests
# ---------------------------------------------------------------------------

class TestVSSEVPI:
    def test_vss_value(self, results, reference):
        assert rel_err(results["vss"], reference["vss"], min_denom=1.0) < 0.02

    def test_evpi_value(self, results, reference):
        assert rel_err(results["evpi"], reference["evpi"], min_denom=1.0) < 0.02

    def test_vss_nonneg(self, results):
        assert results["vss"] >= -0.1, \
            f"VSS should be >= 0, got {results['vss']}"

    def test_evpi_nonneg(self, results):
        assert results["evpi"] >= -0.1, \
            f"EVPI should be >= 0, got {results['evpi']}"
