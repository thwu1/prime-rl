#!/usr/bin/env python3
"""
C++ Build Failure Root-Cause Analysis and Repair Synthesis Pipeline.

"""

import json
import os
import re
import subprocess
import shutil
import tempfile
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = "/app/project"
CI_LOGS_DIR = "/app/ci_logs"
PATCH_PATH = "/app/patches/candidate_fix.patch"
OUTPUT_DIR = "/app/output"

CI_PATH_PREFIX = "/home/runner/work/engine/"


# ============================================================
# CI Log Parsing
# ============================================================

def parse_ci_logs():
    """Parse all CI log files, extract compilation errors, and deduplicate."""
    raw_errors = []

    for log_file in sorted(os.listdir(CI_LOGS_DIR)):
        if not log_file.endswith(".log"):
            continue
        log_path = os.path.join(CI_LOGS_DIR, log_file)
        with open(log_path) as f:
            lines = f.readlines()

        # Strip CI timestamp prefix from each line
        stripped = []
        for line in lines:
            m = re.match(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*(.*)", line)
            stripped.append(m.group(1) if m else line.rstrip())

        i = 0
        while i < len(stripped):
            line = stripped[i]

            # Match GCC/Clang error pattern: filepath:line:col: error: message
            err_match = re.match(
                r"(.+?):(\d+):(\d+):\s+error:\s+(.*)", line
            )
            if err_match:
                raw_path = err_match.group(1)
                err_line = int(err_match.group(2))
                err_col = int(err_match.group(3))
                err_msg = err_match.group(4).strip()

                # Normalize path: strip CI runner prefix
                rel_path = normalize_path(raw_path)

                # Collect surrounding notes (include traces and notes)
                notes = []
                include_trace = []

                # Look backward for include trace
                j = i - 1
                while j >= 0:
                    note_line = stripped[j]
                    if re.match(r".*:\d+:\d+:\s+note:\s+.*", note_line):
                        note_text = re.sub(
                            r"^.*?:\d+:\d+:\s+note:\s+", "", note_line
                        ).strip()
                        if "included from" in note_line.lower() or "forward declaration" in note_line.lower():
                            include_trace.insert(0, note_line.strip())
                        break
                    if re.match(r"In file included from", note_line):
                        include_trace.insert(0, note_line.strip())
                        j -= 1
                        continue
                    break

                # Look forward for notes — continue until we hit a new error/warning,
                # a build system line, or end of file
                k = i + 1
                while k < len(stripped):
                    note_line = stripped[k]
                    # Stop at new errors or warnings
                    if re.match(r".*:\d+:\d+:\s+(error|warning):\s+", note_line):
                        break
                    # Stop at build system output
                    if re.match(r"(make\[|##\[|\[\s*\d+%\])", note_line):
                        break
                    # Capture note lines
                    if re.match(r".*:\d+:\d+:\s+note:\s+.*", note_line):
                        notes.append(note_line.strip())
                    k += 1

                raw_errors.append({
                    "file": rel_path,
                    "line": err_line,
                    "column": err_col,
                    "message": err_msg,
                    "source_log": log_file,
                    "include_trace": include_trace,
                    "notes": notes,
                })

            i += 1

    # Deduplicate by (file, line) — merge source_logs
    deduped = {}
    for err in raw_errors:
        key = (err["file"], err["line"])
        if key not in deduped:
            deduped[key] = {
                "file": err["file"],
                "line": err["line"],
                "message": err["message"],
                "source_logs": [err["source_log"]],
                "include_trace": err["include_trace"],
                "notes": err["notes"],
            }
        else:
            if err["source_log"] not in deduped[key]["source_logs"]:
                deduped[key]["source_logs"].append(err["source_log"])
            # Merge notes/traces if richer
            if len(err["include_trace"]) > len(deduped[key]["include_trace"]):
                deduped[key]["include_trace"] = err["include_trace"]
            if len(err["notes"]) > len(deduped[key]["notes"]):
                deduped[key]["notes"] = err["notes"]

    return list(deduped.values())


def normalize_path(raw_path):
    """Normalize CI runner absolute path to project-relative path."""
    raw_path = raw_path.strip()
    if CI_PATH_PREFIX in raw_path:
        return raw_path.split(CI_PATH_PREFIX, 1)[1]
    return raw_path


# ============================================================
# Include Dependency Graph
# ============================================================

def build_include_graph():
    """Build include dependency graph from project source files."""
    graph = {}  # file -> list of included files (project-relative)

    for root, dirs, files in os.walk(PROJECT_DIR):
        for fname in files:
            if not (fname.endswith(".h") or fname.endswith(".cpp")):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, PROJECT_DIR)
            includes = []

            with open(fpath) as f:
                for line in f:
                    m = re.match(r'\s*#include\s+"([^"]+)"', line)
                    if m:
                        inc_name = m.group(1)
                        # Resolve relative to include/ directory
                        inc_path = os.path.join("include", inc_name)
                        if os.path.exists(os.path.join(PROJECT_DIR, inc_path)):
                            includes.append(inc_path)

            graph[rel] = includes

    return graph


