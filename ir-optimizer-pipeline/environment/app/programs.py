
"""
Test IR programs for the optimizer.

Each program is a dict with:
  - name: human-readable identifier
  - instructions: list of IR Instruction objects
  - stdin: list of input lines (for read_int)
  - expected_output: list of expected output lines
  - min_reduction: minimum fraction of instructions that must be eliminated (0.0-1.0)
"""

from ir import (
    IRVar, LoadIntConst, LoadBoolConst, Copy, Call, Jump, CondJump, Label,
)


def V(name: str) -> IRVar:
    return IRVar(name)


PROGRAMS: list[dict] = []

# ---------------------------------------------------------------------------
# Program 1: Pure constant arithmetic — everything foldable
# 3 + 5 = 8, 8 * 2 = 16, 16 - 10 = 6 → print 6
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'constant_arithmetic',
    'instructions': [
        LoadIntConst(3, V('x1')),
        LoadIntConst(5, V('x2')),
        Call(V('+'), (V('x1'), V('x2')), V('x3')),
        LoadIntConst(2, V('x4')),
        Call(V('*'), (V('x3'), V('x4')), V('x5')),
        LoadIntConst(10, V('x6')),
        Call(V('-'), (V('x5'), V('x6')), V('x7')),
        Call(V('print_int'), (V('x7'),), V('_r1')),
    ],
    'stdin': [],
    'expected_output': ['6'],
    'min_reduction': 0.3,
})

# ---------------------------------------------------------------------------
# Program 2: Dead code elimination — only 'a' is used
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'dead_code',
    'instructions': [
        LoadIntConst(42, V('a')),
        LoadIntConst(99, V('b')),
        LoadIntConst(200, V('c')),
        Call(V('+'), (V('b'), V('c')), V('d')),
        Call(V('*'), (V('d'), V('b')), V('e')),
        LoadIntConst(7, V('f')),
        Call(V('print_int'), (V('a'),), V('_r1')),
    ],
    'stdin': [],
    'expected_output': ['42'],
    'min_reduction': 0.5,
})

# ---------------------------------------------------------------------------
# Program 3: Constant condition → dead branch elimination
# cond = true → only then-branch is taken
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'constant_branch',
    'instructions': [
        LoadBoolConst(True, V('cond')),
        LoadIntConst(42, V('x1')),
        LoadIntConst(99, V('x2')),
        CondJump(V('cond'), 'then_branch', 'else_branch'),
        Label('then_branch'),
        Copy(V('x1'), V('result')),
        Jump('end'),
        Label('else_branch'),
        Copy(V('x2'), V('result')),
        Jump('end'),
        Label('end'),
        Call(V('print_int'), (V('result'),), V('_r1')),
    ],
    'stdin': [],
    'expected_output': ['42'],
    'min_reduction': 0.2,
})

# ---------------------------------------------------------------------------
# Program 4: Copy propagation chain
# a=7, b=a, c=b, d=c, e=d → e=7, result = e+a = 14
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'copy_chain',
    'instructions': [
        LoadIntConst(7, V('a')),
        Copy(V('a'), V('b')),
        Copy(V('b'), V('c')),
        Copy(V('c'), V('d')),
        Copy(V('d'), V('e')),
        Call(V('+'), (V('e'), V('a')), V('result')),
        Call(V('print_int'), (V('result'),), V('_r1')),
    ],
    'stdin': [],
    'expected_output': ['14'],
    'min_reduction': 0.3,
})

# ---------------------------------------------------------------------------
# Program 5: Large dead computation block
# Only live_result = 1 + 2 = 3 is used; everything else is dead
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'large_dead_block',
    'instructions': [
        LoadIntConst(1, V('c1')),
        LoadIntConst(2, V('c2')),
        Call(V('+'), (V('c1'), V('c2')), V('live_result')),
        LoadIntConst(100, V('d1')),
        LoadIntConst(200, V('d2')),
        LoadIntConst(300, V('d3')),
        Call(V('*'), (V('d1'), V('d2')), V('d4')),
        Call(V('+'), (V('d4'), V('d3')), V('d5')),
        Call(V('*'), (V('d5'), V('d1')), V('d6')),
        Call(V('-'), (V('d6'), V('d2')), V('d7')),
        Call(V('/'), (V('d7'), V('d3')), V('d8')),
        LoadIntConst(50, V('d9')),
        Call(V('%'), (V('d8'), V('d9')), V('d10')),
        LoadBoolConst(True, V('unused_bool')),
        LoadIntConst(999, V('unused_int')),
        Call(V('print_int'), (V('live_result'),), V('_r1')),
    ],
    'stdin': [],
    'expected_output': ['3'],
    'min_reduction': 0.6,
})

