#!/usr/bin/env python3

"""
Solve the supply chain network resilience analysis problem.

Formulates and solves two-stage stochastic MILPs:
1. Cost-minimizing (risk-neutral): min fixed + E[transport]
2. Risk-aware (CVaR): min fixed + E[transport] + weight * CVaR_{alpha}

Uses Pyomo + HiGHS solver.
"""

import json
import csv
import os
import pyomo.environ as pyo


def load_data():
    with open("/app/data/network.json") as f:
        network = json.load(f)
    with open("/app/data/config.json") as f:
        config = json.load(f)

    # Parse demand scenarios
    scenarios = []
    probs = []
    with open("/app/data/demand_scenarios.csv") as f:
        reader = csv.DictReader(f)
        cols = [c for c in reader.fieldnames if c not in ("scenario_id", "probability")]
        for row in reader:
            demands = [float(row[c]) for c in cols]
            scenarios.append(demands)
            probs.append(float(row["probability"]))

    return network, config, scenarios, probs


def build_and_solve(network, config, scenarios, probs, lam, alpha):
    """Build and solve the two-stage stochastic MILP.

    lam=0: risk-neutral (pure expected cost minimization)
    lam>0: risk-aware with CVaR_{alpha} penalty
    """
    n_sup = network["suppliers"]["count"]
    n_fac = network["facilities"]["count"]
    n_cust = network["customers"]["count"]
    n_scen = len(scenarios)

    S = range(n_sup)
    W = range(n_fac)
    C = range(n_cust)
    Omega = range(n_scen)

    cost_sw = network["inbound_unit_costs"]
    cost_wc = network["outbound_unit_costs"]
    cap_s = network["suppliers"]["max_output"]
    cap_w = network["facilities"]["throughput_limits"]
    fc = network["facilities"]["opening_costs"]
    budget = config["capital_budget"]

    m = pyo.ConcreteModel()
    m.S = pyo.Set(initialize=S)
    m.W = pyo.Set(initialize=W)
    m.C = pyo.Set(initialize=C)
    m.Omega = pyo.Set(initialize=Omega)

    # Parameters
    m.f = pyo.Param(m.W, initialize={j: fc[j] for j in W})
    m.cap_s = pyo.Param(m.S, initialize={i: cap_s[i] for i in S})
    m.cap_w = pyo.Param(m.W, initialize={j: cap_w[j] for j in W})
    m.c1 = pyo.Param(m.S, m.W, initialize={(i, j): cost_sw[i][j] for i in S for j in W})
    m.c2 = pyo.Param(m.W, m.C, initialize={(j, k): cost_wc[j][k] for j in W for k in C})
    m.d = pyo.Param(m.C, m.Omega, initialize={(k, o): scenarios[o][k] for k in C for o in Omega})
    m.p = pyo.Param(m.Omega, initialize={o: probs[o] for o in Omega})

    # First-stage: binary facility opening
    m.y = pyo.Var(m.W, domain=pyo.Binary)
    # Second-stage: continuous flows per scenario
    m.x1 = pyo.Var(m.S, m.W, m.Omega, domain=pyo.NonNegativeReals)
    m.x2 = pyo.Var(m.W, m.C, m.Omega, domain=pyo.NonNegativeReals)
    # CVaR auxiliaries
    m.eta = pyo.Var(domain=pyo.Reals)  # VaR
    m.sv = pyo.Var(m.Omega, domain=pyo.NonNegativeReals)  # excess

    # Objective
    def obj_rule(md):
        fixed = sum(md.f[j] * md.y[j] for j in md.W)
        exp_transport = sum(
            md.p[o] * (
                sum(md.c1[i, j] * md.x1[i, j, o] for i in md.S for j in md.W)
                + sum(md.c2[j, k] * md.x2[j, k, o] for j in md.W for k in md.C)
            )
            for o in md.Omega
        )
        if lam > 0:
            cvar_term = lam * (
                md.eta + (1.0 / (1.0 - alpha)) * sum(md.p[o] * md.sv[o] for o in md.Omega)
            )
        else:
            cvar_term = 0
        return fixed + exp_transport + cvar_term

    m.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

    # Budget constraint
    m.budget_con = pyo.Constraint(
        rule=lambda md: sum(md.f[j] * md.y[j] for j in md.W) <= budget
    )

    # Demand satisfaction
    m.demand_con = pyo.Constraint(
        m.C, m.Omega,
        rule=lambda md, k, o: sum(md.x2[j, k, o] for j in md.W) >= md.d[k, o]
    )

    # Facility capacity (linked to opening)
    m.fac_cap = pyo.Constraint(
        m.W, m.Omega,
        rule=lambda md, j, o: sum(md.x2[j, k, o] for k in md.C) <= md.cap_w[j] * md.y[j]
    )

    # Supplier capacity
    m.sup_cap = pyo.Constraint(
        m.S, m.Omega,
        rule=lambda md, i, o: sum(md.x1[i, j, o] for j in md.W) <= md.cap_s[i]
    )

    # Flow conservation at facilities
    m.flow_con = pyo.Constraint(
        m.W, m.Omega,
        rule=lambda md, j, o: sum(md.x1[i, j, o] for i in md.S) == sum(md.x2[j, k, o] for k in md.C)
    )

    # CVaR linearization constraints
    if lam > 0:
        def cvar_rule(md, o):
            scenario_cost = (
                sum(md.c1[i, j] * md.x1[i, j, o] for i in md.S for j in md.W)
                + sum(md.c2[j, k] * md.x2[j, k, o] for j in md.W for k in md.C)
            )
            return md.sv[o] >= scenario_cost - md.eta
        m.cvar_con = pyo.Constraint(m.Omega, rule=cvar_rule)
    else:
        m.eta.fix(0)
        for o in Omega:
            m.sv[o].fix(0)

    # Solve
    solver = pyo.SolverFactory("appsi_highs")
    result = solver.solve(m, tee=True)
    assert str(result.solver.termination_condition) == "optimal", (
        f"Solver status: {result.solver.termination_condition}"
    )

    # Extract results
    opened = sorted([j for j in W if pyo.value(m.y[j]) > 0.5])
    obj_val = pyo.value(m.obj)
    eta_val = pyo.value(m.eta)

    exp_transport = 0.0
    for o in Omega:
        sc = (sum(pyo.value(m.c1[i, j]) * pyo.value(m.x1[i, j, o]) for i in S for j in W)
              + sum(pyo.value(m.c2[j, k]) * pyo.value(m.x2[j, k, o]) for j in W for k in C))
        exp_transport += probs[o] * sc

    cvar_excess = sum(probs[o] * pyo.value(m.sv[o]) for o in Omega)
    cvar_val = eta_val + (1.0 / (1.0 - alpha)) * cvar_excess

    fixed_cost = sum(fc[j] for j in opened)

    return {
        "opened": opened,
        "objective": obj_val,
        "expected_transport": exp_transport,
        "cvar": cvar_val,
        "var": eta_val,
        "fixed_cost": fixed_cost,
    }


