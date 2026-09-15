"""
Knuth-Bendix Ordering (KBO) — complete implementation.

"""

from term import Var, Fun
from collections import Counter


class KBOConfig:
    """Configuration for Knuth-Bendix Ordering: weights and precedence."""

    def __init__(self, weights, w0, precedence):
        self.weights = weights
        self.w0 = w0
        self.precedence = precedence


def term_weight(t, config):
    """Compute the KBO weight of term t."""
    if isinstance(t, Var):
        return config.w0
    w = config.weights.get(t.symbol, 0)
    for arg in t.args:
        w += term_weight(arg, config)
    return w


def var_counts(t):
    """Count occurrences of each variable in term t."""
    c = Counter()
    if isinstance(t, Var):
        c[t.name] += 1
    elif isinstance(t, Fun):
        for arg in t.args:
            c += var_counts(arg)
    return c


def kbo_gt(s, t, config):
    """Decide whether s >_KBO t."""
    # Step 1: Check variable condition
    s_vc = var_counts(s)
    t_vc = var_counts(t)
    all_vars = set(s_vc.keys()) | set(t_vc.keys())
    for v in all_vars:
        if s_vc.get(v, 0) < t_vc.get(v, 0):
            return False

    # Step 2: Compare weights
    ws = term_weight(s, config)
    wt = term_weight(t, config)

    # Case 2a: weight(s) > weight(t)
    if ws > wt:
        return True

    # If weight(s) < weight(t), cannot be greater
    if ws < wt:
        return False

    # Case 2b: weight(s) == weight(t)

    # Sub-case (i): t is a variable and s != t
    if isinstance(t, Var):
        if isinstance(s, Var) and s.name == t.name:
            return False
        return True

    # s must be a function application to proceed
    if isinstance(s, Var):
        return False

    # Sub-case (ii): different top symbols, compare precedence
    s_prec = config.precedence.get(s.symbol, -1)
    t_prec = config.precedence.get(t.symbol, -1)
    if s_prec > t_prec:
        return True
    if s_prec < t_prec:
        return False

    # Sub-case (iii): same symbol, lexicographic comparison
    if s.symbol == t.symbol and len(s.args) == len(t.args):
        for i in range(len(s.args)):
            if s.args[i] == t.args[i]:
                continue
            return kbo_gt(s.args[i], t.args[i], config)

    return False


def kbo_ge(s, t, config):
    """Decide s >=_KBO t."""
    return s == t or kbo_gt(s, t, config)
