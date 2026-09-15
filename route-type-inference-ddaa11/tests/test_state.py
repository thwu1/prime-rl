
import subprocess
import os


def run_cmd(cmd, timeout=180):
    """Run a shell command and return the result."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd="/app",
    )
    return result


class TestRoutePathTypes:
    """Verify that both type-level and runtime tests pass."""

    @classmethod
    def setup_class(cls):
        """Install npm dependencies before running tests."""
        result = run_cmd(["npm", "install", "--silent"])
        assert result.returncode == 0, (
            f"npm install failed with exit code {result.returncode}:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_type_check_passes(self):
        """All type-level assertions in type-checks.ts must compile without errors."""
        result = run_cmd(["npx", "tsc", "--noEmit"], timeout=120)
        assert result.returncode == 0, (
            f"TypeScript type checking failed:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_runtime_tests_pass(self):
        """All runtime tests in url.test.ts and router.test.ts must pass."""
        result = run_cmd(["npx", "vitest", "run", "--reporter=verbose"], timeout=120)
        assert result.returncode == 0, (
            f"Vitest runtime tests failed:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_types_file_exists(self):
        """The types.ts source file must exist."""
        assert os.path.isfile("/app/src/types.ts"), "types.ts not found at /app/src/types.ts"

    def test_url_file_exists(self):
        """The url.ts source file must exist."""
        assert os.path.isfile("/app/src/url.ts"), "url.ts not found at /app/src/url.ts"

    def test_router_file_exists(self):
        """The router.ts source file must exist."""
        assert os.path.isfile("/app/src/router.ts"), "router.ts not found at /app/src/router.ts"

    def test_runtime_test_count(self):
        """Vitest must report at least 70 passing tests to prevent test deletion."""
        result = run_cmd(["npx", "vitest", "run", "--reporter=json"], timeout=120)
        assert result.returncode == 0, (
            f"Vitest tests failed:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        import json
        try:
            report = json.loads(result.stdout)
            passed = report.get("numPassedTests", 0)
        except (json.JSONDecodeError, KeyError):
            passed = 0
        assert passed >= 70, f"Expected at least 70 passing tests, got {passed}"
