
"""Complete implementation of the linear arithmetic certificate engine."""

import re
from fractions import Fraction
from typing import Dict, List, Optional, Tuple, Set
from models import CompType, LinearExpr, Constraint, Certificate


# ---------------------------------------------------------------------------
# parse_constraint
# ---------------------------------------------------------------------------

def parse_constraint(s: str) -> Constraint:
    s = s.strip()

    # Detect comparison operator (check <= before <)
    comp = None
    expr_str = None
    for op_str, ct in [("<=", CompType.LE), ("<", CompType.LT), ("=", CompType.EQ)]:
        idx = s.rfind(op_str)
        if idx != -1:
            rhs = s[idx + len(op_str):].strip()
            if rhs == "0":
                expr_str = s[:idx].strip()
                comp = ct
                break
    if comp is None:
        raise ValueError(f"Cannot parse constraint: {s}")

    coeffs: Dict[int, Fraction] = {}

    # Tokenize: split on + but keep - attached to following term
    expr_str = expr_str.replace(" ", "")
    # Insert '+' before every '-' that isn't at the start
    normalized = ""
    for i, ch in enumerate(expr_str):
        if ch == '-' and i > 0 and expr_str[i - 1] not in ('+', '-'):
            normalized += '+'
        normalized += ch
    tokens = [t for t in normalized.split('+') if t]

    for tok in tokens:
        if '*' in tok:
            parts = tok.split('*', 1)
            coeff_s, var_s = parts[0], parts[1]
            coeff = Fraction(coeff_s) if coeff_s not in ('', '+') else Fraction(1)
            if coeff_s == '-':
                coeff = Fraction(-1)
            var_idx = int(var_s[1:])
            coeffs[var_idx] = coeffs.get(var_idx, Fraction(0)) + coeff
        elif 'x' in tok:
            m = re.match(r'^([+-]?\d*/?\.?\d*)x(\d+)$', tok)
            if m:
                cs = m.group(1)
                if cs in ('', '+'):
                    coeff = Fraction(1)
                elif cs == '-':
                    coeff = Fraction(-1)
                else:
                    coeff = Fraction(cs)
                var_idx = int(m.group(2))
                coeffs[var_idx] = coeffs.get(var_idx, Fraction(0)) + coeff
            else:
                raise ValueError(f"Cannot parse term: {tok}")
        else:
            coeffs[-1] = coeffs.get(-1, Fraction(0)) + Fraction(tok)

    coeffs = {k: v for k, v in coeffs.items() if v != 0}
    return Constraint(LinearExpr(coeffs), comp)


# ---------------------------------------------------------------------------
# verify_certificate
# ---------------------------------------------------------------------------

def verify_certificate(constraints: List[Constraint], cert: Certificate) -> bool:
    if not cert.coefficients:
        return False

    combined = LinearExpr()
    has_strict = False
    has_le = False
    has_nonzero = False

    for idx, coeff in cert.coefficients.items():
        if coeff == Fraction(0):
            continue
        if idx < 0 or idx >= len(constraints):
            return False

        c = constraints[idx]

        # Non-negativity check for LT / LE
        if c.comp != CompType.EQ and coeff < 0:
            return False

        has_nonzero = True
        combined = combined + c.expr.scale(coeff)

        if c.comp == CompType.LT and coeff > 0:
            has_strict = True
        if c.comp == CompType.LE and coeff > 0:
            has_le = True

    if not has_nonzero:
        return False

    # All variable coefficients must be zero
    for var in combined.variables():
        if var >= 0 and combined.get(var) != Fraction(0):
            return False

    const = combined.get(-1)

    if has_strict:
        return const >= 0          # const < 0 is false
    elif has_le:
        return const > 0           # const <= 0 is false
    else:
        return const != Fraction(0)  # const = 0 is false


# ---------------------------------------------------------------------------
# Fourier-Motzkin oracle
# ---------------------------------------------------------------------------

def _preprocess_equalities(constraints: List[Constraint]):
    """Split EQ constraints into pairs of LE constraints."""
    processed: List[Constraint] = []
    idx_map: List[Tuple[int, Fraction]] = []  # (orig_idx, sign)

    for i, c in enumerate(constraints):
        if c.comp == CompType.EQ:
            processed.append(Constraint(LinearExpr(dict(c.expr.coeffs)), CompType.LE))
            idx_map.append((i, Fraction(1)))
            neg = {k: -v for k, v in c.expr.coeffs.items()}
            processed.append(Constraint(LinearExpr(neg), CompType.LE))
            idx_map.append((i, Fraction(-1)))
        else:
            processed.append(Constraint(LinearExpr(dict(c.expr.coeffs)), c.comp))
            idx_map.append((i, Fraction(1)))

    return processed, idx_map


