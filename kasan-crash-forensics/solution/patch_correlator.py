
"""
Patch-crash correlation analysis.
Parses unified diffs and scores how likely a patch addresses
a given KASAN crash based on file/function overlap with crash stacks.
"""

import re


def parse_diff(text):
    """
    Parse a unified diff.

    Returns:
        dict with keys:
            files: list[str] - files modified by the patch
            functions: list[str] - functions modified (from @@ headers)
            added_lines: list[str] - lines added (without '+' prefix)
            removed_lines: list[str] - lines removed (without '-' prefix)
    """
    files = set()
    functions = set()
    added_lines = []
    removed_lines = []

    for line in text.split('\n'):
        # File headers: --- a/path or +++ b/path
        if line.startswith('--- a/'):
            path = line[6:].strip()
            if path != '/dev/null':
                files.add(path)
        elif line.startswith('+++ b/'):
            path = line[6:].strip()
            if path != '/dev/null':
                files.add(path)

        # Hunk header: @@ -N,N +N,N @@ optional function context
        hunk_m = re.match(r'@@ [^@]+ @@\s*(.*)', line)
        if hunk_m:
            func_ctx = hunk_m.group(1).strip()
            if func_ctx:
                # Extract function name: skip return type / qualifiers,
                # capture the last identifier before '('
                func_m = re.match(r'(?:[\w*]+\s+)*(\w+)\s*\(', func_ctx)
                if func_m:
                    functions.add(func_m.group(1))

        # Added / removed lines
        if line.startswith('+') and not line.startswith('+++'):
            added_lines.append(line[1:])
        elif line.startswith('-') and not line.startswith('---'):
            removed_lines.append(line[1:])

    return {
        'files': sorted(files),
        'functions': sorted(functions),
        'added_lines': added_lines,
        'removed_lines': removed_lines,
    }


def correlate(report, patch_text):
    """
    Correlate a parsed crash report with a candidate patch.

    Args:
        report: dict - output of kasan_parser.parse_report()
        patch_text: str - unified diff text

    Returns:
        dict with keys:
            touches_faulting_function: bool
            file_overlap: list[str] - patched files found in crash stacks
            function_overlap: list[str] - patched functions found in stacks
            plausibility_score: float (0.0-1.0)
    """
    diff = parse_diff(patch_text)
    patch_files = set(diff['files'])
    patch_functions = set(diff['functions'])

    # Collect all files and functions from all stacks
    stack_files = set()
    stack_functions = set()

    for key in ('call_stack', 'alloc_stack', 'free_stack'):
        stack = report.get(key)
        if not stack:
            continue
        for entry in stack:
            fn = entry.get('function', '')
            if fn:
                stack_functions.add(fn)
            loc = entry.get('location', '')
            if ':' in loc:
                f = loc.rsplit(':', 1)[0]
                stack_files.add(f)

    # Also include source_location
    src = report.get('source_location')
    if src and src.get('file'):
        stack_files.add(src['file'])

    faulting = report.get('faulting_function', '')

    file_overlap = sorted(patch_files & stack_files)
    function_overlap = sorted(patch_functions & stack_functions)
    touches_faulting = faulting in patch_functions

    # Compute plausibility score
    score = 0.0

    # File overlap: patch touches files mentioned in crash stacks
    if file_overlap:
        score += 0.3

    # Function overlap
    if touches_faulting:
        score += 0.4
    elif function_overlap:
        score += 0.2

    # Additional credit for having function-level overlap
    if function_overlap and not touches_faulting:
        score += 0.1

    score = min(score, 1.0)

    return {
        'touches_faulting_function': touches_faulting,
        'file_overlap': file_overlap,
        'function_overlap': function_overlap,
        'plausibility_score': round(score, 2),
    }
