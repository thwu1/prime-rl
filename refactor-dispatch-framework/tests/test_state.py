"""
Verification tests for the C command dispatch framework refactoring.

Tests check that all refactoring objectives were achieved:
1. Handler functions return int (error propagation)
2. handler_func_t typedef returns int
3. dispatch_command/dispatch_pipeline return int
4. CMD_MEMORY_MODE renamed to CMD_ALLOC_STRATEGY everywhere
5. Stats extracted to stats.c/stats.h
6. Circular #include dependency between handlers.h and dispatch.h is broken
7. warn_unused_result attribute on dispatch functions
8. Duplicated handler execution pattern consolidated
9. FRAMEWORK_MAGIC and handler error codes preserved
10. Functional correctness (compile + run test driver with exact value checks)
"""

import subprocess
import os
import re
import shutil

APP = "/app"


def _read(fname):
    with open(os.path.join(APP, fname)) as f:
        return f.read()


def _all_source_content():
    """Return concatenated content of all .c and .h files in /app."""
    parts = []
    for fname in sorted(os.listdir(APP)):
        if fname.endswith((".c", ".h")):
            parts.append(_read(fname))
    return "\n".join(parts)


# ---- Structural: return types ----

def test_handler_functions_return_int():
    """All handle_* functions must return int, not void."""
    content = _read("handlers.h")
    for name in ("handle_query", "handle_insert", "handle_update",
                 "handle_delete", "handle_batch"):
        assert re.search(rf"\bint\s+{name}\s*\(", content), \
            f"{name} must return int in handlers.h"


def test_handler_func_typedef_returns_int():
    """handler_func_t typedef must specify int return type."""
    all_h = ""
    for fname in os.listdir(APP):
        if fname.endswith(".h"):
            all_h += _read(fname) + "\n"
    assert re.search(r"typedef\s+int\s*\(\s*\*\s*handler_func_t\s*\)", all_h), \
        "handler_func_t must be typedef'd to return int"


def test_dispatch_functions_return_int():
    """dispatch_command and dispatch_pipeline must return int."""
    content = _read("dispatch.h")
    assert re.search(r"\bint\s+dispatch_command\s*\(", content), \
        "dispatch_command must return int"
    assert re.search(r"\bint\s+dispatch_pipeline\s*\(", content), \
        "dispatch_pipeline must return int"


# ---- Structural: enum rename ----

def test_no_cmd_memory_mode_anywhere():
    """CMD_MEMORY_MODE must not appear in any source file."""
    for fname in os.listdir(APP):
        if fname.endswith((".c", ".h")):
            content = _read(fname)
            assert "CMD_MEMORY_MODE" not in content, \
                f"CMD_MEMORY_MODE still present in {fname}"


def test_cmd_alloc_strategy_defined():
    """CMD_ALLOC_STRATEGY enum and values must be defined."""
    all_h = ""
    for fname in os.listdir(APP):
        if fname.endswith(".h"):
            all_h += _read(fname) + "\n"
    assert "CMD_ALLOC_STRATEGY" in all_h, \
        "CMD_ALLOC_STRATEGY enum not found"
    for val in ("CMD_ALLOC_NONE", "CMD_ALLOC_STACK",
                "CMD_ALLOC_HEAP", "CMD_ALLOC_POOL"):
        assert val in all_h, f"Enum value {val} not found in headers"


def test_alloc_strategy_functions_renamed():
    """cmd_memory_mode_name/from_name must be renamed."""
    all_code = _all_source_content()
    assert "cmd_alloc_strategy_name" in all_code, \
        "cmd_alloc_strategy_name function not found"
    assert "cmd_alloc_strategy_from_name" in all_code, \
        "cmd_alloc_strategy_from_name function not found"
    assert "cmd_memory_mode_name" not in all_code, \
        "Old cmd_memory_mode_name still present"
    assert "cmd_memory_mode_from_name" not in all_code, \
        "Old cmd_memory_mode_from_name still present"


# ---- DNA: framework magic and error codes ----

def test_framework_magic_preserved():
    """FRAMEWORK_MAGIC constant must be preserved in the refactored headers."""
    all_h = ""
    for fname in os.listdir(APP):
        if fname.endswith(".h"):
            all_h += _read(fname) + "\n"
    assert "0xa7f3c9e2" in all_h.lower(), \
        "FRAMEWORK_MAGIC (0xA7F3C9E2) not found in headers"
    assert re.search(r"\bunsigned\s+long\s+magic\b", all_h), \
        "magic field not found in dispatch_ctx struct"


def test_handler_error_codes_preserved():
    """Handler-specific error codes must be preserved in handlers.c."""
    content = _read("handlers.c")
    # Each handler uses a unique prime-based error code
    expected_codes = {
        "-17": "null argument error code",
        "-23": "query syntax error code",
        "-29": "insert duplicate error code",
        "-37": "update conflict error code",
        "-41": "delete protected error code",
        "-47": "batch toolarge error code",
    }
    for code, desc in expected_codes.items():
        assert code in content, \
            f"{desc} ({code}) not found in handlers.c"


# ---- Structural: stats extraction ----

def test_stats_files_exist():
    """stats.c and stats.h must exist as separate files."""
    assert os.path.isfile(os.path.join(APP, "stats.h")), "stats.h missing"
    assert os.path.isfile(os.path.join(APP, "stats.c")), "stats.c missing"


