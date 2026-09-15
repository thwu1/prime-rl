"""
Simple emulator for pseudo-x86 programs (post register-allocation).
All Variable operands must have been replaced before emulation.
"""
from ir import Immediate, Register, Variable, Deref, Instr, Callq, Jump, JumpIf

MASK64 = 0xFFFFFFFFFFFFFFFF
SIGN_BIT = 0x8000000000000000
ALL_REGS = [
    "rax", "rbx", "rcx", "rdx", "rsi", "rdi",
    "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
    "rsp", "rbp",
]


def _to_signed(v):
    v &= MASK64
    return v - (1 << 64) if v >= SIGN_BIT else v


def emulate(program, inputs=None, stack_size=0):
    """
    Run *program* and return a list of integers that were printed.

    *stack_size*: bytes reserved below rbp for spilled variables.
    *inputs*: list of ints returned by successive ``read_int`` calls.
    """
    if inputs is None:
        inputs = []

    regs = {r: 0 for r in ALL_REGS}
    regs["rsp"] = 0x7FFFFFFFE000
    regs["rbp"] = regs["rsp"]
    regs["rsp"] -= stack_size

    mem = {}
    output = []
    inp_idx = [0]
    # flags from cmpq: we store the *result* of (arg2 - arg1)
    cmp_result = [0]

    def read(arg):
        if isinstance(arg, Immediate):
            return arg.value
        if isinstance(arg, Register):
            return regs[arg.name]
        if isinstance(arg, Deref):
            return mem.get(regs[arg.reg] + arg.offset, 0)
        raise RuntimeError(f"Cannot read {arg!r}")

    def write(arg, val):
        if isinstance(arg, Register):
            regs[arg.name] = _to_signed(val)
        elif isinstance(arg, Deref):
            mem[regs[arg.reg] + arg.offset] = _to_signed(val)
        else:
            raise RuntimeError(f"Cannot write to {arg!r}")

    def cc_true(cc):
        r = cmp_result[0]
        if cc == "e":   return r == 0
        if cc == "ne":  return r != 0
        if cc == "l":   return r < 0
        if cc == "le":  return r <= 0
        if cc == "g":   return r > 0
        if cc == "ge":  return r >= 0
        raise RuntimeError(f"Unknown cc: {cc}")

    cur = "start"
    steps = 0
    while cur != "conclusion":
        if cur not in program.blocks:
            raise RuntimeError(f"Missing block: {cur}")
        instrs = program.blocks[cur]
        pc = 0
        while pc < len(instrs):
            steps += 1
            if steps > 500_000:
                raise RuntimeError("Exceeded 500 000 steps")
            ins = instrs[pc]

            if isinstance(ins, Jump):
                cur = ins.label
                break

            if isinstance(ins, JumpIf):
                if cc_true(ins.cc):
                    cur = ins.label
                    break
                pc += 1
                continue

            if isinstance(ins, Callq):
                if ins.func == "print_int":
                    output.append(_to_signed(regs["rdi"]))
                elif ins.func == "read_int":
                    if inp_idx[0] >= len(inputs):
                        raise RuntimeError("No more inputs for read_int")
                    regs["rax"] = inputs[inp_idx[0]]
                    inp_idx[0] += 1
                pc += 1
                continue

            if isinstance(ins, Instr):
                n, a = ins.name, ins.args
                if n == "movq":
                    write(a[1], read(a[0]))
                elif n == "addq":
                    write(a[1], read(a[1]) + read(a[0]))
                elif n == "subq":
                    write(a[1], read(a[1]) - read(a[0]))
                elif n == "negq":
                    write(a[0], -read(a[0]))
                elif n == "xorq":
                    write(a[1], read(a[1]) ^ read(a[0]))
                elif n == "cmpq":
                    cmp_result[0] = _to_signed((read(a[1]) - read(a[0])) & MASK64)
                elif n == "movzbq":
                    write(a[1], read(a[0]) & 0xFF)
                else:
                    raise RuntimeError(f"Unknown instruction: {n}")
                pc += 1
                continue

            raise RuntimeError(f"Unknown instruction type: {ins!r}")
        else:
            raise RuntimeError(f"Block {cur} has no terminator")

    return output
