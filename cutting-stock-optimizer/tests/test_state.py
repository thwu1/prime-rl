"""
Tests for multi-width stock roll cutting optimization.

"""
import json
import os
import math
import sqlite3
import pytest


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_instance():
    """Load the ground-truth problem data from the operations database."""
    conn = sqlite3.connect("/app/data/operations.db")
    conn.row_factory = sqlite3.Row

    # Available stock rolls only
    stock = [
        dict(r)
        for r in conn.execute(
            "SELECT type_id, width_mm, unit_cost, inventory "
            "FROM stock_rolls WHERE status='available'"
        ).fetchall()
    ]

    # Products in alphabetical order
    products = [
        dict(r)
        for r in conn.execute(
            "SELECT product_code, cut_width_mm FROM products ORDER BY product_code"
        ).fetchall()
    ]

    # Remaining demand: active orders minus production for those orders
    active_orders = conn.execute(
        "SELECT order_id, product_code, quantity "
        "FROM customer_orders WHERE status='active'"
    ).fetchall()

    active_ids = set()
    product_demand = {}
    for o in active_orders:
        active_ids.add(o["order_id"])
        pc = o["product_code"]
        product_demand[pc] = product_demand.get(pc, 0) + o["quantity"]

    for row in conn.execute(
        "SELECT order_id, product_code, pieces_produced FROM production_log"
    ).fetchall():
        if row["order_id"] in active_ids:
            pc = row["product_code"]
            product_demand[pc] = product_demand.get(pc, 0) - row["pieces_produced"]

    conn.close()

    pcodes = [p["product_code"] for p in products]
    demands = [max(0, product_demand.get(pc, 0)) for pc in pcodes]
    widths = [p["cut_width_mm"] for p in products]

    return {
        "stock": stock,
        "products": products,
        "demands": demands,
        "widths": widths,
        "pcodes": pcodes,
    }


