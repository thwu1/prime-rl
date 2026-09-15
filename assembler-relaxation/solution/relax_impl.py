#!/usr/bin/env python3

"""Assembler with binary emission for a simplified x86-like ISA.

Reads an assembly file conforming to /app/isa_spec.md and supports two modes:
  - JSON output (default): labels + total_size
  - Binary output (-b -o <file>): raw machine code bytes
"""

import json
import re
import struct
import sys

# ---------------------------------------------------------------------------
# ISA constants
# ---------------------------------------------------------------------------

REGISTER_RE = re.compile(r"^r([0-7])$")

JCC_MNEMONICS = {"jz", "jnz", "jl", "jg", "jle", "jge"}

JMP_SHORT_SIZE = 2
JMP_LONG_SIZE = 5
JCC_SHORT_SIZE = 2
JCC_LONG_SIZE = 6

SHORT_MIN = -128
SHORT_MAX = 127

# Opcode table
OP_NOP = 0x00
OP_RET = 0x01
OP_PUSH = 0x10
OP_POP = 0x11
OP_CALL = 0x30

BINARY_OP_RR = {"mov": 0x20, "add": 0x22, "sub": 0x24, "cmp": 0x26}
BINARY_OP_RI = {"mov": 0x21, "add": 0x23, "sub": 0x25, "cmp": 0x27}

JMP_SHORT_OP = {
    "jmp": 0xE0, "jz": 0xE1, "jnz": 0xE2,
    "jl": 0xE3, "jg": 0xE4, "jle": 0xE5, "jge": 0xE6,
}

JMP_LONG_SINGLE = 0xF0
JCC_LONG_PREFIX = 0x0F
JCC_LONG_SECOND = {
    "jz": 0x81, "jnz": 0x82, "jl": 0x83,
    "jg": 0x84, "jle": 0x85, "jge": 0x86,
}

PAD_BYTE = 0x00


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_assembly(filename):
    """Parse assembly file into structured elements."""
    elements = []
    with open(filename) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            hash_idx = line.find("#")
            if hash_idx >= 0:
                line = line[:hash_idx].strip()
            if not line:
                continue

            # Label
            if line.endswith(":") and " " not in line and "\t" not in line:
                elements.append({"type": "label", "name": line[:-1]})
                continue

            # Directives
            if line.startswith(".align"):
                tokens = line.split()
                elements.append({"type": "align", "value": int(tokens[1])})
                continue
            if line.startswith(".fill"):
                tokens = line.split()
                elements.append({"type": "fill", "value": int(tokens[1])})
                continue

            # Instructions
            tokens = line.split(None, 1)
            mnemonic = tokens[0].lower()
            operands_str = tokens[1].strip() if len(tokens) > 1 else ""

            if mnemonic == "jmp":
                elements.append({
                    "type": "jmp", "target": operands_str.strip(), "relaxed": False,
                })
            elif mnemonic in JCC_MNEMONICS:
                elements.append({
                    "type": "jcc", "mnemonic": mnemonic,
                    "target": operands_str.strip(), "relaxed": False,
                })
            elif mnemonic in ("nop", "ret"):
                elements.append({
                    "type": "fixed", "mnemonic": mnemonic, "size": 1,
                })
            elif mnemonic in ("push", "pop"):
                m = REGISTER_RE.match(operands_str.strip())
                reg = int(m.group(1)) if m else 0
                elements.append({
                    "type": "fixed", "mnemonic": mnemonic, "size": 2,
                    "reg1": reg,
                })
            elif mnemonic == "call":
                elements.append({
                    "type": "call", "target": operands_str.strip(),
                })
            elif mnemonic in ("mov", "add", "sub", "cmp"):
                parts = [p.strip() for p in operands_str.split(",")]
                m1 = REGISTER_RE.match(parts[0])
                reg1 = int(m1.group(1)) if m1 else 0
                if len(parts) == 2:
                    m2 = REGISTER_RE.match(parts[1])
                    if m2:
                        elements.append({
                            "type": "fixed", "mnemonic": mnemonic, "size": 2,
                            "reg1": reg1, "reg2": int(m2.group(1)),
                        })
                    else:
                        elements.append({
                            "type": "fixed", "mnemonic": mnemonic, "size": 3,
                            "reg1": reg1, "imm": int(parts[1]),
                        })
            else:
                raise ValueError(f"Unknown mnemonic: {mnemonic!r}")

    return elements


# ---------------------------------------------------------------------------
# Layout computation
# ---------------------------------------------------------------------------


def _jump_size(elem):
    if elem["type"] == "jmp":
        return JMP_LONG_SIZE if elem["relaxed"] else JMP_SHORT_SIZE
    else:
        return JCC_LONG_SIZE if elem["relaxed"] else JCC_SHORT_SIZE


