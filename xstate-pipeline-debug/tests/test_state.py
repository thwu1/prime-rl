
import subprocess
import json
import pytest


def run_cmd(args, cwd="/app", timeout=60):
    """Run a command and return the result."""
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
    )
    return result


class TestTypeScriptCompilation:
    def test_tsc_no_emit(self):
        """TypeScript must compile without errors."""
        result = run_cmd(["npx", "tsc", "--noEmit"])
        assert result.returncode == 0, (
            f"TypeScript compilation failed:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


class TestHappyPath:
    def _get_result(self):
        result = run_cmd(["npx", "tsx", "test_runner.ts", "happy"])
        assert result.returncode == 0, (
            f"Test runner crashed:\nstderr: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )
        return json.loads(result.stdout)

    def test_reaches_succeeded(self):
        """Pipeline should reach 'succeeded' final state."""
        data = self._get_result()
        assert "error" not in data, f"Runner error: {data.get('error')}"
        assert data["final_state"] == "succeeded"

    def test_all_stages_recorded(self):
        """All six stages should have results in context."""
        data = self._get_result()
        assert data["stage_count"] == 6, (
            f"Expected 6 stage results, got {data['stage_count']}. "
            f"Stages: {data.get('stage_names')}"
        )

    def test_all_stages_passed(self):
        """All stage results should have status 'passed'."""
        data = self._get_result()
        assert data["all_passed"] is True

    def test_completed_at_set(self):
        """completedAt should be set on successful completion."""
        data = self._get_result()
        assert data["completed_at"] is not None

    def test_no_compensations_on_success(self):
        """No compensations should run on successful pipeline."""
        data = self._get_result()
        assert data["compensation_count"] == 0, (
            f"Expected 0 compensations on success, got {data['compensation_count']}"
        )


class TestDeployFailure:
    def _get_result(self):
        result = run_cmd(["npx", "tsx", "test_runner.ts", "deploy_fail"])
        assert result.returncode == 0, (
            f"Test runner crashed:\nstderr: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )
        return json.loads(result.stdout)

    def test_reaches_failed(self):
        """Pipeline should reach 'failed' when deploy throws."""
        data = self._get_result()
        assert "error" not in data, f"Runner error: {data.get('error')}"
        assert data["final_state"] == "failed"

    def test_error_captured(self):
        """context.error should be set when deploy fails."""
        data = self._get_result()
        assert data["has_error"] is True

    def test_compensations_executed(self):
        """At least one compensation should execute on deploy failure."""
        data = self._get_result()
        assert data["compensation_count"] >= 1, (
            f"Expected at least 1 compensation, got {data['compensation_count']}"
        )

    def test_compensatable_stages_compensated(self):
        """Completed compensatable stages (lint, build) should be compensated."""
        data = self._get_result()
        comp_stages = set(data["compensation_stages"])
        assert "build" in comp_stages, (
            f"'build' should be compensated, got {comp_stages}"
        )
        assert "lint" in comp_stages, (
            f"'lint' should be compensated, got {comp_stages}"
        )

    def test_compensation_order_is_reverse(self):
        """Compensations must run in reverse execution order (build before lint)."""
        data = self._get_result()
        comp_stages = data["compensation_stages"]
        if len(comp_stages) >= 2:
            build_idx = comp_stages.index("build")
            lint_idx = comp_stages.index("lint")
            assert build_idx < lint_idx, (
                f"Expected build before lint in compensations (reverse order), "
                f"got {comp_stages}"
            )

    def test_all_compensations_succeeded(self):
        """All compensation results should have status 'compensated'."""
        data = self._get_result()
        assert data["compensation_all_succeeded"] is True


class TestTestFailure:
    def _get_result(self):
        result = run_cmd(["npx", "tsx", "test_runner.ts", "test_fail"])
        assert result.returncode == 0, (
            f"Test runner crashed:\nstderr: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )
        return json.loads(result.stdout)

    def test_reaches_failed(self):
        """Pipeline should reach 'failed' when tests fail."""
        data = self._get_result()
        assert "error" not in data, f"Runner error: {data.get('error')}"
        assert data["final_state"] == "failed"

    def test_deploy_not_attempted(self):
        """Deploy should never be attempted when tests fail."""
        data = self._get_result()
        assert data["deploy_attempted"] is False, (
            "Deploy was attempted despite test failures"
        )

    def test_no_compensations_on_test_failure(self):
        """Test failures go to failed directly without compensation."""
        data = self._get_result()
        assert data["compensation_count"] == 0, (
            f"Expected 0 compensations on test failure, "
            f"got {data['compensation_count']}"
        )
