"""
GDL (Game Description Language) Reasoner for General Game Playing.
"""

# ==================== PARSING ====================


def _tokenize(text):
    """Tokenize GDL text, stripping ; comments."""
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == ';':
            while i < n and text[i] != '\n':
                i += 1
        elif c in ' \t\n\r':
            i += 1
        elif c == '(':
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


def _parse_one(tokens, pos):
    """Parse one S-expression starting at pos. Returns (term, new_pos)."""
    if tokens[pos] == '(':
        pos += 1
        items = []
        while tokens[pos] != ')':
            item, pos = _parse_one(tokens, pos)
            items.append(item)
        return tuple(items), pos + 1
    return tokens[pos], pos + 1


def _parse_all(text):
    """Parse GDL text into list of term expressions."""
    tokens = _tokenize(text)
    exprs = []
    pos = 0
    while pos < len(tokens):
        expr, pos = _parse_one(tokens, pos)
        exprs.append(expr)
    return exprs


# ==================== TERM UTILITIES ====================


def _is_var(t):
    return isinstance(t, str) and len(t) > 1 and t[0] == '?'


def _is_compound(t):
    return isinstance(t, tuple)


def _term_str(t):
    """Convert internal term to normalized string."""
    if _is_compound(t):
        return '(' + ' '.join(_term_str(x) for x in t) + ')'
    return t


def _str_term(s):
    """Parse a normalized string back to internal term."""
    s = s.strip()
    if not s or s[0] != '(':
        return s
    tokens = _tokenize(s)
    r, _ = _parse_one(tokens, 0)
    return r


# ==================== SUBSTITUTION ====================


def _apply(term, sub):
    """Apply substitution, chasing variable bindings."""
    if _is_var(term):
        if term in sub:
            return _apply(sub[term], sub)
        return term
    if _is_compound(term):
        return tuple(_apply(x, sub) for x in term)
    return term


def _occurs(var, term, sub):
    """Occurs check: does var appear in term under sub?"""
    term = _apply(term, sub)
    if var == term:
        return True
    if _is_compound(term):
        return any(_occurs(var, x, sub) for x in term)
    return False


# ==================== UNIFICATION ====================


def _unify(a, b, sub):
    """Unify terms a and b under substitution. Returns new sub or None."""
    if sub is None:
        return None
    a = _apply(a, sub)
    b = _apply(b, sub)
    if a == b:
        return sub
    if _is_var(a):
        if _occurs(a, b, sub):
            return None
        return {**sub, a: b}
    if _is_var(b):
        if _occurs(b, a, sub):
            return None
        return {**sub, b: a}
    if _is_compound(a) and _is_compound(b) and len(a) == len(b):
        for x, y in zip(a, b):
            sub = _unify(x, y, sub)
            if sub is None:
                return None
        return sub
    return None


# ==================== KNOWLEDGE BASE ====================


class _KB:
    """Knowledge base indexed by predicate functor."""

    def __init__(self, exprs):
        self.facts = {}   # functor -> [term]
        self.rules = {}   # functor -> [(head, body)]
        for e in exprs:
            if _is_compound(e) and len(e) >= 2 and e[0] == '<=':
                head = e[1]
                body = list(e[2:])
                f = head[0] if _is_compound(head) else head
                self.rules.setdefault(f, []).append((head, body))
            else:
                f = e[0] if _is_compound(e) else e
                self.facts.setdefault(f, []).append(e)


# ==================== PROVER ====================


