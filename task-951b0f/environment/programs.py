"""Test programs expressed as pseudo-x86-64 CFGs with virtual registers.

Each ``program_*`` function returns ``(cfg, inputs, expected_outputs)`` where
*inputs* is the list of integers that ``read_int`` will consume and
*expected_outputs* is the list of integers that ``print_int`` should produce.

"""
from ir import VReg, PReg, Imm, Instr, Block, CFG


# ---------------------------------------------------------------------------
# 1. Trivial: read one value and echo it
# ---------------------------------------------------------------------------
def program_simple():
    """Input: [42]  ->  Output: [42]"""
    cfg = CFG(blocks={
        'start': Block('start', [
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('x')]),
            Instr('movq',  [VReg('x'), PReg('rdi')]),
            Instr('callq', ['print_int']),
            Instr('movq',  [Imm(0), PReg('rax')]),
            Instr('retq',  []),
        ]),
    }, entry='start')
    return cfg, [42], [42]


# ---------------------------------------------------------------------------
# 2. Arithmetic – variable live across a call
# ---------------------------------------------------------------------------
def program_arithmetic():
    """a=10, b=3  ->  c=a+b=13, d=a-b=7, e=c+d=20.  Output: [20]

    v_a is live across the second ``callq read_int``, forcing it into a
    callee-saved register or a stack slot.
    """
    cfg = CFG(blocks={
        'start': Block('start', [
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('a')]),
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('b')]),
            Instr('movq',  [VReg('a'), VReg('c')]),
            Instr('addq',  [VReg('b'), VReg('c')]),
            Instr('movq',  [VReg('a'), VReg('d')]),
            Instr('subq',  [VReg('b'), VReg('d')]),
            Instr('movq',  [VReg('c'), VReg('e')]),
            Instr('addq',  [VReg('d'), VReg('e')]),
            Instr('movq',  [VReg('e'), PReg('rdi')]),
            Instr('callq', ['print_int']),
            Instr('movq',  [Imm(0), PReg('rax')]),
            Instr('retq',  []),
        ]),
    }, entry='start')
    return cfg, [10, 3], [20]


# ---------------------------------------------------------------------------
# 3. Diamond CFG – if / else
# ---------------------------------------------------------------------------
def program_conditional():
    """if x>0: y=x+1  else: y=-x.   Input: [5] -> [6]"""
    cfg = CFG(blocks={
        'start': Block('start', [
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('x')]),
            Instr('cmpq',  [Imm(0), VReg('x')]),
            Instr('jg',    ['then']),
            Instr('jmp',   ['else_']),
        ]),
        'then': Block('then', [
            Instr('movq', [VReg('x'), VReg('y')]),
            Instr('addq', [Imm(1), VReg('y')]),
            Instr('jmp',  ['end']),
        ]),
        'else_': Block('else_', [
            Instr('movq', [Imm(0), VReg('y')]),
            Instr('subq', [VReg('x'), VReg('y')]),
            Instr('jmp',  ['end']),
        ]),
        'end': Block('end', [
            Instr('movq',  [VReg('y'), PReg('rdi')]),
            Instr('callq', ['print_int']),
            Instr('movq',  [Imm(0), PReg('rax')]),
            Instr('retq',  []),
        ]),
    }, entry='start')
    return cfg, [5], [6]


# ---------------------------------------------------------------------------
# 4. Loop – back edge requires iterative liveness analysis
# ---------------------------------------------------------------------------
def program_loop():
    """sum = 0+1+…+(n-1).  Input: [5] -> [10]"""
    cfg = CFG(blocks={
        'start': Block('start', [
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('n')]),
            Instr('movq',  [Imm(0), VReg('sum')]),
            Instr('movq',  [Imm(0), VReg('i')]),
            Instr('jmp',   ['loop_test']),
        ]),
        'loop_test': Block('loop_test', [
            Instr('cmpq', [VReg('n'), VReg('i')]),
            Instr('jl',   ['loop_body']),
            Instr('jmp',  ['loop_end']),
        ]),
        'loop_body': Block('loop_body', [
            Instr('addq', [VReg('i'), VReg('sum')]),
            Instr('addq', [Imm(1), VReg('i')]),
            Instr('jmp',  ['loop_test']),
        ]),
        'loop_end': Block('loop_end', [
            Instr('movq',  [VReg('sum'), PReg('rdi')]),
            Instr('callq', ['print_int']),
            Instr('movq',  [Imm(0), PReg('rax')]),
            Instr('retq',  []),
        ]),
    }, entry='start')
    return cfg, [5], [10]


