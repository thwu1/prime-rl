"""
Extended Regular Expression Algebra — Complete Implementation

"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Set


class Regex:
    """Base class for regular expression AST nodes."""
    pass


@dataclass(frozen=True)
class Empty(Regex):
    """The empty set -- matches no strings."""
    pass


@dataclass(frozen=True)
class Epsilon(Regex):
    """The empty string -- matches only the empty string."""
    pass


@dataclass(frozen=True)
class Char(Regex):
    """A single character literal."""
    c: str


@dataclass(frozen=True)
class Alt(Regex):
    """Alternation (union): L(left) | L(right)."""
    left: Regex
    right: Regex


@dataclass(frozen=True)
class Seq(Regex):
    """Concatenation (sequence): L(left) . L(right)."""
    left: Regex
    right: Regex


@dataclass(frozen=True)
class Star(Regex):
    """Kleene star: L(expr)*."""
    expr: Regex


@dataclass(frozen=True)
class Complement(Regex):
    """Complement: all strings over the alphabet NOT in L(expr)."""
    expr: Regex


@dataclass(frozen=True)
class Intersection(Regex):
    """Intersection: L(left) & L(right)."""
    left: Regex
    right: Regex


# ─── Smart constructors with algebraic simplification ────────────────

def _mk_alt(r1: Regex, r2: Regex) -> Regex:
    if isinstance(r1, Empty):
        return r2
    if isinstance(r2, Empty):
        return r1
    if r1 == r2:
        return r1
    return Alt(r1, r2)


def _mk_seq(r1: Regex, r2: Regex) -> Regex:
    if isinstance(r1, Empty) or isinstance(r2, Empty):
        return Empty()
    if isinstance(r1, Epsilon):
        return r2
    if isinstance(r2, Epsilon):
        return r1
    return Seq(r1, r2)


def _mk_star(r: Regex) -> Regex:
    if isinstance(r, Empty) or isinstance(r, Epsilon):
        return Epsilon()
    if isinstance(r, Star):
        return r
    return Star(r)


def _mk_complement(r: Regex) -> Regex:
    if isinstance(r, Complement):
        return r.expr
    return Complement(r)


def _mk_intersection(r1: Regex, r2: Regex) -> Regex:
    if isinstance(r1, Empty) or isinstance(r2, Empty):
        return Empty()
    if r1 == r2:
        return r1
    return Intersection(r1, r2)


# ─── Core operations ─────────────────────────────────────────────────

def nullable(r: Regex) -> bool:
    """Return True if the empty string is in L(r)."""
    if isinstance(r, Empty):
        return False
    if isinstance(r, Epsilon):
        return True
    if isinstance(r, Char):
        return False
    if isinstance(r, Alt):
        return nullable(r.left) or nullable(r.right)
    if isinstance(r, Seq):
        return nullable(r.left) and nullable(r.right)
    if isinstance(r, Star):
        return True
    if isinstance(r, Complement):
        return not nullable(r.expr)
    if isinstance(r, Intersection):
        return nullable(r.left) and nullable(r.right)
    raise TypeError(f"Unknown regex node: {type(r)}")


def _derivative(r: Regex, c: str) -> Regex:
    """Compute the Brzozowski derivative of r with respect to character c."""
    if isinstance(r, Empty):
        return Empty()
    if isinstance(r, Epsilon):
        return Empty()
    if isinstance(r, Char):
        return Epsilon() if r.c == c else Empty()
    if isinstance(r, Alt):
        return _mk_alt(_derivative(r.left, c), _derivative(r.right, c))
    if isinstance(r, Seq):
        d = _mk_seq(_derivative(r.left, c), r.right)
        if nullable(r.left):
            return _mk_alt(d, _derivative(r.right, c))
        return d
    if isinstance(r, Star):
        return _mk_seq(_derivative(r.expr, c), _mk_star(r.expr))
    if isinstance(r, Complement):
        return _mk_complement(_derivative(r.expr, c))
    if isinstance(r, Intersection):
        return _mk_intersection(_derivative(r.left, c), _derivative(r.right, c))
    raise TypeError(f"Unknown regex node: {type(r)}")


def matches(r: Regex, s: str) -> bool:
    """Return True if string s is in L(r)."""
    current = r
    for ch in s:
        current = _derivative(current, ch)
    return nullable(current)


def is_empty(r: Regex, alphabet: Set[str]) -> bool:
    """Return True if L(r) = {} by exploring reachable states."""
    visited: set = set()
    worklist = [r]
    while worklist:
        current = worklist.pop()
        if current in visited:
            continue
        visited.add(current)
        if nullable(current):
            return False
        for ch in sorted(alphabet):
            d = _derivative(current, ch)
            if d not in visited:
                worklist.append(d)
    return True


def is_universal(r: Regex, alphabet: Set[str]) -> bool:
    """Return True if L(r) equals the set of all strings over the alphabet."""
    return is_empty(_mk_complement(r), alphabet)


def equivalent(r1: Regex, r2: Regex, alphabet: Set[str]) -> bool:
    """Return True if L(r1) = L(r2) over the given alphabet."""
    visited: set = set()
    worklist = [(r1, r2)]
    while worklist:
        s1, s2 = worklist.pop()
        pair = (s1, s2)
        if pair in visited:
            continue
        visited.add(pair)
        if nullable(s1) != nullable(s2):
            return False
        for ch in sorted(alphabet):
            d1 = _derivative(s1, ch)
            d2 = _derivative(s2, ch)
            if (d1, d2) not in visited:
                worklist.append((d1, d2))
    return True


def parse(s: str) -> Regex:
    """Parse a regex string into an AST."""
    pos = [0]

    def peek():
        return s[pos[0]] if pos[0] < len(s) else None

    def advance():
        ch = s[pos[0]]
        pos[0] += 1
        return ch

    def parse_union():
        left = parse_inter()
        while peek() == '|':
            advance()
            right = parse_inter()
            left = Alt(left, right)
        return left

    def parse_inter():
        left = parse_concat()
        while peek() == '&':
            advance()
            right = parse_concat()
            left = Intersection(left, right)
        return left

    def parse_concat():
        factors = []
        while peek() is not None and peek() not in ('|', '&', ')'):
            factors.append(parse_unary())
        if not factors:
            return Epsilon()
        result = factors[0]
        for f in factors[1:]:
            result = Seq(result, f)
        return result

    def parse_unary():
        if peek() == '~':
            advance()
            return Complement(parse_unary())
        return parse_postfix()

    def parse_postfix():
        node = parse_primary()
        while peek() == '*':
            advance()
            node = Star(node)
        return node

    def parse_primary():
        ch = peek()
        if ch == '(':
            advance()
            expr = parse_union()
            if peek() == ')':
                advance()
            return expr
        elif ch == '@':
            advance()
            return Epsilon()
        elif ch == '#':
            advance()
            return Empty()
        elif ch is not None and ch.islower():
            advance()
            return Char(ch)
        else:
            raise ValueError(f"Unexpected character at position {pos[0]}: {ch!r}")

    result = parse_union()
    if pos[0] != len(s):
        raise ValueError(f"Unexpected character at position {pos[0]}: {s[pos[0]]!r}")
    return result


def _expr_str(r: Regex) -> str:
    """Convert a regex expression to a string for DOT labels."""
    if isinstance(r, Empty):
        return '#'
    if isinstance(r, Epsilon):
        return '@'
    if isinstance(r, Char):
        return r.c
    if isinstance(r, Alt):
        return f'({_expr_str(r.left)}|{_expr_str(r.right)})'
    if isinstance(r, Seq):
        return f'{_expr_str(r.left)}{_expr_str(r.right)}'
    if isinstance(r, Star):
        inner = _expr_str(r.expr)
        if len(inner) > 1:
            return f'({inner})*'
        return f'{inner}*'
    if isinstance(r, Complement):
        inner = _expr_str(r.expr)
        if len(inner) > 1:
            return f'~({inner})'
        return f'~{inner}'
    if isinstance(r, Intersection):
        return f'({_expr_str(r.left)}&{_expr_str(r.right)})'
    return '?'


def _explore_dfa(r: Regex, alphabet: Set[str]):
    """Explore the DFA via Brzozowski derivatives. Returns (states, state_map, transitions)."""
    states = []
    state_map = {}
    transitions = {}

    def get_id(expr):
        if expr not in state_map:
            idx = len(states)
            state_map[expr] = idx
            states.append(expr)
        return state_map[expr]

    get_id(r)
    i = 0
    while i < len(states):
        current = states[i]
        for ch in sorted(alphabet):
            d = _derivative(current, ch)
            did = get_id(d)
            transitions[(i, ch)] = did
        i += 1

    return states, state_map, transitions


def to_dot(r: Regex, alphabet: Set[str]) -> str:
    """Return a Graphviz DOT string representing the finite state graph."""
    states, state_map, transitions = _explore_dfa(r, alphabet)

    lines = ['digraph {', '  rankdir=LR;']
    lines.append('  __start [shape=none, label=""];')
    lines.append(f'  __start -> s0;')

    for idx, expr in enumerate(states):
        sid = f's{idx}'
        shape = 'doublecircle' if nullable(expr) else 'circle'
        label = _expr_str(expr).replace('\\', '\\\\').replace('"', '\\"')
        lines.append(f'  {sid} [shape={shape}, label="{label}"];')

    for (src_idx, ch), dst_idx in sorted(transitions.items()):
        lines.append(f'  s{src_idx} -> s{dst_idx} [label="{ch}"];')

    lines.append('}')
    return '\n'.join(lines)


def compile_to_c(r: Regex, alphabet: Set[str]) -> str:
    """Generate C source code implementing the DFA as a state machine."""
    states, state_map, transitions = _explore_dfa(r, alphabet)
    sorted_alpha = sorted(alphabet)

    lines = []
    lines.append('#include <stdio.h>')
    lines.append('#include <string.h>')
    lines.append('')
    lines.append('int main(void) {')
    lines.append('    char line[65536];')
    lines.append('    while (fgets(line, sizeof(line), stdin)) {')
    lines.append('        size_t len = strlen(line);')
    lines.append("        if (len > 0 && line[len-1] == '\\n') line[--len] = '\\0';")
    lines.append('        int state = 0;')
    lines.append('        int dead = 0;')
    lines.append('        for (size_t i = 0; i < len && !dead; i++) {')
    lines.append('            switch (state) {')

    for sid in range(len(states)):
        lines.append(f'                case {sid}:')
        lines.append('                    switch (line[i]) {')
        for ch in sorted_alpha:
            target = transitions[(sid, ch)]
            lines.append(f"                        case '{ch}': state = {target}; break;")
        lines.append('                        default: dead = 1; break;')
        lines.append('                    }')
        lines.append('                    break;')

    lines.append('            }')
    lines.append('        }')
    lines.append('        int acc = 0;')
    lines.append('        if (!dead) {')
    lines.append('            switch (state) {')

    for sid in range(len(states)):
        acc = 1 if nullable(states[sid]) else 0
        lines.append(f'                case {sid}: acc = {acc}; break;')

    lines.append('            }')
    lines.append('        }')
    lines.append('        printf("%s\\n", acc ? "accept" : "reject");')
    lines.append('    }')
    lines.append('    return 0;')
    lines.append('}')

    return '\n'.join(lines)


def generate_flex_spec(r: Regex, alphabet: Set[str]) -> str:
    """Generate a flex (.l) specification file encoding the DFA."""
    states, state_map, transitions = _explore_dfa(r, alphabet)
    sorted_alpha = sorted(alphabet)

    lines = []

    # Header section
    lines.append('%{')
    lines.append('#include <stdio.h>')
    lines.append('int accepting;')
    lines.append('%}')
    lines.append('')
    lines.append('%option noyywrap')
    lines.append('')

    # Declare exclusive states for all DFA states except state 0 (INITIAL), plus DEAD
    extra_states = []
    for sid in range(1, len(states)):
        extra_states.append(f'S{sid}')
    extra_states.append('DEAD')
    lines.append(f'%x {" ".join(extra_states)}')
    lines.append('')

    # Rules section
    lines.append('%%')
    lines.append('')

    for sid in range(len(states)):
        sname = 'INITIAL' if sid == 0 else f'S{sid}'
        for ch in sorted_alpha:
            target = transitions[(sid, ch)]
            tname = 'INITIAL' if target == 0 else f'S{target}'
            acc = 1 if nullable(states[target]) else 0
            lines.append(f'<{sname}>{ch}  {{ accepting = {acc}; BEGIN({tname}); }}')
        # Catch-all for characters outside the alphabet
        lines.append(f'<{sname}>.|\\n  {{ accepting = 0; BEGIN(DEAD); }}')
        lines.append('')

    # Dead state absorbs everything
    lines.append('<DEAD>.|\\n  { }')
    lines.append('')

    # EOF handler
    lines.append('<<EOF>>  { printf("%s\\n", accepting ? "accept" : "reject"); return 0; }')
    lines.append('')

    # Code section
    lines.append('%%')
    lines.append('')
    acc_initial = 1 if nullable(r) else 0
    lines.append('int main(void) {')
    lines.append(f'    accepting = {acc_initial};')
    lines.append('    yylex();')
    lines.append('    return 0;')
    lines.append('}')

    return '\n'.join(lines)
