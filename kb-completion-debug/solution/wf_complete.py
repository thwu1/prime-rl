"""
Z3-based automatic discovery of admissible KBO weight functions.

Encodes KBO admissibility constraints and equation orientation as an SMT
problem, then uses Z3 Optimize to find minimal-weight valid assignments.
Minimizing weights ensures that unary functions like inv get weight 0,
triggering the precedence-based tiebreaking that produces standard
completions.

"""

from collections import Counter
from term import Var, Fun


def _static_var_counts(t):
    """Count variable occurrences in a concrete term (no Z3)."""
    c = Counter()
    if isinstance(t, Var):
        c[t.name] += 1
    elif isinstance(t, Fun):
        for arg in t.args:
            c += _static_var_counts(arg)
    return c


def _sym_weight(t, ws, w0):
    """Compute symbolic weight of term t as a Z3 arithmetic expression."""
    if isinstance(t, Var):
        return w0
    w = ws[t.symbol]
    for arg in t.args:
        w = w + _sym_weight(arg, ws, w0)
    return w


def _encode_kbo_gt(s, t, ws, w0, ps):
    """
    Encode s >_KBO t as a Z3 Bool expression.

    Since s and t are concrete terms (fixed structure), the recursive
    encoding terminates and produces a finite Boolean formula over the
    symbolic weight and precedence variables.
    """
    from z3 import And, Or, BoolVal

    # Variable condition (static check)
    s_vc = _static_var_counts(s)
    t_vc = _static_var_counts(t)
    all_vars = set(s_vc.keys()) | set(t_vc.keys())
    for v in all_vars:
        if s_vc.get(v, 0) < t_vc.get(v, 0):
            return BoolVal(False)

    w_s = _sym_weight(s, ws, w0)
    w_t = _sym_weight(t, ws, w0)

    # Case: weight(s) > weight(t)
    weight_gt = (w_s > w_t)

    # Case: weight(s) == weight(t) and structural comparison
    if isinstance(t, Var):
        if isinstance(s, Var) and s.name == t.name:
            return weight_gt
        return Or(weight_gt, w_s == w_t)

    if isinstance(s, Var):
        return weight_gt

    # Both are Fun
    if s.symbol != t.symbol:
        prec_gt = And(w_s == w_t, ps[s.symbol] > ps[t.symbol])
        return Or(weight_gt, prec_gt)

    if len(s.args) != len(t.args):
        return weight_gt

    # Same symbol, same arity: lexicographic comparison
    lex = _encode_lex_gt(list(s.args), list(t.args), ws, w0, ps)
    return Or(weight_gt, And(w_s == w_t, lex))


def _encode_lex_gt(s_args, t_args, ws, w0, ps):
    """Encode lexicographic >_KBO on argument lists."""
    from z3 import BoolVal

    if not s_args:
        return BoolVal(False)

    s0, t0 = s_args[0], t_args[0]
    if s0 == t0:
        return _encode_lex_gt(s_args[1:], t_args[1:], ws, w0, ps)

    return _encode_kbo_gt(s0, t0, ws, w0, ps)


def find_kbo_weights(equations, symbols):
    """
    Find admissible KBO weights and precedence that orient all equations.

    Uses Z3 Optimize to minimize total weight, which ensures unary functions
    get weight 0 when possible (leading to standard precedence-based
    orientations).

    Parameters:
        equations: list of (lhs, rhs) term pairs
        symbols: dict mapping function symbol name -> arity

    Returns:
        dict with 'weights', 'w0', 'precedence', or None if unsatisfiable.
    """
    from z3 import Optimize, Int, Or, Implies, sat

    solver = Optimize()

    w0 = Int('w0')
    ws = {sym: Int(f'w_{sym}') for sym in symbols}
    ps = {sym: Int(f'p_{sym}') for sym in symbols}

    # Admissibility constraints
    solver.add(w0 > 0)
    solver.add(w0 <= 5)

    for sym in symbols:
        solver.add(ws[sym] >= 0)
        solver.add(ws[sym] <= 10)
        solver.add(ps[sym] >= 0)
        solver.add(ps[sym] <= len(symbols) + 2)

    # Constants (arity 0) must have weight >= w0
    for sym, arity in symbols.items():
        if arity == 0:
            solver.add(ws[sym] >= w0)

    # Unary symbols with weight 0 must have greatest precedence
    for sym, arity in symbols.items():
        if arity == 1:
            for sym2 in symbols:
                if sym2 != sym:
                    solver.add(Implies(ws[sym] == 0, ps[sym] > ps[sym2]))

    # Each equation must be orientable in at least one direction
    for lhs, rhs in equations:
        lr = _encode_kbo_gt(lhs, rhs, ws, w0, ps)
        rl = _encode_kbo_gt(rhs, lhs, ws, w0, ps)
        solver.add(Or(lr, rl))

    # Minimize total weight to prefer weight-0 unary functions,
    # which triggers precedence-based tiebreaking for standard orientations
    total_weight = w0
    for sym in symbols:
        total_weight = total_weight + ws[sym]
    solver.minimize(total_weight)

    if solver.check() == sat:
        m = solver.model()
        return {
            'weights': {sym: m[ws[sym]].as_long() for sym in symbols},
            'w0': m[w0].as_long(),
            'precedence': {sym: m[ps[sym]].as_long() for sym in symbols},
        }
    return None
