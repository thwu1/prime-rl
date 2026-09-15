#!/usr/bin/env python3
"""
GDL (Game Description Language) State Machine Reasoner.

Implements parsing of GDL/KIF game descriptions and a backward-chaining
logical prover with unification, negation-as-failure, distinct constraints,
and or-disjunction to compute game state transitions.
"""

import re
from collections import defaultdict


# ============================================================
# S-Expression Parser
# ============================================================

def tokenize(text):
    """Remove comments and tokenize GDL/KIF text."""
    text = re.sub(r';[^\n]*', '', text)
    text = text.replace('(', ' ( ').replace(')', ' ) ')
    return text.split()


def parse_sexps(text):
    """Parse text into a list of s-expressions (nested tuples/strings)."""
    tokens = tokenize(text)
    results = []
    pos = 0
    while pos < len(tokens):
        expr, pos = _parse_one(tokens, pos)
        results.append(expr)
    return results


def _parse_one(tokens, pos):
    tok = tokens[pos]
    if tok == '(':
        elements = []
        pos += 1
        while tokens[pos] != ')':
            elem, pos = _parse_one(tokens, pos)
            elements.append(elem)
        return tuple(elements), pos + 1
    else:
        return tok, pos + 1


# ============================================================
# Term Utilities
# ============================================================

def is_var(term):
    """Check if term is a GDL variable (starts with ?)."""
    return isinstance(term, str) and term.startswith('?')


def is_compound(term):
    """Check if term is a compound (tuple)."""
    return isinstance(term, tuple)


def apply_sub(term, sub):
    """Apply a substitution mapping to a term, chasing variable chains."""
    if is_var(term):
        if term in sub:
            return apply_sub(sub[term], sub)
        return term
    if is_compound(term):
        return tuple(apply_sub(x, sub) for x in term)
    return term


def is_ground(term):
    """Check if term contains no variables."""
    if is_var(term):
        return False
    if is_compound(term):
        return all(is_ground(x) for x in term)
    return True


def term_to_str(term):
    """Convert an internal term representation to a GDL string."""
    if isinstance(term, tuple):
        return '(' + ' '.join(term_to_str(x) for x in term) + ')'
    return str(term)


def str_to_term(s):
    """Convert a GDL string to an internal term representation."""
    results = parse_sexps(s)
    return results[0] if results else s


# ============================================================
# Unification
# ============================================================

def unify(t1, t2, sub=None):
    """
    Unify two terms, returning extended substitution or None on failure.
    Uses Robinson's unification algorithm without occurs check (safe for
    finite GDL terms).
    """
    if sub is None:
        sub = {}
    t1 = apply_sub(t1, sub)
    t2 = apply_sub(t2, sub)
    if t1 == t2:
        return sub
    if is_var(t1):
        return dict(sub, **{t1: t2})
    if is_var(t2):
        return dict(sub, **{t2: t1})
    if is_compound(t1) and is_compound(t2):
        if len(t1) != len(t2):
            return None
        for a, b in zip(t1, t2):
            sub = unify(a, b, sub)
            if sub is None:
                return None
        return sub
    return None


# ============================================================
# Backward-Chaining Prover
# ============================================================

