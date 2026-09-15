#!/usr/bin/env python3
"""
MicroJava Bytecode Peephole Optimizer

Reads a MicroJava .obj file, applies peephole optimizations with correct
jump relocation, and writes an optimized .obj file producing identical output.
"""

import struct
import sys

# ── Opcodes ──────────────────────────────────────────────────────────────────
LOAD = 1; LOAD0 = 2; LOAD1 = 3; LOAD2 = 4; LOAD3 = 5
STORE = 6; STORE0 = 7; STORE1 = 8; STORE2 = 9; STORE3 = 10
GETSTATIC = 11; PUTSTATIC = 12; GETFIELD = 13; PUTFIELD = 14
CONST0 = 15; CONST1 = 16; CONST2 = 17; CONST3 = 18; CONST4 = 19; CONST5 = 20
CONST_M1 = 21; CONST_ = 22
ADD = 23; SUB = 24; MUL = 25; DIV = 26; REM = 27; NEG = 28; SHL = 29; SHR = 30
INC = 31; NEW_ = 32; NEWARRAY = 33
ALOAD = 34; ASTORE = 35; BALOAD = 36; BASTORE = 37; ARRAYLENGTH = 38
POP = 39; DUP = 40; DUP2 = 41
JMP = 42; JEQ = 43; JNE = 44; JLT = 45; JLE = 46; JGT = 47; JGE = 48
CALL = 49; RETURN_ = 50; ENTER = 51; EXIT = 52
READ = 53; PRINT = 54; BREAD = 55; BPRINT = 56; TRAP = 57

JUMP_OPS = frozenset({JMP, JEQ, JNE, JLT, JLE, JGT, JGE, CALL})
ARITH_OPS = frozenset({ADD, SUB, MUL, DIV, REM})


# ── Instruction representation ───────────────────────────────────────────────
class Instr:
    """A single bytecode instruction with its operands and optional jump target."""
    __slots__ = ["op", "operands", "addr", "target"]

    def __init__(self, op, operands, addr=0):
        self.op = op
        self.operands = list(operands)
        self.addr = addr
        self.target = None  # object reference to target Instr (for jumps/calls)

    @property
    def size(self):
        op = self.op
        if op in (LOAD, STORE, NEWARRAY, TRAP):
            return 2
        if op in (GETSTATIC, PUTSTATIC, GETFIELD, PUTFIELD, NEW_,
                  JMP, JEQ, JNE, JLT, JLE, JGT, JGE, CALL, INC, ENTER):
            return 3
        if op == CONST_:
            return 5
        return 1


# ── .obj file I/O ────────────────────────────────────────────────────────────
def read_obj(path):
    with open(path, "rb") as f:
        d = f.read()
    assert d[:2] == b"MJ", "Not a MicroJava file"
    cs = struct.unpack(">i", d[2:6])[0]
    ds = struct.unpack(">i", d[6:10])[0]
    mp = struct.unpack(">i", d[10:14])[0]
    return list(d[14 : 14 + cs]), ds, mp


def write_obj(path, code_bytes, ds, mp):
    with open(path, "wb") as f:
        f.write(b"MJ")
        f.write(struct.pack(">i", len(code_bytes)))
        f.write(struct.pack(">i", ds))
        f.write(struct.pack(">i", mp))
        f.write(bytes(code_bytes))


# ── Disassembler ─────────────────────────────────────────────────────────────
def disassemble(code):
    """Parse bytecode into a list of Instr objects with resolved jump targets."""
    instrs = []
    addr_map = {}  # addr → Instr
    pc = 0
    while pc < len(code):
        addr = pc
        op = code[pc]
        pc += 1
        ops = []

        if op in (LOAD, STORE, NEWARRAY, TRAP):
            ops.append(code[pc])
            pc += 1
        elif op in (GETSTATIC, PUTSTATIC, GETFIELD, PUTFIELD, NEW_) or op in JUMP_OPS:
            val = (code[pc] << 8) | code[pc + 1]
            if val >= 0x8000:
                val -= 0x10000  # sign-extend 16 bits
            ops.append(val)
            pc += 2
        elif op == CONST_:
            val = struct.unpack(">i", bytes(code[pc : pc + 4]))[0]
            ops.append(val)
            pc += 4
        elif op == INC:
            ops.append(code[pc])  # addr (unsigned byte)
            v = code[pc + 1]
            if v > 127:
                v -= 256  # sign-extend
            ops.append(v)
            pc += 2
        elif op == ENTER:
            ops.append(code[pc])
            ops.append(code[pc + 1])
            pc += 2

        instr = Instr(op, ops, addr)
        addr_map[addr] = instr
        instrs.append(instr)

    # Resolve jump/call targets to object references
    for i in instrs:
        if i.op in JUMP_OPS:
            tgt_addr = i.addr + i.operands[0]
            i.target = addr_map.get(tgt_addr)

    return instrs, addr_map


