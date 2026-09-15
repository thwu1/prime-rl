#!/usr/bin/env python3
"""
Reference solution: Two-stage robust chemical production planning
using Column-and-Constraint Generation (CCG) and Sample Average Approximation (SAA).

"""

import json
import numpy as np
import pyomo.environ as pyo

# ---------------------------------------------------------------------------
# Load problem data
# ---------------------------------------------------------------------------
with open("/app/data/problem.json") as f:
    prob = json.load(f)

products = prob["products"]
base_rev = prob["base_revenue"]
proc_reactor = prob["processing_cost"]["reactor"]
proc_sep = prob["processing_cost"]["separator"]
feed_use = prob["feedstock_usage"]
feed_cost = prob["feedstock_unit_cost"]
resources = prob["resources"]
max_dem = prob["max_demand"]
contracts = prob["contracts"]
unc = prob["uncertainty"]
GAMMA = prob["budget_gamma"]
CCG_TOL = prob["ccg_stopping_tolerance"]
CCG_MAX = prob["ccg_max_iterations"]
SAA_N = prob["saa_num_scenarios"]
SAA_SEED = prob["saa_random_seed"]

Z_MAX = {
    "z1": unc["z_reactor"]["max_deviation"],
    "z2": unc["z_separator"]["max_deviation"],
    "z3": unc["z_lab"]["max_deviation"],
    "z4": unc["z_demand_C1"]["max_deviation"],
    "z5": unc["z_demand_C2"]["max_deviation"],
}
Z_KEYS = list(Z_MAX.keys())

SOLVER = pyo.SolverFactory("appsi_highs")
assert SOLVER.available(), "HiGHS solver not available"

# ---------------------------------------------------------------------------
# Helper: net revenue per unit given z
# ---------------------------------------------------------------------------
def net_rev(z1, z2):
    return {
        p: base_rev[p] - proc_reactor[p] * (1 + z1) - proc_sep[p] * (1 + z2)
        for p in products
    }

