#!/usr/bin/env python3
"""Assembler relaxation engine for a simplified x86-like instruction set.

"""

import json
import sys


def parse_assembly(source):
    """Parse assembly source into items list and label-to-index mapping."""
    items = []
    labels = {}

    for lineno, raw_line in enumerate(source.split("\n"), 1):
        line = raw_line.split(";")[0].split("#")[0].strip()
        if not line:
            continue

        # Handle label definitions
        if ":" in line:
            colon_pos = line.index(":")
            label_name = line[:colon_pos].strip()
            labels[label_name] = len(items)
            remainder = line[colon_pos + 1 :].strip()
            if not remainder:
                continue
            line = remainder

        tokens = line.split()
        if not tokens:
            continue

        mnemonic = tokens[0].lower()

        if mnemonic == "inst":
            items.append({"type": "inst", "size": int(tokens[1]), "line": lineno})
        elif mnemonic in ("jmp", "jcc"):
            items.append(
                {
                    "type": mnemonic,
                    "target": tokens[1],
                    "relaxed": False,
                    "line": lineno,
                }
            )
        elif mnemonic == ".fill":
            items.append({"type": "fill", "size": int(tokens[1]), "line": lineno})
        elif mnemonic == ".align":
            items.append(
                {"type": "align", "alignment": int(tokens[1]), "size": 0, "line": lineno}
            )
        else:
            raise ValueError(f"Unknown mnemonic '{mnemonic}' at line {lineno}")

    return items, labels


def compute_layout(items, labels):
    """Compute byte offsets for all items and labels. Returns (total_size, label_offsets)."""
    offset = 0
    label_offsets = {}

    # Build reverse map: item_index -> list of label names
    idx_to_labels = {}
    for name, idx in labels.items():
        idx_to_labels.setdefault(idx, []).append(name)

    for idx, item in enumerate(items):
        # Record any labels pointing to this item index
        for name in idx_to_labels.get(idx, []):
            label_offsets[name] = offset

        if item["type"] in ("inst", "fill"):
            item["offset"] = offset
            offset += item["size"]
        elif item["type"] in ("jmp", "jcc"):
            item["offset"] = offset
            item["size"] = 6 if item["relaxed"] else 2
            offset += item["size"]
        elif item["type"] == "align":
            item["offset"] = offset
            alignment = item["alignment"]
            padding = (alignment - (offset % alignment)) % alignment
            item["size"] = padding
            offset += padding

    # Handle labels at the very end of the program
    for name in idx_to_labels.get(len(items), []):
        label_offsets[name] = offset

    return offset, label_offsets


def relax(items, labels):
    """Perform iterative relaxation until convergence."""
    iterations = 0

    while True:
        total_size, label_offsets = compute_layout(items, labels)

        changed = False
        for item in items:
            if item["type"] in ("jmp", "jcc") and not item["relaxed"]:
                target_offset = label_offsets[item["target"]]
                end_of_jump = item["offset"] + item["size"]
                displacement = target_offset - end_of_jump

                if displacement < -128 or displacement > 127:
                    item["relaxed"] = True
                    changed = True

        if changed:
            iterations += 1
        else:
            break

    return total_size, iterations, label_offsets


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 relaxer.py <assembly_file>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        source = f.read()

    items, labels = parse_assembly(source)
    total_size, iterations, label_offsets = relax(items, labels)

    jumps = []
    for item in items:
        if item["type"] in ("jmp", "jcc"):
            jumps.append(
                {
                    "line": item["line"],
                    "target": item["target"],
                    "offset": item["offset"],
                    "size": item["size"],
                    "relaxed": item["relaxed"],
                }
            )

    result = {
        "total_size": total_size,
        "iterations": iterations,
        "labels": label_offsets,
        "jumps": jumps,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
