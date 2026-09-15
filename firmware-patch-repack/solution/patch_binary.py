#!/usr/bin/env python3
"""Patch a binary string in an ELF file with same-length replacement."""
import sys

def main():
    binary_path = sys.argv[1]
    old_str = sys.argv[2].encode("ascii")
    new_str = sys.argv[3].encode("ascii")

    # Pad new string with null bytes to match original length
    if len(new_str) < len(old_str):
        new_str = new_str + b"\x00" * (len(old_str) - len(new_str))
    elif len(new_str) > len(old_str):
        raise ValueError("Replacement string is longer than original")

    with open(binary_path, "rb") as f:
        data = f.read()

    if old_str not in data:
        raise ValueError(f"String {old_str!r} not found in {binary_path}")

    offset = data.index(old_str)
    data = data[:offset] + new_str + data[offset + len(old_str):]

    with open(binary_path, "wb") as f:
        f.write(data)

    print(f"Patched at offset {offset:#x}: {old_str!r} -> {new_str!r}")

if __name__ == "__main__":
    main()
