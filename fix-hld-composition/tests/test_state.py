
import subprocess
import os
import shutil
import pytest


def ensure_test_data():
    """Ensure test data files exist, restoring from backup if needed."""
    if not os.path.isdir("/app/tests"):
        if os.path.isdir("/opt/initial_app/tests"):
            shutil.copytree("/opt/initial_app/tests", "/app/tests")
        else:
            pytest.fail("Test data not found at /app/tests or /opt/initial_app/tests")


def compile_solution():
    """Compile main.cpp in /app/."""
    result = subprocess.run(
        ["g++", "-O2", "-std=c++17", "-Wall", "-Wextra",
         "-o", "/app/solution", "/app/main.cpp"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"


@pytest.fixture(scope="session", autouse=True)
def setup():
    ensure_test_data()
    compile_solution()


@pytest.mark.parametrize("test_num", [1, 2, 3])
def test_correctness(test_num):
    """Run solution on test input and compare with expected output."""
    input_path = f"/app/tests/input{test_num}.txt"
    expected_path = f"/app/tests/expected{test_num}.txt"

    assert os.path.exists(input_path), f"Missing {input_path}"
    assert os.path.exists(expected_path), f"Missing {expected_path}"

    with open(input_path, "r") as f:
        input_data = f.read()
    with open(expected_path, "r") as f:
        expected = f.read().strip()

    result = subprocess.run(
        ["/app/solution"],
        input=input_data,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, f"Runtime error on test {test_num}:\n{result.stderr}"
    actual = result.stdout.strip()
    assert actual == expected, (
        f"Test {test_num} output mismatch:\n"
        f"Expected:\n{expected}\n"
        f"Got:\n{actual}"
    )


def test_noncommutativity():
    """Verify that path u->v and v->u give different results on test 2.
    Lines 1 and 2 of test 2 output correspond to path 1->8 and 8->1
    with the same x=1, and must differ (non-commutativity check)."""
    expected_path = "/app/tests/expected2.txt"
    with open(expected_path, "r") as f:
        lines = f.read().strip().split("\n")
    fwd_result = lines[0].strip()
    rev_result = lines[1].strip()
    assert fwd_result != rev_result, (
        "Forward and reverse path queries should differ for non-commutative operations"
    )

    input_path = "/app/tests/input2.txt"
    with open(input_path, "r") as f:
        input_data = f.read()

    result = subprocess.run(
        ["/app/solution"],
        input=input_data,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Runtime error:\n{result.stderr}"
    actual_lines = result.stdout.strip().split("\n")
    assert len(actual_lines) >= 2, "Not enough output lines"
    assert actual_lines[0].strip() != actual_lines[1].strip(), (
        f"Path 1->8 and 8->1 should give different results but both gave {actual_lines[0].strip()}"
    )


def test_stub_replaced():
    """Verify that the stub code has been replaced with actual implementations."""
    assert os.path.exists("/app/main.cpp"), "main.cpp not found"
    with open("/app/main.cpp", "r") as f:
        content = f.read()
    # The original stubs have these TODO markers
    todo_count = content.count("// TODO:")
    assert todo_count == 0, (
        f"main.cpp still contains {todo_count} TODO markers — "
        "the stub implementations have not been fully replaced"
    )


def test_inverse_query():
    """Verify inverse query correctness: compose path, then check f(x) = y.

    Uses a self-contained 3-node chain to avoid depending on multi-query
    output line counting from other test inputs.

    Tree: 1 - 2 - 3 (chain)
    Functions: f_1(x)=2x+3, f_2(x)=5x+7, f_3(x)=3x+1
    Path 1->3 composed: f_3(f_2(f_1(x))) = 30x + 67
    Inverse query: find x such that 30x + 67 = 100 (mod 998244353)
    """
    # Step 1: Run a type 3 (inverse) query
    inverse_input = (
        "3 1\n"
        "1 2\n"
        "2 3\n"
        "2 3 5 7 3 1\n"
        "3 1 3 100\n"
    )

    result = subprocess.run(
        ["/app/solution"],
        input=inverse_input,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Inverse query run failed:\n{result.stderr}"

    actual_lines = result.stdout.strip().split("\n")
    assert len(actual_lines) >= 1, (
        f"Expected at least 1 output line from inverse query, got: {result.stdout!r}"
    )
    inverse_x = int(actual_lines[0].strip())
    assert inverse_x >= 0, "Inverse query should return a non-negative value"

    # Step 2: Verify by running a forward (type 2) query with the computed x
    # Same tree and functions; path(1,3)(inverse_x) should equal 100
    verify_input = (
        "3 1\n"
        "1 2\n"
        "2 3\n"
        "2 3 5 7 3 1\n"
        f"2 1 3 {inverse_x}\n"
    )
    verify_result = subprocess.run(
        ["/app/solution"],
        input=verify_input,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert verify_result.returncode == 0, f"Verify run failed:\n{verify_result.stderr}"
    verify_lines = verify_result.stdout.strip().split("\n")
    assert len(verify_lines) >= 1, (
        f"Expected at least 1 output line from verify query, got: {verify_result.stdout!r}"
    )
    composed_value = int(verify_lines[0].strip())
    assert composed_value == 100, (
        f"Inverse query returned x={inverse_x}, but path(1,3)({inverse_x}) = "
        f"{composed_value} != 100"
    )
