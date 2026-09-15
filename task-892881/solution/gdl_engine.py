#!/usr/bin/env python3
"""
GDL State Machine Engine - SWI-Prolog backend.

Translates KIF game descriptions to Prolog, invokes swipl for
backward-chaining inference, and presents results as JSON.

"""
import sys
import json
import subprocess
import tempfile
import os


# ============================================================
# KIF S-Expression Parser
# ============================================================

def tokenize(text):
    """Tokenize KIF/GDL text, stripping ; comments."""
    toks = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == ';':
            while i < n and text[i] != '\n':
                i += 1
        elif c in ' \t\n\r':
            i += 1
        elif c in '()':
            toks.append(c)
            i += 1
        else:
            j = i
            while j < n and text[j] not in ' \t\n\r();':
                j += 1
            toks.append(text[i:j])
            i = j
    return toks


def parse_toks(toks, p):
    """Parse one s-expression from token list at position p."""
    if toks[p] == '(':
        items = []
        p += 1
        while toks[p] != ')':
            item, p = parse_toks(toks, p)
            items.append(item)
        return items, p + 1
    return toks[p], p + 1


def parse_all(text):
    """Parse all top-level s-expressions from KIF text."""
    toks = tokenize(text)
    exprs = []
    p = 0
    while p < len(toks):
        expr, p = parse_toks(toks, p)
        exprs.append(expr)
    return exprs


# ============================================================
# KIF to Prolog Translation
# ============================================================

# GDL keywords that appear as clause heads - prefixed with gdl_
GDL_HEAD_KW = {'role', 'init', 'legal', 'next', 'terminal', 'goal', 'base', 'input'}


def pl_atom(name):
    """Convert a KIF atom/variable name to Prolog syntax."""
    if name.startswith('?'):
        return 'V' + name[1:]
    try:
        int(name)
        return name
    except ValueError:
        pass
    if name and name[0].islower() and all(c.isalnum() or c == '_' for c in name):
        return name
    return "'{}'".format(name)


def tr_term(expr):
    """Translate a KIF expression to a Prolog data term (no predicate prefixing)."""
    if isinstance(expr, str):
        return pl_atom(expr)
    if isinstance(expr, list):
        if len(expr) == 1:
            return tr_term(expr[0])
        functor = pl_atom(expr[0])
        args = ', '.join(tr_term(a) for a in expr[1:])
        return '{}({})'.format(functor, args)
    raise ValueError('Unexpected: {}'.format(expr))


def tr_head(expr):
    """Translate a KIF expression to a Prolog clause head."""
    if isinstance(expr, str):
        if expr in GDL_HEAD_KW:
            return 'gdl_{}'.format(expr)
        return 'g_{}'.format(expr)
    if isinstance(expr, list):
        f = expr[0]
        prefix = 'gdl_' if f in GDL_HEAD_KW else 'g_'
        args = ', '.join(tr_term(a) for a in expr[1:])
        return '{}{}({})'.format(prefix, f, args)
    raise ValueError('Unexpected head: {}'.format(expr))


def tr_body(expr):
    """Translate a KIF body goal to a Prolog goal expression."""
    if isinstance(expr, str):
        if expr.startswith('?'):
            return pl_atom(expr)
        if expr in GDL_HEAD_KW:
            return 'gdl_{}'.format(expr)
        return 'g_{}'.format(expr)
    if isinstance(expr, list):
        f = expr[0]
        if f == 'not':
            inner = tr_body(expr[1])
            return '\\+ ({})'.format(inner)
        if f == 'or':
            parts = [tr_body(a) for a in expr[1:]]
            return '(' + ' ; '.join(parts) + ')'
        if f == 'distinct':
            a = tr_term(expr[1])
            b = tr_term(expr[2])
            return '{} \\= {}'.format(a, b)
        if f == 'true':
            inner = tr_term(expr[1])
            return 'gdl_true({})'.format(inner)
        if f == 'does':
            role = tr_term(expr[1])
            move = tr_term(expr[2])
            return 'gdl_does({}, {})'.format(role, move)
        prefix = 'gdl_' if f in GDL_HEAD_KW else 'g_'
        args = ', '.join(tr_term(a) for a in expr[1:])
        return '{}{}({})'.format(prefix, f, args)
    raise ValueError('Unexpected body: {}'.format(expr))