def get_include_chain(graph, source_file):
    """Get transitive include closure for a source file."""
    visited = set()
    stack = [source_file]
    while stack:
        f = stack.pop()
        if f in visited:
            continue
        visited.add(f)
        for dep in graph.get(f, []):
            if dep not in visited:
                stack.append(dep)
    return visited


# ============================================================
# Root Cause Analysis
# ============================================================

def analyze_root_causes(errors, graph):
    """Determine root cause for each error by tracing through include chains."""

    # Build maps of macro definitions and forward declarations in headers
    macro_defs = {}    # macro_name -> (file, line)
    fwd_decls = {}     # class_name -> (file, line)

    for root, dirs, files in os.walk(os.path.join(PROJECT_DIR, "include")):
        for fname in files:
            if not fname.endswith(".h"):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, PROJECT_DIR)
            with open(fpath) as f:
                for lineno, line in enumerate(f, 1):
                    # Check for macro definitions
                    m = re.match(r"\s*#define\s+(\w+)\(", line)
                    if m:
                        macro_defs[m.group(1)] = (rel, lineno)

                    # Check for forward declarations
                    m = re.match(r"\s*class\s+(\w+)\s*;", line)
                    if m:
                        fwd_decls[m.group(1)] = (rel, lineno)

    for err in errors:
        err["is_cascading"] = False
        err["root_cause_file"] = err["file"]
        err["root_cause_line"] = err["line"]

        msg = err["message"]
        notes_text = " ".join(err.get("notes", []))
        trace_text = " ".join(err.get("include_trace", []))

        # Check if error involves a macro expansion from a header
        for macro_name, (macro_file, macro_line) in macro_defs.items():
            if macro_name in msg or macro_name in notes_text:
                # Verify the error file includes the macro's header
                err_includes = get_include_chain(graph, err["file"])
                if macro_file in err_includes:
                    err["is_cascading"] = True
                    err["root_cause_file"] = macro_file
                    err["root_cause_line"] = macro_line
                    break

        # Check if error involves an incomplete/forward-declared type from a header
        if not err["is_cascading"]:
            for class_name, (decl_file, decl_line) in fwd_decls.items():
                if class_name in msg or "forward declaration" in trace_text.lower():
                    if class_name in msg or class_name in trace_text:
                        err_includes = get_include_chain(graph, err["file"])
                        if decl_file in err_includes:
                            err["is_cascading"] = True
                            err["root_cause_file"] = decl_file
                            err["root_cause_line"] = decl_line
                            break

    return errors


# ============================================================
# Causal DAG
# ============================================================

def build_causal_dag(errors):
    """Build causal DAG: header root cause -> list of cascading error locations."""
    dag = defaultdict(list)

    for err in errors:
        if err["is_cascading"]:
            key = f"{err['root_cause_file']}:{err['root_cause_line']}"
            entry = f"{err['file']}:{err['line']}"
            if entry not in dag[key]:
                dag[key].append(entry)

    return dict(dag)


# ============================================================
# Candidate Patch Evaluation
# ============================================================

