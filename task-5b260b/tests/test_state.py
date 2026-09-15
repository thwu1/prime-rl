
import subprocess
import os
import re

# Ensure lean4 toolchain is on PATH for all subprocess calls
os.environ["HOME"] = "/root"
os.environ["ELAN_HOME"] = "/root/.elan"
os.environ["PATH"] = f"/root/.elan/bin:/usr/local/bin:{os.environ.get('PATH', '')}"


def _run_lake(args, timeout=300):
    """Run a lake/lean command with correct env and reasonable timeout."""
    return subprocess.run(
        args,
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
    )


def test_lake_build_succeeds():
    """The Lean 4 project must build without errors."""
    result = _run_lake(["lake", "build"])
    assert result.returncode == 0, (
        f"lake build failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_no_sorry_in_source():
    """No sorry placeholders should remain in any Lean source file."""
    for root, dirs, files in os.walk("/app"):
        # Skip the .lake build cache directory
        if ".lake" in root.split(os.sep):
            continue
        for fname in files:
            if fname.endswith(".lean") and fname != "lakefile.lean":
                filepath = os.path.join(root, fname)
                with open(filepath, "r") as fh:
                    content = fh.read()
                # Strip block comments (/- ... -/) which may mention sorry
                # in instructional text; use non-greedy match with DOTALL
                cleaned = re.sub(r'/-.*?-/', '', content, flags=re.DOTALL)
                for i, line in enumerate(cleaned.split('\n')):
                    stripped = line.strip()
                    # Skip single-line comments
                    if stripped.startswith("--"):
                        continue
                    if re.search(r'\bsorry\b', stripped):
                        assert False, (
                            f"Found 'sorry' in {filepath}: {stripped}"
                        )


def test_no_sorry_warnings_in_build():
    """The build output should contain no sorry-related warnings."""
    result = _run_lake(["lake", "build"])
    combined = (result.stdout + result.stderr).lower()
    assert "sorry" not in combined, (
        f"Build output contains sorry warning:\n{result.stdout}\n{result.stderr}"
    )


def test_no_sorry_axiom():
    """Verify no theorem relies on the sorryAx axiom via #print axioms."""
    theorems = [
        "VerifiedListOps.append_nil",
        "VerifiedListOps.append_assoc",
        "VerifiedListOps.length_append",
        "VerifiedListOps.map_append",
        "VerifiedListOps.reverse_append",
        "VerifiedListOps.reverse_reverse",
        "VerifiedListOps.length_reverse",
        "VerifiedListOps.filter_length",
    ]

    check_lines = ["import VerifiedListOps"]
    for thm in theorems:
        check_lines.append(f"#print axioms {thm}")
    check_code = "\n".join(check_lines) + "\n"

    check_file = "/tmp/_check_axioms.lean"
    with open(check_file, "w") as f:
        f.write(check_code)

    result = _run_lake(["lake", "env", "lean", check_file], timeout=180)

    if os.path.exists(check_file):
        os.remove(check_file)

    combined = result.stdout + result.stderr
    assert "sorryAx" not in combined, (
        f"One or more theorems still use the sorry axiom:\n{combined}"
    )
    assert result.returncode == 0, (
        f"Axiom check compilation failed:\nstderr: {result.stderr}"
    )


def test_definitions_unchanged():
    """Verify the original function definitions were not modified."""
    with open("/app/VerifiedListOps.lean", "r") as f:
        content = f.read()

    # Check that the 5 core definitions still exist with correct signatures
    expected_defs = [
        "def myAppend : List α → List α → List α",
        "def myReverse : List α → List α",
        "def myLength : List α → Nat",
        "def myMap (f : α → β) : List α → List β",
        "def myFilter (p : α → Bool) : List α → List α",
    ]
    for defn in expected_defs:
        assert defn in content, (
            f"Definition signature was modified or removed: {defn}"
        )

    # Check that all 8 theorem statements still exist with correct signatures
    expected_theorems = [
        "theorem append_nil (xs : List α) : myAppend xs [] = xs",
        "theorem append_assoc (xs ys zs : List α) :",
        "theorem length_append (xs ys : List α) :",
        "theorem map_append (f : α → β) (xs ys : List α) :",
        "theorem reverse_append (xs ys : List α) :",
        "theorem reverse_reverse (xs : List α) :",
        "theorem length_reverse (xs : List α) :",
        "theorem filter_length (p : α → Bool) (xs : List α) :",
    ]
    for thm in expected_theorems:
        assert thm in content, (
            f"Theorem statement was modified or removed: {thm}"
        )


def test_filter_length_nontrivial():
    """Verify filter_length is a non-trivial theorem about myFilter and myLength."""
    check_code = "import VerifiedListOps\n#check @VerifiedListOps.filter_length\n"
    check_file = "/tmp/_check_fl.lean"
    with open(check_file, "w") as f:
        f.write(check_code)

    result = _run_lake(["lake", "env", "lean", check_file], timeout=180)

    if os.path.exists(check_file):
        os.remove(check_file)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"Failed to check filter_length type:\nstderr: {result.stderr}"
    )
    # The theorem's type must mention both myFilter and myLength to prevent
    # trivial workarounds like changing the statement to True
    assert "myFilter" in combined and "myLength" in combined, (
        f"filter_length must be a non-trivial statement about myFilter and myLength:\n{combined}"
    )
