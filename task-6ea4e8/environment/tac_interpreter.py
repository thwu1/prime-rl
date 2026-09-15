#!/usr/bin/env python3
"""Three-Address Code (TAC) interpreter."""
import sys
import re


def parse_program(text):
    instructions = []
    labels = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('LABEL '):
            label_name = line[6:].strip()
            labels[label_name] = len(instructions)
            instructions.append(('LABEL', label_name))
        else:
            instructions.append(parse_instruction(line))
    return instructions, labels


def parse_instruction(line):
    if line.startswith('GOTO '):
        return ('GOTO', line[5:].strip())

    m = re.match(r'IF\s+(\S+)\s+(==|!=|<=|>=|<|>)\s+(\S+)\s+GOTO\s+(\S+)', line)
    if m:
        return ('IF', m.group(1), m.group(2), m.group(3), m.group(4))

    if line.startswith('PRINT '):
        return ('PRINT', line[6:].strip())

    m = re.match(r'(\w+)\s*=\s*(.+)', line)
    if m:
        lhs = m.group(1)
        tokens = m.group(2).strip().split()
        if len(tokens) == 1:
            return ('ASSIGN', lhs, tokens[0])
        elif len(tokens) == 2:
            return ('UNARY', lhs, tokens[0], tokens[1])
        elif len(tokens) == 3:
            return ('BINOP', lhs, tokens[0], tokens[1], tokens[2])
        else:
            raise ValueError(f"Cannot parse: {line}")

    raise ValueError(f"Cannot parse: {line}")


def resolve(val, env):
    """Resolve a value - either a variable or an integer constant."""
    try:
        return int(val)
    except ValueError:
        if val not in env:
            raise RuntimeError(f"Undefined variable: {val}")
        return env[val]


def execute(instructions, labels):
    env = {}
    pc = 0
    outputs = []
    max_steps = 10_000_000
    steps = 0

    while pc < len(instructions):
        steps += 1
        if steps > max_steps:
            raise RuntimeError("Execution limit exceeded")

        inst = instructions[pc]
        op = inst[0]

        if op == 'LABEL':
            pc += 1
        elif op == 'GOTO':
            pc = labels[inst[1]]
        elif op == 'IF':
            _, lhs, relop, rhs, target = inst
            l = resolve(lhs, env)
            r = resolve(rhs, env)
            cond = {
                '==': l == r, '!=': l != r,
                '<': l < r, '>': l > r,
                '<=': l <= r, '>=': l >= r,
            }[relop]
            if cond:
                pc = labels[target]
            else:
                pc += 1
        elif op == 'PRINT':
            val = resolve(inst[1], env)
            outputs.append(str(val))
            pc += 1
        elif op == 'ASSIGN':
            _, lhs, rhs = inst
            env[lhs] = resolve(rhs, env)
            pc += 1
        elif op == 'UNARY':
            _, lhs, uop, operand = inst
            val = resolve(operand, env)
            if uop == 'NEG':
                env[lhs] = -val
            else:
                raise RuntimeError(f"Unknown unary op: {uop}")
            pc += 1
        elif op == 'BINOP':
            _, lhs, a, bop, b = inst
            va = resolve(a, env)
            vb = resolve(b, env)
            result = {
                '+': va + vb, '-': va - vb,
                '*': va * vb,
                '/': va // vb if vb != 0 else 0,
                '%': va % vb if vb != 0 else 0,
            }[bop]
            env[lhs] = result
            pc += 1
        else:
            raise RuntimeError(f"Unknown instruction: {inst}")

    return outputs


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tac_interpreter.py <program.tac>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        text = f.read()

    instructions, labels = parse_program(text)
    outputs = execute(instructions, labels)
    for o in outputs:
        print(o)


if __name__ == '__main__':
    main()
