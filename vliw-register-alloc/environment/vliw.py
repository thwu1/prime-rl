"""
VLIW Machine Model and Simulator


Machine specification:
  - Registers: r0..r(N-1).  r0 is hardwired to 0 (writes ignored).
  - Memory: 256 words, 32-bit unsigned integers, word-addressed.
  - All arithmetic is unsigned 32-bit with wrapping.

Functional units per VLIW bundle (one bundle per cycle):
  Slot ALU0 : add sub and or xor shl shr slt mov li
  Slot ALU1 : (same as ALU0)
  Slot MUL  : mul muladd
  Slot MEM  : lw sw

Latencies (cycles until destination register is available):
  ALU ops : 1     MUL/MULADD : 3     LW : 4     SW : 1

Bundle semantics:
  - All reads in a bundle see register/memory values from *before* the bundle.
  - Two writes to the same physical register in one bundle (WAW) are illegal.
  - If any source register is not yet ready, the whole pipeline stalls.
"""

MASK32 = 0xFFFFFFFF
MEM_SIZE = 256

ALU_OPS = frozenset(["add", "sub", "and", "or", "xor", "shl", "shr", "slt", "mov", "li"])
MUL_OPS = frozenset(["mul", "muladd"])
MEM_OPS = frozenset(["lw", "sw"])
ALL_OPS = ALU_OPS | MUL_OPS | MEM_OPS

LATENCY = {op: 1 for op in ALU_OPS}
LATENCY.update({"mul": 3, "muladd": 3, "lw": 4, "sw": 1})


def slot_kind(op):
    if op in ALU_OPS:
        return "alu"
    if op in MUL_OPS:
        return "mul"
    if op in MEM_OPS:
        return "mem"
    raise ValueError(f"Unknown op: {op}")


# ---------------------------------------------------------------------------
# IR (virtual-register, SSA-like)
# ---------------------------------------------------------------------------

class Inst:
    """Instruction with virtual registers."""
    __slots__ = ("op", "dst", "srcs", "imm")

    def __init__(self, op, dst, srcs, imm=0):
        self.op = op
        self.dst = dst            # virtual register (-1 for sw)
        self.srcs = tuple(srcs)   # source virtual registers
        self.imm = imm & MASK32

    def __repr__(self):
        if self.op == "li":
            return f"v{self.dst} = li {self.imm:#x}"
        if self.op == "lw":
            return f"v{self.dst} = lw [v{self.srcs[0]}+{self.imm}]"
        if self.op == "sw":
            return f"sw [v{self.srcs[0]}+{self.imm}], v{self.srcs[1]}"
        if self.op == "mov":
            return f"v{self.dst} = mov v{self.srcs[0]}"
        if self.op == "muladd":
            return f"v{self.dst} = muladd v{self.srcs[0]}, v{self.srcs[1]}, v{self.srcs[2]}"
        return f"v{self.dst} = {self.op} " + ", ".join(f"v{s}" for s in self.srcs)


class Program:
    """Program with virtual registers."""
    def __init__(self, instructions, num_vregs, data_size, init_mem=None):
        self.instructions = list(instructions)
        self.num_vregs = num_vregs
        self.data_size = data_size
        self.init_mem = list(init_mem) if init_mem else [0] * MEM_SIZE
        while len(self.init_mem) < MEM_SIZE:
            self.init_mem.append(0)


# ---------------------------------------------------------------------------
# Physical-register instructions and VLIW bundles
# ---------------------------------------------------------------------------

class PhysInst:
    """Instruction with physical registers."""
    __slots__ = ("op", "dst", "srcs", "imm")

    def __init__(self, op, dst, srcs, imm=0):
        self.op = op
        self.dst = dst
        self.srcs = tuple(srcs)
        self.imm = imm & MASK32

    def __repr__(self):
        if self.op == "li":
            return f"r{self.dst} = li {self.imm:#x}"
        if self.op == "lw":
            return f"r{self.dst} = lw [r{self.srcs[0]}+{self.imm}]"
        if self.op == "sw":
            return f"sw [r{self.srcs[0]}+{self.imm}], r{self.srcs[1]}"
        if self.op == "mov":
            return f"r{self.dst} = mov r{self.srcs[0]}"
        if self.op == "muladd":
            return f"r{self.dst} = muladd r{self.srcs[0]}, r{self.srcs[1]}, r{self.srcs[2]}"
        return f"r{self.dst} = {self.op} " + ", ".join(f"r{s}" for s in self.srcs)


class VLIWBundle:
    """VLIW bundle: slots [ALU0, ALU1, MUL, MEM]."""
    __slots__ = ("alu0", "alu1", "mul", "mem")

    def __init__(self, alu0=None, alu1=None, mul=None, mem=None):
        self.alu0 = alu0
        self.alu1 = alu1
        self.mul = mul
        self.mem = mem

    def all_insts(self):
        return [i for i in (self.alu0, self.alu1, self.mul, self.mem) if i is not None]

    def __repr__(self):
        parts = []
        for name in ("alu0", "alu1", "mul", "mem"):
            inst = getattr(self, name)
            parts.append(f"{name}: {inst}" if inst else f"{name}: nop")
        return "{ " + " | ".join(parts) + " }"


