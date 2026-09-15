#!/usr/bin/env python3
"""GDL (Game Description Language) Reasoner — State Machine Implementation.

Implements S-expression parsing, first-order unification, backward-chaining
inference with negation-as-failure/disjunction/distinct, and the GDL state
machine interface (roles, init, legal, next, terminal, goal).
"""
import sys
import json
from typing import List, Dict, Set, Optional, Generator


# ========================= S-Expression Parser =========================

def tokenize(text: str) -> List[str]:
    lines = []
    for line in text.split('\n'):
        idx = line.find(';')
        if idx >= 0:
            line = line[:idx]
        lines.append(line)
    text = '\n'.join(lines)
    tokens = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in ' \t\n\r':
            i += 1
        elif c == '(':
            tokens.append('(')
            i += 1
        elif c == ')':
            tokens.append(')')
            i += 1
        else:
            j = i
            while j < len(text) and text[j] not in ' \t\n\r()':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def parse_sexps(tokens: List[str]) -> list:
    results = []
    pos = [0]

    def parse_one():
        if pos[0] >= len(tokens):
            return None
        if tokens[pos[0]] == '(':
            pos[0] += 1
            lst = []
            while pos[0] < len(tokens) and tokens[pos[0]] != ')':
                lst.append(parse_one())
            if pos[0] < len(tokens):
                pos[0] += 1
            return lst
        else:
            atom = tokens[pos[0]]
            pos[0] += 1
            return atom

    while pos[0] < len(tokens):
        expr = parse_one()
        if expr is not None:
            results.append(expr)
    return results


# ========================= Term Types =========================

class Term:
    pass


class Var(Term):
    __slots__ = ('name',)

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, Var) and self.name == other.name

    def __hash__(self):
        return hash(self.name)


class Atom(Term):
    __slots__ = ('name',)

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, Atom) and self.name == other.name

    def __hash__(self):
        return hash(('A', self.name))


class Compound(Term):
    __slots__ = ('name', 'args')

    def __init__(self, name: str, args: tuple):
        self.name = name
        self.args = args if isinstance(args, tuple) else tuple(args)

    def __repr__(self):
        return f"({self.name} {' '.join(repr(a) for a in self.args)})"

    def __eq__(self, other):
        return (isinstance(other, Compound) and self.name == other.name
                and self.args == other.args)

    def __hash__(self):
        return hash(('C', self.name, self.args))


class Negation(Term):
    __slots__ = ('goal',)

    def __init__(self, goal: Term):
        self.goal = goal


class Disjunction(Term):
    __slots__ = ('goals',)

    def __init__(self, goals: list):
        self.goals = goals


class Distinct(Term):
    __slots__ = ('t1', 't2')

    def __init__(self, t1: Term, t2: Term):
        self.t1 = t1
        self.t2 = t2


class Rule:
    __slots__ = ('head', 'body')

    def __init__(self, head: Term, body: list):
        self.head = head
        self.body = body


# ========================= S-exp → Term =========================

def sexp_to_term(sexp) -> Term:
    if isinstance(sexp, str):
        if sexp.startswith('?'):
            return Var(sexp)
        return Atom(sexp)
    if isinstance(sexp, list):
        if not sexp:
            raise ValueError("Empty list")
        head = sexp[0]
        if head == 'not':
            return Negation(sexp_to_term(sexp[1]))
        if head == 'or':
            return Disjunction([sexp_to_term(s) for s in sexp[1:]])
        if head == 'distinct':
            return Distinct(sexp_to_term(sexp[1]), sexp_to_term(sexp[2]))
        args = [sexp_to_term(s) for s in sexp[1:]]
        if args:
            return Compound(head, args)
        return Atom(head)
    raise ValueError(f"Bad sexp: {sexp}")


def parse_gdl(text: str):
    tokens = tokenize(text)
    sexps = parse_sexps(tokens)
    facts = []
    rules = []
    for sexp in sexps:
        if isinstance(sexp, list) and len(sexp) >= 3 and sexp[0] == '<=':
            head = sexp_to_term(sexp[1])
            body = [sexp_to_term(b) for b in sexp[2:]]
            rules.append(Rule(head, body))
        else:
            facts.append(sexp_to_term(sexp))
    return facts, rules


# ========================= Unification =========================

def walk(term: Term, subst: dict) -> Term:
    while isinstance(term, Var) and term in subst:
        term = subst[term]
    return term


def occurs_in(var: Var, term: Term, subst: dict) -> bool:
    term = walk(term, subst)
    if isinstance(term, Var):
        return var == term
    if isinstance(term, Compound):
        return any(occurs_in(var, a, subst) for a in term.args)
    return False


