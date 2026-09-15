#!/usr/bin/env python3

"""
Solve 8 Netlib LP benchmark problems, construct explicit dual LPs,
verify strong duality and complementary slackness conditions.

Dual construction follows standard LP duality theory (Bertsimas & Tsitsiklis):
  Primal (min):  constraint type -> dual variable sign
    E (=)  -> y_i free
    L (<=) -> y_i <= 0
    G (>=) -> y_i >= 0
  Primal variable bounds -> dual auxiliary variables
    x_j >= l_j -> w_lj >= 0 (dual of lower bound)
    x_j <= u_j -> w_uj >= 0 (dual of upper bound, after sign flip)

  Dual problem (max, converted to min for scipy):
    max  b^T y + l^T w_l - u^T w_u
    s.t. A^T y + w_l - w_u = c    (one equality per primal variable)
"""

import json
import os
import sys
import numpy as np
from scipy.optimize import linprog

PROBLEMS = ["afiro", "sc50a", "adlittle", "share2b", "kb2", "bore3d", "boeing2", "capri"]
DATA_DIR = "/app/data"
RESULTS_PATH = "/app/results.json"


def parse_mps(filepath):
    """Parse a standard fixed-column MPS file into LP components."""
    section = None
    obj_name = None
    row_names = []
    row_types = {}
    col_names = []
    col_set = set()
    coefficients = {}
    rhs_values = {}
    range_values = {}
    bound_specs = {}
    has_bounds_section = False
    has_ranges_section = False

    with open(filepath) as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue

            if line[0] not in (' ', '\t'):
                token = line.strip().split()[0] if line.strip() else ''
                if token == 'ROWS':
                    section = 'ROWS'
                elif token == 'COLUMNS':
                    section = 'COLUMNS'
                elif token == 'RHS':
                    section = 'RHS'
                elif token == 'RANGES':
                    section = 'RANGES'
                    has_ranges_section = True
                elif token == 'BOUNDS':
                    section = 'BOUNDS'
                    has_bounds_section = True
                elif token == 'ENDATA':
                    break
                elif token == 'NAME':
                    section = 'NAME'
                continue

            parts = line.split()
            if not parts:
                continue

            if section == 'ROWS':
                if len(parts) >= 2:
                    rtype, rname = parts[0], parts[1]
                    row_types[rname] = rtype
                    row_names.append(rname)
                    if rtype == 'N' and obj_name is None:
                        obj_name = rname

            elif section == 'COLUMNS':
                if len(parts) < 3:
                    continue
                if "'MARKER'" in line or "'INTORG'" in line or "'INTEND'" in line:
                    continue
                cname = parts[0]
                if cname not in col_set:
                    col_names.append(cname)
                    col_set.add(cname)
                coefficients[(parts[1], cname)] = float(parts[2])
                if len(parts) >= 5:
                    coefficients[(parts[3], cname)] = float(parts[4])

            elif section == 'RHS':
                if len(parts) >= 3:
                    rhs_values[parts[1]] = float(parts[2])
                    if len(parts) >= 5:
                        rhs_values[parts[3]] = float(parts[4])

            elif section == 'RANGES':
                if len(parts) >= 3:
                    range_values[parts[1]] = float(parts[2])
                    if len(parts) >= 5:
                        range_values[parts[3]] = float(parts[4])

            elif section == 'BOUNDS':
                if len(parts) >= 3:
                    btype = parts[0]
                    cname = parts[2]
                    if cname not in bound_specs:
                        bound_specs[cname] = {}
                    if btype == 'FR':
                        bound_specs[cname]['lo'] = None
                        bound_specs[cname]['up'] = None
                    elif btype == 'MI':
                        bound_specs[cname]['lo'] = None
                    elif btype == 'PL':
                        bound_specs[cname]['up'] = None
                    elif btype == 'BV':
                        bound_specs[cname]['lo'] = 0.0
                        bound_specs[cname]['up'] = 1.0
                    elif len(parts) >= 4:
                        val = float(parts[3])
                        if btype == 'UP':
                            bound_specs[cname]['up'] = val
                        elif btype == 'LO':
                            bound_specs[cname]['lo'] = val
                        elif btype == 'FX':
                            bound_specs[cname]['lo'] = val
                            bound_specs[cname]['up'] = val

    return {
        'obj_name': obj_name,
        'row_names': row_names,
        'row_types': row_types,
        'col_names': col_names,
        'coefficients': coefficients,
        'rhs_values': rhs_values,
        'range_values': range_values,
        'bound_specs': bound_specs,
        'has_bounds': has_bounds_section,
        'has_ranges': has_ranges_section,
    }


