"""
Tests for SECCOMP BPF pledge() implementation.

Compiles the pledge implementation, runs the C test harness, and
verifies each scenario passes: allowed operations succeed and
forbidden operations are killed by SIGSYS.

"""
import subprocess
import pytest


@pytest.fixture(scope="module")
def harness_output():
    """Compile pledge.c + test_harness.c, run the binary, return stdout."""
    # Compile
    comp = subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True, timeout=30,
    )
    assert comp.returncode == 0, (
        f"Compilation failed:\nstdout:\n{comp.stdout}\nstderr:\n{comp.stderr}"
    )

    # Run
    run = subprocess.run(
        ["/app/test_harness"],
        capture_output=True, text=True, timeout=120,
    )
    return run.stdout


def test_compilation(harness_output):
    """pledge.c compiles and links without errors."""
    assert harness_output is not None


def test_stdio_write_allowed(harness_output):
    """stdio promise allows SYS_write to stdout."""
    assert "PASS stdio_write_allowed" in harness_output


def test_stdio_openat_blocked(harness_output):
    """stdio-only pledge kills process on SYS_openat."""
    assert "PASS stdio_openat_blocked" in harness_output


def test_rpath_openat_rdonly(harness_output):
    """rpath allows openat with O_RDONLY via argument-level BPF filter."""
    assert "PASS rpath_openat_rdonly" in harness_output


def test_rpath_openat_wronly_blocked(harness_output):
    """rpath blocks openat with O_WRONLY via argument-level BPF filter."""
    assert "PASS rpath_openat_wronly_blocked" in harness_output


def test_wpath_openat_wronly(harness_output):
    """wpath allows openat with O_WRONLY unconditionally."""
    assert "PASS wpath_openat_wronly" in harness_output


def test_inet_socket_allowed(harness_output):
    """inet allows socket(AF_INET) via argument-level BPF filter."""
    assert "PASS inet_socket_allowed" in harness_output


def test_inet_socket_unix_blocked(harness_output):
    """inet blocks socket(AF_UNIX) via argument-level BPF filter."""
    assert "PASS inet_socket_unix_blocked" in harness_output


def test_stdio_socket_blocked(harness_output):
    """stdio-only pledge kills process on any socket() call."""
    assert "PASS stdio_socket_blocked" in harness_output


def test_proc_fork_allowed(harness_output):
    """proc promise allows clone (fork) and wait4."""
    assert "PASS proc_fork_allowed" in harness_output


def test_stdio_fork_blocked(harness_output):
    """stdio-only pledge kills process on clone."""
    assert "PASS stdio_fork_blocked" in harness_output


def test_empty_pledge_blocks_write(harness_output):
    """Empty promise string blocks even SYS_write."""
    assert "PASS empty_pledge_blocks_write" in harness_output


def test_empty_pledge_allows_exit(harness_output):
    """Empty promise string still allows exit_group."""
    assert "PASS empty_pledge_allows_exit" in harness_output


def test_all_tests_pass(harness_output):
    """All 12 C-level tests pass with 0 failures."""
    assert "0 failed" in harness_output
