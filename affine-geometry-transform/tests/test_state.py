
import subprocess
import json
import pytest
import os

TEST_RUNNER = "/tests/run_tests.ts"

def run_ts_tests():
    """Run the TypeScript test suite and return parsed results."""
    result = subprocess.run(
        ["npx", "tsx", TEST_RUNNER],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
    )
    # Parse JSON from stdout (first line)
    stdout_lines = result.stdout.strip().split("\n")
    if not stdout_lines or not stdout_lines[0].strip():
        pytest.fail(
            f"TypeScript test runner produced no output.\n"
            f"stderr: {result.stderr}\n"
            f"returncode: {result.returncode}"
        )
    try:
        data = json.loads(stdout_lines[0])
    except json.JSONDecodeError:
        pytest.fail(
            f"Could not parse JSON from test runner.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return data


@pytest.fixture(scope="session")
def test_data():
    return run_ts_tests()


def get_test_names(data):
    return [r["name"] for r in data.get("results", [])]


def pytest_generate_tests(metafunc):
    """Dynamically parametrize tests from the TypeScript runner output."""
    if "test_case" in metafunc.fixturenames:
        # We need to run the TS tests to get names for parametrization
        try:
            data = run_ts_tests()
            names = get_test_names(data)
            metafunc.parametrize(
                "test_case",
                names,
                ids=names,
            )
        except Exception as e:
            metafunc.parametrize("test_case", ["__runner_failed__"])


class TestGeometry2d:
    _cached_data = None

    @classmethod
    def _get_data(cls):
        if cls._cached_data is None:
            cls._cached_data = run_ts_tests()
        return cls._cached_data

    def test_geometry(self, test_case):
        if test_case == "__runner_failed__":
            pytest.fail("TypeScript test runner failed to execute")

        data = self._get_data()
        results = {r["name"]: r for r in data.get("results", [])}

        if test_case not in results:
            pytest.fail(f"Test case '{test_case}' not found in results")

        r = results[test_case]
        if not r["pass"]:
            pytest.fail(r.get("detail", "Test failed without detail"))


def test_all_tests_present():
    """Verify the test runner executed and found tests."""
    data = run_ts_tests()
    summary = data.get("summary", {})
    total = summary.get("total", 0)
    assert total > 0, "No tests were executed by the TypeScript runner"


def test_no_failures():
    """Verify zero failures in the TypeScript test suite."""
    data = run_ts_tests()
    summary = data.get("summary", {})
    failed = summary.get("failed", -1)
    assert failed == 0, f"{failed} test(s) failed"
