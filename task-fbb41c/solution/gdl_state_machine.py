
"""
GDL State Machine — complete interpreter for Game Description Language.

Implements KIF parsing, unification, resolution-based logical inference
(with negation-as-failure, disjunction, distinct), and a state machine
wrapper for General Game Playing.
"""


# ---------------------------------------------------------------------------
# Tokenizer & S-expression parser
# ---------------------------------------------------------------------------

def _tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == ';':
            while i < n and text[i] != '\n':
                i += 1
            continue
        if c in ' \t\n\r':
            i += 1
            continue
        if c == '(':
            tokens.append('(')
            i += 1
        elif c == ')':
            tokens.append(')')
            i += 1
        else:
            j = i
            while j < n and text[j] not in ' \t\n\r();':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def _parse_sexps(tokens):
    results = []
    i = 0
    n = len(tokens)
    while i < n:
        if tokens[i] == '(':
            expr, i = _parse_list(tokens, i + 1)
            results.append(expr)
        else:
            results.append(tokens[i])
            i += 1
    return results


def _parse_list(tokens, i):
    items = []
    n = len(tokens)
    while i < n and tokens[i] != ')':
        if tokens[i] == '(':
            expr, i = _parse_list(tokens, i + 1)
            items.append(expr)
        else:
            items.append(tokens[i])
            i += 1
    return items, i + 1


# ---------------------------------------------------------------------------
# GDL term types
# ---------------------------------------------------------------------------

class Var:
    """Logic variable (?name)."""
    __slots__ = ('name',)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '?' + self.name

    def __eq__(self, other):
        return isinstance(other, Var) and self.name == other.name

    def __hash__(self):
        return hash(self.name) ^ 0x9E3779B9


class Rel:
    """Compound relation/function (name arg1 arg2 ...)."""
    __slots__ = ('name', 'args')

    def __init__(self, name, args):
        self.name = name
        self.args = tuple(args)

    def __repr__(self):
        return '(' + self.name + ' ' + ' '.join(repr(a) for a in self.args) + ')'

    def __eq__(self, other):
        return isinstance(other, Rel) and self.name == other.name and self.args == other.args

    def __hash__(self):
        return hash((self.name, self.args))


class Not:
    __slots__ = ('body',)
    def __init__(self, body):
        self.body = body


class Or:
    __slots__ = ('disjuncts',)
    def __init__(self, disjuncts):
        self.disjuncts = tuple(disjuncts)


class Distinct:
    __slots__ = ('t1', 't2')
    def __init__(self, t1, t2):
        self.t1 = t1
        self.t2 = t2


class Rule:
    __slots__ = ('head', 'body')
    def __init__(self, head, body):
        self.head = head
        self.body = tuple(body)


# ---------------------------------------------------------------------------
# Term builder — converts parsed S-expression to typed term
# ---------------------------------------------------------------------------

def _build(sexp):
    if isinstance(sexp, str):
        return Var(sexp[1:]) if sexp.startswith('?') else sexp
    if not isinstance(sexp, list) or len(sexp) == 0:
        raise ValueError(f'Bad sexp: {sexp}')
    head = sexp[0]
    if head == 'not':
        return Not(_build(sexp[1]))
    if head == 'or':
        return Or([_build(x) for x in sexp[1:]])
    if head == 'distinct':
        return Distinct(_build(sexp[1]), _build(sexp[2]))
    return Rel(head, [_build(x) for x in sexp[1:]])


def _load_kif(path):
    with open(path) as f:
        text = f.read()
    sexps = _parse_sexps(_tokenize(text))
    facts, rules = [], []
    for s in sexps:
        term = _build(s)
        if isinstance(term, Rel) and term.name == '<=':
            rules.append(Rule(term.args[0], list(term.args[1:])))
        else:
            facts.append(term)
    return facts, rules


# ---------------------------------------------------------------------------
# Unification
# ---------------------------------------------------------------------------

