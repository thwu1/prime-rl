"""
Robinson's unification algorithm for first-order terms.

"""

from term import Var, Fun, apply_subst


def occurs_in(var_name, t):
    """Check if a variable name occurs anywhere in term t (occurs check)."""
    if isinstance(t, Var):
        return t.name == var_name
    return any(occurs_in(var_name, a) for a in t.args)


def unify(s, t):
    """
    Compute the most general unifier (mgu) of two terms.
    Returns a substitution dict {var_name: term}, or None if not unifiable.
    """
    subst = {}
    equations = [(s, t)]

    while equations:
        s, t = equations.pop()
        s = apply_subst(s, subst)
        t = apply_subst(t, subst)

        if s == t:
            continue

        if isinstance(s, Var):
            if occurs_in(s.name, t):
                return None
            new_binding = {s.name: t}
            subst = {k: apply_subst(v, new_binding) for k, v in subst.items()}
            subst[s.name] = t
            continue

        if isinstance(t, Var):
            if occurs_in(t.name, s):
                return None
            new_binding = {t.name: s}
            subst = {k: apply_subst(v, new_binding) for k, v in subst.items()}
            subst[t.name] = s
            continue

        if not isinstance(s, Fun) or not isinstance(t, Fun):
            return None
        if s.symbol != t.symbol or len(s.args) != len(t.args):
            return None

        for sa, ta in zip(s.args, t.args):
            equations.append((sa, ta))

    return subst
