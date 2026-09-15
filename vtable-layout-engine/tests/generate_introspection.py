#!/usr/bin/env python3
"""
Generate C++ introspection programs for each test header.
Each program instantiates the classes, inspects object sizes,
base subobject offsets, and vtable metadata, then outputs JSON.

"""

import os
import re
import subprocess
import json
import sys

TEST_HEADERS_DIR = "/app/test_headers"
REFERENCE_DIR = "/app/reference_output"
INTROSPECT_DIR = "/app/introspect_build"

os.makedirs(REFERENCE_DIR, exist_ok=True)
os.makedirs(INTROSPECT_DIR, exist_ok=True)


def parse_header_classes(header_path):
    """
    Minimal parser to extract class names, base classes, virtual functions,
    and data members from a test header file.
    """
    with open(header_path) as f:
        content = f.read()

    # Strip // comments
    lines = []
    for line in content.split('\n'):
        idx = line.find('//')
        if idx != -1:
            line = line[:idx]
        lines.append(line)
    content = '\n'.join(lines)

    classes = []

    # Find each struct/class definition
    # Use a simpler approach: find 'struct X' or 'class X', then extract bases and body
    pattern = re.compile(r'(?:struct|class)\s+(\w+)')
    for m in pattern.finditer(content):
        class_name = m.group(1)
        pos = m.end()

        # Skip whitespace
        while pos < len(content) and content[pos] in ' \t\n\r':
            pos += 1

        # Check for base list
        bases_str = ""
        if pos < len(content) and content[pos] == ':':
            pos += 1
            brace_pos = content.find('{', pos)
            if brace_pos == -1:
                continue
            bases_str = content[pos:brace_pos].strip()
            pos = brace_pos

        # Find body between { and }
        if pos >= len(content) or content[pos] != '{':
            continue
        depth = 1
        body_start = pos + 1
        pos += 1
        while pos < len(content) and depth > 0:
            if content[pos] == '{':
                depth += 1
            elif content[pos] == '}':
                depth -= 1
            pos += 1
        body = content[body_start:pos - 1]

        # Parse bases
        bases = []
        if bases_str:
            for base_spec in re.split(r'\s*,\s*', bases_str):
                base_spec = base_spec.strip()
                if not base_spec:
                    continue
                is_virtual = 'virtual' in base_spec
                # Get the last word as the base name
                words = base_spec.split()
                base_name = words[-1] if words else ''
                if base_name:
                    bases.append({'name': base_name, 'is_virtual': is_virtual})

        # Parse virtual methods
        methods = []
        has_virtual = False
        for stmt in body.split(';'):
            stmt = stmt.strip()
            if not stmt:
                continue
            if 'virtual' in stmt:
                has_virtual = True
                is_pure = '= 0' in stmt
                line_clean = stmt.replace('virtual', '').strip()
                line_clean = re.sub(r'\s*=\s*0\s*', '', line_clean)
                line_clean = re.sub(r'\s*=\s*default\s*', '', line_clean)
                line_clean = line_clean.strip()

                # Try return_type name(params)
                func_match = re.match(r'(.+?)\s+(~?\w+)\s*\(([^)]*)\)', line_clean)
                if func_match:
                    methods.append({
                        'return_type': func_match.group(1).strip(),
                        'name': func_match.group(2).strip(),
                        'params': func_match.group(3).strip(),
                        'is_pure': is_pure,
                        'is_dtor': func_match.group(2).startswith('~')
                    })
                else:
                    # Try destructor: ~Name()
                    dtor_match = re.match(r'(~\w+)\s*\(([^)]*)\)', line_clean)
                    if dtor_match:
                        methods.append({
                            'return_type': 'void',
                            'name': dtor_match.group(1).strip(),
                            'params': dtor_match.group(2).strip(),
                            'is_pure': is_pure,
                            'is_dtor': True
                        })

        # Parse data members
        data_members = []
        for stmt in body.split(';'):
            stmt = stmt.strip()
            if not stmt or 'virtual' in stmt or '(' in stmt:
                continue
            mem_match = re.match(
                r'(int|double|long|char|float|short|long\s+long)\s+(\w+)', stmt)
            if mem_match:
                data_members.append({
                    'type': mem_match.group(1),
                    'name': mem_match.group(2)
                })

        classes.append({
            'name': class_name,
            'bases': bases,
            'methods': methods,
            'data_members': data_members,
            'has_virtual': has_virtual,
        })

    return classes


