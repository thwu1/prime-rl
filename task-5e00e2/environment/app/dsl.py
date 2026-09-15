"""
DSL specification for component-based program synthesis.
All operations use 16-bit unsigned bitvector arithmetic.

Programs are straight-line sequences of binary operations:
  t0 = op(arg, arg)
  t1 = op(arg, arg)
  ...
  result = tN

Each argument can be an input variable (x0, x1, ...), a constant
(c0, c1, c65535), or a previously computed temporary (t0, t1, ...).
"""

BIT_WIDTH = 16
MASK = (1 << BIT_WIDTH) - 1

# Binary operators available in the DSL
OPERATORS = ['add', 'sub', 'mul', 'band', 'bor', 'bxor', 'shl', 'lshr']

# Named constants available as arguments
CONSTANTS = {
    'c0': 0,
    'c1': 1,
    'c65535': 65535,
}


def eval_op(op, a, b):
    """Evaluate a single binary operation on 16-bit unsigned values."""
    if op == 'add':
        return (a + b) & MASK
    elif op == 'sub':
        return (a - b) & MASK
    elif op == 'mul':
        return (a * b) & MASK
    elif op == 'band':
        return a & b
    elif op == 'bor':
        return a | b
    elif op == 'bxor':
        return a ^ b
    elif op == 'shl':
        return (a << (b & 0xF)) & MASK
    elif op == 'lshr':
        return a >> (b & 0xF)
    else:
        raise ValueError(f"Unknown operator: {op}")


def eval_program(program, result_var, inputs):
    """
    Evaluate a DSL program on concrete inputs.

    Args:
        program: list of dicts with keys 'op', 'arg1', 'arg2', 'dest'
        result_var: name of the variable holding the final result
        inputs: list of integer input values

    Returns:
        The 16-bit unsigned integer result.
    """
    env = {}
    for i, v in enumerate(inputs):
        env[f'x{i}'] = v & MASK
    for name, val in CONSTANTS.items():
        env[name] = val
    for step in program:
        a = env[step['arg1']]
        b = env[step['arg2']]
        env[step['dest']] = eval_op(step['op'], a, b)
    return env[result_var]
