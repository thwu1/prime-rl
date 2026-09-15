
import subprocess


def test_typescript_type_check():
    """All type assertions in type-checks.ts must pass tsc --noEmit."""
    result = subprocess.run(
        ["npx", "tsc", "--noEmit"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"tsc --noEmit failed (exit code {result.returncode}).\n"
        f"Errors:\n{result.stdout}\n{result.stderr}"
    )


def test_stub_files_are_substantial():
    """Implementation files must contain substantial type logic, not just stubs."""
    import os

    files = [
        "/app/src/types/DeepExclude.ts",
        "/app/src/types/DistributeUnions.ts",
        "/app/src/types/BuildMany.ts",
        "/app/src/types/IsMatching.ts",
    ]
    for filepath in files:
        assert os.path.exists(filepath), f"Missing file: {filepath}"
        with open(filepath) as f:
            content = f.read()
        # A real implementation should be more than a trivial stub
        assert len(content) > 100, (
            f"{filepath} is too short ({len(content)} chars) — "
            f"appears to still be a placeholder"
        )