class CompiledProgram:
    """Compiled VLIW program."""
    def __init__(self, bundles, num_phys_regs):
        self.bundles = list(bundles)
        self.num_phys_regs = num_phys_regs


# ---------------------------------------------------------------------------
# ALU execution
# ---------------------------------------------------------------------------

def _exec_op(op, a, b, c, imm):
    if op == "add":    return (a + b) & MASK32
    if op == "sub":    return (a - b) & MASK32
    if op == "and":    return a & b
    if op == "or":     return a | b
    if op == "xor":    return a ^ b
    if op == "shl":    return (a << (b & 31)) & MASK32
    if op == "shr":    return a >> (b & 31)
    if op == "slt":    return 1 if a < b else 0
    if op == "mov":    return a
    if op == "li":     return imm & MASK32
    if op == "mul":    return (a * b) & MASK32
    if op == "muladd": return ((a * b) + c) & MASK32
    raise ValueError(f"Unknown op: {op}")


# ---------------------------------------------------------------------------
# Sequential simulator (unlimited virtual registers)
# ---------------------------------------------------------------------------

def simulate_sequential(program):
    """Execute with unlimited virtual registers. Returns memory[0:data_size]."""
    regs = [0] * program.num_vregs
    mem = list(program.init_mem)

    for inst in program.instructions:
        s = inst.srcs
        a = regs[s[0]] if len(s) > 0 else 0
        b = regs[s[1]] if len(s) > 1 else 0
        c = regs[s[2]] if len(s) > 2 else 0

        if inst.op == "lw":
            addr = (a + inst.imm) % MEM_SIZE
            regs[inst.dst] = mem[addr]
        elif inst.op == "sw":
            addr = (a + inst.imm) % MEM_SIZE
            mem[addr] = b & MASK32
        else:
            regs[inst.dst] = _exec_op(inst.op, a, b, c, inst.imm)

    return mem[: program.data_size]


# ---------------------------------------------------------------------------
# VLIW simulator (physical registers, cycle-accurate)
# ---------------------------------------------------------------------------

def simulate_vliw(compiled, init_mem, data_size):
    """Execute compiled VLIW program. Returns (memory[0:data_size], cycle_count)."""
    nr = compiled.num_phys_regs
    regs = [0] * nr
    mem = list(init_mem)
    while len(mem) < MEM_SIZE:
        mem.append(0)

    ready_at = [0] * nr
    cycle = 0

    for bundle in compiled.bundles:
        insts = bundle.all_insts()
        if not insts:
            cycle += 1
            continue

        # Stall until all operands are ready
        max_ready = cycle
        for inst in insts:
            for src in inst.srcs:
                if 0 < src < nr and ready_at[src] > max_ready:
                    max_ready = ready_at[src]
        cycle = max_ready            # absorb stalls

        # Snapshot for read-before-write semantics
        reg_snap = list(regs)
        mem_snap = list(mem)

        for inst in insts:
            s = inst.srcs
            a = reg_snap[s[0]] if len(s) > 0 else 0
            b = reg_snap[s[1]] if len(s) > 1 else 0
            c = reg_snap[s[2]] if len(s) > 2 else 0

            if inst.op == "lw":
                addr = (a + inst.imm) % MEM_SIZE
                val = mem_snap[addr]
                if 0 < inst.dst < nr:
                    regs[inst.dst] = val
                    ready_at[inst.dst] = cycle + LATENCY["lw"]
            elif inst.op == "sw":
                addr = (a + inst.imm) % MEM_SIZE
                mem[addr] = b & MASK32
            else:
                val = _exec_op(inst.op, a, b, c, inst.imm)
                if 0 < inst.dst < nr:
                    regs[inst.dst] = val
                    ready_at[inst.dst] = cycle + LATENCY[inst.op]

        cycle += 1

    return mem[:data_size], cycle


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_compiled(compiled, max_regs):
    """Return list of error strings (empty = valid)."""
    errors = []
    if compiled.num_phys_regs > max_regs:
        errors.append(f"Uses {compiled.num_phys_regs} regs, limit {max_regs}")

    for i, bundle in enumerate(compiled.bundles):
        for name in ("alu0", "alu1", "mul", "mem"):
            inst = getattr(bundle, name)
            if inst is None:
                continue
            kind = slot_kind(inst.op)
            expected = "alu" if name.startswith("alu") else name
            if kind != expected:
                errors.append(f"Bundle {i}: {inst.op} in {name} slot (needs {kind})")

        insts = bundle.all_insts()
        dsts = [inst.dst for inst in insts if inst.dst > 0]
        if len(dsts) != len(set(dsts)):
            errors.append(f"Bundle {i}: WAW hazard")

        for inst in insts:
            if inst.dst >= compiled.num_phys_regs and inst.dst >= 0:
                errors.append(f"Bundle {i}: dst r{inst.dst} out of range")
            for s in inst.srcs:
                if s >= compiled.num_phys_regs:
                    errors.append(f"Bundle {i}: src r{s} out of range")

    return errors
