
import subprocess
import os


def test_hamt_setops_compile():
    """Compile the HAMT source with the test driver."""
    result = subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-O1",
            "-DNDEBUG",
            "-I/app/include",
            "/tests/test_setops.c",
            "/app/src/hamt.c",
            "/app/src/murmur3.c",
            "/app/src/uh.c",
            "-o",
            "/tests/test_setops",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Compilation failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_hamt_setops_run():
    """Run the compiled test binary and verify all tests pass."""
    # Ensure it's compiled
    if not os.path.exists("/tests/test_setops"):
        compile_result = subprocess.run(
            [
                "gcc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-O1",
                "-DNDEBUG",
                "-I/app/include",
                "/tests/test_setops.c",
                "/app/src/hamt.c",
                "/app/src/murmur3.c",
                "/app/src/uh.c",
                "-o",
                "/tests/test_setops",
            ],
            capture_output=True,
            text=True,
        )
        assert compile_result.returncode == 0, (
            f"Compilation failed:\n{compile_result.stderr}"
        )

    result = subprocess.run(
        ["/tests/test_setops"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Test binary returned non-zero exit code ({result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "ALL TESTS PASSED" in result.stdout, (
        f"Not all tests passed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
