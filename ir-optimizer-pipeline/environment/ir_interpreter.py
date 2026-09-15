
"""
Interpreter for the IR instruction set.

Executes a list of IR instructions, handling built-in arithmetic/comparison
operators and I/O functions (print_int, print_bool, read_int).

Division and modulo use truncation-toward-zero semantics (C-style).
"""

from ir import (
    Instruction, IRVar, LoadIntConst, LoadBoolConst, Copy, Call,
    Jump, CondJump, Label,
)

SIDE_EFFECT_FUNS = frozenset({'print_int', 'print_bool', 'read_int'})


def _truncdiv(a: int, b: int) -> int:
    """Integer division truncating toward zero (C-style)."""
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return q


def _truncmod(a: int, b: int) -> int:
    """Integer modulo with sign of dividend (C-style)."""
    r = abs(a) % abs(b)
    if a < 0:
        r = -r
    return r


def interpret(instructions: list, stdin_lines: list | None = None) -> list[str]:
    """
    Interpret a list of IR instructions.

    Args:
        instructions: list of Instruction objects
        stdin_lines: optional list of strings for read_int input

    Returns:
        List of output lines (strings printed by print_int / print_bool).
    """
    # Build label index
    label_index: dict[str, int] = {}
    for i, insn in enumerate(instructions):
        if isinstance(insn, Label):
            if insn.name in label_index:
                raise RuntimeError(f"Duplicate label: {insn.name}")
            label_index[insn.name] = i

    variables: dict[str, object] = {}
    output_lines: list[str] = []
    input_iter = iter(stdin_lines or [])

    def get_var(v: IRVar) -> object:
        if v.name not in variables:
            raise RuntimeError(f"Undefined variable: {v.name}")
        return variables[v.name]

    def call_builtin(name: str, args: list) -> object:
        if name == '+':
            return args[0] + args[1]
        elif name == '-':
            return args[0] - args[1]
        elif name == '*':
            return args[0] * args[1]
        elif name == '/':
            if args[1] == 0:
                raise RuntimeError("Division by zero")
            return _truncdiv(args[0], args[1])
        elif name == '%':
            if args[1] == 0:
                raise RuntimeError("Modulo by zero")
            return _truncmod(args[0], args[1])
        elif name == '==':
            return args[0] == args[1]
        elif name == '!=':
            return args[0] != args[1]
        elif name == '<':
            return args[0] < args[1]
        elif name == '<=':
            return args[0] <= args[1]
        elif name == '>':
            return args[0] > args[1]
        elif name == '>=':
            return args[0] >= args[1]
        elif name == 'unary_-':
            return -args[0]
        elif name == 'not':
            return not args[0]
        elif name == 'print_int':
            output_lines.append(str(args[0]))
            return 0
        elif name == 'print_bool':
            output_lines.append('true' if args[0] else 'false')
            return 0
        elif name == 'read_int':
            try:
                return int(next(input_iter).strip())
            except StopIteration:
                raise RuntimeError("No more input available for read_int")
        else:
            raise RuntimeError(f"Unknown builtin: {name}")

    pc = 0
    max_steps = 2_000_000
    steps = 0

    while pc < len(instructions):
        steps += 1
        if steps > max_steps:
            raise RuntimeError(
                f"Exceeded maximum step count ({max_steps}). Possible infinite loop."
            )

        insn = instructions[pc]

        if isinstance(insn, LoadIntConst):
            variables[insn.dest.name] = insn.value
            pc += 1
        elif isinstance(insn, LoadBoolConst):
            variables[insn.dest.name] = insn.value
            pc += 1
        elif isinstance(insn, Copy):
            variables[insn.dest.name] = get_var(insn.source)
            pc += 1
        elif isinstance(insn, Call):
            arg_vals = [get_var(a) for a in insn.args]
            result = call_builtin(insn.fun.name, arg_vals)
            variables[insn.dest.name] = result
            pc += 1
        elif isinstance(insn, Jump):
            if insn.label not in label_index:
                raise RuntimeError(f"Unknown label: {insn.label}")
            pc = label_index[insn.label]
        elif isinstance(insn, CondJump):
            val = get_var(insn.cond)
            if val:
                pc = label_index[insn.then_label]
            else:
                pc = label_index[insn.else_label]
        elif isinstance(insn, Label):
            pc += 1
        else:
            raise RuntimeError(f"Unknown instruction type: {type(insn)}")

    return output_lines
