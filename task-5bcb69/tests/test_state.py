
import subprocess
import os


def test_cbrtf_source_exists():
    """cbrtf.c must exist in /app/."""
    assert os.path.exists("/app/cbrtf.c"), "/app/cbrtf.c not found"


def test_cbrtf_builds():
    """cbrtf.c must compile with the exhaustive verifier."""
    result = subprocess.run(
        ["gcc", "-O2", "-std=c11", "-I/app", "-o", "/app/verify_exhaustive",
         "/tests/verify.c", "/app/cbrtf.c",
         "-lmpfr", "-lgmp", "-lm"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_cbrtf_correctness():
    """cr_cbrtf must produce correctly-rounded results for all test inputs."""
    result = subprocess.run(
        ["/app/verify_exhaustive"],
        capture_output=True, text=True,
        timeout=250,
    )
    stdout = result.stdout
    print(stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    assert result.returncode == 0, (
        f"Verification exited with code {result.returncode}:\n{stdout}"
    )
    assert "ALL TESTS PASSED" in stdout, (
        f"Verification did not pass all tests:\n{stdout}"
    )
