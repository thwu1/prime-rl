#!/usr/bin/env python3
"""IPC-1 Prefetcher Storage Budget Auditor.

Statically analyzes IPC-1 instruction prefetcher C++ source files to:
1. Resolve #define macros to integer values
2. Evaluate C-style arithmetic expressions using resolved macros
3. Extract and compute storage budgets from l1i_prefetcher_final_stats()

"""

import sys
import json
import re


def strip_comments(source):
    """Remove C/C++ comments from source code."""
    # Remove block comments
    source = re.sub(r'/\*.*?\*/', ' ', source, flags=re.DOTALL)
    # Remove line comments
    lines = []
    for line in source.split('\n'):
        idx = line.find('//')
        if idx >= 0:
            line = line[:idx]
        lines.append(line)
    return '\n'.join(lines)


def extract_defines(source):
    """Extract all #define macros from source code.

    Returns dict of name -> raw expression string.
    Skips flag defines (no value) and function-like macros (with parameters).
    """
    cleaned = strip_comments(source)
    defines = {}

    for line in cleaned.split('\n'):
        stripped = line.strip()
        if not stripped.startswith('#define'):
            continue

        rest = stripped[len('#define'):].strip()

        # Extract name: sequence of word chars
        name_match = re.match(r'(\w+)', rest)
        if not name_match:
            continue
        name = name_match.group(1)
        after_name = rest[len(name):]

        # Skip function-like macros: #define NAME(...)
        if after_name.startswith('('):
            continue

        # Get value (everything after whitespace following the name)
        value = after_name.strip()
        if not value:
            continue  # Flag define, no value

        defines[name] = value

    return defines


def substitute_macros(expr, resolved):
    """Replace macro identifiers in an expression with their resolved integer values."""
    # Remove C type casts like (uint64_t), (int64_t), (int), (unsigned)
    expr = re.sub(r'\(\s*(?:u?int(?:8|16|32|64)_t|unsigned\s+(?:long|int)|long\s+long|long|int|char|short)\s*\)', '', expr)

    def replacer(match):
        name = match.group(0)
        if name in resolved:
            return str(resolved[name])
        return name

    return re.sub(r'\b[A-Za-z_]\w*\b', replacer, expr)


def try_evaluate(expr, resolved):
    """Try to evaluate a C-style integer expression.

    Returns integer value on success, None if unresolved identifiers remain.
    Uses C-style integer division (truncation toward zero for positive operands).
    """
    substituted = substitute_macros(expr, resolved)

    # Check if any identifiers remain unresolved
    if re.search(r'[A-Za-z_]\w*', substituted):
        return None

    # Replace / with // for integer division (C-style)
    # Avoid replacing existing // or /= operators
    int_div_expr = re.sub(r'(?<!/)/(?![/=])', '//', substituted)

    try:
        result = eval(int_div_expr, {"__builtins__": {}})
        return int(result)
    except Exception:
        return None


def resolve_all_macros(raw_defines):
    """Iteratively resolve all macros to integer values.

    Handles dependency ordering automatically through repeated passes.
    """
    resolved = {}
    unresolved = dict(raw_defines)

    for _ in range(100):
        if not unresolved:
            break
        progress = False
        for name in list(unresolved.keys()):
            value = try_evaluate(unresolved[name], resolved)
            if value is not None:
                resolved[name] = value
                del unresolved[name]
                progress = True
        if not progress:
            break

    return resolved


def resolve_member_variables(source, resolved_macros):
    """Resolve class member variables set through init() method calls.

    Traces patterns like:
        ClassName INSTANCE;
        INSTANCE.init(ARG1, ARG2);
    Then parses the init() method to compute member variable values.

    Returns dict of "INSTANCE.MEMBER" -> integer value.
    """
    members = {}
    cleaned = strip_comments(source)

    # Find global object declarations: ClassName OBJECTNAME;
    # Collect object -> class mappings
    objects = {}
    for m in re.finditer(r'\b(\w+)\s+(\w+)\s*;', cleaned):
        class_name = m.group(1)
        obj_name = m.group(2)
        # Verify it's likely a class (starts with uppercase or has known pattern)
        if re.match(r'[A-Z]', class_name) and class_name not in (
            'O3_CPU', 'CACHE', 'DRAM', 'RANDOM'
        ):
            objects[obj_name] = class_name

    # Find init calls: OBJECTNAME.init(arg1, arg2, ...)
    for m in re.finditer(r'\b(\w+)\.init\s*\(([^)]+)\)', cleaned):
        obj_name = m.group(1)
        args_str = m.group(2)

        if obj_name not in objects:
            continue

        class_name = objects[obj_name]

        # Parse arguments
        args = [a.strip() for a in args_str.split(',')]
        arg_values = []
        for arg in args:
            val = try_evaluate(arg, resolved_macros)
            if val is not None:
                arg_values.append(val)
            else:
                arg_values.append(None)

        # Find the init method in the class definition
        # Look for: void init(param1, param2, ...) { ... }
        class_pattern = re.compile(
            r'\bclass\s+' + re.escape(class_name) + r'\b.*?'
            r'void\s+init\s*\(([^)]*)\)\s*\{',
            re.DOTALL
        )
        class_match = class_pattern.search(cleaned)
        if not class_match:
            continue

        # Extract parameter names
        params_str = class_match.group(1)
        param_names = []
        for p in params_str.split(','):
            p = p.strip()
            # Extract parameter name (last word)
            parts = p.split()
            if parts:
                param_names.append(parts[-1])

        # Build parameter -> value mapping
        param_map = dict(resolved_macros)
        for i, pname in enumerate(param_names):
            if i < len(arg_values) and arg_values[i] is not None:
                param_map[pname] = arg_values[i]

        # Find init method body
        init_start = class_match.end()
        depth = 1
        i = init_start
        while i < len(cleaned) and depth > 0:
            if cleaned[i] == '{':
                depth += 1
            elif cleaned[i] == '}':
                depth -= 1
            i += 1
        init_body = cleaned[init_start:i - 1]

        # Process assignments in init body
        local_vars = dict(param_map)
        for assign_match in re.finditer(
            r'\b(\w+)\s*=\s*([^;]+);', init_body
        ):
            var_name = assign_match.group(1)
            var_expr = assign_match.group(2).strip()
            val = try_evaluate(var_expr, local_vars)
            if val is not None:
                local_vars[var_name] = val
                members[f"{obj_name}.{var_name}"] = val

    return members


