#!/usr/bin/env python3

"""
Custom AST-based vulnerability scanner for C2 teamserver security assessment.

Detects vulnerability patterns that standard SAST tools (like bandit) miss:
- Implicit None returns in authentication functions
- Manually quoted shell interpolations (instead of shlex.quote)
- Incomplete path traversal validation
- dict.get() identity fallback patterns
"""

import ast
import os
import sys
import json


def scan_file(filename, source):
    """Scan a single Python file for vulnerability patterns."""
    findings = []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        # Rules 1-3 operate at function definition level within classes
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    findings.extend(_check_implicit_none_return(filename, item))
                    findings.extend(_check_manual_shell_quoting(filename, item))
                    findings.extend(_check_incomplete_path_validation(filename, item))

        # Rule 4 operates at call-expression level
        if isinstance(node, ast.Call):
            result = _check_dict_get_identity_fallback(filename, node)
            if result:
                findings.append(result)

    return findings


# ---------------------------------------------------------------------------
# Rule 1: implicit-none-return
# ---------------------------------------------------------------------------
def _check_implicit_none_return(filename, func_node):
    """Detect authentication functions that can return None implicitly.

    Pattern: a function whose name contains 'authenticate' has return
    statements inside its body (e.g., inside for-loops/if-blocks) but the
    function body's last statement is not an explicit 'return' or 'raise'.
    This means control can fall off the end and return None, which may bypass
    callers that check 'result is not False' instead of truthiness.
    """
    findings = []
    if 'authenticate' not in func_node.name.lower():
        return findings

    # Must have at least one return statement inside the function
    has_return = any(isinstance(child, ast.Return)
                     for child in ast.walk(func_node)
                     if child is not func_node)
    if not has_return or not func_node.body:
        return findings

    last_stmt = func_node.body[-1]
    if isinstance(last_stmt, (ast.Return, ast.Raise)):
        return findings  # Explicit terminal control flow

    findings.append({
        "file": filename,
        "line": getattr(func_node, 'end_lineno', func_node.lineno),
        "rule_id": "implicit-none-return",
        "severity": "high",
        "message": (
            f"Function '{func_node.name}' can return None implicitly. "
            "Authentication functions must always return an explicit value "
            "to prevent bypass via 'is not False' checks in callers."
        )
    })
    return findings


# ---------------------------------------------------------------------------
# Rule 2: manual-shell-quoting
# ---------------------------------------------------------------------------
def _check_manual_shell_quoting(filename, func_node):
    """Detect f-strings in shell commands where a variable is manually
    quoted with literal double-quote characters instead of shlex.quote().

    Pattern: in a function that calls subprocess.run/call/Popen with
    shell=True, an f-string (JoinedStr) contains a FormattedValue
    immediately preceded by a Constant ending with '"' and followed
    by a Constant starting with '"'. This means the developer placed
    literal quotes around the interpolation instead of using shlex.quote,
    which is trivially bypassable.
    """
    findings = []

    # Step 1: check if this function uses subprocess with shell=True
    has_shell_true = False
    for child in ast.walk(func_node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr in (
                'run', 'call', 'Popen', 'check_output'):
            for kw in child.keywords:
                if (kw.arg == 'shell'
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True):
                    has_shell_true = True

    if not has_shell_true:
        return findings

    # Step 2: scan JoinedStr nodes for the manual-quoting pattern
    for child in ast.walk(func_node):
        if not isinstance(child, ast.JoinedStr):
            continue
        values = child.values
        for i in range(1, len(values) - 1):
            if not isinstance(values[i], ast.FormattedValue):
                continue
            prev_val = values[i - 1]
            next_val = values[i + 1]
            if (isinstance(prev_val, ast.Constant)
                    and isinstance(prev_val.value, str)
                    and prev_val.value.endswith('"')
                    and isinstance(next_val, ast.Constant)
                    and isinstance(next_val.value, str)
                    and next_val.value.startswith('"')):
                findings.append({
                    "file": filename,
                    "line": child.lineno,
                    "rule_id": "manual-shell-quoting",
                    "severity": "critical",
                    "message": (
                        "Variable interpolated into shell command with manual "
                        "double-quote wrapping instead of shlex.quote(). "
                        "Literal quotes are trivially escaped by an attacker."
                    )
                })
    return findings


# ---------------------------------------------------------------------------
# Rule 3: incomplete-path-validation
# ---------------------------------------------------------------------------
def _check_incomplete_path_validation(filename, func_node):
    """Detect os.path.join with user input validated by manual component
    checking (.split('/')[0]) but without os.path.realpath verification.

    Pattern: a function contains os.path.join, a file-open call, and a
    .split('/') manual path check, but does NOT call os.path.realpath().
    Checking only the first path component for '..' is insufficient because
    interior components like 'ok/../../..' can traverse out.
    """
    findings = []
    has_path_join = False
    has_file_io = False
    has_manual_check = False
    has_realpath = False
    join_line = 0

    for child in ast.walk(func_node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func

        # os.path.join(...)
        if (isinstance(func, ast.Attribute) and func.attr == 'join'
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == 'path'):
            has_path_join = True
            join_line = child.lineno

        # open(...)
        if isinstance(func, ast.Name) and func.id == 'open':
            has_file_io = True

        # os.path.realpath(...)
        if (isinstance(func, ast.Attribute) and func.attr == 'realpath'
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == 'path'):
            has_realpath = True

        # .split('/')
        if isinstance(func, ast.Attribute) and func.attr == 'split':
            if (child.args
                    and isinstance(child.args[0], ast.Constant)
                    and child.args[0].value == '/'):
                has_manual_check = True

    if has_path_join and has_file_io and has_manual_check and not has_realpath:
        findings.append({
            "file": filename,
            "line": join_line,
            "rule_id": "incomplete-path-validation",
            "severity": "high",
            "message": (
                "os.path.join() with user input validated only by manual "
                "component checking (.split). Use os.path.realpath() and "
                "verify the resolved path stays under the intended directory."
            )
        })
    return findings


# ---------------------------------------------------------------------------
# Rule 4: dict-get-identity-fallback
# ---------------------------------------------------------------------------
def _check_dict_get_identity_fallback(filename, node):
    """Detect dict.get(key, key) where the fallback is the lookup key itself.

    Pattern: DICT.get(var, var) where both arguments are the same Name node.
    If 'var' is attacker-controlled and not in DICT, the raw unsanitized
    value passes through as the fallback. When used in a security-sensitive
    context (shell commands, SQL, etc.), this enables injection.
    """
    if not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr != 'get':
        return None
    if len(node.args) != 2:
        return None

    arg0, arg1 = node.args
    if (isinstance(arg0, ast.Name) and isinstance(arg1, ast.Name)
            and arg0.id == arg1.id):
        return {
            "file": filename,
            "line": node.lineno,
            "rule_id": "dict-get-identity-fallback",
            "severity": "critical",
            "message": (
                f"dict.get({arg0.id}, {arg0.id}) uses the lookup key as "
                f"fallback. If '{arg0.id}' is attacker-controlled and not "
                "in the dict, the raw value passes through unsanitized."
            )
        }
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <directory>", file=sys.stderr)
        sys.exit(1)

    directory = sys.argv[1]
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    all_findings = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith('.py'):
            continue
        filepath = os.path.join(directory, filename)
        try:
            with open(filepath) as f:
                source = f.read()
        except IOError:
            continue
        all_findings.extend(scan_file(filename, source))

    output = {"findings": all_findings}
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