# ── Helper utilities ─────────────────────────────────────────────────────────
def const_val(instr):
    """Return the integer value pushed by a const instruction, or None."""
    if instr is None:
        return None
    if CONST0 <= instr.op <= CONST5:
        return instr.op - CONST0
    if instr.op == CONST_M1:
        return -1
    if instr.op == CONST_:
        return instr.operands[0]
    return None


def make_const(val):
    """Create an Instr that loads the given constant value."""
    if 0 <= val <= 5:
        return Instr(CONST0 + val, [])
    if val == -1:
        return Instr(CONST_M1, [])
    return Instr(CONST_, [val])


def const_size(val):
    """Size of the instruction needed to push val."""
    if 0 <= val <= 5 or val == -1:
        return 1
    return 5


def to_i32(v):
    """Truncate to 32-bit signed integer (Java int semantics)."""
    v = v & 0xFFFFFFFF
    if v >= 0x80000000:
        v -= 0x100000000
    return v


def build_target_set(instrs, main_instr):
    """Build set of id(instr) for every instruction that is a jump target or mainPc."""
    s = set()
    if main_instr is not None:
        s.add(id(main_instr))
    for i in instrs:
        if i.op in JUMP_OPS and i.target is not None:
            s.add(id(i.target))
    return s


def retarget_jumps(instrs, old_instr, new_instr, main_instr):
    """Update any jump/call targeting old_instr to point to new_instr instead."""
    for j in instrs:
        if j.op in JUMP_OPS and j.target is old_instr:
            j.target = new_instr
    if main_instr is old_instr:
        return new_instr
    return main_instr


