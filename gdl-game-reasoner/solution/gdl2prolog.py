#!/usr/bin/env python3
"""GDL-to-Prolog Compiler: translates .kif game descriptions to SWI-Prolog programs."""

import sys


def _tokenize(text):
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
    if tokens[pos] == '(':
        pos += 1
        items = []
        while tokens[pos] != ')':
            item, pos = _parse_one(tokens, pos)
            items.append(item)
        return tuple(items), pos + 1
    return tokens[pos], pos + 1


def _parse_all(text):
    tokens = _tokenize(text)
    exprs = []
    pos = 0
    while pos < len(tokens):
        expr, pos = _parse_one(tokens, pos)
        exprs.append(expr)
    return exprs


def _is_var(t):
    return isinstance(t, str) and len(t) > 1 and t[0] == '?'


def _var_to_prolog(v):
    name = v[1:]
    return name[0].upper() + name[1:]


def _term_to_prolog(t):
    """Convert a GDL term to Prolog syntax string."""
    if isinstance(t, str):
        if _is_var(t):
            return _var_to_prolog(t)
        try:
            int(t)
            return t
        except ValueError:
            return t
    if isinstance(t, tuple):
        if not t:
            return ''
        functor = _term_to_prolog(t[0])
        if len(t) == 1:
            return functor
        args = ', '.join(_term_to_prolog(a) for a in t[1:])
        return f'{functor}({args})'
    return str(t)


def _body_to_prolog(t):
    """Convert a GDL body literal to Prolog syntax."""
    if isinstance(t, str):
        if _is_var(t):
            return _var_to_prolog(t)
        return t
    if isinstance(t, tuple):
        functor = t[0]
        if functor == 'not':
            return f'\\+ ({_body_to_prolog(t[1])})'
        if functor == 'or':
            return '(' + ' ; '.join(_body_to_prolog(d) for d in t[1:]) + ')'
        if functor == 'distinct':
            return f'{_term_to_prolog(t[1])} \\= {_term_to_prolog(t[2])}'
        return _term_to_prolog(t)
    return str(t)


def compile_gdl(text):
    """Compile GDL text to a SWI-Prolog program string."""
    exprs = _parse_all(text)
    lines = [':- dynamic true/1.', ':- dynamic does/2.', '']

    for e in exprs:
        if isinstance(e, tuple) and len(e) >= 2 and e[0] == '<=':
            head = e[1]
            body = list(e[2:])
            head_functor = head[0] if isinstance(head, tuple) else head
            if head_functor in ('base', 'input'):
                continue
            head_str = _term_to_prolog(head) if isinstance(head, tuple) else head
            body_strs = [_body_to_prolog(b) for b in body]
            lines.append(f'{head_str} :- {", ".join(body_strs)}.')
        else:
            if isinstance(e, tuple) and e[0] in ('base', 'input'):
                continue
            fact_str = _term_to_prolog(e) if isinstance(e, tuple) else e
            lines.append(f'{fact_str}.')

    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f'Usage: {sys.argv[0]} <input.kif> <output.pl>', file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        gdl_text = f.read()

    prolog_code = compile_gdl(gdl_text)

    with open(sys.argv[2], 'w') as f:
        f.write(prolog_code)
