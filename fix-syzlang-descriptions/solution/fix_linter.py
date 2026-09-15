#!/usr/bin/env python3
"""
Fix bugs in the syzlang linter (/app/tools/syzlang_lint.py).

Analyzes the linter source and applies targeted patches for 4 bugs:
1. extract_constants: missing support for (1 << N) shift expressions
2. extract_ioctls: _IOW prefix matches _IOWR because regex has no trailing anchor
3. extract_struct_fields: non-greedy .*? stops at first } (breaks on unions)
4. extract_packed_structs: non-greedy .*? spans across struct boundaries

"""

import re

LINTER_PATH = "/app/tools/syzlang_lint.py"


def read_linter():
    with open(LINTER_PATH, "r") as f:
        return f.read()


def write_linter(content):
    with open(LINTER_PATH, "w") as f:
        f.write(content)


def apply_fixes():
    source = read_linter()

    # ---- Fix 1: Constants with shift expressions ----
    # The original only matches plain numeric constants: (0x[0-9a-fA-F]+|\d+)
    # Need to also handle (1 << N) expressions like VDMA_CAP_SG
    old_const_func = '''def extract_constants(header):
    """Extract #define constants and their values from the header."""
    constants = {}
    for match in re.finditer(
        r'^#define\\s+(\\w+)\\s+(0x[0-9a-fA-F]+|\\d+)\\s*(?:/\\*.*?\\*/)?$',
        header, re.MULTILINE
    ):
        name, value = match.groups()
        try:
            constants[name] = int(value, 0)
        except ValueError:
            constants[name] = value
    return constants'''

    new_const_func = '''def extract_constants(header):
    """Extract #define constants and their values from the header."""
    constants = {}
    # Match plain numeric constants
    for match in re.finditer(
        r'^#define\\s+(\\w+)\\s+(0x[0-9a-fA-F]+|\\d+)\\s*(?:/\\*.*?\\*/)?$',
        header, re.MULTILINE
    ):
        name, value = match.groups()
        try:
            constants[name] = int(value, 0)
        except ValueError:
            constants[name] = value
    # Match shift expressions: (base << shift)
    for match in re.finditer(
        r'^#define\\s+(\\w+)\\s+\\(\\s*(\\d+)\\s*<<\\s*(\\d+)\\s*\\)',
        header, re.MULTILINE
    ):
        name = match.group(1)
        base = int(match.group(2))
        shift = int(match.group(3))
        constants[name] = base << shift
    return constants'''

    source = source.replace(old_const_func, new_const_func)

    # ---- Fix 2: ioctl direction detection ----
    # The regex (_IOW|_IOR|_IOWR) without a trailing \s*\( allows _IOW
    # to match at _IOWR positions since _IOW is a prefix and nothing
    # forces the match to be longer. Fix: reorder so _IOWR is tried first.
    source = source.replace(
        "(_IOW|_IOR|_IOWR)",
        "(_IOWR|_IOW|_IOR)"
    )

    # ---- Fix 3: Struct field extraction with nested braces ----
    # The regex r'struct\s+(\w+)\s*\{(.*?)\}' with re.DOTALL stops at the
    # first }, which breaks on structs containing anonymous unions.
    # Replace with brace-depth aware parsing.
    old_struct_func = '''def extract_struct_fields(header):
    """Extract struct definitions and their field names from the header."""
    structs = {}
    for match in re.finditer(
        r'struct\\s+(\\w+)\\s*\\{(.*?)\\}', header, re.DOTALL
    ):
        name = match.group(1)
        body = match.group(2)
        fields = []
        for line in body.split('\\n'):
            line = line.strip()
            if not line or line.startswith('/*') or line.startswith('*') \\
                    or line.startswith('//'):
                continue
            if line.startswith('union') or \\
                    line.startswith('struct') and '{' in line:
                continue
            if line in ('};', '}'):
                continue
            field_m = re.match(
                r'(?:(?:struct\\s+)?\\w+)\\s+(\\w+)(?:\\s*\\[.*?\\])?\\s*;',
                line
            )
            if field_m:
                fields.append(field_m.group(1))
        structs[name] = fields
    return structs'''

    new_struct_func = '''def extract_struct_fields(header):
    """Extract struct definitions and their field names from the header."""
    structs = {}
    i = 0
    while i < len(header):
        m = re.search(r'struct\\s+(\\w+)\\s*\\{', header[i:])
        if not m:
            break
        name = m.group(1)
        start = i + m.end()
        depth = 1
        pos = start
        while pos < len(header) and depth > 0:
            if header[pos] == '{':
                depth += 1
            elif header[pos] == '}':
                depth -= 1
            pos += 1
        body = header[start:pos - 1]
        i = pos
        fields = []
        inner_depth = 0
        for line in body.split('\\n'):
            stripped = line.strip()
            # Detect anonymous unions before updating depth
            if stripped.startswith('union'):
                fields.append('__anon_union')
                inner_depth += stripped.count('{') - stripped.count('}')
                continue
            inner_depth += stripped.count('{') - stripped.count('}')
            if inner_depth > 0 or not stripped:
                continue
            if stripped.startswith('/*') or stripped.startswith('*') \\
                    or stripped.startswith('//'):
                continue
            if stripped in ('};', '}'):
                continue
            field_m = re.match(
                r'(?:(?:struct\\s+)?\\w+)\\s+(\\w+)(?:\\s*\\[.*?\\])?\\s*;',
                stripped
            )
            if field_m:
                fields.append(field_m.group(1))
        structs[name] = fields
    return structs'''

    source = source.replace(old_struct_func, new_struct_func)

    # ---- Fix 4: Packed struct detection ----
    # Same problem: non-greedy .*? with re.DOTALL spans struct boundaries.
    # Replace with brace-depth aware matching.
    old_packed_func = '''def extract_packed_structs(header):
    """Find structs declared with __attribute__((packed))."""
    packed = set()
    for match in re.finditer(
        r'struct\\s+(\\w+)\\s*\\{.*?\\}\\s*__attribute__\\s*\\(\\s*\\(\\s*packed\\s*\\)\\s*\\)',
        header, re.DOTALL
    ):
        packed.add(match.group(1))
    return packed'''

    new_packed_func = '''def extract_packed_structs(header):
    """Find structs declared with __attribute__((packed))."""
    packed = set()
    i = 0
    while i < len(header):
        m = re.search(r'struct\\s+(\\w+)\\s*\\{', header[i:])
        if not m:
            break
        name = m.group(1)
        start = i + m.end()
        depth = 1
        pos = start
        while pos < len(header) and depth > 0:
            if header[pos] == '{':
                depth += 1
            elif header[pos] == '}':
                depth -= 1
            pos += 1
        rest = header[pos:pos + 80]
        if re.match(r'\\s*__attribute__\\s*\\(\\s*\\(\\s*packed\\s*\\)\\s*\\)', rest):
            packed.add(name)
        i = pos
    return packed'''

    source = source.replace(old_packed_func, new_packed_func)

    write_linter(source)
    print("Linter fixes applied successfully.")


if __name__ == "__main__":
    apply_fixes()
