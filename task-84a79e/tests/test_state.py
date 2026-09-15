"""
Tests for the Three-Address Code IR Optimizer.

"""

import subprocess
import os
import pytest

PROGRAMS = ["prog1", "prog2", "prog3", "prog4", "prog5"]

# Maximum allowed instruction count after optimization for each program.
# These thresholds require correct data-flow analysis — pattern matching or
# local-only optimizations are not sufficient for all programs.
MAX_INSTRUCTIONS = {
    "prog1": 5,   # straight-line constant propagation => nearly everything folds
    "prog2": 7,   # dead code elimination removes 3 dead variables
    "prog3": 11,  # CSE across blocks eliminates 2 redundant a+b computations
    "prog4": 18,  # constant propagation + DCE across loop with branches
    "prog5": 22,  # combined: const prop + CSE + DCE across multiple functions
}

ORIGINAL_COUNTS = {
    "prog1": 12,
    "prog2": 10,
    "prog3": 13,
    "prog4": 21,
    "prog5": 27,
}


def count_instructions(ir_text):
    """Count executable instructions in IR text (excludes labels, comments, FUNC/ENDFUNC, blanks)."""
    count = 0
    for line in ir_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("FUNC ") or line == "ENDFUNC":
            continue
        if line.startswith("LABEL "):
            continue
        count += 1
    return count


def run_interpreter(ir_file):
    """Run the reference interpreter on an IR file and return stdout."""
    result = subprocess.run(
        ["python3", "/app/interpreter.py", ir_file],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Interpreter failed on {ir_file}: {result.stderr}"
    return result.stdout


def run_optimizer(ir_file, output_file):
    """Run the optimizer on an IR file, write result to output_file, return the optimized IR text."""
    result = subprocess.run(
        ["python3", "/app/optimizer.py", ir_file],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Optimizer failed on {ir_file}: {result.stderr}"
    with open(output_file, "w") as f:
        f.write(result.stdout)
    return result.stdout


# ---------------------------------------------------------------------------
# 1. Optimizer must exist
# ---------------------------------------------------------------------------
class TestOptimizerExists:
    def test_optimizer_file_exists(self):
        assert os.path.exists("/app/optimizer.py"), "/app/optimizer.py not found"


# ---------------------------------------------------------------------------
# 2. Semantic equivalence: optimized programs must produce same output
# ---------------------------------------------------------------------------
class TestSemanticEquivalence:
    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_output_matches(self, prog, tmp_path):
        ir_file = f"/app/programs/{prog}.ir"
        opt_file = str(tmp_path / f"{prog}_opt.ir")
        expected_file = f"/app/expected_outputs/{prog}.out"

        with open(expected_file) as f:
            expected = f.read().strip()

        run_optimizer(ir_file, opt_file)
        actual = run_interpreter(opt_file).strip()

        assert actual == expected, (
            f"Semantic mismatch for {prog}:\n"
            f"  expected: {expected!r}\n"
            f"  got:      {actual!r}"
        )


# ---------------------------------------------------------------------------
# 3. Optimization must reduce instruction count below threshold
# ---------------------------------------------------------------------------
class TestInstructionReduction:
    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_meets_threshold(self, prog, tmp_path):
        ir_file = f"/app/programs/{prog}.ir"
        opt_file = str(tmp_path / f"{prog}_opt.ir")

        opt_ir = run_optimizer(ir_file, opt_file)
        opt_count = count_instructions(opt_ir)
        max_count = MAX_INSTRUCTIONS[prog]

        assert opt_count <= max_count, (
            f"{prog}: optimized has {opt_count} instructions, "
            f"max allowed is {max_count} (original: {ORIGINAL_COUNTS[prog]})"
        )

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_strictly_fewer(self, prog, tmp_path):
        ir_file = f"/app/programs/{prog}.ir"
        opt_file = str(tmp_path / f"{prog}_opt.ir")

        with open(ir_file) as f:
            orig_count = count_instructions(f.read())

        opt_ir = run_optimizer(ir_file, opt_file)
        opt_count = count_instructions(opt_ir)

        assert opt_count < orig_count, (
            f"{prog}: optimizer did not reduce instructions "
            f"(original={orig_count}, optimized={opt_count})"
        )


# ---------------------------------------------------------------------------
# 4. Structural validity of optimized IR
# ---------------------------------------------------------------------------
class TestStructuralValidity:
    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_valid_structure(self, prog, tmp_path):
        ir_file = f"/app/programs/{prog}.ir"
        opt_file = str(tmp_path / f"{prog}_opt.ir")

        opt_ir = run_optimizer(ir_file, opt_file)

        assert "FUNC main" in opt_ir, f"Optimized {prog} is missing main function"
        assert "ENDFUNC" in opt_ir, f"Optimized {prog} is missing ENDFUNC"
        assert "RETURN" in opt_ir, f"Optimized {prog} is missing RETURN statement"
