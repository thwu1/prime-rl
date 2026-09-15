
import subprocess
import os
import shutil


def _go_env():
    """Return environment with Go paths explicitly set."""
    env = os.environ.copy()
    env.setdefault("GOTOOLCHAIN", "local")
    return env


def _run(cmd, cwd="/app", timeout=180):
    """Run a command and return the CompletedProcess."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_go_env(),
    )


def _ensure_test_file():
    """Copy the authoritative test file into the Go project."""
    shutil.copy("/tests/reconciler_test.go", "/app/engine/reconciler_test.go")


def test_go_build():
    """The project must compile without errors."""
    _ensure_test_file()
    result = _run(["go", "build", "./..."])
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"


def test_go_vet():
    """go vet must pass."""
    _ensure_test_file()
    result = _run(["go", "vet", "./..."])
    assert result.returncode == 0, f"go vet failed:\n{result.stderr}"


def test_reconciler_not_stub():
    """The reconciler must be implemented (not return 'not implemented')."""
    with open("/app/engine/reconciler.go") as f:
        content = f.read()
    assert 'return fmt.Errorf("not implemented")' not in content, (
        "Reconciler Run() still returns 'not implemented'"
    )


def test_cycle_detection():
    """Cycle detection tests must pass."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-run", "TestCycleDetection|TestTriangleCycle",
         "-timeout", "60s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Cycle detection tests failed:\n{result.stdout}\n{result.stderr}"
    )


def test_single_resource():
    """Single resource convergence test must pass."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-run", "TestSingleResourceConvergence",
         "-timeout", "60s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Single resource test failed:\n{result.stdout}\n{result.stderr}"
    )


def test_dependency_ordering():
    """Linear and diamond dependency ordering tests must pass."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-run", "TestLinearDependencyOrder|TestDiamondDependency",
         "-timeout", "60s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Dependency ordering tests failed:\n{result.stdout}\n{result.stderr}"
    )


def test_parallel_execution():
    """Parallel execution test must pass."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-run", "TestParallelExecution",
         "-timeout", "60s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Parallel execution test failed:\n{result.stdout}\n{result.stderr}"
    )


def test_refresh_notification():
    """Refresh notification test must pass."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-run", "TestRefreshNotification",
         "-timeout", "60s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Refresh notification test failed:\n{result.stdout}\n{result.stderr}"
    )


def test_noop_mode():
    """Noop mode test must pass."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-run", "TestNoopMode",
         "-timeout", "60s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Noop mode test failed:\n{result.stdout}\n{result.stderr}"
    )


def test_event_recheck():
    """Event-triggered recheck test must pass."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-run", "TestEventTriggersRecheck",
         "-timeout", "60s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Event recheck test failed:\n{result.stdout}\n{result.stderr}"
    )


def test_retry_mechanism():
    """Retry and retry-exhaustion tests must pass."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-run", "TestResourceRetry|TestRetryExhaustion",
         "-timeout", "60s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Retry tests failed:\n{result.stdout}\n{result.stderr}"
    )


def test_graceful_shutdown():
    """Graceful shutdown test must pass."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-run", "TestGracefulShutdown",
         "-timeout", "60s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Graceful shutdown test failed:\n{result.stdout}\n{result.stderr}"
    )


def test_all_tests_pass():
    """All Go tests must pass together."""
    _ensure_test_file()
    result = _run(
        ["go", "test", "-v", "-timeout", "180s", "-count=1", "./engine/..."]
    )
    assert result.returncode == 0, (
        f"Full test suite failed:\n{result.stdout}\n{result.stderr}"
    )