def fourier_motzkin_oracle(constraints: List[Constraint]) -> Optional[Certificate]:
    if not constraints:
        return None

    processed, idx_map = _preprocess_equalities(constraints)
    n = len(processed)

    # Working set: (Constraint, provenance_dict)
    working: List[Tuple[Constraint, Dict[int, Fraction]]] = []
    for i in range(n):
        c = processed[i]
        working.append((
            Constraint(LinearExpr(dict(c.expr.coeffs)), c.comp),
            {i: Fraction(1)}
        ))

    # Collect actual variables (not constant)
    all_vars: Set[int] = set()
    for c, _ in working:
        all_vars.update(v for v in c.expr.variables() if v >= 0)

    # Eliminate variables one by one
    for var in sorted(all_vars):
        positive = []
        negative = []
        zero = []

        for c, prov in working:
            coeff = c.expr.get(var)
            if coeff > 0:
                positive.append((c, prov))
            elif coeff < 0:
                negative.append((c, prov))
            else:
                zero.append((c, prov))

        new_working = list(zero)

        for pc, pp in positive:
            for nc, np_ in negative:
                pos_c = pc.expr.get(var)        # > 0
                neg_c = abs(nc.expr.get(var))    # > 0

                new_expr = pc.expr.scale(neg_c) + nc.expr.scale(pos_c)

                if pc.comp == CompType.LT or nc.comp == CompType.LT:
                    new_comp = CompType.LT
                else:
                    new_comp = CompType.LE

                new_prov: Dict[int, Fraction] = {}
                for k, v in pp.items():
                    new_prov[k] = new_prov.get(k, Fraction(0)) + v * neg_c
                for k, v in np_.items():
                    new_prov[k] = new_prov.get(k, Fraction(0)) + v * pos_c

                new_working.append((Constraint(new_expr, new_comp), new_prov))

        working = new_working

    # Check for contradictions among constant-only constraints
    for c, prov in working:
        has_vars = any(v >= 0 and c.expr.get(v) != Fraction(0)
                       for v in c.expr.variables())
        if has_vars:
            continue

        const = c.expr.get(-1)
        is_contradiction = False
        if c.comp == CompType.LT and const >= 0:
            is_contradiction = True
        elif c.comp == CompType.LE and const > 0:
            is_contradiction = True

        if is_contradiction:
            # Map provenance back to original constraint indices
            orig_prov: Dict[int, Fraction] = {}
            for proc_idx, proc_coeff in prov.items():
                if proc_coeff == Fraction(0):
                    continue
                orig_idx, sign = idx_map[proc_idx]
                orig_prov[orig_idx] = orig_prov.get(orig_idx, Fraction(0)) + proc_coeff * sign

            orig_prov = {k: v for k, v in orig_prov.items() if v != Fraction(0)}
            cert = Certificate(coefficients=orig_prov)

            if verify_certificate(constraints, cert):
                return cert

    return None


# ---------------------------------------------------------------------------
# Two-phase Simplex solver
# ---------------------------------------------------------------------------