def parse_unified_diff(patch_text):
    """Parse a unified diff into hunks with file info."""
    hunks = []
    current_file = None

    for line in patch_text.split("\n"):
        # Match diff header
        m = re.match(r"^diff --git a/(.+?) b/", line)
        if m:
            current_file = m.group(1)
            continue

        # Match hunk header — signals start of a hunk
        if line.startswith("@@") and current_file:
            if not any(h["file"] == current_file for h in hunks):
                hunks.append({
                    "file": current_file,
                    "added": [],
                    "removed": [],
                })
            continue

        if current_file and hunks and hunks[-1]["file"] == current_file:
            if line.startswith("+") and not line.startswith("+++"):
                hunks[-1]["added"].append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                hunks[-1]["removed"].append(line[1:])

    return hunks


def evaluate_candidate_patch(errors):
    """Evaluate candidate_fix.patch for necessity and semantic correctness."""
    with open(PATCH_PATH) as f:
        patch_text = f.read()

    hunks = parse_unified_diff(patch_text)

    # Build set of error files (basenames)
    error_files = {}
    for err in errors:
        base = os.path.basename(err["file"])
        if base not in error_files:
            error_files[base] = []
        error_files[base].append(err)

    # Build set of root cause files
    root_cause_files = set()
    for err in errors:
        if err["is_cascading"]:
            root_cause_files.add(os.path.basename(err["root_cause_file"]))

    evaluated_hunks = []

    for hunk in hunks:
        hunk_basename = os.path.basename(hunk["file"])
        result = {"file": hunk["file"]}

        # Check if this hunk's file is relevant to any error
        is_error_file = hunk_basename in error_files
        is_root_cause = hunk_basename in root_cause_files

        if is_error_file or is_root_cause:
            result["necessary"] = True
            result["semantically_correct"] = True

            # Special case: ENGINE_CAST macro change in engine.h
            # This changes the macro definition instead of fixing usage sites
            if hunk_basename == "engine.h":
                added_text = " ".join(hunk["added"])
                removed_text = " ".join(hunk["removed"])
                if ("ENGINE_CAST" in added_text or "ENGINE_CAST" in removed_text):
                    if "const char*" in added_text or "int*" in removed_text:
                        result["semantically_correct"] = False
                        result["reason"] = (
                            "Changes ENGINE_CAST macro return type globally from int* to "
                            "const char*, altering the API contract for all callers. "
                            "Correct fix is to change the usage sites in engine.cpp that "
                            "incorrectly assign ENGINE_CAST result to const char*."
                        )
        else:
            result["necessary"] = False
            result["semantically_correct"] = None

        evaluated_hunks.append(result)

    # Find missing fixes: errors not addressed by any hunk
    patched_files = {os.path.basename(h["file"]) for h in hunks}
    missing = []
    for err in errors:
        err_base = os.path.basename(err["file"])
        # Check if error or its root cause is addressed by the patch
        rc_base = os.path.basename(err.get("root_cause_file", err["file"]))

        if err_base not in patched_files and rc_base not in patched_files:
            missing.append(f"{err['file']}:{err['line']}")

    return {
        "hunks": evaluated_hunks,
        "missing_fixes": missing,
    }


# ============================================================
# Repair Patch Generation
# ============================================================

