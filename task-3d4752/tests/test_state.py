
import subprocess
import os


def test_hsm_c_not_stub():
    """Verify hsm.c has been modified from the original stub."""
    with open("/app/hsm.c", "r") as f:
        content = f.read()
    assert "YOUR IMPLEMENTATION HERE" not in content, \
        "hsm.c still contains stub markers - implementation required"


def test_primary_suite():
    """Build and run the primary test suite (10 test cases, 4-level hierarchy)."""
    result = subprocess.run(
        ["gcc", "-Wall", "-Wextra", "-std=c11",
         "-o", "/app/hsm_test",
         "/app/main.c", "/app/hsm.c", "/app/test_sm.c"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Primary build failed:\n{result.stderr}"

    result = subprocess.run(
        ["/app/hsm_test"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"Primary tests failed (exit {result.returncode}):\n{result.stdout}"

    lines = result.stdout.strip().split('\n')
    pass_lines = [l for l in lines if l.startswith('PASS')]
    fail_lines = [l for l in lines if l.startswith('FAIL')]
    assert len(fail_lines) == 0, \
        f"Failed tests:\n" + "\n".join(fail_lines)
    assert len(pass_lines) >= 10, \
        f"Expected at least 10 PASS lines, got {len(pass_lines)}"


def test_secondary_suite():
    """Build and run the secondary test suite (6 test cases, different topology)."""
    result = subprocess.run(
        ["gcc", "-Wall", "-Wextra", "-std=c11",
         "-o", "/app/hsm_test2",
         "/tests/test_main2.c", "/tests/test_sm2.c", "/app/hsm.c",
         "-I/app"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, \
        f"Secondary build failed:\n{result.stderr}"

    result = subprocess.run(
        ["/app/hsm_test2"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"Secondary tests failed (exit {result.returncode}):\n{result.stdout}"

    lines = result.stdout.strip().split('\n')
    fail_lines = [l for l in lines if l.startswith('FAIL')]
    assert len(fail_lines) == 0, \
        f"Secondary failed tests:\n" + "\n".join(fail_lines)
    pass_lines = [l for l in lines if l.startswith('PASS')]
    assert len(pass_lines) >= 6, \
        f"Expected at least 6 PASS lines in secondary, got {len(pass_lines)}"


def test_guard_suite():
    """Build and run guard condition test suite (8 tests with HSM_UNHANDLED)."""
    result = subprocess.run(
        ["gcc", "-Wall", "-Wextra", "-std=c11",
         "-o", "/app/hsm_test3",
         "/tests/test_main3.c", "/tests/test_sm3.c", "/app/hsm.c",
         "-I/app"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, \
        f"Guard build failed:\n{result.stderr}"

    result = subprocess.run(
        ["/app/hsm_test3"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"Guard tests failed (exit {result.returncode}):\n{result.stdout}"

    lines = result.stdout.strip().split('\n')
    fail_lines = [l for l in lines if l.startswith('FAIL')]
    assert len(fail_lines) == 0, \
        f"Guard failed tests:\n" + "\n".join(fail_lines)
    pass_lines = [l for l in lines if l.startswith('PASS')]
    assert len(pass_lines) >= 8, \
        f"Expected at least 8 PASS lines in guard suite, got {len(pass_lines)}"


def test_is_in_suite():
    """Build and run hsm_is_in containment query tests."""
    result = subprocess.run(
        ["gcc", "-Wall", "-Wextra", "-std=c11",
         "-o", "/app/hsm_test_isin",
         "/tests/test_is_in.c", "/app/hsm.c", "/app/test_sm.c",
         "-I/app"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, \
        f"is_in build failed:\n{result.stderr}"

    result = subprocess.run(
        ["/app/hsm_test_isin"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"is_in tests failed (exit {result.returncode}):\n{result.stdout}"

    lines = result.stdout.strip().split('\n')
    fail_lines = [l for l in lines if l.startswith('FAIL')]
    assert len(fail_lines) == 0, \
        f"is_in failed tests:\n" + "\n".join(fail_lines)
    pass_lines = [l for l in lines if l.startswith('PASS')]
    assert len(pass_lines) >= 14, \
        f"Expected at least 14 PASS lines in is_in suite, got {len(pass_lines)}"


def test_asan_ubsan_clean():
    """Build with AddressSanitizer + UBSan and verify clean execution."""
    suites = [
        ("primary",
         ["/app/main.c", "/app/hsm.c", "/app/test_sm.c"],
         "/app/hsm_asan1", []),
        ("guard",
         ["/tests/test_main3.c", "/tests/test_sm3.c", "/app/hsm.c"],
         "/app/hsm_asan3", ["-I/app"]),
        ("is_in",
         ["/tests/test_is_in.c", "/app/hsm.c", "/app/test_sm.c"],
         "/app/hsm_asan_isin", ["-I/app"]),
    ]

    env = os.environ.copy()
    env["ASAN_OPTIONS"] = "detect_leaks=0"

    for name, srcs, binary, extra in suites:
        result = subprocess.run(
            ["gcc", "-Wall", "-Wextra", "-std=c11", "-g",
             "-fsanitize=address,undefined",
             "-static-libasan",
             "-o", binary] + srcs + extra,
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"ASan build failed ({name}):\n{result.stderr}"

        result = subprocess.run(
            [binary], capture_output=True, text=True, timeout=30, env=env
        )
        assert result.returncode == 0, \
            f"ASan tests failed ({name}, exit {result.returncode}):\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"


def test_valgrind_memcheck():
    """Verify zero Valgrind memcheck errors on primary and guard suites."""
    # Build primary for Valgrind
    result = subprocess.run(
        ["gcc", "-Wall", "-Wextra", "-std=c11", "-g",
         "-o", "/app/hsm_test_vg",
         "/app/main.c", "/app/hsm.c", "/app/test_sm.c"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Build for Valgrind failed:\n{result.stderr}"

    result = subprocess.run(
        ["valgrind", "--error-exitcode=42", "--leak-check=full",
         "--errors-for-leak-kinds=definite",
         "/app/hsm_test_vg"],
        capture_output=True, text=True, timeout=60
    )
    assert "ERROR SUMMARY: 0 errors" in result.stderr, \
        f"Valgrind detected memory errors:\n{result.stderr}"
    assert result.returncode == 0, \
        f"Tests failed under Valgrind (exit {result.returncode}):\n" \
        f"stdout: {result.stdout}\nstderr: {result.stderr}"

    # Build guard suite for Valgrind
    result = subprocess.run(
        ["gcc", "-Wall", "-Wextra", "-std=c11", "-g",
         "-o", "/app/hsm_test3_vg",
         "/tests/test_main3.c", "/tests/test_sm3.c", "/app/hsm.c",
         "-I/app"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, \
        f"Guard build for Valgrind failed:\n{result.stderr}"

    result = subprocess.run(
        ["valgrind", "--error-exitcode=42", "--leak-check=full",
         "--errors-for-leak-kinds=definite",
         "/app/hsm_test3_vg"],
        capture_output=True, text=True, timeout=60
    )
    assert "ERROR SUMMARY: 0 errors" in result.stderr, \
        f"Valgrind detected memory errors (guard):\n{result.stderr}"
    assert result.returncode == 0, \
        f"Guard tests failed under Valgrind (exit {result.returncode}):\n" \
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
