#!/usr/bin/env python3
"""IPC-1 Prefetcher Storage Analysis Pipeline.

Uses gcc preprocessor (-E -dM), Universal Ctags (JSON output), and custom
C++ source analysis to compute hardware storage budgets for IPC-1
instruction prefetchers.

"""

import sys
import os
import json
import re
import subprocess
import glob as glob_module

INCLUDE_PATH = "/app/include"
PREFETCHERS_DIR = "/app/prefetchers"
BUDGET_LIMIT = 131072  # 128 KB


# ─── GCC Preprocessor Integration ────────────────────────────────────

def run_gcc_dM(filepath):
    """Run g++ -E -dM with ChampSim include path to extract macro definitions."""
    result = subprocess.run(
        ["g++", "-E", "-dM", f"-I{INCLUDE_PATH}", filepath],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"g++ -E -dM failed: {result.stderr}")
    return result.stdout


def try_evaluate_expr(expr, resolved):
    """Evaluate a C-style integer expression using resolved symbols.

    Handles arithmetic (+, -, *, /), bit shifts (<<, >>), parentheses,
    and C-style integer division (truncation toward zero).
    Returns integer on success, None if unresolved identifiers remain.
    """
    # Remove C type casts
    cleaned = re.sub(
        r'\(\s*(?:u?int(?:8|16|32|64)_t|unsigned\s+(?:long|int)|'
        r'long\s+long|long|int|char|short|size_t)\s*\)', '', expr)

    # Substitute resolved symbols
    def replacer(m):
        name = m.group(0)
        return str(resolved[name]) if name in resolved else name

    substituted = re.sub(r'\b[A-Za-z_]\w*\b', replacer, cleaned)

    # Check for remaining unresolved identifiers
    if re.search(r'[A-Za-z_]\w*', substituted):
        return None

    # Convert / to // for Python integer division (C-style)
    int_div_expr = re.sub(r'(?<!/)/(?![/=])', '//', substituted)

    try:
        result = eval(int_div_expr, {"__builtins__": {}})
        return int(result)
    except Exception:
        return None


def parse_gcc_macros(gcc_output):
    """Parse gcc -E -dM output into a dict of name -> integer value.

    Filters out system/compiler macros (names starting with _).
    Iteratively resolves expressions referencing other macros.
    """
    raw = {}
    for line in gcc_output.strip().split('\n'):
        m = re.match(r'#define\s+(\w+)\s+(.*)', line)
        if not m:
            continue
        name = m.group(1)
        value_str = m.group(2).strip()

        # Skip system/compiler macros
        if name.startswith('_'):
            continue
        # Skip empty (flag-only) macros
        if not value_str:
            continue

        raw[name] = value_str

    # Iterative resolution
    resolved = {}
    for _ in range(100):
        progress = False
        for name, val in raw.items():
            if name in resolved:
                continue
            result = try_evaluate_expr(val, resolved)
            if result is not None:
                resolved[name] = result
                progress = True
        if not progress:
            break

    return resolved


# ─── Universal Ctags Integration ─────────────────────────────────────

