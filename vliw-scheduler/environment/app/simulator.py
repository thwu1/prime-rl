"""
VLIW Machine Simulator
======================

Provides sequential and VLIW execution of programs conforming to the ISA
specification in isa.py.
"""


MASK32 = 0xFFFFFFFF


def _exec_alu(op, v1, v2):
    """Execute an ALU operation on two unsigned 32-bit values."""
    if op == "add":
        return (v1 + v2) & MASK32
    elif op == "sub":
        return (v1 - v2) & MASK32
    elif op == "mul":
        return (v1 * v2) & MASK32
    elif op == "shr":
        return (v1 >> (v2 & 31)) & MASK32
    elif op == "shl":
        return (v1 << (v2 & 31)) & MASK32
    elif op == "xor":
        return v1 ^ v2
    elif op == "and":
        return v1 & v2
    elif op == "or":
        return v1 | v2
    elif op == "cmplt":
        return 1 if v1 < v2 else 0
    elif op == "mod":
        return (v1 % v2) & MASK32 if v2 != 0 else 0
    else:
        raise ValueError(f"Unknown ALU op: {op}")


def run_sequential(instructions, memory_init=None):
    """Run a program sequentially (one instruction per cycle).

    Args:
        instructions: List of instructions, each a list [unit, op, ...args].
        memory_init: Optional dict {address: value} of initial memory.

    Returns:
        (memory, cycles) where memory is a dict of final memory state and
        cycles is the number of cycles executed.
    """
    regs = {}  # sparse register file, default 0
    memory = dict(memory_init) if memory_init else {}
    cycles = 0

    for instr in instructions:
        unit, op = instr[0], instr[1]
        args = instr[2:]
        halted = False

        if unit == "alu":
            dst, src1, src2 = args
            v1 = regs.get(src1, 0)
            v2 = regs.get(src2, 0)
            regs[dst] = _exec_alu(op, v1, v2)

        elif unit == "load":
            if op == "const":
                dst, imm = args
                regs[dst] = imm & MASK32
            elif op == "load":
                dst, addr_reg = args
                addr = regs.get(addr_reg, 0)
                regs[dst] = memory.get(addr, 0)

        elif unit == "store":
            addr_reg, val_reg = args
            addr = regs.get(addr_reg, 0)
            memory[addr] = regs.get(val_reg, 0)

        elif unit == "flow":
            if op == "halt":
                halted = True
            elif op == "mov":
                dst, src = args
                regs[dst] = regs.get(src, 0)

        cycles += 1
        if halted:
            break

    return memory, cycles


def run_vliw(bundles, memory_init=None):
    """Run a VLIW program (multiple instructions per cycle).

    VLIW semantics: all reads within a bundle see the register/memory state
    from BEFORE the bundle. All writes take effect at the END of the bundle.

    Args:
        bundles: List of bundles. Each bundle is a list of instructions.
        memory_init: Optional dict {address: value} of initial memory.

    Returns:
        (memory, cycles) where memory is a dict of final memory state and
        cycles is the number of cycles executed.
    """
    regs = {}  # sparse register file, default 0
    memory = dict(memory_init) if memory_init else {}
    cycles = 0

    for bundle in bundles:
        # Snapshot register and memory state for reads
        old_regs = dict(regs)
        old_memory = dict(memory)

        reg_writes = {}
        mem_writes = {}
        halted = False

        for instr in bundle:
            unit, op = instr[0], instr[1]
            args = instr[2:]

            if unit == "alu":
                dst, src1, src2 = args
                v1 = old_regs.get(src1, 0)
                v2 = old_regs.get(src2, 0)
                reg_writes[dst] = _exec_alu(op, v1, v2)

            elif unit == "load":
                if op == "const":
                    dst, imm = args
                    reg_writes[dst] = imm & MASK32
                elif op == "load":
                    dst, addr_reg = args
                    addr = old_regs.get(addr_reg, 0)
                    reg_writes[dst] = old_memory.get(addr, 0)

            elif unit == "store":
                addr_reg, val_reg = args
                addr = old_regs.get(addr_reg, 0)
                val = old_regs.get(val_reg, 0)
                mem_writes[addr] = val

            elif unit == "flow":
                if op == "halt":
                    halted = True
                elif op == "mov":
                    dst, src = args
                    reg_writes[dst] = old_regs.get(src, 0)

        # Apply writes
        regs.update(reg_writes)
        memory.update(mem_writes)
        cycles += 1

        if halted:
            break

    return memory, cycles
