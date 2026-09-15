#!/usr/bin/env python3
"""Translates GDL/KIF game descriptions into SWI-Prolog programs."""

import os
import re


def tokenize(text):
    text = re.sub(r';[^\n]*', '', text)
    text = text.replace('(', ' ( ').replace(')', ' ) ')
    return text.split()


def parse_sexps(text):
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


def _atom_to_prolog(name):
    """Convert a GDL atom to a valid Prolog atom, quoting if necessary."""
    if re.match(r'^\d+$', name):
        return name
    if re.match(r'^[a-z][a-zA-Z0-9_]*$', name):
        return name
    return "'" + name.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _var_to_prolog(name):
    """Convert a GDL variable (?name) to a Prolog variable (capitalized)."""
    raw = name[1:]
    return raw[0].upper() + raw[1:]


def term_to_prolog(term):
    """Convert a GDL term/literal to Prolog syntax."""
    if isinstance(term, str):
        if term.startswith('?'):
            return _var_to_prolog(term)
        return _atom_to_prolog(term)

    if not isinstance(term, tuple) or len(term) == 0:
        return str(term)

    head = term[0]

    # Special forms
    if head == 'not':
        inner = term_to_prolog(term[1])
        return '\\+(' + inner + ')'

    if head == 'distinct':
        return term_to_prolog(term[1]) + ' \\= ' + term_to_prolog(term[2])

    if head == 'or':
        parts = [term_to_prolog(t) for t in term[1:]]
        return '(' + ' ; '.join(parts) + ')'

    # Regular compound: (pred arg1 arg2) -> pred(arg1, arg2)
    pred = _atom_to_prolog(head) if isinstance(head, str) else term_to_prolog(head)
    if len(term) == 1:
        return pred
    args = ', '.join(term_to_prolog(a) for a in term[1:])
    return pred + '(' + args + ')'


def _get_pred_sig(term):
    """Extract (prolog_pred_name, arity) from a clause head term."""
    if isinstance(term, str):
        return (_atom_to_prolog(term), 0)
    if isinstance(term, tuple) and len(term) >= 1:
        return (_atom_to_prolog(term[0]), len(term) - 1)
    return None


def compile_to_prolog(kif_path, output_path):
    """Translate a GDL/KIF game file to a SWI-Prolog program.

    The generated .pl file can be loaded by swipl. State predicates true/1
    and does/2 are declared dynamic so they can be asserted for queries.
    """
    with open(kif_path) as f:
        text = f.read()

    exprs = parse_sexps(text)
    pred_sigs = set()
    clauses = []

    for expr in exprs:
        if isinstance(expr, tuple) and len(expr) >= 3 and expr[0] == '<=':
            head = expr[1]
            body = list(expr[2:])
            head_pl = term_to_prolog(head)
            body_pl = ', '.join(term_to_prolog(b) for b in body)
            clauses.append(head_pl + ' :-\n    ' + body_pl + '.')
            sig = _get_pred_sig(head)
            if sig:
                pred_sigs.add(sig)
        elif isinstance(expr, tuple):
            clauses.append(term_to_prolog(expr) + '.')
            sig = _get_pred_sig(expr)
            if sig:
                pred_sigs.add(sig)
        elif isinstance(expr, str):
            clauses.append(_atom_to_prolog(expr) + '.')
            pred_sigs.add((_atom_to_prolog(expr), 0))

    lines = ['% Auto-generated SWI-Prolog program from GDL/KIF']
    lines.append(':- dynamic true/1, does/2.')

    # Declare all head predicates as discontiguous (safe even if contiguous)
    discontig = sorted(
        f'{name}/{arity}' for name, arity in pred_sigs
        if name not in ('true', 'does')
    )
    if discontig:
        lines.append(':- discontiguous ' + ', '.join(discontig) + '.')

    lines.append('')
    lines.extend(clauses)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    return output_path
