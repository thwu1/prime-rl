
"""Test programs for the register allocator, defined as X86Program instances."""

from ir import *


def make_program_1():
    """Straight-line program (from Siek's running example).
    Computes: let v=1, w=42, x=v+7, y=x, z=x+w, t=-y in z+t
    Expected result in %%rax: 42
    """
    return X86Program(blocks={
        'start': [
            Instr('movq', [Immediate(1), Var('v')]),
            Instr('movq', [Immediate(42), Var('w')]),
            Instr('movq', [Var('v'), Var('x')]),
            Instr('addq', [Immediate(7), Var('x')]),
            Instr('movq', [Var('x'), Var('y')]),
            Instr('movq', [Var('x'), Var('z')]),
            Instr('addq', [Var('w'), Var('z')]),
            Instr('movq', [Var('y'), Var('t')]),
            Instr('negq', [Var('t')]),
            Instr('movq', [Var('z'), Reg('rax')]),
            Instr('addq', [Var('t'), Reg('rax')]),
            Jump('conclusion'),
        ]
    })


def make_program_2():
    """Diamond CFG (conditional branching with merge).
    a=10, b=20. If a < b: c = a + b, else: c = b - a.
    Since 10 < 20, takes then-branch: c = 30.
    Expected result: 30
    """
    return X86Program(blocks={
        'start': [
            Instr('movq', [Immediate(10), Var('a')]),
            Instr('movq', [Immediate(20), Var('b')]),
            Instr('cmpq', [Var('b'), Var('a')]),
            JumpIf('l', 'then_block'),
            Jump('else_block'),
        ],
        'then_block': [
            Instr('movq', [Var('a'), Var('c')]),
            Instr('addq', [Var('b'), Var('c')]),
            Jump('merge'),
        ],
        'else_block': [
            Instr('movq', [Var('b'), Var('c')]),
            Instr('subq', [Var('a'), Var('c')]),
            Jump('merge'),
        ],
        'merge': [
            Instr('movq', [Var('c'), Reg('rax')]),
            Jump('conclusion'),
        ],
    })


def make_program_3():
    """Loop program requiring fixed-point liveness iteration.
    sum=0, i=5. While i != 0: sum += i, i -= 1.
    Expected result: 15 (= 5+4+3+2+1)
    """
    return X86Program(blocks={
        'start': [
            Instr('movq', [Immediate(0), Var('sum')]),
            Instr('movq', [Immediate(5), Var('i')]),
            Jump('loop_header'),
        ],
        'loop_header': [
            Instr('cmpq', [Immediate(0), Var('i')]),
            JumpIf('e', 'done'),
            Jump('loop_body'),
        ],
        'loop_body': [
            Instr('addq', [Var('i'), Var('sum')]),
            Instr('subq', [Immediate(1), Var('i')]),
            Jump('loop_header'),
        ],
        'done': [
            Instr('movq', [Var('sum'), Reg('rax')]),
            Jump('conclusion'),
        ],
    })


def make_program_4():
    """High register pressure: 13 simultaneously-live variables.
    With 12 allocatable registers, at least one variable must spill to stack.
    Computes 1+2+...+13 = 91.
    """
    return X86Program(blocks={
        'start': [
            Instr('movq', [Immediate(1), Var('a')]),
            Instr('movq', [Immediate(2), Var('b')]),
            Instr('movq', [Immediate(3), Var('c')]),
            Instr('movq', [Immediate(4), Var('d')]),
            Instr('movq', [Immediate(5), Var('e')]),
            Instr('movq', [Immediate(6), Var('f')]),
            Instr('movq', [Immediate(7), Var('g')]),
            Instr('movq', [Immediate(8), Var('h')]),
            Instr('movq', [Immediate(9), Var('ii')]),
            Instr('movq', [Immediate(10), Var('j')]),
            Instr('movq', [Immediate(11), Var('k')]),
            Instr('movq', [Immediate(12), Var('l')]),
            Instr('movq', [Immediate(13), Var('m')]),
            Instr('movq', [Var('a'), Reg('rax')]),
            Instr('addq', [Var('b'), Reg('rax')]),
            Instr('addq', [Var('c'), Reg('rax')]),
            Instr('addq', [Var('d'), Reg('rax')]),
            Instr('addq', [Var('e'), Reg('rax')]),
            Instr('addq', [Var('f'), Reg('rax')]),
            Instr('addq', [Var('g'), Reg('rax')]),
            Instr('addq', [Var('h'), Reg('rax')]),
            Instr('addq', [Var('ii'), Reg('rax')]),
            Instr('addq', [Var('j'), Reg('rax')]),
            Instr('addq', [Var('k'), Reg('rax')]),
            Instr('addq', [Var('l'), Reg('rax')]),
            Instr('addq', [Var('m'), Reg('rax')]),
            Jump('conclusion'),
        ]
    })


def make_program_5():
    """Program with a function call. Tests caller-saved register clobbering.
    a=100, b=200, call print_int(a), result = b + a.
    Both a and b live across callq -> must be in callee-saved regs or stack.
    Expected result: 300
    """
    return X86Program(blocks={
        'start': [
            Instr('movq', [Immediate(100), Var('a')]),
            Instr('movq', [Immediate(200), Var('b')]),
            Instr('movq', [Var('a'), Reg('rdi')]),
            Callq('print_int', 1),
            Instr('movq', [Var('b'), Reg('rax')]),
            Instr('addq', [Var('a'), Reg('rax')]),
            Jump('conclusion'),
        ]
    })


def make_program_6():
    """Move biasing test. v -> w -> x via movq chain.
    None of v, w, x are simultaneously live, so they can share a register.
    Move biasing should assign them the same color.
    Expected result: 42
    """
    return X86Program(blocks={
        'start': [
            Instr('movq', [Immediate(1), Var('v')]),
            Instr('movq', [Var('v'), Var('w')]),
            Instr('movq', [Var('w'), Var('x')]),
            Instr('addq', [Immediate(41), Var('x')]),
            Instr('movq', [Var('x'), Reg('rax')]),
            Jump('conclusion'),
        ]
    })


ALL_PROGRAMS = [
    ('program_1', make_program_1, 42),
    ('program_2', make_program_2, 30),
    ('program_3', make_program_3, 15),
    ('program_4', make_program_4, 91),
    ('program_5', make_program_5, 300),
    ('program_6', make_program_6, 42),
]