# ── Optimization passes ─────────────────────────────────────────────────────
def optimize(instrs, main_instr):
    """Apply all optimizations in a fixed-point loop until convergence."""
    max_passes = 30
    for _ in range(max_passes):
        changed = False

        # ── Pass 1: Constant folding ────────────────────────────────────
        target_set = build_target_set(instrs, main_instr)
        new_instrs = []
        i = 0
        while i < len(instrs):
            if i + 2 < len(instrs):
                va = const_val(instrs[i])
                vb = const_val(instrs[i + 1])
                cop = instrs[i + 2].op
                if (
                    va is not None
                    and vb is not None
                    and cop in ARITH_OPS
                    and id(instrs[i + 1]) not in target_set
                    and id(instrs[i + 2]) not in target_set
                ):
                    # Don't fold division/remainder by zero
                    if cop in (DIV, REM) and vb == 0:
                        new_instrs.append(instrs[i])
                        i += 1
                        continue

                    if cop == ADD:
                        res = to_i32(va + vb)
                    elif cop == SUB:
                        res = to_i32(va - vb)
                    elif cop == MUL:
                        res = to_i32(va * vb)
                    elif cop == DIV:
                        # Java truncates toward zero
                        res = to_i32(int(va / vb))
                    elif cop == REM:
                        res = to_i32(int(va - int(va / vb) * vb))
                    else:
                        new_instrs.append(instrs[i])
                        i += 1
                        continue

                    old_sz = instrs[i].size + instrs[i + 1].size + 1
                    new_sz = const_size(res)
                    if new_sz < old_sz:
                        rep = make_const(res)
                        # Retarget jumps pointing to instrs[i]
                        main_instr = retarget_jumps(
                            instrs, instrs[i], rep, main_instr
                        )
                        new_instrs.append(rep)
                        changed = True
                        i += 3
                        continue

            new_instrs.append(instrs[i])
            i += 1
        instrs = new_instrs

        # ── Pass 2: Strength reduction (power-of-2 multiply → shift) ───
        target_set = build_target_set(instrs, main_instr)
        new_instrs = []
        i = 0
        while i < len(instrs):
            if i + 1 < len(instrs) and instrs[i + 1].op == MUL:
                val = const_val(instrs[i])
                if (
                    val is not None
                    and val > 0
                    and (val & (val - 1)) == 0
                    and id(instrs[i + 1]) not in target_set
                ):
                    shift = val.bit_length() - 1
                    old_sz = instrs[i].size + 1  # const + mul
                    new_sz = const_size(shift) + 1  # const_shift + shl
                    if new_sz < old_sz:
                        rep_c = make_const(shift)
                        rep_s = Instr(SHL, [])
                        main_instr = retarget_jumps(
                            instrs, instrs[i], rep_c, main_instr
                        )
                        main_instr = retarget_jumps(
                            instrs, instrs[i + 1], rep_s, main_instr
                        )
                        new_instrs.append(rep_c)
                        new_instrs.append(rep_s)
                        changed = True
                        i += 2
                        continue
            new_instrs.append(instrs[i])
            i += 1
        instrs = new_instrs

        # ── Pass 3: Jump-chain shortcutting ─────────────────────────────
        for i in instrs:
            if i.op in JUMP_OPS and i.op != CALL and i.target is not None:
                # Follow chain of unconditional jumps
                visited = set()
                t = i.target
                while (
                    t is not None
                    and t.op == JMP
                    and t.target is not None
                    and id(t) not in visited
                ):
                    visited.add(id(t))
                    t = t.target
                if t is not None and t is not i.target:
                    i.target = t
                    changed = True

        # ── Pass 4: Unreachable code elimination ────────────────────────
        target_set = build_target_set(instrs, main_instr)
        new_instrs = []
        unreachable = False
        for i in instrs:
            if id(i) in target_set or i.op == ENTER:
                unreachable = False
            if not unreachable:
                new_instrs.append(i)
            if i.op in (JMP, RETURN_):
                unreachable = True
        if len(new_instrs) < len(instrs):
            changed = True
        instrs = new_instrs

        if not changed:
            break

    return instrs, main_instr


# ── Code emission ────────────────────────────────────────────────────────────
def emit(instrs):
    """Assign final addresses and emit bytecode with correct jump offsets."""
    # Assign sequential addresses
    pc = 0
    for i in instrs:
        i.addr = pc
        pc += i.size

    # Emit bytes
    code = bytearray()
    for i in instrs:
        code.append(i.op & 0xFF)

        if i.op in (LOAD, STORE, NEWARRAY, TRAP):
            code.append(i.operands[0] & 0xFF)

        elif i.op in (GETSTATIC, PUTSTATIC, GETFIELD, PUTFIELD, NEW_):
            val = i.operands[0] & 0xFFFF
            code.append((val >> 8) & 0xFF)
            code.append(val & 0xFF)

        elif i.op in JUMP_OPS:
            # Recompute relative offset from current instr address to target
            offset = i.target.addr - i.addr
            offset = offset & 0xFFFF
            code.append((offset >> 8) & 0xFF)
            code.append(offset & 0xFF)

        elif i.op == CONST_:
            code.extend(struct.pack(">i", i.operands[0]))

        elif i.op == INC:
            code.append(i.operands[0] & 0xFF)
            code.append(i.operands[1] & 0xFF)

        elif i.op == ENTER:
            code.append(i.operands[0] & 0xFF)
            code.append(i.operands[1] & 0xFF)

    return bytes(code)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.obj> <output.obj>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    code, data_size, main_pc = read_obj(input_path)
    instrs, addr_map = disassemble(code)

    main_instr = addr_map.get(main_pc)
    assert main_instr is not None, f"No instruction at mainPc={main_pc}"

    optimized, main_instr = optimize(instrs, main_instr)
    new_code = emit(optimized)

    write_obj(output_path, new_code, data_size, main_instr.addr)

    orig_sz = len(code)
    opt_sz = len(new_code)
    print(f"{input_path}: {orig_sz} -> {opt_sz} bytes (saved {orig_sz - opt_sz})")


if __name__ == "__main__":
    main()
