
import json
import os
import pytest

VERIFICATION_PATH = "/var/lib/task/.verification.json"


@pytest.fixture(scope="module")
def verification():
    """Load build-time verification data (randomized per instance)."""
    assert os.path.exists(VERIFICATION_PATH), (
        "Verification file not found at %s" % VERIFICATION_PATH
    )
    with open(VERIFICATION_PATH) as f:
        return json.load(f)


def test_token(verification):
    """Verify the extracted security token matches the randomized build value."""
    path = "/app/output/token.txt"
    assert os.path.exists(path), "token.txt not found at /app/output/token.txt"
    with open(path) as f:
        token = f.read().strip()
    assert token == verification["token"], (
        "Incorrect token: %r" % token
    )


def test_manifest(verification):
    """Verify the manifest JSON structure and values."""
    path = "/app/output/manifest.json"
    assert os.path.exists(path), "manifest.json not found at /app/output/manifest.json"
    with open(path) as f:
        m = json.load(f)

    assert m["num_files"] == verification["num_files"], (
        "Expected %d files, got %d" % (verification["num_files"], m["num_files"])
    )
    assert m["encrypted_count"] == verification["encrypted_count"], (
        "Expected %d encrypted entries, got %d"
        % (verification["encrypted_count"], m["encrypted_count"])
    )

    expected_names = sorted(verification["file_names"])
    actual_names = sorted(m["file_names"])
    assert actual_names == expected_names, (
        "File names mismatch:\n  expected: %s\n  actual:   %s"
        % (expected_names, actual_names)
    )


def test_credentials(verification):
    """Verify decrypted credentials content."""
    path = "/app/output/credentials.txt"
    assert os.path.exists(path), "credentials.txt not found at /app/output/credentials.txt"
    with open(path) as f:
        content = f.read()

    for line in verification["credential_lines"]:
        assert line in content, "Missing credential line: %r" % line
