
import subprocess


def test_cargo_build():
    """The project must compile without errors."""
    result = subprocess.run(
        ["cargo", "build"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"cargo build failed:\nstderr: {result.stderr[-2000:]}"
    )


def test_cargo_test():
    """All integration tests must pass."""
    result = subprocess.run(
        ["cargo", "test", "--", "--test-threads=1"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"cargo test failed:\nstdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
    )


def test_specific_tests_present():
    """Verify key tests actually ran (not just an empty test suite)."""
    result = subprocess.run(
        ["cargo", "test", "--", "--list"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout
    required_tests = [
        "test_cmp_le_i32_same_type",
        "test_cmp_ge_cross_type_i16_f64",
        "test_str_contains_direct",
        "test_build_cmp_le_i16_f64",
        "test_build_str_contains",
        "test_build_cmp_eq_ne",
        "test_build_cmp_i32_f32_cross",
        "test_dynamic_dispatch_vec",
    ]
    for test_name in required_tests:
        assert test_name in output, (
            f"Required test '{test_name}' not found in test list. "
            f"Available tests:\n{output[:2000]}"
        )
