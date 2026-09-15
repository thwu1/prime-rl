
"""
Tests for the multi-stock cutting stock optimization problem.
Independently enumerates all feasible patterns, solves LP and IP,
and verifies the agent's results against the ground-truth optimum.
"""

import json
import os
import pytest
from pulp import LpProblem, LpMinimize, LpVariable, lpSum, value, PULP_CBC_CMD


def load_instance():
    with open('/app/instance.json') as f:
        return json.load(f)


def load_results():
    with open('/app/results.json') as f:
        return json.load(f)


def enumerate_patterns(roll_width, item_widths):
    """Enumerate all feasible non-empty cutting patterns for a given roll width."""
    n = len(item_widths)
    patterns = []

    def generate(idx, remaining, current):
        if idx == n:
            if any(x > 0 for x in current):
                patterns.append(list(current))
            return
        max_count = remaining // item_widths[idx]
        for count in range(max_count + 1):
            current.append(count)
            generate(idx + 1, remaining - count * item_widths[idx], current)
            current.pop()

    generate(0, roll_width, [])
    return patterns


def compute_reference(instance):
    """
    Compute reference LP bound and IP optimal via full pattern enumeration.
    Returns (lp_bound, ip_optimal).
    """
    stock_types = instance['stock_types']
    items = instance['items']
    n_items = len(items)
    widths = [item['width'] for item in items]
    demands = [item['demand'] for item in items]

    # Enumerate patterns for each stock type
    all_patterns = []
    for s_idx, stock in enumerate(stock_types):
        pats = enumerate_patterns(stock['width'], widths)
        for p in pats:
            all_patterns.append((s_idx, p))

    n_patterns = len(all_patterns)

    # Solve LP relaxation
    prob_lp = LpProblem("Ref_LP", LpMinimize)
    x_lp = [LpVariable(f"x_{j}", lowBound=0) for j in range(n_patterns)]
    prob_lp += lpSum(
        stock_types[all_patterns[j][0]]['cost'] * x_lp[j]
        for j in range(n_patterns)
    )
    for i in range(n_items):
        prob_lp += (
            lpSum(all_patterns[j][1][i] * x_lp[j] for j in range(n_patterns))
            >= demands[i]
        )
    prob_lp.solve(PULP_CBC_CMD(msg=0))
    ref_lp = value(prob_lp.objective)

    # Solve IP
    prob_ip = LpProblem("Ref_IP", LpMinimize)
    x_ip = [LpVariable(f"x_{j}", lowBound=0, cat='Integer')
            for j in range(n_patterns)]
    prob_ip += lpSum(
        stock_types[all_patterns[j][0]]['cost'] * x_ip[j]
        for j in range(n_patterns)
    )
    for i in range(n_items):
        prob_ip += (
            lpSum(all_patterns[j][1][i] * x_ip[j] for j in range(n_patterns))
            >= demands[i]
        )
    prob_ip.solve(PULP_CBC_CMD(msg=0))
    ref_ip = value(prob_ip.objective)

    return ref_lp, ref_ip


@pytest.fixture(scope="module")
def instance():
    return load_instance()


@pytest.fixture(scope="module")
def results():
    return load_results()


@pytest.fixture(scope="module")
def reference(instance):
    return compute_reference(instance)


class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), \
            "/app/results.json not found"

    def test_has_required_fields(self, results):
        assert 'lp_bound' in results, "Missing 'lp_bound'"
        assert 'total_cost' in results, "Missing 'total_cost'"
        assert 'patterns' in results, "Missing 'patterns'"

    def test_field_types(self, results):
        assert isinstance(results['lp_bound'], (int, float)), \
            "lp_bound must be numeric"
        assert isinstance(results['total_cost'], (int, float)), \
            "total_cost must be numeric"
        assert isinstance(results['patterns'], list), \
            "patterns must be a list"
        assert len(results['patterns']) > 0, \
            "patterns list is empty"


class TestPatternValidity:
    def test_patterns_fit_stock(self, results, instance):
        """Each pattern must fit within its stock type width."""
        stock_types = instance['stock_types']
        widths = [item['width'] for item in instance['items']]
        n_items = len(widths)

        for idx, p in enumerate(results['patterns']):
            assert 0 <= p['stock_type'] < len(stock_types), \
                f"Pattern {idx}: invalid stock_type {p['stock_type']}"
            assert len(p['cuts']) == n_items, \
                f"Pattern {idx}: has {len(p['cuts'])} entries, expected {n_items}"
            assert all(
                isinstance(c, (int, float)) and c >= 0 and float(c) == int(c)
                for c in p['cuts']
            ), f"Pattern {idx}: cuts must be non-negative integers"
            assert p['count'] > 0, \
                f"Pattern {idx}: count must be positive"

            stock_width = stock_types[p['stock_type']]['width']
            total_width = sum(c * w for c, w in zip(p['cuts'], widths))
            assert total_width <= stock_width, \
                f"Pattern {idx}: total width {total_width} exceeds " \
                f"stock width {stock_width}"

    def test_demands_satisfied(self, results, instance):
        """All item demands must be fully met."""
        items = instance['items']
        n_items = len(items)
        demands = [item['demand'] for item in items]

        supplied = [0] * n_items
        for p in results['patterns']:
            for i in range(n_items):
                supplied[i] += p['cuts'][i] * p['count']

        for i in range(n_items):
            assert supplied[i] >= demands[i], \
                f"Item {i} (w={items[i]['width']}): " \
                f"supplied {supplied[i]} < demand {demands[i]}"


class TestOptimality:
    def test_cost_consistent(self, results, instance):
        """Reported total_cost must match sum of pattern costs."""
        stock_types = instance['stock_types']
        computed_cost = sum(
            stock_types[p['stock_type']]['cost'] * p['count']
            for p in results['patterns']
        )
        assert abs(computed_cost - results['total_cost']) < 0.5, \
            f"Reported cost {results['total_cost']} != " \
            f"computed cost {computed_cost}"

    def test_lp_bound_is_lower_bound(self, results):
        """LP bound must be <= total cost (relaxation is a lower bound)."""
        assert results['lp_bound'] <= results['total_cost'] + 0.01, \
            f"LP bound {results['lp_bound']} > total cost " \
            f"{results['total_cost']}"

    def test_lp_bound_correct(self, results, reference):
        """LP bound must match the reference LP optimal."""
        ref_lp, _ = reference
        assert abs(results['lp_bound'] - ref_lp) < 0.1, \
            f"LP bound {results['lp_bound']} != reference {ref_lp:.6f}"

    def test_total_cost_optimal(self, results, reference):
        """Total cost must match reference IP optimal."""
        _, ref_ip = reference
        assert abs(results['total_cost'] - ref_ip) < 0.5, \
            f"Total cost {results['total_cost']} != reference IP " \
            f"optimal {ref_ip}"
