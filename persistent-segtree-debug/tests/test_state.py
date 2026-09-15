
import subprocess
import pytest
import random

MOD = 998244353


def run_program(input_text):
    """Run the compiled persistent_segtree binary with given input."""
    result = subprocess.run(
        ["/app/target/release/persistent_segtree"],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Program crashed:\n{result.stderr}"
    return result.stdout.strip()


def check_test_file(test_name):
    """Run binary against a test file and compare output."""
    with open(f"/app/data/{test_name}.in") as f:
        input_text = f.read()
    with open(f"/app/data/{test_name}.out") as f:
        expected = f.read().strip()
    actual = run_program(input_text)
    assert actual == expected, (
        f"Test {test_name} failed.\n"
        f"Expected:\n{expected}\n"
        f"Actual:\n{actual}"
    )


def test_basic_affine():
    """Test basic affine transforms: multiply-add, zero-out, multiply-only."""
    check_test_file("test1")


def test_single_element():
    """Test edge case with single-element array and affine transforms."""
    check_test_file("test2")


def test_stacked_transforms():
    """Test stacked affine transforms across chained versions."""
    check_test_file("test3")


def test_modular_arithmetic():
    """Test modular arithmetic edge cases near P boundary and multiply by P-1."""
    check_test_file("test4")


def test_forked_partial_ranges():
    """Test partial-range affine transforms on forked versions."""
    check_test_file("test5")


def test_stress_correctness():
    """Stress test: compare against Python brute-force on random affine operations."""
    random.seed(42)
    n = 50
    arr = [random.randint(0, MOD - 1) for _ in range(n)]
    ops = []
    version_count = 0

    for _ in range(200):
        op_type = random.choice([1, 1, 2])
        v = random.randint(0, version_count)
        l = random.randint(1, n)
        r = random.randint(l, n)
        if op_type == 1:
            a = random.randint(0, MOD - 1)
            b = random.randint(0, MOD - 1)
            ops.append([1, v, l, r, a, b])
            version_count += 1
        else:
            ops.append([2, v, l, r])

    # Brute-force simulation
    versions = [list(arr)]
    expected_lines = []
    for op in ops:
        if op[0] == 1:
            base = list(versions[op[1]])
            for i in range(op[2] - 1, op[3]):
                base[i] = (op[4] * base[i] + op[5]) % MOD
            versions.append(base)
        else:
            expected_lines.append(str(sum(versions[op[1]][op[2] - 1 : op[3]]) % MOD))

    # Build input string
    lines = [f"{n} {len(ops)}", " ".join(str(x) for x in arr)]
    for op in ops:
        lines.append(" ".join(str(x) for x in op))
    input_text = "\n".join(lines) + "\n"

    actual = run_program(input_text)
    actual_lines = actual.split("\n")

    assert len(actual_lines) == len(expected_lines), (
        f"Line count mismatch: got {len(actual_lines)}, expected {len(expected_lines)}"
    )
    for i, (a, e) in enumerate(zip(actual_lines, expected_lines)):
        assert a.strip() == e.strip(), (
            f"Line {i + 1}: got '{a.strip()}', expected '{e.strip()}'"
        )


def test_performance():
    """Verify the solution handles large inputs within time limits."""
    random.seed(123)
    n = 100000
    arr = [random.randint(0, MOD - 1) for _ in range(n)]

    lines = [f"{n} 1000"]
    lines.append(" ".join(str(x) for x in arr))

    version_count = 0
    for _ in range(1000):
        op_type = random.choice([1, 2])
        v = random.randint(0, version_count)
        l = random.randint(1, n)
        r = random.randint(l, n)
        if op_type == 1:
            a = random.randint(0, MOD - 1)
            b = random.randint(0, MOD - 1)
            lines.append(f"1 {v} {l} {r} {a} {b}")
            version_count += 1
        else:
            lines.append(f"2 {v} {l} {r}")

    input_text = "\n".join(lines) + "\n"

    result = subprocess.run(
        ["/app/target/release/persistent_segtree"],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Program failed on large input:\n{result.stderr}"
    assert len(result.stdout.strip()) > 0, "No output produced for large input"