def get_all_bases_recursive(class_name, class_map, visited=None):
    """Get all direct and indirect base classes (unique, preserving order)."""
    if visited is None:
        visited = set()
    if class_name in visited:
        return []
    visited.add(class_name)

    result = []
    if class_name not in class_map:
        return result

    cls = class_map[class_name]
    for base in cls['bases']:
        if base['name'] not in visited:
            result.append(base)
        result.extend(get_all_bases_recursive(base['name'], class_map, visited))

    return result


def get_virtual_bases(class_name, class_map, visited=None):
    """Get all virtual bases (direct and indirect), unique."""
    if visited is None:
        visited = set()
    if class_name in visited:
        return []
    visited.add(class_name)

    result = []
    if class_name not in class_map:
        return result

    cls = class_map[class_name]
    for base in cls['bases']:
        if base['is_virtual']:
            if base['name'] not in [r['name'] for r in result]:
                result.append(base)
        indirect = get_virtual_bases(base['name'], class_map, visited)
        for ib in indirect:
            if ib['name'] not in [r['name'] for r in result]:
                result.append(ib)

    return result


def is_polymorphic(class_name, class_map):
    """Check if a class is polymorphic."""
    if class_name not in class_map:
        return False
    cls = class_map[class_name]
    if cls['has_virtual']:
        return True
    if cls['methods']:
        return True
    for base in cls['bases']:
        if is_polymorphic(base['name'], class_map):
            return True
    return False


def is_abstract(class_name, class_map, visited=None):
    """Check if a class is abstract (has unoverridden pure virtual methods)."""
    if visited is None:
        visited = set()
    if class_name not in class_map:
        return False

    # Collect all pure method names from all ancestors
    pure_methods = set()
    overridden_methods = set()

    def collect(cn, seen=None):
        if seen is None:
            seen = set()
        if cn in seen:
            return
        seen.add(cn)
        if cn not in class_map:
            return
        c = class_map[cn]
        for m in c['methods']:
            if m['is_pure']:
                pure_methods.add(m['name'])
            else:
                overridden_methods.add(m['name'])
        for b in c['bases']:
            collect(b['name'], seen)

    collect(class_name)

    for pm in pure_methods:
        if pm not in overridden_methods:
            return True
    return False


