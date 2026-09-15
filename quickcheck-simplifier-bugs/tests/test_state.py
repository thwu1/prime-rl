
import subprocess
import os
import re

LIB_RS = "/app/src/lib.rs"
PROPS_RS = "/app/tests/properties.rs"

CARGO_ENV = os.environ.copy()
CARGO_ENV["PATH"] = "/opt/cargo/bin:/usr/local/bin:" + CARGO_ENV.get("PATH", "")
CARGO_ENV["RUSTUP_HOME"] = "/opt/rustup"
CARGO_ENV["CARGO_HOME"] = "/opt/cargo"


def run_cargo(args, timeout=180):
    """Run a cargo command in /app and return the result."""
    cmd = ["cargo"] + args
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env=CARGO_ENV, cwd="/app",
    )


def test_project_builds():
    """The project must compile without errors."""
    result = run_cargo(["build"])
    assert result.returncode == 0, f"cargo build failed:\n{result.stderr}"


def test_unit_tests_pass():
    """Built-in unit tests in lib.rs must pass."""
    result = run_cargo(["test", "--lib"])
    assert result.returncode == 0, (
        f"Unit tests failed:\n{result.stdout}\n{result.stderr}"
    )


def test_verification_sub_zero():
    """Bug fix: Sub(Lit(0), b) must produce negation, not b itself."""
    result = run_cargo(["test", "--test", "verify", "--", "verify_sub_zero_produces_negation"])
    assert result.returncode == 0, (
        f"Sub(0,b) bug not fixed:\n{result.stdout}\n{result.stderr}"
    )


def test_verification_div_self_zero():
    """Bug fix: Div(a,a) must not simplify to 1 when a could be zero."""
    result = run_cargo(["test", "--test", "verify", "--", "verify_div_self_handles_zero"])
    assert result.returncode == 0, (
        f"Div(a,a) bug not fixed:\n{result.stdout}\n{result.stderr}"
    )


def test_verification_if_branches():
    """Bug fix: If with literal condition must select the correct branch."""
    result = run_cargo(["test", "--test", "verify", "--", "verify_if_correct_branch"])
    assert result.returncode == 0, (
        f"If branch bug not fixed:\n{result.stdout}\n{result.stderr}"
    )


def test_verification_mul_identity():
    """Bug fix: Mul(a, Lit(1)) must return a, not Lit(1)."""
    result = run_cargo(["test", "--test", "verify", "--", "verify_mul_identity_right"])
    assert result.returncode == 0, (
        f"Mul identity bug not fixed:\n{result.stdout}\n{result.stderr}"
    )


def test_verification_complex():
    """Combined expression exercising multiple simplification rules."""
    result = run_cargo(["test", "--test", "verify", "--", "verify_simplify_complex_expression"])
    assert result.returncode == 0, (
        f"Complex verification failed:\n{result.stdout}\n{result.stderr}"
    )


def test_verification_idempotent():
    """Simplify must be idempotent on expressions that exercise bug sites."""
    result = run_cargo(["test", "--test", "verify", "--", "verify_simplify_idempotent"])
    assert result.returncode == 0, (
        f"Idempotency verification failed:\n{result.stdout}\n{result.stderr}"
    )


def test_arbitrary_implemented():
    """Arbitrary must be implemented for Expr (in lib.rs or tests)."""
    found = False
    for path in [LIB_RS, PROPS_RS]:
        if os.path.exists(path):
            with open(path) as f:
                content = f.read()
            if re.search(r"impl\s+Arbitrary\s+for\s+\w*Expr", content):
                found = True
                break
            if re.search(r"fn\s+arbitrary\s*\(", content) and "Expr" in content:
                found = True
                break
    assert found, (
        "No Arbitrary implementation found for Expr in lib.rs or properties.rs"
    )


def test_property_tests_exist():
    """Property-based tests must exist in tests/properties.rs."""
    assert os.path.exists(PROPS_RS), "tests/properties.rs does not exist"
    with open(PROPS_RS) as f:
        content = f.read()
    has_quickcheck = (
        "#[quickcheck]" in content
        or "quickcheck!" in content
        or "quickcheck(" in content
        or "QuickCheck" in content
    )
    assert has_quickcheck, (
        "No quickcheck property tests found in tests/properties.rs"
    )


def test_property_tests_pass():
    """The agent's property-based tests must pass."""
    result = run_cargo(["test", "--test", "properties"])
    assert result.returncode == 0, (
        f"Property tests failed:\n{result.stdout}\n{result.stderr}"
    )


def test_all_cargo_tests_pass():
    """All cargo tests (unit + integration) must pass."""
    result = run_cargo(["test"])
    assert result.returncode == 0, (
        f"cargo test failed:\n{result.stdout}\n{result.stderr}"
    )
