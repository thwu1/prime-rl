#!/usr/bin/env python3
"""TAC structural validator.

Checks well-formedness of TAC programs:
- Valid syntax on every non-blank, non-comment line
- No duplicate function definitions
- No duplicate labels within a function
- All jump targets reference labels in the same function
- All called functions exist and argument counts match parameter counts
- Every function has at least one return statement
- Variables used are defined somewhere in the enclosing function

Exits 0 (prints OK) if valid, exits 1 with error messages if invalid.
"""

import re
import sys


def _strip_comment(line):
    """Remove trailing comment from a line, respecting parentheses."""
    if '#' not in line:
        return line
    idx = line.index('#')
    depth = 0
    for c in line[:idx]:
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
    if depth == 0:
        return line[:idx].strip()
    return line


def validate(text):
    """Validate a TAC program text. Returns list of error strings (empty = valid)."""
    errors = []
    functions = {}
    lines = text.split('\n')
    i = 0
    current_func = None
    func_info = None

    while i < len(lines):
        line = lines[i].strip()
        lineno = i + 1

        line = _strip_comment(line)
        if not line:
            i += 1
            continue

        # Function header
        fm = re.match(r'function\s+(\w+)\s*\(([^)]*)\)\s*:', line)
        if fm:
            if current_func is not None and func_info is not None:
                functions[current_func] = func_info

            current_func = fm.group(1)
            if current_func in functions:
                errors.append(
                    "line %d: duplicate function '%s'" % (lineno, current_func))

            ps = fm.group(2).strip()
            params = [p.strip() for p in ps.split(',') if p.strip()]

            func_info = {
                'param_count': len(params),
                'labels': set(),
                'jump_targets': [],
                'calls': [],
                'has_return': False,
                'defined_vars': set(params),
                'used_vars': set(),
            }
            i += 1
            continue

        if current_func is None:
            errors.append(
                "line %d: code outside any function: '%s'" % (lineno, line))
            i += 1
            continue

        # Label
        lm = re.match(r'^(\w+)\s*:\s*$', line)
        if lm:
            label = lm.group(1)
            if label in func_info['labels']:
                errors.append(
                    "line %d: duplicate label '%s' in '%s'"
                    % (lineno, label, current_func))
            func_info['labels'].add(label)
            i += 1
            continue

        # return
        rm = re.match(r'return\s+(\S+)$', line)
        if rm:
            func_info['has_return'] = True
            val = rm.group(1)
            if not re.match(r'^-?\d+$', val):
                func_info['used_vars'].add(val)
            i += 1
            continue

        # jump
        jm = re.match(r'jump\s+(\w+)$', line)
        if jm:
            func_info['jump_targets'].append((jm.group(1), lineno))
            i += 1
            continue

        # jz / jnz
        jcm = re.match(r'(jz|jnz)\s+(\S+)\s+(\w+)$', line)
        if jcm:
            cond = jcm.group(2)
            if not re.match(r'^-?\d+$', cond):
                func_info['used_vars'].add(cond)
            func_info['jump_targets'].append((jcm.group(3), lineno))
            i += 1
            continue

        # Assignment
        am = re.match(r'(\w+)\s*=\s*(.+)', line)
        if am:
            dest = am.group(1)
            rhs = am.group(2).strip()
            func_info['defined_vars'].add(dest)

            # call
            cm = re.match(r'call\s+(\w+)\s*\(([^)]*)\)$', rhs)
            if cm:
                callee = cm.group(1)
                args_str = cm.group(2).strip()
                args = ([a.strip() for a in args_str.split(',') if a.strip()]
                        if args_str else [])
                func_info['calls'].append((callee, len(args), lineno))
                for a in args:
                    if not re.match(r'^-?\d+$', a):
                        func_info['used_vars'].add(a)
                i += 1
                continue

            # binop
            bm = re.match(
                r'(add|sub|mul|div|mod|eq|ne|lt|le|gt|ge|'
                r'band|bor|bxor|shl|shr|and|or)\s+(\S+)\s+(\S+)$', rhs)
            if bm:
                for a in [bm.group(2), bm.group(3)]:
                    if not re.match(r'^-?\d+$', a):
                        func_info['used_vars'].add(a)
                i += 1
                continue

            # unop
            um = re.match(r'(neg|not|bnot)\s+(\S+)$', rhs)
            if um:
                a = um.group(2)
                if not re.match(r'^-?\d+$', a):
                    func_info['used_vars'].add(a)
                i += 1
                continue

            # copy
            cpm = re.match(r'copy\s+(\S+)$', rhs)
            if cpm:
                a = cpm.group(1)
                if not re.match(r'^-?\d+$', a):
                    func_info['used_vars'].add(a)
                i += 1
                continue

            # constant assignment
            if re.match(r'^-?\d+$', rhs):
                i += 1
                continue

            errors.append(
                "line %d: invalid RHS in assignment: '%s'" % (lineno, rhs))
            i += 1
            continue

        errors.append(
            "line %d: unrecognized syntax: '%s'" % (lineno, line))
        i += 1

    # Save last function
    if current_func is not None and func_info is not None:
        functions[current_func] = func_info

    if not functions:
        errors.append("no functions defined")
        return errors

    # Cross-reference checks
    for fname, fdata in functions.items():
        # Jump target validity
        for target, lineno in fdata['jump_targets']:
            if target not in fdata['labels']:
                errors.append(
                    "line %d: jump to undefined label '%s' in '%s'"
                    % (lineno, target, fname))

        # Function call validity
        for callee, argc, lineno in fdata['calls']:
            if callee not in functions:
                errors.append(
                    "line %d: call to undefined function '%s'" % (lineno, callee))
            else:
                expected = functions[callee]['param_count']
                if expected != argc:
                    errors.append(
                        "line %d: '%s' expects %d arg(s), got %d"
                        % (lineno, callee, expected, argc))

        # Return presence
        if not fdata['has_return']:
            errors.append("function '%s' has no return statement" % fname)

        # Undefined variables
        undefined = fdata['used_vars'] - fdata['defined_vars']
        for v in sorted(undefined):
            errors.append(
                "function '%s': variable '%s' used but never defined"
                % (fname, v))

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tac_check.py <file.tac>", file=sys.stderr)
        sys.exit(1)

    try:
        with open(sys.argv[1], 'r') as f:
            text = f.read()
    except FileNotFoundError:
        print("ERROR: file not found: %s" % sys.argv[1], file=sys.stderr)
        sys.exit(1)

    errors = validate(text)
    if errors:
        for e in errors:
            print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
    else:
        print("OK")
        sys.exit(0)


if __name__ == '__main__':
    main()
