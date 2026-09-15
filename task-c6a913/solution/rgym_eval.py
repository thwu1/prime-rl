#!/usr/bin/env python3
"""
Kernel patch evaluation pipeline with ASan and Valgrind cross-validation.
"""

import json
import os
import re
import subprocess
import tempfile
import glob


DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
SOURCES_DIR = os.path.join(DATA_DIR, "sources")
PATCHES_DIR = os.path.join(DATA_DIR, "patches")


# ============================================================
# KASAN Report Parsing
# ============================================================

def parse_kasan_report(filepath):
    """Parse a KASAN crash report and extract structured metadata."""
    with open(filepath) as f:
        text = f.read()

    result = {}

    bug_match = re.search(r'BUG: KASAN: (\S+) in (\S+)\+0x[0-9a-f]+/0x[0-9a-f]+', text)
    if bug_match:
        result['bug_type'] = bug_match.group(1)
        func = bug_match.group(2)
        if '.' in func:
            func = func.split('.')[0]
        result['faulting_function'] = func

    loc_match = re.search(
        r'BUG: KASAN: \S+ in \S+\+0x[0-9a-f]+/0x[0-9a-f]+ (\S+\.c:\d+)', text
    )
    if loc_match:
        result['source_location'] = loc_match.group(1)
    else:
        result['source_location'] = ""

    access_match = re.search(r'(Read|Write) of size (\d+) at addr', text)
    if access_match:
        result['access_type'] = access_match.group(1)
        result['access_size'] = int(access_match.group(2))

    stack_entries = []
    in_stack = False
    for line in text.split('\n'):
        stripped = line.strip()
        if '<TASK>' in stripped:
            in_stack = True
            continue
        if '</TASK>' in stripped:
            in_stack = False
            continue
        if in_stack:
            func_match = re.match(r'\s*(\S+)\+0x[0-9a-f]+/0x[0-9a-f]+', stripped)
            if func_match:
                func_name = func_match.group(1)
                if '.' in func_name:
                    func_name = func_name.split('.')[0]
                stack_entries.append(func_name)
    result['call_stack'] = stack_entries

    cache_match = re.search(
        r'belongs to the cache (\S+) of size (\d+)', text
    )
    if cache_match:
        result['slab_cache'] = cache_match.group(1)
        result['object_size'] = int(cache_match.group(2))

    return result


# ============================================================
# C Function Extraction and Patch Application
# ============================================================

def _skip_block_comment(source, pos):
    """Skip past a /* ... */ block comment."""
    pos += 2
    while pos + 1 < len(source):
        if source[pos] == '*' and source[pos + 1] == '/':
            return pos + 2
        pos += 1
    return pos


def _skip_line_comment(source, pos):
    """Skip past a // line comment."""
    while pos < len(source) and source[pos] != '\n':
        pos += 1
    return pos


def _find_matching_brace(source, open_pos):
    """Find position just after the matching closing brace."""
    depth = 1
    pos = open_pos + 1
    while pos < len(source) and depth > 0:
        c = source[pos]
        if c == '/' and pos + 1 < len(source):
            if source[pos + 1] == '*':
                pos = _skip_block_comment(source, pos)
                continue
            elif source[pos + 1] == '/':
                pos = _skip_line_comment(source, pos)
                continue
        if c == '"':
            pos += 1
            while pos < len(source) and source[pos] != '"':
                if source[pos] == '\\' and pos + 1 < len(source):
                    pos += 1
                pos += 1
            pos += 1
            continue
        if c == "'":
            pos += 1
            if pos < len(source) and source[pos] == '\\':
                pos += 1
            if pos < len(source):
                pos += 1
            if pos < len(source) and source[pos] == "'":
                pos += 1
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return pos


def _find_decl_start(source, name_pos):
    """Find the start of a function declaration/definition."""
    last_boundary = -1
    pos = 0
    while pos < name_pos:
        c = source[pos]
        if c == '/' and pos + 1 < len(source):
            if source[pos + 1] == '*':
                pos = _skip_block_comment(source, pos)
                continue
            elif source[pos + 1] == '/':
                pos = _skip_line_comment(source, pos)
                continue
        if c == '"':
            pos += 1
            while pos < len(source) and source[pos] != '"':
                if source[pos] == '\\' and pos + 1 < len(source):
                    pos += 1
                pos += 1
            pos += 1
            continue
        if c == "'":
            pos += 1
            if pos < len(source) and source[pos] == '\\':
                pos += 1
            if pos < len(source):
                pos += 1
            if pos < len(source) and source[pos] == "'":
                pos += 1
            continue
        if c in '};':
            last_boundary = pos
        pos += 1

    start = last_boundary + 1
    while start < name_pos:
        if source[start] in ' \t\n\r':
            start += 1
        elif source[start:start + 2] == '/*':
            start = _skip_block_comment(source, start)
        elif source[start:start + 2] == '//':
            start = _skip_line_comment(source, start)
            if start < len(source) and source[start] == '\n':
                start += 1
        else:
            break
    return start


def find_function_definition(source, func_name):
    """Locate a function definition in C source code."""
    pos = 0
    while pos < len(source):
        idx = source.find(func_name, pos)
        if idx == -1:
            return None
        if idx > 0 and (source[idx - 1].isalnum() or source[idx - 1] == '_'):
            pos = idx + 1
            continue
        end_name = idx + len(func_name)
        if end_name < len(source) and (source[end_name].isalnum() or source[end_name] == '_'):
            pos = idx + 1
            continue
        after = end_name
        while after < len(source) and source[after] in ' \t\n\r':
            after += 1
        if after >= len(source) or source[after] != '(':
            pos = idx + 1
            continue
        paren_depth = 1
        ppos = after + 1
        while ppos < len(source) and paren_depth > 0:
            if source[ppos] == '(':
                paren_depth += 1
            elif source[ppos] == ')':
                paren_depth -= 1
            ppos += 1
        after_paren = ppos
        while after_paren < len(source) and source[after_paren] in ' \t\n\r':
            after_paren += 1
        if after_paren >= len(source) or source[after_paren] != '{':
            pos = idx + 1
            continue
        start = _find_decl_start(source, idx)
        end = _find_matching_brace(source, after_paren)
        return (start, end)
    return None


