"""X86-64 IR with virtual variables for register allocation."""


class Imm:
    """Immediate integer value."""
    __slots__ = ('val',)

    def __init__(self, val):
        self.val = val

    def __eq__(self, o):
        return type(o) is Imm and self.val == o.val

    def __hash__(self):
        return hash(('I', self.val))

    def __repr__(self):
        return f'Imm({self.val})'


class Reg:
    """Physical register."""
    __slots__ = ('name',)

    def __init__(self, name):
        self.name = name

    def __eq__(self, o):
        return type(o) is Reg and self.name == o.name

    def __hash__(self):
        return hash(('R', self.name))

    def __repr__(self):
        return f'Reg({self.name!r})'


class Var:
    """Virtual variable (to be replaced by register allocation)."""
    __slots__ = ('name',)

    def __init__(self, name):
        self.name = name

    def __eq__(self, o):
        return type(o) is Var and self.name == o.name

    def __hash__(self):
        return hash(('V', self.name))

    def __repr__(self):
        return f'Var({self.name!r})'


class Deref:
    """Memory dereference: offset(%reg)."""
    __slots__ = ('reg', 'offset')

    def __init__(self, reg, offset):
        self.reg = reg
        self.offset = offset

    def __eq__(self, o):
        return type(o) is Deref and self.reg == o.reg and self.offset == o.offset

    def __hash__(self):
        return hash(('D', self.reg, self.offset))

    def __repr__(self):
        return f'Deref({self.reg!r}, {self.offset})'


class Instr:
    """X86-64 instruction with opcode and argument list."""
    __slots__ = ('op', 'args')

    def __init__(self, op, args):
        self.op = op
        self.args = list(args)

    def __repr__(self):
        return f'Instr({self.op!r}, {self.args})'


class X86Program:
    """X86-64 program as a control-flow graph of basic blocks.

    Attributes:
        blocks: dict mapping label (str) to list of Instr.
                Execution starts at 'start'. Jumping to 'conclusion'
                terminates the program with rax as the result.
        stack_space: bytes of stack needed for spilled variables (set
                     by the register allocator, must be 16-byte aligned).
    """

    def __init__(self, blocks, stack_space=0):
        self.blocks = dict(blocks)
        self.stack_space = stack_space


# ---------------------------------------------------------------------------
# Register sets
# ---------------------------------------------------------------------------

CALLER_SAVED = ['rax', 'rcx', 'rdx', 'rsi', 'rdi',
                'r8', 'r9', 'r10', 'r11']

CALLEE_SAVED = ['rbx', 'r12', 'r13', 'r14', 'r15']

ALLOCATABLE = ['rbx', 'rcx', 'rdx', 'rsi', 'rdi',
               'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14']

ARG_REGS = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']

# ---------------------------------------------------------------------------
# Instruction analysis helpers
# ---------------------------------------------------------------------------


def reads_of(instr):
    """Return set of Reg/Var locations read by *instr*."""
    op, args = instr.op, instr.args
    s = set()
    if op == 'movq':
        if isinstance(args[0], (Reg, Var)):
            s.add(args[0])
    elif op in ('addq', 'subq', 'xorq'):
        if isinstance(args[0], (Reg, Var)):
            s.add(args[0])
        if isinstance(args[1], (Reg, Var)):
            s.add(args[1])
    elif op == 'negq':
        if isinstance(args[0], (Reg, Var)):
            s.add(args[0])
    elif op == 'cmpq':
        if isinstance(args[0], (Reg, Var)):
            s.add(args[0])
        if isinstance(args[1], (Reg, Var)):
            s.add(args[1])
    elif op == 'movzbq':
        if isinstance(args[0], (Reg, Var)):
            s.add(args[0])
    elif op == 'callq':
        arity = args[1] if len(args) > 1 else 0
        for i in range(min(arity, len(ARG_REGS))):
            s.add(Reg(ARG_REGS[i]))
    elif op == 'retq':
        s.add(Reg('rax'))
    return s


def writes_of(instr):
    """Return set of Reg/Var locations written by *instr*."""
    op, args = instr.op, instr.args
    s = set()
    if op == 'movq':
        if isinstance(args[1], (Reg, Var)):
            s.add(args[1])
    elif op in ('addq', 'subq', 'xorq'):
        if isinstance(args[1], (Reg, Var)):
            s.add(args[1])
    elif op == 'negq':
        if isinstance(args[0], (Reg, Var)):
            s.add(args[0])
    elif op == 'movzbq':
        if isinstance(args[1], (Reg, Var)):
            s.add(args[1])
    elif op.startswith('set'):
        if isinstance(args[0], (Reg, Var)):
            s.add(args[0])
    elif op == 'callq':
        for r in CALLER_SAVED:
            s.add(Reg(r))
    return s


def block_successors(instrs):
    """Return successor labels (strings) of a basic block."""
    succs = []
    for instr in instrs:
        if instr.op == 'jmp':
            succs.append(instr.args[0])
        elif instr.op in ('je', 'jne', 'jl', 'jle', 'jg', 'jge'):
            succs.append(instr.args[0])
    return succs
