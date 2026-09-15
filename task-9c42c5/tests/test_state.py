
import subprocess
import pytest


def run_coqc(args, timeout=120):
    """Run coqc with the given arguments and return the result."""
    result = subprocess.run(
        ["coqc"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


class TestIPLCompilation:
    """Test that IPL.v compiles successfully."""

    def test_ipl_compiles(self):
        """The IPL.v file must compile without errors."""
        result = run_coqc(["-Q", "/app", "IPL", "/app/IPL.v"])
        assert result.returncode == 0, (
            f"IPL.v compilation failed with exit code {result.returncode}.\n"
            f"stderr:\n{result.stderr}\n"
            f"stdout:\n{result.stdout}"
        )


class TestPositiveGoals:
    """Test that solve_prop/ipl_auto proves intuitionistically valid goals."""

    def test_positive_goals(self):
        """All positive goals in test_ipl.v must be proved."""
        # First compile IPL.v
        r1 = run_coqc(["-Q", "/app", "IPL", "/app/IPL.v"])
        assert r1.returncode == 0, (
            f"IPL.v compilation failed:\n{r1.stderr}"
        )

        # Then compile the test file
        r2 = run_coqc(
            ["-Q", "/app", "IPL", "/tests/test_ipl.v"],
            timeout=180,
        )
        assert r2.returncode == 0, (
            f"test_ipl.v compilation failed with exit code {r2.returncode}.\n"
            f"stderr:\n{r2.stderr}\n"
            f"stdout:\n{r2.stdout}"
        )


class TestNegativeGoals:
    """Test that classically-valid but intuitionistically-invalid goals fail."""

    def test_negative_goals(self):
        """Negative goals (wrapped in Fail) must not be provable.

        This is implicitly tested by test_positive_goals since test_ipl.v
        contains Fail commands. If a Fail command's argument succeeds,
        coqc reports an error. So if test_ipl.v compiles, all Fail
        assertions hold.
        """
        pass


class TestDepthBounds:
    """Test that depth bounds are respected."""

    def test_depth_bounds(self):
        """Depth bounds are tested within test_ipl.v via Fail solve_prop 3
        on goals that require more than 3 steps, and solve_prop 15 on
        goals that need fewer steps. This is implicitly checked by
        test_positive_goals.
        """
        pass