def unify(t1: Term, t2: Term, subst: Optional[dict]) -> Optional[dict]:
    if subst is None:
        return None
    t1 = walk(t1, subst)
    t2 = walk(t2, subst)
    if t1 == t2:
        return subst
    if isinstance(t1, Var):
        if occurs_in(t1, t2, subst):
            return None
        s = dict(subst)
        s[t1] = t2
        return s
    if isinstance(t2, Var):
        if occurs_in(t2, t1, subst):
            return None
        s = dict(subst)
        s[t2] = t1
        return s
    if isinstance(t1, Compound) and isinstance(t2, Compound):
        if t1.name != t2.name or len(t1.args) != len(t2.args):
            return None
        for a, b in zip(t1.args, t2.args):
            subst = unify(a, b, subst)
            if subst is None:
                return None
        return subst
    return None


def apply_subst(term: Term, subst: dict) -> Term:
    if isinstance(term, Var):
        r = walk(term, subst)
        if isinstance(r, Var):
            return r
        return apply_subst(r, subst)
    if isinstance(term, Atom):
        return term
    if isinstance(term, Compound):
        return Compound(term.name, tuple(apply_subst(a, subst) for a in term.args))
    if isinstance(term, Negation):
        return Negation(apply_subst(term.goal, subst))
    if isinstance(term, Disjunction):
        return Disjunction([apply_subst(g, subst) for g in term.goals])
    if isinstance(term, Distinct):
        return Distinct(apply_subst(term.t1, subst), apply_subst(term.t2, subst))
    return term


def has_vars(term: Term) -> bool:
    if isinstance(term, Var):
        return True
    if isinstance(term, Atom):
        return False
    if isinstance(term, Compound):
        return any(has_vars(a) for a in term.args)
    return False


# ========================= Variable Renaming =========================

_vc = [0]


def _rename(term: Term, m: dict) -> Term:
    if isinstance(term, Var):
        if term.name not in m:
            _vc[0] += 1
            m[term.name] = Var(f"_R{_vc[0]}")
        return m[term.name]
    if isinstance(term, Atom):
        return term
    if isinstance(term, Compound):
        return Compound(term.name, tuple(_rename(a, m) for a in term.args))
    if isinstance(term, Negation):
        return Negation(_rename(term.goal, m))
    if isinstance(term, Disjunction):
        return Disjunction([_rename(g, m) for g in term.goals])
    if isinstance(term, Distinct):
        return Distinct(_rename(term.t1, m), _rename(term.t2, m))
    return term


def rename_rule(rule: Rule) -> Rule:
    m = {}
    return Rule(_rename(rule.head, m), [_rename(b, m) for b in rule.body])


# ========================= Prover =========================

def _get_name(term: Term) -> Optional[str]:
    if isinstance(term, Atom):
        return term.name
    if isinstance(term, Compound):
        return term.name
    return None


class Prover:
    def __init__(self, facts: list, rules: list):
        self.facts_idx: Dict[str, list] = {}
        self.rules_idx: Dict[str, list] = {}
        for f in facts:
            n = _get_name(f)
            self.facts_idx.setdefault(n, []).append(f)
        for r in rules:
            n = _get_name(r.head)
            self.rules_idx.setdefault(n, []).append(r)

    def ask_all(self, query: Term, ctx: Optional[dict] = None) -> List[dict]:
        if ctx is None:
            ctx = {}
        results = []
        seen: Set[str] = set()
        for subst in self._prove(query, {}, ctx, 0):
            resolved = apply_subst(query, subst)
            key = repr(resolved)
            if key not in seen:
                seen.add(key)
                results.append(subst)
        return results

    def ask_any(self, query: Term, ctx: Optional[dict] = None) -> bool:
        if ctx is None:
            ctx = {}
        for _ in self._prove(query, {}, ctx, 0):
            return True
        return False

    def _prove(self, goal: Term, subst: dict, ctx: dict, depth: int) -> Generator:
        if depth > 300:
            return
        goal = apply_subst(goal, subst)

        if isinstance(goal, Negation):
            inner = apply_subst(goal.goal, subst)
            for _ in self._prove(inner, subst, ctx, depth + 1):
                return  # inner succeeded → negation fails
            yield subst  # inner failed → negation succeeds
            return

        if isinstance(goal, Disjunction):
            for alt in goal.goals:
                yield from self._prove(alt, subst, ctx, depth + 1)
            return

        if isinstance(goal, Distinct):
            a = apply_subst(goal.t1, subst)
            b = apply_subst(goal.t2, subst)
            if not has_vars(a) and not has_vars(b) and a != b:
                yield subst
            return

        name = _get_name(goal)

        # Context facts (true/does)
        if name in ctx:
            for fact in ctx[name]:
                s = unify(goal, fact, dict(subst))
                if s is not None:
                    yield s

        # Static facts
        if name in self.facts_idx:
            for fact in self.facts_idx[name]:
                s = unify(goal, fact, dict(subst))
                if s is not None:
                    yield s

        # Rules
        if name in self.rules_idx:
            for rule in self.rules_idx[name]:
                rr = rename_rule(rule)
                s = unify(goal, rr.head, dict(subst))
                if s is not None:
                    yield from self._prove_conj(rr.body, s, ctx, depth + 1)

    def _prove_conj(self, goals: list, subst: dict, ctx: dict, depth: int) -> Generator:
        if not goals:
            yield subst
            return
        for s in self._prove(goals[0], subst, ctx, depth):
            yield from self._prove_conj(goals[1:], s, ctx, depth)


