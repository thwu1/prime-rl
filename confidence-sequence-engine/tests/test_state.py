import subprocess
import os
import shutil
import pytest



def test_build_succeeds():
    """The project must build without errors."""
    build_dir = "/app/build"
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)

    result = subprocess.run(
        ["cmake", ".."],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"CMake failed:\n{result.stderr}"

    result = subprocess.run(
        ["make", "-j2"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"


def test_all_boundaries_pass():
    """All boundary function tests must pass with tolerance 1e-5."""
    build_dir = "/app/build"
    if not os.path.exists(os.path.join(build_dir, "test_runner")):
        # Build first if not already built
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir)
        os.makedirs(build_dir)
        subprocess.run(["cmake", ".."], cwd=build_dir, capture_output=True,
                        timeout=120, check=True)
        subprocess.run(["make", "-j2"], cwd=build_dir, capture_output=True,
                        timeout=120, check=True)

    result = subprocess.run(
        ["./test_runner"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Test runner failed (exit code {result.returncode}):\n{result.stdout}"
    )
    assert "ALL TESTS PASSED" in result.stdout, (
        f"Not all tests passed:\n{result.stdout}"
    )


def test_no_errors_in_output():
    """No test should throw an exception (ERROR)."""
    build_dir = "/app/build"
    result = subprocess.run(
        ["./test_runner"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "ERROR:" not in result.stdout, (
        f"Some tests threw exceptions:\n{result.stdout}"
    )


def test_no_failures_in_output():
    """No test should produce a wrong value (FAIL)."""
    build_dir = "/app/build"
    result = subprocess.run(
        ["./test_runner"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "FAIL:" not in result.stdout, (
        f"Some tests produced wrong values:\n{result.stdout}"
    )
