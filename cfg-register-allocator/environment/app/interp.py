"""Reference interpreter for X86-64 IR programs."""
from ir import Imm, Reg, Var, Deref


def interp(program, inputs=None):
    """Execute an X86Program and return the value in rax at conclusion.

    The interpreter supports both pre-allocation programs (with Var args)
    and post-allocation programs (with Reg/Deref args).

    Args:
        program: X86Program instance.
        inputs: list of ints fed to ``callq read_int`` calls (FIFO order).

    Returns:
        Integer value of rax when ``jmp conclusion`` is reached.
    """
    if inputs is None:
        inputs = []
    inp_idx = [0]

    regs = {}
    for r in ('rax', 'rbx', 'rcx', 'rdx', 'rsi', 'rdi',
              'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15',
              'rsp', 'rbp', 'al'):
        regs[r] = 0
    regs['rsp'] = 100000
    regs['rbp'] = 100000
    mem = {}
    env = {}
    flags = [None]

    def clip(v):
        """Signed 64-bit wrap."""
        return ((v + (1 << 63)) % (1 << 64)) - (1 << 63)

    def rd(a):
        if isinstance(a, Imm):
            return a.val
        if isinstance(a, Reg):
            return regs.get(a.name, 0)
        if isinstance(a, Var):
            return env.get(a.name, 0)
        if isinstance(a, Deref):
            return mem.get(regs[a.reg] + a.offset, 0)
        return 0

    def wr(a, v):
        v = clip(v)
        if isinstance(a, Reg):
            regs[a.name] = v
        elif isinstance(a, Var):
            env[a.name] = v
        elif isinstance(a, Deref):
            mem[regs[a.reg] + a.offset] = v

    def check_cc(cc):
        f = flags[0]
        if cc == 'e':
            return f == 'e'
        if cc == 'ne':
            return f != 'e'
        if cc == 'l':
            return f == 'l'
        if cc == 'le':
            return f in ('l', 'e')
        if cc == 'g':
            return f == 'g'
        if cc == 'ge':
            return f in ('g', 'e')
        return False

    def run(label):
        if label == 'conclusion':
            return regs['rax']
        instrs = program.blocks[label]
        for ins in instrs:
            op = ins.op
            a = ins.args
            if op == 'movq':
                wr(a[1], rd(a[0]))
            elif op == 'addq':
                wr(a[1], clip(rd(a[0]) + rd(a[1])))
            elif op == 'subq':
                wr(a[1], clip(rd(a[1]) - rd(a[0])))
            elif op == 'negq':
                wr(a[0], clip(-rd(a[0])))
            elif op == 'xorq':
                wr(a[1], clip(rd(a[0]) ^ rd(a[1])))
            elif op == 'cmpq':
                d = clip(rd(a[1]) - rd(a[0]))
                if d == 0:
                    flags[0] = 'e'
                elif d < 0:
                    flags[0] = 'l'
                else:
                    flags[0] = 'g'
            elif op == 'movzbq':
                wr(a[1], rd(a[0]) & 0xFF)
            elif op.startswith('set'):
                wr(a[0], 1 if check_cc(op[3:]) else 0)
            elif op == 'jmp':
                return run(a[0])
            elif op in ('je', 'jne', 'jl', 'jle', 'jg', 'jge'):
                if check_cc(op[1:]):
                    return run(a[0])
            elif op == 'callq':
                fn = a[0]
                if fn == 'read_int':
                    regs['rax'] = inputs[inp_idx[0]] if inp_idx[0] < len(inputs) else 0
                    inp_idx[0] += 1
                # Clobber caller-saved registers (except rax which holds return value)
                for r in ('rcx', 'rdx', 'rsi', 'rdi',
                           'r8', 'r9', 'r10', 'r11'):
                    regs[r] = -999999
            elif op == 'retq':
                return regs['rax']
        return regs['rax']

    return run('start')