def _walk(t, s):
    while isinstance(t, Var) and t in s:
        t = s[t]
    return t


def _unify(a, b, s):
    if s is None:
        return None
    a = _walk(a, s)
    b = _walk(b, s)
    if a == b:
        return s
    if isinstance(a, Var):
        return {**s, a: b}
    if isinstance(b, Var):
        return {**s, b: a}
    if isinstance(a, Rel) and isinstance(b, Rel):
        if a.name != b.name or len(a.args) != len(b.args):
            return None
        for x, y in zip(a.args, b.args):
            s = _unify(x, y, s)
            if s is None:
                return None
        return s
    return None  # incompatible types or different constants


def _apply(term, s):
    """Fully resolve a term under substitution *s*."""
    if isinstance(term, Var):
        t = _walk(term, s)
        return t if isinstance(t, Var) else _apply(t, s)
    if isinstance(term, str):
        return term
    if isinstance(term, Rel):
        return Rel(term.name, tuple(_apply(a, s) for a in term.args))
    if isinstance(term, Not):
        return Not(_apply(term.body, s))
    if isinstance(term, Or):
        return Or(tuple(_apply(d, s) for d in term.disjuncts))
    if isinstance(term, Distinct):
        return Distinct(_apply(term.t1, s), _apply(term.t2, s))
    return term


# ---------------------------------------------------------------------------
# Logic prover
# ---------------------------------------------------------------------------

class _Prover:
    def __init__(self, facts, rules):
        self._facts = {}
        self._rules = {}
        for f in facts:
            key = f.name if isinstance(f, Rel) else f
            self._facts.setdefault(key, []).append(f)
        for r in rules:
            key = r.head.name if isinstance(r.head, Rel) else r.head
            self._rules.setdefault(key, []).append(r)
        self._vc = 0
        self._ctx = {}

    def set_ctx(self, ctx):
        self._ctx = ctx

    # -- variable renaming --------------------------------------------------

    def _rename(self, rule):
        self._vc += 1
        sfx = f'_{self._vc}'
        memo = {}

        def go(t):
            if isinstance(t, Var):
                if t.name not in memo:
                    memo[t.name] = Var(t.name + sfx)
                return memo[t.name]
            if isinstance(t, str):
                return t
            if isinstance(t, Rel):
                return Rel(t.name, tuple(go(a) for a in t.args))
            if isinstance(t, Not):
                return Not(go(t.body))
            if isinstance(t, Or):
                return Or(tuple(go(d) for d in t.disjuncts))
            if isinstance(t, Distinct):
                return Distinct(go(t.t1), go(t.t2))
            return t

        return Rule(go(rule.head), tuple(go(b) for b in rule.body))

    # -- core query engine ---------------------------------------------------

    def ask(self, goal, s, depth=0):
        if depth > 128:
            return []
        goal = _apply(goal, s)

        if isinstance(goal, Not):
            return [] if self.ask(goal.body, s, depth + 1) else [s]

        if isinstance(goal, Or):
            out = []
            for d in goal.disjuncts:
                out.extend(self.ask(d, s, depth + 1))
            return out

        if isinstance(goal, Distinct):
            t1 = _apply(goal.t1, s)
            t2 = _apply(goal.t2, s)
            if isinstance(t1, Var) or isinstance(t2, Var):
                return []
            return [s] if t1 != t2 else []

        results = []

        if isinstance(goal, str):
            # bare atom (e.g. "terminal", "boardOpen")
            for f in self._facts.get(goal, []):
                if isinstance(f, str) and f == goal:
                    results.append(s)
            for f in self._ctx.get(goal, []):
                if isinstance(f, str) and f == goal:
                    results.append(s)
            for r in self._rules.get(goal, []):
                r2 = self._rename(r)
                if isinstance(r2.head, str):
                    results.extend(self._conj(r2.body, s, depth + 1))
            return results

        if isinstance(goal, Rel):
            for f in self._facts.get(goal.name, []):
                u = _unify(goal, f, s)
                if u is not None:
                    results.append(u)
            for f in self._ctx.get(goal.name, []):
                u = _unify(goal, f, s)
                if u is not None:
                    results.append(u)
            for r in self._rules.get(goal.name, []):
                r2 = self._rename(r)
                u = _unify(goal, r2.head, s)
                if u is not None:
                    results.extend(self._conj(r2.body, u, depth + 1))
            return results

        return results

    def _conj(self, goals, s, depth):
        if not goals:
            return [s]
        first, rest = goals[0], goals[1:]
        out = []
        for s2 in self.ask(first, s, depth):
            out.extend(self._conj(rest, s2, depth))
        return out