def find_function_body(source, func_name):
    """Extract the body of a function by name."""
    pattern = re.compile(
        re.escape(func_name) + r'\s*\([^)]*\)\s*\{',
        re.DOTALL
    )
    match = pattern.search(source)
    if not match:
        return ""

    start = match.end()
    depth = 1
    i = start
    while i < len(source) and depth > 0:
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
        i += 1

    return source[start:i - 1]


def extract_storage_from_final_stats(source, resolved_macros, member_vars):
    """Extract and evaluate storage expressions from l1i_prefetcher_final_stats().

    Returns (components, total_bytes) where components is a list of
    {"label": str, "bytes": int} and total_bytes is the final total.
    """
    body = find_function_body(source, "l1i_prefetcher_final_stats")
    if not body.strip():
        return [], 0

    # Check for printf with storage info
    if 'printf' not in body:
        return [], 0

    # Build combined symbol table: macros + member variables
    all_symbols = dict(resolved_macros)
    for key, val in member_vars.items():
        all_symbols[key.replace('.', '_DOT_')] = val

    # Find all printf statements with %d (integer storage values)
    components = []
    total = None

    # Extract printf calls — handle multi-line printf
    # Regex to find printf("...", EXPR);
    # We need to handle multi-line and nested parentheses
    printf_pattern = re.compile(r'printf\s*\(', re.DOTALL)

    for pmatch in printf_pattern.finditer(body):
        pstart = pmatch.end()
        # Find matching closing paren
        depth = 1
        j = pstart
        while j < len(body) and depth > 0:
            if body[j] == '(':
                depth += 1
            elif body[j] == ')':
                depth -= 1
            j += 1
        printf_content = body[pstart:j - 1]

        # Check if this printf has a %d format specifier
        if '%d' not in printf_content:
            continue

        # Split format string from arguments
        # Find the closing quote of the format string
        in_string = False
        quote_end = -1
        k = 0
        while k < len(printf_content):
            if printf_content[k] == '"' and (k == 0 or printf_content[k - 1] != '\\'):
                if not in_string:
                    in_string = True
                else:
                    quote_end = k
                    in_string = False
            k += 1

        if quote_end < 0:
            continue

        # Extract the format string for label
        fmt_str = printf_content[:quote_end + 1].strip().strip('"')
        # Extract the expression after the format string
        rest = printf_content[quote_end + 1:].strip()
        if rest.startswith(','):
            rest = rest[1:].strip()

        expr = rest.strip()
        if not expr:
            continue

        # Replace member variable references (AHEAD.SIZEWAYNEXTMISS -> value)
        for mvar, mval in member_vars.items():
            expr = expr.replace(mvar, str(mval))

        value = try_evaluate(expr, resolved_macros)

        is_total = 'TOTAL' in fmt_str.upper() or 'total' in fmt_str.lower()
        label = fmt_str.replace('%d', '').replace('\\n', '').strip()

        if value is not None:
            components.append({"label": label, "bytes": value})
            if is_total:
                total = value

    if total is None and components:
        # Sum all non-total components
        total = sum(c["bytes"] for c in components)

    return components, total if total is not None else 0


def cmd_macros(filepath):
    """Handle 'macros' subcommand."""
    with open(filepath) as f:
        source = f.read()

    raw = extract_defines(source)
    resolved = resolve_all_macros(raw)

    print(json.dumps({"macros": resolved}, indent=2, sort_keys=True))


def cmd_eval(filepath, expression):
    """Handle 'eval' subcommand."""
    with open(filepath) as f:
        source = f.read()

    raw = extract_defines(source)
    resolved = resolve_all_macros(raw)
    result = try_evaluate(expression, resolved)

    print(json.dumps({"result": result}))


def cmd_audit(filepath):
    """Handle 'audit' subcommand."""
    with open(filepath) as f:
        source = f.read()

    raw = extract_defines(source)
    resolved = resolve_all_macros(raw)
    members = resolve_member_variables(source, resolved)
    components, total = extract_storage_from_final_stats(source, resolved, members)

    result = {
        "total_storage_bytes": total,
        "budget_limit_bytes": 131072,
        "within_budget": total <= 131072,
    }

    print(json.dumps(result, indent=2))


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 budget_auditor.py <mode> <file.cc> [expression]",
              file=sys.stderr)
        print("Modes: macros, eval, audit", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    filepath = sys.argv[2]

    if mode == "macros":
        cmd_macros(filepath)
    elif mode == "eval":
        if len(sys.argv) < 4:
            print("Usage: python3 budget_auditor.py eval <file.cc> '<expression>'",
                  file=sys.stderr)
            sys.exit(1)
        cmd_eval(filepath, sys.argv[3])
    elif mode == "audit":
        cmd_audit(filepath)
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
