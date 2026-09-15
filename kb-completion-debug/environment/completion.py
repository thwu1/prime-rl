"""
Knuth-Bendix completion procedure for first-order equational theories.

Given a set of equations and a reduction ordering, this module attempts to
produce a confluent, terminating term rewriting system equivalent to the
input theory. The completion algorithm iteratively computes critical pairs
between rules, orients them using the ordering, and simplifies the rule set.

"""

from term import (Var, Fun, variables, apply_subst, rename_variables,
                  subterms_with_positions, replace_at_position)
from unify import unify
from ordering import lpo_gt
from rewriting import normalize


def compute_critical_pairs(rule1, rule2, rules):
    """
    Compute critical pairs between two rewrite rules.

    A critical pair arises when the left-hand side of one rule can overlap
    with a (non-variable) subterm of the left-hand side of another rule.
    Each overlap produces an equation that must hold if the system is
    confluent.
    """
    lhs1, rhs1 = rule1
    lhs2, rhs2 = rule2
    pairs = []

    # Rename variables in rule2 to avoid variable capture
    suffix = "_r"
    lhs2r = rename_variables(lhs2, suffix)
    rhs2r = rename_variables(rhs2, suffix)

    # Try to unify lhs1 with lhs2 (overlap at root)
    sigma = unify(lhs1, lhs2r)
    if sigma is not None:
        cp_left = normalize(apply_subst(rhs1, sigma), rules)
        cp_right = normalize(apply_subst(rhs2r, sigma), rules)
        if cp_left != cp_right:
            pairs.append((cp_left, cp_right))

    return pairs


def orient_equation(s, t):
    """Try to orient an equation s = t into a rewrite rule using LPO.
    Returns (lhs, rhs) or None if the equation cannot be oriented."""
    if lpo_gt(s, t):
        return (s, t)
    if lpo_gt(t, s):
        return (t, s)
    return None


def interreduce(rules):
    """Simplify rules using each other: normalize right-hand sides,
    and remove rules whose left-hand sides are reducible by other rules."""
    changed = True
    while changed:
        changed = False
        new_rules = []
        for i, (lhs, rhs) in enumerate(rules):
            other_rules = rules[:i] + rules[i + 1:]

            new_rhs = normalize(rhs, other_rules)
            if new_rhs != rhs:
                changed = True

            lhs_reduced = normalize(lhs, other_rules)
            if lhs_reduced != lhs:
                changed = True
                oriented = orient_equation(lhs_reduced, new_rhs)
                if oriented is not None and oriented not in new_rules:
                    new_rules.append(oriented)
            else:
                rule = (lhs, new_rhs)
                if rule not in new_rules:
                    new_rules.append(rule)

        rules = new_rules
    return rules


def complete(axioms, max_iterations=200):
    """
    Run Knuth-Bendix completion on a set of equations.

    Parameters:
        axioms: list of (lhs, rhs) term pairs representing equations
        max_iterations: maximum number of completion steps

    Returns:
        A list of oriented rewrite rules forming a confluent, terminating
        rewrite system.

    Raises:
        ValueError if an equation cannot be oriented by the ordering.
    """
    # Orient initial axioms as rewrite rules
    rules = []
    for lhs, rhs in axioms:
        oriented = orient_equation(lhs, rhs)
        if oriented is None:
            raise ValueError(f"Cannot orient initial axiom: {lhs} = {rhs}")
        rules.append(oriented)

    # Seed the work queue with initial critical pairs
    pending = []
    for i in range(len(rules)):
        for j in range(len(rules)):
            cps = compute_critical_pairs(rules[i], rules[j], rules)
            pending.extend(cps)

    iteration = 0
    while pending and iteration < max_iterations:
        iteration += 1
        s, t = pending.pop(0)

        # Re-normalize with current rules
        s = normalize(s, rules)
        t = normalize(t, rules)

        if s == t:
            continue

        # Orient the new equation
        oriented = orient_equation(s, t)
        if oriented is None:
            raise ValueError(
                f"Completion failed at iteration {iteration}: "
                f"cannot orient equation\n  {s} = {t}\n"
                f"Check the term ordering and precedence configuration."
            )

        new_rule = oriented
        rules.append(new_rule)

        # Compute critical pairs involving the new rule
        for i in range(len(rules)):
            cps = compute_critical_pairs(rules[i], new_rule, rules)
            pending.extend(cps)
            if rules[i] != new_rule:
                cps = compute_critical_pairs(new_rule, rules[i], rules)
                pending.extend(cps)

        # Periodically simplify the rule set
        if iteration % 10 == 0:
            rules = interreduce(rules)

    # Final simplification pass
    rules = interreduce(rules)
    return rules
