"""
Term rewriting: pattern matching, single-step reduction, and normalization.

"""

from term import Var, Fun, apply_subst


def match_term(pattern, target):
    """
    One-way pattern matching: find substitution sigma such that
    sigma(pattern) = target. Variables in target are treated as constants.
    Returns a substitution dict, or None if no match.
    """
    subst = {}
    stack = [(pattern, target)]

    while stack:
        p, t = stack.pop()

        if isinstance(p, Var):
            if p.name in subst:
                if subst[p.name] != t:
                    return None
            else:
                subst[p.name] = t
            continue

        if not isinstance(t, Fun):
            return None
        if p.symbol != t.symbol or len(p.args) != len(t.args):
            return None

        for pa, ta in zip(p.args, t.args):
            stack.append((pa, ta))

    return subst


def rewrite_at_root(t, rules):
    """Try to apply a rewrite rule at the root of term t.
    Returns the rewritten term, or None if no rule applies."""
    for lhs, rhs in rules:
        sigma = match_term(lhs, t)
        if sigma is not None:
            return apply_subst(rhs, sigma)
    return None


def rewrite_step(t, rules):
    """Apply one leftmost-innermost rewrite step.
    Returns the new term after one step, or None if no rule applies anywhere."""
    if isinstance(t, Fun):
        # Try innermost first: rewrite in arguments left-to-right
        for i, arg in enumerate(t.args):
            result = rewrite_step(arg, rules)
            if result is not None:
                new_args = list(t.args)
                new_args[i] = result
                return Fun(t.symbol, tuple(new_args))

    # Then try the root
    return rewrite_at_root(t, rules)


def normalize(t, rules):
    """
    Reduce a term to its normal form by exhaustively applying rewrite rules.
    A term is in normal form when no rewrite rule can be applied anywhere.
    """
    result = rewrite_step(t, rules)
    if result is not None:
        return result
    return t