def _two_phase_simplex(c_obj, A_eq, b_eq, n_vars):
    """
    Solve: maximize c_obj^T x  subject to  A_eq x = b_eq, x >= 0.

    Returns ('optimal', x, obj_val) or None if infeasible.
    """
    F = Fraction
    m = len(A_eq)
    n = n_vars
    if m == 0 or n == 0:
        return None

    # Copy and ensure b >= 0
    A = [list(row) for row in A_eq]
    b = list(b_eq)
    for i in range(m):
        if b[i] < 0:
            A[i] = [-v for v in A[i]]
            b[i] = -b[i]

    total = n + m  # original + artificial
    # Tableau rows: [A_i | e_i | b_i]
    tableau = []
    for i in range(m):
        row = list(A[i]) + [F(0)] * m + [b[i]]
        row[n + i] = F(1)
        tableau.append(row)

    basis = list(range(n, n + m))

    # ---- Phase I: minimize sum of artificials ----
    c1 = [F(0)] * total
    for j in range(total):
        c1[j] = F(0) if j < n else F(-1)
        for i in range(m):
            c1[j] += tableau[i][j]

    MAX_ITER = 20000
    for _ in range(MAX_ITER):
        # Bland entering
        entering = None
        for j in range(total):
            if c1[j] > 0:
                entering = j
                break
        if entering is None:
            break

        # Minimum-ratio leaving (Bland for ties)
        min_ratio = None
        leaving = None
        for i in range(m):
            if tableau[i][entering] > 0:
                ratio = tableau[i][-1] / tableau[i][entering]
                if leaving is None or ratio < min_ratio or \
                   (ratio == min_ratio and basis[i] < basis[leaving]):
                    min_ratio = ratio
                    leaving = i
        if leaving is None:
            break  # unbounded in Phase I

        # Pivot
        pv = tableau[leaving][entering]
        for j in range(total + 1):
            tableau[leaving][j] /= pv
        for i in range(m):
            if i != leaving:
                f = tableau[i][entering]
                if f != 0:
                    for j in range(total + 1):
                        tableau[i][j] -= f * tableau[leaving][j]
        f = c1[entering]
        for j in range(total):
            c1[j] -= f * tableau[leaving][j]
        basis[leaving] = entering

    # Check feasibility: all artificials must be 0
    for i in range(m):
        if basis[i] >= n and tableau[i][-1] != 0:
            return None  # infeasible

    # Drive remaining artificial basis vars out
    for i in range(m):
        if basis[i] >= n:
            pivoted = False
            for j in range(n):
                if tableau[i][j] != 0:
                    pv = tableau[i][j]
                    for jj in range(total + 1):
                        tableau[i][jj] /= pv
                    for ii in range(m):
                        if ii != i:
                            f = tableau[ii][j]
                            if f != 0:
                                for jj in range(total + 1):
                                    tableau[ii][jj] -= f * tableau[i][jj]
                    basis[i] = j
                    pivoted = True
                    break

    # ---- Phase II: optimize original objective ----
    c2 = [F(0)] * total
    for j in range(total):
        c2[j] = c_obj[j] if j < n else F(0)
        for i in range(m):
            if basis[i] < n:
                c2[j] -= c_obj[basis[i]] * tableau[i][j]

    obj_val = F(0)
    for i in range(m):
        if basis[i] < n:
            obj_val += c_obj[basis[i]] * tableau[i][-1]

    for _ in range(MAX_ITER):
        entering = None
        for j in range(n):  # only original variables
            if c2[j] > 0:
                entering = j
                break
        if entering is None:
            break

        min_ratio = None
        leaving = None
        for i in range(m):
            if tableau[i][entering] > 0:
                ratio = tableau[i][-1] / tableau[i][entering]
                if leaving is None or ratio < min_ratio or \
                   (ratio == min_ratio and basis[i] < basis[leaving]):
                    min_ratio = ratio
                    leaving = i
        if leaving is None:
            return ('unbounded', None, None)

        obj_val += c2[entering] * (tableau[leaving][-1] / tableau[leaving][entering])

        pv = tableau[leaving][entering]
        for j in range(total + 1):
            tableau[leaving][j] /= pv
        for i in range(m):
            if i != leaving:
                f = tableau[i][entering]
                if f != 0:
                    for j in range(total + 1):
                        tableau[i][j] -= f * tableau[leaving][j]
        f = c2[entering]
        for j in range(total):
            c2[j] -= f * tableau[leaving][j]
        basis[leaving] = entering

    x_opt = [F(0)] * n
    for i in range(m):
        if basis[i] < n:
            x_opt[basis[i]] = tableau[i][-1]

    return ('optimal', x_opt, obj_val)


# ---------------------------------------------------------------------------
# Simplex oracle
# ---------------------------------------------------------------------------

def simplex_oracle(constraints: List[Constraint]) -> Optional[Certificate]:
    if not constraints:
        return None

    processed, idx_map = _preprocess_equalities(constraints)
    n = len(processed)
    if n == 0:
        return None

    # Collect variables
    all_vars: Set[int] = set()
    for c in processed:
        all_vars.update(v for v in c.expr.variables() if v >= 0)
    var_list = sorted(all_vars)
    m = len(var_list)

    F = Fraction

    # Build constraint matrix A (n constraints x m variables) and constant vector b
    A_rows = [[F(0)] * m for _ in range(n)]
    b_vec = [F(0)] * n
    for i, c in enumerate(processed):
        for j, var in enumerate(var_list):
            A_rows[i][j] = c.expr.get(var)
        b_vec[i] = c.expr.get(-1)

    # LP: max b^T y, s.t. A^T y = 0, sum(y) = 1, y >= 0
    A_eq = []
    for j in range(m):
        row = [A_rows[i][j] for i in range(n)]
        A_eq.append(row)
    A_eq.append([F(1)] * n)

    b_eq = [F(0)] * m + [F(1)]
    c_obj = list(b_vec)

    result = _two_phase_simplex(c_obj, A_eq, b_eq, n)

    if result is None:
        return None

    status, y_opt, obj_val = result

    if status != 'optimal':
        return None

    # Check if objective > 0 or >= 0 with strict participation
    if obj_val > 0:
        pass  # good
    elif obj_val == 0:
        has_lt = False
        for i in range(n):
            if y_opt[i] > 0 and processed[i].comp == CompType.LT:
                has_lt = True
                break
        if not has_lt:
            return None
    else:
        return None

    # Convert back to original indices
    cert_coeffs: Dict[int, Fraction] = {}
    for i in range(n):
        if y_opt[i] != 0:
            orig_idx, sign = idx_map[i]
            cert_coeffs[orig_idx] = cert_coeffs.get(orig_idx, F(0)) + y_opt[i] * sign

    cert_coeffs = {k: v for k, v in cert_coeffs.items() if v != F(0)}
    cert = Certificate(coefficients=cert_coeffs)

    if verify_certificate(constraints, cert):
        return cert

    return None


