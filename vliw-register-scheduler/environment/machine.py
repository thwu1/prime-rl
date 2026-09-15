"""VLIW Machine Simulator

Defines the instruction set, VLIW constraints, and machine simulator
for a simple VLIW (Very Long Instruction Word) architecture.

Instruction format (dict):
    {"op": str, "dst": int, "srcs": list[int], "imm": int (optional)}

    - op: opcode string (see OPCODES)
    - dst: destination register number (-1 for ops with no destination)
    - srcs: list of source register numbers
    - imm: immediate value (only for "const" opcode)

VLIW Bundle:
    A list of instructions that execute simultaneously in one cycle.
    All source registers are read BEFORE any destination registers are written.

Constraints per bundle:
    - At most 2 ALU instructions
    - At most 1 MEM instruction (load or store)
    - At most 1 FLOW instruction
    - No two instructions may write to the same register (WAW hazard)
"""


OPCODES = {
    # ALU operations (unit: "alu") - up to 2 per bundle
    "add":    {"unit": "alu"},
    "sub":    {"unit": "alu"},
    "mul":    {"unit": "alu"},
    "xor":    {"unit": "alu"},
    "and":    {"unit": "alu"},
    "or":     {"unit": "alu"},
    "shl":    {"unit": "alu"},
    "shr":    {"unit": "alu"},
    "cmplt":  {"unit": "alu"},
    "const":  {"unit": "alu"},
    # Memory operations (unit: "mem") - up to 1 per bundle
    "load":   {"unit": "mem"},
    "store":  {"unit": "mem"},
    # Flow operations (unit: "flow") - up to 1 per bundle
    "select": {"unit": "flow"},
    "mov":    {"unit": "flow"},
    "halt":   {"unit": "flow"},
}

# Maximum instructions per functional unit per VLIW bundle
UNIT_SLOTS = {"alu": 2, "mem": 1, "flow": 1}


def get_unit(op):
    """Get the functional unit for an opcode."""
    return OPCODES[op]["unit"]


def mask32(x):
    """Mask to unsigned 32-bit integer."""
    return x & 0xFFFFFFFF


def execute_op(op, src_vals, imm, mem):
    """Execute a single instruction.

    Returns (result_value, mem_write_or_None).
    mem_write is a tuple (addr, value) for store operations, None otherwise.
    result_value is None for store and halt.
    """
    if op == "add":    return mask32(src_vals[0] + src_vals[1]), None
    if op == "sub":    return mask32(src_vals[0] - src_vals[1]), None
    if op == "mul":    return mask32(src_vals[0] * src_vals[1]), None
    if op == "xor":    return src_vals[0] ^ src_vals[1], None
    if op == "and":    return src_vals[0] & src_vals[1], None
    if op == "or":     return src_vals[0] | src_vals[1], None
    if op == "shl":    return mask32(src_vals[0] << (src_vals[1] & 31)), None
    if op == "shr":    return (src_vals[0] >> (src_vals[1] & 31)), None
    if op == "cmplt":  return int(src_vals[0] < src_vals[1]), None
    if op == "const":  return mask32(imm), None
    if op == "load":   return mem.get(src_vals[0], 0), None
    if op == "store":  return None, (src_vals[0], mask32(src_vals[1]))
    if op == "select": return src_vals[1] if src_vals[0] else src_vals[2], None
    if op == "mov":    return src_vals[0], None
    if op == "halt":   return None, None
    raise ValueError(f"Unknown opcode: {op}")


def validate_bundle(bundle):
    """Validate a VLIW bundle respects architectural constraints.

    Returns (is_valid: bool, message: str).
    """
    unit_counts = {}
    dsts = []
    for inst in bundle:
        unit = get_unit(inst["op"])
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
        if unit_counts[unit] > UNIT_SLOTS[unit]:
            return False, (f"Unit '{unit}' has {unit_counts[unit]} instructions "
                           f"(max {UNIT_SLOTS[unit]})")
        if inst["dst"] >= 0:
            dsts.append(inst["dst"])
    if len(dsts) != len(set(dsts)):
        return False, f"WAW hazard: duplicate destination registers {dsts}"
    return True, "OK"


def max_register(bundles):
    """Get the number of physical registers needed (max register number + 1)."""
    max_reg = -1
    for bundle in bundles:
        for inst in bundle:
            if inst["dst"] >= 0:
                max_reg = max(max_reg, inst["dst"])
            for s in inst["srcs"]:
                max_reg = max(max_reg, s)
    return max_reg + 1 if max_reg >= 0 else 0


class VLIWMachine:
    """Simulator for the VLIW machine."""

    def __init__(self, initial_memory=None):
        self.regs = {}   # register_id -> uint32 value (default 0)
        self.mem = dict(initial_memory) if initial_memory else {}
        self.cycles = 0

    def run_sequential(self, instructions):
        """Run instructions sequentially (one per cycle).

        Returns final memory state as a dict.
        """
        for inst in instructions:
            if inst["op"] == "halt":
                self.cycles += 1
                break
            src_vals = [self.regs.get(s, 0) for s in inst["srcs"]]
            val, mem_write = execute_op(
                inst["op"], src_vals, inst.get("imm"), self.mem
            )
            if inst["dst"] >= 0 and val is not None:
                self.regs[inst["dst"]] = val
            if mem_write:
                self.mem[mem_write[0]] = mem_write[1]
            self.cycles += 1
        return dict(self.mem)

    def run_vliw(self, bundles):
        """Run VLIW bundles.

        Within each bundle, all source register reads happen BEFORE any
        destination register writes (standard VLIW semantics).

        Returns final memory state as a dict.
        """
        for bundle in bundles:
            has_halt = any(inst["op"] == "halt" for inst in bundle)

            # Phase 1: Snapshot all source register values
            snapshots = []
            for inst in bundle:
                src_vals = [self.regs.get(s, 0) for s in inst["srcs"]]
                snapshots.append(src_vals)

            # Phase 2: Execute all instructions using snapshots
            results = []
            for inst, src_vals in zip(bundle, snapshots):
                val, mem_write = execute_op(
                    inst["op"], src_vals, inst.get("imm"), self.mem
                )
                results.append((inst, val, mem_write))

            # Phase 3: Write back all results
            for inst, val, mem_write in results:
                if inst["dst"] >= 0 and val is not None:
                    self.regs[inst["dst"]] = val
                if mem_write:
                    self.mem[mem_write[0]] = mem_write[1]

            self.cycles += 1
            if has_halt:
                break

        return dict(self.mem)
