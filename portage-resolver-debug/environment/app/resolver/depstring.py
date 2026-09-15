"""
Dependency string parser and evaluator for Gentoo-style expressions.

Supported syntax:
  atom                    - unconditional dependency
  flag? ( group )         - include group when USE flag is enabled
  !flag? ( group )        - include group when USE flag is disabled
  || ( dep1 dep2 ... )    - any-of: pick first satisfiable option
"""

from .atom import Atom


def tokenize(depstring: str) -> list:
    """Tokenize a dependency string into a flat list of string tokens."""
    tokens = []
    buf = []
    for ch in depstring:
        if ch in '()':
            if buf:
                tokens.append(''.join(buf).strip())
                buf = []
            tokens.append(ch)
        elif ch.isspace():
            if buf:
                tokens.append(''.join(buf).strip())
                buf = []
        else:
            buf.append(ch)
    if buf:
        tokens.append(''.join(buf).strip())
    return [t for t in tokens if t]


def evaluate(depstring: str, active_use_flags: set) -> list:
    """
    Evaluate a dependency string against a set of active USE flags.

    Returns a list of :class:`Atom` objects for the dependencies that
    should be pulled in given the current flag configuration.
    """
    if not depstring or not depstring.strip():
        return []
    tokens = tokenize(depstring)
    result, _ = _eval_tokens(tokens, 0, active_use_flags)
    return result


def _eval_tokens(tokens, pos, active_flags):
    """Recursively evaluate a token stream starting at *pos*.

    Returns ``(list_of_atoms, next_position)``.
    """
    result = []
    negate = False

    while pos < len(tokens):
        tok = tokens[pos]

        # End of current group
        if tok == ')':
            return result, pos + 1

        # any-of group:  || ( dep1 dep2 ... )
        if tok == '||':
            pos += 1
            if pos < len(tokens) and tokens[pos] == '(':
                pos += 1
                group, pos = _eval_tokens(tokens, pos, active_flags)
                if group:
                    result.append(group[0])  # pick first option
            continue

        # USE-conditional:  flag? ( ... )  or  !flag? ( ... )
        if tok.endswith('?'):
            is_negated = tok.startswith('!')
            flag_name = tok.lstrip('!').rstrip('?')

            pos += 1
            if pos < len(tokens) and tokens[pos] == '(':
                pos += 1

                flag_active = flag_name in active_flags

                if is_negated:
                    negate = True

                should_include = flag_active
                if negate:
                    should_include = not should_include

                if should_include:
                    group, pos = _eval_tokens(tokens, pos, active_flags)
                    result.extend(group)
                else:
                    pos = _skip_group(tokens, pos)

                continue
            continue

        # Plain parenthesized group
        if tok == '(':
            pos += 1
            group, pos = _eval_tokens(tokens, pos, active_flags)
            result.extend(group)
            continue

        # Regular dependency atom
        try:
            result.append(Atom(tok))
        except ValueError:
            pass  # skip unparseable tokens
        pos += 1

    return result, pos


def _skip_group(tokens, pos):
    """Advance *pos* past a balanced ``(...)`` group without evaluating."""
    depth = 1
    while pos < len(tokens) and depth > 0:
        if tokens[pos] == '(':
            depth += 1
        elif tokens[pos] == ')':
            depth -= 1
        pos += 1
    return pos
