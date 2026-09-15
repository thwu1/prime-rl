
import subprocess
import re


def run_effects():
    """Run the effects program and return stdout."""
    result = subprocess.run(
        ["chezscheme", "--libdirs", "/app/lib", "--program", "/app/effects.scm"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout, result.stderr, result.returncode


def test_program_runs_successfully():
    """The effects program must execute without crashing."""
    stdout, stderr, rc = run_effects()
    assert rc == 0, f"Program exited with code {rc}.\nstderr: {stderr}\nstdout: {stdout}"


def test_total_line_present():
    """Output must contain a TOTAL summary line."""
    stdout, _, _ = run_effects()
    assert "TOTAL:" in stdout, f"No TOTAL line found in output:\n{stdout}"


def test_zero_failures():
    """The TOTAL line must report 23 tests and 0 failures."""
    stdout, _, _ = run_effects()
    match = re.search(r"TOTAL:\s*(\d+)\s*tests?,\s*(\d+)\s*failures?", stdout)
    assert match, f"Could not parse TOTAL line from output:\n{stdout}"
    total_tests = int(match.group(1))
    total_failures = int(match.group(2))
    assert total_tests == 23, f"Expected 23 tests, found {total_tests}"
    assert total_failures == 0, f"Expected 0 failures, found {total_failures}"


def test_all_tests_pass():
    """Every TEST line must show PASS."""
    stdout, _, _ = run_effects()
    test_lines = [line for line in stdout.split("\n") if line.startswith("TEST ")]
    assert len(test_lines) == 23, (
        f"Expected 23 TEST lines, found {len(test_lines)}:\n"
        + "\n".join(test_lines)
    )
    for line in test_lines:
        assert ": PASS" in line, f"Test did not pass: {line}"


def test_shift_reset_basic():
    """Verify shift-reset-basic test passes."""
    stdout, _, _ = run_effects()
    assert "TEST shift-reset-basic: PASS" in stdout


def test_shift_reset_apply():
    """Verify repeated continuation application works."""
    stdout, _, _ = run_effects()
    assert "TEST shift-reset-apply1: PASS" in stdout
    assert "TEST shift-reset-apply2: PASS" in stdout


def test_shift_nested():
    """Verify nested shifts work correctly."""
    stdout, _, _ = run_effects()
    assert "TEST shift-nested: PASS" in stdout


def test_shift_at():
    """Verify tagged shift-at/reset-at work."""
    stdout, _, _ = run_effects()
    assert "TEST shift-at-basic: PASS" in stdout
    assert "TEST shift-at-apply: PASS" in stdout


def test_state():
    """Verify run-with-state works for basic, nested, and accumulated cases."""
    stdout, _, _ = run_effects()
    assert "TEST state-basic-get: PASS" in stdout
    assert "TEST state-nested: PASS" in stdout
    assert "TEST state-accumulate: PASS" in stdout


def test_state_amb_scoping():
    """Verify state is properly scoped across nondeterministic branches."""
    stdout, _, _ = run_effects()
    assert "TEST state-amb-scoping: PASS" in stdout


def test_amb():
    """Verify nondeterministic choice works."""
    stdout, _, _ = run_effects()
    assert "TEST amb-basic: PASS" in stdout
    assert "TEST amb-filter: PASS" in stdout
    assert "TEST amb-cartesian: PASS" in stdout
    assert "TEST amb-empty: PASS" in stdout
    assert "TEST amb-pythagorean: PASS" in stdout


def test_streams():
    """Verify for-each->stream produces correct lazy streams."""
    stdout, _, _ = run_effects()
    assert "TEST foreach-stream: PASS" in stdout
    assert "TEST foreach-stream-partial: PASS" in stdout


def test_dynamic_wind_backtracking():
    """Verify dynamic-wind fires correctly during amb backtracking."""
    stdout, _, _ = run_effects()
    assert "TEST wind-backtrack: PASS" in stdout


def test_handler_return():
    """Verify handler return transformation works when no effects occur."""
    stdout, _, _ = run_effects()
    assert "TEST handler-return: PASS" in stdout


def test_handler_effect():
    """Verify handler processes effects and resumes computation."""
    stdout, _, _ = run_effects()
    assert "TEST handler-effect: PASS" in stdout


def test_handler_multi():
    """Verify handler handles multiple effects in sequence."""
    stdout, _, _ = run_effects()
    assert "TEST handler-multi: PASS" in stdout


def test_handler_abort():
    """Verify handler can abort computation by not resuming."""
    stdout, _, _ = run_effects()
    assert "TEST handler-abort: PASS" in stdout
