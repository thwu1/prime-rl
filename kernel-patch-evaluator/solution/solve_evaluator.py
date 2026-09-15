#!/usr/bin/env python3
"""
Kernel Patch Semantic Triage Engine — Reference Implementation

Parses kernel crash reports, uses universal-ctags for source-aware function
boundary detection, lsdiff for diff file enumeration, and performs structural
patch equivalence analysis via alpha-equivalence checking with guard clause
normalization.

"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


# ============================================================
# 1. Crash Report Parsing
# ============================================================

def parse_crash_report(report_text):
    """Parse a kernel crash report and extract structured information."""
    result = {
        "type": None,
        "access_type": None,
        "file": None,
        "function": None,
        "line": None,
    }

    # --- KASAN reports ---
    kasan_match = re.search(
        r'BUG:\s+KASAN:\s+([\w-]+)\s+in\s+(\w+)\+0x[\da-f]+/0x[\da-f]+\s+(\S+):(\d+)',
        report_text
    )
    if kasan_match:
        result["type"] = kasan_match.group(1)
        result["function"] = kasan_match.group(2)
        result["file"] = kasan_match.group(3)
        result["line"] = int(kasan_match.group(4))

        access_match = re.search(r'(Read|Write)\s+of\s+size\s+\d+', report_text)
        if access_match:
            result["access_type"] = access_match.group(1)
        return result

    # --- NULL pointer dereference ---
    null_match = re.search(r'BUG:\s+kernel\s+NULL\s+pointer\s+dereference', report_text)
    if null_match:
        result["type"] = "null-ptr-deref"

        # Extract access type from #PF line
        pf_match = re.search(r'#PF:\s+supervisor\s+(read|write)\s+access', report_text)
        if pf_match:
            result["access_type"] = pf_match.group(1).capitalize()

        # Extract function, file, line from RIP
        rip_match = re.search(
            r'RIP:\s+\w+:(\w+)\+0x[\da-f]+/0x[\da-f]+\s+(\S+):(\d+)',
            report_text
        )
        if rip_match:
            result["function"] = rip_match.group(1)
            result["file"] = rip_match.group(2)
            result["line"] = int(rip_match.group(3))
        return result

    # --- WARNING ---
    warn_match = re.search(
        r'WARNING:\s+CPU:\s+\d+\s+PID:\s+\d+\s+at\s+(\S+):(\d+)\s+(\w+)\+0x[\da-f]+/0x[\da-f]+',
        report_text
    )
    if warn_match:
        result["type"] = "warning"
        result["access_type"] = None
        result["file"] = warn_match.group(1)
        result["line"] = int(warn_match.group(2))
        result["function"] = warn_match.group(3)
        return result

    return result


# ============================================================
# 2. ctags-based Function Boundary Detection
# ============================================================

def build_ctags_function_map(source_path):
    """
    Use universal-ctags to extract function definitions with line ranges.
    Returns dict mapping every line number inside a function body to
    the function name: {line_number: function_name}.
    """
    result = subprocess.run(
        ['ctags', '--output-format=json', '--kinds-C=f', '--fields=+ne',
         '-f', '-', source_path],
        capture_output=True, text=True
    )
    func_map = {}
    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        try:
            tag = json.loads(line)
            if tag.get('_type') != 'tag':
                continue
            name = tag['name']
            start_line = tag.get('line', 0)
            end_line = tag.get('end', start_line)
            for ln in range(start_line, end_line + 1):
                func_map[ln] = name
        except (json.JSONDecodeError, KeyError):
            continue
    return func_map


def load_source_function_maps(source_dir):
    """Load function maps for all C source files in a case's source/ directory."""
    maps = {}
    source_path = Path(source_dir)
    if not source_path.exists():
        return maps
    for c_file in source_path.rglob("*.c"):
        rel_path = str(c_file.relative_to(source_path))
        maps[rel_path] = build_ctags_function_map(str(c_file))
    return maps


# ============================================================
# 3. lsdiff-based File Enumeration
# ============================================================

