import subprocess
import re



def test_maven_compilation_succeeds():
    """Verify the project compiles without errors."""
    result = subprocess.run(
        ["mvn", "compile", "-q"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=300,
    )
    assert result.returncode == 0, (
        f"Compilation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_all_junit_tests_pass():
    """Run mvn test and verify all 25 JUnit tests pass."""
    result = subprocess.run(
        ["mvn", "test"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=300,
    )
    output = result.stdout + "\n" + result.stderr

    assert result.returncode == 0, f"Maven tests failed:\n{output}"

    # Verify a reasonable number of tests actually ran
    match = re.search(r"Tests run:\s*(\d+)", output)
    assert match, f"Could not find test count in Maven output:\n{output}"
    tests_run = int(match.group(1))
    assert tests_run >= 20, (
        f"Expected at least 20 tests to run but only {tests_run} detected"
    )

    # Verify zero failures and zero errors
    failures_match = re.search(r"Failures:\s*(\d+)", output)
    errors_match = re.search(r"Errors:\s*(\d+)", output)
    if failures_match:
        assert int(failures_match.group(1)) == 0, f"Some tests had failures:\n{output}"
    if errors_match:
        assert int(errors_match.group(1)) == 0, f"Some tests had errors:\n{output}"