# ---------------------------------------------------------------------------
# Tuple ↔ Term conversion
# ---------------------------------------------------------------------------

def _to_tuple(term):
    if isinstance(term, str):
        return (term,)
    if isinstance(term, Rel):
        parts = [term.name]
        for a in term.args:
            if isinstance(a, Rel):
                parts.append(_to_tuple(a))
            elif isinstance(a, str):
                parts.append(a)
            else:
                parts.append(str(a))
        return tuple(parts)
    return (str(term),)


def _from_tuple(t):
    if isinstance(t, str):
        return t
    if isinstance(t, tuple):
        if len(t) == 1 and isinstance(t[0], str):
            return t[0]
        return Rel(t[0], [_from_tuple(a) for a in t[1:]])
    return t


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class GdlStateMachine:
    def __init__(self, kif_path):
        facts, rules = _load_kif(kif_path)
        self._prover = _Prover(facts, rules)

    # -- helpers -------------------------------------------------------------

    def _ctx_for(self, state, moves=None):
        ctx = {}
        for t in state:
            term = _from_tuple(t)
            ctx.setdefault('true', []).append(Rel('true', [term]))
        if moves:
            for role, move in moves.items():
                ctx.setdefault('does', []).append(
                    Rel('does', [role, _from_tuple(move)])
                )
        return ctx

    def _collect(self, var_name, results):
        seen = set()
        out = []
        for s in results:
            v = _apply(Var(var_name), s)
            t = _to_tuple(v)
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    # -- public API ----------------------------------------------------------

    def get_roles(self):
        results = self._prover.ask(Rel('role', [Var('R')]), {})
        seen = []
        for s in results:
            v = _apply(Var('R'), s)
            if isinstance(v, str) and v not in seen:
                seen.append(v)
        return seen

    def get_initial_state(self):
        results = self._prover.ask(Rel('init', [Var('X')]), {})
        return frozenset(t for t in dict.fromkeys(
            _to_tuple(_apply(Var('X'), s)) for s in results
        ))

    def get_legal_moves(self, state, role):
        self._prover.set_ctx(self._ctx_for(state))
        results = self._prover.ask(Rel('legal', [role, Var('M')]), {})
        self._prover.set_ctx({})
        return set(_to_tuple(_apply(Var('M'), s)) for s in results)

    def get_next_state(self, state, moves):
        self._prover.set_ctx(self._ctx_for(state, moves))
        results = self._prover.ask(Rel('next', [Var('X')]), {})
        self._prover.set_ctx({})
        return frozenset(_to_tuple(_apply(Var('X'), s)) for s in results)

    def is_terminal(self, state):
        self._prover.set_ctx(self._ctx_for(state))
        out = bool(self._prover.ask('terminal', {}))
        self._prover.set_ctx({})
        return out

    def get_goal(self, state, role):
        self._prover.set_ctx(self._ctx_for(state))
        results = self._prover.ask(Rel('goal', [role, Var('V')]), {})
        self._prover.set_ctx({})
        for s in results:
            v = _apply(Var('V'), s)
            if isinstance(v, str):
                return int(v)
        return None
