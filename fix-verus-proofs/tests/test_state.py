
import subprocess
import os
import re


VERUS_PATH = "/opt/verus/verus"
SOURCE_FILE = "/app/verified_algorithms.rs"

VERUS_ENV = {
    **os.environ,
    "PATH": f"/opt/verus:/opt/cargo/bin:/usr/local/bin:{os.environ.get('PATH', '')}",
    "CARGO_HOME": "/opt/cargo",
    "RUSTUP_HOME": "/opt/rustup",
    "HOME": "/root",
}


def read_source():
    """Read the source file contents."""
    with open(SOURCE_FILE, "r") as f:
        return f.read()


def test_source_file_exists():
    """The source file must exist at the expected path."""
    assert os.path.isfile(SOURCE_FILE), f"{SOURCE_FILE} does not exist"


def test_no_assume_false():
    """The source file must not contain assume(false) — that's cheating."""
    content = read_source()
    matches = re.findall(r'\bassume\s*\(\s*false\s*\)', content)
    assert len(matches) == 0, (
        f"Found {len(matches)} assume(false) statement(s) in {SOURCE_FILE}. "
        "These are disallowed — proofs must be completed without unsound assumptions."
    )


def test_no_verification_bypass():
    """The source file must not bypass verification with external attributes."""
    content = read_source()
    bypasses = re.findall(r'#\[verifier::(external|external_body)\]', content)
    assert len(bypasses) == 0, (
        f"Found {len(bypasses)} verification bypass attribute(s) in {SOURCE_FILE}. "
        "All functions must be verified."
    )


def test_required_functions_present():
    """The source file must contain the expected function signatures."""
    content = read_source()
    required = [
        "fn is_sorted",
        "fn merge",
        "fn merge_sort",
        "fn extend_from_idx",
        "fn binary_search",
        "fn lemma_to_multiset_distributes_over_add",
        "fn lemma_subrange_push",
        "fn lemma_subrange_add",
    ]
    for sig in required:
        assert sig in content, (
            f"Required function signature '{sig}' not found in {SOURCE_FILE}. "
            "Do not remove or rename the core functions."
        )


def test_verus_verification_succeeds():
    """Running verus on the source file must succeed with exit code 0."""
    result = subprocess.run(
        [VERUS_PATH, SOURCE_FILE],
        capture_output=True,
        text=True,
        timeout=240,
        env=VERUS_ENV,
    )
    if result.stdout:
        print("VERUS STDOUT:")
        print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.stderr:
        print("VERUS STDERR:")
        print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)

    assert result.returncode == 0, (
        f"Verus verification failed with exit code {result.returncode}.\n"
        f"stderr (last 1000 chars): {result.stderr[-1000:]}"
    )


def test_no_verification_errors_in_output():
    """Verus output must report 0 errors."""
    result = subprocess.run(
        [VERUS_PATH, SOURCE_FILE],
        capture_output=True,
        text=True,
        timeout=240,
        env=VERUS_ENV,
    )
    combined_output = result.stdout + result.stderr
    error_match = re.search(r'(\d+)\s+error', combined_output)
    if error_match:
        num_errors = int(error_match.group(1))
        assert num_errors == 0, (
            f"Verus reported {num_errors} error(s). Expected 0 errors.\n"
            f"Output: {combined_output[-1000:]}"
        )