def count_dimensions(parsed):
    """Count MPS dimensions matching Netlib PROBLEM SUMMARY TABLE.
    Rows = all rows including objective (N) row.
    Cols = structural columns only (no slacks).
    Nonzeros = all nonzero coefficients including objective row."""
    return len(parsed['row_names']), len(parsed['col_names']), len(parsed['coefficients'])


def build_expanded_constraints(parsed):
    """Build expanded constraint list from parsed MPS.
    Expands RANGES into pairs of inequalities.

    Returns:
      constraints: list of (type, coef_dict, rhs) where coef_dict maps col_index -> value
      c: objective coefficient vector (numpy array)
      bounds: list of (lo, up) tuples per variable (None = unbounded)
    """
    obj_name = parsed['obj_name']
    col_names = parsed['col_names']
    n = len(col_names)
    col_idx = {name: i for i, name in enumerate(col_names)}

    # Objective vector
    c = np.zeros(n)
    for cname in col_names:
        key = (obj_name, cname)
        if key in parsed['coefficients']:
            c[col_idx[cname]] = parsed['coefficients'][key]

    # Variable bounds (MPS default: 0 <= x < +inf)
    bounds = []
    for cname in col_names:
        lo = 0.0
        up = None
        if cname in parsed['bound_specs']:
            bs = parsed['bound_specs'][cname]
            if 'lo' in bs:
                lo = bs['lo']
            if 'up' in bs:
                up = bs['up']
        bounds.append((lo, up))

    # Build expanded constraints: expand RANGES into paired inequalities
    constraints = []
    for rname in parsed['row_names']:
        rtype = parsed['row_types'][rname]
        if rtype == 'N':
            continue

        coef = {}
        for cname in col_names:
            key = (rname, cname)
            if key in parsed['coefficients']:
                coef[col_idx[cname]] = parsed['coefficients'][key]

        b = parsed['rhs_values'].get(rname, 0.0)

        if rname in parsed['range_values']:
            r = parsed['range_values'][rname]
            if rtype == 'L':
                constraints.append(('L', coef, b))
                constraints.append(('G', dict(coef), b - abs(r)))
            elif rtype == 'G':
                constraints.append(('G', coef, b))
                constraints.append(('L', dict(coef), b + abs(r)))
            elif rtype == 'E':
                if r >= 0:
                    constraints.append(('G', coef, b))
                    constraints.append(('L', dict(coef), b + r))
                else:
                    constraints.append(('G', coef, b + r))
                    constraints.append(('L', dict(coef), b))
        else:
            constraints.append((rtype, coef, b))

    return constraints, c, bounds


def solve_primal(constraints, c, bounds):
    """Solve primal LP: min c^T x subject to constraints and bounds."""
    n = len(bounds)

    A_ub_rows, b_ub_vals = [], []
    A_eq_rows, b_eq_vals = [], []

    for ctype, coef, b in constraints:
        a = np.zeros(n)
        for j, val in coef.items():
            a[j] = val

        if ctype == 'L':
            A_ub_rows.append(a)
            b_ub_vals.append(b)
        elif ctype == 'G':
            A_ub_rows.append(-a)
            b_ub_vals.append(-b)
        elif ctype == 'E':
            A_eq_rows.append(a)
            b_eq_vals.append(b)

    A_ub = np.array(A_ub_rows) if A_ub_rows else None
    b_ub = np.array(b_ub_vals) if b_ub_vals else None
    A_eq = np.array(A_eq_rows) if A_eq_rows else None
    b_eq = np.array(b_eq_vals) if b_eq_vals else None

    return linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                   bounds=bounds, method='highs',
                   options={'presolve': True, 'disp': False})


