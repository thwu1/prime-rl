#!/usr/bin/env python3
"""
Benders decomposition for two-stage stochastic capacitated facility location.

Master problem: binary facility opening decisions + epigraphical variables theta_s.
Subproblems: LP transportation assignment per scenario given opened facilities.
Optimality cuts derived from subproblem duals are added iteratively.

"""

import json
import math
import sys

from pulp import (
    PULP_CBC_CMD,
    LpMinimize,
    LpProblem,
    LpVariable,
    lpSum,
    value,
)


def load_instance(path="/app/instance.json"):
    with open(path) as f:
        return json.load(f)


def euclidean_dist(x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def solve_subproblem(facs, scen_demands, trans_costs, nF, nC, y_vals):
    """
    Solve the transportation subproblem for one scenario over ALL facilities.
    Capacity of facility i is cap_i * y_vals[i]. Slack variables with a large
    penalty ensure feasibility even when capacity is insufficient.

    Returns: (true_transport_cost, demand_duals, capacity_duals, is_truly_feasible)
    """
    BIG_M = 10000.0

    prob = LpProblem("subproblem", LpMinimize)

    x = {}
    for i in range(nF):
        for j in range(nC):
            x[i, j] = LpVariable(f"x_{i}_{j}", lowBound=0)

    slack = {}
    for j in range(nC):
        slack[j] = LpVariable(f"s_{j}", lowBound=0)

    prob += (
        lpSum(
            trans_costs[i, j] * scen_demands[j] * x[i, j]
            for i in range(nF) for j in range(nC)
        )
        + lpSum(BIG_M * slack[j] for j in range(nC))
    )

    for j in range(nC):
        prob += (
            lpSum(x[i, j] for i in range(nF)) + slack[j] == 1,
            f"demand_{j}",
        )

    for i in range(nF):
        cap = facs[i]["capacity"] * y_vals[i]
        prob += (
            lpSum(scen_demands[j] * x[i, j] for j in range(nC)) <= cap,
            f"cap_{i}",
        )

    prob.solve(PULP_CBC_CMD(msg=0))
    if prob.status != 1:
        return None, None, None, False

    demand_duals = {}
    cap_duals = {}
    for j in range(nC):
        pi_val = prob.constraints[f"demand_{j}"].pi
        demand_duals[j] = pi_val if pi_val is not None else 0.0
    for i in range(nF):
        pi_val = prob.constraints[f"cap_{i}"].pi
        cap_duals[i] = pi_val if pi_val is not None else 0.0

    total_slack = sum(value(slack[j]) for j in range(nC))
    is_feasible = total_slack < 1e-6

    if is_feasible:
        transport_cost = value(prob.objective)
    else:
        transport_cost = float("inf")

    return transport_cost, demand_duals, cap_duals, is_feasible


def evaluate_configuration(facs, scens, trans_costs, nF, nC, y_vals):
    """Evaluate the total objective for a given facility configuration."""
    fixed_cost = sum(facs[i]["fixed_cost"] for i in range(nF) if y_vals[i] == 1)
    total_transport = 0.0

    for s_idx, scen in enumerate(scens):
        demands = scen["demands"]
        prob = LpProblem(f"eval_{s_idx}", LpMinimize)

        opened = [i for i in range(nF) if y_vals[i] == 1]
        x = {}
        for i in opened:
            for j in range(nC):
                x[i, j] = LpVariable(f"x_{i}_{j}", lowBound=0)

        prob += lpSum(
            trans_costs[i, j] * demands[j] * x[i, j]
            for i in opened for j in range(nC)
        )

        for j in range(nC):
            prob += lpSum(x[i, j] for i in opened) == 1

        for i in opened:
            prob += lpSum(demands[j] * x[i, j] for j in range(nC)) <= facs[i]["capacity"]

        prob.solve(PULP_CBC_CMD(msg=0))
        if prob.status != 1:
            return float("inf")

        total_transport += scen["probability"] * value(prob.objective)

    return fixed_cost + total_transport


def benders_decomposition(instance, max_iterations=200, gap_tolerance=0.005):
    """
    Solve two-stage stochastic facility location via Benders decomposition.
    """
    facs = instance["facilities"]
    custs = instance["customers"]
    scens = instance["scenarios"]
    unit_cost = instance["unit_transport_cost"]
    nF = len(facs)
    nC = len(custs)
    nS = len(scens)

    trans_costs = {}
    for i in range(nF):
        for j in range(nC):
            trans_costs[i, j] = unit_cost * euclidean_dist(
                facs[i]["x"], facs[i]["y"], custs[j]["x"], custs[j]["y"]
            )

    # Phase 0: Compute initial upper bounds from several heuristic solutions
    upper_bound = float("inf")
    best_y = None
    best_obj = float("inf")

    heuristic_configs = []
    # All open
    heuristic_configs.append([1] * nF)
    # Cheapest k facilities
    sorted_by_cost = sorted(range(nF), key=lambda i: facs[i]["fixed_cost"])
    for k in range(2, nF):
        y_h = [0] * nF
        for i in sorted_by_cost[:k]:
            y_h[i] = 1
        heuristic_configs.append(y_h)

    for y_h in heuristic_configs:
        obj_h = evaluate_configuration(facs, scens, trans_costs, nF, nC, y_h)
        if obj_h < upper_bound:
            upper_bound = obj_h
            best_y = y_h[:]
            best_obj = obj_h

    print(f"Initial UB from heuristics: {upper_bound:.4f} "
          f"(facilities: {[i for i in range(nF) if best_y[i]]})")

    # Phase 1: Generate initial cuts from the best heuristic solution
    cuts = []
    n_cuts = 0
    for s in range(nS):
        demands = scens[s]["demands"]
        _, dd, cd, _ = solve_subproblem(
            facs, demands, trans_costs, nF, nC, best_y
        )
        if dd is not None:
            cuts.append((s, dd, cd))
            n_cuts += 1

    lower_bound = float("-inf")

    # Phase 2: Benders decomposition loop
    for iteration in range(1, max_iterations + 1):
        # === BUILD MASTER ===
        master = LpProblem("master", LpMinimize)

        y = [LpVariable(f"y_{i}", cat="Binary") for i in range(nF)]
        theta = [LpVariable(f"theta_{s}", lowBound=0) for s in range(nS)]

        master += (
            lpSum(facs[i]["fixed_cost"] * y[i] for i in range(nF))
            + lpSum(scens[s]["probability"] * theta[s] for s in range(nS))
        )

        for cut_idx, (s, mu, lam) in enumerate(cuts):
            cut_rhs = lpSum(mu[j] for j in range(nC))
            for i in range(nF):
                cut_rhs += lam[i] * facs[i]["capacity"] * y[i]
            master += (theta[s] >= cut_rhs, f"cut_{cut_idx}")

        master.solve(PULP_CBC_CMD(msg=0))

        if master.status != 1:
            print(f"Iteration {iteration}: Master infeasible, stopping.")
            break

        y_vals = [int(round(value(y[i]))) for i in range(nF)]
        lower_bound = value(master.objective)

        # === SOLVE SUBPROBLEMS ===
        total_recourse = 0.0
        new_cuts_added = False
        all_feasible = True

        for s in range(nS):
            demands = scens[s]["demands"]
            obj_val, dd, cd, is_feas = solve_subproblem(
                facs, demands, trans_costs, nF, nC, y_vals
            )

            if not is_feas:
                all_feasible = False
                total_recourse = float("inf")
            else:
                total_recourse += scens[s]["probability"] * obj_val

            # Add cut if theta underestimates
            if dd is not None:
                theta_val = value(theta[s])
                if not is_feas or obj_val > theta_val + 1e-4:
                    cuts.append((s, dd, cd))
                    n_cuts += 1
                    new_cuts_added = True

        # === UPDATE UPPER BOUND ===
        if all_feasible:
            fixed_cost = sum(
                facs[i]["fixed_cost"] for i in range(nF) if y_vals[i] == 1
            )
            current_obj = fixed_cost + total_recourse
            if current_obj < upper_bound:
                upper_bound = current_obj
                best_y = y_vals[:]
                best_obj = current_obj

        # === CONVERGENCE ===
        gap = (upper_bound - lower_bound) / max(abs(upper_bound), 1e-9)
        opened = [i for i in range(nF) if y_vals[i] == 1]
        print(
            f"Iter {iteration}: LB={lower_bound:.4f} UB={upper_bound:.4f} "
            f"gap={gap:.6f} cuts={n_cuts} opened={opened}"
        )

        if gap < gap_tolerance:
            print(f"Converged (gap={gap:.6f} < {gap_tolerance})")
            break

        if not new_cuts_added:
            print("No new cuts added, converged.")
            break

    return best_y, best_obj


def main():
    instance = load_instance()
    facs = instance["facilities"]

    print("Benders decomposition for stochastic facility location")
    print("=" * 60)

    y_vals, obj_val = benders_decomposition(instance)

    if y_vals is None:
        print("ERROR: Failed to find a solution.")
        sys.exit(1)

    opened = [i for i in range(len(facs)) if y_vals[i] == 1]

    solution = {
        "opened_facilities": opened,
        "objective_value": round(obj_val, 6),
    }

    with open("/app/solution.json", "w") as f:
        json.dump(solution, f, indent=2)

    print(f"\nSolution written to /app/solution.json")
    print(f"Opened facilities: {opened}")
    print(f"Objective value: {obj_val:.4f}")
    fixed = sum(facs[i]["fixed_cost"] for i in opened)
    print(f"Fixed cost: {fixed}, Transport: {obj_val - fixed:.4f}")


if __name__ == "__main__":
    main()
