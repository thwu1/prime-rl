
"""GDL/KIF to SWI-Prolog transpiler.

Converts Game Description Language files in KIF (Knowledge Interchange Format)
into executable SWI-Prolog programs, mapping GDL semantics to Prolog equivalents.
"""


def tokenize(text):
    """Tokenize KIF S-expression text, stripping comments."""
    tokens = []
    i, n = 0, len(text)
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


def parse_sexps(tokens):
    """Parse flat token list into nested Python lists (S-expressions)."""
    result = []
    i, n = 0, len(tokens)
    while i < n:
        if tokens[i] == '(':
            expr, i = _parse_list(tokens, i + 1)
            result.append(expr)
        else:
            result.append(tokens[i])
            i += 1
    return result


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


def _is_var(s):
    return isinstance(s, str) and s.startswith('?')


def _var_to_prolog(v):
    """Convert GDL variable ?name to Prolog variable Name."""
    name = v[1:]
    return name[0].upper() + name[1:]


def _atom_to_prolog(s):
    """Convert a GDL constant to a valid Prolog atom."""
    if not s:
        return "''"
    try:
        int(s)
        return s
    except ValueError:
        pass
    if s[0].islower() and all(c.isalnum() or c == '_' for c in s):
        return s
    return "'" + s + "'"


def _expr_to_prolog(expr):
    """Convert a parsed GDL S-expression to Prolog syntax string."""
    if isinstance(expr, str):
        if _is_var(expr):
            return _var_to_prolog(expr)
        return _atom_to_prolog(expr)

    if not isinstance(expr, list) or len(expr) == 0:
        return ''

    head = expr[0]

    if head == 'true':
        return 'true_fact(' + _expr_to_prolog(expr[1]) + ')'
    if head == 'does':
        return 'does_fact(' + _expr_to_prolog(expr[1]) + ', ' + _expr_to_prolog(expr[2]) + ')'
    if head == 'not':
        return '\\+ (' + _expr_to_prolog(expr[1]) + ')'
    if head == 'or':
        parts = [_expr_to_prolog(e) for e in expr[1:]]
        return '(' + ' ; '.join(parts) + ')'
    if head == 'distinct':
        return _expr_to_prolog(expr[1]) + ' \\= ' + _expr_to_prolog(expr[2])

    func = _atom_to_prolog(head)
    if len(expr) == 1:
        return func
    args = ', '.join(_expr_to_prolog(e) for e in expr[1:])
    return func + '(' + args + ')'


def transpile(kif_path, output_pl_path):
    """Transpile a GDL/KIF file to a SWI-Prolog program.

    The generated Prolog program includes:
    - All game rules and facts translated to Prolog syntax
    - Dynamic predicates true_fact/1 and does_fact/2 for state/move context
    - Helper predicates set_state/1, set_moves/1, clear_context/0
    """
    with open(kif_path) as f:
        text = f.read()

    tokens = tokenize(text)
    exprs = parse_sexps(tokens)

    lines = []
    lines.append('% Auto-generated from GDL/KIF by gdl_transpiler.py')
    lines.append(':- style_check(-discontiguous).')
    lines.append(':- dynamic true_fact/1, does_fact/2.')
    lines.append('')
    lines.append('% Context management helpers')
    lines.append('set_state(State) :-')
    lines.append('    retractall(true_fact(_)),')
    lines.append('    forall(member(F, State), assert(true_fact(F))).')
    lines.append('set_moves(Moves) :-')
    lines.append('    retractall(does_fact(_, _)),')
    lines.append('    forall(member(does(R, M), Moves), assert(does_fact(R, M))).')
    lines.append('clear_context :-')
    lines.append('    retractall(true_fact(_)),')
    lines.append('    retractall(does_fact(_, _)).')
    lines.append('')

    for expr in exprs:
        if isinstance(expr, str):
            continue
        if not isinstance(expr, list) or len(expr) == 0:
            continue

        if expr[0] == '<=':
            head_pl = _expr_to_prolog(expr[1])
            body_parts = [_expr_to_prolog(b) for b in expr[2:]]
            if body_parts:
                body_pl = ',\n    '.join(body_parts)
                lines.append(head_pl + ' :-')
                lines.append('    ' + body_pl + '.')
            else:
                lines.append(head_pl + '.')
        else:
            fact_pl = _expr_to_prolog(expr)
            lines.append(fact_pl + '.')

    with open(output_pl_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
