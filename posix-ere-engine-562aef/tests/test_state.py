"""
Verify that the POSIX ERE engine passes all conformance tests, exports
correct shared library symbols, and has zero memory leaks.

"""

import json
import subprocess
import os

RESULTS_PATH = "/app/results.json"


def test_build_succeeds():
    """The project must compile without errors."""
    r = subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
    r = subprocess.run(["make", "-C", "/app"], capture_output=True)
    assert r.returncode == 0, f"Build failed:\n{r.stderr.decode()}"


def test_all_vectors_pass():
    """Every test vector in the conformance suite must pass."""
    r = subprocess.run(
        ["./test_driver"], cwd="/app",
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    assert r.stdout.strip(), "test_driver produced no output"
    data = json.loads(r.stdout)

    total = data["total"]
    passed = data["passed"]
    failed = data["failed"]

    assert total > 0, "No tests were run"

    failures = [
        d for d in data.get("details", []) if d.get("result") == "FAIL"
    ]
    fail_msgs = "\n".join(
        f"  line {d['line']}: pattern={d['pattern']}  reason={d['reason']}"
        for d in failures[:30]
    )

    assert failed == 0, (
        f"{failed}/{total} tests failed (passed {passed}).\n"
        f"First failures:\n{fail_msgs}"
    )


def test_minimum_test_count():
    """Sanity-check that the suite has a reasonable number of test vectors."""
    r = subprocess.run(
        ["./test_driver"], cwd="/app",
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    if not r.stdout.strip():
        return
    data = json.loads(r.stdout)
    assert data["total"] >= 100, (
        f"Only {data['total']} tests found — expected >= 100"
    )


def test_shared_library_exists():
    """libposixre.so must exist at /app/libposixre.so."""
    assert os.path.isfile("/app/libposixre.so"), (
        "Shared library /app/libposixre.so not found"
    )


def test_shared_library_symbols():
    """libposixre.so must export regcomp, regexec, regfree, regerror as T symbols."""
    r = subprocess.run(
        ["nm", "-D", "/app/libposixre.so"],
        capture_output=True, text=True
    )
    assert r.returncode == 0, f"nm -D failed: {r.stderr}"
    required = ["regcomp", "regexec", "regfree", "regerror"]
    for sym in required:
        found = any(
            len(parts) >= 3 and parts[1] == "T" and parts[2] == sym
            for parts in (line.split() for line in r.stdout.splitlines())
        )
        assert found, (
            f"Symbol '{sym}' not exported as dynamic text symbol (T) "
            f"in libposixre.so.\nnm -D output:\n{r.stdout[:1500]}"
        )


def test_valgrind_no_leaks():
    """The engine must have zero definitely-lost memory under valgrind."""
    subprocess.run(["make", "-C", "/app"], capture_output=True)
    assert os.path.isfile("/app/test_driver"), "test_driver binary not found"
    r = subprocess.run(
        ["valgrind", "--leak-check=full",
         "--errors-for-leak-kinds=definite",
         "--error-exitcode=99",
         "./test_driver"],
        cwd="/app",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180
    )
    assert r.returncode != 99, (
        f"Valgrind detected definite memory leaks:\n"
        f"{r.stderr[-2000:]}"
    )
    assert r.returncode == 0, (
        f"test_driver failed under valgrind (exit code {r.returncode})"
    )
