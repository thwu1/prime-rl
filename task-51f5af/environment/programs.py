"""Test programs for the register allocator.

Each program is an X86Program using Variable nodes for temporaries.
After register allocation, all Variables must be replaced with Reg
or Deref nodes, and the program must produce identical output when
run through the emulator.

Programs cover: basic arithmetic, overlapping lifetimes, conditional
branches, loops (requiring fixed-point liveness analysis), function
calls (requiring caller-saved register handling), spilling (more
simultaneously-live variables than physical registers), nested
control flow, and loops with embedded calls.
"""

from x86_ast import X86Program, Instr, Callq, Jump, JumpIf, Variable, Immediate, Reg

# ---------------------------------------------------------------------------
# Program 1 – Simple: two variables, basic arithmetic
# Expected: rax = 42, output = []
# ---------------------------------------------------------------------------
prog_simple = X86Program({
    'start': [
        Instr('movq', [Immediate(10), Variable('x')]),
        Instr('movq', [Immediate(32), Variable('y')]),
        Instr('movq', [Variable('x'), Reg('rax')]),
        Instr('addq', [Variable('y'), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Program 2 – Multiple variables with overlapping lifetimes
# a=1, b=2, c=a+b=3, d=3, rax = c+d = 6
# Expected: rax = 6, output = []
# ---------------------------------------------------------------------------
prog_multi = X86Program({
    'start': [
        Instr('movq', [Immediate(1), Variable('a')]),
        Instr('movq', [Immediate(2), Variable('b')]),
        Instr('movq', [Variable('a'), Variable('c')]),
        Instr('addq', [Variable('b'), Variable('c')]),
        Instr('movq', [Immediate(3), Variable('d')]),
        Instr('movq', [Variable('c'), Reg('rax')]),
        Instr('addq', [Variable('d'), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Program 3 – Conditional branches
# if 10 > 5 then result=100 else result=200 → rax=100
# Expected: rax = 100, output = []
# ---------------------------------------------------------------------------
prog_cond = X86Program({
    'start': [
        Instr('movq', [Immediate(10), Variable('x')]),
        Instr('cmpq', [Immediate(5), Variable('x')]),
        JumpIf('g', 'then_block'),
        Jump('else_block'),
    ],
    'then_block': [
        Instr('movq', [Immediate(100), Variable('result')]),
        Jump('done'),
    ],
    'else_block': [
        Instr('movq', [Immediate(200), Variable('result')]),
        Jump('done'),
    ],
    'done': [
        Instr('movq', [Variable('result'), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Program 4 – Loop: sum 1..10
# sum=0, i=1; while i<11: sum+=i, i+=1; rax=sum
# Expected: rax = 55, output = []
# ---------------------------------------------------------------------------
prog_loop = X86Program({
    'start': [
        Instr('movq', [Immediate(0), Variable('sum')]),
        Instr('movq', [Immediate(1), Variable('i')]),
        Jump('loop_test'),
    ],
    'loop_test': [
        Instr('cmpq', [Immediate(11), Variable('i')]),
        JumpIf('l', 'loop_body'),
        Jump('loop_done'),
    ],
    'loop_body': [
        Instr('addq', [Variable('i'), Variable('sum')]),
        Instr('addq', [Immediate(1), Variable('i')]),
        Jump('loop_test'),
    ],
    'loop_done': [
        Instr('movq', [Variable('sum'), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Program 5 – Single function call (print_int)
# Expected: rax = 0, output = [42]
# ---------------------------------------------------------------------------
prog_call = X86Program({
    'start': [
        Instr('movq', [Immediate(42), Variable('x')]),
        Instr('movq', [Variable('x'), Reg('rdi')]),
        Callq('print_int', 1),
        Instr('movq', [Immediate(0), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Program 6 – Variables live across a function call
# y must survive the first callq → must be in callee-saved reg
# Expected: rax = 0, output = [10, 20]
# ---------------------------------------------------------------------------
prog_call_live = X86Program({
    'start': [
        Instr('movq', [Immediate(10), Variable('x')]),
        Instr('movq', [Immediate(20), Variable('y')]),
        Instr('movq', [Variable('x'), Reg('rdi')]),
        Callq('print_int', 1),
        Instr('movq', [Variable('y'), Reg('rdi')]),
        Callq('print_int', 1),
        Instr('movq', [Immediate(0), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Program 7 – Many simultaneous variables → forces register spilling
# 12 variables (v0..v11) live simultaneously, then summed.
# With 11 allocatable registers, at least 1 spill is required.
# Expected: rax = 78, output = []
# ---------------------------------------------------------------------------
prog_spill = X86Program({
    'start': [
        Instr('movq', [Immediate(1), Variable('v0')]),
        Instr('movq', [Immediate(2), Variable('v1')]),
        Instr('movq', [Immediate(3), Variable('v2')]),
        Instr('movq', [Immediate(4), Variable('v3')]),
        Instr('movq', [Immediate(5), Variable('v4')]),
        Instr('movq', [Immediate(6), Variable('v5')]),
        Instr('movq', [Immediate(7), Variable('v6')]),
        Instr('movq', [Immediate(8), Variable('v7')]),
        Instr('movq', [Immediate(9), Variable('v8')]),
        Instr('movq', [Immediate(10), Variable('v9')]),
        Instr('movq', [Immediate(11), Variable('v10')]),
        Instr('movq', [Immediate(12), Variable('v11')]),
        Instr('movq', [Variable('v0'), Variable('total')]),
        Instr('addq', [Variable('v1'), Variable('total')]),
        Instr('addq', [Variable('v2'), Variable('total')]),
        Instr('addq', [Variable('v3'), Variable('total')]),
        Instr('addq', [Variable('v4'), Variable('total')]),
        Instr('addq', [Variable('v5'), Variable('total')]),
        Instr('addq', [Variable('v6'), Variable('total')]),
        Instr('addq', [Variable('v7'), Variable('total')]),
        Instr('addq', [Variable('v8'), Variable('total')]),
        Instr('addq', [Variable('v9'), Variable('total')]),
        Instr('addq', [Variable('v10'), Variable('total')]),
        Instr('addq', [Variable('v11'), Variable('total')]),
        Instr('movq', [Variable('total'), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Program 8 – Nested conditionals
# a=5, b=10, c=15
# a < b → outer_then: d = a+b = 15
# d == c (not less) → inner_else: result = d+c = 30
# Expected: rax = 30, output = []
# ---------------------------------------------------------------------------
prog_nested = X86Program({
    'start': [
        Instr('movq', [Immediate(5), Variable('a')]),
        Instr('movq', [Immediate(10), Variable('b')]),
        Instr('movq', [Immediate(15), Variable('c')]),
        Instr('cmpq', [Variable('b'), Variable('a')]),
        JumpIf('l', 'outer_then'),
        Jump('outer_else'),
    ],
    'outer_then': [
        Instr('movq', [Variable('a'), Variable('d')]),
        Instr('addq', [Variable('b'), Variable('d')]),
        Instr('cmpq', [Variable('c'), Variable('d')]),
        JumpIf('l', 'inner_then'),
        Jump('inner_else'),
    ],
    'inner_then': [
        Instr('movq', [Variable('c'), Variable('result')]),
        Instr('subq', [Variable('d'), Variable('result')]),
        Instr('addq', [Variable('a'), Variable('result')]),
        Jump('end'),
    ],
    'inner_else': [
        Instr('movq', [Variable('d'), Variable('result')]),
        Instr('addq', [Variable('c'), Variable('result')]),
        Jump('end'),
    ],
    'outer_else': [
        Instr('movq', [Variable('b'), Variable('result')]),
        Instr('addq', [Variable('c'), Variable('result')]),
        Jump('end'),
    ],
    'end': [
        Instr('movq', [Variable('result'), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Program 9 – Loop with function call inside
# Print 1, 2, 3, 4, 5.  i must survive each callq.
# Expected: rax = 0, output = [1, 2, 3, 4, 5]
# ---------------------------------------------------------------------------
prog_loop_call = X86Program({
    'start': [
        Instr('movq', [Immediate(1), Variable('i')]),
        Jump('lc_test'),
    ],
    'lc_test': [
        Instr('cmpq', [Immediate(6), Variable('i')]),
        JumpIf('l', 'lc_body'),
        Jump('lc_done'),
    ],
    'lc_body': [
        Instr('movq', [Variable('i'), Reg('rdi')]),
        Callq('print_int', 1),
        Instr('addq', [Immediate(1), Variable('i')]),
        Jump('lc_test'),
    ],
    'lc_done': [
        Instr('movq', [Immediate(0), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Program 10 – Fibonacci loop (20 iterations)
# a=0, b=1; 20×{c=a+b; a=b; b=c}; rax=b  → fib(22) = 10946 (shifted indexing)
# Expected: rax = 10946, output = []
# ---------------------------------------------------------------------------
prog_fib = X86Program({
    'start': [
        Instr('movq', [Immediate(0), Variable('a')]),
        Instr('movq', [Immediate(1), Variable('b')]),
        Instr('movq', [Immediate(0), Variable('cnt')]),
        Jump('fib_test'),
    ],
    'fib_test': [
        Instr('cmpq', [Immediate(20), Variable('cnt')]),
        JumpIf('l', 'fib_body'),
        Jump('fib_done'),
    ],
    'fib_body': [
        Instr('movq', [Variable('a'), Variable('c')]),
        Instr('addq', [Variable('b'), Variable('c')]),
        Instr('movq', [Variable('b'), Variable('a')]),
        Instr('movq', [Variable('c'), Variable('b')]),
        Instr('addq', [Immediate(1), Variable('cnt')]),
        Jump('fib_test'),
    ],
    'fib_done': [
        Instr('movq', [Variable('b'), Reg('rax')]),
        Jump('conclusion'),
    ],
})

# ---------------------------------------------------------------------------
# Master list – importable by tests and allocator
# ---------------------------------------------------------------------------
ALL_PROGRAMS = [
    ('simple', prog_simple),
    ('multi', prog_multi),
    ('cond', prog_cond),
    ('loop', prog_loop),
    ('call', prog_call),
    ('call_live', prog_call_live),
    ('spill', prog_spill),
    ('nested', prog_nested),
    ('loop_call', prog_loop_call),
    ('fib', prog_fib),
]