def main():
    network, config, scenarios, probs = load_data()
    alpha = config["tail_risk_confidence"]
    weight = config["risk_cost_weight"]

    print("=" * 60)
    print("Solving cost-minimizing (risk-neutral) model...")
    print("=" * 60)
    cm = build_and_solve(network, config, scenarios, probs, lam=0.0, alpha=alpha)

    print()
    print("=" * 60)
    print("Solving risk-aware model...")
    print("=" * 60)
    ra = build_and_solve(network, config, scenarios, probs, lam=weight, alpha=alpha)

    # Compute comparison
    facilities_differ = cm["opened"] != ra["opened"]
    additional = sorted([f for f in ra["opened"] if f not in cm["opened"]])
    cost_change_pct = (ra["expected_transport"] - cm["expected_transport"]) / cm["expected_transport"] * 100

    # For tail risk change, compare CVaR values
    # Risk-neutral doesn't optimize CVaR, but we can compute what its CVaR would be
    # by re-solving or using the risk-aware CVaR reference
    # Actually, we need the tail risk of the cost-minimizing solution
    # We'll use the worst-5% average from risk-neutral scenario costs
    # Re-compute scenario costs under cost-minimizing solution
    # Since we already have the CVaR from the risk-aware solve, use those
    # For risk-neutral, the CVaR wasn't optimized, so we compute it post-hoc
    cm_tail = cm["cvar"]  # This is 0 because eta was fixed to 0
    # Actually need to compute worst-5% avg cost for cost-minimizing solution
    # But the model already solved — we need scenario costs
    # Let's use the risk-neutral objective as reference and the risk-aware tail_risk

    # The comparison should use the actual tail risk values from each model
    # For cost-minimizing: we solve again with lambda=0 but compute CVaR post-hoc
    # Simpler: re-solve with tiny lambda to get CVaR without changing binary decisions
    # Actually, let's just use a proxy: the tail risk change is based on the risk-aware model's metrics

    # More accurate: compute worst-5% scenario transport costs for each solution
    # by replaying the optimal routing. Since both models were solved, we can extract this.

    # For now, use CVaR values directly
    # Risk-neutral CVaR is not meaningful (eta=0), so compare tail risk differently
    # Use the actual tail risk of both solutions
    # Risk-neutral tail risk = its worst-5% avg cost (need to compute)
    # Risk-aware tail risk = ra["cvar"]

    # Approximate: Since the risk-neutral solution has no CVaR optimization,
    # its worst-5% cost is higher. The change is:
    # (ra_tail - cm_tail) / cm_tail * 100
    # But cm_tail isn't directly available from the lambda=0 solve.
    # We need to rebuild and evaluate. Let's solve with very small lambda.

    cm_with_cvar = build_and_solve(network, config, scenarios, probs, lam=1e-6, alpha=alpha)
    cm_tail_risk = cm_with_cvar["cvar"]
    tail_risk_change_pct = (ra["cvar"] - cm_tail_risk) / cm_tail_risk * 100

    # Build output
    analysis = {
        "cost_minimizing": {
            "opened_facilities": cm["opened"],
            "total_cost": round(cm["objective"], 4),
            "expected_transport_cost": round(cm["expected_transport"], 4),
            "fixed_cost": cm["fixed_cost"],
        },
        "risk_aware": {
            "opened_facilities": ra["opened"],
            "total_cost": round(ra["objective"], 4),
            "expected_transport_cost": round(ra["expected_transport"], 4),
            "fixed_cost": ra["fixed_cost"],
            "tail_risk_value": round(ra["cvar"], 4),
            "risk_threshold": round(ra["var"], 4),
        },
        "comparison": {
            "facilities_differ": facilities_differ,
            "additional_facilities_in_risk_plan": additional,
            "expected_cost_change_pct": round(cost_change_pct, 4),
            "tail_risk_change_pct": round(tail_risk_change_pct, 4),
        },
    }

    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print()
    print("=" * 60)
    print("Results written to /app/results/analysis.json")
    print("=" * 60)
    print(json.dumps(analysis, indent=2))


if __name__ == "__main__":
    main()
