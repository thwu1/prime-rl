#!/usr/bin/env python3
"""
syzlang_lint.py - Validate syzlang descriptions against a kernel UAPI header.

Usage: python3 syzlang_lint.py <header.h> <description.txt>

Performs the following checks:
  - Include directive is present
  - Resource types match C typedefs
  - Struct field counts match C struct definitions
  - Packed structs have [packed] attribute in syzlang
  - ioctl pointer directions match _IOW/_IOR/_IOWR
  - Flag constants reference valid #define'd constants
"""

import re
import sys
from collections import defaultdict


def extract_constants(header):
    """Extract #define constants and their values from the header."""
    constants = {}
    for match in re.finditer(
        r'^#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\s*(?:/\*.*?\*/)?$',
        header, re.MULTILINE
    ):
        name, value = match.groups()
        try:
            constants[name] = int(value, 0)
        except ValueError:
            constants[name] = value
    return constants


def extract_typedefs(header):
    """Extract typedef mappings from C types to syzlang types."""
    typedefs = {}
    type_map = {
        '__u8': 'int8', '__u16': 'int16',
        '__u32': 'int32', '__u64': 'int64'
    }
    for match in re.finditer(r'typedef\s+(__u\d+)\s+(\w+)\s*;', header):
        c_type, name = match.groups()
        typedefs[name] = type_map.get(c_type, 'intptr')
    return typedefs


def extract_struct_fields(header):
    """Extract struct definitions and their field names from the header."""
    structs = {}
    for match in re.finditer(
        r'struct\s+(\w+)\s*\{(.*?)\}', header, re.DOTALL
    ):
        name = match.group(1)
        body = match.group(2)
        fields = []
        for line in body.split('\n'):
            line = line.strip()
            if not line or line.startswith('/*') or line.startswith('*') \
                    or line.startswith('//'):
                continue
            if line.startswith('union') or \
                    line.startswith('struct') and '{' in line:
                continue
            if line in ('};', '}'):
                continue
            field_m = re.match(
                r'(?:(?:struct\s+)?\w+)\s+(\w+)(?:\s*\[.*?\])?\s*;',
                line
            )
            if field_m:
                fields.append(field_m.group(1))
        structs[name] = fields
    return structs


def extract_packed_structs(header):
    """Find structs declared with __attribute__((packed))."""
    packed = set()
    for match in re.finditer(
        r'struct\s+(\w+)\s*\{.*?\}\s*__attribute__\s*\(\s*\(\s*packed\s*\)\s*\)',
        header, re.DOTALL
    ):
        packed.add(match.group(1))
    return packed


def extract_ioctls(header):
    """Extract ioctl definitions and their direction macros."""
    ioctls = {}
    for match in re.finditer(
        r'#define\s+(\w+)\s+(_IOW|_IOR|_IOWR)',
        header
    ):
        name, direction = match.groups()
        ioctls[name] = direction
    return ioctls


# ---- syzlang parsers ----

def parse_syzlang_resources(content):
    """Parse resource definitions from syzlang."""
    resources = {}
    for match in re.finditer(r'resource\s+(\w+)\s*\[\s*(\w+)\s*\]', content):
        resources[match.group(1)] = match.group(2)
    return resources


def parse_syzlang_structs(content):
    """Parse struct definitions from syzlang."""
    structs = {}
    for match in re.finditer(
        r'^(\w+)\s*\{(.*?)\}(\s*\[.*?\])?',
        content, re.DOTALL | re.MULTILINE
    ):
        name = match.group(1)
        body = match.group(2)
        attrs = match.group(3) or ''
        fields = []
        for line in body.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split()
                if parts:
                    fields.append(parts[0])
        structs[name] = {'fields': fields, 'attrs': attrs.strip()}
    return structs


def parse_syzlang_ioctls(content):
    """Parse ioctl pointer directions from syzlang."""
    ioctls = {}
    for match in re.finditer(
        r'ioctl\$(\w+)\([^)]*ptr\s*\[\s*(\w+)', content
    ):
        ioctls[match.group(1)] = match.group(2)
    return ioctls


