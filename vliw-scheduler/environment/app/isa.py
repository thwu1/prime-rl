"""
VLIW Processor ISA Specification
=================================

A simplified VLIW (Very Long Instruction Word) processor with 4 functional units
that can execute one instruction each per cycle, in parallel.

Registers:
    Physical registers: r0 through r255 (256 total).
    All registers hold unsigned 32-bit integers (0 to 0xFFFFFFFF).
    Uninitialized registers read as 0.

Memory:
    Flat, word-addressable. Each address holds an unsigned 32-bit integer.
    Uninitialized addresses read as 0.

VLIW Semantics:
    Within a single cycle (bundle), all register reads see the values from BEFORE
    the bundle. All writes take effect at the END of the bundle. This means:
    - Two instructions in the same bundle CAN read the same register.
    - An instruction CANNOT read a value written by another instruction in the
      same bundle (it reads the old value instead).
    - Two instructions MUST NOT write to the same register in one bundle.

Functional Units:
    alu   - Integer arithmetic and logic (1 per cycle)
    load  - Constants and memory reads   (1 per cycle)
    store - Memory writes                (1 per cycle)
    flow  - Control flow and data moves  (1 per cycle)

Instruction Format:
    Each instruction is a list: [unit, op, ...args]

    ALU operations: ["alu", op, dst, src1, src2]
        op in {add, sub, mul, shr, shl, xor, and, or, cmplt, mod}
        dst = src1 OP src2 (unsigned 32-bit)
        shr/shl shift amount is masked to 0-31

    Load operations: ["load", "const", dst, immediate]
                     ["load", "load", dst, addr_reg]
        const: dst = immediate value (32-bit)
        load:  dst = memory[regs[addr_reg]]

    Store operations: ["store", "store", addr_reg, val_reg]
        memory[regs[addr_reg]] = regs[val_reg]

    Flow operations: ["flow", "halt"]
                     ["flow", "mov", dst, src]
        halt: stop execution (other instructions in the same bundle still execute)
        mov:  dst = src (register copy)

Sequential Program Format:
    A list of instructions executed one per cycle in order.

VLIW Bundle Format:
    A list of bundles. Each bundle is a list of instructions that execute in
    one cycle. Each bundle may contain at most one instruction per functional unit.
"""


MASK32 = 0xFFFFFFFF

UNITS = {"alu", "load", "store", "flow"}

ALU_OPS = {"add", "sub", "mul", "shr", "shl", "xor", "and", "or", "cmplt", "mod"}
LOAD_OPS = {"const", "load"}
STORE_OPS = {"store"}
FLOW_OPS = {"halt", "mov"}


def get_unit(instr):
    """Return the functional unit name for an instruction."""
    return instr[0]


def get_op(instr):
    """Return the operation name for an instruction."""
    return instr[1]


def get_reads_writes(instr):
    """Return (reads, writes) as sets of register numbers for an instruction.

    Does not include immediate values. Only register operands are tracked.
    """
    unit, op = instr[0], instr[1]
    args = instr[2:]
    reads, writes = set(), set()

    if unit == "alu":
        dst, src1, src2 = args
        writes.add(dst)
        reads.add(src1)
        reads.add(src2)
    elif unit == "load":
        if op == "const":
            writes.add(args[0])
        else:  # "load" from memory
            writes.add(args[0])
            reads.add(args[1])
    elif unit == "store":
        reads.add(args[0])  # addr_reg
        reads.add(args[1])  # val_reg
    elif unit == "flow":
        if op == "mov":
            writes.add(args[0])
            reads.add(args[1])
        # halt has no register operands

    return reads, writes


def is_memory_access(instr):
    """Check if instruction performs a real memory access (not const)."""
    unit, op = instr[0], instr[1]
    return (unit == "load" and op == "load") or (unit == "store")


def validate_bundle(bundle):
    """Validate that a VLIW bundle has at most one instruction per functional unit
    and no write-write conflicts.

    Returns (valid, error_message).
    """
    units_seen = set()
    writes_seen = set()

    for instr in bundle:
        unit = get_unit(instr)
        if unit in units_seen:
            return False, f"Duplicate functional unit: {unit}"
        units_seen.add(unit)

        _, writes = get_reads_writes(instr)
        overlap = writes & writes_seen
        if overlap:
            return False, f"Write-write conflict on registers: {overlap}"
        writes_seen.update(writes)

    return True, ""
