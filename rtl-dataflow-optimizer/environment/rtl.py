"""
RTL Intermediate Representation and Interpreter.


This module defines a register transfer language (RTL) intermediate representation
inspired by CompCert's RTL IR. Programs are control-flow graphs where nodes map to
instructions operating on pseudo-registers.

Programs are stored as JSON:
{
  "name": "function_name",
  "params": [reg_id, ...],         // parameter registers (integer IDs)
  "entrypoint": node_id,           // entry node (integer)
  "code": {
    "node_id": {instruction},      // keys are stringified ints in JSON
    ...
  }
}

After loading with load_program(), code keys are converted to Python ints.

Instruction formats:
  {"kind": "nop", "succ": node_id}
  {"kind": "op", "op": op_name, "args": [reg_ids], "dst": reg_id, "succ": node_id}
      For "const": {"kind": "op", "op": "const", "imm": int_value, "args": [], "dst": reg_id, "succ": node_id}
      For "move":  {"kind": "op", "op": "move", "args": [src_reg], "dst": reg_id, "succ": node_id}
  {"kind": "cond", "cmp": cmp_name, "arg1": reg_id, "arg2": reg_id, "ifso": node_id, "ifnot": node_id}
  {"kind": "ret", "arg": reg_id}

Operations (op field):
  const  - load immediate (uses "imm" field, "args" is [])
  move   - register copy
  add    - integer addition
  sub    - integer subtraction
  mul    - integer multiplication
  div    - integer division (truncated toward zero, 0 on div-by-zero)
  mod    - integer modulo (0 on div-by-zero)
  neg    - integer negation (unary, args has 1 element)
  and    - bitwise AND
  or     - bitwise OR
  xor    - bitwise XOR
  shl    - left shift (masked to 0-63)
  shr    - arithmetic right shift (masked to 0-63)

Comparisons (cmp field):
  eq, ne, lt, le, gt, ge
"""

import json
import sys


def load_program(path):
    """Load an RTL program from a JSON file. Code keys are converted to ints."""
    with open(path) as f:
        prog = json.load(f)
    prog["code"] = {int(k): v for k, v in prog["code"].items()}
    return prog


def save_program(prog, path):
    """Save an RTL program to a JSON file."""
    out = dict(prog)
    out["code"] = {str(k): v for k, v in prog["code"].items()}
    with open(path, 'w') as f:
        json.dump(out, f, indent=2)


def eval_op(op, arg_vals, imm=None):
    """Evaluate an RTL operation on concrete integer arguments."""
    if op == "const":
        return imm
    elif op == "move":
        return arg_vals[0]
    elif op == "add":
        return arg_vals[0] + arg_vals[1]
    elif op == "sub":
        return arg_vals[0] - arg_vals[1]
    elif op == "mul":
        return arg_vals[0] * arg_vals[1]
    elif op == "div":
        if arg_vals[1] == 0:
            return 0
        a, b = arg_vals[0], arg_vals[1]
        sign = -1 if (a < 0) != (b < 0) else 1
        return sign * (abs(a) // abs(b))
    elif op == "mod":
        if arg_vals[1] == 0:
            return 0
        a, b = arg_vals[0], arg_vals[1]
        return a - b * (a // b) if (a < 0) == (b < 0) else a - b * (-(abs(a) // abs(b)))
    elif op == "neg":
        return -arg_vals[0]
    elif op == "and":
        return arg_vals[0] & arg_vals[1]
    elif op == "or":
        return arg_vals[0] | arg_vals[1]
    elif op == "xor":
        return arg_vals[0] ^ arg_vals[1]
    elif op == "shl":
        return arg_vals[0] << (arg_vals[1] & 63)
    elif op == "shr":
        return arg_vals[0] >> (arg_vals[1] & 63)
    raise ValueError(f"Unknown operation: {op}")


def eval_cond(cmp, a, b):
    """Evaluate an RTL comparison on two concrete integer values."""
    if cmp == "eq":
        return a == b
    elif cmp == "ne":
        return a != b
    elif cmp == "lt":
        return a < b
    elif cmp == "le":
        return a <= b
    elif cmp == "gt":
        return a > b
    elif cmp == "ge":
        return a >= b
    raise ValueError(f"Unknown comparison: {cmp}")


def successors(instr):
    """Return the list of successor node IDs for an instruction."""
    kind = instr["kind"]
    if kind == "nop":
        return [instr["succ"]]
    elif kind == "op":
        return [instr["succ"]]
    elif kind == "cond":
        return [instr["ifso"], instr["ifnot"]]
    elif kind == "ret":
        return []
    return []


def predecessors(prog):
    """Compute predecessor map: node -> list of predecessor nodes."""
    code = prog["code"]
    preds = {n: [] for n in code}
    for n, instr in code.items():
        for s in successors(instr):
            if s in code:
                if s not in preds:
                    preds[s] = []
                preds[s].append(n)
    return preds


def defined_reg(instr):
    """Return the register defined by an instruction, or None."""
    if instr["kind"] == "op":
        return instr["dst"]
    return None


def used_regs(instr):
    """Return the list of registers used (read) by an instruction."""
    kind = instr["kind"]
    if kind == "op":
        if instr["op"] == "const":
            return []
        return list(instr.get("args", []))
    elif kind == "cond":
        return [instr["arg1"], instr["arg2"]]
    elif kind == "ret":
        return [instr["arg"]]
    return []


def interpret(prog, args, max_steps=1000000):
    """Execute an RTL program with the given arguments. Returns the integer result."""
    regs = {}
    for p, a in zip(prog["params"], args):
        regs[p] = a

    pc = prog["entrypoint"]
    code = prog["code"]
    steps = 0

    while steps < max_steps:
        steps += 1
        if pc not in code:
            raise RuntimeError(f"PC {pc} not in code")
        instr = code[pc]
        kind = instr["kind"]

        if kind == "nop":
            pc = instr["succ"]
        elif kind == "op":
            op = instr["op"]
            dst = instr["dst"]
            if op == "const":
                regs[dst] = instr["imm"]
            else:
                av = [regs.get(r, 0) for r in instr["args"]]
                regs[dst] = eval_op(op, av)
            pc = instr["succ"]
        elif kind == "cond":
            a = regs.get(instr["arg1"], 0)
            b = regs.get(instr["arg2"], 0)
            if eval_cond(instr["cmp"], a, b):
                pc = instr["ifso"]
            else:
                pc = instr["ifnot"]
        elif kind == "ret":
            return regs.get(instr["arg"], 0)
        else:
            raise RuntimeError(f"Unknown instruction kind: {kind}")

    raise RuntimeError("Max steps exceeded — possible infinite loop")
