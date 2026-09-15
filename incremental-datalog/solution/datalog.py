#!/usr/bin/env python3
"""
Incremental Datalog evaluator with stratified negation and correct
deletion handling via full re-evaluation (DRed-equivalent).

Implements:
- Parsing of Datalog rules, facts, and batched updates
- Stratification based on negative dependency analysis
- Per-stratum fixed-point evaluation with nested-loop joins
- Negation filtering for body atoms prefixed with "not"
- Full re-evaluation for incremental maintenance under deletions
"""

import argparse
import json
import re
import sys
from collections import defaultdict


def parse_atom(s):
    """Parse 'pred(a1, a2, ...)' or 'not pred(a1, a2, ...)' into dict."""
    s = s.strip()
    negated = False
    if s.startswith("not "):
        negated = True
        s = s[4:].strip()
    match = re.match(r"(\w+)\(([^)]*)\)", s)
    if not match:
        raise ValueError(f"Cannot parse atom: '{s}'")
    pred = match.group(1)
    args_str = match.group(2).strip()
    args = [a.strip() for a in args_str.split(",")] if args_str else []
    return {"predicate": pred, "args": args, "negated": negated}


def parse_rules(filename):
    """Parse Datalog rules from a .dl file."""
    rules = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            if line.endswith("."):
                line = line[:-1]
            if ":-" not in line:
                continue
            head_str, body_str = line.split(":-", 1)
            head = parse_atom(head_str)
            # Split body atoms respecting parentheses
            body_atoms = []
            depth = 0
            current = ""
            for ch in body_str:
                if ch == "(":
                    depth += 1
                    current += ch
                elif ch == ")":
                    depth -= 1
                    current += ch
                elif ch == "," and depth == 0:
                    if current.strip():
                        body_atoms.append(parse_atom(current))
                    current = ""
                else:
                    current += ch
            if current.strip():
                body_atoms.append(parse_atom(current))
            rules.append({"head": head, "body": body_atoms})
    return rules


def parse_facts(filename):
    """Parse ground facts. Returns dict: predicate -> set of tuples."""
    facts = defaultdict(set)
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            if line.endswith("."):
                line = line[:-1]
            atom = parse_atom(line)
            facts[atom["predicate"]].add(tuple(int(a) for a in atom["args"]))
    return facts


def parse_updates(filename):
    """Parse batched updates. Returns list of batches."""
    batches = []
    current = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            if line == "---":
                if current:
                    batches.append(current)
                    current = []
                continue
            op = line[0]
            rest = line[1:].strip()
            if rest.endswith("."):
                rest = rest[:-1]
            atom = parse_atom(rest)
            current.append((op, atom["predicate"], tuple(int(a) for a in atom["args"])))
    if current:
        batches.append(current)
    return batches


def compute_strata(rules):
    """Compute stratification: group rule indices by stratum.

    Predicates that appear negated in a rule body require the negated
    predicate to be in a strictly lower stratum than the rule head.
    """
    derived_preds = sorted(set(r["head"]["predicate"] for r in rules))
    pred_to_idx = {p: i for i, p in enumerate(derived_preds)}
    n = len(derived_preds)
    if n == 0:
        return []

    # Build dependency edges
    deps = [[] for _ in range(n)]
    for rule in rules:
        head_idx = pred_to_idx.get(rule["head"]["predicate"])
        if head_idx is None:
            continue
        for atom in rule["body"]:
            body_idx = pred_to_idx.get(atom["predicate"])
            if body_idx is not None:
                deps[head_idx].append((body_idx, atom["negated"]))

    # Iteratively assign strata
    stratum = [0] * n
    changed = True
    while changed:
        changed = False
        for i in range(n):
            for j, is_neg in deps[i]:
                required = stratum[j] + 1 if is_neg else stratum[j]
                if stratum[i] < required:
                    stratum[i] = required
                    changed = True

    # Group rules by their head predicate's stratum
    max_stratum = max(stratum) if stratum else 0
    strata = [[] for _ in range(max_stratum + 1)]
    for rule_idx, rule in enumerate(rules):
        pidx = pred_to_idx.get(rule["head"]["predicate"])
        if pidx is not None:
            strata[stratum[pidx]].append(rule_idx)

    return strata


