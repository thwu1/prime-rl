"""
Knuth-Bendix Ordering (KBO) for orienting equations into rewrite rules.

KBO compares terms using a weight function w: Sigma -> N and a minimum
variable weight w0 > 0. Terms are compared first by total weight; ties
are broken by function symbol precedence and lexicographic subterm
comparison.

Admissibility requirements for a valid KBO configuration:
  - w0 > 0
  - For every constant c (arity 0): w(c) >= w0
  - If f is unary and w(f) = 0, then f must have the greatest precedence
    among all function symbols in the signature

Weight definition:
  w(x)             = w0                    for any variable x
  w(f(t1,...,tn))  = w(f) + w(t1) + ... + w(tn)

Comparison s >_KBO t holds iff:
  1. For every variable x: |s|_x >= |t|_x        (variable condition)
  2. AND one of:
     (a) weight(s) > weight(t)
     (b) weight(s) = weight(t) AND one of:
         (i)   t is a variable and s != t
         (ii)  s = f(...), t = g(...), prec(f) > prec(g)
         (iii) s = f(s1,...,sn), t = f(t1,...,tn), and there exists i
               such that s1=t1, ..., s(i-1)=t(i-1), and si >_KBO ti

"""

from term import Var, Fun
from collections import Counter


class KBOConfig:
    """Configuration for Knuth-Bendix Ordering: weights and precedence."""

    def __init__(self, weights, w0, precedence):
        """
        Parameters:
            weights: dict mapping function symbol name -> non-negative int weight
            w0: positive int, weight assigned to each variable occurrence
            precedence: dict mapping function symbol name -> int rank (higher = greater)
        """
        self.weights = weights
        self.w0 = w0
        self.precedence = precedence


def term_weight(t, config):
    """
    Compute the KBO weight of term t under the given configuration.

    w(x)             = w0
    w(f(t1,...,tn))  = w(f) + sum(w(ti))
    """
    raise NotImplementedError("term_weight not implemented")


def var_counts(t):
    """
    Count occurrences of each variable in term t.

    Returns: Counter mapping variable name -> occurrence count
    Example: var_counts(Fun('f', (Var('x'), Var('x')))) == Counter({'x': 2})
    """
    raise NotImplementedError("var_counts not implemented")


def kbo_gt(s, t, config):
    """
    Decide whether s >_KBO t under the given configuration.

    Returns True iff s is strictly greater than t in the KBO.
    See module docstring for the formal definition.
    """
    raise NotImplementedError("kbo_gt not implemented")


def kbo_ge(s, t, config):
    """Decide s >=_KBO t (greater than or equal)."""
    return s == t or kbo_gt(s, t, config)
