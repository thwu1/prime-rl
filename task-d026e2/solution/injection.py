"""
Code injection engine for held-out shape replacement.

Implements three text-based codegen injection strategies:
1. Bracket-balanced TEST_SHAPES replacement
2. Indentation-based function replacement
3. Exact substring (raw) replacement
"""
import re


def _find_bracket_end(text, start):
    """Find closing bracket matching the opening bracket at `start`."""
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def replace_test_shapes(source, replacement_code):
    """
    Replace a TEST_SHAPES = [...] block using bracket balancing.

    Finds the assignment via regex (ensuring it's exactly TEST_SHAPES, not a
    longer name like TEST_SHAPES_EXTENDED), then uses bracket balancing to
    locate the full extent of the list literal.
    """
    # Match TEST_SHAPES followed by = (not TEST_SHAPES_SOMETHING)
    pattern = re.compile(r'^([ \t]*)TEST_SHAPES\s*=\s*\[', re.MULTILINE)
    match = pattern.search(source)
    if not match:
        raise ValueError("Could not find 'TEST_SHAPES = [' in source")

    # Verify it's exactly TEST_SHAPES (not a longer name)
    # Check that the character before TEST_SHAPES (if any) is not a word char
    start_pos = match.start()
    indent = match.group(1)
    name_start = start_pos + len(indent)

    # Check character after TEST_SHAPES
    after_name = name_start + len('TEST_SHAPES')
    if after_name < len(source) and (source[after_name].isalnum() or source[after_name] == '_'):
        # This is a longer name like TEST_SHAPES_EXTENDED; search further
        remaining = source[match.end():]
        # Try to find another match after this one
        match2 = pattern.search(source, match.end())
        if match2:
            match = match2
            indent = match.group(1)
        else:
            raise ValueError("Could not find standalone 'TEST_SHAPES = [' in source")

    bracket_start = source.index('[', match.start())
    bracket_end = _find_bracket_end(source, bracket_start)
    if bracket_end == -1:
        raise ValueError("Unbalanced brackets in TEST_SHAPES definition")

    # Consume trailing newline if present
    end = bracket_end + 1
    if end < len(source) and source[end] == '\n':
        end += 1

    # Indent the replacement to match the original
    indented_replacement = '\n'.join(
        (indent + line) if line.strip() else line
        for line in replacement_code.strip().splitlines()
    ) + '\n'

    return source[:match.start()] + indented_replacement + source[end:]


def _find_function_end(source, func_start):
    """
    Find the end of a top-level function definition starting at `func_start`.

    Uses indentation: the function body is all lines after the def line that
    are either blank, comment-only, or indented deeper than the def line.
    """
    lines = source[func_start:].split('\n')
    if not lines:
        return func_start

    def_line = lines[0]
    base_indent = len(def_line) - len(def_line.lstrip())

    consumed = len(lines[0]) + 1  # +1 for the newline
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == '' or stripped.startswith('#'):
            consumed += len(line) + 1
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= base_indent:
            break
        consumed += len(line) + 1

    return func_start + consumed


def replace_function(source, func_name, replacement_code):
    """
    Replace a top-level function definition using indentation analysis.

    Finds `def func_name(` via regex, detects the function end via
    indentation, and replaces the entire function.
    """
    pattern = re.compile(
        r'^([ \t]*)def ' + re.escape(func_name) + r'\s*\(',
        re.MULTILINE,
    )
    match = pattern.search(source)
    if not match:
        raise ValueError(f"Could not find 'def {func_name}(' in source")

    func_end = _find_function_end(source, match.start())
    indent = match.group(1)

    indented_replacement = '\n'.join(
        (indent + line) if line.strip() else line
        for line in replacement_code.strip().splitlines()
    ) + '\n'

    return source[:match.start()] + indented_replacement + source[func_end:]


def raw_replace(source, old_code, new_code):
    """
    Exact substring replacement.

    Raises ValueError if old_code is not found in source.
    """
    if old_code not in source:
        raise ValueError(
            f"old_code not found in source. "
            f"First 80 chars: {old_code[:80]!r}"
        )
    return source.replace(old_code, new_code, 1)


def apply_injection(source, injection_spec):
    """
    Dispatch to the appropriate injection strategy based on find_marker.

    - "TEST_SHAPES" -> replace_test_shapes
    - starts with "def " -> replace_function (extracts func name)
    - "raw_replace" -> raw_replace using old_code from spec
    """
    marker = injection_spec['find_marker']
    replacement = injection_spec['replacement_code']

    if marker == 'TEST_SHAPES':
        return replace_test_shapes(source, replacement)
    elif marker.startswith('def '):
        func_name = marker[4:].strip()
        return replace_function(source, func_name, replacement)
    elif marker == 'raw_replace':
        old_code = injection_spec['old_code']
        return raw_replace(source, old_code, replacement)
    else:
        raise ValueError(f"Unknown find_marker: {marker}")
