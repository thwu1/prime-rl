
"""GDL Query Engine — wraps SWI-Prolog subprocess calls for game state queries.

Provides a Python interface to query game properties (roles, initial state,
legal moves, next state, terminal detection, goal values) by executing
swipl against a transpiled Prolog game file.
"""

import subprocess
import tempfile
import os


def _atom_repr(s):
    """Represent a Python string as a valid Prolog atom/number."""
    try:
        int(s)
        return s
    except ValueError:
        if s and s[0].islower() and all(c.isalnum() or c == '_' for c in s):
            return s
        return "'" + s + "'"


def _tuple_to_prolog(t):
    """Convert a Python tuple to a Prolog term string."""
    if len(t) == 1:
        return _atom_repr(t[0])
    functor = _atom_repr(t[0])
    args = ', '.join(
        _atom_repr(a) if isinstance(a, str) else _tuple_to_prolog(a)
        for a in t[1:]
    )
    return functor + '(' + args + ')'


def _split_prolog_args(s):
    """Split comma-separated Prolog arguments respecting nesting."""
    args = []
    depth = 0
    current = []
    for c in s:
        if c == '(':
            depth += 1
            current.append(c)
        elif c == ')':
            depth -= 1
            current.append(c)
        elif c == ',' and depth == 0:
            args.append(''.join(current).strip())
            current = []
        else:
            current.append(c)
    if current:
        args.append(''.join(current).strip())
    return args


def _parse_prolog_term(s):
    """Parse a Prolog term string to a Python tuple of strings.

    Examples:
        'cell(1,1,b)' -> ('cell', '1', '1', 'b')
        'noop'        -> ('noop',)
        'mark(1,1)'   -> ('mark', '1', '1')
    """
    s = s.strip()
    if not s:
        return None

    paren_idx = s.find('(')
    if paren_idx == -1:
        return (s.strip("'"),)

    functor = s[:paren_idx].strip("'")
    args_str = s[paren_idx + 1:-1]
    args = _split_prolog_args(args_str)

    result = [functor]
    for arg in args:
        result.append(arg.strip("'"))
    return tuple(result)


class GdlQueryEngine:
    """Query engine that executes game-state queries via swipl subprocess."""

    def __init__(self, pl_path):
        self.pl_path = os.path.abspath(pl_path)

    def _run_query(self, prolog_code):
        """Write prolog_code to a temp file and run swipl on it. Return stdout lines."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.pl', delete=False, dir='/tmp'
        ) as f:
            f.write(prolog_code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                ['swipl', '-l', tmp_path],
                capture_output=True, text=True, timeout=60
            )
            if result.stdout.strip():
                return result.stdout.strip().split('\n')
            return []
        finally:
            os.unlink(tmp_path)

    def _state_assertions(self, state):
        """Generate Prolog :- assert(...) directives for a game state."""
        lines = []
        for t in sorted(state):
            term = _tuple_to_prolog(t)
            lines.append(':- assert(true_fact(' + term + ')).')
        return '\n'.join(lines)

    def _moves_assertions(self, moves):
        """Generate Prolog :- assert(...) directives for player moves."""
        lines = []
        for role in sorted(moves):
            move = moves[role]
            role_pl = _atom_repr(role)
            move_pl = _tuple_to_prolog(move)
            lines.append(':- assert(does_fact(' + role_pl + ', ' + move_pl + ')).')
        return '\n'.join(lines)

    def get_roles(self):
        """Return ordered list of player role strings."""
        code = (
            ":- consult('" + self.pl_path + "').\n"
            ":- forall(role(R), (write(R), nl)).\n"
            ":- halt.\n"
        )
        lines = self._run_query(code)
        return [l.strip().strip("'") for l in lines if l.strip()]

    def get_initial_state(self):
        """Return the initial game state as a frozenset of tuples."""
        code = (
            ":- consult('" + self.pl_path + "').\n"
            ":- forall(init(X), (writeq(X), nl)).\n"
            ":- halt.\n"
        )
        lines = self._run_query(code)
        result = set()
        for l in lines:
            l = l.strip()
            if l:
                t = _parse_prolog_term(l)
                if t:
                    result.add(t)
        return frozenset(result)

    def get_legal_moves(self, state, role):
        """Return set of legal move tuples for a role in the given state."""
        assertions = self._state_assertions(state)
        role_pl = _atom_repr(role)
        code = (
            ":- consult('" + self.pl_path + "').\n"
            + assertions + "\n"
            ":- forall(legal(" + role_pl + ", M), (writeq(M), nl)).\n"
            ":- halt.\n"
        )
        lines = self._run_query(code)
        result = set()
        for l in lines:
            l = l.strip()
            if l:
                t = _parse_prolog_term(l)
                if t:
                    result.add(t)
        return result

    def get_next_state(self, state, moves):
        """Given state and joint moves dict {role: move_tuple}, return next state."""
        state_assertions = self._state_assertions(state)
        moves_assertions = self._moves_assertions(moves)
        code = (
            ":- consult('" + self.pl_path + "').\n"
            + state_assertions + "\n"
            + moves_assertions + "\n"
            ":- forall(next(X), (writeq(X), nl)).\n"
            ":- halt.\n"
        )
        lines = self._run_query(code)
        result = set()
        for l in lines:
            l = l.strip()
            if l:
                t = _parse_prolog_term(l)
                if t:
                    result.add(t)
        return frozenset(result)

    def is_terminal(self, state):
        """Return whether the given state is terminal."""
        assertions = self._state_assertions(state)
        code = (
            ":- consult('" + self.pl_path + "').\n"
            + assertions + "\n"
            ":- (terminal -> write(true) ; write(false)), nl.\n"
            ":- halt.\n"
        )
        lines = self._run_query(code)
        return bool(lines) and lines[0].strip() == 'true'

    def get_goal(self, state, role):
        """Return integer goal value (0-100) for a role in the given state."""
        assertions = self._state_assertions(state)
        role_pl = _atom_repr(role)
        code = (
            ":- consult('" + self.pl_path + "').\n"
            + assertions + "\n"
            ":- goal(" + role_pl + ", V), write(V), nl.\n"
            ":- halt.\n"
        )
        lines = self._run_query(code)
        if lines and lines[0].strip():
            return int(lines[0].strip())
        return None
