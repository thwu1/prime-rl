
"""
Tests for the sealed-type exhaustiveness checker.
Builds the project via Makefile, runs the checker JAR on each test input,
and compares stdout against expected output.
"""

import subprocess
import pytest
import os

EXPECTED = {
    "test01": "s1:exhaustive=true,null_handled=false,missing=,dominated=",
    "test02": "s1:exhaustive=false,null_handled=false,missing=Triangle,dominated=",
    "test03": "s1:exhaustive=true,null_handled=false,missing=,dominated=",
    "test04": "s1:exhaustive=false,null_handled=false,missing=Circle,dominated=",
    "test05": "s1:exhaustive=true,null_handled=false,missing=,dominated=",
    "test06": "s1:exhaustive=true,null_handled=false,missing=,dominated=",
    "test07": "s1:exhaustive=true,null_handled=false,missing=,dominated=1",
    "test08": "s1:exhaustive=true,null_handled=true,missing=,dominated=",
    "test09": "s1:exhaustive=true,null_handled=true,missing=,dominated=",
    "test10": "s1:exhaustive=true,null_handled=false,missing=,dominated=",
    "test11": "s1:exhaustive=false,null_handled=false,missing=Status.ACTIVE,dominated=",
    "test12": "s1:exhaustive=true,null_handled=false,missing=,dominated=",
    "test13": "s1:exhaustive=true,null_handled=false,missing=,dominated=1",
    "test14": "s1:exhaustive=true,null_handled=false,missing=,dominated=",
}


@pytest.fixture(scope="session", autouse=True)
def build_project():
    """Build the project using the Makefile: clean then jar."""
    clean = subprocess.run(
        ["make", "-C", "/app", "clean"],
        capture_output=True,
        text=True,
    )
    build = subprocess.run(
        ["make", "-C", "/app", "jar"],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, (
        f"Build failed (make jar):\nstdout:\n{build.stdout}\nstderr:\n{build.stderr}"
    )
    assert os.path.exists("/app/checker.jar"), "checker.jar was not created"


@pytest.mark.parametrize("test_name", sorted(EXPECTED.keys()))
def test_exhaustiveness_checker(test_name, build_project):
    """Run the checker JAR on a test input and verify the output."""
    input_file = f"/app/testdata/{test_name}.txt"
    assert os.path.exists(input_file), f"Missing test file: {input_file}"

    result = subprocess.run(
        ["java", "-jar", "/app/checker.jar", input_file],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=10,
    )
    assert result.returncode == 0, (
        f"Checker crashed on {test_name}:\nstderr: {result.stderr}\nstdout: {result.stdout}"
    )

    actual = result.stdout.strip()
    expected = EXPECTED[test_name]
    assert actual == expected, (
        f"\n  Test:     {test_name}\n"
        f"  Expected: {expected}\n"
        f"  Actual:   {actual}"
    )
