"""Tests for the NAE-SAT to 3-Coloring Lean formalization."""

import re


def test_no_sorry_in_source():
    """The Lean source file must not contain any sorry outside of comments."""
    with open("/app/Reduction.lean", "r") as f:
        content = f.read()
    # Strip single-line comments (-- ... to end of line)
    no_line_comments = re.sub(r"--.*$", "", content, flags=re.MULTILINE)
    # Strip block comments (/- ... -/), including nested
    no_comments = re.sub(r"/\-.*?\-/", "", no_line_comments, flags=re.DOTALL)
    matches = re.findall(r"\bsorry\b", no_comments)
    assert len(matches) == 0, (
        f"Source file still contains {len(matches)} occurrence(s) of 'sorry'"
    )


def test_lean_build_succeeds():
    """lake build must exit with code 0."""
    with open("/tmp/lean_build_exitcode.txt", "r") as f:
        exitcode = int(f.read().strip())
    assert exitcode == 0, f"lake build failed with exit code {exitcode}"


def test_no_sorry_in_build_output():
    """Build output must not contain any sorry warnings."""
    with open("/tmp/lean_build_output.txt", "r") as f:
        output = f.read()
    assert "sorry" not in output.lower(), (
        f"Build output contains sorry warning:\n{output[:500]}"
    )
