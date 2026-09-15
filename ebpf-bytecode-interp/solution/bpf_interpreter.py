#!/usr/bin/env python3
"""
BPF Bytecode Interpreter

Executes eBPF programs encoded as raw bytecode and prints the unsigned
64-bit value of R0 at program exit.

Usage: bpf_interp <hex_bytecode>
"""
import struct
import sys

MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1
STACK_SIZE = 512
MAX_INSNS = 1000000


def s64(v):
    """Interpret unsigned 64-bit as signed."""
    v &= MASK64
    return v - (1 << 64) if v >= (1 << 63) else v


def s32(v):
    """Interpret unsigned 32-bit as signed."""
    v &= MASK32
    return v - (1 << 32) if v >= (1 << 31) else v


def tdiv(a, b):
    """Truncated division (rounds toward zero, like C)."""
    if b == 0:
        return 0
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def tmod(a, b):
    """Truncated modulo (sign of dividend, like C)."""
    if b == 0:
        return a
    return a - b * tdiv(a, b)


def interpret(bytecode):
    """Execute BPF bytecode and return R0."""
    # Decode all instruction slots
    insns = []
    i = 0
    while i < len(bytecode):
        if i + 8 > len(bytecode):
            raise ValueError("Truncated instruction at offset %d" % i)
        opcode, regs, off, imm = struct.unpack_from('<BBhi', bytecode, i)
        dst = regs & 0x0f
        src = (regs >> 4) & 0x0f
        insns.append((opcode, dst, src, off, imm))
        i += 8

    # State
    r = [0] * 11          # R0-R10
    r[10] = STACK_SIZE    # Frame pointer
    stack = bytearray(STACK_SIZE)
    pc = 0
    count = 0

    while 0 <= pc < len(insns) and count < MAX_INSNS:
        opcode, dst, src, off, imm = insns[pc]
        cls = opcode & 0x07
        count += 1

        # ==============================================================
        # ALU64 (class 0x7)
        # ==============================================================
        if cls == 0x07:
            code = (opcode >> 4) & 0x0f
            source = (opcode >> 3) & 1
            # Source value: sign-extend imm from s32 to u64 for K
            sv = r[src] if source else (imm & MASK64)

            if code == 0x0:    # ADD
                r[dst] = (r[dst] + sv) & MASK64
            elif code == 0x1:  # SUB
                r[dst] = (r[dst] - sv) & MASK64
            elif code == 0x2:  # MUL
                r[dst] = (r[dst] * sv) & MASK64
            elif code == 0x3:  # DIV / SDIV
                if off == 0:   # unsigned
                    r[dst] = 0 if sv == 0 else r[dst] // sv
                else:          # SDIV (off=1)
                    sd, ss = s64(r[dst]), s64(sv)
                    if ss == 0:
                        r[dst] = 0
                    elif ss == -1 and sd == -(1 << 63):
                        pass   # LLONG_MIN / -1 → LLONG_MIN (unchanged)
                    else:
                        r[dst] = tdiv(sd, ss) & MASK64
            elif code == 0x4:  # OR
                r[dst] = (r[dst] | sv) & MASK64
            elif code == 0x5:  # AND
                r[dst] = (r[dst] & sv) & MASK64
            elif code == 0x6:  # LSH
                r[dst] = (r[dst] << (sv & 0x3f)) & MASK64
            elif code == 0x7:  # RSH
                r[dst] = r[dst] >> (sv & 0x3f)
            elif code == 0x8:  # NEG
                r[dst] = (-s64(r[dst])) & MASK64
            elif code == 0x9:  # MOD / SMOD
                if off == 0:   # unsigned
                    if sv != 0:
                        r[dst] = r[dst] % sv
                    # else: unchanged
                else:          # SMOD (off=1)
                    sd, ss = s64(r[dst]), s64(sv)
                    if ss == 0:
                        pass   # unchanged
                    elif ss == -1 and sd == -(1 << 63):
                        r[dst] = 0
                    else:
                        r[dst] = tmod(sd, ss) & MASK64
            elif code == 0xa:  # XOR
                r[dst] = (r[dst] ^ sv) & MASK64
            elif code == 0xb:  # MOV / MOVSX
                if off == 0:
                    r[dst] = sv & MASK64
                else:
                    # MOVSX: sign-extend from off bits
                    raw = sv
                    if off == 8:
                        v = raw & 0xFF
                        r[dst] = (v - 256 if v >= 128 else v) & MASK64
                    elif off == 16:
                        v = raw & 0xFFFF
                        r[dst] = (v - 0x10000 if v >= 0x8000 else v) & MASK64
                    elif off == 32:
                        r[dst] = s32(raw) & MASK64
            elif code == 0xc:  # ARSH
                shift = sv & 0x3f
                r[dst] = (s64(r[dst]) >> shift) & MASK64

            pc += 1
            continue

        # ==============================================================
        # ALU (32-bit, class 0x4)
        # ==============================================================
        elif cls == 0x04:
            code = (opcode >> 4) & 0x0f
            source = (opcode >> 3) & 1
            sv = (r[src] & MASK32) if source else (imm & MASK32)
            dv = r[dst] & MASK32

            if code == 0x0:    # ADD
                res = (dv + sv) & MASK32
            elif code == 0x1:  # SUB
                res = (dv - sv) & MASK32
            elif code == 0x2:  # MUL
                res = (dv * sv) & MASK32
            elif code == 0x3:  # DIV / SDIV
                if off == 0:
                    res = 0 if sv == 0 else dv // sv
                else:
                    sd, ss = s32(dv), s32(sv)
                    if ss == 0:
                        res = 0
                    elif ss == -1 and sd == -(1 << 31):
                        res = dv  # INT_MIN
                    else:
                        res = tdiv(sd, ss) & MASK32
            elif code == 0x4:  # OR
                res = (dv | sv) & MASK32
            elif code == 0x5:  # AND
                res = (dv & sv) & MASK32
            elif code == 0x6:  # LSH
                res = (dv << (sv & 0x1f)) & MASK32
            elif code == 0x7:  # RSH
                res = dv >> (sv & 0x1f)
            elif code == 0x8:  # NEG
                res = (-s32(dv)) & MASK32
            elif code == 0x9:  # MOD / SMOD
                if off == 0:
                    res = dv if sv == 0 else dv % sv
                else:
                    sd, ss = s32(dv), s32(sv)
                    if ss == 0:
                        res = dv
                    elif ss == -1 and sd == -(1 << 31):
                        res = 0
                    else:
                        res = tmod(sd, ss) & MASK32
            elif code == 0xa:  # XOR
                res = (dv ^ sv) & MASK32
            elif code == 0xb:  # MOV / MOVSX
                if off == 0:
                    res = sv & MASK32
                else:
                    if off == 8:
                        v = sv & 0xFF
                        res = ((v - 256 if v >= 128 else v) & MASK32)
                    elif off == 16:
                        v = sv & 0xFFFF
                        res = ((v - 0x10000 if v >= 0x8000 else v) & MASK32)
                    else:
                        res = sv & MASK32
            elif code == 0xc:  # ARSH
                shift = sv & 0x1f
                res = (s32(dv) >> shift) & MASK32
            elif code == 0xd:  # END (byte swap)
                s_bit = (opcode >> 3) & 1
                if s_bit == 0:  # LE
                    if imm == 16:
                        res = dv & 0xFFFF
                    elif imm == 32:
                        res = dv
                    elif imm == 64:
                        r[dst] = r[dst]
                        pc += 1
                        continue
                    else:
                        res = dv
                else:  # BE
                    if imm == 16:
                        res = ((dv & 0xFF) << 8) | ((dv >> 8) & 0xFF)
                    elif imm == 32:
                        b = dv.to_bytes(4, 'little')
                        res = int.from_bytes(b, 'big')
                    elif imm == 64:
                        b = r[dst].to_bytes(8, 'little')
                        r[dst] = int.from_bytes(b, 'big')
                        pc += 1
                        continue
                    else:
                        res = dv
            else:
                res = dv

            # ALU32: zero-extend result to 64 bits
            r[dst] = res & MASK32
            pc += 1
            continue

        # ==============================================================
        # JMP (class 0x5)
        # ==============================================================
        elif cls == 0x05:
            code = (opcode >> 4) & 0x0f
            source = (opcode >> 3) & 1

            if code == 0x0:  # JA
                pc += off + 1
                continue
            if code == 0x9:  # EXIT
                return r[0]
            if code == 0x8:  # CALL (stub)
                for i in range(1, 6):
                    r[i] = 0
                r[0] = 0
                pc += 1
                continue

            sv = r[src] if source else (imm & MASK64)
            dv = r[dst]

            taken = False
            if code == 0x1:   taken = dv == sv             # JEQ
            elif code == 0x2: taken = dv > sv              # JGT
            elif code == 0x3: taken = dv >= sv             # JGE
            elif code == 0x4: taken = (dv & sv) != 0       # JSET
            elif code == 0x5: taken = dv != sv             # JNE
            elif code == 0x6: taken = s64(dv) > s64(sv)    # JSGT
            elif code == 0x7: taken = s64(dv) >= s64(sv)   # JSGE
            elif code == 0xa: taken = dv < sv              # JLT
            elif code == 0xb: taken = dv <= sv             # JLE
            elif code == 0xc: taken = s64(dv) < s64(sv)    # JSLT
            elif code == 0xd: taken = s64(dv) <= s64(sv)   # JSLE

            pc += (off + 1) if taken else 1
            continue

        # ==============================================================
        # JMP32 (class 0x6)
        # ==============================================================
        elif cls == 0x06:
            code = (opcode >> 4) & 0x0f
            source = (opcode >> 3) & 1

            if code == 0x0:  # JA (32-bit uses imm for offset)
                pc += imm + 1
                continue

            sv = (r[src] & MASK32) if source else (imm & MASK32)
            dv = r[dst] & MASK32

            taken = False
            if code == 0x1:   taken = dv == sv
            elif code == 0x2: taken = dv > sv
            elif code == 0x3: taken = dv >= sv
            elif code == 0x4: taken = (dv & sv) != 0
            elif code == 0x5: taken = dv != sv
            elif code == 0x6: taken = s32(dv) > s32(sv)
            elif code == 0x7: taken = s32(dv) >= s32(sv)
            elif code == 0xa: taken = dv < sv
            elif code == 0xb: taken = dv <= sv
            elif code == 0xc: taken = s32(dv) < s32(sv)
            elif code == 0xd: taken = s32(dv) <= s32(sv)

            pc += (off + 1) if taken else 1
            continue

        # ==============================================================
        # LD (class 0x0)
        # ==============================================================
        elif cls == 0x00:
            mode = (opcode >> 5) & 0x07
            sz = (opcode >> 3) & 0x03
            if mode == 0 and sz == 3:  # LD_IMM64
                if pc + 1 >= len(insns):
                    raise ValueError("LD_IMM64 at end of program")
                _, _, _, _, next_imm = insns[pc + 1]
                lo = imm & MASK32
                hi = next_imm & MASK32
                r[dst] = ((hi << 32) | lo) & MASK64
                pc += 2
                continue
            pc += 1
            continue

        # ==============================================================
        # LDX (class 0x1)
        # ==============================================================
        elif cls == 0x01:
            mode = (opcode >> 5) & 0x07
            sz = (opcode >> 3) & 0x03
            addr = r[src] + off
            sizes = {0: 4, 1: 2, 2: 1, 3: 8}
            nbytes = sizes.get(sz, 0)
            if addr < 0 or addr + nbytes > STACK_SIZE:
                raise ValueError("LDX out of bounds: addr=%d size=%d" % (addr, nbytes))

            if mode == 3:  # MEM (unsigned load)
                if sz == 0:   r[dst] = struct.unpack_from('<I', stack, addr)[0]
                elif sz == 1: r[dst] = struct.unpack_from('<H', stack, addr)[0]
                elif sz == 2: r[dst] = stack[addr]
                elif sz == 3: r[dst] = struct.unpack_from('<Q', stack, addr)[0]
            elif mode == 4:  # MEMSX (sign-extending load)
                if sz == 0:   r[dst] = struct.unpack_from('<i', stack, addr)[0] & MASK64
                elif sz == 1: r[dst] = struct.unpack_from('<h', stack, addr)[0] & MASK64
                elif sz == 2:
                    v = stack[addr]
                    r[dst] = (v - 256 if v >= 128 else v) & MASK64

            pc += 1
            continue

        # ==============================================================
        # ST (class 0x2, store immediate)
        # ==============================================================
        elif cls == 0x02:
            mode = (opcode >> 5) & 0x07
            sz = (opcode >> 3) & 0x03
            addr = r[dst] + off

            if mode == 3:  # MEM
                if sz == 0:   struct.pack_into('<I', stack, addr, imm & MASK32)
                elif sz == 1: struct.pack_into('<H', stack, addr, imm & 0xFFFF)
                elif sz == 2: stack[addr] = imm & 0xFF
                elif sz == 3:
                    val = imm & MASK64  # sign-extend s32 imm to 64 bits
                    struct.pack_into('<Q', stack, addr, val)

            pc += 1
            continue

        # ==============================================================
        # STX (class 0x3, store register / atomic)
        # ==============================================================
        elif cls == 0x03:
            mode = (opcode >> 5) & 0x07
            sz = (opcode >> 3) & 0x03
            addr = r[dst] + off

            if mode == 3:  # MEM
                if sz == 0:   struct.pack_into('<I', stack, addr, r[src] & MASK32)
                elif sz == 1: struct.pack_into('<H', stack, addr, r[src] & 0xFFFF)
                elif sz == 2: stack[addr] = r[src] & 0xFF
                elif sz == 3: struct.pack_into('<Q', stack, addr, r[src] & MASK64)
            elif mode == 6:  # ATOMIC
                atomic_op = imm & 0xF0
                fetch = imm & 0x01
                if sz == 3:  # DW
                    old = struct.unpack_from('<Q', stack, addr)[0]
                    if atomic_op == 0x00:   nv = (old + r[src]) & MASK64
                    elif atomic_op == 0x40: nv = old | r[src]
                    elif atomic_op == 0x50: nv = old & r[src]
                    elif atomic_op == 0xa0: nv = old ^ r[src]
                    elif atomic_op == 0xe0:
                        nv = r[src]; r[src] = old
                    elif atomic_op == 0xf0:
                        nv = r[src] if old == r[0] else old
                        r[0] = old
                    else:
                        nv = old
                    if fetch and atomic_op not in (0xe0, 0xf0):
                        r[src] = old
                    struct.pack_into('<Q', stack, addr, nv)
                elif sz == 0:  # W
                    old = struct.unpack_from('<I', stack, addr)[0]
                    sv32 = r[src] & MASK32
                    if atomic_op == 0x00:   nv = (old + sv32) & MASK32
                    elif atomic_op == 0x40: nv = old | sv32
                    elif atomic_op == 0x50: nv = old & sv32
                    elif atomic_op == 0xa0: nv = old ^ sv32
                    elif atomic_op == 0xe0:
                        nv = sv32; r[src] = old
                    elif atomic_op == 0xf0:
                        nv = sv32 if old == (r[0] & MASK32) else old
                        r[0] = old
                    else:
                        nv = old
                    if fetch and atomic_op not in (0xe0, 0xf0):
                        r[src] = old
                    struct.pack_into('<I', stack, addr, nv)

            pc += 1
            continue

        pc += 1

    return r[0]


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: bpf_interp <hex_bytecode>", file=sys.stderr)
        sys.exit(1)
    try:
        bytecode = bytes.fromhex(sys.argv[1])
    except ValueError as e:
        print("Invalid hex input: %s" % e, file=sys.stderr)
        sys.exit(1)
    result = interpret(bytecode)
    print(result)