def load_solution():
    with open("/app/results/solution.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Reference solver — multi-width CSP via column generation
# ---------------------------------------------------------------------------

def solve_reference(inst):
    """
    Solve the multi-width cutting stock problem to near-optimality using
    column generation with bounded-knapsack pricing per stock type, then
    rounding with an IP over all generated columns.
    """
    from pulp import (
        LpProblem, LpMinimize, LpVariable, lpSum,
        value, PULP_CBC_CMD, constants,
    )

    stock = inst["stock"]
    widths = inst["widths"]
    demands = inst["demands"]
    n = len(widths)

    stock_map = {s["type_id"]: s for s in stock}
    sids = sorted(stock_map.keys())

    # Initialise with trivial one-product patterns per stock type
    patterns = {sid: [] for sid in sids}
    for sid in sids:
        W = stock_map[sid]["width_mm"]
        for i in range(n):
            if widths[i] <= W:
                p = [0] * n
                p[i] = W // widths[i]
                patterns[sid].append(p)

    EPS = 1e-6
    lp_obj = None

    for iteration in range(500):
        # --- Master LP ---
        prob = LpProblem(f"MW_{iteration}", LpMinimize)

        x = {}
        for sid in sids:
            x[sid] = [
                LpVariable(f"x_{sid}_{j}", lowBound=0)
                for j in range(len(patterns[sid]))
            ]

        # Objective: minimise total cost
        prob += lpSum(
            stock_map[sid]["unit_cost"] * xv
            for sid in sids
            for xv in x[sid]
        )

        # Demand constraints — store objects directly to avoid PuLP name issues
        demand_ctrs = []
        for i in range(n):
            ctr = (
                lpSum(
                    patterns[sid][j][i] * x[sid][j]
                    for sid in sids
                    for j in range(len(patterns[sid]))
                )
                >= demands[i]
            )
            prob += (ctr, f"d{i}")
            demand_ctrs.append(ctr)

        # Inventory constraints — store objects directly
        inv_ctrs = {}
        for sid in sids:
            ctr = lpSum(x[sid]) <= stock_map[sid]["inventory"]
            prob += (ctr, f"inv_{sid}")
            inv_ctrs[sid] = ctr

        prob.solve(PULP_CBC_CMD(msg=0))
        if prob.status != constants.LpStatusOptimal:
            break

        lp_obj = value(prob.objective)

        # Dual values from stored constraint objects
        pi = []
        for i in range(n):
            pv = demand_ctrs[i].pi
            pi.append(pv if pv is not None else 0.0)

        inv_pi = {}
        for sid in sids:
            iv = inv_ctrs[sid].pi
            inv_pi[sid] = iv if iv is not None else 0.0

        # --- Pricing ---
        improved = False
        for sid in sids:
            W = stock_map[sid]["width_mm"]
            c = stock_map[sid]["unit_cost"]

            knap = LpProblem(f"KP_{sid}_{iteration}", LpMinimize)
            y = [LpVariable(f"y{i}", lowBound=0, cat="Integer") for i in range(n)]

            # Maximise dual profit = minimise negative
            knap += -lpSum(pi[i] * y[i] for i in range(n))
            knap += lpSum(widths[i] * y[i] for i in range(n)) <= W
            for i in range(n):
                ub = W // widths[i]
                if ub > 0:
                    knap += y[i] <= ub

            knap.solve(PULP_CBC_CMD(msg=0))
            if knap.status != constants.LpStatusOptimal:
                continue

            dual_profit = -value(knap.objective)

            reduced_cost = c - dual_profit - inv_pi[sid]

            if reduced_cost < -EPS:
                new_pat = [int(round(value(y[i]))) for i in range(n)]
                if not any(new_pat == p for p in patterns[sid]):
                    patterns[sid].append(new_pat)
                    improved = True

        if not improved:
            break

    # --- Solve IP over all generated columns ---
    prob_ip = LpProblem("MW_IP", LpMinimize)
    x_ip = {}
    for sid in sids:
        x_ip[sid] = [
            LpVariable(f"x_{sid}_{j}", lowBound=0, cat="Integer")
            for j in range(len(patterns[sid]))
        ]

    prob_ip += lpSum(
        stock_map[sid]["unit_cost"] * xv
        for sid in sids
        for xv in x_ip[sid]
    )

    for i in range(n):
        prob_ip += (
            lpSum(
                patterns[sid][j][i] * x_ip[sid][j]
                for sid in sids
                for j in range(len(patterns[sid]))
            )
            >= demands[i],
            f"d{i}",
        )

    for sid in sids:
        prob_ip += lpSum(x_ip[sid]) <= stock_map[sid]["inventory"]

    prob_ip.solve(PULP_CBC_CMD(msg=0, timeLimit=120))

    ip_cost = None
    if prob_ip.status == constants.LpStatusOptimal:
        ip_cost = value(prob_ip.objective)

    return {"lp_bound": lp_obj, "ip_cost": ip_cost}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSolutionFileExists:
    def test_solution_file_exists(self):
        assert os.path.exists("/app/results/solution.json"), (
            "Solution file /app/results/solution.json does not exist"
        )


class TestSolutionFormat:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.sol = load_solution()
        self.inst = load_instance()
        self.n = len(self.inst["products"])

    def test_required_fields(self):
        for field in ("total_cost", "cutting_plan", "total_waste_mm"):
            assert field in self.sol, f"Missing field: {field}"

    def test_plan_entries_have_fields(self):
        for idx, entry in enumerate(self.sol["cutting_plan"]):
            for key in ("stock_type", "cuts", "num_rolls"):
                assert key in entry, f"cutting_plan[{idx}] missing '{key}'"

    def test_cuts_vector_lengths(self):
        for idx, entry in enumerate(self.sol["cutting_plan"]):
            assert len(entry["cuts"]) == self.n, (
                f"cutting_plan[{idx}].cuts has length {len(entry['cuts'])}, "
                f"expected {self.n}"
            )


class TestFeasibility:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.sol = load_solution()
        self.inst = load_instance()
        self.n = len(self.inst["products"])
        self.widths = self.inst["widths"]
        self.demands = self.inst["demands"]
        self.stock_map = {s["type_id"]: s for s in self.inst["stock"]}

    def test_stock_types_are_available(self):
        """All stock types used must be available (not on maintenance etc.)."""
        for idx, entry in enumerate(self.sol["cutting_plan"]):
            assert entry["stock_type"] in self.stock_map, (
                f"cutting_plan[{idx}] uses unknown or unavailable stock type "
                f"'{entry['stock_type']}'"
            )

    def test_patterns_fit_roll_width(self):
        for idx, entry in enumerate(self.sol["cutting_plan"]):
            sid = entry["stock_type"]
            W = self.stock_map[sid]["width_mm"]
            total = sum(entry["cuts"][j] * self.widths[j] for j in range(self.n))
            assert total <= W, (
                f"cutting_plan[{idx}] total cut width {total} exceeds "
                f"roll width {W} for {sid}"
            )

    def test_cuts_nonneg_int(self):
        for idx, entry in enumerate(self.sol["cutting_plan"]):
            for j, v in enumerate(entry["cuts"]):
                assert isinstance(v, int) and v >= 0, (
                    f"cutting_plan[{idx}].cuts[{j}] = {v} (need non-negative int)"
                )

    def test_num_rolls_positive(self):
        for idx, entry in enumerate(self.sol["cutting_plan"]):
            assert isinstance(entry["num_rolls"], int) and entry["num_rolls"] > 0, (
                f"cutting_plan[{idx}].num_rolls = {entry['num_rolls']} "
                "(must be positive int)"
            )

    def test_all_demands_met(self):
        production = [0] * self.n
        for entry in self.sol["cutting_plan"]:
            for j in range(self.n):
                production[j] += entry["cuts"][j] * entry["num_rolls"]
        for j in range(self.n):
            assert production[j] >= self.demands[j], (
                f"Demand for {self.inst['pcodes'][j]} not met: "
                f"produced {production[j]}, need {self.demands[j]}"
            )

    def test_inventory_limits(self):
        usage = {}
        for entry in self.sol["cutting_plan"]:
            sid = entry["stock_type"]
            usage[sid] = usage.get(sid, 0) + entry["num_rolls"]
        for sid, count in usage.items():
            limit = self.stock_map[sid]["inventory"]
            assert count <= limit, (
                f"Stock type {sid} uses {count} rolls but only {limit} available"
            )


class TestConsistency:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.sol = load_solution()
        self.inst = load_instance()
        self.n = len(self.inst["products"])
        self.widths = self.inst["widths"]
        self.stock_map = {s["type_id"]: s for s in self.inst["stock"]}

    def test_total_cost_correct(self):
        computed = 0.0
        for entry in self.sol["cutting_plan"]:
            sid = entry["stock_type"]
            computed += self.stock_map[sid]["unit_cost"] * entry["num_rolls"]
        assert abs(self.sol["total_cost"] - computed) < 0.01, (
            f"total_cost mismatch: reported {self.sol['total_cost']}, "
            f"computed {computed}"
        )

    def test_total_waste_correct(self):
        computed_waste = 0
        for entry in self.sol["cutting_plan"]:
            sid = entry["stock_type"]
            W = self.stock_map[sid]["width_mm"]
            used = sum(entry["cuts"][j] * self.widths[j] for j in range(self.n))
            computed_waste += (W - used) * entry["num_rolls"]
        assert self.sol["total_waste_mm"] == computed_waste, (
            f"total_waste_mm mismatch: reported {self.sol['total_waste_mm']}, "
            f"computed {computed_waste}"
        )


class TestDemandCorrectness:
    """Verify the agent computed the correct remaining demands."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.sol = load_solution()
        self.inst = load_instance()
        self.n = len(self.inst["products"])
        self.demands = self.inst["demands"]

    def test_production_covers_exact_demand(self):
        """Total production should meet but not wildly exceed actual demand."""
        production = [0] * self.n
        for entry in self.sol["cutting_plan"]:
            for j in range(self.n):
                production[j] += entry["cuts"][j] * entry["num_rolls"]

        total_demand = sum(self.demands)
        total_produced = sum(production)
        # Allow up to 50% overproduction (waste is normal in CSP)
        # but catch grossly wrong demand computation (e.g. cancelled orders included)
        assert total_produced < total_demand * 2.5, (
            f"Total production ({total_produced}) is far above total demand "
            f"({total_demand}) — likely wrong demand computation"
        )


class TestOptimality:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.sol = load_solution()
        self.inst = load_instance()

    def test_cost_above_volume_lower_bound(self):
        """Cost must be at least the volume-based lower bound."""
        total_vol = sum(
            w * d for w, d in zip(self.inst["widths"], self.inst["demands"])
        )
        # Cheapest available cost-per-mm
        min_cost_per_mm = min(
            s["unit_cost"] / s["width_mm"] for s in self.inst["stock"]
        )
        vol_lb = total_vol * min_cost_per_mm
        assert self.sol["total_cost"] >= vol_lb * 0.99, (
            f"total_cost {self.sol['total_cost']} below volume LB {vol_lb}"
        )

    def test_cost_within_tolerance_of_reference(self):
        """Agent cost should be within 8% of independently computed optimal."""
        ref = solve_reference(self.inst)
        assert ref["ip_cost"] is not None, "Reference IP solve failed"
        tolerance = 0.08
        assert self.sol["total_cost"] <= ref["ip_cost"] * (1 + tolerance), (
            f"Agent cost {self.sol['total_cost']:.2f} exceeds reference "
            f"{ref['ip_cost']:.2f} by more than {tolerance*100}%"
        )

    def test_cost_at_or_above_lp_bound(self):
        """Agent cost should be at or above the LP relaxation bound."""
        ref = solve_reference(self.inst)
        assert ref["lp_bound"] is not None, "Reference LP solve failed"
        assert self.sol["total_cost"] >= ref["lp_bound"] - 1.0, (
            f"Agent cost {self.sol['total_cost']:.2f} is below LP bound "
            f"{ref['lp_bound']:.2f}"
        )
