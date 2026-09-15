#!/usr/bin/env python3
"""Reference interpreter for the Three-Address Code IR.

Usage: python3 interpreter.py <file.ir>

Reads an IR program, executes main(), and prints all PRINT output to stdout.
"""

import sys
import re


def parse_operand(token, env):
    """Evaluate an operand: integer literal or variable lookup."""
    token = token.strip()
    try:
        return int(token)
    except ValueError:
        return env.get(token, 0)


def parse_program(source):
    """Parse IR source text into a dict mapping function names to definitions."""
    functions = {}
    current_func = None

    for line in source.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Function header
        m = re.match(r'FUNC\s+(\w+)\s*\(([^)]*)\)\s*:', line)
        if m:
            fname = m.group(1)
            params = [p.strip() for p in m.group(2).split(',') if p.strip()]
            current_func = {
                'name': fname,
                'params': params,
                'instructions': [],
                'label_index': {}
            }
            functions[fname] = current_func
            continue

        if line == 'ENDFUNC':
            current_func = None
            continue

        # Label declaration
        m = re.match(r'LABEL\s+(\w+)\s*:', line)
        if m:
            if current_func is not None:
                label = m.group(1)
                current_func['label_index'][label] = len(current_func['instructions'])
            continue

        # Any other line is an instruction
        if current_func is not None:
            current_func['instructions'].append(line)

    return functions


def eval_binop(left, op, right):
    """Evaluate a binary operation on two integers."""
    if op == '+':
        return left + right
    elif op == '-':
        return left - right
    elif op == '*':
        return left * right
    elif op == '/':
        if right == 0:
            return 0
        # Truncation toward zero (C semantics)
        result = abs(left) // abs(right)
        if (left < 0) != (right < 0):
            result = -result
        return result
    elif op == '%':
        if right == 0:
            return 0
        # C semantics: result has sign of dividend
        result = abs(left) % abs(right)
        if left < 0:
            result = -result
        return result
    elif op == '==':
        return 1 if left == right else 0
    elif op == '!=':
        return 1 if left != right else 0
    elif op == '<':
        return 1 if left < right else 0
    elif op == '>':
        return 1 if left > right else 0
    elif op == '<=':
        return 1 if left <= right else 0
    elif op == '>=':
        return 1 if left >= right else 0
    return 0


# Regex patterns for instruction matching (compiled once)
RE_RETURN = re.compile(r'RETURN\s+(.+)')
RE_PRINT = re.compile(r'PRINT\s+(.+)')
RE_IF_GOTO = re.compile(r'IF\s+(.+?)\s+GOTO\s+(\w+)')
RE_GOTO = re.compile(r'GOTO\s+(\w+)')
RE_CALL = re.compile(r'(\w+)\s*=\s*CALL\s+(\w+)\s*\(([^)]*)\)')
RE_BINOP = re.compile(r'(\w+)\s*=\s*(.+?)\s+(==|!=|<=|>=|<|>|[+\-*/%])\s+(.+)')
RE_ASSIGN = re.compile(r'(\w+)\s*=\s*(.+)')


def execute_function(functions, fname, args, output):
    """Execute a function and return its return value."""
    func = functions[fname]
    env = {}

    # Bind parameters
    for idx, param in enumerate(func['params']):
        env[param] = args[idx] if idx < len(args) else 0

    pc = 0
    instructions = func['instructions']

    while pc < len(instructions):
        inst = instructions[pc]
        pc += 1

        # RETURN
        m = RE_RETURN.match(inst)
        if m:
            return parse_operand(m.group(1), env)

        # PRINT
        m = RE_PRINT.match(inst)
        if m:
            val = parse_operand(m.group(1), env)
            output.append(str(val))
            continue

        # IF ... GOTO
        m = RE_IF_GOTO.match(inst)
        if m:
            cond = parse_operand(m.group(1), env)
            if cond != 0:
                pc = func['label_index'][m.group(2)]
            continue

        # GOTO
        m = RE_GOTO.match(inst)
        if m:
            pc = func['label_index'][m.group(1)]
            continue

        # x = CALL f(args)
        m = RE_CALL.match(inst)
        if m:
            dest = m.group(1)
            callee = m.group(2)
            arg_tokens = [a.strip() for a in m.group(3).split(',') if a.strip()]
            arg_vals = [parse_operand(t, env) for t in arg_tokens]
            result = execute_function(functions, callee, arg_vals, output)
            env[dest] = result
            continue

        # x = y op z  (binary operation)
        m = RE_BINOP.match(inst)
        if m:
            dest = m.group(1)
            left = parse_operand(m.group(2), env)
            op = m.group(3)
            right = parse_operand(m.group(4), env)
            env[dest] = eval_binop(left, op, right)
            continue

        # x = operand  (simple assignment / copy / constant load)
        m = RE_ASSIGN.match(inst)
        if m:
            dest = m.group(1)
            env[dest] = parse_operand(m.group(2), env)
            continue

    # Implicit return 0 if no RETURN encountered
    return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: interpreter.py <file.ir>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        source = f.read()

    functions = parse_program(source)
    if 'main' not in functions:
        print("Error: no main() function found", file=sys.stderr)
        sys.exit(1)

    output = []
    execute_function(functions, 'main', [], output)

    for line in output:
        print(line)


if __name__ == '__main__':
    main()
