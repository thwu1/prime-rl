"""Test programs for the register allocator.

Each program is an X86Program whose blocks use Var arguments that
must be replaced by the allocator.  ``test_cases`` is a list of
(name, program, inputs, expected_rax) tuples used for verification.
"""
from ir import Imm, Reg, Var, Instr, X86Program

# ---------------------------------------------------------------------------
# Program 1 – simple arithmetic (classic Siek textbook example)
# v=1, w=42, x=v+7=8, y=x=8, z=x+w=50, t=-y=-8, rax=z+t=42
# ---------------------------------------------------------------------------
prog_simple = X86Program({
    'start': [
        Instr('movq', [Imm(1), Var('v')]),
        Instr('movq', [Imm(42), Var('w')]),
        Instr('movq', [Var('v'), Var('x')]),
        Instr('addq', [Imm(7), Var('x')]),
        Instr('movq', [Var('x'), Var('y')]),
        Instr('movq', [Var('x'), Var('z')]),
        Instr('addq', [Var('w'), Var('z')]),
        Instr('movq', [Var('y'), Var('t')]),
        Instr('negq', [Var('t')]),
        Instr('movq', [Var('z'), Reg('rax')]),
        Instr('addq', [Var('t'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ]
})

# ---------------------------------------------------------------------------
# Program 2 – conditional branch (min of two numbers)
# cmpq y,x => x-y = 20-10 = 10 > 0 => jl NOT taken => else => rax=y=10
# ---------------------------------------------------------------------------
prog_branch = X86Program({
    'start': [
        Instr('movq', [Imm(20), Var('x')]),
        Instr('movq', [Imm(10), Var('y')]),
        Instr('cmpq', [Var('y'), Var('x')]),
        Instr('jl', ['then_block']),
        Instr('jmp', ['else_block']),
    ],
    'then_block': [
        Instr('movq', [Var('x'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
    'else_block': [
        Instr('movq', [Var('y'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
})

# ---------------------------------------------------------------------------
# Program 3 – simple loop: sum 1..10 = 55
# ---------------------------------------------------------------------------
prog_loop = X86Program({
    'start': [
        Instr('movq', [Imm(0), Var('sum')]),
        Instr('movq', [Imm(1), Var('i')]),
        Instr('jmp', ['loop_test']),
    ],
    'loop_test': [
        Instr('cmpq', [Imm(11), Var('i')]),
        Instr('jl', ['loop_body']),
        Instr('jmp', ['loop_done']),
    ],
    'loop_body': [
        Instr('addq', [Var('i'), Var('sum')]),
        Instr('addq', [Imm(1), Var('i')]),
        Instr('jmp', ['loop_test']),
    ],
    'loop_done': [
        Instr('movq', [Var('sum'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
})

# ---------------------------------------------------------------------------
# Program 4 – Fibonacci: fib(10)=55  (loop with multiple live vars)
# ---------------------------------------------------------------------------
prog_fib = X86Program({
    'start': [
        Instr('movq', [Imm(0), Var('a')]),
        Instr('movq', [Imm(1), Var('b')]),
        Instr('movq', [Imm(0), Var('i')]),
        Instr('jmp', ['fib_test']),
    ],
    'fib_test': [
        Instr('cmpq', [Imm(10), Var('i')]),
        Instr('jl', ['fib_body']),
        Instr('jmp', ['fib_done']),
    ],
    'fib_body': [
        Instr('movq', [Var('b'), Var('tmp')]),
        Instr('addq', [Var('a'), Var('b')]),
        Instr('movq', [Var('tmp'), Var('a')]),
        Instr('addq', [Imm(1), Var('i')]),
        Instr('jmp', ['fib_test']),
    ],
    'fib_done': [
        Instr('movq', [Var('a'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
})

# ---------------------------------------------------------------------------
# Program 5 – high register pressure: 15 variables, must spill
# Expected: rax = 1+2+...+15 = 120
# ---------------------------------------------------------------------------
_instrs5 = []
for _k in range(15):
    _instrs5.append(Instr('movq', [Imm(_k + 1), Var(f'v{_k}')]))
_instrs5.append(Instr('movq', [Var('v0'), Reg('rax')]))
for _k in range(1, 15):
    _instrs5.append(Instr('addq', [Var(f'v{_k}'), Reg('rax')]))
_instrs5.append(Instr('jmp', ['conclusion']))
prog_spill = X86Program({'start': _instrs5})

# ---------------------------------------------------------------------------
# Program 6 – callq clobbers caller-saved registers
# With input [7]: rax = 100 + 7 = 107
# 'saved' MUST survive the call (callee-saved reg or spill)
# ---------------------------------------------------------------------------
prog_call = X86Program({
    'start': [
        Instr('movq', [Imm(100), Var('saved')]),
        Instr('callq', ['read_int', 0]),
        Instr('movq', [Reg('rax'), Var('input_val')]),
        Instr('addq', [Var('saved'), Var('input_val')]),
        Instr('movq', [Var('input_val'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
})

# ---------------------------------------------------------------------------
# Program 7 – nested conditionals (max of three numbers)
# a=10 < b=20 < c=30 => rax = c = 30
# ---------------------------------------------------------------------------
prog_nested_cond = X86Program({
    'start': [
        Instr('movq', [Imm(10), Var('a')]),
        Instr('movq', [Imm(20), Var('b')]),
        Instr('movq', [Imm(30), Var('c')]),
        Instr('cmpq', [Var('b'), Var('a')]),
        Instr('jl', ['a_less']),
        Instr('jmp', ['a_geq']),
    ],
    'a_less': [
        Instr('cmpq', [Var('c'), Var('b')]),
        Instr('jl', ['b_less_c']),
        Instr('jmp', ['b_geq_c']),
    ],
    'a_geq': [
        Instr('movq', [Var('a'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
    'b_less_c': [
        Instr('movq', [Var('c'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
    'b_geq_c': [
        Instr('movq', [Var('b'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
})

# ---------------------------------------------------------------------------
# Program 8 – loop with conditional body: sum of odd numbers 1..9 = 25
# Uses xor to detect odd/even: if (i ^ 1) < i then i is odd.
# ---------------------------------------------------------------------------
prog_loop_cond = X86Program({
    'start': [
        Instr('movq', [Imm(0), Var('sum')]),
        Instr('movq', [Imm(1), Var('i')]),
        Instr('jmp', ['ltest']),
    ],
    'ltest': [
        Instr('cmpq', [Imm(10), Var('i')]),
        Instr('jl', ['lbody']),
        Instr('jmp', ['ldone']),
    ],
    'lbody': [
        Instr('movq', [Var('i'), Var('tmp')]),
        Instr('xorq', [Imm(1), Var('tmp')]),
        Instr('cmpq', [Var('i'), Var('tmp')]),
        Instr('jl', ['is_odd']),
        Instr('jmp', ['skip']),
    ],
    'is_odd': [
        Instr('addq', [Var('i'), Var('sum')]),
        Instr('jmp', ['skip']),
    ],
    'skip': [
        Instr('addq', [Imm(1), Var('i')]),
        Instr('jmp', ['ltest']),
    ],
    'ldone': [
        Instr('movq', [Var('sum'), Reg('rax')]),
        Instr('jmp', ['conclusion']),
    ],
})

# ---------------------------------------------------------------------------
# Exported collections for tests
# ---------------------------------------------------------------------------

test_cases = [
    ('simple', prog_simple, [], 42),
    ('branch', prog_branch, [], 10),
    ('loop', prog_loop, [], 55),
    ('fib', prog_fib, [], 55),
    ('spill', prog_spill, [], 120),
    ('call', prog_call, [7], 107),
    ('nested_cond', prog_nested_cond, [], 30),
    ('loop_cond', prog_loop_cond, [], 25),
]

all_programs = [
    ('simple', prog_simple),
    ('branch', prog_branch),
    ('loop', prog_loop),
    ('fib', prog_fib),
    ('spill', prog_spill),
    ('call', prog_call),
    ('nested_cond', prog_nested_cond),
    ('loop_cond', prog_loop_cond),
]
