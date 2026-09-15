"""
Knuth-Bendix completion procedure for first-order equational theories.

Fixed version: critical pairs computed at all non-variable subterm positions,
and completion accepts an optional gt_fn parameter for pluggable orderings.

"""

from term import (Var, Fun, variables, apply_subst, rename_variables,
                  subterms_with_positions, replace_at_position)
from unify import unify
from ordering import lpo_gt
from rewriting import normalize


def compute_critical_pairs(rule1, rule2, rules):
    """
    Compute critical pairs between two rewrite rules by checking overlaps
    at every non-variable subterm position of rule1's LHS.
    """
    lhs1, rhs1 = rule1
    lhs2, rhs2 = rule2
    pairs = []

    suffix = "_r"
    lhs2r = rename_variables(lhs2, suffix)
    rhs2r = rename_variables(rhs2, suffix)

    for pos, subterm in subterms_with_positions(lhs1):
        if isinstance(subterm, Var):
            continue
        sigma = unify(subterm, lhs2r)
        if sigma is not None:
            cp_left = normalize(apply_subst(rhs1, sigma), rules)
            replaced = replace_at_position(lhs1, pos, rhs2r)
            cp_right = normalize(apply_subst(replaced, sigma), rules)
            if cp_left != cp_right:
                pairs.append((cp_left, cp_right))

    return pairs


def orient_equation(s, t, gt_fn):
    """Orient equation s = t into a rewrite rule using the given ordering."""
    if gt_fn(s, t):
        return (s, t)
    if gt_fn(t, s):
        return (t, s)
    return None


def interreduce(rules, gt_fn):
    """Simplify rules using each other."""
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
                oriented = orient_equation(lhs_reduced, new_rhs, gt_fn)
                if oriented is not None and oriented not in new_rules:
                    new_rules.append(oriented)
            else:
                rule = (lhs, new_rhs)
                if rule not in new_rules:
                    new_rules.append(rule)

        rules = new_rules
    return rules


def complete(axioms, max_iterations=200, gt_fn=None):
    """
    Run Knuth-Bendix completion on a set of equations.

    Parameters:
        axioms: list of (lhs, rhs) term pairs representing equations
        max_iterations: maximum number of completion steps
        gt_fn: comparison function (s, t) -> bool for orienting equations.
               Defaults to LPO (lpo_gt) if not provided.

    Returns:
        A list of oriented rewrite rules forming a confluent, terminating
        rewrite system.
    """
    if gt_fn is None:
        gt_fn = lpo_gt

    rules = []
    for lhs, rhs in axioms:
        oriented = orient_equation(lhs, rhs, gt_fn)
        if oriented is None:
            raise ValueError(f"Cannot orient initial axiom: {lhs} = {rhs}")
        rules.append(oriented)

    pending = []
    for i in range(len(rules)):
        for j in range(len(rules)):
            cps = compute_critical_pairs(rules[i], rules[j], rules)
            pending.extend(cps)

    iteration = 0
    while pending and iteration < max_iterations:
        iteration += 1
        s, t = pending.pop(0)

        s = normalize(s, rules)
        t = normalize(t, rules)

        if s == t:
            continue

        oriented = orient_equation(s, t, gt_fn)
        if oriented is None:
            raise ValueError(
                f"Completion failed at iteration {iteration}: "
                f"cannot orient equation\n  {s} = {t}\n"
                f"Check the term ordering and precedence configuration."
            )

        new_rule = oriented
        rules.append(new_rule)

        for i in range(len(rules)):
            cps = compute_critical_pairs(rules[i], new_rule, rules)
            pending.extend(cps)
            if rules[i] != new_rule:
                cps = compute_critical_pairs(new_rule, rules[i], rules)
                pending.extend(cps)

        if iteration % 10 == 0:
            rules = interreduce(rules, gt_fn)

    rules = interreduce(rules, gt_fn)
    return rules
