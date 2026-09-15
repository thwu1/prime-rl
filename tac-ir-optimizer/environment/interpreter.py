#!/usr/bin/env python3
"""TAC (Three-Address Code) interpreter."""

import re
import sys
from typing import Dict, List, Optional

INT32_MASK = 0xFFFFFFFF
INT32_SIGN = 0x80000000
INT32_MOD = 0x100000000


def to_int32(val: int) -> int:
    val = val & INT32_MASK
    if val >= INT32_SIGN:
        val -= INT32_MOD
    return val


class Instruction:
    __slots__ = ('kind', 'dest', 'op', 'args', 'label')

    def __init__(self, kind: str, dest: Optional[str] = None,
                 op: Optional[str] = None, args: Optional[List[str]] = None,
                 label: Optional[str] = None):
        self.kind = kind
        self.dest = dest
        self.op = op
        self.args = args if args is not None else []
        self.label = label


class Function:
    def __init__(self, name: str, params: List[str], instructions: List[Instruction]):
        self.name = name
        self.params = params
        self.instructions = instructions
        self.label_map: Dict[str, int] = {}
        for i, inst in enumerate(instructions):
            if inst.label is not None:
                self.label_map[inst.label] = i


class Program:
    def __init__(self, functions: Dict[str, Function]):
        self.functions = functions


def parse_instruction(line: str) -> Optional[Instruction]:
    if '#' in line:
        comment_pos = line.index('#')
        in_call = False
        for c in line[:comment_pos]:
            if c == '(':
                in_call = True
            elif c == ')':
                in_call = False
        if not in_call:
            line = line[:comment_pos].strip()
    if not line:
        return None

    m = re.match(r'return\s+(.+)', line)
    if m:
        return Instruction('return', args=[m.group(1).strip()])

    m = re.match(r'jump\s+(\w+)', line)
    if m:
        return Instruction('jump', args=[m.group(1)])

    m = re.match(r'jz\s+(\S+)\s+(\w+)', line)
    if m:
        return Instruction('jz', args=[m.group(1), m.group(2)])

    m = re.match(r'jnz\s+(\S+)\s+(\w+)', line)
    if m:
        return Instruction('jnz', args=[m.group(1), m.group(2)])

    m = re.match(r'(\w+)\s*=\s*(.+)', line)
    if m:
        dest = m.group(1)
        rhs = m.group(2).strip()

        cm = re.match(r'call\s+(\w+)\s*\(([^)]*)\)', rhs)
        if cm:
            func = cm.group(1)
            args_str = cm.group(2).strip()
            args = [a.strip() for a in args_str.split(',') if a.strip()] if args_str else []
            return Instruction('call', dest=dest, op=func, args=args)

        bm = re.match(
            r'(add|sub|mul|div|mod|eq|ne|lt|le|gt|ge|band|bor|bxor|shl|shr|and|or)\s+(\S+)\s+(\S+)',
            rhs)
        if bm:
            return Instruction('binop', dest=dest, op=bm.group(1),
                               args=[bm.group(2), bm.group(3)])

        um = re.match(r'(neg|not|bnot)\s+(\S+)', rhs)
        if um:
            return Instruction('unop', dest=dest, op=um.group(1), args=[um.group(2)])

        cm2 = re.match(r'copy\s+(\S+)', rhs)
        if cm2:
            return Instruction('copy', dest=dest, args=[cm2.group(1)])

        if re.match(r'^-?\d+$', rhs):
            return Instruction('assign_const', dest=dest, args=[rhs])

        raise ValueError(f"Cannot parse RHS: '{rhs}' in line: '{line}'")

    raise ValueError(f"Cannot parse instruction: '{line}'")


def parse_tac(text: str) -> Program:
    functions: Dict[str, Function] = {}
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('#'):
            i += 1
            continue

        fm = re.match(r'function\s+(\w+)\s*\(([^)]*)\)\s*:', line)
        if fm:
            func_name = fm.group(1)
            params_str = fm.group(2).strip()
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            instructions: List[Instruction] = []
            pending_label: Optional[str] = None
            i += 1
            while i < len(lines):
                line = lines[i].strip()
                if not line or line.startswith('#'):
                    i += 1
                    continue
                if re.match(r'function\s+\w+\s*\(', line):
                    break
                lm = re.match(r'^(\w+)\s*:\s*$', line)
                if lm:
                    pending_label = lm.group(1)
                    i += 1
                    continue
                inst = parse_instruction(line)
                if inst is not None:
                    inst.label = pending_label
                    pending_label = None
                    instructions.append(inst)
                i += 1
            functions[func_name] = Function(func_name, params, instructions)
        else:
            i += 1
    return Program(functions)