def run_ctags_json(filepath):
    """Run Universal Ctags with JSON output to extract C++ symbols."""
    result = subprocess.run(
        ["ctags", "--output-format=json", "--fields=+neS",
         "--kinds-C++=+smtdg", "-f-", filepath],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ctags failed: {result.stderr}")

    tags = []
    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            tag = json.loads(line)
            if tag.get("_type") == "tag":
                tags.append(tag)
        except json.JSONDecodeError:
            continue
    return tags


def find_struct_members(tags, struct_name):
    """Find all member tags belonging to a struct/class by name.

    Handles typedef patterns where the scope is __struct_name but the
    user references struct_name.
    """
    # Possible scope names for typedef structs
    candidates = {
        struct_name,
        f"__{struct_name}",
        f"__l1i_{struct_name.replace('l1i_', '')}",
    }

    # Also check all struct/class tags to find matching typedef names
    for tag in tags:
        if tag.get("kind") in ("struct", "class", "typedef"):
            tag_name = tag.get("name", "")
            if tag_name == struct_name or tag_name.endswith(struct_name):
                candidates.add(tag_name)

    members = []
    for tag in tags:
        if tag.get("kind") == "member" and tag.get("scope", "") in candidates:
            members.append(tag)

    return members


# ─── Bit-Width Analysis ──────────────────────────────────────────────

def extract_bits_from_comment(source_line, macros):
    """Extract bit-width from a source line's trailing comment.

    Patterns recognized:
      // N bits
      // MACRO_NAME bits
      // N bit
    Also handles bool type as 1 bit.
    """
    # Check for bool type
    if re.match(r'\s*bool\s+', source_line):
        return 1

    # Look for "// ... bits" comment pattern
    comment_match = re.search(r'//\s*(.*)\s+bits?\b', source_line, re.IGNORECASE)
    if comment_match:
        bits_expr = comment_match.group(1).strip()

        # Try as plain integer
        try:
            return int(bits_expr)
        except ValueError:
            pass

        # Try evaluating as macro expression
        result = try_evaluate_expr(bits_expr, macros)
        if result is not None:
            return result

    return None


def analyze_struct(filepath, struct_name, macros=None):
    """Analyze a struct's per-entry bit width using ctags + source parsing.

    Combines ctags member discovery with source comment parsing and
    preprocessor macro resolution.
    """
    if macros is None:
        gcc_out = run_gcc_dM(filepath)
        macros = parse_gcc_macros(gcc_out)

    tags = run_ctags_json(filepath)
    member_tags = find_struct_members(tags, struct_name)

    with open(filepath) as f:
        source_lines = f.readlines()

    members = []
    for mtag in member_tags:
        name = mtag["name"]
        line_no = mtag.get("line", 0) - 1  # 0-indexed

        if line_no < 0 or line_no >= len(source_lines):
            continue

        source_line = source_lines[line_no]
        bits = extract_bits_from_comment(source_line, macros)

        if bits is not None:
            members.append({"name": name, "bits": bits})

    total = sum(m["bits"] for m in members)
    return {
        "name": struct_name,
        "members": members,
        "bits_per_entry": total
    }


# ─── Budget Computation ──────────────────────────────────────────────

def strip_comments(source):
    """Remove C/C++ comments from source code."""
    source = re.sub(r'/\*.*?\*/', ' ', source, flags=re.DOTALL)
    lines = []
    for line in source.split('\n'):
        idx = line.find('//')
        if idx >= 0:
            line = line[:idx]
        lines.append(line)
    return '\n'.join(lines)


def find_function_body(source, func_name):
    """Extract the body of a function by name."""
    pattern = re.compile(re.escape(func_name) + r'\s*\([^)]*\)\s*\{', re.DOTALL)
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


def resolve_member_variables(source, macros):
    """Resolve class member variables set through init() method calls.

    Traces patterns like:
        ClassName INSTANCE;
        INSTANCE.init(ARG1, ARG2);
    then parses the init() method body to compute member assignments.
    """
    members = {}
    cleaned = strip_comments(source)

    # Find global object declarations
    objects = {}
    for m in re.finditer(r'\b(\w+)\s+(\w+)\s*;', cleaned):
        class_name = m.group(1)
        obj_name = m.group(2)
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
            val = try_evaluate_expr(arg, macros)
            arg_values.append(val)

        # Find the init method in the class
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
            parts = p.split()
            if parts:
                param_names.append(parts[-1])

        # Build parameter -> value mapping
        param_map = dict(macros)
        for i, pname in enumerate(param_names):
            if i < len(arg_values) and arg_values[i] is not None:
                param_map[pname] = arg_values[i]

        # Extract init method body
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

        # Process assignments
        local_vars = dict(param_map)
        for assign_match in re.finditer(r'\b(\w+)\s*=\s*([^;]+);', init_body):
            var_name = assign_match.group(1)
            var_expr = assign_match.group(2).strip()
            val = try_evaluate_expr(var_expr, local_vars)
            if val is not None:
                local_vars[var_name] = val
                members[f"{obj_name}.{var_name}"] = val

    return members


def extract_storage_from_final_stats(source, macros, member_vars):
    """Extract storage expressions from l1i_prefetcher_final_stats().

    Parses printf statements with %d format specifiers to find
    storage computation expressions.
    """
    body = find_function_body(source, "l1i_prefetcher_final_stats")
    if not body.strip() or 'printf' not in body:
        return [], 0

    components = []
    total = None

    printf_pattern = re.compile(r'printf\s*\(', re.DOTALL)
    for pmatch in printf_pattern.finditer(body):
        pstart = pmatch.end()
        depth = 1
        j = pstart
        while j < len(body) and depth > 0:
            if body[j] == '(':
                depth += 1
            elif body[j] == ')':
                depth -= 1
            j += 1
        printf_content = body[pstart:j - 1]

        if '%d' not in printf_content:
            continue

        # Find end of format string
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

        fmt_str = printf_content[:quote_end + 1].strip().strip('"')
        rest = printf_content[quote_end + 1:].strip()
        if rest.startswith(','):
            rest = rest[1:].strip()

        expr = rest.strip()
        if not expr:
            continue

        # Substitute member variables
        for mvar, mval in member_vars.items():
            expr = expr.replace(mvar, str(mval))

        value = try_evaluate_expr(expr, macros)
        is_total = 'TOTAL' in fmt_str.upper()
        label = fmt_str.replace('%d', '').replace('\\n', '').strip()

        if value is not None:
            components.append({"label": label, "bytes": value})
            if is_total:
                total = value

    if total is None and components:
        total = sum(c["bytes"] for c in components)

    return components, total if total is not None else 0


def compute_budget(filepath):
    """Compute total hardware storage budget for a prefetcher file."""
    gcc_out = run_gcc_dM(filepath)
    macros = parse_gcc_macros(gcc_out)

    with open(filepath) as f:
        source = f.read()

    member_vars = resolve_member_variables(source, macros)
    components, total = extract_storage_from_final_stats(source, macros, member_vars)

    return {
        "total_storage_bytes": total,
        "budget_limit_bytes": BUDGET_LIMIT,
        "within_budget": total <= BUDGET_LIMIT,
    }


# ─── Command Handlers ────────────────────────────────────────────────

def cmd_preprocess(filepath):
    gcc_out = run_gcc_dM(filepath)
    macros = parse_gcc_macros(gcc_out)
    print(json.dumps({"macros": macros}, indent=2, sort_keys=True))


def cmd_analyze(filepath, struct_name):
    result = analyze_struct(filepath, struct_name)
    print(json.dumps(result, indent=2))


def cmd_budget(filepath):
    result = compute_budget(filepath)
    print(json.dumps(result, indent=2))


def cmd_report():
    cc_files = sorted(glob_module.glob(os.path.join(PREFETCHERS_DIR, "*.cc")))
    prefetchers = []
    for fpath in cc_files:
        fname = os.path.basename(fpath)
        budget = compute_budget(fpath)
        prefetchers.append({
            "file": fname,
            "total_storage_bytes": budget["total_storage_bytes"],
            "within_budget": budget["within_budget"],
        })

    # Rank by storage descending
    ranking = sorted(prefetchers, key=lambda p: p["total_storage_bytes"], reverse=True)
    ranking_names = [p["file"] for p in ranking]

    print(json.dumps({
        "prefetchers": prefetchers,
        "ranking": ranking_names,
    }, indent=2))


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 storage_pipeline.py <command> [args...]",
              file=sys.stderr)
        print("Commands: preprocess, analyze, budget, report", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "preprocess":
        if len(sys.argv) < 3:
            print("Usage: preprocess <file.cc>", file=sys.stderr)
            sys.exit(1)
        cmd_preprocess(sys.argv[2])

    elif cmd == "analyze":
        if len(sys.argv) < 4:
            print("Usage: analyze <file.cc> <struct_name>", file=sys.stderr)
            sys.exit(1)
        cmd_analyze(sys.argv[2], sys.argv[3])

    elif cmd == "budget":
        if len(sys.argv) < 3:
            print("Usage: budget <file.cc>", file=sys.stderr)
            sys.exit(1)
        cmd_budget(sys.argv[2])

    elif cmd == "report":
        cmd_report()

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