class _Prover:
    """Recursive prover for GDL queries."""

    def __init__(self, kb):
        self.kb = kb
        self._counter = 0

    def _fresh(self):
        self._counter += 1
        return self._counter

    def _rename_term(self, term, mapping):
        if _is_var(term):
            if term not in mapping:
                mapping[term] = f'?_v{self._fresh()}'
            return mapping[term]
        if _is_compound(term):
            return tuple(self._rename_term(x, mapping) for x in term)
        return term

    def _rename_clause(self, head, body):
        m = {}
        h = self._rename_term(head, m)
        b = [self._rename_term(g, m) for g in body]
        return h, b

    def query(self, goal, state, does):
        """Return all unique ground instances of goal."""
        results = []
        self._solve([goal], {}, state, does, results, 0)
        seen = set()
        out = []
        for sub in results:
            t = _apply(goal, sub)
            k = repr(t)
            if k not in seen:
                seen.add(k)
                out.append(t)
        return out

    def _solve(self, goals, sub, state, does, results, depth):
        if depth > 200:
            return
        if not goals:
            results.append(dict(sub))
            return

        goal = _apply(goals[0], sub)
        rest = goals[1:]

        # ---- Special forms ----
        if _is_compound(goal):
            fn = goal[0]

            if fn == 'true':
                self._solve_true(goal[1], rest, sub, state, does, results, depth)
                return

            if fn == 'does':
                self._solve_does(goal, rest, sub, state, does, results, depth)
                return

            if fn == 'not':
                self._solve_not(goal[1], rest, sub, state, does, results, depth)
                return

            if fn == 'or':
                self._solve_or(goal[1:], rest, sub, state, does, results, depth)
                return

            if fn == 'distinct':
                self._solve_distinct(goal[1], goal[2], rest, sub, state, does, results, depth)
                return

        # ---- Regular predicate: facts then rules ----
        fn = goal[0] if _is_compound(goal) else goal

        for fact in self.kb.facts.get(fn, []):
            rh, _ = self._rename_clause(fact, [])
            s = _unify(goal, rh, dict(sub))
            if s is not None:
                self._solve(rest, s, state, does, results, depth + 1)

        for head, body in self.kb.rules.get(fn, []):
            rh, rb = self._rename_clause(head, body)
            s = _unify(goal, rh, dict(sub))
            if s is not None:
                self._solve(rb + rest, s, state, does, results, depth + 1)

    def _solve_true(self, inner, rest, sub, state, does, results, depth):
        """(true X) — match X against current state facts."""
        for fact in state:
            s = _unify(inner, fact, dict(sub))
            if s is not None:
                self._solve(rest, s, state, does, results, depth + 1)

    def _solve_does(self, goal, rest, sub, state, does, results, depth):
        """(does role move) — match against action context."""
        for dfact in does:
            s = _unify(goal, dfact, dict(sub))
            if s is not None:
                self._solve(rest, s, state, does, results, depth + 1)

    def _solve_not(self, inner, rest, sub, state, does, results, depth):
        """Negation: (not X) succeeds iff X has no solutions."""
        neg = []
        self._solve([inner], dict(sub), state, does, neg, depth + 1)
        if not neg:
            self._solve(rest, sub, state, does, results, depth + 1)

    def _solve_or(self, disjuncts, rest, sub, state, does, results, depth):
        """(or D1 D2 ...) — try each disjunct."""
        for d in disjuncts:
            self._solve([d] + rest, dict(sub), state, does, results, depth + 1)

    def _solve_distinct(self, a, b, rest, sub, state, does, results, depth):
        """(distinct A B) — succeeds if A and B are ground and unequal."""
        va = _apply(a, sub)
        vb = _apply(b, sub)
        if va != vb and not _is_var(va) and not _is_var(vb):
            self._solve(rest, sub, state, does, results, depth + 1)


# ==================== GDL REASONER ====================


class GDLReasoner:
    """Game Description Language reasoner."""

    def __init__(self, gdl_text):
        exprs = _parse_all(gdl_text)
        self._kb = _KB(exprs)
        self._prover = _Prover(self._kb)
        self._roles_cache = None
        self._init_cache = None

    @classmethod
    def from_file(cls, path):
        with open(path) as f:
            return cls(f.read())

    def get_roles(self):
        if self._roles_cache is None:
            results = self._prover.query(('role', '?_qr'), frozenset(), [])
            self._roles_cache = []
            for r in results:
                val = r[1] if _is_compound(r) else r
                self._roles_cache.append(val if isinstance(val, str) else _term_str(val))
        return list(self._roles_cache)

    def get_initial_state(self):
        if self._init_cache is None:
            results = self._prover.query(('init', '?_qi'), frozenset(), [])
            self._init_cache = frozenset(
                _term_str(r[1]) for r in results if _is_compound(r)
            )
        return self._init_cache

    def _to_terms(self, state_strs):
        return frozenset(_str_term(s) for s in state_strs)

    def get_legal_moves(self, state, role):
        st = self._to_terms(state)
        rt = _str_term(role)
        results = self._prover.query(('legal', rt, '?_qm'), st, [])
        moves = set()
        for r in results:
            if _is_compound(r) and len(r) >= 3:
                moves.add(_term_str(r[2]))
        return moves

    def get_next_state(self, state, moves):
        st = self._to_terms(state)
        does = []
        for role_s, move_s in moves.items():
            r = _str_term(role_s)
            m = _str_term(move_s)
            does.append(('does', r, m))
        results = self._prover.query(('next', '?_qn'), st, does)
        return frozenset(
            _term_str(r[1]) for r in results if _is_compound(r) and r[0] == 'next'
        )

    def is_terminal(self, state):
        st = self._to_terms(state)
        results = self._prover.query('terminal', st, [])
        return len(results) > 0

    def get_goal(self, state, role):
        st = self._to_terms(state)
        rt = _str_term(role)
        results = self._prover.query(('goal', rt, '?_qv'), st, [])
        for r in results:
            if _is_compound(r) and len(r) >= 3:
                return int(r[2])
        return None
