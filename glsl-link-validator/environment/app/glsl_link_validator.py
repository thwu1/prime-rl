#!/usr/bin/env python3
"""GLSL ES 3.00 Shader Link-Time Conformance Validator"""
import json
import re
import sys


def strip_comments(source):
    """Remove C-style comments from GLSL source."""
    result = []
    i = 0
    while i < len(source):
        if i + 1 < len(source) and source[i] == '/' and source[i + 1] == '/':
            while i < len(source) and source[i] != '\n':
                i += 1
        elif i + 1 < len(source) and source[i] == '/' and source[i + 1] == '*':
            i += 2
            while i + 1 < len(source) and not (source[i] == '*' and source[i + 1] == '/'):
                i += 1
            i += 2
        else:
            result.append(source[i])
            i += 1
    return ''.join(result)


def strip_preprocessor(source):
    """Remove all preprocessor directives."""
    lines = source.split('\n')
    return '\n'.join(
        line for line in lines
        if not line.strip().startswith('#')
    )


def parse_structs(source):
    """Parse struct definitions returning {name: [(member_name, member_type), ...]}."""
    structs = {}
    for m in re.finditer(r'struct\s+(\w+)\s*\{([^}]*)\}', source):
        name = m.group(1)
        body = m.group(2)
        members = []
        for decl in body.split(';'):
            decl = decl.strip()
            if not decl:
                continue
            parts = decl.split()
            if len(parts) >= 2:
                members.append((parts[1].rstrip(';'), parts[0]))
        structs[name] = members
    return structs


def parse_declarations(source, structs):
    """Extract in/out/uniform declarations from preprocessed GLSL source."""
    decls = []
    for segment in source.split(';'):
        segment = segment.strip()
        if not segment:
            continue
        if 'void ' in segment or '(' in segment or '{' in segment or '}' in segment:
            continue

        storage = None
        for sq in ['out', 'in', 'uniform']:
            if re.search(r'\b' + sq + r'\b', segment):
                storage = sq
                break
        if not storage:
            continue

        # Layout location
        location = None
        loc_m = re.search(r'layout\(location=(\d+)\)', segment)
        if loc_m:
            location = int(loc_m.group(1))

        # Interpolation qualifier
        interpolation = 'smooth'
        if re.search(r'\bflat\b', segment):
            interpolation = 'flat'
        elif re.search(r'\bcentroid\b', segment):
            interpolation = 'centroid'

        # Invariant flag
        invariant = bool(re.search(r'\binvariant\b', segment))

        # Precision qualifier
        precision = None
        for p in ['highp', 'mediump', 'lowp']:
            if re.search(r'\b' + p + r'\b', segment):
                precision = p
                break

        # Strip all qualifiers to isolate type and variable names
        cleaned = segment
        for pat in [r'layout\s*\([^)]*\)', r'\bflat\b', r'\bsmooth\b', r'\bcentroid\b',
                    r'\binvariant\b', r'\bout\b', r'\bin\b', r'\buniform\b',
                    r'\bhighp\b', r'\bmediump\b', r'\blowp\b']:
            cleaned = re.sub(pat, '', cleaned)
        cleaned = cleaned.strip()
        if not cleaned:
            continue

        # Extract type and variable name(s)
        m = re.match(r'(\w+)\s+([\w,\s\[\]]+)', cleaned)
        if not m:
            continue

        base_type = m.group(1)
        names_str = m.group(2)

        # Split variable names from declaration
        var_names = [names_str.split(',')[0].strip()]

        for vn in var_names:
            if not vn:
                continue
            arr = re.match(r'(\w+)\s*\[(\d+)\]', vn)
            vs = None
            if arr:
                vn = arr.group(1)
                vs = int(arr.group(2))
            else:
                vn_m = re.match(r'(\w+)', vn)
                if vn_m:
                    vn = vn_m.group(1)

            decls.append({
                'storage': storage,
                'name': vn,
                'type': base_type,
                'precision': precision,
                'interpolation': interpolation,
                'invariant': invariant,
                'array_size': vs,
                'location': location,
                'struct_members': structs.get(base_type),
            })
    return decls


def validate_link(vert_src, frag_src):
    """Validate link-time compatibility between vertex and fragment shaders."""
    errors = []

    vert_clean = strip_preprocessor(strip_comments(vert_src))
    frag_clean = strip_preprocessor(strip_comments(frag_src))

    vert_structs = parse_structs(vert_clean)
    frag_structs = parse_structs(frag_clean)

    vert_decls = parse_declarations(vert_clean, vert_structs)
    frag_decls = parse_declarations(frag_clean, frag_structs)

    vert_outs = {d['name']: d for d in vert_decls if d['storage'] == 'out'}
    vert_unis = {d['name']: d for d in vert_decls if d['storage'] == 'uniform'}
    frag_ins = {d['name']: d for d in frag_decls if d['storage'] == 'in'}
    frag_unis = {d['name']: d for d in frag_decls if d['storage'] == 'uniform'}

    for name, fd in frag_ins.items():
        if name.startswith('gl_'):
            continue
        if name not in vert_outs:
            errors.append({'category': 'MISSING_VERTEX_OUTPUT', 'variable': name})
            continue

        vd = vert_outs[name]

        # Type check
        if vd['type'] != fd['type']:
            errors.append({'category': 'TYPE_MISMATCH', 'variable': name})
            continue

        # Precision (only when both carry explicit qualifiers)
        if vd['precision'] and fd['precision'] and vd['precision'] != fd['precision']:
            errors.append({'category': 'PRECISION_MISMATCH', 'variable': name})

        # Interpolation
        if vd['interpolation'] != fd['interpolation']:
            errors.append({'category': 'INTERPOLATION_MISMATCH', 'variable': name})

        # Invariant
        if vd['invariant']:
            errors.append({'category': 'INVARIANT_MISMATCH', 'variable': name})

        # Array size
        if vd['array_size'] != fd['array_size']:
            errors.append({'category': 'ARRAY_SIZE_MISMATCH', 'variable': name})

        # Struct (structural comparison)
        if vd['struct_members'] is not None and fd['struct_members'] is not None:
            if set(vd['struct_members']) != set(fd['struct_members']):
                errors.append({'category': 'STRUCT_MISMATCH', 'variable': name})

        # Location
        if vd['location'] is not None and fd['location'] is not None:
            if vd['location'] != fd['location']:
                errors.append({'category': 'LOCATION_MISMATCH', 'variable': name})

    # Uniform consistency
    for name in set(vert_unis) & set(frag_unis):
        if vert_unis[name]['type'] != frag_unis[name]['type']:
            errors.append({'category': 'UNIFORM_TYPE_MISMATCH', 'variable': name})

    return {'valid': len(errors) == 0, 'errors': errors}


def main():
    if len(sys.argv) != 3:
        print("Usage: glsl_link_validator.py <vertex.vert> <fragment.frag>",
              file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        vert = f.read()
    with open(sys.argv[2]) as f:
        frag = f.read()
    print(json.dumps(validate_link(vert, frag)))


if __name__ == '__main__':
    main()
