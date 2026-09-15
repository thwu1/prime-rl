"""
Tests for two-stage robust chemical production planning.

"""

import json
import itertools
import numpy as np
import pyomo.environ as pyo
import pytest

SOLVER = pyo.SolverFactory("appsi_highs")

# ---------------------------------------------------------------------------
# Load data fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def problem():
    with open("/app/data/problem.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def z_max(problem):
    unc = problem["uncertainty"]
    return {
        "z1": unc["z_reactor"]["max_deviation"],
        "z2": unc["z_separator"]["max_deviation"],
        "z3": unc["z_lab"]["max_deviation"],
        "z4": unc["z_demand_C1"]["max_deviation"],
        "z5": unc["z_demand_C2"]["max_deviation"],
    }


# ---------------------------------------------------------------------------
# Helper: evaluate second-stage LP for given x and z
# ---------------------------------------------------------------------------
def eval_stage2(x_val, z, prob):
    products = prob["products"]
    base_rev = prob["base_revenue"]
    pr = prob["processing_cost"]["reactor"]
    ps = prob["processing_cost"]["separator"]
    fu = prob["feedstock_usage"]
    res = prob["resources"]
    md = prob["max_demand"]
    ct = prob["contracts"]
    z1, z2, z3, z4, z5 = z["z1"], z["z2"], z["z3"], z["z4"], z["z5"]

    rev = {
        p: base_rev[p] - pr[p] * (1 + z1) - ps[p] * (1 + z2)
        for p in products
    }

    m = pyo.ConcreteModel()
    m.y1 = pyo.Var(domain=pyo.NonNegativeReals)
    m.y2 = pyo.Var(domain=pyo.NonNegativeReals)
    m.y3 = pyo.Var(domain=pyo.NonNegativeReals)
    m.y4 = pyo.Var(domain=pyo.NonNegativeReals)
    m.yP = pyo.Var(domain=pyo.NonNegativeReals)

    yvars = [m.y1, m.y2, m.y3, m.y4]

    m.obj = pyo.Objective(expr=m.yP, sense=pyo.maximize)
    m.profit = pyo.Constraint(
        expr=sum(rev[products[i]] * yvars[i] for i in range(4)) >= m.yP
    )
    m.d1 = pyo.Constraint(expr=m.y1 >= ct["C1"]["min_demand_nominal"] * (1 + z4))
    m.d2 = pyo.Constraint(expr=m.y2 >= ct["C2"]["min_demand_nominal"] * (1 + z5))
    m.mx1 = pyo.Constraint(expr=m.y1 <= md["C1"])
    m.mx2 = pyo.Constraint(expr=m.y2 <= md["C2"])
    m.mx3 = pyo.Constraint(expr=m.y3 <= md["C3"])

    rc = res["reactor"]["consumption"]
    m.reactor = pyo.Constraint(
        expr=(1 + z1) * sum(rc[products[i]] * yvars[i] for i in range(4))
        <= res["reactor"]["capacity"]
    )
    sc = res["separator"]["consumption"]
    m.separator = pyo.Constraint(
        expr=(1 + z2) * sum(sc[products[i]] * yvars[i] for i in range(4))
        <= res["separator"]["capacity"]
    )
    lc = res["lab"]["consumption"]
    m.lab = pyo.Constraint(
        expr=(1 + z3) * sum(lc[products[i]] * yvars[i] for i in range(4))
        <= res["lab"]["capacity"]
    )
    m.feed = pyo.Constraint(
        expr=sum(fu[products[i]] * yvars[i] for i in range(4)) <= x_val
    )

    r = SOLVER.solve(m, tee=False)
    if r.solver.termination_condition == pyo.TerminationCondition.optimal:
        return pyo.value(m.yP)
    return float("-inf")


# ---------------------------------------------------------------------------
# Helper: compute worst-case total profit for a given x
# ---------------------------------------------------------------------------
def worst_case_for_x(x_val, z_max_dict, gamma, prob, n_random=2000, seed=77777):
    zkeys = list(z_max_dict.keys())
    fc = prob["feedstock_unit_cost"]
    worst = float("inf")

    # Extreme points: choose 3 of 5 at max deviation, all sign combos
    for active in itertools.combinations(range(5), 3):
        for signs in itertools.product([-1, 1], repeat=3):
            z = {zk: 0.0 for zk in zkeys}
            for idx, s in zip(active, signs):
                z[zkeys[idx]] = s * z_max_dict[zkeys[idx]]
            p = eval_stage2(x_val, z, prob)
            total = -fc * x_val + p
            worst = min(worst, total)

    # Random samples
    rng = np.random.default_rng(seed)
    for _ in range(n_random):
        while True:
            z = {zk: z_max_dict[zk] * rng.uniform(-1, 1) for zk in zkeys}
            if sum(abs(z[zk]) / z_max_dict[zk] for zk in zkeys) <= gamma:
                break
        p = eval_stage2(x_val, z, prob)
        total = -fc * x_val + p
        worst = min(worst, total)

    return worst


# ---------------------------------------------------------------------------
# Helper: run a reference CCG
# ---------------------------------------------------------------------------
def reference_ccg(prob, z_max_dict, gamma, tol=0.5, max_iter=50):
    """Independent CCG implementation for reference comparison."""
    products = prob["products"]
    base_rev = prob["base_revenue"]
    pr = prob["processing_cost"]["reactor"]
    ps = prob["processing_cost"]["separator"]
    fu = prob["feedstock_usage"]
    fc = prob["feedstock_unit_cost"]
    res = prob["resources"]
    md = prob["max_demand"]
    ct = prob["contracts"]
    zkeys = list(z_max_dict.keys())

    def _net_rev(z1, z2):
        return {
            p: base_rev[p] - pr[p] * (1 + z1) - ps[p] * (1 + z2) for p in products
        }

    def _build_master(Z_s):
        m = pyo.ConcreteModel()
        m.x = pyo.Var(domain=pyo.NonNegativeReals)
        m.tau = pyo.Var(domain=pyo.Reals)
        m.SC = pyo.Set(initialize=range(len(Z_s)))
        yn = ["y1", "y2", "y3", "y4", "yP"]
        m.YV = pyo.Set(initialize=yn)

        @m.Block(m.SC)
        def blk(b, s):
            z = Z_s[s]
            rv = _net_rev(z["z1"], z["z2"])
            b.y = pyo.Var(b.model().YV, domain=pyo.NonNegativeReals)
            b.tb = pyo.Constraint(expr=b.y["yP"] >= b.model().tau)
            b.pd = pyo.Constraint(
                expr=sum(rv[products[i]] * b.y[f"y{i+1}"] for i in range(4))
                >= b.y["yP"]
            )
            b.d1 = pyo.Constraint(
                expr=b.y["y1"] >= ct["C1"]["min_demand_nominal"] * (1 + z["z4"])
            )
            b.d2 = pyo.Constraint(
                expr=b.y["y2"] >= ct["C2"]["min_demand_nominal"] * (1 + z["z5"])
            )
            b.m1 = pyo.Constraint(expr=b.y["y1"] <= md["C1"])
            b.m2 = pyo.Constraint(expr=b.y["y2"] <= md["C2"])
            b.m3 = pyo.Constraint(expr=b.y["y3"] <= md["C3"])
            rc = res["reactor"]["consumption"]
            b.rc = pyo.Constraint(
                expr=(1 + z["z1"])
                * sum(rc[products[i]] * b.y[f"y{i+1}"] for i in range(4))
                <= res["reactor"]["capacity"]
            )
            sc = res["separator"]["consumption"]
            b.sc = pyo.Constraint(
                expr=(1 + z["z2"])
                * sum(sc[products[i]] * b.y[f"y{i+1}"] for i in range(4))
                <= res["separator"]["capacity"]
            )
            lc = res["lab"]["consumption"]
            b.lc = pyo.Constraint(
                expr=(1 + z["z3"])
                * sum(lc[products[i]] * b.y[f"y{i+1}"] for i in range(4))
                <= res["lab"]["capacity"]
            )
            b.fd = pyo.Constraint(
                expr=sum(fu[products[i]] * b.y[f"y{i+1}"] for i in range(4))
                <= b.model().x
            )

        @m.Objective(sense=pyo.maximize)
        def obj(m):
            return -fc * m.x + m.tau

        return m

    def _build_pess(sols):
        m = pyo.ConcreteModel()
        BM = 50000.0
        m.ZI = pyo.Set(initialize=zkeys)
        m.SC = pyo.Set(initialize=range(len(sols)))
        m.z = pyo.Var(m.ZI, domain=pyo.Reals)
        m.za = pyo.Var(m.ZI, domain=pyo.NonNegativeReals)
        m.theta = pyo.Var(domain=pyo.Reals)
        for zk in zkeys:
            m.z[zk].setlb(-z_max_dict[zk])
            m.z[zk].setub(z_max_dict[zk])

        @m.Constraint(m.ZI)
        def ap(m, zk):
            return m.z[zk] <= m.za[zk]

        @m.Constraint(m.ZI)
        def an(m, zk):
            return -m.z[zk] <= m.za[zk]

        m.bgt = pyo.Constraint(
            expr=sum(m.za[zk] / z_max_dict[zk] for zk in zkeys) <= gamma
        )
        ctypes = ["profit", "dem1", "dem2", "reactor", "separator", "lab"]
        np_keys = [k for k in ctypes if k != "profit"]

        @m.Block(m.SC)
        def sblk(b, s):
            d = sols[s]
            y1, y2, y3, y4, yP = d["y1"], d["y2"], d["y3"], d["y4"], d["yP"]
            rc = res["reactor"]["consumption"]
            scc = res["separator"]["consumption"]
            lcc = res["lab"]["consumption"]
            SR = sum(rc[products[i]] * d[f"y{i+1}"] for i in range(4))
            SS = sum(scc[products[i]] * d[f"y{i+1}"] for i in range(4))
            SL = sum(lcc[products[i]] * d[f"y{i+1}"] for i in range(4))
            nr0 = _net_rev(0, 0)
            L = {
                "profit": {
                    "z1": pr["C1"]*y1 + pr["C2"]*y2 + pr["C3"]*y3 + pr["C4"]*y4,
                    "z2": ps["C1"]*y1 + ps["C2"]*y2 + ps["C3"]*y3 + ps["C4"]*y4,
                    "z3": 0, "z4": 0, "z5": 0,
                },
                "dem1": {"z1": 0, "z2": 0, "z3": 0,
                         "z4": ct["C1"]["min_demand_nominal"], "z5": 0},
                "dem2": {"z1": 0, "z2": 0, "z3": 0, "z4": 0,
                         "z5": ct["C2"]["min_demand_nominal"]},
                "reactor": {"z1": SR, "z2": 0, "z3": 0, "z4": 0, "z5": 0},
                "separator": {"z1": 0, "z2": SS, "z3": 0, "z4": 0, "z5": 0},
                "lab": {"z1": 0, "z2": 0, "z3": SL, "z4": 0, "z5": 0},
            }
            R = {
                "profit": sum(nr0[products[i]] * d[f"y{i+1}"] for i in range(4)) - yP,
                "dem1": y1 - ct["C1"]["min_demand_nominal"],
                "dem2": y2 - ct["C2"]["min_demand_nominal"],
                "reactor": res["reactor"]["capacity"] - SR,
                "separator": res["separator"]["capacity"] - SS,
                "lab": res["lab"]["capacity"] - SL,
            }
            b.u = pyo.Var(ctypes, domain=pyo.Binary)
            b.al = pyo.Constraint(
                expr=sum(b.u[k] for k in np_keys) <= len(np_keys) - 1
            )

            @b.Constraint(ctypes)
            def vl(b, k):
                return (
                    sum(L[k][zk] * b.model().z[zk] for zk in zkeys)
                    - b.model().theta
                    >= R[k] - b.u[k] * BM
                )

        @m.Objective(sense=pyo.maximize)
        def obj(m):
            return m.theta

        return m

    # Run CCG
    Z_list = [{"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}]
    for it in range(max_iter):
        mm = _build_master(Z_list)
        SOLVER.solve(mm)
        obj_val = pyo.value(mm.obj)
        x_v = pyo.value(mm.x)
        sols = []
        for s in range(len(Z_list)):
            sols.append({
                "x": x_v,
                "y1": pyo.value(mm.blk[s].y["y1"]),
                "y2": pyo.value(mm.blk[s].y["y2"]),
                "y3": pyo.value(mm.blk[s].y["y3"]),
                "y4": pyo.value(mm.blk[s].y["y4"]),
                "yP": pyo.value(mm.blk[s].y["yP"]),
            })
        mp = _build_pess(sols)
        SOLVER.solve(mp)
        th = pyo.value(mp.theta)
        if th < tol:
            return x_v, obj_val
        Z_list.append({zk: pyo.value(mp.z[zk]) for zk in zkeys})
    return x_v, obj_val


# ===========================================================================
# Test: output file structure
# ===========================================================================
class TestStructure:
    def test_file_exists(self, results):
        assert results is not None

    def test_robust_keys(self, results):
        assert "robust_optimal_objective" in results
        assert "robust_first_stage_x" in results
        assert "robust_iterations" in results

    def test_stochastic_keys(self, results):
        assert "stochastic_optimal_objective" in results
        assert "stochastic_first_stage_x" in results

    def test_types(self, results):
        assert isinstance(results["robust_optimal_objective"], (int, float))
        assert isinstance(results["robust_first_stage_x"], (int, float))
        assert isinstance(results["robust_iterations"], (int, float))
        assert isinstance(results["stochastic_optimal_objective"], (int, float))
        assert isinstance(results["stochastic_first_stage_x"], (int, float))

    def test_positive_values(self, results):
        assert results["robust_optimal_objective"] > 0
        assert results["robust_first_stage_x"] > 0
        assert results["stochastic_optimal_objective"] > 0
        assert results["stochastic_first_stage_x"] > 0

    def test_robust_converged(self, results):
        assert int(results["robust_iterations"]) > 0
        assert int(results["robust_iterations"]) < 50


# ===========================================================================
# Test: robust solution correctness via independent worst-case evaluation
# ===========================================================================
class TestRobustCorrectness:
    def test_worst_case_matches_reported(self, results, problem, z_max):
        """Independently evaluate worst case for the reported x value."""
        x_val = results["robust_first_stage_x"]
        gamma = problem["budget_gamma"]
        wc = worst_case_for_x(x_val, z_max, gamma, problem, n_random=1500, seed=54321)
        reported = results["robust_optimal_objective"]
        assert abs(reported - wc) < 100, (
            f"Reported robust obj {reported:.2f} vs independent worst case {wc:.2f}"
        )

    def test_below_nominal(self, results, problem):
        """Robust objective must be strictly below the nominal optimum (~5437)."""
        assert results["robust_optimal_objective"] < 5500

    def test_above_trivial(self, results):
        """Robust profit must be meaningfully positive."""
        assert results["robust_optimal_objective"] > 500


# ===========================================================================
# Test: robust optimality via reference computation
# ===========================================================================
class TestRobustOptimality:
    def test_reference_comparison(self, results, problem, z_max):
        """Compare with independently computed reference solution."""
        gamma = problem["budget_gamma"]
        ref_x, ref_obj = reference_ccg(problem, z_max, gamma, tol=0.5, max_iter=50)

        rep_obj = results["robust_optimal_objective"]
        rep_x = results["robust_first_stage_x"]

        # Objectives within 5%
        rel_err_obj = abs(rep_obj - ref_obj) / max(abs(ref_obj), 1)
        assert rel_err_obj < 0.05, (
            f"Robust obj mismatch: reported={rep_obj:.2f} ref={ref_obj:.2f} "
            f"(rel err {rel_err_obj:.4f})"
        )

        # x within 10%
        rel_err_x = abs(rep_x - ref_x) / max(abs(ref_x), 1)
        assert rel_err_x < 0.10, (
            f"Robust x mismatch: reported={rep_x:.2f} ref={ref_x:.2f} "
            f"(rel err {rel_err_x:.4f})"
        )


# ===========================================================================
# Test: robust solution provides protection
# ===========================================================================
class TestRobustValue:
    def test_robust_beats_nominal_in_worst_case(self, results, problem, z_max):
        """The robust solution should have better worst-case profit than
        the nominal solution."""
        gamma = problem["budget_gamma"]
        fc = problem["feedstock_unit_cost"]
        products = problem["products"]
        br = problem["base_revenue"]
        pr = problem["processing_cost"]["reactor"]
        ps = problem["processing_cost"]["separator"]
        fu = problem["feedstock_usage"]
        res = problem["resources"]
        md = problem["max_demand"]
        ct = problem["contracts"]

        # --- Solve nominal (z = 0) problem to get nominal_x ---
        m = pyo.ConcreteModel()
        m.x = pyo.Var(domain=pyo.NonNegativeReals)
        m.PI = pyo.Set(initialize=range(4))
        m.y = pyo.Var(m.PI, domain=pyo.NonNegativeReals)
        m.yP = pyo.Var(domain=pyo.NonNegativeReals)
        rev0 = {p: br[p] - pr[p] - ps[p] for p in products}

        m.obj = pyo.Objective(expr=-fc * m.x + m.yP, sense=pyo.maximize)
        m.pdef = pyo.Constraint(
            expr=sum(rev0[products[i]] * m.y[i] for i in range(4)) >= m.yP
        )
        m.d1 = pyo.Constraint(expr=m.y[0] >= ct["C1"]["min_demand_nominal"])
        m.d2 = pyo.Constraint(expr=m.y[1] >= ct["C2"]["min_demand_nominal"])
        m.mx1 = pyo.Constraint(expr=m.y[0] <= md["C1"])
        m.mx2 = pyo.Constraint(expr=m.y[1] <= md["C2"])
        m.mx3 = pyo.Constraint(expr=m.y[2] <= md["C3"])
        rc = res["reactor"]["consumption"]
        m.rc_con = pyo.Constraint(
            expr=sum(rc[products[i]] * m.y[i] for i in range(4))
            <= res["reactor"]["capacity"]
        )
        sep_c = res["separator"]["consumption"]
        m.sc_con = pyo.Constraint(
            expr=sum(sep_c[products[i]] * m.y[i] for i in range(4))
            <= res["separator"]["capacity"]
        )
        lab_c = res["lab"]["consumption"]
        m.lc_con = pyo.Constraint(
            expr=sum(lab_c[products[i]] * m.y[i] for i in range(4))
            <= res["lab"]["capacity"]
        )
        m.fd = pyo.Constraint(
            expr=sum(fu[products[i]] * m.y[i] for i in range(4)) <= m.x
        )
        SOLVER.solve(m)
        nominal_x = pyo.value(m.x)

        # Sanity: nominal buys more feedstock than robust (no protection)
        robust_x = results["robust_first_stage_x"]
        assert nominal_x > robust_x * 1.05, (
            f"Nominal x={nominal_x:.2f} should exceed robust x={robust_x:.2f}"
        )

        # --- Robust objective is the exact worst-case profit for robust x ---
        wc_robust = results["robust_optimal_objective"]

        # --- Evaluate nominal x under adversarial scenarios ---
        zkeys = list(z_max.keys())
        n_active = int(gamma)
        found_worse = False
        worst_nominal_eval = float("inf")

        for active in itertools.combinations(range(5), n_active):
            z = {zk: 0.0 for zk in zkeys}
            for idx in active:
                z[zkeys[idx]] = z_max[zkeys[idx]]
            p = eval_stage2(nominal_x, z, problem)
            total = -fc * nominal_x + p
            worst_nominal_eval = min(worst_nominal_eval, total)
            if total < wc_robust:
                found_worse = True

        assert found_worse, (
            f"No adversarial scenario pushed nominal (x={nominal_x:.2f}) "
            f"below robust worst-case {wc_robust:.2f}; "
            f"best adversarial eval for nominal = {worst_nominal_eval:.2f}"
        )


# ===========================================================================
# Test: stochastic solution properties
# ===========================================================================
class TestStochastic:
    def test_stochastic_above_robust(self, results):
        """Stochastic average-case objective should exceed robust worst-case."""
        assert results["stochastic_optimal_objective"] > results["robust_optimal_objective"], (
            f"Stochastic {results['stochastic_optimal_objective']:.2f} should exceed "
            f"robust {results['robust_optimal_objective']:.2f}"
        )

    def test_stochastic_reasonable(self, results):
        """Stochastic should produce a reasonable objective."""
        assert results["stochastic_optimal_objective"] < 6000
        assert results["stochastic_optimal_objective"] > 2000

    def test_stochastic_x_reasonable(self, results):
        """Stochastic x should be positive and finite."""
        assert 100 < results["stochastic_first_stage_x"] < 1000