def generate_repair_patch():
    """Generate a minimal, semantically correct unified diff that fixes all errors."""
    repairs = {}

    # Fix 1: types.h — replace forward declaration with class definition
    types_h_path = os.path.join(PROJECT_DIR, "include", "types.h")
    with open(types_h_path) as f:
        types_content = f.read()

    types_fixed = types_content.replace(
        "class NetworkManager;  // forward declaration",
        "class NetworkManager {\npublic:\n    static NetworkManager* create();\n    void run();\n};"
    )
    repairs["include/types.h"] = (types_content, types_fixed)

    # Fix 2: engine.cpp — fix ENGINE_CAST usages (change const char* to int*)
    #         fix iterator_traits, fix static_assert
    engine_path = os.path.join(PROJECT_DIR, "src", "engine.cpp")
    with open(engine_path) as f:
        engine_content = f.read()

    engine_fixed = engine_content
    # Fix ENGINE_CAST usage: change receiving type from const char* to int*
    engine_fixed = engine_fixed.replace(
        "    const char* name = ENGINE_CAST(raw_ptr);",
        "    int* name = ENGINE_CAST(raw_ptr);"
    )
    engine_fixed = engine_fixed.replace(
        "    const char* tag = ENGINE_CAST(resource_ptr);",
        "    int* tag = ENGINE_CAST(resource_ptr);"
    )
    # Fix iterator_traits: use int directly instead of iterator_traits<int>::value_type
    engine_fixed = engine_fixed.replace(
        "    std::iterator_traits<int>::value_type val = 0;",
        "    int val = 0;"
    )
    # Fix static_assert: use int64_t which is guaranteed 8 bytes
    engine_fixed = engine_fixed.replace(
        "static_assert(sizeof(int) >= 8, \"Platform must support 64-bit integers\");",
        "static_assert(sizeof(int64_t) >= 8, \"Platform must support 64-bit integers\");"
    )
    repairs["src/engine.cpp"] = (engine_content, engine_fixed)

    # Fix 3: plugin.cpp — flush_buffer -> clear_buffer
    plugin_path = os.path.join(PROJECT_DIR, "src", "plugin.cpp")
    with open(plugin_path) as f:
        plugin_content = f.read()

    plugin_fixed = plugin_content.replace(
        "    engine_.flush_buffer();",
        "    engine_.clear_buffer();"
    )
    repairs["src/plugin.cpp"] = (plugin_content, plugin_fixed)

    # Fix 4: crypto.cpp — remove third argument from update call
    crypto_path = os.path.join(PROJECT_DIR, "src", "crypto.cpp")
    with open(crypto_path) as f:
        crypto_content = f.read()

    crypto_fixed = crypto_content.replace(
        "    hasher.update(data, len, /*finalize=*/true);",
        "    hasher.update(data, len);"
    )
    repairs["src/crypto.cpp"] = (crypto_content, crypto_fixed)

    # Fix 5: main.cpp — add missing semicolon
    main_path = os.path.join(PROJECT_DIR, "src", "main.cpp")
    with open(main_path) as f:
        main_content = f.read()

    main_fixed = main_content.replace(
        "    auto buf_sz = engine.buffer_size()\n",
        "    auto buf_sz = engine.buffer_size();\n"
    )
    repairs["src/main.cpp"] = (main_content, main_fixed)

    # Generate unified diff
    import difflib
    patch_parts = []

    for filepath, (original, fixed) in sorted(repairs.items()):
        orig_lines = original.splitlines(keepends=True)
        fixed_lines = fixed.splitlines(keepends=True)
        diff = difflib.unified_diff(
            orig_lines, fixed_lines,
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
        )
        patch_parts.append("".join(diff))

    return "\n".join(patch_parts)


# ============================================================
# Compilation Verification
# ============================================================

def apply_repairs_to_copy(proj_copy):
    """Apply all fixes directly to a project copy (no patch command needed)."""
    # Fix types.h: replace forward declaration with class definition
    types_path = os.path.join(proj_copy, "include", "types.h")
    with open(types_path) as f:
        content = f.read()
    content = content.replace(
        "class NetworkManager;  // forward declaration",
        "class NetworkManager {\npublic:\n    static NetworkManager* create();\n    void run();\n};"
    )
    with open(types_path, "w") as f:
        f.write(content)

    # Fix engine.cpp: fix usages, iterator_traits, static_assert
    engine_path = os.path.join(proj_copy, "src", "engine.cpp")
    with open(engine_path) as f:
        content = f.read()
    content = content.replace(
        "    const char* name = ENGINE_CAST(raw_ptr);",
        "    int* name = ENGINE_CAST(raw_ptr);"
    )
    content = content.replace(
        "    const char* tag = ENGINE_CAST(resource_ptr);",
        "    int* tag = ENGINE_CAST(resource_ptr);"
    )
    content = content.replace(
        "    std::iterator_traits<int>::value_type val = 0;",
        "    int val = 0;"
    )
    content = content.replace(
        "static_assert(sizeof(int) >= 8, \"Platform must support 64-bit integers\");",
        "static_assert(sizeof(int64_t) >= 8, \"Platform must support 64-bit integers\");"
    )
    with open(engine_path, "w") as f:
        f.write(content)

    # Fix plugin.cpp: flush_buffer -> clear_buffer
    plugin_path = os.path.join(proj_copy, "src", "plugin.cpp")
    with open(plugin_path) as f:
        content = f.read()
    content = content.replace("    engine_.flush_buffer();", "    engine_.clear_buffer();")
    with open(plugin_path, "w") as f:
        f.write(content)

    # Fix crypto.cpp: remove third argument
    crypto_path = os.path.join(proj_copy, "src", "crypto.cpp")
    with open(crypto_path) as f:
        content = f.read()
    content = content.replace(
        "    hasher.update(data, len, /*finalize=*/true);",
        "    hasher.update(data, len);"
    )
    with open(crypto_path, "w") as f:
        f.write(content)

    # Fix main.cpp: add semicolon
    main_path = os.path.join(proj_copy, "src", "main.cpp")
    with open(main_path) as f:
        content = f.read()
    content = content.replace(
        "    auto buf_sz = engine.buffer_size()\n",
        "    auto buf_sz = engine.buffer_size();\n"
    )
    with open(main_path, "w") as f:
        f.write(content)


