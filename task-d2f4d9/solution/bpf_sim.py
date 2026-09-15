"""
BPF Virtual Machine Simulator for SECCOMP filters.

Executes classic BPF filter programs on seccomp_data inputs and returns
the SECCOMP action value.
"""
import struct


def simulate(instructions, seccomp_data):
    """
    Execute a classic BPF filter program on seccomp_data.

    Args:
        instructions: list of dicts with keys 'code', 'jt', 'jf', 'k' (all ints)
        seccomp_data: dict with keys:
            'nr': int (syscall number)
            'arch': int (architecture, e.g. 0xc000003e for x86-64)
            'instruction_pointer': int (64-bit)
            'args': list of 6 ints (64-bit unsigned each)

    Returns:
        int: The SECCOMP return value (e.g. 0x7fff0000 for ALLOW, 0 for KILL)
    """
    # Serialize seccomp_data to a 64-byte little-endian buffer
    buf = bytearray(64)
    struct.pack_into('<i', buf, 0, seccomp_data['nr'])
    struct.pack_into('<I', buf, 4, seccomp_data['arch'])
    struct.pack_into('<Q', buf, 8, seccomp_data['instruction_pointer'])
    for i, arg in enumerate(seccomp_data['args']):
        struct.pack_into('<Q', buf, 16 + i * 8, arg & 0xFFFFFFFFFFFFFFFF)

    A = 0   # accumulator, 32-bit unsigned
    pc = 0  # program counter

    while pc < len(instructions):
        insn = instructions[pc]
        code = insn['code']
        jt = insn['jt']
        jf = insn['jf']
        k = insn['k']

        if code == 0x20:      # BPF_LD|BPF_W|BPF_ABS
            A = struct.unpack_from('<I', buf, k)[0]
            pc += 1
        elif code == 0x00:    # BPF_LD|BPF_IMM
            A = k
            pc += 1
        elif code == 0x54:    # BPF_ALU|BPF_AND|BPF_K
            A = (A & k) & 0xFFFFFFFF
            pc += 1
        elif code == 0x44:    # BPF_ALU|BPF_OR|BPF_K
            A = (A | k) & 0xFFFFFFFF
            pc += 1
        elif code == 0x04:    # BPF_ALU|BPF_ADD|BPF_K
            A = (A + k) & 0xFFFFFFFF
            pc += 1
        elif code == 0x14:    # BPF_ALU|BPF_SUB|BPF_K
            A = (A - k) & 0xFFFFFFFF
            pc += 1
        elif code == 0x05:    # BPF_JMP|BPF_JA
            pc += 1 + k
        elif code == 0x15:    # BPF_JMP|BPF_JEQ|BPF_K
            pc += 1 + (jt if A == k else jf)
        elif code == 0x25:    # BPF_JMP|BPF_JGT|BPF_K
            pc += 1 + (jt if A > k else jf)
        elif code == 0x35:    # BPF_JMP|BPF_JGE|BPF_K
            pc += 1 + (jt if A >= k else jf)
        elif code == 0x45:    # BPF_JMP|BPF_JSET|BPF_K
            pc += 1 + (jt if (A & k) != 0 else jf)
        elif code == 0x06:    # BPF_RET|BPF_K
            return k
        else:
            raise ValueError(f"Unknown BPF opcode: 0x{code:x} at pc={pc}")

    raise RuntimeError("BPF program fell off the end without returning")
