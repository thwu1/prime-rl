#!/usr/bin/env python3
"""
Tests for the register allocation verification checker.

Validates that the checker correctly identifies valid and invalid
register allocations and produces valid Graphviz DOT output.
"""

import json
import subprocess
import os
import pytest

CHECKER = "/app/regalloc_checker.py"
OUTPUT_DIR = "/app/output"


def run_checker(program_name):
    """Run the checker on a program and return parsed output + exit code."""
    result = subprocess.run(
        ["python3", CHECKER, program_name],
        capture_output=True, text=True, timeout=30,
        cwd="/app"
    )
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"Checker output is not valid JSON for {program_name}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
    return output, result.returncode


def dot_file_path(program_name):
    return os.path.join(OUTPUT_DIR, f"{program_name}.dot")


def validate_dot(program_name):
    """Verify the DOT file exists and is valid graphviz input."""
    path = dot_file_path(program_name)
    assert os.path.isfile(path), f"DOT file not found: {path}"
    result = subprocess.run(
        ["dot", "-Tcanon", path],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, (
        f"DOT file is not valid graphviz for {program_name}.\n"
        f"stderr: {result.stderr!r}"
    )
    return open(path).read()


# ─── Correct allocation tests ───────────────────────────────────────

class TestCorrectAllocations:
    """Programs with correct register allocations must validate."""

    def test_straight_line_correct(self):
        output, rc = run_checker("straight_line_correct")
        assert output["valid"] is True, f"Expected valid: {output['errors']}"
        assert rc == 0
        assert output["errors"] == []

    def test_branch_join_correct(self):
        output, rc = run_checker("branch_join_correct")
        assert output["valid"] is True, f"Expected valid: {output['errors']}"
        assert rc == 0

    def test_loop_correct(self):
        output, rc = run_checker("loop_correct")
        assert output["valid"] is True, f"Expected valid: {output['errors']}"
        assert rc == 0

    def test_spill_reload_correct(self):
        output, rc = run_checker("spill_reload_correct")
        assert output["valid"] is True, f"Expected valid: {output['errors']}"
        assert rc == 0

    def test_move_chain_correct(self):
        output, rc = run_checker("move_chain_correct")
        assert output["valid"] is True, f"Expected valid: {output['errors']}"
        assert rc == 0

    def test_complex_cfg_correct(self):
        output, rc = run_checker("complex_cfg_correct")
        assert output["valid"] is True, f"Expected valid: {output['errors']}"
        assert rc == 0


# ─── Incorrect allocation tests ─────────────────────────────────────

class TestIncorrectAllocations:
    """Programs with incorrect register allocations must be flagged."""

    def test_straight_line_wrong(self):
        output, rc = run_checker("straight_line_wrong")
        assert output["valid"] is False
        assert rc == 1
        assert len(output["errors"]) > 0

    def test_straight_line_wrong_error_details(self):
        output, _ = run_checker("straight_line_wrong")
        errors = output["errors"]
        entry_errors = [e for e in errors if e["block"] == "entry"]
        assert len(entry_errors) > 0
        inst2_errors = [e for e in entry_errors if e["instruction"] == 2]
        assert len(inst2_errors) > 0
        for err in inst2_errors:
            assert "preg" in err
            assert "expected_vreg" in err
            assert "actual" in err

    def test_branch_join_conflict(self):
        output, rc = run_checker("branch_join_conflict")
        assert output["valid"] is False
        assert rc == 1
        assert len(output["errors"]) > 0

    def test_branch_join_conflict_error_details(self):
        output, _ = run_checker("branch_join_conflict")
        errors = output["errors"]
        join_errors = [e for e in errors if e["block"] == "join"]
        assert len(join_errors) > 0
        r0_errors = [e for e in join_errors if e.get("preg") == "r0"]
        assert len(r0_errors) > 0
        assert any(e["actual"] == "conflicted" for e in r0_errors)

    def test_wrong_reload(self):
        output, rc = run_checker("wrong_reload")
        assert output["valid"] is False
        assert rc == 1
        assert len(output["errors"]) > 0

    def test_wrong_reload_error_details(self):
        output, _ = run_checker("wrong_reload")
        errors = output["errors"]
        assert any(e.get("actual") == "unknown" for e in errors)

    def test_bad_terminator_arg(self):
        output, rc = run_checker("bad_terminator_arg")
        assert output["valid"] is False
        assert rc == 1
        assert len(output["errors"]) > 0

    def test_bad_terminator_arg_error_details(self):
        output, _ = run_checker("bad_terminator_arg")
        errors = output["errors"]
        term_errors = [e for e in errors if e.get("instruction") == "terminator"]
        assert len(term_errors) > 0
        entry_term_errors = [e for e in term_errors if e["block"] == "entry"]
        assert len(entry_term_errors) > 0


# ─── DOT output tests ──────────────────────────────────────────────

class TestDotOutput:
    """Verify DOT graph files are produced and valid."""

    def test_dot_valid_correct_program(self):
        """Correct program should produce valid DOT with block nodes."""
        run_checker("branch_join_correct")
        content = validate_dot("branch_join_correct")
        assert "entry" in content
        assert "join" in content

    def test_dot_valid_incorrect_program(self):
        """Incorrect program should produce valid DOT with error highlighting."""
        run_checker("branch_join_conflict")
        content = validate_dot("branch_join_conflict")
        assert "join" in content
        assert "red" in content.lower(), "Error blocks must be highlighted in red"

    def test_dot_valid_loop(self):
        """Loop program should produce valid DOT with back edges."""
        run_checker("loop_correct")
        content = validate_dot("loop_correct")
        assert "loop_header" in content or "header" in content

    def test_dot_valid_straight_line_wrong(self):
        """Straight-line wrong should have red error block."""
        run_checker("straight_line_wrong")
        content = validate_dot("straight_line_wrong")
        assert "entry" in content
        assert "red" in content.lower()

    def test_dot_edges_present(self):
        """DOT for branch program must have edges."""
        run_checker("branch_join_correct")
        content = validate_dot("branch_join_correct")
        assert "->" in content, "DOT file must contain edges"

    def test_dot_renders_svg(self):
        """DOT file must successfully render to SVG via dot command."""
        run_checker("complex_cfg_correct")
        path = dot_file_path("complex_cfg_correct")
        assert os.path.isfile(path)
        result = subprocess.run(
            ["dot", "-Tsvg", path],
            capture_output=True, timeout=10
        )
        assert result.returncode == 0, f"dot -Tsvg failed: {result.stderr}"


# ─── Output format tests ────────────────────────────────────────────

class TestOutputFormat:
    """Verify the output JSON matches the specification."""

    def test_valid_output_has_required_fields(self):
        output, _ = run_checker("straight_line_correct")
        assert "valid" in output
        assert "errors" in output
        assert isinstance(output["valid"], bool)
        assert isinstance(output["errors"], list)

    def test_error_output_has_required_fields(self):
        output, _ = run_checker("straight_line_wrong")
        assert "valid" in output
        assert "errors" in output
        assert isinstance(output["valid"], bool)
        assert isinstance(output["errors"], list)
        for error in output["errors"]:
            assert "block" in error
            assert "instruction" in error
            assert "preg" in error
            assert "expected_vreg" in error
            assert "actual" in error

    def test_exit_code_valid(self):
        _, rc = run_checker("straight_line_correct")
        assert rc == 0

    def test_exit_code_invalid(self):
        _, rc = run_checker("straight_line_wrong")
        assert rc == 1


# ─── Database interaction tests ─────────────────────────────────────

class TestDatabaseInteraction:
    """Verify the checker reads from the SQLite database."""

    def test_database_exists(self):
        assert os.path.isfile("/app/programs.db"), "programs.db must exist"

    def test_checker_handles_all_programs(self):
        """Checker must handle every program in the database."""
        import sqlite3
        conn = sqlite3.connect("/app/programs.db")
        names = [r[0] for r in conn.execute("SELECT name FROM programs").fetchall()]
        conn.close()
        for name in names:
            output, rc = run_checker(name)
            assert "valid" in output, f"Missing 'valid' field for {name}"
            assert isinstance(output["valid"], bool), f"'valid' not bool for {name}"
            dot_path = dot_file_path(name)
            assert os.path.isfile(dot_path), f"Missing DOT file for {name}"
