#!/usr/bin/env python3
"""
Reconstruct hierarchy.json from class_defs.py and compiler_output.o.

Uses riscv64-linux-gnu binary analysis tools to extract type tag ordering
from the RISC-V ELF object file, and Python ast module to parse class
definitions from the ChocoPy source.

"""

import ast
import json
import re
import subprocess
import sys


def parse_class_defs(source_path):
    """Parse ChocoPy class definitions from Python source."""
    with open(source_path) as f:
        tree = ast.parse(f.read())

    classes = {}
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        name = node.name
        if node.bases:
            base = node.bases[0]
            if isinstance(base, ast.Name):
                super_cls = base.id
            elif isinstance(base, ast.Constant):
                super_cls = base.value
            else:
                super_cls = "object"
        else:
            super_cls = "object"

        attrs = {}
        methods = {}

        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                attr_name = item.target.id
                attr_type = _resolve_annotation(item.annotation)
                attrs[attr_name] = attr_type

            elif isinstance(item, ast.FunctionDef):
                method_name = item.name
                params = []
                for arg in item.args.args:
                    params.append(_resolve_annotation(arg.annotation))
                ret = "<None>"
                if item.returns is not None:
                    ret = _resolve_annotation(item.returns)
                methods[method_name] = {"params": params, "return": ret}

        classes[name] = {
            "super": super_cls,
            "attrs": attrs,
            "methods": methods,
        }

    return classes


def _resolve_annotation(node):
    """Convert an AST annotation node to a type string."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    elif isinstance(node, ast.Subscript):
        inner = _resolve_annotation(node.slice)
        return f"[{inner}]"
    elif isinstance(node, ast.List):
        if node.elts:
            inner = _resolve_annotation(node.elts[0])
            return f"[{inner}]"
        return "<Empty>"
    else:
        return str(ast.dump(node))


def extract_type_tags(obj_path):
    """Extract prototype type tags from ELF object file.

    Uses riscv64-linux-gnu-nm to find prototype symbol offsets in the
    .data section, then riscv64-linux-gnu-objdump -s to read the raw
    hex data and extract type tag values (first 32-bit LE word of each
    prototype object).
    """
    # Step 1: Get symbol table using nm
    nm_result = subprocess.run(
        ["riscv64-linux-gnu-nm", obj_path],
        capture_output=True, text=True, check=True
    )

    # Parse prototype symbol offsets from nm output
    # Format: "00000054 D $A$prototype"
    proto_offsets = {}
    for line in nm_result.stdout.splitlines():
        m = re.match(
            r'([0-9a-fA-F]+)\s+\w\s+\$(\w+)\$prototype\s*$', line
        )
        if m:
            offset = int(m.group(1), 16)
            class_name = m.group(2)
            proto_offsets[class_name] = offset

    # Step 2: Get data section hex dump
    objdump_result = subprocess.run(
        ["riscv64-linux-gnu-objdump", "-s", "-j", ".data", obj_path],
        capture_output=True, text=True, check=True
    )

    # Parse hex dump into byte map
    # Format: " 0054 04000000 04000000 00000000 00000000  ................"
    hex_bytes = {}
    for line in objdump_result.stdout.splitlines():
        m = re.match(r'\s+([0-9a-fA-F]+)\s+((?:[0-9a-fA-F]+\s*)+)\s{2}', line)
        if m:
            base = int(m.group(1), 16)
            raw_hex = m.group(2).replace(' ', '')
            for i in range(0, len(raw_hex), 2):
                hex_bytes[base + i // 2] = int(raw_hex[i:i + 2], 16)

    # Step 3: Read type tag (first 4-byte little-endian word) at each prototype
    tags = {}
    for cls_name, off in proto_offsets.items():
        word = (
            hex_bytes.get(off, 0)
            | (hex_bytes.get(off + 1, 0) << 8)
            | (hex_bytes.get(off + 2, 0) << 16)
            | (hex_bytes.get(off + 3, 0) << 24)
        )
        # Handle signed 32-bit
        if word & 0x80000000:
            word -= 0x100000000
        tags[cls_name] = word

    return tags


def build_hierarchy(source_path, obj_path):
    """Build hierarchy.json from source and object file."""
    user_classes = parse_class_defs(source_path)
    type_tags = extract_type_tags(obj_path)

    # Built-in classes (always present, always first)
    builtins = {
        "object": {"super": None, "attrs": {}, "methods": {
            "__init__": {"params": ["object"], "return": "<None>"}
        }},
        "int": {"super": "object", "attrs": {}, "methods": {
            "__init__": {"params": ["object"], "return": "<None>"}
        }},
        "bool": {"super": "object", "attrs": {}, "methods": {
            "__init__": {"params": ["object"], "return": "<None>"}
        }},
        "str": {"super": "object", "attrs": {}, "methods": {
            "__init__": {"params": ["object"], "return": "<None>"}
        }},
    }

    # Sort user-defined classes by their binary type tag
    user_class_names = [n for n in user_classes if n not in builtins]
    user_class_names.sort(key=lambda n: type_tags.get(n, 999))

    # Build ordered hierarchy: builtins first, then user classes in tag order
    hierarchy = {"classes": {}}
    for name in ["object", "int", "bool", "str"]:
        hierarchy["classes"][name] = builtins[name]
    for name in user_class_names:
        hierarchy["classes"][name] = user_classes[name]

    return hierarchy


if __name__ == "__main__":
    hierarchy = build_hierarchy("/app/class_defs.py", "/app/compiler_output.o")
    with open("/app/hierarchy.json", "w") as f:
        json.dump(hierarchy, f, indent=2)
    print("Wrote /app/hierarchy.json")