def resolve(val: str, env: Dict[str, int]) -> int:
    try:
        return to_int32(int(val))
    except ValueError:
        if val not in env:
            raise RuntimeError(f"Undefined variable: {val}")
        return env[val]


def c_div(a: int, b: int) -> int:
    if b == 0:
        raise RuntimeError("Division by zero")
    q, r = divmod(a, b)
    if r != 0 and (a < 0) != (b < 0):
        q += 1
    return q


def eval_binop(op: str, a: int, b: int) -> int:
    if op == 'add': return to_int32(a + b)
    if op == 'sub': return to_int32(a - b)
    if op == 'mul': return to_int32(a * b)
    if op == 'div': return to_int32(c_div(a, b))
    if op == 'mod':
        if b == 0:
            raise RuntimeError("Division by zero")
        return to_int32(a - c_div(a, b) * b)
    if op == 'eq': return 1 if a == b else 0
    if op == 'ne': return 1 if a != b else 0
    if op == 'lt': return 1 if a < b else 0
    if op == 'le': return 1 if a <= b else 0
    if op == 'gt': return 1 if a > b else 0
    if op == 'ge': return 1 if a >= b else 0
    if op == 'and': return 1 if (a != 0 and b != 0) else 0
    if op == 'or': return 1 if (a != 0 or b != 0) else 0
    if op == 'band': return to_int32(a & b)
    if op == 'bor': return to_int32(a | b)
    if op == 'bxor': return to_int32(a ^ b)
    if op == 'shl': return to_int32(a << (b & 31))
    if op == 'shr': return to_int32(a >> (b & 31))
    raise ValueError(f"Unknown binop: {op}")


def eval_unop(op: str, a: int) -> int:
    if op == 'neg': return to_int32(-a)
    if op == 'not': return 1 if a == 0 else 0
    if op == 'bnot': return to_int32(~a)
    raise ValueError(f"Unknown unop: {op}")


def execute(program: Program, func_name: str, args: Optional[List[int]] = None,
            max_steps: int = 10000000) -> int:
    if args is None:
        args = []
    func = program.functions.get(func_name)
    if func is None:
        raise RuntimeError(f"Undefined function: {func_name}")

    env: Dict[str, int] = {}
    for param, arg in zip(func.params, args):
        env[param] = to_int32(arg)

    pc = 0
    steps = 0
    while pc < len(func.instructions):
        if steps >= max_steps:
            raise RuntimeError("Maximum step count exceeded")
        steps += 1
        inst = func.instructions[pc]

        if inst.kind == 'assign_const':
            env[inst.dest] = to_int32(int(inst.args[0]))
            pc += 1
        elif inst.kind == 'copy':
            env[inst.dest] = resolve(inst.args[0], env)
            pc += 1
        elif inst.kind == 'binop':
            a = resolve(inst.args[0], env)
            b = resolve(inst.args[1], env)
            env[inst.dest] = eval_binop(inst.op, a, b)
            pc += 1
        elif inst.kind == 'unop':
            a = resolve(inst.args[0], env)
            env[inst.dest] = eval_unop(inst.op, a)
            pc += 1
        elif inst.kind == 'call':
            call_args = [resolve(a, env) for a in inst.args]
            env[inst.dest] = execute(program, inst.op, call_args, max_steps - steps)
            pc += 1
        elif inst.kind == 'return':
            return resolve(inst.args[0], env)
        elif inst.kind == 'jump':
            label = inst.args[0]
            if label not in func.label_map:
                raise RuntimeError(f"Undefined label: {label}")
            pc = func.label_map[label]
        elif inst.kind == 'jz':
            val = resolve(inst.args[0], env)
            label = inst.args[1]
            if val == 0:
                if label not in func.label_map:
                    raise RuntimeError(f"Undefined label: {label}")
                pc = func.label_map[label]
            else:
                pc += 1
        elif inst.kind == 'jnz':
            val = resolve(inst.args[0], env)
            label = inst.args[1]
            if val != 0:
                if label not in func.label_map:
                    raise RuntimeError(f"Undefined label: {label}")
                pc = func.label_map[label]
            else:
                pc += 1
        else:
            raise RuntimeError(f"Unknown instruction kind: {inst.kind}")

    raise RuntimeError(f"Function {func_name} ended without returning")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 interpreter.py <file.tac> [function_name]", file=sys.stderr)
        sys.exit(1)
    filename = sys.argv[1]
    func_name = sys.argv[2] if len(sys.argv) > 2 else 'target'
    with open(filename, 'r') as f:
        text = f.read()
    program = parse_tac(text)
    result = execute(program, func_name)
    print(result)


if __name__ == '__main__':
    main()
