#!/usr/bin/env python3
"""
Benders decomposition for two-stage stochastic capacitated facility location.

Master problem: binary facility opening decisions (y) + recourse cost variables (theta).
Subproblems (one per scenario): continuous demand allocation LP given fixed y.
Cuts: optimality cuts from subproblem dual values; feasibility ensured by
aggregate capacity constraints (valid for transportation-structured subproblems).
"""

import json
import os
import sys
from pulp import LpProblem, LpMinimize, LpVariable, lpSum, PULP_CBC_CMD, value

DATA_PATH = "/app/data/instance.json"
OUTPUT_PATH = "/app/output/solution.json"
MAX_ITER = 300
EPS = 1e-5


def solve():
    with open(DATA_PATH) as f:
        data = json.load(f)

    nf = data["n_facilities"]
    nc = data["n_customers"]
    ns = data["n_scenarios"]
    fc = data["opening_costs"]
    cap = data["capacities"]
    tc = data["transport_costs"]
    scenarios = data["scenarios"]

    # Accumulated Benders optimality cuts: list of (scenario_idx, lambda_vals, mu_vals)
    opt_cuts = []

    best_ub = float("inf")
    best_y = None
    best_oc = None
    best_recourse = None

    for iteration in range(MAX_ITER):
        # ========== MASTER PROBLEM ==========
        master = LpProblem("master", LpMinimize)
        y = [LpVariable(f"y_{j}", cat="Binary") for j in range(nf)]
        theta = [LpVariable(f"theta_{s}", lowBound=0) for s in range(ns)]

        master += lpSum(fc[j] * y[j] for j in range(nf)) + lpSum(
            scenarios[s]["probability"] * theta[s] for s in range(ns)
        )

        # Aggregate feasibility cuts: total capacity of opened facilities must
        # cover total demand in every scenario. For a transportation-structured
        # subproblem (all customer-facility pairs feasible), this is the only
        # source of infeasibility.
        for s in range(ns):
            total_demand_s = sum(scenarios[s]["demands"])
            master += lpSum(cap[j] * y[j] for j in range(nf)) >= total_demand_s

        # Accumulated optimality cuts from previous iterations
        for idx, (s, lam, mu) in enumerate(opt_cuts):
            demands_s = scenarios[s]["demands"]
            master += (
                theta[s]
                >= lpSum(demands_s[i] * lam[i] for i in range(nc))
                + lpSum(cap[j] * mu[j] * y[j] for j in range(nf))
            )

        master.solve(PULP_CBC_CMD(msg=0))
        if master.status != 1:
            print(f"Master infeasible at iteration {iteration}", file=sys.stderr)
            break

        y_val = [int(round(value(y[j]))) for j in range(nf)]
        theta_val = [value(theta[s]) for s in range(ns)]
        lb = value(master.objective)

        # ========== SUBPROBLEMS ==========
        total_recourse = 0.0
        new_cut = False

        for s in range(ns):
            demands = scenarios[s]["demands"]
            prob_s = scenarios[s]["probability"]

            sub = LpProblem(f"sub_{s}", LpMinimize)
            x = {}
            for i in range(nc):
                for j in range(nf):
                    x[i, j] = LpVariable(f"x_{i}_{j}", lowBound=0)

            sub += lpSum(
                tc[i][j] * x[i, j] for i in range(nc) for j in range(nf)
            )

            # Demand satisfaction (equality)
            for i in range(nc):
                sub += (
                    lpSum(x[i, j] for j in range(nf)) == demands[i],
                    f"demand_{i}",
                )

            # Capacity (inequality, <= )
            for j in range(nf):
                sub += (
                    lpSum(x[i, j] for i in range(nc)) <= cap[j] * y_val[j],
                    f"cap_{j}",
                )

            sub.solve(PULP_CBC_CMD(msg=0))

            if sub.status != 1:
                print(
                    f"  WARNING: Subproblem {s} not optimal (status={sub.status})",
                    file=sys.stderr,
                )
                # Should not happen with aggregate feasibility cuts
                total_recourse = float("inf")
                break

            sub_obj = value(sub.objective)
            total_recourse += prob_s * sub_obj

            # Extract dual values (shadow prices)
            lam = []
            for i in range(nc):
                pi_val = sub.constraints[f"demand_{i}"].pi
                lam.append(float(pi_val) if pi_val is not None else 0.0)

            mu = []
            for j in range(nf):
                pi_val = sub.constraints[f"cap_{j}"].pi
                mu.append(float(pi_val) if pi_val is not None else 0.0)

            # Check if optimality cut is needed (subproblem cost exceeds master's estimate)
            if theta_val[s] is not None and sub_obj > theta_val[s] + EPS:
                opt_cuts.append((s, lam[:], mu[:]))
                new_cut = True

        # Update upper bound with current feasible solution
        if total_recourse < float("inf"):
            current_oc = sum(fc[j] * y_val[j] for j in range(nf))
            ub = current_oc + total_recourse
            if ub < best_ub:
                best_ub = ub
                best_y = y_val[:]
                best_oc = current_oc
                best_recourse = total_recourse

        # Check convergence
        gap = abs(best_ub - lb) / max(abs(best_ub), 1.0)
        print(f"Iter {iteration:3d}: LB={lb:12.4f}  UB={best_ub:12.4f}  gap={gap:.8f}")

        if gap < EPS:
            print("Converged: gap below tolerance.")
            break
        if not new_cut:
            print("Converged: no new cuts generated.")
            break

    # ========== OUTPUT ==========
    if best_y is None:
        print("ERROR: No feasible solution found.", file=sys.stderr)
        sys.exit(1)

    opened = [j for j in range(nf) if best_y[j] > 0.5]

    solution = {
        "objective_value": round(best_ub, 6),
        "facilities_opened": opened,
        "opening_cost": float(best_oc),
        "expected_transport_cost": round(best_recourse, 6),
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(solution, f, indent=2)

    print(f"\nSolution written to {OUTPUT_PATH}")
    print(f"Objective:  {best_ub:.4f}")
    print(f"Opened:     {opened}")
    print(f"Open cost:  {best_oc:.2f}")
    print(f"E[transp]:  {best_recourse:.4f}")


if __name__ == "__main__":
    solve()