def compute_layout(elements):
    offsets = []
    labels = {}
    offset = 0

    for elem in elements:
        offsets.append(offset)
        t = elem["type"]

        if t == "label":
            labels[elem["name"]] = offset
        elif t == "align":
            n = elem["value"]
            padding = (n - (offset % n)) % n
            offset += padding
        elif t == "fill":
            offset += elem["value"]
        elif t == "fixed":
            offset += elem["size"]
        elif t == "call":
            offset += 5
        elif t in ("jmp", "jcc"):
            offset += _jump_size(elem)

    return offsets, labels, offset


# ---------------------------------------------------------------------------
# Iterative relaxation
# ---------------------------------------------------------------------------


def relax(elements):
    for _ in range(200):
        offsets, labels, total_size = compute_layout(elements)
        changed = False

        for i, elem in enumerate(elements):
            if elem["type"] not in ("jmp", "jcc"):
                continue
            if elem["relaxed"]:
                continue

            target_label = elem["target"]
            if target_label not in labels:
                raise ValueError(f"Undefined label: {target_label!r}")

            instr_size = _jump_size(elem)
            instr_end = offsets[i] + instr_size
            pc_rel = labels[target_label] - instr_end

            if pc_rel < SHORT_MIN or pc_rel > SHORT_MAX:
                elem["relaxed"] = True
                changed = True

        if not changed:
            break

    _, labels, total_size = compute_layout(elements)
    return labels, total_size


# ---------------------------------------------------------------------------
# Binary emission
# ---------------------------------------------------------------------------


def emit_binary(elements):
    """Emit assembled binary bytes after relaxation."""
    offsets, labels, total_size = compute_layout(elements)
    output = bytearray()

    for i, elem in enumerate(elements):
        t = elem["type"]

        if t == "label":
            continue
        elif t == "align":
            n = elem["value"]
            off = offsets[i]
            pad = (n - (off % n)) % n
            output.extend(bytes(pad))
        elif t == "fill":
            output.extend(bytes(elem["value"]))
        elif t == "fixed":
            mnem = elem["mnemonic"]
            if mnem == "nop":
                output.append(OP_NOP)
            elif mnem == "ret":
                output.append(OP_RET)
            elif mnem == "push":
                output.append(OP_PUSH)
                output.append(elem["reg1"])
            elif mnem == "pop":
                output.append(OP_POP)
                output.append(elem["reg1"])
            elif mnem in BINARY_OP_RR:
                if "reg2" in elem:
                    output.append(BINARY_OP_RR[mnem])
                    output.append((elem["reg1"] << 4) | elem["reg2"])
                else:
                    output.append(BINARY_OP_RI[mnem])
                    output.append(elem["reg1"])
                    output.append(elem["imm"] & 0xFF)
        elif t == "call":
            tgt = labels[elem["target"]]
            rel = tgt - (offsets[i] + 5)
            output.append(OP_CALL)
            output.extend(struct.pack("<i", rel))
        elif t in ("jmp", "jcc"):
            tgt = labels[elem["target"]]
            cur_size = _jump_size(elem)
            rel = tgt - (offsets[i] + cur_size)

            if not elem["relaxed"]:
                # Short form
                if t == "jmp":
                    output.append(JMP_SHORT_OP["jmp"])
                else:
                    output.append(JMP_SHORT_OP[elem["mnemonic"]])
                output.append(rel & 0xFF)
            else:
                # Long form
                if t == "jmp":
                    output.append(JMP_LONG_SINGLE)
                    output.extend(struct.pack("<i", rel))
                else:
                    output.append(JCC_LONG_PREFIX)
                    output.append(JCC_LONG_SECOND[elem["mnemonic"]])
                    output.extend(struct.pack("<i", rel))

    return bytes(output)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = sys.argv[1:]
    binary_mode = False
    output_file = None
    asm_file = None

    i = 0
    while i < len(args):
        if args[i] == "-b":
            binary_mode = True
        elif args[i] == "-o":
            i += 1
            output_file = args[i]
        elif not args[i].startswith("-"):
            asm_file = args[i]
        i += 1

    if not asm_file:
        print("Usage: relax.py [-b -o <output.bin>] <assembly_file>",
              file=sys.stderr)
        sys.exit(1)

    elements = parse_assembly(asm_file)
    labels, total_size = relax(elements)

    if binary_mode and output_file:
        binary_data = emit_binary(elements)
        with open(output_file, "wb") as f:
            f.write(binary_data)
    else:
        result = {"labels": labels, "total_size": total_size}
        json.dump(result, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
