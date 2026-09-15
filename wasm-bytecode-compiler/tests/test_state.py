
import subprocess
import json
import os
import pytest

MODULES_DIR = "/app/modules"
TOOL = "/app/wasm_abc"


def run_tool(args, check=True):
    """Run the wasm_abc tool and return stdout."""
    result = subprocess.run(
        [TOOL] + args,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"wasm_abc failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


def compile_module(name):
    """Compile a module and return the JSON report."""
    wasm = os.path.join(MODULES_DIR, f"{name}.wasm")
    out = f"/tmp/test_{name}.json"
    run_tool(["compile", wasm, out])
    with open(out) as f:
        return json.load(f)


def run_func(module_name, func_name, args):
    """Run a function and return the integer result."""
    wasm = os.path.join(MODULES_DIR, f"{module_name}.wasm")
    str_args = [str(a) for a in args]
    stdout = run_tool(["run", wasm, func_name] + str_args)
    return int(stdout)


# ── Tool existence and executability ──────────────────────────────

class TestToolSetup:
    def test_tool_exists(self):
        assert os.path.exists(TOOL), f"{TOOL} does not exist"

    def test_tool_executable(self):
        assert os.access(TOOL, os.X_OK), f"{TOOL} is not executable"

    def test_modules_exist(self):
        for name in ["arith", "control", "nested", "calls", "switch"]:
            path = os.path.join(MODULES_DIR, f"{name}.wasm")
            assert os.path.exists(path), f"{path} missing"


# ── Execution correctness (run subcommand) ───────────────────────

class TestRunArith:
    def test_add_basic(self):
        assert run_func("arith", "add", [3, 5]) == 8

    def test_add_zero(self):
        assert run_func("arith", "add", [0, 0]) == 0

    def test_add_negative(self):
        assert run_func("arith", "add", [-10, 3]) == -7

    def test_complex(self):
        # 2*3 + 4 = 10
        assert run_func("arith", "complex", [2, 3, 4]) == 10

    def test_complex_large(self):
        # 100*200 + 50 = 20050
        assert run_func("arith", "complex", [100, 200, 50]) == 20050


class TestRunControlFlow:
    def test_abs_negative(self):
        assert run_func("control", "abs", [-5]) == 5

    def test_abs_positive(self):
        assert run_func("control", "abs", [5]) == 5

    def test_abs_zero(self):
        assert run_func("control", "abs", [0]) == 0

    def test_sum_to_n_10(self):
        assert run_func("control", "sum_to_n", [10]) == 55

    def test_sum_to_n_100(self):
        assert run_func("control", "sum_to_n", [100]) == 5050

    def test_sum_to_n_0(self):
        assert run_func("control", "sum_to_n", [0]) == 0

    def test_sum_to_n_1(self):
        assert run_func("control", "sum_to_n", [1]) == 1

    def test_fib_10(self):
        assert run_func("control", "fib", [10]) == 55

    def test_fib_0(self):
        assert run_func("control", "fib", [0]) == 0

    def test_fib_1(self):
        assert run_func("control", "fib", [1]) == 1

    def test_fib_20(self):
        assert run_func("control", "fib", [20]) == 6765


class TestRunNestedBlocks:
    def test_classify_negative(self):
        assert run_func("nested", "classify", [-5]) == -1

    def test_classify_large_negative(self):
        assert run_func("nested", "classify", [-100]) == -1

    def test_classify_in_range(self):
        assert run_func("nested", "classify", [5]) == 0

    def test_classify_zero(self):
        assert run_func("nested", "classify", [0]) == 0

    def test_classify_boundary(self):
        assert run_func("nested", "classify", [10]) == 0

    def test_classify_above(self):
        assert run_func("nested", "classify", [15]) == 1

    def test_classify_large_above(self):
        assert run_func("nested", "classify", [999]) == 1


class TestRunCalls:
    def test_quadruple(self):
        assert run_func("calls", "quadruple", [7]) == 28

    def test_quadruple_zero(self):
        assert run_func("calls", "quadruple", [0]) == 0

    def test_sum_doubles(self):
        # double(3) + double(4) = 6 + 8 = 14
        assert run_func("calls", "sum_doubles", [3, 4]) == 14

    def test_sum_doubles_same(self):
        assert run_func("calls", "sum_doubles", [5, 5]) == 20


class TestRunBrTable:
    def test_switch_0(self):
        assert run_func("switch", "switch_val", [0]) == 10

    def test_switch_1(self):
        assert run_func("switch", "switch_val", [1]) == 20

    def test_switch_2(self):
        assert run_func("switch", "switch_val", [2]) == 30

    def test_switch_3_default(self):
        assert run_func("switch", "switch_val", [3]) == 40

    def test_switch_large_default(self):
        assert run_func("switch", "switch_val", [99]) == 40


# ── Compile output structure ─────────────────────────────────────

class TestCompileStructure:
    def test_arith_function_count(self):
        report = compile_module("arith")
        assert report["summary"]["total_functions"] == 2

    def test_control_function_count(self):
        report = compile_module("control")
        assert report["summary"]["total_functions"] == 3

    def test_nested_function_count(self):
        report = compile_module("nested")
        assert report["summary"]["total_functions"] == 1

    def test_calls_function_count(self):
        report = compile_module("calls")
        # 3 functions ($double + quadruple + sum_doubles)
        assert report["summary"]["total_functions"] == 3

    def test_switch_function_count(self):
        report = compile_module("switch")
        assert report["summary"]["total_functions"] == 1

    def test_export_names_arith(self):
        report = compile_module("arith")
        exports = {f["export_name"] for f in report["functions"]}
        assert "add" in exports
        assert "complex" in exports

    def test_export_names_control(self):
        report = compile_module("control")
        exports = {f["export_name"] for f in report["functions"]}
        assert "abs" in exports
        assert "sum_to_n" in exports
        assert "fib" in exports

    def test_param_counts_arith(self):
        report = compile_module("arith")
        by_name = {f["export_name"]: f for f in report["functions"]}
        assert by_name["add"]["param_count"] == 2
        assert by_name["complex"]["param_count"] == 3

    def test_local_counts_control(self):
        report = compile_module("control")
        by_name = {f["export_name"]: f for f in report["functions"]}
        assert by_name["abs"]["local_count"] == 0
        assert by_name["sum_to_n"]["local_count"] == 1
        assert by_name["fib"]["local_count"] == 3


class TestCompileExpansion:
    """Annotated bytecode should always be larger than original due to
    fixed-width immediate expansion (structural opcodes are elided but
    index/const immediates grow from 1-2 bytes to 4-8)."""

    def test_expansion_arith(self):
        report = compile_module("arith")
        for func in report["functions"]:
            assert func["annotated_bytes"] > func["original_code_bytes"], (
                f"Function {func['export_name']}: annotated ({func['annotated_bytes']}) "
                f"should exceed original ({func['original_code_bytes']})"
            )

    def test_expansion_control(self):
        report = compile_module("control")
        for func in report["functions"]:
            assert func["annotated_bytes"] > func["original_code_bytes"]

    def test_expansion_ratio_positive(self):
        report = compile_module("arith")
        for func in report["functions"]:
            assert func["expansion_ratio"] > 1.0

    def test_summary_averages(self):
        report = compile_module("arith")
        s = report["summary"]
        assert s["total_annotated_bytes"] > s["total_original_bytes"]
        assert s["average_expansion_ratio"] > 1.0


class TestCompileBranchTargets:
    """Branch targets must be valid offsets within the annotated stream."""

    def test_control_has_branch_targets(self):
        report = compile_module("control")
        by_name = {f["export_name"]: f for f in report["functions"]}
        # abs has if/else
        abs_targets = by_name["abs"]["branch_targets"]
        assert len(abs_targets) > 0, "abs should have branch targets for if/else"

        # sum_to_n has br_if and br
        sum_targets = by_name["sum_to_n"]["branch_targets"]
        assert len(sum_targets) >= 2, "sum_to_n should have branch targets for br_if and br"

    def test_nested_has_branch_targets(self):
        report = compile_module("nested")
        func = report["functions"][0]
        targets = func["branch_targets"]
        # classify has br_if 0, br_if 1, br 2 = 3 branch targets
        assert len(targets) >= 3, "classify should have >= 3 branch targets"

    def test_branch_targets_within_bounds(self):
        """All branch targets must point to valid offsets."""
        for module_name in ["arith", "control", "nested", "calls", "switch"]:
            report = compile_module(module_name)
            for func in report["functions"]:
                stream_size = func["annotated_bytes"]
                for offset_str, target in func["branch_targets"].items():
                    offset = int(offset_str)
                    assert 0 <= offset < stream_size, (
                        f"Branch offset {offset} out of bounds in {func['export_name']} "
                        f"(stream size {stream_size})"
                    )
                    assert 0 <= target <= stream_size, (
                        f"Branch target {target} out of bounds in {func['export_name']} "
                        f"(stream size {stream_size})"
                    )

    def test_switch_has_br_table_target(self):
        report = compile_module("switch")
        func = report["functions"][0]
        targets = func["branch_targets"]
        assert len(targets) >= 1, "switch_val should have a br_table branch target"


# ── Fusion candidate detection ───────────────────────────────────

class TestFusionDetection:
    def test_arith_fusion_count(self):
        report = compile_module("arith")
        total = report["summary"]["total_fusion_candidates"]
        assert total == 2, f"arith should have 2 fusion candidates, got {total}"

    def test_arith_fusion_patterns(self):
        report = compile_module("arith")
        by_name = {f["export_name"]: f for f in report["functions"]}
        add_patterns = {c["pattern"] for c in by_name["add"]["fusion_candidates"]}
        assert "i32_add_locals" in add_patterns

        complex_patterns = {c["pattern"] for c in by_name["complex"]["fusion_candidates"]}
        assert "i32_mul_locals" in complex_patterns

    def test_control_fusion_sum_to_n(self):
        report = compile_module("control")
        by_name = {f["export_name"]: f for f in report["functions"]}
        sum_cands = by_name["sum_to_n"]["fusion_candidates"]
        patterns = {c["pattern"] for c in sum_cands}
        # Should detect i32_const_set (i32.const 0; local.set 1) and
        # i32_add_locals (local.get 1; local.get 0; i32.add)
        assert "i32_const_set" in patterns, f"Expected i32_const_set in sum_to_n, got {patterns}"
        assert "i32_add_locals" in patterns, f"Expected i32_add_locals in sum_to_n, got {patterns}"

    def test_control_fusion_fib(self):
        report = compile_module("control")
        by_name = {f["export_name"]: f for f in report["functions"]}
        fib_cands = by_name["fib"]["fusion_candidates"]
        patterns = [c["pattern"] for c in fib_cands]
        # fib should have: 2x i32_const_set, 2x local_copy, 1x i32_add_locals = 5
        assert patterns.count("i32_const_set") == 2, f"Expected 2 i32_const_set, got {patterns}"
        assert patterns.count("local_copy") == 2, f"Expected 2 local_copy, got {patterns}"
        assert patterns.count("i32_add_locals") == 1, f"Expected 1 i32_add_locals, got {patterns}"
        assert len(fib_cands) == 5, f"Expected 5 fusion candidates in fib, got {len(fib_cands)}"

    def test_calls_fusion(self):
        report = compile_module("calls")
        # $double has local.get + local.get + i32.add = i32_add_locals
        all_cands = []
        for func in report["functions"]:
            all_cands.extend(func["fusion_candidates"])
        patterns = [c["pattern"] for c in all_cands]
        assert "i32_add_locals" in patterns, \
            f"calls module should have i32_add_locals (in $double), got {patterns}"

    def test_fusion_candidate_offsets_valid(self):
        """Fusion candidate offsets must be within the annotated stream."""
        for module_name in ["arith", "control", "nested", "calls", "switch"]:
            report = compile_module(module_name)
            for func in report["functions"]:
                stream_size = func["annotated_bytes"]
                for cand in func["fusion_candidates"]:
                    assert 0 <= cand["offset"] < stream_size, (
                        f"Fusion offset {cand['offset']} out of bounds in "
                        f"{func['export_name']} (stream size {stream_size})"
                    )
                    assert cand["length"] >= 2, "Fused patterns must be >= 2 instructions"

    def test_fusion_offsets_non_overlapping(self):
        """Fusion candidates must not overlap."""
        for module_name in ["arith", "control"]:
            report = compile_module(module_name)
            for func in report["functions"]:
                offsets = sorted([c["offset"] for c in func["fusion_candidates"]])
                for i in range(1, len(offsets)):
                    assert offsets[i] > offsets[i - 1], (
                        f"Overlapping fusion candidates at offsets {offsets[i-1]} and {offsets[i]} "
                        f"in {func['export_name']}"
                    )