# ---------------------------------------------------------------------------
# Program 6: Loop with dead code outside
# Print 5, 4, 3, 2, 1 via countdown loop; dead code before the loop
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'loop_with_dead_code',
    'instructions': [
        LoadIntConst(5, V('n')),
        LoadIntConst(1, V('one')),
        LoadIntConst(0, V('zero')),
        LoadIntConst(999, V('dead1')),
        LoadIntConst(888, V('dead2')),
        Call(V('+'), (V('dead1'), V('dead2')), V('dead3')),
        Label('loop_start'),
        Call(V('>'), (V('n'), V('zero')), V('loop_cond')),
        CondJump(V('loop_cond'), 'loop_body', 'loop_end'),
        Label('loop_body'),
        Call(V('print_int'), (V('n'),), V('_r_loop')),
        Call(V('-'), (V('n'), V('one')), V('n_new')),
        Copy(V('n_new'), V('n')),
        Jump('loop_start'),
        Label('loop_end'),
    ],
    'stdin': [],
    'expected_output': ['5', '4', '3', '2', '1'],
    'min_reduction': 0.1,
})

# ---------------------------------------------------------------------------
# Program 7: Nested conditions — all constant-foldable
# sum=30, 30>25→true → inner_sum=35, 35>30→true → print 35
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'nested_conditions',
    'instructions': [
        LoadIntConst(10, V('a')),
        LoadIntConst(20, V('b')),
        Call(V('+'), (V('a'), V('b')), V('sum')),
        LoadIntConst(25, V('threshold')),
        Call(V('>'), (V('sum'), V('threshold')), V('cond1')),
        CondJump(V('cond1'), 'outer_then', 'outer_else'),
        Label('outer_then'),
        LoadIntConst(5, V('inner_val')),
        Call(V('+'), (V('sum'), V('inner_val')), V('inner_sum')),
        LoadIntConst(30, V('inner_threshold')),
        Call(V('>'), (V('inner_sum'), V('inner_threshold')), V('cond2')),
        CondJump(V('cond2'), 'inner_then', 'inner_else'),
        Label('inner_then'),
        Call(V('print_int'), (V('inner_sum'),), V('_r1')),
        Jump('inner_end'),
        Label('inner_else'),
        Call(V('print_int'), (V('sum'),), V('_r2')),
        Jump('inner_end'),
        Label('inner_end'),
        Jump('outer_end'),
        Label('outer_else'),
        Call(V('print_int'), (V('a'),), V('_r3')),
        Jump('outer_end'),
        Label('outer_end'),
    ],
    'stdin': [],
    'expected_output': ['35'],
    'min_reduction': 0.2,
})

# ---------------------------------------------------------------------------
# Program 8: Dynamic input with surrounding dead code
# n = read_int(), result = n*2 + 1 → print result; dead vars around it
# stdin: 7 → output: 15
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'dynamic_with_dead_code',
    'instructions': [
        Call(V('read_int'), (), V('n')),
        LoadIntConst(2, V('two')),
        LoadIntConst(1, V('one')),
        Call(V('*'), (V('n'), V('two')), V('doubled')),
        Call(V('+'), (V('doubled'), V('one')), V('result')),
        LoadIntConst(100, V('dead1')),
        LoadIntConst(200, V('dead2')),
        Call(V('+'), (V('dead1'), V('dead2')), V('dead3')),
        Call(V('*'), (V('dead3'), V('dead1')), V('dead4')),
        Call(V('print_int'), (V('result'),), V('_r1')),
    ],
    'stdin': ['7'],
    'expected_output': ['15'],
    'min_reduction': 0.3,
})

# ---------------------------------------------------------------------------
# Program 9: Multiple prints with interleaved dead code
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'interleaved_dead',
    'instructions': [
        LoadIntConst(1, V('a')),
        LoadIntConst(2, V('b')),
        LoadIntConst(3, V('c')),
        Call(V('+'), (V('a'), V('b')), V('r1')),
        LoadIntConst(999, V('dead1')),
        Call(V('print_int'), (V('r1'),), V('_p1')),
        Call(V('+'), (V('r1'), V('c')), V('r2')),
        LoadIntConst(888, V('dead2')),
        Call(V('*'), (V('dead1'), V('dead2')), V('dead3')),
        Call(V('print_int'), (V('r2'),), V('_p2')),
        Call(V('*'), (V('a'), V('b')), V('r3')),
        LoadIntConst(777, V('dead4')),
        Call(V('+'), (V('r3'), V('c')), V('r4')),
        Call(V('print_int'), (V('r4'),), V('_p3')),
    ],
    'stdin': [],
    'expected_output': ['3', '6', '5'],
    'min_reduction': 0.2,
})

