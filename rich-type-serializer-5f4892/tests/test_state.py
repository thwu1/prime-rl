
import subprocess
import shutil
import os


def test_vitest_all_pass():
    """Run the full vitest test suite and verify all tests pass."""
    # Ensure npm deps are installed
    install = subprocess.run(
        ['npm', 'install', '--silent'],
        cwd='/app',
        capture_output=True,
        text=True,
        timeout=180
    )
    assert install.returncode == 0, (
        f"npm install failed:\n{install.stderr}"
    )

    # Copy authoritative test suite
    shutil.copy('/tests/test_suite.ts', '/app/src/index.test.ts')

    # Run vitest
    result = subprocess.run(
        ['npx', 'vitest', 'run', '--reporter=verbose'],
        cwd='/app',
        capture_output=True,
        text=True,
        timeout=120
    )
    assert result.returncode == 0, (
        f"Vitest tests failed (exit {result.returncode}):\n"
        f"STDOUT:\n{result.stdout[-3000:]}\n"
        f"STDERR:\n{result.stderr[-2000:]}"
    )
    # Verify tests actually ran (not zero tests)
    assert 'pass' in result.stdout.lower() or 'passed' in result.stdout.lower(), (
        f"No passing tests found in output:\n{result.stdout[-2000:]}"
    )