def apply_function_patch(source, func_name, replacement):
    """Replace a function definition with the replacement text."""
    bounds = find_function_definition(source, func_name)
    if bounds is None:
        return None
    start, end = bounds
    return source[:start] + replacement + source[end:]


# ============================================================
# Compilation and Testing
# ============================================================

def compile_and_test_asan(patched_source, timeout=30):
    """Compile with AddressSanitizer and run. Returns (result, compiled)."""
    with tempfile.NamedTemporaryFile(
        suffix='.c', mode='w', delete=False, dir='/tmp'
    ) as f:
        f.write(patched_source)
        src_path = f.name
    binary_path = src_path.replace('.c', '_asan.bin')
    try:
        compile_result = subprocess.run(
            ['gcc', '-fsanitize=address', '-static-libasan', '-g',
             '-o', binary_path, src_path, '-lpthread'],
            capture_output=True, text=True, timeout=30
        )
        if compile_result.returncode != 0:
            return "build_fail", False
        env = os.environ.copy()
        env['ASAN_OPTIONS'] = 'exitcode=1:detect_leaks=0'
        run_result = subprocess.run(
            [binary_path],
            capture_output=True, text=True, timeout=timeout,
            env=env
        )
        if run_result.returncode == 0:
            return "pass", True
        else:
            return "trigger", True
    except subprocess.TimeoutExpired:
        return "trigger", True
    finally:
        for path in [src_path, binary_path]:
            try:
                os.unlink(path)
            except OSError:
                pass


def test_with_valgrind(patched_source, timeout=60):
    """Compile without ASan and run under Valgrind. Returns True/False/None."""
    with tempfile.NamedTemporaryFile(
        suffix='.c', mode='w', delete=False, dir='/tmp'
    ) as f:
        f.write(patched_source)
        src_path = f.name
    binary_path = src_path.replace('.c', '_vg.bin')
    try:
        compile_result = subprocess.run(
            ['gcc', '-g', '-o', binary_path, src_path],
            capture_output=True, text=True, timeout=30
        )
        if compile_result.returncode != 0:
            return None
        result = subprocess.run(
            ['valgrind', '--error-exitcode=99', '--leak-check=no',
             '-q', binary_path],
            capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    finally:
        for path in [src_path, binary_path]:
            try:
                os.unlink(path)
            except OSError:
                pass


# ============================================================
# Main Pipeline
# ============================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    report = {"bugs": {}, "summary": {}}
    report_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "bug_*.txt")))

    total_patches = 0
    pass_count = 0
    trigger_count = 0
    build_fail_count = 0

    for report_file in report_files:
        bug_id = os.path.basename(report_file).replace('.txt', '')
        print(f"\n=== Processing {bug_id} ===")

        parsed_report = parse_kasan_report(report_file)
        print(f"  Bug type: {parsed_report.get('bug_type', 'unknown')}")
        print(f"  Function: {parsed_report.get('faulting_function', 'unknown')}")

        bug_entry = {"report": parsed_report, "patches": {}}

        patch_files = sorted(
            glob.glob(os.path.join(PATCHES_DIR, f"{bug_id}_patch_*.json"))
        )

        for patch_file in patch_files:
            basename = os.path.basename(patch_file).replace('.json', '')
            patch_id = basename.replace(f'{bug_id}_', '')

            print(f"  Evaluating {patch_id}...")

            with open(patch_file) as f:
                patch_spec = json.load(f)

            source_path = os.path.join(SOURCES_DIR, patch_spec['source_file'])
            with open(source_path) as f:
                source = f.read()

            patched = apply_function_patch(
                source,
                patch_spec['target_function'],
                patch_spec['replacement']
            )

            if patched is None:
                patch_result = {
                    "applied": False,
                    "compiled": False,
                    "result": "build_fail",
                    "valgrind_clean": None
                }
            else:
                result_category, compiled = compile_and_test_asan(patched)
                if compiled:
                    vg_clean = test_with_valgrind(patched)
                else:
                    vg_clean = None
                print(f"    -> ASan: {result_category}, Valgrind clean: {vg_clean}")
                patch_result = {
                    "applied": True,
                    "compiled": compiled,
                    "result": result_category,
                    "valgrind_clean": vg_clean
                }

            bug_entry["patches"][patch_id] = patch_result
            total_patches += 1

            if patch_result["result"] == "pass":
                pass_count += 1
            elif patch_result["result"] == "trigger":
                trigger_count += 1
            elif patch_result["result"] == "build_fail":
                build_fail_count += 1

        report["bugs"][bug_id] = bug_entry

    report["summary"] = {
        "total_patches": total_patches,
        "pass_count": pass_count,
        "trigger_count": trigger_count,
        "build_fail_count": build_fail_count,
        "pass_rate": round(pass_count / total_patches, 4) if total_patches > 0 else 0.0
    }

    output_path = os.path.join(OUTPUT_DIR, "report.json")
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to {output_path}")
    print(f"Total: {total_patches}, Pass: {pass_count}, Trigger: {trigger_count}, Build fail: {build_fail_count}")
    print(f"Pass rate: {report['summary']['pass_rate']:.2%}")


if __name__ == '__main__':
    main()
