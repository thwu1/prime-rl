"""
Lexicographic Path Ordering (LPO) for orienting equations into rewrite rules.

The LPO provides a well-founded, monotone, and stable ordering on terms,
which is essential for guaranteeing termination of the rewrite system
produced by Knuth-Bendix completion.

"""

from term import Var, Fun, variables


# Precedence ranking for function symbols used in group theory.
# Higher numeric value = higher precedence in the term ordering.
PRECEDENCE = {
    'mul': 2,
    'inv': 1,
    'e': 0,
}


def prec(symbol):
    """Look up the precedence rank of a function symbol."""
    return PRECEDENCE.get(symbol, -1)


def lpo_ge(s, t):
    """Check s >= t in LPO (greater than or equal)."""
    return s == t or lpo_gt(s, t)


def lpo_gt(s, t):
    """
    Check s > t in the lexicographic path ordering.

    Definition: s = f(s1,...,sn) >_lpo t iff
      (1) si >=_lpo t for some argument si of s, OR
      (2) t = g(t1,...,tm) AND s >_lpo tj for all j, AND EITHER
          (a) f >_prec g, OR
          (b) f = g and (s1,...,sn) >_lex (t1,...,tm)
    """
    if isinstance(s, Var):
        return False

    # s = f(s1, ..., sn)
    # Case 1: some argument si >= t
    if any(lpo_ge(si, t) for si in s.args):
        return True

    if isinstance(t, Var):
        # If t is a variable not covered by Case 1, s cannot be > t
        return False

    # t = g(t1, ..., tm)
    # Prerequisite for Cases 2a and 2b: s > every argument of t
    if not all(lpo_gt(s, tj) for tj in t.args):
        return False

    # Case 2a: f has strictly higher precedence than g
    if prec(s.symbol) > prec(t.symbol):
        return True

    # Case 2b: same function symbol, lexicographic argument comparison
    if s.symbol == t.symbol and len(s.args) == len(t.args):
        for i in range(len(s.args)):
            if lpo_gt(s.args[i], t.args[i]):
                return True
            if s.args[i] != t.args[i]:
                return False

    return False