def generate_introspection_cpp(classes, header_path):
    """Generate a C++ program that introspects all polymorphic classes."""
    class_map = {c['name']: c for c in classes}

    lines = []
    lines.append('#include <cstdio>')
    lines.append('#include <cstddef>')
    lines.append('#include <cstdint>')
    lines.append('#include <cstring>')
    lines.append('#include <typeinfo>')
    lines.append('')
    lines.append(f'#include "{header_path}"')
    lines.append('')

    # Generate dummy implementations for all declared virtual functions
    for cls in classes:
        for method in cls['methods']:
            if method['is_pure']:
                continue
            if method['is_dtor']:
                lines.append(f'{cls["name"]}::{method["name"]}() {{}}')
            else:
                params = method['params']
                ret = method['return_type']
                if ret == 'void':
                    lines.append(
                        f'{ret} {cls["name"]}::{method["name"]}({params}) {{}}'
                    )
                elif '*' in ret:
                    lines.append(
                        f'{ret} {cls["name"]}::{method["name"]}({params})'
                        f' {{ return nullptr; }}'
                    )
                else:
                    lines.append(
                        f'{ret} {cls["name"]}::{method["name"]}({params})'
                        f' {{ return {ret}(); }}'
                    )
    lines.append('')

    # Main function
    lines.append('int main() {')
    lines.append('    printf("{\\n");')

    polymorphic_classes = [
        c for c in classes if is_polymorphic(c['name'], class_map)
    ]

    for idx, cls in enumerate(polymorphic_classes):
        cname = cls['name']
        abstract = is_abstract(cname, class_map)
        can_instantiate = not abstract
        comma = ',' if idx < len(polymorphic_classes) - 1 else ''

        # Open a block scope for this class
        lines.append(f'    {{ // {cname}')

        lines.append(f'    printf("  \\"{cname}\\": {{\\n");')
        lines.append(
            f'    printf("    \\"object_size\\": %zu,\\n", sizeof({cname}));')
        lines.append(
            f'    printf("    \\"object_align\\": %zu,\\n", alignof({cname}));')

        # Declare an actual object instance for offset calculations
        if can_instantiate:
            lines.append(f'    {cname} _inst;')

        # Subobject offsets
        all_bases = get_all_bases_recursive(cname, class_map)
        unique_bases = []
        seen = set()
        for b in all_bases:
            if b['name'] not in seen:
                unique_bases.append(b)
                seen.add(b['name'])

        lines.append(f'    printf("    \\"subobject_offsets\\": {{\\n");')
        for bidx, base in enumerate(unique_bases):
            bcomma = ',' if bidx < len(unique_bases) - 1 else ''
            bname = base['name']
            if can_instantiate:
                lines.append(
                    f'    {{'
                    f' {bname} *bp = static_cast<{bname}*>(&_inst);'
                    f' ptrdiff_t off = (char*)bp - (char*)&_inst;'
                    f' printf("      \\"{bname}\\": %td{bcomma}\\n", off);'
                    f' }}'
                )
            else:
                lines.append(
                    f'    printf("      \\"{bname}\\": -1{bcomma}\\n");')

        lines.append(f'    printf("    }},\\n");')

        # Virtual base offsets
        vbases = get_virtual_bases(cname, class_map)
        lines.append(f'    printf("    \\"vbase_offsets\\": {{\\n");')
        for vidx, vbase in enumerate(vbases):
            vcomma = ',' if vidx < len(vbases) - 1 else ''
            vname = vbase['name']
            if can_instantiate:
                lines.append(
                    f'    {{'
                    f' {vname} *vp = static_cast<{vname}*>(&_inst);'
                    f' ptrdiff_t off = (char*)vp - (char*)&_inst;'
                    f' printf("      \\"{vname}\\": %td{vcomma}\\n", off);'
                    f' }}'
                )
            else:
                lines.append(
                    f'    printf("      \\"{vname}\\": -1{vcomma}\\n");')

        lines.append(f'    printf("    }}\\n");')
        lines.append(f'    printf("  }}{comma}\\n");')

        # Close block scope
        lines.append(f'    }} // end {cname}')

    lines.append('    printf("}\\n");')
    lines.append('    return 0;')
    lines.append('}')

    return '\n'.join(lines)


def main():
    for fname in sorted(os.listdir(TEST_HEADERS_DIR)):
        if not fname.startswith("test") or not fname.endswith(".h"):
            continue

        base_name = fname.replace(".h", "")
        header_path = os.path.join(TEST_HEADERS_DIR, fname)

        print(f"Processing {fname}...")

        classes = parse_header_classes(header_path)
        if not classes:
            print(f"  Warning: no classes found in {fname}")
            continue

        # Generate introspection C++ program
        cpp_code = generate_introspection_cpp(classes, header_path)
        cpp_path = os.path.join(INTROSPECT_DIR, f"{base_name}_introspect.cpp")
        bin_path = os.path.join(INTROSPECT_DIR, f"{base_name}_introspect")

        with open(cpp_path, 'w') as f:
            f.write(cpp_code)

        # Compile
        result = subprocess.run(
            ['g++', '-std=c++17', '-O0', '-o', bin_path, cpp_path],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            print(f"  Compilation failed for {base_name}: {result.stderr}")
            ref_path = os.path.join(REFERENCE_DIR, f"{base_name}.ref.json")
            with open(ref_path, 'w') as f:
                json.dump({}, f)
            continue

        # Run
        result = subprocess.run(
            [bin_path], capture_output=True, text=True, timeout=10
        )

        if result.returncode != 0:
            print(f"  Runtime error for {base_name}: {result.stderr}")
            ref_path = os.path.join(REFERENCE_DIR, f"{base_name}.ref.json")
            with open(ref_path, 'w') as f:
                json.dump({}, f)
            continue

        # Parse JSON output
        try:
            ref_data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"  JSON parse error for {base_name}: {e}")
            print(f"  Output was: {result.stdout[:500]}")
            ref_data = {}

        ref_path = os.path.join(REFERENCE_DIR, f"{base_name}.ref.json")
        with open(ref_path, 'w') as f:
            json.dump(ref_data, f, indent=2)

        print(f"  Generated reference for {len(ref_data)} classes")


if __name__ == '__main__':
    main()