# ========================= GDL State Machine =========================

def term_to_str(term: Term) -> str:
    if isinstance(term, Atom):
        return term.name
    if isinstance(term, Compound):
        return f"({term.name} {' '.join(term_to_str(a) for a in term.args)})"
    if isinstance(term, Var):
        return term.name
    return str(term)


def str_to_term(s: str) -> Term:
    s = s.strip()
    if s.startswith('('):
        tokens = tokenize(s)
        sexps = parse_sexps(tokens)
        return sexp_to_term(sexps[0])
    if s.startswith('?'):
        return Var(s)
    return Atom(s)


class GDLStateMachine:
    def __init__(self, kif_path: str):
        with open(kif_path) as f:
            text = f.read()
        facts, rules = parse_gdl(text)
        self.prover = Prover(facts, rules)

    def roles(self) -> List[str]:
        q = Compound('role', (Var('?_r'),))
        out = []
        seen: Set[str] = set()
        for subst in self.prover.ask_all(q):
            r = term_to_str(apply_subst(Var('?_r'), subst))
            if r not in seen:
                seen.add(r)
                out.append(r)
        return out

    def initial_state(self) -> List[str]:
        q = Compound('init', (Var('?_x'),))
        out: Set[str] = set()
        for subst in self.prover.ask_all(q):
            f = apply_subst(Var('?_x'), subst)
            if not has_vars(f):
                out.add(term_to_str(f))
        return sorted(out)

    def _ctx(self, state: List[str], moves: Optional[Dict[str, str]] = None) -> dict:
        ctx: dict = {}
        true_facts = []
        for s in state:
            true_facts.append(Compound('true', (str_to_term(s),)))
        ctx['true'] = true_facts
        if moves:
            does_facts = []
            for role, move in moves.items():
                does_facts.append(Compound('does', (Atom(role), str_to_term(move))))
            ctx['does'] = does_facts
        return ctx

    def legal_moves(self, state: List[str], role: str) -> List[str]:
        ctx = self._ctx(state)
        q = Compound('legal', (Atom(role), Var('?_m')))
        out: Set[str] = set()
        for subst in self.prover.ask_all(q, ctx):
            m = apply_subst(Var('?_m'), subst)
            if not has_vars(m):
                out.add(term_to_str(m))
        return sorted(out)

    def next_state(self, state: List[str], moves: Dict[str, str]) -> List[str]:
        ctx = self._ctx(state, moves)
        q = Compound('next', (Var('?_x'),))
        out: Set[str] = set()
        for subst in self.prover.ask_all(q, ctx):
            f = apply_subst(Var('?_x'), subst)
            if not has_vars(f):
                out.add(term_to_str(f))
        return sorted(out)

    def is_terminal(self, state: List[str]) -> bool:
        ctx = self._ctx(state)
        return self.prover.ask_any(Atom('terminal'), ctx)

    def goal(self, state: List[str], role: str) -> int:
        ctx = self._ctx(state)
        q = Compound('goal', (Atom(role), Var('?_v')))
        for subst in self.prover.ask_all(q, ctx):
            v = apply_subst(Var('?_v'), subst)
            return int(term_to_str(v))
        raise ValueError(f"No goal for {role}")


# ========================= CLI =========================

def main():
    if len(sys.argv) < 3:
        print("Usage: gdl_reasoner.py <game.kif> <command> [args...]",
              file=sys.stderr)
        sys.exit(1)

    sm = GDLStateMachine(sys.argv[1])
    cmd = sys.argv[2]

    if cmd == 'roles':
        print(json.dumps(sm.roles()))
    elif cmd == 'initial_state':
        print(json.dumps(sm.initial_state()))
    elif cmd == 'legal_moves':
        role = sys.argv[3]
        state = json.loads(sys.argv[4])
        print(json.dumps(sm.legal_moves(state, role)))
    elif cmd == 'next_state':
        state = json.loads(sys.argv[3])
        moves = json.loads(sys.argv[4])
        print(json.dumps(sm.next_state(state, moves)))
    elif cmd == 'is_terminal':
        state = json.loads(sys.argv[3])
        print(json.dumps(sm.is_terminal(state)))
    elif cmd == 'goal':
        role = sys.argv[3]
        state = json.loads(sys.argv[4])
        print(json.dumps(sm.goal(state, role)))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
