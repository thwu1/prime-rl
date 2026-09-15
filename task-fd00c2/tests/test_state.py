
import csv
import json
import math
import sqlite3

import pytest
from pulp import (
    PULP_CBC_CMD,
    LpInteger,
    LpMinimize,
    LpProblem,
    LpVariable,
    lpSum,
    value,
)

SOLUTION_PATH = "/app/output/solution.json"
REGULAR_CSV = "/app/data/orders/regular_orders.csv"
PRIORITY_CSV = "/app/data/orders/priority_orders.csv"
STOCK_DB = "/app/data/inventory/stock.db"
LP_BOUND_TOLERANCE = 0.005  # 0.5% relative tolerance for LP bound comparison
ROLL_GAP_TOLERANCE = 0.02  # 2% gap tolerance for integer solution quality


def load_orders():
    """Load all orders from both CSV files."""
    orders = []
    with open(REGULAR_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            orders.append(
                {
                    "product_code": row["product_code"],
                    "width": int(row["width_mm"]),
                    "demand": int(row["quantity_required"]),
                }
            )
    with open(PRIORITY_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            orders.append(
                {
                    "product_code": row["item_code"],
                    "width": int(row["cut_width_mm"]),
                    "demand": int(row["units_needed"]),
                }
            )
    orders.sort(key=lambda x: x["product_code"])
    return orders


def load_stock_width():
    """Load stock roll width from SQLite database."""
    conn = sqlite3.connect(STOCK_DB)
    c = conn.cursor()
    c.execute("SELECT width_mm FROM stock_rolls LIMIT 1")
    width = c.fetchone()[0]
    conn.close()
    return width


def solve_bounded_knapsack(widths, profits, capacity, upper_bounds):
    """Bounded knapsack via DP with binary expansion. Returns (max_profit, pattern_dict)."""
    n = len(widths)

    # Binary expand items
    bin_items = []
    for i in range(n):
        if profits[i] <= 1e-10 or widths[i] > capacity:
            continue
        u = min(upper_bounds[i], capacity // widths[i])
        if u <= 0:
            continue
        rem = u
        k = 1
        while rem > 0:
            take = min(k, rem)
            bin_items.append((take * widths[i], take * profits[i], i, take))
            rem -= take
            k *= 2

    if not bin_items:
        return 0.0, {}

    nb = len(bin_items)
    dp = [0.0] * (capacity + 1)
    used = [[False] * (capacity + 1) for _ in range(nb)]

    for bi in range(nb):
        bw, bp = bin_items[bi][0], bin_items[bi][1]
        for w in range(capacity, bw - 1, -1):
            if dp[w - bw] + bp > dp[w] + 1e-12:
                dp[w] = dp[w - bw] + bp
                used[bi][w] = True

    best_w = 0
    for w in range(capacity + 1):
        if dp[w] > dp[best_w] + 1e-12:
            best_w = w

    pattern = {}
    w = best_w
    for bi in range(nb - 1, -1, -1):
        if used[bi][w]:
            _, _, orig_i, count = bin_items[bi]
            pattern[orig_i] = pattern.get(orig_i, 0) + count
            w -= bin_items[bi][0]

    return dp[best_w], pattern


def compute_lp_bound(widths, demands, stock_width):
    """Compute LP relaxation bound via Gilmore-Gomory column generation."""
    n = len(widths)

    # Initialize with single-item patterns
    patterns = []
    for i in range(n):
        if widths[i] <= stock_width:
            patterns.append({i: 1})

    for _ in range(500):
        num_p = len(patterns)
        prob = LpProblem("cg_verify", LpMinimize)
        x = [LpVariable(f"x_{p}", lowBound=0) for p in range(num_p)]
        prob += lpSum(x)

        for i in range(n):
            prob += (
                lpSum(patterns[p].get(i, 0) * x[p] for p in range(num_p))
                >= demands[i],
                f"d_{i}",
            )

        prob.solve(PULP_CBC_CMD(msg=0))
        if prob.status != 1:
            return None

        lp_val = value(prob.objective)

        duals = []
        for i in range(n):
            pi = prob.constraints[f"d_{i}"].pi
            duals.append(float(pi) if pi is not None else 0.0)

        ub = [min(demands[i], stock_width // widths[i]) for i in range(n)]
        profit, new_pat = solve_bounded_knapsack(widths, duals, stock_width, ub)

        if profit <= 1.0 + 1e-6:
            break

        patterns.append(new_pat)

    return lp_val


@pytest.fixture(scope="module")
def problem_data():
    orders = load_orders()
    stock_width = load_stock_width()
    return orders, stock_width


@pytest.fixture(scope="module")
def solution():
    with open(SOLUTION_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def lp_bound(problem_data):
    orders, stock_width = problem_data
    widths = [o["width"] for o in orders]
    demands = [o["demand"] for o in orders]
    bound = compute_lp_bound(widths, demands, stock_width)
    assert bound is not None, "Failed to compute LP bound independently"
    return bound


def test_solution_exists():
    """Solution file must exist and be valid JSON."""
    with open(SOLUTION_PATH) as f:
        sol = json.load(f)
    assert isinstance(sol, dict), "Solution must be a JSON object"


def test_required_fields(solution):
    """Solution must contain all required fields."""
    required = [
        "patterns",
        "total_rolls",
        "lp_relaxation_bound",
        "optimality_gap_pct",
        "total_waste_mm",
    ]
    for key in required:
        assert key in solution, f"Missing required field: {key}"
    assert isinstance(solution["patterns"], list)
    assert len(solution["patterns"]) > 0, "Must have at least one cutting pattern"


def test_patterns_feasible(solution, problem_data):
    """Every cutting pattern must fit within the stock roll width."""
    orders, stock_width = problem_data
    code_to_width = {o["product_code"]: o["width"] for o in orders}
    valid_codes = set(code_to_width.keys())

    for idx, pattern in enumerate(solution["patterns"]):
        assert "items" in pattern, f"Pattern {idx} missing 'items'"
        assert "rolls" in pattern, f"Pattern {idx} missing 'rolls'"
        assert isinstance(pattern["rolls"], int) and pattern["rolls"] > 0, (
            f"Pattern {idx} must have positive integer rolls count"
        )

        total_width = 0
        for code, count in pattern["items"].items():
            assert code in valid_codes, (
                f"Unknown product code '{code}' in pattern {idx}"
            )
            assert isinstance(count, int) and count > 0, (
                f"Item count for {code} in pattern {idx} must be a positive integer"
            )
            total_width += code_to_width[code] * count

        assert total_width <= stock_width, (
            f"Pattern {idx} exceeds stock width: {total_width} > {stock_width}"
        )


def test_demands_met(solution, problem_data):
    """All customer order quantities must be fully met."""
    orders, _ = problem_data
    code_to_demand = {o["product_code"]: o["demand"] for o in orders}

    produced = {}
    for pattern in solution["patterns"]:
        for code, count in pattern["items"].items():
            produced[code] = produced.get(code, 0) + count * pattern["rolls"]

    for code, demand in code_to_demand.items():
        actual = produced.get(code, 0)
        assert actual >= demand, (
            f"Demand not met for {code}: produced {actual} < required {demand}"
        )


def test_total_rolls_consistent(solution):
    """total_rolls must equal the sum of rolls across all patterns."""
    computed = sum(p["rolls"] for p in solution["patterns"])
    assert computed == solution["total_rolls"], (
        f"Inconsistent total_rolls: stated {solution['total_rolls']} != sum {computed}"
    )


def test_width_used_consistent(solution, problem_data):
    """width_used in each pattern must match the sum of item widths."""
    orders, _ = problem_data
    code_to_width = {o["product_code"]: o["width"] for o in orders}

    for idx, pattern in enumerate(solution["patterns"]):
        if "width_used" not in pattern:
            continue
        expected = sum(
            code_to_width[code] * count for code, count in pattern["items"].items()
        )
        assert pattern["width_used"] == expected, (
            f"Pattern {idx} width_used {pattern['width_used']} != computed {expected}"
        )


def test_waste_consistent(solution, problem_data):
    """total_waste_mm must match independently computed waste."""
    _, stock_width = problem_data
    code_to_width = {o["product_code"]: o["width"] for o in problem_data[0]}

    computed_waste = 0
    for pattern in solution["patterns"]:
        width_used = sum(
            code_to_width[code] * count for code, count in pattern["items"].items()
        )
        computed_waste += (stock_width - width_used) * pattern["rolls"]

    assert abs(computed_waste - solution["total_waste_mm"]) < 10, (
        f"Inconsistent waste: stated {solution['total_waste_mm']} != computed {computed_waste}"
    )


def test_lp_bound_correct(solution, lp_bound):
    """Agent's LP bound must match independently computed LP bound."""
    agent_bound = solution["lp_relaxation_bound"]
    rel_diff = abs(agent_bound - lp_bound) / max(lp_bound, 1.0)
    assert rel_diff < LP_BOUND_TOLERANCE, (
        f"LP bound mismatch: agent={agent_bound:.4f} vs computed={lp_bound:.4f} "
        f"(rel_diff={rel_diff:.6f})"
    )


def test_optimality_gap(solution, lp_bound):
    """Total rolls must be within acceptable gap of LP bound."""
    total_rolls = solution["total_rolls"]
    gap_pct = ((total_rolls - lp_bound) / lp_bound) * 100

    assert gap_pct <= ROLL_GAP_TOLERANCE * 100, (
        f"Solution quality too poor: {total_rolls} rolls, "
        f"LP bound={lp_bound:.4f}, gap={gap_pct:.2f}% > {ROLL_GAP_TOLERANCE * 100}%"
    )


def test_gap_field_consistent(solution, lp_bound):
    """Reported optimality_gap_pct must be consistent with actual gap."""
    total_rolls = solution["total_rolls"]
    expected_gap = ((total_rolls - lp_bound) / lp_bound) * 100

    assert abs(solution["optimality_gap_pct"] - expected_gap) < 0.5, (
        f"Reported gap {solution['optimality_gap_pct']:.4f}% doesn't match "
        f"computed gap {expected_gap:.4f}%"
    )