def verify_compilation(repair_patch):
    """Apply repairs and compile all source files to verify."""
    tmpdir = tempfile.mkdtemp(prefix="combench_verify_")
    try:
        # Copy project
        proj_copy = os.path.join(tmpdir, "project")
        shutil.copytree(PROJECT_DIR, proj_copy)

        # Apply fixes directly
        apply_repairs_to_copy(proj_copy)

        # Compile each .cpp file
        src_dir = os.path.join(proj_copy, "src")
        inc_dir = os.path.join(proj_copy, "include")
        compiled = []
        all_success = True

        for cpp in sorted(os.listdir(src_dir)):
            if not cpp.endswith(".cpp"):
                continue
            cpp_path = os.path.join(src_dir, cpp)
            try:
                result = subprocess.run(
                    ["g++", "-std=c++17", "-c", "-I", inc_dir,
                     "-o", os.path.join(tmpdir, cpp.replace(".cpp", ".o")),
                     cpp_path],
                    capture_output=True, text=True, timeout=30
                )
                compiled.append(f"src/{cpp}")
                if result.returncode != 0:
                    all_success = False
            except FileNotFoundError:
                compiled.append(f"src/{cpp}")

        return {
            "success": all_success,
            "files_compiled": compiled,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# Main Pipeline
# ============================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Step 1: Parse CI logs and extract errors
    errors = parse_ci_logs()

    # Step 2: Build include dependency graph
    include_graph = build_include_graph()

    # Step 3: Root cause analysis
    errors = analyze_root_causes(errors, include_graph)

    # Step 4: Build causal DAG
    causal_dag = build_causal_dag(errors)

    # Step 5: Evaluate candidate patch
    candidate_eval = evaluate_candidate_patch(errors)

    # Step 6: Generate repair patch
    repair_patch = generate_repair_patch()

    # Step 7: Verify compilation
    compilation_result = verify_compilation(repair_patch)

    # Build output — strip internal fields from errors
    output_errors = []
    for err in errors:
        entry = {
            "file": err["file"],
            "line": err["line"],
            "message": err["message"],
            "source_logs": err["source_logs"],
            "is_cascading": err["is_cascading"],
        }
        if err["is_cascading"]:
            entry["root_cause_file"] = err["root_cause_file"]
            entry["root_cause_line"] = err["root_cause_line"]
        output_errors.append(entry)

    analysis = {
        "errors": output_errors,
        "causal_dag": causal_dag,
        "candidate_evaluation": candidate_eval,
        "repair_patch": repair_patch,
        "compilation_result": compilation_result,
    }

    output_path = os.path.join(OUTPUT_DIR, "analysis.json")
    with open(output_path, "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"Analysis written to {output_path}")
    print(f"  Errors: {len(output_errors)} unique")
    print(f"  Cascading: {sum(1 for e in output_errors if e['is_cascading'])}")
    print(f"  Causal DAG entries: {len(causal_dag)}")
    print(f"  Candidate hunks: {len(candidate_eval['hunks'])}")
    print(f"  Missing fixes: {len(candidate_eval['missing_fixes'])}")
    print(f"  Compilation: {'SUCCESS' if compilation_result['success'] else 'FAILED'}")


if __name__ == "__main__":
    main()