# ---------------------------------------------------------------------------
# Program 10: Boolean logic with constant propagation
# not false = true, true == true → true → print 1
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'boolean_logic',
    'instructions': [
        LoadBoolConst(True, V('t')),
        LoadBoolConst(False, V('f')),
        LoadIntConst(1, V('one')),
        LoadIntConst(0, V('zero')),
        Call(V('not'), (V('f'),), V('not_f')),
        Call(V('=='), (V('t'), V('not_f')), V('both_true')),
        CondJump(V('both_true'), 'yes', 'no'),
        Label('yes'),
        Call(V('print_int'), (V('one'),), V('_r1')),
        Jump('done'),
        Label('no'),
        Call(V('print_int'), (V('zero'),), V('_r2')),
        Jump('done'),
        Label('done'),
    ],
    'stdin': [],
    'expected_output': ['1'],
    'min_reduction': 0.15,
})

# ---------------------------------------------------------------------------
# Program 11: Correctness test — branch reassignment
# x is assigned in one branch; optimizer must NOT propagate x=10 past merge
# stdin: 1 (flag > 0 → if_true branch → x reassigned to 20)
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'branch_reassignment',
    'instructions': [
        LoadIntConst(10, V('x')),
        LoadIntConst(999, V('dead_var')),
        Call(V('+'), (V('dead_var'), V('x')), V('dead_sum')),
        Call(V('read_int'), (), V('flag')),
        LoadIntConst(0, V('zero')),
        Call(V('>'), (V('flag'), V('zero')), V('cond')),
        CondJump(V('cond'), 'if_true', 'if_false'),
        Label('if_true'),
        LoadIntConst(20, V('x')),
        Jump('after'),
        Label('if_false'),
        Jump('after'),
        Label('after'),
        Call(V('print_int'), (V('x'),), V('_r')),
    ],
    'stdin': ['1'],
    'expected_output': ['20'],
    'min_reduction': 0.1,
})

# ---------------------------------------------------------------------------
# Program 12: Loop-carried dependence — optimizer must not break the loop
# Collatz step: if n%2==0 then n/2 else 3*n+1, repeated until n==1
# stdin: 6 → 6, 3, 10, 5, 16, 8, 4, 2, 1
# ---------------------------------------------------------------------------
PROGRAMS.append({
    'name': 'collatz_sequence',
    'instructions': [
        Call(V('read_int'), (), V('n')),
        LoadIntConst(1, V('one')),
        LoadIntConst(2, V('two')),
        LoadIntConst(3, V('three')),
        LoadIntConst(0, V('zero')),
        # Dead constants outside the loop
        LoadIntConst(12345, V('dead_outer1')),
        LoadIntConst(67890, V('dead_outer2')),
        Call(V('*'), (V('dead_outer1'), V('dead_outer2')), V('dead_outer3')),
        Label('collatz_loop'),
        Call(V('print_int'), (V('n'),), V('_rp')),
        Call(V('=='), (V('n'), V('one')), V('is_one')),
        CondJump(V('is_one'), 'collatz_done', 'collatz_continue'),
        Label('collatz_continue'),
        Call(V('%'), (V('n'), V('two')), V('rem')),
        Call(V('=='), (V('rem'), V('zero')), V('is_even')),
        CondJump(V('is_even'), 'even_case', 'odd_case'),
        Label('even_case'),
        Call(V('/'), (V('n'), V('two')), V('n_next_even')),
        Copy(V('n_next_even'), V('n')),
        Jump('collatz_loop'),
        Label('odd_case'),
        Call(V('*'), (V('n'), V('three')), V('t1')),
        Call(V('+'), (V('t1'), V('one')), V('n_next_odd')),
        Copy(V('n_next_odd'), V('n')),
        Jump('collatz_loop'),
        Label('collatz_done'),
    ],
    'stdin': ['6'],
    'expected_output': ['6', '3', '10', '5', '16', '8', '4', '2', '1'],
    'min_reduction': 0.05,
})
