#!/usr/bin/env python3
"""

OpenFOAM blockMeshDict parser and CHT mesh analyzer.

Parses the OpenFOAM dictionary format, computes mesh statistics,
detects block adjacency, classifies solid/fluid regions, and
solves the analytical 1D conjugate heat transfer problem.
"""
import json
import math
import re
import sys


# ---------------------------------------------------------------------------
# Tokenizer / Parser for OpenFOAM dictionary format
# ---------------------------------------------------------------------------

def strip_comments(text):
    """Remove C-style block comments and C++ line comments."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def tokenize(text):
    """Split cleaned text into tokens: words, numbers, and delimiters."""
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c in '(){};':
            tokens.append(c)
            i += 1
            continue
        if c == '-' or c == '+' or c == '.' or c.isdigit():
            j = i
            if c in '-+':
                j += 1
                if j >= n or (not text[j].isdigit() and text[j] != '.'):
                    # Not a number, treat as word
                    while j < n and not text[j].isspace() and text[j] not in '(){};':
                        j += 1
                    tokens.append(text[i:j])
                    i = j
                    continue
            while j < n and (text[j].isdigit() or text[j] in '.eE'):
                j += 1
            # Handle exponent sign
            if j < n and j >= 2 and text[j - 1] in 'eE' and text[j] in '+-':
                j += 1
                while j < n and text[j].isdigit():
                    j += 1
            tokens.append(text[i:j])
            i = j
            continue
        if c.isalpha() or c in '_"#':
            j = i
            while j < n and not text[j].isspace() and text[j] not in '(){};':
                j += 1
            tokens.append(text[i:j])
            i = j
            continue
        i += 1
    return tokens


def parse_list(tokens, pos):
    """Parse a parenthesized list recursively. Returns (items, new_pos)."""
    assert tokens[pos] == '(', f"Expected '(' at pos {pos}, got '{tokens[pos]}'"
    pos += 1
    items = []
    while pos < len(tokens) and tokens[pos] != ')':
        if tokens[pos] == '(':
            sublist, pos = parse_list(tokens, pos)
            items.append(sublist)
        else:
            tok = tokens[pos]
            try:
                val = float(tok)
                if val == int(val) and '.' not in tok and 'e' not in tok.lower():
                    val = int(val)
                items.append(val)
            except ValueError:
                items.append(tok)
            pos += 1
    assert pos < len(tokens) and tokens[pos] == ')', "Unmatched parenthesis"
    pos += 1
    return items, pos


def skip_brace_block(tokens, pos):
    """Skip a { ... } block, handling nesting."""
    assert tokens[pos] == '{'
    depth = 1
    pos += 1
    while depth > 0:
        if tokens[pos] == '{':
            depth += 1
        elif tokens[pos] == '}':
            depth -= 1
        pos += 1
    return pos


def parse_blockmeshdict(filepath):
    """Parse an OpenFOAM blockMeshDict file.

    Returns:
        vertices: list of [x, y, z] coordinate lists
        blocks: list of dicts with 'vertices', 'cells', 'grading' keys
        boundaries: dict of patch_name -> {'type': str, 'faces': list}
    """
    with open(filepath) as f:
        text = f.read()

    text = strip_comments(text)
    tokens = tokenize(text)

    vertices = []
    blocks = []
    boundaries = {}
    scale = 1.0

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        if tok == 'FoamFile':
            i += 1
            i = skip_brace_block(tokens, i)

        elif tok == 'scale' or tok == 'convertToMeters':
            i += 1
            scale = float(tokens[i])
            i += 1
            if i < len(tokens) and tokens[i] == ';':
                i += 1

        elif tok == 'vertices':
            i += 1
            vert_list, i = parse_list(tokens, i)
            for v in vert_list:
                vertices.append([v[0] * scale, v[1] * scale, v[2] * scale])
            if i < len(tokens) and tokens[i] == ';':
                i += 1

        elif tok == 'blocks':
            i += 1
            assert tokens[i] == '('
            i += 1
            while tokens[i] != ')':
                if tokens[i] == 'hex':
                    i += 1
                    hex_verts, i = parse_list(tokens, i)
                    cell_counts, i = parse_list(tokens, i)
                    # Expect 'simpleGrading' (or 'edgeGrading' which we don't handle)
                    assert tokens[i] == 'simpleGrading', (
                        f"Expected 'simpleGrading', got '{tokens[i]}'"
                    )
                    i += 1
                    grading, i = parse_list(tokens, i)
                    blocks.append({
                        'vertices': [int(v) for v in hex_verts],
                        'cells': [int(c) for c in cell_counts],
                        'grading': grading,
                    })
                else:
                    i += 1
            i += 1  # skip closing ')'
            if i < len(tokens) and tokens[i] == ';':
                i += 1

        elif tok in ('edges', 'mergePatchPairs'):
            i += 1
            if i < len(tokens) and tokens[i] == '(':
                _, i = parse_list(tokens, i)
            if i < len(tokens) and tokens[i] == ';':
                i += 1

        elif tok == 'boundary':
            i += 1
            assert tokens[i] == '('
            i += 1
            while tokens[i] != ')':
                patch_name = tokens[i]
                i += 1
                assert tokens[i] == '{'
                i += 1
                patch_type = None
                faces = []
                while tokens[i] != '}':
                    if tokens[i] == 'type':
                        i += 1
                        patch_type = tokens[i]
                        i += 1
                        if tokens[i] == ';':
                            i += 1
                    elif tokens[i] == 'faces':
                        i += 1
                        faces, i = parse_list(tokens, i)
                        if i < len(tokens) and tokens[i] == ';':
                            i += 1
                    else:
                        i += 1
                i += 1  # skip '}'
                boundaries[patch_name] = {'type': patch_type, 'faces': faces}
            i += 1  # skip closing ')'
            if i < len(tokens) and tokens[i] == ';':
                i += 1

        else:
            i += 1

    return vertices, blocks, boundaries


# ---------------------------------------------------------------------------
# Mesh analysis functions
# ---------------------------------------------------------------------------

def compute_cell_sizes(L, N, grading):
    """Compute first and last cell size given length, cell count, and grading.

    grading: either a scalar (simple expansion ratio R = last/first)
             or a list of [lengthFraction, cellFraction, expansionRatio]
             sub-segments (multi-grading).
    """
    if isinstance(grading, (int, float)):
        R = float(grading)
        if N <= 1:
            return L, L
        if abs(R - 1.0) < 1e-10:
            d = L / N
            return d, d
        r = R ** (1.0 / (N - 1))
        d_first = L * (r - 1.0) / (r ** N - 1.0)
        d_last = d_first * R
        return d_first, d_last

    elif isinstance(grading, list):
        # Multi-grading: each element is [lenFrac, cellFrac, expansion]
        # First cell is in the first segment; last cell is in the last segment
        first_seg = grading[0]
        L1 = first_seg[0] * L
        N1 = round(first_seg[1] * N)
        R1 = first_seg[2]
        d_first, _ = compute_cell_sizes(L1, N1, R1)

        last_seg = grading[-1]
        L_last = last_seg[0] * L
        N_last = round(last_seg[1] * N)
        R_last = last_seg[2]
        _, d_last = compute_cell_sizes(L_last, N_last, R_last)

        return d_first, d_last

    else:
        raise ValueError(f"Unknown grading format: {type(grading)}")


def get_block_dimensions(block, vertices):
    """Compute block extent in each local direction from hex vertex coords.

    Returns (dx, dy, dz) - the lengths along the three block-local axes.
    For a hex(v0 v1 v2 v3 v4 v5 v6 v7):
      direction 1 (x): v0 -> v1
      direction 2 (y): v0 -> v3
      direction 3 (z): v0 -> v4
    """
    v = block['vertices']
    p0 = vertices[v[0]]
    p1 = vertices[v[1]]
    p3 = vertices[v[3]]
    p4 = vertices[v[4]]

    dx = math.sqrt(sum((p1[k] - p0[k]) ** 2 for k in range(3)))
    dy = math.sqrt(sum((p3[k] - p0[k]) ** 2 for k in range(3)))
    dz = math.sqrt(sum((p4[k] - p0[k]) ** 2 for k in range(3)))
    return dx, dy, dz


def find_adjacencies(blocks):
    """Find block pairs sharing a face (>= 4 common vertex indices)."""
    adjacencies = []
    nb = len(blocks)
    for i in range(nb):
        si = set(blocks[i]['vertices'])
        for j in range(i + 1, nb):
            sj = set(blocks[j]['vertices'])
            if len(si & sj) >= 4:
                adjacencies.append([i, j])
    return adjacencies


def classify_region(block, vertices, heater_region):
    """Classify a block as 'solid' or 'fluid' based on bounding-box match."""
    v = block['vertices']
    xs = [vertices[vi][0] for vi in v]
    ys = [vertices[vi][1] for vi in v]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    hx = heater_region['x_range']
    hy = heater_region['y_range']

    tol = 1e-6
    if (abs(x_min - hx[0]) < tol and abs(x_max - hx[1]) < tol and
            abs(y_min - hy[0]) < tol and abs(y_max - hy[1]) < tol):
        return "solid"
    return "fluid"


def compute_cht(params, blocks, vertices, adjacencies):
    """Compute analytical 1D steady-state CHT solution.

    Physics:
      d²T/dy² = -q_gen / k_s  in the solid heater
      BC at y=0 (bottom): dT/dy = 0  (adiabatic)
      BC at y=H (top):    -k_s * dT/dy = h * (T - T_fluid)  (convective)

    Solution:
      T(y) = -q_gen/(2*k_s) * y² + C2
      Heat flux at interface: q_flux = q_gen * H
      Interface temperature: T_int = T_f + q_flux / h
      Max temperature: T_max = T_int + q_gen/(2*k_s) * H²
    """
    tp = params['thermal_properties']
    k_s = tp['solid_conductivity']
    q_gen = tp['volumetric_heat_generation']
    T_f = tp['fluid_bulk_temperature']
    h_conv = tp['convective_htc']

    heater = params['heater_region']
    H = heater['y_range'][1] - heater['y_range'][0]

    # Find solid block
    solid_block = None
    for idx, b in enumerate(blocks):
        if classify_region(b, vertices, heater) == "solid":
            solid_block = idx
            break

    # Find fluid block directly above the heater
    fluid_interface_block = None
    for adj in adjacencies:
        if solid_block in adj:
            other = adj[0] if adj[1] == solid_block else adj[1]
            v = blocks[other]['vertices']
            y_vals = [vertices[vi][1] for vi in v]
            # Block above heater has y_min at the heater top
            if abs(min(y_vals) - heater['y_range'][1]) < 1e-6:
                fluid_interface_block = other
                break

    q_flux = q_gen * H
    T_interface = T_f + q_flux / h_conv
    T_max = T_interface + q_gen / (2.0 * k_s) * H ** 2

    return {
        'solid_block': solid_block,
        'fluid_interface_block': fluid_interface_block,
        'interface_temperature_K': round(T_interface, 4),
        'max_heater_temperature_K': round(T_max, 4),
        'interface_heat_flux_W_m2': round(q_flux, 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    bmdict_path = '/app/case/system/blockMeshDict'
    params_path = '/app/case/cht_params.json'
    output_path = '/app/mesh_report.json'

    # Parse inputs
    vertices, blocks_raw, _ = parse_blockmeshdict(bmdict_path)
    with open(params_path) as f:
        params = json.load(f)

    # Build per-block info
    block_info = []
    total_cells = 0
    for idx, b in enumerate(blocks_raw):
        dims = get_block_dimensions(b, vertices)
        nx, ny, nz = b['cells']
        tc = nx * ny * nz
        total_cells += tc

        gy = b['grading'][1]  # y-direction grading
        first_y, last_y = compute_cell_sizes(dims[1], ny, gy)

        region = classify_region(b, vertices, params['heater_region'])

        block_info.append({
            'id': idx,
            'vertices': b['vertices'],
            'cell_count': [nx, ny, nz],
            'total_cells': tc,
            'region': region,
            'first_cell_height_y': first_y,
            'last_cell_height_y': last_y,
        })

    # Adjacency
    adjacencies = find_adjacencies(blocks_raw)

    # CHT analysis
    cht = compute_cht(params, blocks_raw, vertices, adjacencies)

    # Assemble report
    report = {
        'num_vertices': len(vertices),
        'num_blocks': len(blocks_raw),
        'total_cells': total_cells,
        'blocks': block_info,
        'adjacency': adjacencies,
        'cht': cht,
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Mesh report written to {output_path}")
    print(f"  Vertices: {len(vertices)}")
    print(f"  Blocks:   {len(blocks_raw)}")
    print(f"  Cells:    {total_cells}")
    print(f"  Adjacencies: {len(adjacencies)}")
    print(f"  CHT interface temp: {cht['interface_temperature_K']} K")


if __name__ == '__main__':
    main()
