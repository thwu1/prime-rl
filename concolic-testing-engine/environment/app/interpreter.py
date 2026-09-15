#!/usr/bin/env python3
"""
WHILE3ADDR Interpreter
Parses and executes programs in a simple 3-address code intermediate representation.


Language specification:
  VAR = NUM                    # constant assignment
  VAR = input()                # read integer input
  VAR = VAR2                   # copy assignment
  VAR = VAR2 OP VAR3           # binary operation
  if VAR RELOP VAR2 goto LABEL # conditional branch
  goto LABEL                   # unconditional jump
  assert VAR RELOP VAR2        # assertion (fails if condition is false)
  halt                         # stop execution

Operators: + - * / % & | ^ << >>
Relational: == != < > <= >=
Labels: NAME: (on its own line or before an instruction)
Comments: # ...
"""

import sys


class Instruction:
    pass

class ConstAssign(Instruction):
    def __init__(self, var, value):
        self.var = var
        self.value = value
    def __repr__(self):
        return f"{self.var} = {self.value}"

class InputAssign(Instruction):
    def __init__(self, var):
        self.var = var
    def __repr__(self):
        return f"{self.var} = input()"

class CopyAssign(Instruction):
    def __init__(self, dst, src):
        self.dst = dst
        self.src = src
    def __repr__(self):
        return f"{self.dst} = {self.src}"

class BinOpAssign(Instruction):
    def __init__(self, dst, left, op, right):
        self.dst = dst
        self.left = left
        self.op = op
        self.right = right
    def __repr__(self):
        return f"{self.dst} = {self.left} {self.op} {self.right}"

class CondGoto(Instruction):
    def __init__(self, left, relop, right, label):
        self.left = left
        self.relop = relop
        self.right = right
        self.label = label
    def __repr__(self):
        return f"if {self.left} {self.relop} {self.right} goto {self.label}"

class Goto(Instruction):
    def __init__(self, label):
        self.label = label
    def __repr__(self):
        return f"goto {self.label}"

class Assert(Instruction):
    def __init__(self, left, relop, right):
        self.left = left
        self.relop = relop
        self.right = right
    def __repr__(self):
        return f"assert {self.left} {self.relop} {self.right}"

class Halt(Instruction):
    def __repr__(self):
        return "halt"


class Program:
    def __init__(self, instructions, labels):
        self.instructions = instructions
        self.labels = labels


def parse_instruction(line):
    """Parse a single instruction line (no label prefix)."""
    tokens = line.split()
    if not tokens:
        return None

    if tokens[0] == 'halt':
        return Halt()

    if tokens[0] == 'goto':
        return Goto(tokens[1])

    if tokens[0] == 'assert':
        return Assert(tokens[1], tokens[2], tokens[3])

    if tokens[0] == 'if':
        # if VAR RELOP VAR goto LABEL
        return CondGoto(tokens[1], tokens[2], tokens[3], tokens[5])

    # Assignment: VAR = ...
    var = tokens[0]
    # tokens[1] should be '='
    rhs = tokens[2:]

    if len(rhs) == 1:
        if rhs[0] == 'input()':
            return InputAssign(var)
        try:
            return ConstAssign(var, int(rhs[0]))
        except ValueError:
            return CopyAssign(var, rhs[0])

    if len(rhs) == 3:
        return BinOpAssign(var, rhs[0], rhs[1], rhs[2])

    raise ValueError(f"Cannot parse instruction: {line}")


def parse(source):
    """Parse a WHILE3ADDR program from source text."""
    instructions = []
    labels = {}

    for line in source.split('\n'):
        line = line.split('#')[0].strip()
        if not line:
            continue

        colon_pos = line.find(':')
        if colon_pos > 0:
            potential_label = line[:colon_pos].strip()
            if ' ' not in potential_label and potential_label not in ('if', 'assert', 'goto', 'halt'):
                labels[potential_label] = len(instructions)
                rest = line[colon_pos + 1:].strip()
                if rest:
                    inst = parse_instruction(rest)
                    if inst:
                        instructions.append(inst)
                continue

        inst = parse_instruction(line)
        if inst:
            instructions.append(inst)

    return Program(instructions, labels)


OPS = {
    '+': lambda a, b: a + b,
    '-': lambda a, b: a - b,
    '*': lambda a, b: a * b,
    '/': lambda a, b: a // b if b != 0 else 0,
    '%': lambda a, b: a % b if b != 0 else 0,
    '&': lambda a, b: a & b,
    '|': lambda a, b: a | b,
    '^': lambda a, b: a ^ b,
    '<<': lambda a, b: a << b if 0 <= b < 64 else 0,
    '>>': lambda a, b: a >> b if 0 <= b < 64 else 0,
}

RELOPS = {
    '==': lambda a, b: a == b,
    '!=': lambda a, b: a != b,
    '<': lambda a, b: a < b,
    '>': lambda a, b: a > b,
    '<=': lambda a, b: a <= b,
    '>=': lambda a, b: a >= b,
}


def execute(program, inputs, max_steps=100000):
    """Execute a WHILE3ADDR program with given inputs.

    Args:
        program: A Program object
        inputs: A list of integers to supply to input() calls
        max_steps: Maximum execution steps before timeout

    Returns:
        (status, assertion_failed, env) where:
        - status: 'halt', 'assertion_failed', 'ok', or 'timeout'
        - assertion_failed: True if an assertion failed
        - env: The final variable environment
    """
    env = {}
    input_idx = 0
    pc = 0
    steps = 0

    while pc < len(program.instructions) and steps < max_steps:
        inst = program.instructions[pc]
        steps += 1

        if isinstance(inst, Halt):
            return 'halt', False, env

        elif isinstance(inst, ConstAssign):
            env[inst.var] = inst.value
            pc += 1

        elif isinstance(inst, InputAssign):
            if input_idx >= len(inputs):
                raise RuntimeError(f"Not enough inputs: needed more than {len(inputs)}")
            env[inst.var] = inputs[input_idx]
            input_idx += 1
            pc += 1

        elif isinstance(inst, CopyAssign):
            env[inst.dst] = env[inst.src]
            pc += 1

        elif isinstance(inst, BinOpAssign):
            left_val = env[inst.left]
            right_val = env[inst.right]
            env[inst.dst] = OPS[inst.op](left_val, right_val)
            pc += 1

        elif isinstance(inst, CondGoto):
            left_val = env[inst.left]
            right_val = env[inst.right]
            if RELOPS[inst.relop](left_val, right_val):
                pc = program.labels[inst.label]
            else:
                pc += 1

        elif isinstance(inst, Goto):
            pc = program.labels[inst.label]

        elif isinstance(inst, Assert):
            left_val = env[inst.left]
            right_val = env[inst.right]
            if not RELOPS[inst.relop](left_val, right_val):
                return 'assertion_failed', True, env
            pc += 1

    if steps >= max_steps:
        return 'timeout', False, env
    return 'ok', False, env


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 interpreter.py <program.prog> [input1 input2 ...]")
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        source = f.read()

    program = parse(source)
    inputs = [int(x) for x in sys.argv[2:]]

    status, failed, env = execute(program, inputs)
    print(f"Status: {status}")
    if failed:
        print("ASSERTION FAILED")
    print(f"Environment: {env}")
