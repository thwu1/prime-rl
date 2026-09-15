
import hashlib
import os
import json

EXPECTED_HASH = "c1375201abaeb8e8923ffc7134fd319f149b59b370c70c5fce721e18a7cc6a60"
SECRET_FILE = "/app/secret.txt"
MANIFEST_FILE = "/app/vault_manifest.json"


def test_secret_file_exists():
    """The recovered secret file must exist."""
    assert os.path.isfile(SECRET_FILE), (
        f"{SECRET_FILE} does not exist. "
        "Write the recovered master secret as a lowercase hex string to this file."
    )


def test_secret_format():
    """The secret must be a valid lowercase hex string with no prefix."""
    with open(SECRET_FILE) as f:
        content = f.read().strip()
    assert len(content) > 0, "secret.txt is empty"
    assert not content.startswith("0x"), "Secret should not have 0x prefix"
    assert all(c in "0123456789abcdef" for c in content), (
        "Secret must be a lowercase hex string"
    )


def test_secret_correct():
    """The recovered secret must match the expected SHA-256 hash."""
    with open(SECRET_FILE) as f:
        secret_hex = f.read().strip()
    computed_hash = hashlib.sha256(secret_hex.encode()).hexdigest()
    assert computed_hash == EXPECTED_HASH, (
        f"Secret hash mismatch: got {computed_hash}, expected {EXPECTED_HASH}"
    )


def test_secret_in_field():
    """Verify the secret is consistent with the Shamir scheme parameters."""
    with open(SECRET_FILE) as f:
        secret_hex = f.read().strip()
    secret = int(secret_hex, 16)

    with open(MANIFEST_FILE) as f:
        data = json.load(f)

    prime = int(data["sss_prime"])
    assert 0 < secret < prime, (
        f"Secret {secret} is out of range for field F_{prime}"
    )