class Prover:
    """
    SLD-resolution prover with negation-as-failure for GDL.

    Supports: unification, variable renaming per rule application,
    negation-as-failure (not), distinct constraints, or-disjunction.
    """

    def __init__(self, rules, facts):
        self.rules_by_head = defaultdict(list)
        for head, body in rules:
            pred = head[0] if is_compound(head) else head
            self.rules_by_head[pred].append((head, body))

        self.facts_by_pred = defaultdict(set)
        for f in facts:
            pred = f[0] if is_compound(f) else f
            self.facts_by_pred[pred].add(f)

        self._var_counter = 0

    def _fresh_var(self):
        self._var_counter += 1
        return f'?_v{self._var_counter}'

    def _rename_term(self, term, mapping):
        if is_var(term):
            if term not in mapping:
                mapping[term] = self._fresh_var()
            return mapping[term]
        if is_compound(term):
            return tuple(self._rename_term(x, mapping) for x in term)
        return term

    def _rename_rule(self, head, body):
        mapping = {}
        new_head = self._rename_term(head, mapping)
        new_body = [self._rename_term(lit, mapping) for lit in body]
        return new_head, new_body

    def prove_all(self, goals, sub, context, depth):
        """Prove a conjunction of goals, yielding valid substitutions."""
        if depth > 500:
            return
        if not goals:
            yield sub
            return
        for new_sub in self.prove_one(goals[0], sub, context, depth):
            yield from self.prove_all(goals[1:], new_sub, context, depth)

    def prove_one(self, goal, sub, context, depth):
        """Prove a single goal, yielding substitutions."""
        if depth > 500:
            return

        goal = apply_sub(goal, sub)

        # ---- Special forms ----
        if is_compound(goal):
            if goal[0] == 'not':
                # Negation-as-failure: succeed iff inner goal has no proof
                for _ in self.prove_one(goal[1], sub, context, depth + 1):
                    return  # inner succeeded => negation fails
                yield sub
                return

            if goal[0] == 'distinct':
                t1 = apply_sub(goal[1], sub)
                t2 = apply_sub(goal[2], sub)
                if is_ground(t1) and is_ground(t2) and t1 != t2:
                    yield sub
                return

            if goal[0] == 'or':
                for disjunct in goal[1:]:
                    yield from self.prove_one(disjunct, sub, context, depth + 1)
                return

        # ---- Regular goal: match against context, facts, and rules ----
        pred = goal[0] if is_compound(goal) else goal

        # Try context facts (true/does injected for state queries)
        for fact in context.get(pred, set()):
            new_sub = unify(goal, fact, dict(sub))
            if new_sub is not None:
                yield new_sub

        # Try static facts from the game description
        for fact in self.facts_by_pred.get(pred, set()):
            new_sub = unify(goal, fact, dict(sub))
            if new_sub is not None:
                yield new_sub

        # Try rules via backward chaining
        for head, body in self.rules_by_head.get(pred, []):
            r_head, r_body = self._rename_rule(head, body)
            new_sub = unify(goal, r_head, dict(sub))
            if new_sub is not None:
                yield from self.prove_all(r_body, new_sub, context, depth + 1)

    def ask_all(self, query, context):
        """Find all ground instantiations of query that can be proved."""
        results = set()
        for sub in self.prove_one(query, {}, context, 0):
            result = apply_sub(query, sub)
            if is_ground(result):
                results.add(result)
        return results


# ============================================================
# GDL State Machine
# ============================================================

class GDLReasoner:
    """
    GDL game state machine built on backward-chaining logical inference.

    Loads a game from a KIF file and provides methods to query game
    states: initial state, legal moves, next state, terminal detection,
    and goal values.
    """

    def __init__(self, kif_path):
        with open(kif_path) as f:
            text = f.read()

        exprs = parse_sexps(text)

        rules = []
        facts = set()

        for expr in exprs:
            if is_compound(expr) and len(expr) >= 3 and expr[0] == '<=':
                head = expr[1]
                body = list(expr[2:])
                rules.append((head, body))
            else:
                facts.add(expr) if is_compound(expr) or isinstance(expr, str) else None

        self.prover = Prover(rules, facts)

    def _make_context(self, state_terms=None, move_terms=None):
        ctx = defaultdict(set)
        if state_terms:
            for prop in state_terms:
                ctx['true'].add(('true', prop))
        if move_terms:
            for role, move in move_terms.items():
                ctx['does'].add(('does', role, move))
        return ctx

    def _state_to_terms(self, state):
        return {str_to_term(s) for s in state}

    def get_roles(self):
        """Return sorted list of role names."""
        results = self.prover.ask_all(('role', '?r'), {})
        return sorted(r[1] for r in results)

    def get_initial_state(self):
        """Return set of initial state propositions as strings."""
        results = self.prover.ask_all(('init', '?p'), {})
        return {term_to_str(r[1]) for r in results}

    def get_legal_moves(self, state):
        """Return dict mapping each role to its sorted list of legal move strings."""
        ctx = self._make_context(state_terms=self._state_to_terms(state))
        results = self.prover.ask_all(('legal', '?r', '?m'), ctx)
        legal = defaultdict(list)
        for r in results:
            legal[r[1]].append(term_to_str(r[2]))
        return {k: sorted(v) for k, v in legal.items()}

    def get_next_state(self, state, moves):
        """Given current state and joint moves {role: move_string}, return next state."""
        state_terms = self._state_to_terms(state)
        move_terms = {}
        for role, move in moves.items():
            move_terms[role] = str_to_term(move) if isinstance(move, str) else move
        ctx = self._make_context(state_terms=state_terms, move_terms=move_terms)
        results = self.prover.ask_all(('next', '?p'), ctx)
        return {term_to_str(r[1]) for r in results}

    def is_terminal(self, state):
        """Return whether the state is terminal."""
        ctx = self._make_context(state_terms=self._state_to_terms(state))
        for _ in self.prover.prove_one('terminal', {}, ctx, 0):
            return True
        return False

    def get_goals(self, state):
        """Return dict mapping each role to its integer goal value."""
        ctx = self._make_context(state_terms=self._state_to_terms(state))
        results = self.prover.ask_all(('goal', '?r', '?v'), ctx)
        goals = {}
        for r in results:
            goals[r[1]] = int(r[2])
        return goals
