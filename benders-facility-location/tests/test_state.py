
import json
import math
import os
import re

import pytest
from pulp import (
    PULP_CBC_CMD,
    LpMinimize,
    LpProblem,
    LpStatus,
    LpVariable,
    lpSum,
    value,
)


def load_instance():
    with open("/app/instance.json") as f:
        return json.load(f)


def euclidean_dist(x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def solve_dep(instance):
    """Solve the deterministic equivalent program (DEP) as a monolithic MIP."""
    facs = instance["facilities"]
    custs = instance["customers"]
    scens = instance["scenarios"]
    unit_cost = instance["unit_transport_cost"]
    nF = len(facs)
    nC = len(custs)
    nS = len(scens)

    dist = {}
    for i in range(nF):
        for j in range(nC):
            dist[i, j] = euclidean_dist(
                facs[i]["x"], facs[i]["y"], custs[j]["x"], custs[j]["y"]
            )

    prob = LpProblem("DEP_FacilityLocation", LpMinimize)

    y = [LpVariable(f"y_{i}", cat="Binary") for i in range(nF)]
    x = {}
    for s in range(nS):
        for i in range(nF):
            for j in range(nC):
                x[i, j, s] = LpVariable(f"x_{i}_{j}_{s}", lowBound=0)

    obj = lpSum(facs[i]["fixed_cost"] * y[i] for i in range(nF))
    for s in range(nS):
        p = scens[s]["probability"]
        for i in range(nF):
            for j in range(nC):
                d = scens[s]["demands"][j]
                obj += p * unit_cost * dist[i, j] * d * x[i, j, s]
    prob += obj

    for s in range(nS):
        for j in range(nC):
            prob += (
                lpSum(x[i, j, s] for i in range(nF)) == 1,
                f"serve_{j}_{s}",
            )

    for s in range(nS):
        for i in range(nF):
            demands = scens[s]["demands"]
            prob += (
                lpSum(demands[j] * x[i, j, s] for j in range(nC))
                <= facs[i]["capacity"] * y[i],
                f"cap_{i}_{s}",
            )

    prob.solve(PULP_CBC_CMD(msg=0, timeLimit=120))
    assert prob.status == 1, f"DEP solver failed with status {LpStatus[prob.status]}"

    opt_val = value(prob.objective)
    opened = [i for i in range(nF) if value(y[i]) > 0.5]
    return opt_val, opened


class TestSolverSolution:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.instance = load_instance()
        self.dep_optimal, self.dep_opened = solve_dep(self.instance)

    def test_solver_file_exists(self):
        """The agent must create /app/solver.py."""
        assert os.path.isfile(
            "/app/solver.py"
        ), "Solver file /app/solver.py not found"

    def test_solver_uses_decomposition(self):
        """The implementation must use an iterative decomposition, not monolithic DEP."""
        with open("/app/solver.py") as f:
            code = f.read()

        has_iteration = bool(
            re.search(r"\b(while|for)\b.*\b(iter|cut|converge|gap|bound)\b", code, re.IGNORECASE)
            or re.search(r"\b(iteration|n_cuts|num_cuts|cut_count)\b", code, re.IGNORECASE)
        )
        has_master_sub = bool(
            re.search(r"\b(master|sub_?problem|pricing|recourse)\b", code, re.IGNORECASE)
        )
        has_dual = bool(
            re.search(r"\b(dual|shadow|pi|mu|lambda|multiplier)\b", code, re.IGNORECASE)
            or re.search(r"\.pi\b|duals|constraint.*value", code, re.IGNORECASE)
        )
        has_cut = bool(
            re.search(r"\b(cut|benders|optimality.cut|feasibility.cut)\b", code, re.IGNORECASE)
        )

        decomp_score = sum([has_iteration, has_master_sub, has_dual, has_cut])
        assert decomp_score >= 3, (
            f"Code does not appear to implement a decomposition approach "
            f"(score {decomp_score}/4: iteration={has_iteration}, "
            f"master_sub={has_master_sub}, dual={has_dual}, cut={has_cut}). "
            f"A monolithic DEP formulation is not accepted."
        )

    def test_solution_file_exists(self):
        """The solution file must exist."""
        assert os.path.isfile(
            "/app/solution.json"
        ), "Solution file /app/solution.json not found"

    def test_solution_format(self):
        """Solution must have correct JSON structure."""
        with open("/app/solution.json") as f:
            sol = json.load(f)

        assert "opened_facilities" in sol, "Missing 'opened_facilities' key"
        assert "objective_value" in sol, "Missing 'objective_value' key"
        assert isinstance(sol["opened_facilities"], list), "'opened_facilities' must be a list"
        assert isinstance(
            sol["objective_value"], (int, float)
        ), "'objective_value' must be numeric"
        assert len(sol["opened_facilities"]) > 0, "Must open at least one facility"

        nF = len(self.instance["facilities"])
        for fid in sol["opened_facilities"]:
            assert 0 <= fid < nF, f"Invalid facility index {fid}"

    def test_solution_feasibility(self):
        """Opened facilities must have enough capacity for all scenarios."""
        with open("/app/solution.json") as f:
            sol = json.load(f)

        facs = self.instance["facilities"]
        opened = sol["opened_facilities"]
        total_cap = sum(facs[i]["capacity"] for i in opened)

        for s_idx, scen in enumerate(self.instance["scenarios"]):
            total_demand = sum(scen["demands"])
            assert total_cap >= total_demand, (
                f"Scenario {s_idx}: total demand {total_demand} exceeds "
                f"total capacity {total_cap} of opened facilities {opened}"
            )

    def test_solution_feasibility_per_scenario(self):
        """Verify that an optimal assignment exists for each scenario."""
        with open("/app/solution.json") as f:
            sol = json.load(f)

        facs = self.instance["facilities"]
        custs = self.instance["customers"]
        scens = self.instance["scenarios"]
        unit_cost = self.instance["unit_transport_cost"]
        opened = sol["opened_facilities"]
        nC = len(custs)

        for s_idx, scen in enumerate(scens):
            prob = LpProblem(f"feasibility_s{s_idx}", LpMinimize)
            x = {}
            for i in opened:
                for j in range(nC):
                    x[i, j] = LpVariable(f"x_{i}_{j}", lowBound=0)

            prob += lpSum(x[i, j] for i in opened for j in range(nC))

            for j in range(nC):
                prob += lpSum(x[i, j] for i in opened) == 1

            for i in opened:
                prob += (
                    lpSum(scen["demands"][j] * x[i, j] for j in range(nC))
                    <= facs[i]["capacity"]
                )

            prob.solve(PULP_CBC_CMD(msg=0))
            assert prob.status == 1, (
                f"Scenario {s_idx}: infeasible assignment with facilities {opened}"
            )

    def test_objective_near_optimal(self):
        """Reported objective must be within 1% of the true DEP optimal."""
        with open("/app/solution.json") as f:
            sol = json.load(f)

        reported = sol["objective_value"]
        dep_opt = self.dep_optimal

        # Compute the true objective for the opened facilities
        facs = self.instance["facilities"]
        custs = self.instance["customers"]
        scens = self.instance["scenarios"]
        unit_cost = self.instance["unit_transport_cost"]
        opened = sol["opened_facilities"]
        nC = len(custs)

        fixed_cost = sum(facs[i]["fixed_cost"] for i in opened)
        transport_cost = 0.0

        for s_idx, scen in enumerate(scens):
            prob = LpProblem(f"transport_s{s_idx}", LpMinimize)
            x = {}
            for i in opened:
                for j in range(nC):
                    dist = euclidean_dist(
                        facs[i]["x"], facs[i]["y"], custs[j]["x"], custs[j]["y"]
                    )
                    x[i, j] = LpVariable(f"x_{i}_{j}", lowBound=0)

            obj = 0
            for i in opened:
                for j in range(nC):
                    dist = euclidean_dist(
                        facs[i]["x"], facs[i]["y"], custs[j]["x"], custs[j]["y"]
                    )
                    obj += unit_cost * dist * scen["demands"][j] * x[i, j]
            prob += obj

            for j in range(nC):
                prob += lpSum(x[i, j] for i in opened) == 1

            for i in opened:
                prob += (
                    lpSum(scen["demands"][j] * x[i, j] for j in range(nC))
                    <= facs[i]["capacity"]
                )

            prob.solve(PULP_CBC_CMD(msg=0))
            assert prob.status == 1
            transport_cost += scen["probability"] * value(prob.objective)

        true_obj = fixed_cost + transport_cost

        # Check the reported value is close to the computed true objective
        assert abs(reported - true_obj) / max(abs(true_obj), 1e-9) < 0.02, (
            f"Reported objective {reported:.4f} differs from computed "
            f"objective {true_obj:.4f} for the given facilities"
        )

        # Check the solution is near-optimal compared to DEP
        assert true_obj <= dep_opt * 1.01 + 1e-6, (
            f"Solution objective {true_obj:.4f} exceeds DEP optimal "
            f"{dep_opt:.4f} by more than 1%"
        )
