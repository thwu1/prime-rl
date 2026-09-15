#!/usr/bin/env python3
"""CLI wrapper for the SEAT cryptographic transform library."""

import ctypes
import sys
import json

_lib = ctypes.CDLL("/app/libseat.so")
_lib.seat_transform.argtypes = [ctypes.c_uint64]
_lib.seat_transform.restype = ctypes.c_uint64


def transform(x):
    """Apply the SEAT transform to a 64-bit integer."""
    return _lib.seat_transform(x)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("SEAT Transform CLI")
        print(f"Usage: {sys.argv[0]} <hex_value>")
        print(f"       {sys.argv[0]} --batch <input.json>")
        print(f"       {sys.argv[0]} --verify <hex_input> <hex_expected>")
        sys.exit(1)

    if sys.argv[1] == "--verify":
        if len(sys.argv) != 4:
            print("Usage: --verify <hex_input> <hex_expected>", file=sys.stderr)
            sys.exit(1)
        inp = int(sys.argv[2], 16)
        exp = int(sys.argv[3], 16)
        out = transform(inp)
        if out == exp:
            print("VERIFIED")
        else:
            print(f"FAILED: transform(0x{inp:016x}) = 0x{out:016x}, "
                  f"expected 0x{exp:016x}")
            sys.exit(1)
    elif sys.argv[1] == "--batch":
        if len(sys.argv) != 3:
            print("Usage: --batch <input.json>", file=sys.stderr)
            sys.exit(1)
        with open(sys.argv[2]) as f:
            inputs = json.load(f)
        outputs = []
        for v in inputs:
            x = int(v, 16) if isinstance(v, str) else v
            outputs.append(f"{transform(x):016x}")
        print(json.dumps(outputs, indent=2))
    else:
        val = int(sys.argv[1], 16)
        print(f"{transform(val):016x}")