def construct_and_solve_dual(constraints, c, bounds):
    """Construct the explicit dual LP and solve it.

    Given primal: min c^T x
      s.t. constraints (E/L/G types with coefficients and RHS)
           l <= x <= u  (variable bounds)

    Dual (maximization, negated for scipy minimization):
      max  b^T y + l^T w_l - u^T w_u
      s.t. A^T y + w_l - w_u = c  (one equality per primal variable)

      y_i bounds: E -> free, L -> <= 0, G -> >= 0
      w_lj >= 0 if l_j finite, else fixed at 0
      w_uj >= 0 if u_j finite, else fixed at 0

    Returns (dual_optimal_value, y_star, w_l_star, w_u_star) or Nones on failure.
    """
    m = len(constraints)
    n = len(bounds)
    n_dual = m + 2 * n

    # Dual objective (negated for minimization): min -(b^T y + l^T w_l - u^T w_u)
    d = np.zeros(n_dual)
    for i, (ctype, coef, b) in enumerate(constraints):
        d[i] = -b
    for j in range(n):
        lo, up = bounds[j]
        if lo is not None:
            d[m + j] = -lo
        if up is not None:
            d[m + n + j] = up  # negated: -(- u_j) = u_j

    # Dual constraints (n equalities): A^T y + w_l - w_u = c
    A_eq = np.zeros((n, n_dual))
    b_eq = c.copy()

    for i, (ctype, coef, b) in enumerate(constraints):
        for j, val in coef.items():
            A_eq[j, i] = val  # A^T: transpose of constraint matrix

    for j in range(n):
        A_eq[j, m + j] = 1.0       # + w_lj
        A_eq[j, m + n + j] = -1.0  # - w_uj

    # Dual variable bounds
    dual_bounds = []
    for i, (ctype, _, _) in enumerate(constraints):
        if ctype == 'E':
            dual_bounds.append((None, None))
        elif ctype == 'L':
            dual_bounds.append((None, 0.0))
        elif ctype == 'G':
            dual_bounds.append((0.0, None))

    for j in range(n):
        lo, _ = bounds[j]
        if lo is not None:
            dual_bounds.append((0.0, None))
        else:
            dual_bounds.append((0.0, 0.0))

    for j in range(n):
        _, up = bounds[j]
        if up is not None:
            dual_bounds.append((0.0, None))
        else:
            dual_bounds.append((0.0, 0.0))

    result = linprog(d, A_eq=A_eq, b_eq=b_eq, bounds=dual_bounds,
                     method='highs', options={'presolve': True, 'disp': False})

    if result.success:
        dual_opt = -result.fun
        y_star = result.x[:m]
        w_l_star = result.x[m:m + n]
        w_u_star = result.x[m + n:m + 2 * n]
        return dual_opt, y_star, w_l_star, w_u_star
    else:
        print(f"  Dual solver failed: {result.message}", file=sys.stderr)
        return None, None, None, None


def check_complementary_slackness(constraints, bounds, x_star, y_star,
                                   w_l_star, w_u_star):
    """Check complementary slackness conditions and return max violation.

    CS conditions:
    - Constraint: slack_i * y_i = 0
      (L type: slack = b - ax; G type: slack = ax - b; E: trivially 0)
    - Variable lower bound: (x_j - l_j) * w_lj = 0
    - Variable upper bound: (u_j - x_j) * w_uj = 0
    """
    n = len(bounds)
    max_violation = 0.0

    for i, (ctype, coef, b) in enumerate(constraints):
        ax = sum(coef.get(j, 0.0) * x_star[j] for j in range(n))
        if ctype == 'L':
            slack = b - ax
        elif ctype == 'G':
            slack = ax - b
        else:
            slack = 0.0
        violation = abs(slack * y_star[i])
        if violation > max_violation:
            max_violation = violation

    for j in range(n):
        lo, up = bounds[j]
        if lo is not None:
            violation = abs((x_star[j] - lo) * w_l_star[j])
            if violation > max_violation:
                max_violation = violation
        if up is not None:
            violation = abs((up - x_star[j]) * w_u_star[j])
            if violation > max_violation:
                max_violation = violation

    return max_violation


def main():
    results = {}

    for prob in PROBLEMS:
        mps_path = os.path.join(DATA_DIR, f"{prob}.mps")
        if not os.path.exists(mps_path):
            print(f"ERROR: MPS file not found: {mps_path}", file=sys.stderr)
            continue

        print(f"Processing {prob.upper()}...")
        parsed = parse_mps(mps_path)
        num_rows, num_cols, num_nonzeros = count_dimensions(parsed)
        constraints, c, bounds = build_expanded_constraints(parsed)

        # Solve primal LP
        primal_result = solve_primal(constraints, c, bounds)
        if not primal_result.success:
            print(f"  ERROR: Primal solver failed: {primal_result.message}",
                  file=sys.stderr)
            continue
        primal_opt = primal_result.fun
        x_star = primal_result.x

        # Construct and solve the explicit dual LP
        dual_opt, y_star, w_l_star, w_u_star = construct_and_solve_dual(
            constraints, c, bounds)

        # Compute duality gap
        duality_gap = abs(primal_opt - dual_opt) if dual_opt is not None else None

        # Verify complementary slackness
        cs_max = None
        if y_star is not None:
            cs_max = check_complementary_slackness(
                constraints, bounds, x_star, y_star, w_l_star, w_u_star)

        name = prob.upper()
        results[name] = {
            "optimal_value": primal_opt,
            "dual_optimal_value": dual_opt,
            "duality_gap": duality_gap,
            "cs_max_violation": cs_max,
            "num_rows": num_rows,
            "num_cols": num_cols,
            "num_nonzeros": num_nonzeros,
            "has_bounds": parsed['has_bounds'],
            "has_ranges": parsed['has_ranges'],
        }

        print(f"  primal={primal_opt:.10e} dual={dual_opt:.10e} "
              f"gap={duality_gap:.2e} cs={cs_max:.2e}")

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {RESULTS_PATH}")


if __name__ == '__main__':
    main()
