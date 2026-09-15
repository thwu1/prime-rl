#!/usr/bin/env python3

"""
Netlib LP Benchmark Analysis — Reference Solution

Decompresses Netlib compressed MPS files, solves each LP with HiGHS,
and performs optimality verification and basis analysis.
"""

import subprocess
import json
import os
import math
import numpy as np


def setup_emps():
    """Download and compile the Netlib emps decompressor."""
    emps_bin = '/tmp/emps'
    if os.path.exists(emps_bin):
        return emps_bin

    subprocess.run(
        ['curl', '-sfL', '-o', '/tmp/emps.c',
         'https://www.netlib.org/lp/data/emps.c'],
        check=True
    )

    try:
        subprocess.run(
            ['gcc', '-o', emps_bin, '/tmp/emps.c'],
            check=True, capture_output=True
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ['gcc', '-o', emps_bin, '/tmp/emps.c', '-lm'],
            check=True
        )

    return emps_bin


def decompress_problems(emps_bin, problems, data_dir, mps_dir):
    """Decompress all Netlib compressed files into standard MPS."""
    os.makedirs(mps_dir, exist_ok=True)
    for prob in problems:
        compressed = os.path.join(data_dir, prob)
        mps_file = os.path.join(mps_dir, f'{prob}.mps')
        with open(compressed, 'r') as fin:
            with open(mps_file, 'w') as fout:
                subprocess.run([emps_bin], stdin=fin, stdout=fout,
                               check=True)
    return mps_dir


def compute_basis_condition_log10(h):
    """Compute log10 of the 1-norm condition number of the optimal basis matrix."""
    nr = h.getNumRow()
    nc = h.getNumCol()

    basis = h.getBasis()
    col_status = [int(s) for s in basis.col_status]
    row_status = [int(s) for s in basis.row_status]

    BASIC = 1

    lp = h.getLp()
    starts = list(lp.a_matrix_.start_)
    indices = list(lp.a_matrix_.index_)
    values = list(lp.a_matrix_.value_)

    B = np.zeros((nr, nr))
    b_col = 0

    # Columns from constraint matrix A for basic structural variables
    for j in range(nc):
        if col_status[j] == BASIC:
            for k in range(starts[j], starts[j + 1]):
                B[indices[k], b_col] = values[k]
            b_col += 1

    # Identity columns for basic row (slack/surplus) variables
    for i in range(nr):
        if row_status[i] == BASIC:
            B[i, b_col] = 1.0
            b_col += 1

    assert b_col == nr, f"Expected {nr} basic columns, got {b_col}"

    cond = np.linalg.cond(B, 1)
    return math.log10(max(cond, 1.0))


def solve_and_analyze(mps_file, prob_name):
    """Solve an LP from MPS and extract optimality analysis data."""
    import highspy

    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.readModel(mps_file)
    h.run()

    nr = h.getNumRow()
    nc = h.getNumCol()
    _, obj_val = h.getInfoValue("objective_function_value")
    _, max_pi = h.getInfoValue("max_primal_infeasibility")
    _, max_di = h.getInfoValue("max_dual_infeasibility")

    sol = h.getSolution()
    col_values = list(sol.col_value)
    col_duals = list(sol.col_dual)
    row_values = list(sol.row_value)

    basis = h.getBasis()
    col_status = [int(s) for s in basis.col_status]
    row_status = [int(s) for s in basis.row_status]

    BASIC = 1
    LOWER = 0
    UPPER = 2

    num_basic = (sum(1 for s in col_status if s == BASIC) +
                 sum(1 for s in row_status if s == BASIC))

    # Complementary slackness violation
    max_cs = 0.0
    for j in range(nc):
        rc = col_duals[j]
        s = col_status[j]
        if s == BASIC:
            max_cs = max(max_cs, abs(rc))
        elif s == LOWER:
            max_cs = max(max_cs, max(0.0, -rc))
        elif s == UPPER:
            max_cs = max(max_cs, max(0.0, rc))

    col_lower, col_upper = _get_col_bounds(h, nc)
    row_lower, row_upper = _get_row_bounds(h, nr)

    # Degenerate basic variables
    tol = 1e-8
    num_degenerate = 0

    for j in range(nc):
        if col_status[j] == BASIC:
            val = col_values[j]
            lb, ub = col_lower[j], col_upper[j]
            if abs(val - lb) < tol or (ub < 1e20 and abs(val - ub) < tol):
                num_degenerate += 1

    for i in range(nr):
        if row_status[i] == BASIC:
            val = row_values[i]
            lb, ub = row_lower[i], row_upper[i]
            at_lb = (lb > -1e20 and abs(val - lb) < tol)
            at_ub = (ub < 1e20 and abs(val - ub) < tol)
            if at_lb or at_ub:
                num_degenerate += 1

    # Alternative optima
    has_alt = False
    for j in range(nc):
        if col_status[j] != BASIC and abs(col_duals[j]) < 1e-8:
            has_alt = True
            break

    # Basis condition number
    cond_log10 = compute_basis_condition_log10(h)

    return {
        "optimal_value": obj_val,
        "num_constraints": nr,
        "num_variables": nc,
        "num_basic_variables": num_basic,
        "max_primal_infeasibility": max_pi,
        "max_dual_infeasibility": max_di,
        "max_complementary_slackness_violation": max_cs,
        "num_degenerate_basics": num_degenerate,
        "has_alternative_optima": has_alt,
        "basis_condition_number_log10": cond_log10,
    }


def _get_col_bounds(h, nc):
    """Extract column bounds from the HiGHS model."""
    try:
        lp = h.getLp()
        return list(lp.col_lower_), list(lp.col_upper_)
    except Exception:
        pass
    return [0.0] * nc, [1e30] * nc


def _get_row_bounds(h, nr):
    """Extract row bounds from the HiGHS model."""
    try:
        lp = h.getLp()
        return list(lp.row_lower_), list(lp.row_upper_)
    except Exception:
        pass
    return [-1e30] * nr, [1e30] * nr


def main():
    with open('/app/spec.json') as f:
        spec = json.load(f)

    problems = spec['problems']
    data_dir = spec['data_dir']
    output_file = spec['output_file']

    emps = setup_emps()

    mps_dir = '/app/mps'
    decompress_problems(emps, problems, data_dir, mps_dir)

    results = {"problems": {}}
    for prob in problems:
        mps_file = os.path.join(mps_dir, f'{prob}.mps')
        analysis = solve_and_analyze(mps_file, prob)
        results["problems"][prob] = analysis

    ranking = sorted(
        problems,
        key=lambda p: results["problems"][p]["optimal_value"]
    )
    results["ranking_by_optimal_value"] = ranking

    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)


if __name__ == '__main__':
    main()
