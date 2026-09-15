#!/usr/bin/env python3
"""
Generate binary trace file from JSON test vectors.
Used during Docker build only — removed from final image.

"""

import json
import struct
import sys

MAGIC = b"8T88"
VERSION = 1
REG_ORDER = ['ax', 'cx', 'dx', 'bx', 'sp', 'bp', 'si', 'di']


def encode_vector(tv):
    """Encode a test vector into a binary trace record (81 bytes)."""
    # Test name: 32 bytes, null-padded ASCII
    name = tv['name'].encode('ascii')[:32].ljust(32, b'\x00')

    # Instruction bytes: 1 byte length + 8 bytes zero-padded
    insn_bytes = bytes(tv['bytes'])
    insn_len = struct.pack('B', len(insn_bytes))
    insn_padded = insn_bytes.ljust(8, b'\x00')

    # Initial register file: 8 x uint16 LE
    init = tv['initial']
    init_regs = struct.pack('<8H', *[init.get(r, 0) for r in REG_ORDER])
    init_flags = struct.pack('<H', init.get('flags', 2))
    init_ip = struct.pack('<H', init.get('ip', 0x1000))

    # Expected register file: 8 x uint16 LE (use initial as default)
    exp = tv['expected']
    exp_regs = struct.pack('<8H', *[exp.get(r, init.get(r, 0)) for r in REG_ORDER])
    exp_flags = struct.pack('<H', exp.get('flags', init.get('flags', 2)))

    # Flags comparison mask: 2 bytes (undocumented in format spec)
    flags_mask = struct.pack('<H', tv.get('flags_mask', 0x08D5))

    record = name + insn_len + insn_padded + init_regs + init_flags + init_ip + exp_regs + exp_flags + flags_mask
    assert len(record) == 81, f"Record size mismatch: {len(record)}"
    return record


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.json> <output.bin>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        vectors = json.load(f)

    header = MAGIC + struct.pack('<HH', VERSION, len(vectors))
    assert len(header) == 8

    with open(sys.argv[2], 'wb') as f:
        f.write(header)
        for v in vectors:
            f.write(encode_vector(v))

    total = 8 + 81 * len(vectors)
    print(f"Wrote {len(vectors)} traces ({total} bytes) to {sys.argv[2]}")


if __name__ == '__main__':
    main()