# ---------------------------------------------------------------------------
# CCG master problem
# ---------------------------------------------------------------------------
def build_master(Z_scen):
    m = pyo.ConcreteModel("Master")
    m.x = pyo.Var(domain=pyo.NonNegativeReals)
    m.tau = pyo.Var(domain=pyo.Reals)
    m.SCEN = pyo.Set(initialize=range(len(Z_scen)))
    ynames = ["y1", "y2", "y3", "y4", "yP"]
    m.YV = pyo.Set(initialize=ynames)

    @m.Block(m.SCEN)
    def blk(b, s):
        z = Z_scen[s]
        z1, z2, z3, z4, z5 = z["z1"], z["z2"], z["z3"], z["z4"], z["z5"]
        rev = net_rev(z1, z2)
        b.y = pyo.Var(b.model().YV, domain=pyo.NonNegativeReals)

        # yP >= tau
        b.tau_lb = pyo.Constraint(expr=b.y["yP"] >= b.model().tau)

        # profit definition
        b.profit_def = pyo.Constraint(
            expr=sum(rev[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            >= b.y["yP"]
        )

        # contract demands
        b.dem1 = pyo.Constraint(
            expr=b.y["y1"] >= contracts["C1"]["min_demand_nominal"] * (1 + z4)
        )
        b.dem2 = pyo.Constraint(
            expr=b.y["y2"] >= contracts["C2"]["min_demand_nominal"] * (1 + z5)
        )

        # max demands
        b.mx1 = pyo.Constraint(expr=b.y["y1"] <= max_dem["C1"])
        b.mx2 = pyo.Constraint(expr=b.y["y2"] <= max_dem["C2"])
        b.mx3 = pyo.Constraint(expr=b.y["y3"] <= max_dem["C3"])

        # resources
        rc = resources["reactor"]["consumption"]
        b.reactor = pyo.Constraint(
            expr=(1 + z1)
            * sum(rc[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            <= resources["reactor"]["capacity"]
        )
        sc = resources["separator"]["consumption"]
        b.separator = pyo.Constraint(
            expr=(1 + z2)
            * sum(sc[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            <= resources["separator"]["capacity"]
        )
        lc = resources["lab"]["consumption"]
        b.lab = pyo.Constraint(
            expr=(1 + z3)
            * sum(lc[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            <= resources["lab"]["capacity"]
        )

        # feedstock
        b.feed = pyo.Constraint(
            expr=sum(feed_use[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            <= b.model().x
        )

    @m.Objective(sense=pyo.maximize)
    def obj(m):
        return -feed_cost * m.x + m.tau

    return m

# ---------------------------------------------------------------------------
# Extract per-scenario decisions from solved master
# ---------------------------------------------------------------------------
def extract_sol(m, Z_scen):
    sols = []
    for s in range(len(Z_scen)):
        sols.append(
            {
                "x": pyo.value(m.x),
                "y1": pyo.value(m.blk[s].y["y1"]),
                "y2": pyo.value(m.blk[s].y["y2"]),
                "y3": pyo.value(m.blk[s].y["y3"]),
                "y4": pyo.value(m.blk[s].y["y4"]),
                "yP": pyo.value(m.blk[s].y["yP"]),
            }
        )
    return sols

# ---------------------------------------------------------------------------
# Pessimization MIP
# ---------------------------------------------------------------------------
def build_pessimization(sols):
    m = pyo.ConcreteModel("Pessimization")
    BIG_M = 50000.0

    m.ZI = pyo.Set(initialize=Z_KEYS)
    m.SCEN = pyo.Set(initialize=range(len(sols)))

    m.z = pyo.Var(m.ZI, domain=pyo.Reals)
    m.za = pyo.Var(m.ZI, domain=pyo.NonNegativeReals)
    m.theta = pyo.Var(domain=pyo.Reals)

    for zk in Z_KEYS:
        m.z[zk].setlb(-Z_MAX[zk])
        m.z[zk].setub(Z_MAX[zk])

    @m.Constraint(m.ZI)
    def ap(m, zk):
        return m.z[zk] <= m.za[zk]

    @m.Constraint(m.ZI)
    def an(m, zk):
        return -m.z[zk] <= m.za[zk]

    m.budget = pyo.Constraint(
        expr=sum(m.za[zk] / Z_MAX[zk] for zk in Z_KEYS) <= GAMMA
    )

    ctypes = ["profit", "dem1", "dem2", "reactor", "separator", "lab"]
    non_profit = [k for k in ctypes if k != "profit"]

    @m.Block(m.SCEN)
    def sblk(b, s):
        d = sols[s]
        y1, y2, y3, y4, yP = d["y1"], d["y2"], d["y3"], d["y4"], d["yP"]

        rc = resources["reactor"]["consumption"]
        sc = resources["separator"]["consumption"]
        lc = resources["lab"]["consumption"]
        SR = sum(rc[products[i]] * d[f"y{i+1}"] for i in range(4))
        SS = sum(sc[products[i]] * d[f"y{i+1}"] for i in range(4))
        SL = sum(lc[products[i]] * d[f"y{i+1}"] for i in range(4))

        # L[k][zvar] coefficients and R[k] right-hand sides for violation: L*z >= R
        L = {
            "profit": {
                "z1": proc_reactor["C1"] * y1 + proc_reactor["C2"] * y2
                + proc_reactor["C3"] * y3 + proc_reactor["C4"] * y4,
                "z2": proc_sep["C1"] * y1 + proc_sep["C2"] * y2
                + proc_sep["C3"] * y3 + proc_sep["C4"] * y4,
                "z3": 0, "z4": 0, "z5": 0,
            },
            "dem1": {"z1": 0, "z2": 0, "z3": 0,
                     "z4": contracts["C1"]["min_demand_nominal"], "z5": 0},
            "dem2": {"z1": 0, "z2": 0, "z3": 0, "z4": 0,
                     "z5": contracts["C2"]["min_demand_nominal"]},
            "reactor": {"z1": SR, "z2": 0, "z3": 0, "z4": 0, "z5": 0},
            "separator": {"z1": 0, "z2": SS, "z3": 0, "z4": 0, "z5": 0},
            "lab": {"z1": 0, "z2": 0, "z3": SL, "z4": 0, "z5": 0},
        }

        nr = net_rev(0, 0)  # nominal revenues for R computation
        R = {
            "profit": sum(nr[products[i]] * d[f"y{i+1}"] for i in range(4)) - yP,
            "dem1": y1 - contracts["C1"]["min_demand_nominal"],
            "dem2": y2 - contracts["C2"]["min_demand_nominal"],
            "reactor": resources["reactor"]["capacity"] - SR,
            "separator": resources["separator"]["capacity"] - SS,
            "lab": resources["lab"]["capacity"] - SL,
        }

        b.u = pyo.Var(ctypes, domain=pyo.Binary)

        # at least one non-profit constraint must be violated
        b.atleast = pyo.Constraint(
            expr=sum(b.u[k] for k in non_profit) <= len(non_profit) - 1
        )

        @b.Constraint(ctypes)
        def viol(b, k):
            return (
                sum(L[k][zk] * b.model().z[zk] for zk in Z_KEYS)
                - b.model().theta
                >= R[k] - b.u[k] * BIG_M
            )

    @m.Objective(sense=pyo.maximize)
    def obj(m):
        return m.theta

    return m

# ---------------------------------------------------------------------------
# SAA problem
# ---------------------------------------------------------------------------
def sample_z(seed):
    rng = np.random.default_rng(seed)
    while True:
        z = {zk: Z_MAX[zk] * rng.uniform(-1, 1) for zk in Z_KEYS}
        if sum(abs(z[zk]) / Z_MAX[zk] for zk in Z_KEYS) <= GAMMA:
            return z


def build_saa(Z_scen):
    m = pyo.ConcreteModel("SAA")
    m.x = pyo.Var(domain=pyo.NonNegativeReals)
    m.SCEN = pyo.Set(initialize=range(len(Z_scen)))
    ynames = ["y1", "y2", "y3", "y4", "yP"]
    m.YV = pyo.Set(initialize=ynames)

    @m.Block(m.SCEN)
    def blk(b, s):
        z = Z_scen[s]
        z1, z2, z3, z4, z5 = z["z1"], z["z2"], z["z3"], z["z4"], z["z5"]
        rev = net_rev(z1, z2)
        b.y = pyo.Var(b.model().YV, domain=pyo.NonNegativeReals)

        b.profit_def = pyo.Constraint(
            expr=sum(rev[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            >= b.y["yP"]
        )
        b.dem1 = pyo.Constraint(
            expr=b.y["y1"] >= contracts["C1"]["min_demand_nominal"] * (1 + z4)
        )
        b.dem2 = pyo.Constraint(
            expr=b.y["y2"] >= contracts["C2"]["min_demand_nominal"] * (1 + z5)
        )
        b.mx1 = pyo.Constraint(expr=b.y["y1"] <= max_dem["C1"])
        b.mx2 = pyo.Constraint(expr=b.y["y2"] <= max_dem["C2"])
        b.mx3 = pyo.Constraint(expr=b.y["y3"] <= max_dem["C3"])

        rc = resources["reactor"]["consumption"]
        b.reactor = pyo.Constraint(
            expr=(1 + z1)
            * sum(rc[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            <= resources["reactor"]["capacity"]
        )
        scc = resources["separator"]["consumption"]
        b.separator = pyo.Constraint(
            expr=(1 + z2)
            * sum(scc[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            <= resources["separator"]["capacity"]
        )
        lcc = resources["lab"]["consumption"]
        b.lab = pyo.Constraint(
            expr=(1 + z3)
            * sum(lcc[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            <= resources["lab"]["capacity"]
        )
        b.feed = pyo.Constraint(
            expr=sum(feed_use[products[i]] * b.y[f"y{i+1}"] for i in range(4))
            <= b.model().x
        )

    @m.Objective(sense=pyo.maximize)
    def obj(m):
        return -feed_cost * m.x + sum(
            m.blk[s].y["yP"] for s in m.SCEN
        ) / len(Z_scen)

    return m

# ===========================================================================
# CCG Algorithm
# ===========================================================================
print("=" * 60)
print("Running CCG algorithm")
print("=" * 60)

Z_ccg = [{"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}]
ccg_converged = False
ccg_iter = 0

while not ccg_converged and ccg_iter < CCG_MAX:
    m_master = build_master(Z_ccg)
    SOLVER.solve(m_master)

    ccg_obj = pyo.value(m_master.obj)
    x_val = pyo.value(m_master.x)
    print(f"  Iter {ccg_iter}: obj={ccg_obj:.2f}  x={x_val:.2f}")

    sols = extract_sol(m_master, Z_ccg)

    m_pess = build_pessimization(sols)
    SOLVER.solve(m_pess)

    theta = pyo.value(m_pess.theta)
    z_new = {zk: pyo.value(m_pess.z[zk]) for zk in Z_KEYS}
    print(f"    theta={theta:.4f}  z={[round(z_new[zk], 4) for zk in Z_KEYS]}")

    if theta < CCG_TOL:
        print("  Converged!")
        ccg_converged = True
    else:
        Z_ccg.append(z_new)

    ccg_iter += 1

ccg_final_obj = ccg_obj
ccg_final_x = x_val

# ===========================================================================
# SAA
# ===========================================================================
print(f"\nRunning SAA with {SAA_N} scenarios (seed={SAA_SEED})...")
Z_saa = [sample_z(j + SAA_SEED) for j in range(SAA_N)]

m_saa = build_saa(Z_saa)
SOLVER.solve(m_saa)

saa_obj = pyo.value(m_saa.obj)
saa_x = pyo.value(m_saa.x)
print(f"  SAA: obj={saa_obj:.2f}  x={saa_x:.2f}")

# ===========================================================================
# Write results
# ===========================================================================
results = {
    "robust_optimal_objective": round(ccg_final_obj, 6),
    "robust_first_stage_x": round(ccg_final_x, 6),
    "robust_iterations": ccg_iter,
    "stochastic_optimal_objective": round(saa_obj, 6),
    "stochastic_first_stage_x": round(saa_x, 6),
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nResults written to /app/results.json")
print(json.dumps(results, indent=2))
