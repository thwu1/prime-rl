#!/usr/bin/env python3

"""Interpreter for the custom IR language."""

import sys
from ir_parser import parse_program

BINARY_OPS = {
    'add': lambda a, b: a + b,
    'sub': lambda a, b: a - b,
    'mul': lambda a, b: a * b,
    'div': lambda a, b: a // b if b != 0 else 0,
    'mod': lambda a, b: a % b if b != 0 else 0,
    'lt':  lambda a, b: 1 if a < b else 0,
    'gt':  lambda a, b: 1 if a > b else 0,
    'le':  lambda a, b: 1 if a <= b else 0,
    'ge':  lambda a, b: 1 if a >= b else 0,
    'eq':  lambda a, b: 1 if a == b else 0,
    'ne':  lambda a, b: 1 if a != b else 0,
    'and': lambda a, b: 1 if (a and b) else 0,
    'or':  lambda a, b: 1 if (a or b) else 0,
}

UNARY_OPS = {
    'not': lambda a: 1 if not a else 0,
    'neg': lambda a: -a,
}


class InterpreterError(Exception):
    pass


def interpret(program, func_name='main', args=None, max_steps=500000):
    """Interpret an IR program starting from the named function.

    Returns (return_value, output_lines).
    """
    if args is None:
        args = []

    output = []

    # Locate function
    func = None
    for f in program.functions:
        if f.name == func_name:
            func = f
            break
    if func is None:
        raise InterpreterError(f"Function '{func_name}' not found")

    block_map = {b.label: b for b in func.blocks}

    # Registers
    env = {}
    for i, param in enumerate(func.params):
        env[param] = args[i] if i < len(args) else 0

    def resolve(val):
        if isinstance(val, int):
            return val
        if val in env:
            return env[val]
        raise InterpreterError(f"Undefined register: '{val}'")

    if not func.blocks:
        return 0, output

    current_block = func.blocks[0]
    pc = 0
    steps = 0

    while steps < max_steps:
        steps += 1

        if pc >= len(current_block.instructions):
            raise InterpreterError(
                f"Fell off end of block '.{current_block.label}' without a terminator"
            )

        instr = current_block.instructions[pc]

        if instr.op == 'const':
            env[instr.dest] = instr.args[0]
            pc += 1

        elif instr.op in BINARY_OPS:
            a = resolve(instr.args[0])
            b = resolve(instr.args[1])
            env[instr.dest] = BINARY_OPS[instr.op](a, b)
            pc += 1

        elif instr.op in UNARY_OPS:
            a = resolve(instr.args[0])
            env[instr.dest] = UNARY_OPS[instr.op](a)
            pc += 1

        elif instr.op == 'copy':
            env[instr.dest] = resolve(instr.args[0])
            pc += 1

        elif instr.op == 'call':
            callee_name = instr.args[0]
            call_args = [resolve(a) for a in instr.args[1:]]
            ret_val, sub_output = interpret(
                program, callee_name, call_args, max_steps - steps
            )
            output.extend(sub_output)
            env[instr.dest] = ret_val
            pc += 1

        elif instr.op == 'cbr':
            cond = resolve(instr.args[0])
            target = instr.args[1] if cond else instr.args[2]
            if target not in block_map:
                raise InterpreterError(f"Unknown block '.{target}'")
            current_block = block_map[target]
            pc = 0

        elif instr.op == 'br':
            target = instr.args[0]
            if target not in block_map:
                raise InterpreterError(f"Unknown block '.{target}'")
            current_block = block_map[target]
            pc = 0

        elif instr.op == 'ret':
            return resolve(instr.args[0]), output

        elif instr.op == 'print':
            val = resolve(instr.args[0])
            output.append(str(val))
            pc += 1

        elif instr.op == 'nop':
            pc += 1

        else:
            raise InterpreterError(f"Unknown operation: '{instr.op}'")

    raise InterpreterError("Maximum step count exceeded (possible infinite loop)")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} program.ir [func] [args...]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        source = f.read()

    program = parse_program(source)
    func_name = sys.argv[2] if len(sys.argv) > 2 else 'main'
    call_args = [int(a) for a in sys.argv[3:]]

    ret_val, out = interpret(program, func_name, call_args)
    for line in out:
        print(line)
    sys.exit(ret_val if isinstance(ret_val, int) else 0)
