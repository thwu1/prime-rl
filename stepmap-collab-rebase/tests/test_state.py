
import subprocess
import json
import pytest
import os


def get_ts_results():
    """Run the TypeScript test suite and parse its JSON output."""
    try:
        result = subprocess.run(
            ["tsx", "/app/src/run_tests.ts"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/app",
        )
        # Try to parse JSON from stdout
        stdout = result.stdout.strip()
        if not stdout:
            return [
                {
                    "group": "setup",
                    "name": "typescript_execution",
                    "passed": False,
                    "error": f"No output from tsx. stderr: {result.stderr[:500]}",
                }
            ]
        data = json.loads(stdout)
        return data["results"]
    except subprocess.TimeoutExpired:
        return [
            {
                "group": "setup",
                "name": "typescript_execution",
                "passed": False,
                "error": "TypeScript test execution timed out after 120s",
            }
        ]
    except json.JSONDecodeError as e:
        return [
            {
                "group": "setup",
                "name": "typescript_execution",
                "passed": False,
                "error": f"Failed to parse JSON output: {e}. stdout: {result.stdout[:500]}",
            }
        ]
    except Exception as e:
        return [
            {
                "group": "setup",
                "name": "typescript_execution",
                "passed": False,
                "error": str(e),
            }
        ]


results = get_ts_results()


@pytest.mark.parametrize(
    "test_case",
    results,
    ids=[f"{r['group']}/{r['name']}" for r in results],
)
def test_collab_rebase(test_case):
    assert test_case["passed"], test_case.get("error", "Test failed")
