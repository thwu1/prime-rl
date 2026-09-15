#!/usr/bin/env python3
"""
Automated program repair tool.

"""

import ast
import difflib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile


def discover_test_functions(test_path):
    """Parse a test file and return names of test_ functions."""
    with open(test_path) as f:
        source = f.read()
    tree = ast.parse(source)
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def collect_coverage(subject_dir):
    """Run each test with line-level tracing, return per-test coverage and outcomes."""
    program_path = os.path.abspath(os.path.join(subject_dir, "program.py"))
    test_path = os.path.join(subject_dir, "test_program.py")
    abs_subject = os.path.abspath(subject_dir)

    test_funcs = discover_test_functions(test_path)

    results = []
    for func_name in test_funcs:
        runner = (
            "import sys, json, os\n"
            f"sys.path.insert(0, {repr(abs_subject)})\n"
            "covered = set()\n"
            f"real_path = os.path.realpath({repr(program_path)})\n"
            "def tracer(frame, event, arg):\n"
            "    if event == 'call':\n"
            "        try:\n"
            "            if os.path.realpath(frame.f_code.co_filename) == real_path:\n"
            "                return line_tracer\n"
            "        except Exception:\n"
            "            pass\n"
            "        return None\n"
            "    return None\n"
            "def line_tracer(frame, event, arg):\n"
            "    if event == 'line':\n"
            "        covered.add(frame.f_lineno)\n"
            "    return line_tracer\n"
            "for mod_name in list(sys.modules):\n"
            "    if mod_name in ('program', 'test_program'):\n"
            "        del sys.modules[mod_name]\n"
            "sys.settrace(tracer)\n"
            "passed = True\n"
            "try:\n"
            "    import test_program\n"
            f"    func = getattr(test_program, {repr(func_name)})\n"
            "    func()\n"
            "except Exception:\n"
            "    passed = False\n"
            "finally:\n"
            "    sys.settrace(None)\n"
            "print(json.dumps({'passed': passed, 'covered': sorted(covered)}))\n"
        )

        result = subprocess.run(
            ["python3", "-c", runner],
            capture_output=True,
            text=True,
            timeout=30,
        )

        data = {"passed": False, "covered": []}
        if result.returncode == 0 and result.stdout.strip():
            for line in reversed(result.stdout.strip().split("\n")):
                try:
                    data = json.loads(line)
                    break
                except (json.JSONDecodeError, ValueError):
                    continue

        results.append(
            {
                "name": func_name,
                "passed": data["passed"],
                "covered_lines": set(data["covered"]),
            }
        )

    return results


def compute_suspiciousness(test_results):
    """Compute Ochiai suspiciousness scores per executed line."""
    fail_results = [r for r in test_results if not r["passed"]]
    pass_results = [r for r in test_results if r["passed"]]
    total_failed = len(fail_results)

    all_lines = set()
    for r in test_results:
        all_lines.update(r["covered_lines"])

    scores = []
    for line in sorted(all_lines):
        ef = sum(1 for r in fail_results if line in r["covered_lines"])
        ep = sum(1 for r in pass_results if line in r["covered_lines"])
        denom = math.sqrt(total_failed * (ef + ep))
        score = ef / denom if denom > 0 else 0.0
        scores.append({"line": line, "score": round(score, 6)})

    scores.sort(key=lambda x: (-x["score"], x["line"]))
    return scores


