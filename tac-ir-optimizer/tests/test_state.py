"""Tests for TAC IR optimizer pipeline: optimizer correctness and Makefile orchestration."""

import json
import os
import re
import subprocess
import tempfile

import pytest

PROGRAMS_DIR = "/app/programs"
INTERPRETER = "/app/interpreter.py"
OPTIMIZER = "/app/optimizer.py"
VALIDATOR = "/app/tac_check.py"

# Expected return values and maximum instruction counts for the target function
# after optimization. Thresholds require multiple interacting optimization
# techniques to be working correctly.
EXPECTED = {
    "pure_fold": {"ret": 361, "max_instr": 2},
    "propagate_fold": {"ret": 20, "max_instr": 2},
    "dead_stores": {"ret": 57, "max_instr": 2},
    "unreachable": {"ret": 15, "max_instr": 5},
    "loop_optimization": {"ret": 45, "max_instr": 9},
    "cascading": {"ret": 10, "max_instr": 2},
    "diamond_cfg": {"ret": 9, "max_instr": 5},
    "copy_chain": {"ret": 42, "max_instr": 2},
    "recursive_call": {"ret": 720, "max_instr": 4},
    "overflow": {"ret": 1, "max_instr": 2},
}


def _run(cmd, **kwargs):
    """Run a command and return CompletedProcess."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, **kwargs)


def _count_target_instructions(tac_text):
    """Count instructions in the 'target' function of TAC text.

    Instructions are lines inside function target() that are not comments,
    blank lines, function headers, or labels.
    """
    lines = tac_text.strip().split("\n")
    in_target = False
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Detect function header
        func_match = re.match(r"function\s+(\w+)\s*\(", stripped)
        if func_match:
            in_target = func_match.group(1) == "target"
            continue
        if not in_target:
            continue
        # Skip labels
        if re.match(r"^\w+\s*:\s*$", stripped):
            continue
        # Everything else is an instruction
        count += 1
    return count


# =========================================================================
# Direct optimizer tests (no Makefile required)
# =========================================================================

def test_optimizer_exists():
    """The optimizer script must exist at /app/optimizer.py."""
    assert os.path.exists(OPTIMIZER), (
        f"Optimizer not found at {OPTIMIZER}. "
        "Create /app/optimizer.py that reads a .tac file and writes optimized TAC to stdout."
    )


@pytest.mark.parametrize("prog", sorted(EXPECTED.keys()))
def test_interpreter_baseline(prog):
    """Sanity check: interpreter produces expected return value on original program."""
    info = EXPECTED[prog]
    path = os.path.join(PROGRAMS_DIR, f"{prog}.tac")
    r = _run(["python3", INTERPRETER, path, "target"])
    assert r.returncode == 0, f"Interpreter failed on {prog}: {r.stderr}"
    assert int(r.stdout.strip()) == info["ret"], (
        f"Interpreter returned {r.stdout.strip()} for {prog}, expected {info['ret']}"
    )


@pytest.mark.parametrize("prog", sorted(EXPECTED.keys()))
def test_original_validity(prog):
    """Original programs must pass structural validation."""
    path = os.path.join(PROGRAMS_DIR, f"{prog}.tac")
    r = _run(["python3", VALIDATOR, path])
    assert r.returncode == 0, (
        f"Original {prog} failed structural validation: {r.stderr}"
    )


@pytest.mark.parametrize("prog", sorted(EXPECTED.keys()))
def test_optimizer_validity(prog):
    """Optimized program must pass structural validation."""
    path = os.path.join(PROGRAMS_DIR, f"{prog}.tac")

    r = _run(["python3", OPTIMIZER, path])
    assert r.returncode == 0, f"Optimizer crashed on {prog}: {r.stderr}"
    optimized_tac = r.stdout
    assert optimized_tac.strip(), f"Optimizer produced empty output for {prog}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".tac", delete=False) as f:
        f.write(optimized_tac)
        opt_path = f.name
    try:
        r2 = _run(["python3", VALIDATOR, opt_path])
        assert r2.returncode == 0, (
            f"Optimized {prog} failed structural validation: {r2.stderr}\n"
            f"Optimized TAC:\n{optimized_tac}"
        )
    finally:
        os.unlink(opt_path)


@pytest.mark.parametrize("prog", sorted(EXPECTED.keys()))
def test_optimizer_correctness(prog):
    """Optimized program must produce the same return value as the original."""
    info = EXPECTED[prog]
    path = os.path.join(PROGRAMS_DIR, f"{prog}.tac")

    # Run optimizer
    r = _run(["python3", OPTIMIZER, path])
    assert r.returncode == 0, f"Optimizer crashed on {prog}: {r.stderr}"
    optimized_tac = r.stdout
    assert optimized_tac.strip(), f"Optimizer produced empty output for {prog}"

    # Write optimized to temp file and interpret
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tac", delete=False) as f:
        f.write(optimized_tac)
        opt_path = f.name
    try:
        r2 = _run(["python3", INTERPRETER, opt_path, "target"])
        assert r2.returncode == 0, (
            f"Interpreter failed on optimized {prog}: {r2.stderr}\n"
            f"Optimized TAC:\n{optimized_tac}"
        )
        actual = int(r2.stdout.strip())
        assert actual == info["ret"], (
            f"Optimized {prog} returned {actual}, expected {info['ret']}.\n"
            f"Optimized TAC:\n{optimized_tac}"
        )
    finally:
        os.unlink(opt_path)


@pytest.mark.parametrize("prog", sorted(EXPECTED.keys()))
def test_optimization_quality(prog):
    """Optimized target function must have instruction count within threshold."""
    info = EXPECTED[prog]
    path = os.path.join(PROGRAMS_DIR, f"{prog}.tac")

    r = _run(["python3", OPTIMIZER, path])
    assert r.returncode == 0, f"Optimizer crashed on {prog}: {r.stderr}"
    optimized_tac = r.stdout

    instr_count = _count_target_instructions(optimized_tac)
    assert instr_count <= info["max_instr"], (
        f"Optimized {prog} has {instr_count} instructions in target(), "
        f"expected at most {info['max_instr']}.\n"
        f"Optimized TAC:\n{optimized_tac}"
    )
    # Also verify the optimizer actually outputs something parseable
    assert instr_count >= 1, (
        f"Optimized {prog} has 0 instructions in target() - "
        f"every function must have at least a return.\n"
        f"Optimized TAC:\n{optimized_tac}"
    )


# =========================================================================
# Makefile pipeline tests
# =========================================================================

class TestMakefilePipeline:
    """Tests for the Makefile-orchestrated optimization pipeline."""

    @classmethod
    def setup_class(cls):
        """Run make all to produce output files and report."""
        r = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, (
            f"make all failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )
        with open("/app/output/report.json") as f:
            cls.report = json.load(f)

    def test_makefile_exists(self):
        """Makefile must exist at /app/Makefile."""
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    @pytest.mark.parametrize("prog", sorted(EXPECTED.keys()))
    def test_output_file_exists(self, prog):
        """Optimized output file must exist for each program."""
        path = f"/app/output/{prog}.tac"
        assert os.path.exists(path), f"Expected output file {path} not found"

    def test_report_is_valid_json_array(self):
        """report.json must be a JSON array with 10 entries."""
        assert isinstance(self.report, list), "report.json must be a JSON array"
        assert len(self.report) == len(EXPECTED), (
            f"report.json has {len(self.report)} entries, expected {len(EXPECTED)}"
        )

    def test_report_covers_all_programs(self):
        """report.json must have an entry for every program."""
        programs_in_report = {e["program"] for e in self.report}
        expected_programs = set(EXPECTED.keys())
        assert programs_in_report == expected_programs, (
            f"Missing programs in report: {expected_programs - programs_in_report}"
        )

    @pytest.mark.parametrize("prog", sorted(EXPECTED.keys()))
    def test_report_entry_schema(self, prog):
        """Each report entry must have the required fields with correct types."""
        entries = {e["program"]: e for e in self.report}
        assert prog in entries, f"Program {prog} missing from report"
        e = entries[prog]
        assert isinstance(e.get("original_ret"), int), (
            f"original_ret must be an integer, got {type(e.get('original_ret'))}"
        )
        assert isinstance(e.get("optimized_ret"), int), (
            f"optimized_ret must be an integer, got {type(e.get('optimized_ret'))}"
        )
        assert isinstance(e.get("match"), bool), (
            f"match must be a boolean, got {type(e.get('match'))}"
        )
        assert isinstance(e.get("instruction_count"), int), (
            f"instruction_count must be an integer, got {type(e.get('instruction_count'))}"
        )
        assert isinstance(e.get("valid"), bool), (
            f"valid must be a boolean, got {type(e.get('valid'))}"
        )

    @pytest.mark.parametrize("prog", sorted(EXPECTED.keys()))
    def test_report_data_correct(self, prog):
        """Report data must match expected values and reflect correct optimization."""
        entries = {e["program"]: e for e in self.report}
        e = entries[prog]
        info = EXPECTED[prog]
        assert e["original_ret"] == info["ret"], (
            f"Report original_ret for {prog}: {e['original_ret']}, expected {info['ret']}"
        )
        assert e["optimized_ret"] == info["ret"], (
            f"Report optimized_ret for {prog}: {e['optimized_ret']}, expected {info['ret']}"
        )
        assert e["match"] is True, f"Report match for {prog} is False"
        assert e["valid"] is True, f"Report valid for {prog} is False"
        assert e["instruction_count"] >= 1, (
            f"Report instruction_count for {prog} is {e['instruction_count']}, must be >= 1"
        )
        assert e["instruction_count"] <= info["max_instr"], (
            f"Report instruction_count for {prog}: {e['instruction_count']}, "
            f"max allowed: {info['max_instr']}"
        )

    def test_makefile_incremental_build(self):
        """File targets must be up to date after make all (proper dependencies)."""
        r = subprocess.run(
            ["make", "-C", "/app", "-q", "output/pure_fold.tac"],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, (
            "Makefile must track file dependencies for incremental builds. "
            "output/pure_fold.tac should be up to date after make all."
        )
