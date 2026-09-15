
"""
Verification tests for the cutting stock optimization task.
Tests check structural validity, feasibility, optimality bounds,
and compare against an independent column generation reference solver.
"""

import json
import math
import os
import pytest


def load_problem():
    with open('/app/data/problem.json') as f:
        return json.load(f)


def load_results():
    with open('/app/results.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.isfile('/app/results.json'), "results.json not found"
        results = load_results()
        assert isinstance(results, dict)

    def test_has_total_rolls(self):
        results = load_results()
        assert 'total_rolls' in results, "Missing 'total_rolls' field"
        assert isinstance(results['total_rolls'], int), "total_rolls must be int"
        assert results['total_rolls'] > 0, "total_rolls must be positive"

    def test_has_lp_bound(self):
        results = load_results()
        assert 'lp_bound' in results, "Missing 'lp_bound' field"
        assert isinstance(results['lp_bound'], (int, float)), "lp_bound must be numeric"
        assert results['lp_bound'] > 0, "lp_bound must be positive"

    def test_has_patterns(self):
        results = load_results()
        assert 'patterns' in results, "Missing 'patterns' field"
        assert isinstance(results['patterns'], list), "patterns must be a list"
        assert len(results['patterns']) > 0, "patterns must be non-empty"

    def test_pattern_structure(self):
        results = load_results()
        for i, pat in enumerate(results['patterns']):
            assert 'cuts' in pat, f"Pattern {i}: missing 'cuts'"
            assert 'count' in pat, f"Pattern {i}: missing 'count'"
            assert isinstance(pat['cuts'], dict), f"Pattern {i}: cuts must be dict"
            assert isinstance(pat['count'], int), f"Pattern {i}: count must be int"


# ---------------------------------------------------------------------------
# Feasibility tests
# ---------------------------------------------------------------------------

class TestFeasibility:
    def test_all_demands_met(self):
        problem = load_problem()
        results = load_results()

        # Accumulate total production per width
        total_cuts = {}
        for pat in results['patterns']:
            count = pat['count']
            for width_str, num_cuts in pat['cuts'].items():
                w = int(width_str)
                total_cuts[w] = total_cuts.get(w, 0) + num_cuts * count

        for item in problem['items']:
            w = item['width']
            d = item['demand']
            produced = total_cuts.get(w, 0)
            assert produced >= d, (
                f"Demand not met for width {w}: need {d}, produced {produced}"
            )

    def test_no_pattern_exceeds_stock_width(self):
        problem = load_problem()
        results = load_results()
        sw = problem['stock_width']

        for i, pat in enumerate(results['patterns']):
            total_width = sum(int(w) * c for w, c in pat['cuts'].items())
            assert total_width <= sw, (
                f"Pattern {i} exceeds stock width: {total_width} > {sw}"
            )

    def test_positive_counts(self):
        results = load_results()
        for i, pat in enumerate(results['patterns']):
            assert pat['count'] > 0, f"Pattern {i} has non-positive count {pat['count']}"

    def test_positive_cut_counts(self):
        results = load_results()
        for i, pat in enumerate(results['patterns']):
            for w, c in pat['cuts'].items():
                assert c > 0, f"Pattern {i}, width {w}: non-positive cut count {c}"

    def test_valid_widths_only(self):
        problem = load_problem()
        results = load_results()
        valid = {item['width'] for item in problem['items']}

        for i, pat in enumerate(results['patterns']):
            for width_str in pat['cuts']:
                w = int(width_str)
                assert w in valid, f"Pattern {i} uses invalid width {w}"

    def test_total_rolls_consistent(self):
        results = load_results()
        computed = sum(p['count'] for p in results['patterns'])
        assert computed == results['total_rolls'], (
            f"total_rolls mismatch: reported {results['total_rolls']}, "
            f"sum of counts {computed}"
        )


# ---------------------------------------------------------------------------
# Optimality bound tests
# ---------------------------------------------------------------------------

class TestOptimality:
    def test_material_lower_bound(self):
        problem = load_problem()
        results = load_results()

        total_len = sum(it['width'] * it['demand'] for it in problem['items'])
        mat_lb = math.ceil(total_len / problem['stock_width'])

        assert results['total_rolls'] >= mat_lb, (
            f"Solution ({results['total_rolls']}) below material lower bound ({mat_lb})"
        )

    def test_lp_bound_is_lower_bound(self):
        results = load_results()
        assert results['lp_bound'] <= results['total_rolls'] + 0.01, (
            f"LP bound ({results['lp_bound']}) exceeds total_rolls ({results['total_rolls']})"
        )

    def test_near_optimal_gap(self):
        results = load_results()
        lp_ceil = math.ceil(results['lp_bound'] - 1e-9)
        assert results['total_rolls'] <= lp_ceil + 1, (
            f"Solution ({results['total_rolls']}) exceeds ceil(lp_bound)+1 = {lp_ceil + 1}"
        )


# ---------------------------------------------------------------------------
# Reference solver comparison
# ---------------------------------------------------------------------------

class TestReferenceSolver:
    """
    Run an independent column generation solver and compare.
    """

    def _run_reference_colgen(self):
        from pulp import (
            LpProblem, LpMinimize, LpMaximize, LpVariable,
            lpSum, value, PULP_CBC_CMD, LpStatusOptimal
        )

        problem = load_problem()
        sw = problem['stock_width']
        items = problem['items']
        n = len(items)
        widths = [it['width'] for it in items]
        demands = [it['demand'] for it in items]

        # Basic patterns
        patterns = []
        for i in range(n):
            mf = sw // widths[i]
            if mf > 0:
                p = [0] * n
                p[i] = mf
                patterns.append(p)

        # Column generation
        lp_val = None
        for _ in range(1000):
            prob = LpProblem("Ref_Master", LpMinimize)
            x = [LpVariable(f"x{j}", lowBound=0) for j in range(len(patterns))]
            prob += lpSum(x)

            cstrs = []
            for i in range(n):
                c = lpSum(patterns[j][i] * x[j]
                          for j in range(len(patterns))) >= demands[i]
                prob += c
                cstrs.append(c)

            prob.solve(PULP_CBC_CMD(msg=0))
            lp_val = value(prob.objective)

            duals = []
            for i in range(n):
                pi = cstrs[i].pi
                duals.append(pi if pi is not None else 0.0)

            knap = LpProblem("Ref_Knap", LpMaximize)
            y = [LpVariable(f"y{i}", lowBound=0, upBound=sw // widths[i],
                            cat='Integer') for i in range(n)]
            knap += lpSum(duals[i] * y[i] for i in range(n))
            knap += lpSum(widths[i] * y[i] for i in range(n)) <= sw
            knap.solve(PULP_CBC_CMD(msg=0))

            if knap.status != LpStatusOptimal or value(knap.objective) <= 1.0 + 1e-6:
                break

            new_p = [int(round(value(y[i]))) for i in range(n)]
            if all(c == 0 for c in new_p):
                break
            patterns.append(new_p)

        # MIP
        mip = LpProblem("Ref_MIP", LpMinimize)
        xi = [LpVariable(f"x{j}", lowBound=0, cat='Integer')
              for j in range(len(patterns))]
        mip += lpSum(xi)
        for i in range(n):
            mip += lpSum(patterns[j][i] * xi[j]
                         for j in range(len(patterns))) >= demands[i]
        mip.solve(PULP_CBC_CMD(msg=0))

        ref_total = int(round(value(mip.objective)))
        return lp_val, ref_total

    def test_against_reference(self):
        results = load_results()
        ref_lp, ref_total = self._run_reference_colgen()

        assert results['total_rolls'] <= ref_total + 2, (
            f"Agent solution ({results['total_rolls']}) exceeds reference "
            f"optimal ({ref_total}) by more than 2"
        )

    def test_lp_bound_matches_reference(self):
        results = load_results()
        ref_lp, _ = self._run_reference_colgen()

        assert abs(results['lp_bound'] - ref_lp) <= 1.5, (
            f"Agent LP bound ({results['lp_bound']}) differs from reference "
            f"LP bound ({ref_lp}) by more than 1.5"
        )