def get_modified_files(diff_text):
    """Use lsdiff from patchutils to enumerate files modified by a diff."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.diff', delete=False) as f:
        f.write(diff_text)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ['lsdiff', '-p1', tmp_path],
            capture_output=True, text=True
        )
        files = [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]
        return sorted(set(files))
    finally:
        os.unlink(tmp_path)


# ============================================================
# 4. Unified Diff Parsing
# ============================================================

def parse_unified_diff(diff_text):
    """
    Parse a unified diff into a structured representation.
    Returns list of file dicts, each containing file path and hunks.
    """
    files = []
    current_file = None
    current_hunk = None

    # Use splitlines() to avoid trailing empty string from split('\n')
    for line in diff_text.splitlines():
        file_match = re.match(r'^diff --git a/(.+?) b/(.+)$', line)
        if file_match:
            if current_file and current_hunk:
                current_file['hunks'].append(current_hunk)
            if current_file:
                files.append(current_file)
            current_file = {'file': file_match.group(2), 'hunks': []}
            current_hunk = None
            continue

        hunk_match = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if hunk_match:
            if current_hunk and current_file:
                current_file['hunks'].append(current_hunk)
            current_hunk = {
                'old_start': int(hunk_match.group(1)),
                'old_count': int(hunk_match.group(2)) if hunk_match.group(2) else 1,
                'new_start': int(hunk_match.group(3)),
                'new_count': int(hunk_match.group(4)) if hunk_match.group(4) else 1,
                'lines': [],
            }
            continue

        if line.startswith('---') or line.startswith('+++') or line.startswith('index '):
            continue

        if current_hunk is not None:
            if line.startswith('-'):
                current_hunk['lines'].append(('-', line[1:]))
            elif line.startswith('+'):
                current_hunk['lines'].append(('+', line[1:]))
            elif line.startswith(' ') or line == '':
                content = line[1:] if line.startswith(' ') else ''
                current_hunk['lines'].append((' ', content))

    if current_hunk and current_file:
        current_file['hunks'].append(current_hunk)
    if current_file:
        files.append(current_file)

    return files


# ============================================================
# 5. Source-Aware Function Extraction
# ============================================================

def extract_modified_functions(parsed_diff, func_maps):
    """
    Map changed diff lines to functions using ctags function maps.
    Walks through each hunk line-by-line, tracking old line numbers
    and looking up which function each line belongs to.
    """
    modified = set()

    for file_info in parsed_diff:
        filepath = file_info['file']
        fmap = func_maps.get(filepath, {})

        for hunk in file_info['hunks']:
            old_lineno = hunk['old_start']
            new_lineno = hunk['new_start']
            last_known_func = None

            for line_type, content in hunk['lines']:
                if line_type == ' ':
                    if old_lineno in fmap:
                        last_known_func = fmap[old_lineno]
                    old_lineno += 1
                    new_lineno += 1
                elif line_type == '-':
                    if old_lineno in fmap:
                        modified.add(f"{filepath}:{fmap[old_lineno]}")
                        last_known_func = fmap[old_lineno]
                    old_lineno += 1
                elif line_type == '+':
                    if last_known_func:
                        modified.add(f"{filepath}:{last_known_func}")
                    new_lineno += 1

    return sorted(modified)


def extract_modified_files(parsed_diff):
    """Extract sorted list of modified file paths from a parsed diff."""
    return sorted(set(f['file'] for f in parsed_diff))


# ============================================================
# 6. IoU Computation
# ============================================================

def compute_iou(set_a, set_b):
    """Compute intersection over union of two sets."""
    a = set(set_a)
    b = set(set_b)
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# ============================================================
# 7. Patch Application
# ============================================================

def apply_patch_to_source(source_lines, hunks):
    """
    Apply diff hunks to source lines (list of strings).
    Returns new list of strings representing the patched file.
    """
    result = []
    old_idx = 0

    for hunk in hunks:
        old_start_0 = hunk['old_start'] - 1

        while old_idx < old_start_0:
            result.append(source_lines[old_idx])
            old_idx += 1

        for line_type, content in hunk['lines']:
            if line_type == ' ':
                if old_idx < len(source_lines):
                    result.append(source_lines[old_idx])
                old_idx += 1
            elif line_type == '-':
                old_idx += 1
            elif line_type == '+':
                result.append(content + '\n')

    while old_idx < len(source_lines):
        result.append(source_lines[old_idx])
        old_idx += 1

    return result


# ============================================================
# 8. Structural Equivalence Analysis
# ============================================================

def tokenize_c(code):
    """
    Simple C tokenizer. Returns list of tokens.
    Strips comments and normalizes whitespace.
    """
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    code = re.sub(r'//.*$', '', code, flags=re.MULTILINE)
    code = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', code)

    tokens = re.findall(
        r'[a-zA-Z_]\w*|0x[\da-fA-F]+|\d+|[<>=!]=|->|&&|\|\||<<|>>|[^\s]',
        code
    )
    return tokens


def check_alpha_equivalent(tokens_a, tokens_b):
    """
    Check if two token sequences are equivalent up to consistent
    bijective identifier renaming.
    """
    if len(tokens_a) != len(tokens_b):
        return False

    c_keywords = {
        'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do',
        'double', 'else', 'enum', 'extern', 'float', 'for', 'goto', 'if',
        'inline', 'int', 'long', 'register', 'return', 'short', 'signed',
        'sizeof', 'static', 'struct', 'switch', 'typedef', 'union', 'unsigned',
        'void', 'volatile', 'while', 'bool', 'true', 'false', 'NULL',
        'unlikely', 'likely', '__u32', '__le32', '__be32', '__u64', '__le64',
        'GFP_KERNEL', 'EINVAL', 'EBUSY', 'ENOMEM', 'ENODEV',
        'atomic_t', 'gfp_t', 'size_t', 'ssize_t', 'u8', 'u16', 'u32', 'u64',
        's8', 's16', 's32', 's64',
    }

    mapping_a_to_b = {}
    mapping_b_to_a = {}

    for ta, tb in zip(tokens_a, tokens_b):
        if ta == tb:
            continue

        is_ident_a = bool(re.match(r'^[a-zA-Z_]\w*$', ta))
        is_ident_b = bool(re.match(r'^[a-zA-Z_]\w*$', tb))

        if not (is_ident_a and is_ident_b):
            return False

        if ta in c_keywords or tb in c_keywords:
            return False

        if ta in mapping_a_to_b:
            if mapping_a_to_b[ta] != tb:
                return False
        else:
            mapping_a_to_b[ta] = tb

        if tb in mapping_b_to_a:
            if mapping_b_to_a[tb] != ta:
                return False
        else:
            mapping_b_to_a[tb] = ta

    return True


# ============================================================
# 8b. Guard Clause Normalization
# ============================================================

def normalize_guard_clauses(tokens):
    """
    Normalize guard clause patterns to canonical early-return form.
    Detects: if (COND) { BODY } return VAL ;
    Converts to: if ( ! COND ) return VAL ; BODY
    where COND is a non-negated condition.
    This allows comparison of semantically equivalent code that uses
    different guard clause styles (early return vs wrapped block).
    """
    result = list(tokens)
    i = 0
    while i < len(result):
        if result[i] != 'if' or i + 1 >= len(result) or result[i + 1] != '(':
            i += 1
            continue

        # Extract condition tokens (matching parentheses)
        cond_start = i + 2
        depth = 1
        j = cond_start
        while j < len(result) and depth > 0:
            if result[j] == '(':
                depth += 1
            elif result[j] == ')':
                depth -= 1
            j += 1
        cond_end = j - 1
        cond_tokens = result[cond_start:cond_end]

        after_cond = j

        # Skip if condition is already negated (early-return form)
        if cond_tokens and cond_tokens[0] == '!':
            i += 1
            continue

        # Check for wrapped-block pattern: if (COND) { BODY } return VAL ;
        if after_cond >= len(result) or result[after_cond] != '{':
            i += 1
            continue

        # Find matching closing brace
        brace_depth = 1
        k = after_cond + 1
        while k < len(result) and brace_depth > 0:
            if result[k] == '{':
                brace_depth += 1
            elif result[k] == '}':
                brace_depth -= 1
            k += 1
        body_tokens = result[after_cond + 1:k - 1]

        # Check for 'return' after the closing brace
        if k >= len(result) or result[k] != 'return':
            i += 1
            continue

        # Find semicolon terminating the return statement
        m = k + 1
        while m < len(result) and result[m] != ';':
            m += 1
        if m >= len(result):
            i += 1
            continue

        return_val = result[k + 1:m]

        # Reconstruct as early-return form: if (!COND) return VAL; BODY
        new_tokens = result[:i]
        new_tokens.extend(['if', '(', '!'])
        # Wrap multi-token conditions in parens for correct precedence
        if len(cond_tokens) > 1:
            new_tokens.append('(')
            new_tokens.extend(cond_tokens)
            new_tokens.append(')')
        else:
            new_tokens.extend(cond_tokens)
        new_tokens.extend([')', 'return'])
        new_tokens.extend(return_val)
        new_tokens.append(';')
        new_tokens.extend(body_tokens)
        new_tokens.extend(result[m + 1:])

        # Recurse in case there are nested guard clauses
        return normalize_guard_clauses(new_tokens)

    return result


# ============================================================
# 9. Patch Equivalence Check
# ============================================================

def check_patch_equivalence(parsed_agent, parsed_developer, source_dir):
    """
    Determine if two patches are structurally equivalent.
    Applies both patches to source files and checks alpha-equivalence,
    with guard clause normalization as a fallback.
    """
    agent_files = set(f['file'] for f in parsed_agent)
    dev_files = set(f['file'] for f in parsed_developer)

    if agent_files != dev_files:
        return False

    source_path = Path(source_dir)

    for filepath in agent_files:
        src_file = source_path / filepath
        if not src_file.exists():
            return False

        with open(src_file) as f:
            source_lines = f.readlines()

        agent_hunks = []
        for fi in parsed_agent:
            if fi['file'] == filepath:
                agent_hunks = fi['hunks']
                break

        dev_hunks = []
        for fi in parsed_developer:
            if fi['file'] == filepath:
                dev_hunks = fi['hunks']
                break

        agent_result = apply_patch_to_source(source_lines, agent_hunks)
        dev_result = apply_patch_to_source(source_lines, dev_hunks)

        agent_code = ''.join(agent_result)
        dev_code = ''.join(dev_result)

        agent_tokens = tokenize_c(agent_code)
        dev_tokens = tokenize_c(dev_code)

        # Direct alpha-equivalence
        if check_alpha_equivalent(agent_tokens, dev_tokens):
            continue

        # Try with guard clause normalization
        agent_normalized = normalize_guard_clauses(agent_tokens)
        dev_normalized = normalize_guard_clauses(dev_tokens)

        if check_alpha_equivalent(agent_normalized, dev_normalized):
            continue

        return False

    return True


# ============================================================
# 10. Main Pipeline
# ============================================================

def evaluate_case(case_dir):
    """Evaluate a single case directory."""
    case_path = Path(case_dir)

    # Read crash report
    with open(case_path / "crash_report.txt") as f:
        crash_text = f.read()
    crash_info = parse_crash_report(crash_text)

    # Read patches
    with open(case_path / "agent_patch.diff") as f:
        agent_diff_text = f.read()
    with open(case_path / "developer_patch.diff") as f:
        dev_diff_text = f.read()

    # Parse diffs
    parsed_agent = parse_unified_diff(agent_diff_text)
    parsed_developer = parse_unified_diff(dev_diff_text)

    # Load source function maps via ctags
    source_dir = case_path / "source"
    func_maps = load_source_function_maps(str(source_dir))

    # Extract modified files using lsdiff
    agent_files = get_modified_files(agent_diff_text)
    dev_files = get_modified_files(dev_diff_text)

    # Extract modified functions using source-aware mapping
    agent_functions = extract_modified_functions(parsed_agent, func_maps)
    dev_functions = extract_modified_functions(parsed_developer, func_maps)

    # Compute metrics
    file_iou = compute_iou(agent_files, dev_files)
    function_iou = compute_iou(agent_functions, dev_functions)

    # Localization hit
    crash_func_key = None
    if crash_info['file'] and crash_info['function']:
        crash_func_key = f"{crash_info['file']}:{crash_info['function']}"
    localization_hit = crash_func_key in agent_functions if crash_func_key else False

    # Patch equivalence
    patch_equivalent = check_patch_equivalence(
        parsed_agent, parsed_developer, str(source_dir)
    )

    return {
        "crash_info": crash_info,
        "agent_patch": {
            "modified_files": agent_files,
            "modified_functions": agent_functions,
        },
        "developer_patch": {
            "modified_files": dev_files,
            "modified_functions": dev_functions,
        },
        "metrics": {
            "file_iou": file_iou,
            "function_iou": function_iou,
            "localization_hit": localization_hit,
            "patch_equivalent": patch_equivalent,
        },
    }


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <cases_dir> <output_json>", file=sys.stderr)
        sys.exit(1)

    cases_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    output_path.parent.mkdir(parents=True, exist_ok=True)

    results = {}
    for case_dir in sorted(cases_dir.iterdir()):
        if case_dir.is_dir() and case_dir.name.startswith("case_"):
            print(f"Evaluating {case_dir.name}...")
            results[case_dir.name] = evaluate_case(case_dir)

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