# ---------------------------------------------------------------------------
# 5. Nested conditionals
# ---------------------------------------------------------------------------
def program_nested_conditional():
    """if x>5: if y>2: z=x+y  else: z=x-y  else: z=0.
    Input: [10, 3] -> [13]
    """
    cfg = CFG(blocks={
        'start': Block('start', [
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('x')]),
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('y')]),
            Instr('cmpq',  [Imm(5), VReg('x')]),
            Instr('jg',    ['outer_then']),
            Instr('jmp',   ['outer_else']),
        ]),
        'outer_then': Block('outer_then', [
            Instr('cmpq', [Imm(2), VReg('y')]),
            Instr('jg',   ['inner_then']),
            Instr('jmp',  ['inner_else']),
        ]),
        'inner_then': Block('inner_then', [
            Instr('movq', [VReg('x'), VReg('z')]),
            Instr('addq', [VReg('y'), VReg('z')]),
            Instr('jmp',  ['end']),
        ]),
        'inner_else': Block('inner_else', [
            Instr('movq', [VReg('x'), VReg('z')]),
            Instr('subq', [VReg('y'), VReg('z')]),
            Instr('jmp',  ['end']),
        ]),
        'outer_else': Block('outer_else', [
            Instr('movq', [Imm(0), VReg('z')]),
            Instr('jmp',  ['end']),
        ]),
        'end': Block('end', [
            Instr('movq',  [VReg('z'), PReg('rdi')]),
            Instr('callq', ['print_int']),
            Instr('movq',  [Imm(0), PReg('rax')]),
            Instr('retq',  []),
        ]),
    }, entry='start')
    return cfg, [10, 3], [13]


# ---------------------------------------------------------------------------
# 6. High register pressure – requires spilling
# ---------------------------------------------------------------------------
def program_pressure():
    """16 simultaneously-live variables (> 14 allocatable registers).
    a=input, b=a+1, c=b+1, …, p=o+1.  result = a+b+…+p = 1+2+…+16 = 136.
    Input: [1] -> [136]
    """
    instrs = [
        Instr('callq', ['read_int']),
        Instr('movq',  [PReg('rax'), VReg('a')]),
    ]
    names = list('bcdefghijklmnop')            # 15 more variables
    for i, name in enumerate(names):
        prev = chr(ord('a') + i)
        instrs.append(Instr('movq', [VReg(prev), VReg(name)]))
        instrs.append(Instr('addq', [Imm(1), VReg(name)]))

    # All 16 variables are live at this point.
    instrs.append(Instr('movq', [VReg('a'), VReg('result')]))
    for name in names:
        instrs.append(Instr('addq', [VReg(name), VReg('result')]))

    instrs += [
        Instr('movq',  [VReg('result'), PReg('rdi')]),
        Instr('callq', ['print_int']),
        Instr('movq',  [Imm(0), PReg('rax')]),
        Instr('retq',  []),
    ]
    cfg = CFG(blocks={'start': Block('start', instrs)}, entry='start')
    return cfg, [1], [136]


# ---------------------------------------------------------------------------
# 7. Loop with two accumulators + variable live across call
# ---------------------------------------------------------------------------
def program_loop_multi():
    """sum=Σi, sumsq=Σi² for i in 0..n-1.
    Input: [5] -> [10, 30]

    v_sumsq is live across ``callq print_int`` inside the done block,
    stressing caller-saved / callee-saved handling.
    """
    cfg = CFG(blocks={
        'start': Block('start', [
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('n')]),
            Instr('movq',  [Imm(0), VReg('sum')]),
            Instr('movq',  [Imm(0), VReg('sumsq')]),
            Instr('movq',  [Imm(0), VReg('i')]),
            Instr('jmp',   ['test']),
        ]),
        'test': Block('test', [
            Instr('cmpq', [VReg('n'), VReg('i')]),
            Instr('jl',   ['body']),
            Instr('jmp',  ['done']),
        ]),
        'body': Block('body', [
            Instr('addq',  [VReg('i'), VReg('sum')]),
            Instr('movq',  [VReg('i'), VReg('tmp')]),
            Instr('imulq', [VReg('i'), VReg('tmp')]),
            Instr('addq',  [VReg('tmp'), VReg('sumsq')]),
            Instr('addq',  [Imm(1), VReg('i')]),
            Instr('jmp',   ['test']),
        ]),
        'done': Block('done', [
            Instr('movq',  [VReg('sum'), PReg('rdi')]),
            Instr('callq', ['print_int']),
            Instr('movq',  [VReg('sumsq'), PReg('rdi')]),
            Instr('callq', ['print_int']),
            Instr('movq',  [Imm(0), PReg('rax')]),
            Instr('retq',  []),
        ]),
    }, entry='start')
    return cfg, [5], [10, 30]


# ---------------------------------------------------------------------------
# 8. Cross-call liveness with three reads
# ---------------------------------------------------------------------------
def program_three_calls():
    """Reads a, b, c (three successive calls), prints a+b+c.
    a and b must survive across later calls.
    Input: [100, 200, 300] -> [600]
    """
    cfg = CFG(blocks={
        'start': Block('start', [
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('a')]),
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('b')]),
            Instr('callq', ['read_int']),
            Instr('movq',  [PReg('rax'), VReg('c')]),
            Instr('movq',  [VReg('a'), VReg('s')]),
            Instr('addq',  [VReg('b'), VReg('s')]),
            Instr('addq',  [VReg('c'), VReg('s')]),
            Instr('movq',  [VReg('s'), PReg('rdi')]),
            Instr('callq', ['print_int']),
            Instr('movq',  [Imm(0), PReg('rax')]),
            Instr('retq',  []),
        ]),
    }, entry='start')
    return cfg, [100, 200, 300], [600]
