"""DSL for 16-bit bitvector programs.

Programs are straight-line sequences of instructions operating on registers.
Registers z0..z3 hold the 4 input values; each instruction appends a new
register computed from two earlier registers via a chosen operation.
The output is the value of the last register.
"""

BITS = 16
MASK = (1 << BITS) - 1

# (name, arity, semantics)
OPS = [
    ("add", 2, lambda x, y: (x + y) & MASK),
    ("sub", 2, lambda x, y: (x - y) & MASK),
    ("mul", 2, lambda x, y: (x * y) & MASK),
    ("and", 2, lambda x, y: x & y),
    ("or",  2, lambda x, y: x | y),
    ("xor", 2, lambda x, y: x ^ y),
    ("shl", 2, lambda x, y: (x << (y & 0xf)) & MASK),
    ("shr", 2, lambda x, y: (x >> (y & 0xf)) & MASK),
    ("neg", 1, lambda x, _: (-x) & MASK),
    ("not", 1, lambda x, _: (~x) & MASK),
]

NUM_OPS = len(OPS)
NUM_INPUTS = 4  # a, b, c, d


def evaluate_program(program, inputs):
    """Evaluate a DSL program on concrete inputs.

    Args:
        program: list of {"op": int, "arg1": int, "arg2": int}
        inputs:  tuple of 4 ints in [0, MASK]

    Returns:
        16-bit unsigned integer result (value of last register)
    """
    regs = list(inputs[:NUM_INPUTS])
    for instr in program:
        op_idx = instr["op"]
        a1 = regs[instr["arg1"]]
        a2 = regs[instr["arg2"]] if OPS[op_idx][1] == 2 else 0
        result = OPS[op_idx][2](a1, a2)
        regs.append(result)
    return regs[-1]


def validate_program(program, max_lines=5):
    """Check syntactic validity of a DSL program."""
    if not isinstance(program, list) or len(program) == 0 or len(program) > max_lines:
        return False
    num_regs = NUM_INPUTS
    for instr in program:
        if not isinstance(instr, dict):
            return False
        for key in ("op", "arg1", "arg2"):
            if key not in instr:
                return False
        if not (0 <= instr["op"] < NUM_OPS):
            return False
        if not (0 <= instr["arg1"] < num_regs):
            return False
        if not (0 <= instr["arg2"] < num_regs):
            return False
        num_regs += 1
    return True


def program_to_string(program):
    """Human-readable representation of a DSL program."""
    reg_names = ["a", "b", "c", "d"]
    lines = []
    for i, instr in enumerate(program):
        reg = f"z{NUM_INPUTS + i}"
        reg_names.append(reg)
        op_name = OPS[instr["op"]][0]
        arity = OPS[instr["op"]][1]
        if arity == 1:
            lines.append(f"{reg} = {op_name}({reg_names[instr['arg1']]})")
        else:
            lines.append(
                f"{reg} = {op_name}({reg_names[instr['arg1']]}, "
                f"{reg_names[instr['arg2']]})"
            )
    lines.append(f"output = {reg_names[-1]}")
    return "\n".join(lines)
