
"""Tests for the IR optimizer and build pipeline.

Verifies that:
  1. Optimized programs produce identical output to the originals.
  2. Each program's instruction count is reduced by a minimum threshold.
  3. Specific optimization patterns are applied.
  4. The Makefile targets work correctly and produce valid outputs.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "/app")
sys.path.insert(0, "/opt/ir_task")
from ir_parser import parse_program
from ir_emitter import emit_program

PROGRAMS_DIR = "/app/programs"
OPTIMIZER = "/app/optimize.py"
INTERPRETER = "/app/interpreter.py"

PROGRAMS = ["prog1", "prog2", "prog3", "prog4", "prog5"]

EXPECTED_OUTPUTS = {
    "prog1": ["35", "30", "45"],
    "prog2": ["272"],
    "prog3": ["10", "20", "30"],
    "prog4": ["150", "20", "55"],
    "prog5": ["779"],
}

# Minimum fraction of instructions that must be eliminated
MIN_REDUCTIONS = {
    "prog1": 0.25,
    "prog2": 0.20,
    "prog3": 0.25,
    "prog4": 0.25,
    "prog5": 0.15,
}

ORIGINAL_COUNTS = {
    "prog1": 19,
    "prog2": 15,
    "prog3": 15,
    "prog4": 27,
    "prog5": 26,
}


def _run_interpreter(ir_path):
    """Run the interpreter on an IR file and return output lines."""
    result = subprocess.run(
        [sys.executable, INTERPRETER, ir_path],
        capture_output=True,
        text=True,
        timeout=30,
        cwd="/app",
    )
    if result.returncode != 0 and result.stderr:
        raise RuntimeError(
            f"Interpreter failed on {ir_path}: {result.stderr.strip()}"
        )
    return result.stdout.strip().splitlines() if result.stdout.strip() else []


def _run_optimizer(input_path, output_path):
    """Run the optimizer on an IR file."""
    result = subprocess.run(
        [sys.executable, OPTIMIZER, input_path, output_path],
        capture_output=True,
        text=True,
        timeout=60,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Optimizer failed on {input_path}: {result.stderr.strip()}"
    )


def _count_instructions(ir_path):
    """Parse an IR file and count total instructions."""
    with open(ir_path) as f:
        prog = parse_program(f.read())
    return sum(
        len(block.instructions)
        for func in prog.functions
        for block in func.blocks
    )


def _get_block_labels(ir_path):
    """Return set of block labels in an IR file."""
    with open(ir_path) as f:
        prog = parse_program(f.read())
    return {
        block.label
        for func in prog.functions
        for block in func.blocks
    }


def _get_dest_registers(ir_path):
    """Return set of all destination registers defined in the IR."""
    with open(ir_path) as f:
        prog = parse_program(f.read())
    return {
        instr.dest
        for func in prog.functions
        for block in func.blocks
        for instr in block.instructions
        if instr.dest is not None
    }


# ---------------------------------------------------------------------------
# Correctness tests: optimised output must match original
# ---------------------------------------------------------------------------

class TestSemanticCorrectness:
    """Optimised programs must produce identical output."""

    def _check(self, name):
        input_path = os.path.join(PROGRAMS_DIR, f"{name}.ir")
        with tempfile.NamedTemporaryFile(suffix=".ir", delete=False) as tmp:
            opt_path = tmp.name
        try:
            orig_out = _run_interpreter(input_path)
            assert orig_out == EXPECTED_OUTPUTS[name], (
                f"Interpreter baseline mismatch for {name}: {orig_out}"
            )
            _run_optimizer(input_path, opt_path)
            opt_out = _run_interpreter(opt_path)
            assert opt_out == orig_out, (
                f"Output mismatch for {name}:\n"
                f"  original:  {orig_out}\n"
                f"  optimised: {opt_out}"
            )
        finally:
            os.unlink(opt_path)

    def test_prog1(self):
        self._check("prog1")

    def test_prog2(self):
        self._check("prog2")

    def test_prog3(self):
        self._check("prog3")

    def test_prog4(self):
        self._check("prog4")

    def test_prog5(self):
        self._check("prog5")


# ---------------------------------------------------------------------------
# Instruction-count reduction tests
# ---------------------------------------------------------------------------

class TestInstructionReduction:
    """Optimised programs must have strictly fewer instructions."""

    def _check(self, name):
        input_path = os.path.join(PROGRAMS_DIR, f"{name}.ir")
        with tempfile.NamedTemporaryFile(suffix=".ir", delete=False) as tmp:
            opt_path = tmp.name
        try:
            _run_optimizer(input_path, opt_path)
            orig_count = ORIGINAL_COUNTS[name]
            opt_count = _count_instructions(opt_path)
            reduction = 1.0 - opt_count / orig_count
            min_red = MIN_REDUCTIONS[name]
            assert reduction >= min_red, (
                f"{name}: reduction {reduction:.1%} < required {min_red:.0%} "
                f"({orig_count} -> {opt_count} instructions)"
            )
        finally:
            os.unlink(opt_path)

    def test_prog1_reduction(self):
        self._check("prog1")

    def test_prog2_reduction(self):
        self._check("prog2")

    def test_prog3_reduction(self):
        self._check("prog3")

    def test_prog4_reduction(self):
        self._check("prog4")

    def test_prog5_reduction(self):
        self._check("prog5")


# ---------------------------------------------------------------------------
# Specific optimisation pattern tests
# ---------------------------------------------------------------------------

class TestSpecificOptimisations:
    """Verify that particular optimisations are applied."""

    def test_unreachable_block_removed(self):
        """prog1: the '.then' block is unreachable and should be eliminated."""
        input_path = os.path.join(PROGRAMS_DIR, "prog1.ir")
        with tempfile.NamedTemporaryFile(suffix=".ir", delete=False) as tmp:
            opt_path = tmp.name
        try:
            _run_optimizer(input_path, opt_path)
            labels = _get_block_labels(opt_path)
            assert "then" not in labels, (
                "Unreachable block '.then' was not removed from prog1"
            )
        finally:
            os.unlink(opt_path)

    def test_dead_registers_removed(self):
        """prog3: dead registers d, e, f, h, i, j should be eliminated."""
        input_path = os.path.join(PROGRAMS_DIR, "prog3.ir")
        with tempfile.NamedTemporaryFile(suffix=".ir", delete=False) as tmp:
            opt_path = tmp.name
        try:
            _run_optimizer(input_path, opt_path)
            dests = _get_dest_registers(opt_path)
            dead = {"d", "e", "f", "h", "i", "j"}
            remaining_dead = dead & dests
            assert len(remaining_dead) <= 1, (
                f"Dead registers still present in prog3: {remaining_dead}"
            )
        finally:
            os.unlink(opt_path)

    def test_cse_eliminates_duplicates(self):
        """prog2: repeated add/mul a b should be eliminated."""
        input_path = os.path.join(PROGRAMS_DIR, "prog2.ir")
        with tempfile.NamedTemporaryFile(suffix=".ir", delete=False) as tmp:
            opt_path = tmp.name
        try:
            _run_optimizer(input_path, opt_path)
            # After deduplication, registers e, f, g, h (duplicates of c, d) should be gone
            dests = _get_dest_registers(opt_path)
            dup_regs = {"e", "f", "g", "h"}
            remaining = dup_regs & dests
            assert len(remaining) <= 1, (
                f"Duplicate registers still present in prog2: {remaining}"
            )
        finally:
            os.unlink(opt_path)

    def test_combined_unreachable_in_prog4(self):
        """prog4: .path_b is unreachable and should be removed."""
        input_path = os.path.join(PROGRAMS_DIR, "prog4.ir")
        with tempfile.NamedTemporaryFile(suffix=".ir", delete=False) as tmp:
            opt_path = tmp.name
        try:
            _run_optimizer(input_path, opt_path)
            labels = _get_block_labels(opt_path)
            assert "path_b" not in labels, (
                "Unreachable block '.path_b' was not removed from prog4"
            )
        finally:
            os.unlink(opt_path)

    def test_loop_redundant_computation_in_prog5(self):
        """prog5: duplicate mul i i in loop body should be deduplicated."""
        input_path = os.path.join(PROGRAMS_DIR, "prog5.ir")
        with tempfile.NamedTemporaryFile(suffix=".ir", delete=False) as tmp:
            opt_path = tmp.name
        try:
            _run_optimizer(input_path, opt_path)
            with open(opt_path) as f:
                prog = parse_program(f.read())
            # Count 'mul i i' instructions in the body block
            mul_ii_count = 0
            for func in prog.functions:
                for block in func.blocks:
                    if block.label == "body":
                        for instr in block.instructions:
                            if (instr.op == "mul" and
                                    len(instr.args) == 2 and
                                    instr.args[0] == "i" and
                                    instr.args[1] == "i"):
                                mul_ii_count += 1
            assert mul_ii_count <= 1, (
                f"Expected at most 1 'mul i i' in loop body after optimization, "
                f"found {mul_ii_count}"
            )
        finally:
            os.unlink(opt_path)


# ---------------------------------------------------------------------------
# Build pipeline tests: Makefile targets and optimization report
# ---------------------------------------------------------------------------

class TestBuildPipeline:
    """Verify Makefile targets and optimization report."""

    def test_makefile_exists(self):
        """Makefile must exist at /app/Makefile."""
        assert os.path.isfile("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_makefile_uses_required_tools(self):
        """Makefile must reference diff for verify and jq for report."""
        with open("/app/Makefile") as f:
            content = f.read()
        assert "diff" in content, "Makefile must use diff for output comparison"
        assert "jq" in content, "Makefile must use jq for JSON assembly"

    def test_optimize_all_target(self):
        """make optimize-all must produce .opt.ir files for all programs."""
        # Clean any previous .opt.ir files
        for prog in PROGRAMS:
            opt_path = os.path.join(PROGRAMS_DIR, f"{prog}.opt.ir")
            if os.path.exists(opt_path):
                os.unlink(opt_path)
        result = subprocess.run(
            ["make", "-C", "/app", "optimize-all"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            f"make optimize-all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        for prog in PROGRAMS:
            opt_path = os.path.join(PROGRAMS_DIR, f"{prog}.opt.ir")
            assert os.path.isfile(opt_path), f"Missing optimized file: {opt_path}"

    def test_verify_target(self):
        """make verify must exit 0 (optimized output matches original)."""
        subprocess.run(
            ["make", "-C", "/app", "optimize-all"],
            capture_output=True, text=True, timeout=120,
        )
        result = subprocess.run(
            ["make", "-C", "/app", "verify"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            f"make verify failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_report_valid_json(self):
        """make report must produce valid JSON with correct schema."""
        subprocess.run(
            ["make", "-C", "/app", "optimize-all"],
            capture_output=True, text=True, timeout=120,
        )
        result = subprocess.run(
            ["make", "-C", "/app", "report"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            f"make report failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        report_path = "/app/optimization_report.json"
        assert os.path.isfile(report_path), f"Report not found at {report_path}"

        with open(report_path) as f:
            report = json.load(f)

        for prog in PROGRAMS:
            assert prog in report, f"Missing program '{prog}' in report"
            entry = report[prog]
            for field in ("original_count", "optimized_count", "reduction_pct"):
                assert field in entry, f"Missing field '{field}' for {prog}"
            assert isinstance(entry["original_count"], int), (
                f"original_count must be int for {prog}"
            )
            assert isinstance(entry["optimized_count"], int), (
                f"optimized_count must be int for {prog}"
            )
            assert isinstance(entry["reduction_pct"], (int, float)), (
                f"reduction_pct must be numeric for {prog}"
            )
            assert entry["optimized_count"] < entry["original_count"], (
                f"No reduction reported for {prog}"
            )

    def test_report_accuracy(self):
        """Report counts must match actual instruction totals from IR files."""
        subprocess.run(
            ["make", "-C", "/app", "optimize-all"],
            capture_output=True, text=True, timeout=120,
        )
        subprocess.run(
            ["make", "-C", "/app", "report"],
            capture_output=True, text=True, timeout=120,
        )
        report_path = "/app/optimization_report.json"
        with open(report_path) as f:
            report = json.load(f)

        for prog in PROGRAMS:
            orig_path = os.path.join(PROGRAMS_DIR, f"{prog}.ir")
            opt_path = os.path.join(PROGRAMS_DIR, f"{prog}.opt.ir")
            actual_orig = _count_instructions(orig_path)
            actual_opt = _count_instructions(opt_path)
            entry = report[prog]
            assert entry["original_count"] == actual_orig, (
                f"{prog}: report original_count {entry['original_count']} "
                f"!= actual {actual_orig}"
            )
            assert entry["optimized_count"] == actual_opt, (
                f"{prog}: report optimized_count {entry['optimized_count']} "
                f"!= actual {actual_opt}"
            )