def evaluate_rule(rule, facts):
    """Evaluate a single rule via nested-loop join. Returns set of head tuples."""
    head = rule["head"]
    body = rule["body"]

    positive_atoms = [a for a in body if not a["negated"]]
    negative_atoms = [a for a in body if a["negated"]]

    # Build variable bindings from positive atoms
    bindings = [{}]
    for atom in positive_atoms:
        relation = facts.get(atom["predicate"], set())
        next_bindings = []
        for binding in bindings:
            for tup in relation:
                if len(tup) != len(atom["args"]):
                    continue
                ext = dict(binding)
                ok = True
                for arg, val in zip(atom["args"], tup):
                    if arg[0].isupper():  # Variable
                        if arg in ext:
                            if ext[arg] != val:
                                ok = False
                                break
                        else:
                            ext[arg] = val
                    else:  # Constant
                        if int(arg) != val:
                            ok = False
                            break
                if ok:
                    next_bindings.append(ext)
        bindings = next_bindings

    # Filter bindings by negative atoms
    def passes_negation(binding):
        for atom in negative_atoms:
            relation = facts.get(atom["predicate"], set())
            tup = tuple(
                binding[a] if a[0].isupper() else int(a)
                for a in atom["args"]
            )
            if tup in relation:
                return False
        return True

    # Project bindings onto head arguments
    result = set()
    for binding in bindings:
        if not passes_negation(binding):
            continue
        ht = tuple(
            binding[a] if a[0].isupper() else int(a)
            for a in head["args"]
        )
        result.add(ht)
    return result


def compute_fixpoint(rules, base_facts):
    """Compute least fixed point with stratified evaluation."""
    facts = defaultdict(set)
    for pred, tuples in base_facts.items():
        facts[pred] = set(tuples)

    strata = compute_strata(rules)

    for stratum_rule_indices in strata:
        if not stratum_rule_indices:
            continue
        # Fixed-point iteration within this stratum
        changed = True
        while changed:
            changed = False
            for rule_idx in stratum_rule_indices:
                rule = rules[rule_idx]
                derived = evaluate_rule(rule, facts)
                pred = rule["head"]["predicate"]
                new = derived - facts[pred]
                if new:
                    facts[pred] |= new
                    changed = True

    return facts


def main():
    parser = argparse.ArgumentParser(description="Incremental Datalog evaluator")
    parser.add_argument("--rules", required=True)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--updates", required=True)
    parser.add_argument("--query", required=True)
    args = parser.parse_args()

    rules = parse_rules(args.rules)
    base_facts = parse_facts(args.facts)
    updates = parse_updates(args.updates)

    # Identify derived predicates for clearing on re-evaluation
    head_preds = set(r["head"]["predicate"] for r in rules)

    # Initial evaluation
    all_facts = compute_fixpoint(rules, base_facts)
    tuples = sorted(all_facts.get(args.query, set()))
    print(json.dumps({"batch": 0, "tuples": [list(t) for t in tuples]}))

    # Process each batch of updates
    for i, batch in enumerate(updates, 1):
        for op, pred, tup in batch:
            if op == "+":
                base_facts[pred].add(tup)
            elif op == "-":
                base_facts[pred].discard(tup)

        # Re-evaluate from base facts only (clear all derived)
        eval_base = {
            pred: set(tuples) for pred, tuples in base_facts.items()
            if pred not in head_preds
        }
        all_facts = compute_fixpoint(rules, eval_base)
        tuples = sorted(all_facts.get(args.query, set()))
        print(json.dumps({"batch": i, "tuples": [list(t) for t in tuples]}))


if __name__ == "__main__":
    main()
