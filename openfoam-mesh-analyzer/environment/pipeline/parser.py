"""
OpenFOAM blockMeshDict parser.

Handles C/C++ style comments, nested parenthesized structures,
the FoamFile header, scale keyword, and multi-grading syntax.
"""
import re


def strip_comments(text):
    """Remove C-style block comments and C++ line comments."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def tokenize(text):
    """Split cleaned OpenFOAM dictionary text into tokens."""
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
                    while j < n and not text[j].isspace() and text[j] not in '(){};':
                        j += 1
                    tokens.append(text[i:j])
                    i = j
                    continue
            while j < n and (text[j].isdigit() or text[j] in '.eE'):
                j += 1
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
    assert tokens[pos] == '(', f"Expected '(' at pos {pos}"
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


def _normalize_grading(grading_raw):
    """Convert raw parsed grading into structured format.

    For each direction, grading is either:
      - A scalar expansion ratio (simple grading)
      - A list of sub-segments for multi-grading, where each segment
        in OpenFOAM is specified as (lengthFraction cellFraction expansionRatio)

    Internally we store segments as [nCellsFraction, lengthFraction, expansionRatio]
    to keep cell distribution as the leading field for downstream analysis.
    """
    grading = []
    for g in grading_raw:
        if isinstance(g, list):
            segments = []
            for seg in g:
                # Remap to internal layout: [nCellsFrac, lenFrac, expRatio]
                segments.append([seg[1], seg[0], seg[2]])
            grading.append(segments)
        else:
            grading.append(g)
    return grading


def parse_blockmeshdict(filepath):
    """Parse an OpenFOAM blockMeshDict file.

    Returns:
        vertices: list of [x, y, z] coordinate lists
        blocks: list of dicts with 'vertices', 'cells', 'grading' keys
    """
    with open(filepath) as f:
        text = f.read()

    text = strip_comments(text)
    tokens = tokenize(text)

    vertices = []
    blocks = []
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
                    assert tokens[i] == 'simpleGrading', (
                        f"Expected 'simpleGrading', got '{tokens[i]}'"
                    )
                    i += 1
                    grading_raw, i = parse_list(tokens, i)
                    grading = _normalize_grading(grading_raw)
                    blocks.append({
                        'vertices': [int(v) for v in hex_verts],
                        'cells': [int(c) for c in cell_counts],
                        'grading': grading,
                    })
                else:
                    i += 1
            i += 1
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
            if i < len(tokens) and tokens[i] == '(':
                _, i = parse_list(tokens, i)
            if i < len(tokens) and tokens[i] == ';':
                i += 1

        else:
            i += 1

    return vertices, blocks