def test_stats_declarations_in_header():
    """stats.h must declare core stats functions."""
    content = _read("stats.h")
    for func in ("stats_init", "stats_cleanup", "stats_record_latency",
                 "stats_record_error", "stats_get_total_errors",
                 "stats_report"):
        assert func in content, f"{func} not declared in stats.h"


def test_stats_impl_not_in_dispatch():
    """g_stats and stats implementations must not be in dispatch.c."""
    content = _read("dispatch.c")
    assert "g_stats" not in content, \
        "g_stats struct still in dispatch.c — extract to stats.c"


# ---- Structural: circular dependency ----

def test_handlers_h_no_dispatch_include():
    """handlers.h must not #include dispatch.h (breaks circular dep)."""
    content = _read("handlers.h")
    includes = re.findall(r'#\s*include\s+"dispatch\.h"', content)
    assert len(includes) == 0, \
        'handlers.h still includes dispatch.h — use forward declaration'


def test_handlers_h_forward_declares_ctx():
    """handlers.h must forward-declare struct dispatch_ctx."""
    content = _read("handlers.h")
    assert re.search(r"\bstruct\s+dispatch_ctx\b", content), \
        "handlers.h must forward-declare struct dispatch_ctx"


def test_handlers_h_compiles_alone():
    """handlers.h must compile independently (no implicit dispatch.h)."""
    test_src = "/tmp/_test_handlers_indep.c"
    with open(test_src, "w") as f:
        f.write('#include "handlers.h"\nint main(void){return 0;}\n')
    result = subprocess.run(
        ["gcc", "-Wall", "-Wextra", "-std=c11", "-D_GNU_SOURCE",
         "-fsyntax-only", "-I", APP, test_src],
        capture_output=True, text=True
    )
    assert result.returncode == 0, \
        f"handlers.h fails to compile alone:\n{result.stderr}"


# ---- Structural: warn_unused_result ----

def test_warn_unused_result_attribute():
    """dispatch.h must have warn_unused_result on dispatch functions."""
    content = _read("dispatch.h")
    assert "warn_unused_result" in content, \
        "warn_unused_result attribute missing from dispatch.h"


# ---- Structural: consolidated helper ----

def test_handler_execution_consolidated():
    """Duplicated timing/stats pattern should be consolidated."""
    content = _read("dispatch.c")
    # After consolidation, clock_gettime should appear at most twice
    # (one start + one end, in a single helper function)
    count = content.count("clock_gettime")
    assert count <= 2, \
        f"Expected clock_gettime in one helper only (<=2 calls), found {count}"


# ---- Compilation ----

def test_project_compiles():
    """Refactored code must compile cleanly with make."""
    subprocess.run(["make", "clean"], cwd=APP, capture_output=True)
    result = subprocess.run(["make"], cwd=APP, capture_output=True, text=True)
    assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"


# ---- Functional: test driver with DNA verification ----

def test_functional_test_driver():
    """Compile and run test_driver.c; verify exact computed values."""
    # Ensure the project is built first
    subprocess.run(["make", "clean"], cwd=APP, capture_output=True)
    build = subprocess.run(["make"], cwd=APP, capture_output=True, text=True)
    assert build.returncode == 0, f"Build failed:\n{build.stderr}"

    # Gather all .c source files except main.c
    srcs = [os.path.join(APP, f)
            for f in sorted(os.listdir(APP))
            if f.endswith(".c") and f != "main.c"]

    # Compile test driver
    compile_cmd = [
        "gcc", "-Wall", "-Wextra", "-std=c11", "-D_GNU_SOURCE", "-g",
        "-I", APP,
        "-o", "/tmp/_test_driver",
        "/tests/test_driver.c",
    ] + srcs
    result = subprocess.run(compile_cmd, capture_output=True, text=True)
    assert result.returncode == 0, \
        f"Test driver compilation failed:\n{result.stderr}"

    # Run test driver
    result = subprocess.run(
        ["/tmp/_test_driver"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, \
        f"Test driver returned non-zero:\n{result.stdout}\n{result.stderr}"

    out = result.stdout

    # Verify framework magic (DNA)
    assert "VERIFY:magic=0xa7f3c9e2" in out, \
        f"Framework magic 0xa7f3c9e2 not verified in output"

    # Verify handler error codes (DNA)
    assert "VERIFY:query_null=-17" in out, \
        "Query null-arg error code -17 not verified"
    assert "VERIFY:query_invalid=-23" in out, \
        "Query syntax error code -23 not verified"
    assert "VERIFY:insert_dup=-29" in out, \
        "Insert duplicate error code -29 not verified"
    assert "VERIFY:update_conflict=-37" in out, \
        "Update conflict error code -37 not verified"
    assert "VERIFY:delete_protected=-41" in out, \
        "Delete protected error code -41 not verified"
    assert "VERIFY:batch_toolarge=-47" in out, \
        "Batch toolarge error code -47 not verified"

    # Verify dispatch command propagation (DNA)
    assert "VERIFY:dispatch_cmd_err=-29" in out, \
        "dispatch_command did not propagate error code -29"

    # Verify pipeline short-circuit (DNA)
    assert "VERIFY:pipeline_sc=-29,insert_errs=1,delete_errs=0" in out, \
        "Pipeline short-circuit not working correctly"

    # Verify stats counts (DNA)
    assert "VERIFY:total_errors=3" in out, \
        "Stats total error count incorrect"
    assert "VERIFY:query_errs=1,insert_errs=2" in out, \
        "Stats per-type error counts incorrect"

    # Overall pass marker
    assert "ALL_TESTS_PASSED" in out, \
        f"Not all tests passed:\n{out}"