def get_function_names(tree, line_num):
    """Get all variable names in the function/method containing line_num."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None)
            if end and node.lineno <= line_num <= end:
                names = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Name):
                        names.add(child.id)
                return names
    names = set()
    for child in ast.walk(tree):
        if isinstance(child, ast.Name):
            names.add(child.id)
    return names


def generate_mutations(source_code, line_num):
    """Generate candidate mutated source codes for a given line."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    lines = source_code.split("\n")
    if line_num < 1 or line_num > len(lines):
        return []
    target_line = lines[line_num - 1]
    candidates = []

    def make_source(new_line):
        return "\n".join(lines[: line_num - 1] + [new_line] + lines[line_num:])

    def try_candidate(new_line):
        if new_line == target_line:
            return
        new_source = make_source(new_line)
        try:
            ast.parse(new_source)
            candidates.append(new_source)
        except SyntaxError:
            pass

    # --- Strategy 1: Variable name swaps ---
    func_names = get_function_names(tree, line_num)
    names_on_line = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and hasattr(node, "lineno")
            and node.lineno == line_num
        ):
            names_on_line.append(node)

    for name_node in names_on_line:
        co = name_node.col_offset
        old = name_node.id
        if co >= len(target_line) or target_line[co : co + len(old)] != old:
            continue
        for replacement in sorted(func_names):
            if replacement != old:
                new_line = (
                    target_line[:co] + replacement + target_line[co + len(old) :]
                )
                try_candidate(new_line)

    # --- Strategy 2: Multi-character operator swaps ---
    op_swaps = {
        ">=": [">", "<=", "<", "==", "!="],
        "<=": ["<", ">=", ">", "==", "!="],
        "!=": ["==", ">=", "<="],
        "==": ["!=", ">=", "<="],
        "+=": ["-="],
        "-=": ["+="],
        "**": ["*", "+"],
    }
    for op, repls in op_swaps.items():
        if op in target_line:
            for repl in repls:
                try_candidate(target_line.replace(op, repl, 1))

    # --- Strategy 3: Single-character operator swaps (non-compound) ---
    for match in re.finditer(r"(?<!=)(?<!<)(?<!>)>(?!=)", target_line):
        for repl in ["<", ">=", "<="]:
            try_candidate(
                target_line[: match.start()] + repl + target_line[match.end() :]
            )
    for match in re.finditer(r"(?<!=)(?<!<)(?<!>)<(?!=)", target_line):
        for repl in [">", "<=", ">="]:
            try_candidate(
                target_line[: match.start()] + repl + target_line[match.end() :]
            )

    # --- Strategy 4: Method call argument mutations ---
    for match in re.finditer(r"\.(\w+)\(\)", target_line):
        method = match.group(1)
        for arg in ["0", "-1", "1", "True", "False"]:
            new_frag = f".{method}({arg})"
            try_candidate(
                target_line[: match.start()] + new_frag + target_line[match.end() :]
            )

    for match in re.finditer(r"\.(\w+)\(([^)]+)\)", target_line):
        method = match.group(1)
        try_candidate(
            target_line[: match.start()]
            + f".{method}()"
            + target_line[match.end() :]
        )

    # --- Strategy 5: Subscript mutations ---
    for match in re.finditer(r"\[(\w+)\]", target_line):
        var = match.group(1)
        for repl_expr in [f"{var} + 1", f"{var} - 1"]:
            try_candidate(
                target_line[: match.start()]
                + f"[{repl_expr}]"
                + target_line[match.end() :]
            )

    return candidates


def validate_repair(candidate_source, subject_dir):
    """Test whether a candidate repair passes all tests."""
    tmp_dir = tempfile.mkdtemp(prefix="repair_val_")
    try:
        with open(os.path.join(tmp_dir, "program.py"), "w") as f:
            f.write(candidate_source)
        shutil.copy(
            os.path.join(subject_dir, "test_program.py"),
            os.path.join(tmp_dir, "test_program.py"),
        )
        result = subprocess.run(
            ["python3", "-m", "pytest", "test_program.py", "-x", "--tb=no", "-q"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_dir,
        )
        return result.returncode == 0
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def make_unified_diff(original, fixed, filename="program.py"):
    """Produce a unified diff string."""
    orig_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)
    if orig_lines and not orig_lines[-1].endswith("\n"):
        orig_lines[-1] += "\n"
    if fixed_lines and not fixed_lines[-1].endswith("\n"):
        fixed_lines[-1] += "\n"
    diff = difflib.unified_diff(
        orig_lines, fixed_lines, fromfile=filename, tofile=filename
    )
    return "".join(diff)


def repair_subject(subject_dir, output_dir):
    """Localize fault, search for repair, and write outputs."""
    program_path = os.path.join(subject_dir, "program.py")
    with open(program_path) as f:
        original = f.read()

    test_results = collect_coverage(subject_dir)
    scores = compute_suspiciousness(test_results)

    fixed = None
    for entry in scores[:20]:
        line_num = entry["line"]
        candidates = generate_mutations(original, line_num)
        for candidate in candidates:
            if validate_repair(candidate, subject_dir):
                fixed = candidate
                break
        if fixed:
            break

    if not fixed:
        fixed = original

    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "diagnosis.json"), "w") as f:
        json.dump({"suspicious_lines": scores}, f, indent=2)

    with open(os.path.join(output_dir, "program_fixed.py"), "w") as f:
        f.write(fixed)

    patch = make_unified_diff(original, fixed)
    with open(os.path.join(output_dir, "repair.patch"), "w") as f:
        f.write(patch)

    return fixed != original


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 autorepair.py <subject_dir>")
        sys.exit(1)

    subject_dir = os.path.abspath(sys.argv[1])
    subject_name = os.path.basename(subject_dir)
    output_dir = f"/app/output/{subject_name}"

    success = repair_subject(subject_dir, output_dir)
    print(f"[{subject_name}] {'REPAIRED' if success else 'FAILED'}")


if __name__ == "__main__":
    main()