def parse_syzlang_flags(content):
    """Parse flag set definitions from syzlang."""
    flags = {}
    for match in re.finditer(r'^(\w+)\s*=\s*(.+)$', content, re.MULTILINE):
        name = match.group(1)
        consts = [c.strip() for c in match.group(2).split(',')]
        flags[name] = consts
    return flags


def parse_syzlang_include(content):
    """Check for include directive."""
    return re.search(r'^include\s+<(.+?)>', content, re.MULTILINE)


def validate(header_path, syzlang_path):
    """Run all validation checks and return a list of error strings."""
    with open(header_path) as f:
        header = f.read()
    with open(syzlang_path) as f:
        syzlang = f.read()

    errors = []

    # Extract header information
    constants = extract_constants(header)
    typedefs = extract_typedefs(header)
    header_structs = extract_struct_fields(header)
    packed = extract_packed_structs(header)
    ioctls = extract_ioctls(header)

    # Parse syzlang
    sz_resources = parse_syzlang_resources(syzlang)
    sz_structs = parse_syzlang_structs(syzlang)
    sz_ioctls = parse_syzlang_ioctls(syzlang)
    sz_flags = parse_syzlang_flags(syzlang)
    inc = parse_syzlang_include(syzlang)

    # 1. Check include directive
    if not inc:
        errors.append("Missing include directive for UAPI header")

    # 2. Check resource types against typedefs
    for res_name, res_type in sz_resources.items():
        if res_name.startswith('fd_'):
            continue  # fd-based resources are special
        typedef_name = res_name + '_t'
        if typedef_name in typedefs:
            expected = typedefs[typedef_name]
            if expected != res_type:
                errors.append(
                    f"Resource '{res_name}' has base type '{res_type}' "
                    f"but C typedef '{typedef_name}' maps to '{expected}'"
                )

    # 3. Check struct field counts
    for sz_name, sz_info in sz_structs.items():
        if sz_name in header_structs:
            h_count = len(header_structs[sz_name])
            s_count = len(sz_info['fields'])
            if h_count != s_count:
                errors.append(
                    f"Struct '{sz_name}': header has {h_count} fields "
                    f"but syzlang has {s_count}"
                )

    # 4. Check packed attributes
    for sz_name, sz_info in sz_structs.items():
        if sz_name in packed:
            if 'packed' not in sz_info['attrs']:
                errors.append(
                    f"Struct '{sz_name}' has __attribute__((packed)) in C "
                    f"but is missing [packed] in syzlang"
                )
        elif sz_name in header_structs:
            if 'packed' in sz_info['attrs']:
                errors.append(
                    f"Struct '{sz_name}' is NOT packed in C "
                    f"but has [packed] in syzlang"
                )

    # 5. Check ioctl pointer directions
    for ioc_name, direction in ioctls.items():
        if ioc_name in sz_ioctls:
            sz_dir = sz_ioctls[ioc_name]
            if direction == '_IOW' and sz_dir != 'in':
                errors.append(
                    f"ioctl '{ioc_name}' uses _IOW but syzlang has "
                    f"ptr[{sz_dir}] (expected ptr[in])"
                )
            elif direction == '_IOR' and sz_dir != 'out':
                errors.append(
                    f"ioctl '{ioc_name}' uses _IOR but syzlang has "
                    f"ptr[{sz_dir}] (expected ptr[out])"
                )
            elif direction == '_IOWR' and sz_dir != 'inout':
                errors.append(
                    f"ioctl '{ioc_name}' uses _IOWR but syzlang has "
                    f"ptr[{sz_dir}] (expected ptr[inout])"
                )

    # 6. Check flag constants exist
    for flag_name, flag_consts in sz_flags.items():
        for const_name in flag_consts:
            if const_name not in constants:
                errors.append(
                    f"Flag set '{flag_name}' references unknown "
                    f"constant '{const_name}'"
                )

    return errors


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <header.h> <description.txt>",
              file=sys.stderr)
        sys.exit(2)

    errors = validate(sys.argv[1], sys.argv[2])
    if errors:
        print(f"Found {len(errors)} error(s):")
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}")
        sys.exit(1)
    else:
        print("Validation passed: 0 errors")
        sys.exit(0)


if __name__ == '__main__':
    main()