# ---------------------------------------------------------------------------
# is_unsatisfiable
# ---------------------------------------------------------------------------

def is_unsatisfiable(constraints: List[Constraint],
                     oracle: str = "fm") -> Tuple[bool, Optional[Certificate]]:
    if oracle == "fm":
        cert = fourier_motzkin_oracle(constraints)
    elif oracle == "simplex":
        cert = simplex_oracle(constraints)
    else:
        raise ValueError(f"Unknown oracle: {oracle}")

    if cert is not None:
        return (True, cert)
    return (False, None)


# ---------------------------------------------------------------------------
# GLPK integration: LP export and cross-validation
# ---------------------------------------------------------------------------

def export_lp(constraints: List[Constraint], filepath: str) -> None:
    """Export constraints to CPLEX LP format, relaxing strict inequalities to non-strict."""
    F = Fraction
    all_vars: Set[int] = set()
    for c in constraints:
        all_vars.update(v for v in c.expr.variables() if v >= 0)
    if not all_vars:
        all_vars = {0}
    var_list = sorted(all_vars)

    def fmt(val):
        fv = float(val)
        if fv == int(fv) and abs(fv) < 1e15:
            return str(int(fv))
        return f"{fv:.15g}"

    with open(filepath, 'w') as f:
        f.write("Minimize\n")
        f.write(f" obj: x{var_list[0]}\n")
        f.write("Subject To\n")

        for i, c in enumerate(constraints):
            parts = []
            first = True
            for v in var_list:
                coeff = c.expr.get(v)
                if coeff == F(0):
                    continue
                cf = float(coeff)
                acf = abs(cf)
                if first:
                    sign = "- " if cf < 0 else ""
                else:
                    sign = "- " if cf < 0 else "+ "
                if acf == 1.0:
                    parts.append(f"{sign}x{v}")
                else:
                    parts.append(f"{sign}{fmt(abs(coeff))} x{v}")
                first = False

            if not parts:
                # Pure constant constraint — add zero-coeff dummy term
                parts = [f"0 x{var_list[0]}"]

            expr_str = " ".join(parts)
            rhs = fmt(-c.expr.get(-1))
            op = "=" if c.comp == CompType.EQ else "<="
            f.write(f" c{i}: {expr_str} {op} {rhs}\n")

        f.write("Bounds\n")
        for v in var_list:
            f.write(f" x{v} free\n")
        f.write("End\n")


def validate_with_glpsol(filepath: str) -> str:
    """Run glpsol on an LP file and determine feasibility from its output."""
    import subprocess
    import os

    sol_path = filepath + '.sol'
    try:
        result = subprocess.run(
            ['glpsol', '--lp', filepath, '-o', sol_path],
            capture_output=True, text=True, timeout=30
        )

        # Check stdout for clear infeasibility messages
        stdout_upper = result.stdout.upper()
        if 'NO PRIMAL FEASIBLE' in stdout_upper or 'PROBLEM HAS NO FEASIBLE' in stdout_upper:
            return 'INFEASIBLE'

        # Parse solution file for Status line
        if os.path.exists(sol_path):
            with open(sol_path) as sf:
                for line in sf:
                    stripped = line.strip().upper()
                    if stripped.startswith('STATUS:'):
                        if 'INFEASIBLE' in stripped or 'NOFEAS' in stripped:
                            return 'INFEASIBLE'
                        return 'FEASIBLE'

        # Fallback: check combined output
        if 'INFEASIBLE' in stdout_upper:
            return 'INFEASIBLE'

        return 'FEASIBLE'
    finally:
        if os.path.exists(sol_path):
            os.unlink(sol_path)
