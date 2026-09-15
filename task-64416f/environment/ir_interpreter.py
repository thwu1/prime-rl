#!/usr/bin/env python3
"""
Interpreter for a simple three-address code (TAC) intermediate representation.

IR Format:
  func <name>(<params>)
    <instructions>
  endfunc

Instructions:
  <var> = <int>                          # constant assignment
  <var> = <var>                          # copy
  <var> = <var|int> <op> <var|int>       # binary operation
  <var> = -<var>                         # negate
  print <var|int>                        # print value
  goto <label>                           # unconditional jump
  if <var> goto <label>                  # conditional jump (jump if non-zero)
  <label>:                               # label definition
  return <var|int>                       # return
  nop                                    # no operation

Binary operators: + - * / % == != < > <= >=
"""
import sys
import re


def parse_program(filename):
    """Parse an IR file into a dict of functions."""
    with open(filename) as f:
        lines = f.readlines()

    functions = {}
    current_func = None
    current_params = []
    current_body = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        m = re.match(r'func\s+(\w+)\((.*?)\)', stripped)
        if m:
            current_func = m.group(1)
            current_params = [p.strip() for p in m.group(2).split(',') if p.strip()]
            current_body = []
            continue

        if stripped == 'endfunc':
            if current_func:
                functions[current_func] = {
                    'params': current_params,
                    'body': current_body,
                }
            current_func = None
            continue

        if current_func is not None:
            current_body.append(stripped)

    return functions


def execute(functions, func_name='main', args=None):
    """Execute a function and return (return_value, output_lines)."""
    if func_name not in functions:
        raise RuntimeError(f"Function '{func_name}' not found")

    func = functions[func_name]
    env = {}

    if args:
        for param, arg in zip(func['params'], args):
            env[param] = arg

    body = func['body']

    # Build label index
    labels = {}
    for i, instr in enumerate(body):
        m = re.match(r'^(\w+):$', instr)
        if m:
            labels[m.group(1)] = i

    output = []
    pc = 0
    max_steps = 10_000_000

    for step in range(max_steps):
        if pc >= len(body):
            break

        instr = body[pc]

        # Label – skip
        if re.match(r'^\w+:$', instr):
            pc += 1
            continue

        # Nop
        if instr == 'nop':
            pc += 1
            continue

        # Print
        m = re.match(r'^print\s+(\S+)$', instr)
        if m:
            val = m.group(1)
            if val.lstrip('-').isdigit():
                output.append(str(int(val)))
            else:
                output.append(str(env.get(val, 0)))
            pc += 1
            continue

        # Return
        m = re.match(r'^return\s+(\S+)$', instr)
        if m:
            val = m.group(1)
            if val.lstrip('-').isdigit():
                return int(val), output
            return env.get(val, 0), output

        # Goto
        m = re.match(r'^goto\s+(\w+)$', instr)
        if m:
            pc = labels[m.group(1)]
            continue

        # Conditional goto
        m = re.match(r'^if\s+(\w+)\s+goto\s+(\w+)$', instr)
        if m:
            var, label = m.group(1), m.group(2)
            if env.get(var, 0) != 0:
                pc = labels[label]
            else:
                pc += 1
            continue

        # Binary operation: var = operand op operand
        m = re.match(
            r'^(\w+)\s*=\s*(\w+|-?\d+)\s*([\+\-\*/%]|==|!=|<=|>=|<|>)\s*(\w+|-?\d+)$',
            instr,
        )
        if m:
            dst = m.group(1)
            left_tok, op, right_tok = m.group(2), m.group(3), m.group(4)

            lval = int(left_tok) if left_tok.lstrip('-').isdigit() else env.get(left_tok, 0)
            rval = int(right_tok) if right_tok.lstrip('-').isdigit() else env.get(right_tok, 0)

            if   op == '+':  result = lval + rval
            elif op == '-':  result = lval - rval
            elif op == '*':  result = lval * rval
            elif op == '/':  result = lval // rval if rval != 0 else 0
            elif op == '%':  result = lval % rval  if rval != 0 else 0
            elif op == '==': result = 1 if lval == rval else 0
            elif op == '!=': result = 1 if lval != rval else 0
            elif op == '<':  result = 1 if lval <  rval else 0
            elif op == '>':  result = 1 if lval >  rval else 0
            elif op == '<=': result = 1 if lval <= rval else 0
            elif op == '>=': result = 1 if lval >= rval else 0
            else: result = 0

            env[dst] = result
            pc += 1
            continue

        # Negate: var = -var (source must start with a letter)
        m = re.match(r'^(\w+)\s*=\s*-([a-zA-Z]\w*)$', instr)
        if m:
            dst, src = m.group(1), m.group(2)
            env[dst] = -env.get(src, 0)
            pc += 1
            continue

        # Constant assignment: var = integer (including negative)
        m = re.match(r'^(\w+)\s*=\s*(-?\d+)$', instr)
        if m:
            dst, val = m.group(1), m.group(2)
            env[dst] = int(val)
            pc += 1
            continue

        # Copy: var = var
        m = re.match(r'^(\w+)\s*=\s*([a-zA-Z]\w*)$', instr)
        if m:
            dst, src = m.group(1), m.group(2)
            env[dst] = env.get(src, 0)
            pc += 1
            continue

        raise RuntimeError(f"Unknown instruction at pc={pc}: {instr}")

    else:
        raise RuntimeError("Execution step limit exceeded (possible infinite loop)")

    return 0, output


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 ir_interpreter.py <program.ir>", file=sys.stderr)
        sys.exit(1)

    functions = parse_program(sys.argv[1])
    _, output = execute(functions)
    for line in output:
        print(line)


if __name__ == '__main__':
    main()