def kif_to_prolog(kif_text):
    """Translate a complete KIF game file to Prolog source code."""
    exprs = parse_all(kif_text)
    lines = [
        ':- style_check(-discontiguous).',
        ':- style_check(-singleton).',
    ]
    for ex in exprs:
        if isinstance(ex, list) and len(ex) >= 2 and ex[0] == '<=':
            head = tr_head(ex[1])
            body = ', '.join(tr_body(b) for b in ex[2:])
            lines.append('{} :- {}.'.format(head, body))
        else:
            lines.append('{}.'.format(tr_head(ex)))
    return '\n'.join(lines)


# ============================================================
# State / Move Marshalling (JSON <-> Prolog)
# ============================================================

def kif_str_to_pl(s):
    """Convert a KIF s-expression string to a Prolog term string."""
    toks = tokenize(s.strip())
    expr, _ = parse_toks(toks, 0)
    return tr_term(expr)


def state_to_pl(state_json):
    """Convert JSON state array to Prolog list string."""
    terms = [kif_str_to_pl(s) for s in state_json]
    return '[' + ', '.join(terms) + ']'


def moves_to_pl(moves_json):
    """Convert JSON moves dict to Prolog list of Role-Move pairs."""
    pairs = []
    for role, move in moves_json.items():
        pairs.append('{}-{}'.format(pl_atom(role), kif_str_to_pl(move)))
    return '[' + ', '.join(pairs) + ']'


# ============================================================
# SWI-Prolog Invocation
# ============================================================

PROVER_PL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gdl_prover.pl')


def run_swipl(combined_pl_path, goal):
    """Invoke swipl with the combined prover+game file, executing goal."""
    cmd = [
        'swipl',
        '-l', combined_pl_path,
        '-g', goal,
        '-t', 'halt',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print('swipl error:\n{}'.format(result.stderr), file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


# ============================================================
# CLI
# ============================================================

def get_flag(name):
    """Extract value following a --flag from sys.argv."""
    for i in range(3, len(sys.argv) - 1):
        if sys.argv[i] == name:
            return sys.argv[i + 1]
    return None


def parse_lines(output):
    """Split swipl output into non-empty lines."""
    if not output:
        return []
    return [ln for ln in output.split('\n') if ln.strip()]


def main():
    if len(sys.argv) < 3:
        print('Usage: gdl_engine.py <game.kif> <command> [args]', file=sys.stderr)
        sys.exit(1)

    game_file = sys.argv[1]
    command = sys.argv[2]

    with open(game_file) as f:
        kif_text = f.read()
    game_prolog = kif_to_prolog(kif_text)

    with open(PROVER_PL) as f:
        prover_code = f.read()

    # Combine prover helpers and translated game into a single file
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.pl', delete=False)
    tmp.write(prover_code)
    tmp.write('\n')
    tmp.write(game_prolog)
    tmp.close()

    try:
        if command == 'roles':
            out = run_swipl(tmp.name, 'do_roles')
            print(json.dumps(sorted(parse_lines(out))))

        elif command == 'initial':
            out = run_swipl(tmp.name, 'do_initial')
            print(json.dumps(sorted(parse_lines(out))))

        elif command in ('legal', 'next', 'terminal', 'goal'):
            state_file = get_flag('--state')
            with open(state_file) as f:
                state_json = json.load(f)
            pl_state = state_to_pl(state_json)
            setup = 'clear_ctx, forall(member(X,{}), assert(gdl_true(X)))'.format(pl_state)

            if command == 'legal':
                role = get_flag('--role')
                goal = '{}, do_legal({})'.format(setup, pl_atom(role))
                out = run_swipl(tmp.name, goal)
                print(json.dumps(sorted(parse_lines(out))))

            elif command == 'next':
                moves_file = get_flag('--moves')
                with open(moves_file) as f:
                    moves_json = json.load(f)
                pl_moves = moves_to_pl(moves_json)
                goal = '{}, forall(member(R-M,{}), assert(gdl_does(R,M))), do_next'.format(
                    setup, pl_moves)
                out = run_swipl(tmp.name, goal)
                print(json.dumps(sorted(parse_lines(out))))

            elif command == 'terminal':
                goal = '{}, do_terminal'.format(setup)
                out = run_swipl(tmp.name, goal)
                print(out)

            elif command == 'goal':
                role = get_flag('--role')
                goal = '{}, do_goal({})'.format(setup, pl_atom(role))
                out = run_swipl(tmp.name, goal)
                print(out)

        else:
            print('Unknown command: {}'.format(command), file=sys.stderr)
            sys.exit(1)

    finally:
        os.unlink(tmp.name)


if __name__ == '__main__':
    main()
