
import json
import os

import pytest
from Crypto.PublicKey import RSA
from Crypto.Util.number import bytes_to_long


@pytest.fixture
def assessment():
    with open("/app/assessment.json", "r") as f:
        return json.load(f)


def test_assessment_file_exists():
    """assessment.json must exist."""
    assert os.path.isfile("/app/assessment.json"), "/app/assessment.json not found"


def test_assessment_is_valid_json():
    """assessment.json must be parseable JSON with required keys."""
    with open("/app/assessment.json", "r") as f:
        data = json.load(f)
    required = {
        "compromised_instance",
        "attack_vector",
        "decrypted_message",
        "secure_instances",
        "remediation_verdict",
        "minimum_secure_rounds",
    }
    assert required.issubset(data.keys()), (
        f"Missing keys: {required - set(data.keys())}"
    )


def test_compromised_instance(assessment):
    """The solver must identify the correct compromised PRNG instance."""
    assert assessment["compromised_instance"] == "prng-7a3f", (
        f"Expected prng-7a3f, got {assessment['compromised_instance']}"
    )


def test_secure_instances(assessment):
    """All three secure instances must be correctly identified."""
    secure = set(assessment["secure_instances"])
    expected = {"prng-b1e2", "prng-c4d9", "prng-d5e8"}
    assert secure == expected, (
        f"Expected secure instances {expected}, got {secure}"
    )


def test_decrypted_message_proves_compromise(assessment):
    """
    Core verification: encrypt the claimed plaintext with the public key.
    If it matches the stored ciphertext, the solver truly recovered the key.
    No hardcoded flag — pure mathematical round-trip.
    """
    msg = assessment["decrypted_message"]
    assert len(msg) > 0, "decrypted_message is empty"
    msg_int = bytes_to_long(msg.encode("ascii"))

    with open("/app/pubkey.der", "rb") as f:
        rsa_key = RSA.import_key(f.read())

    with open("/app/intercepted.enc", "r") as f:
        ct = int(f.read().strip(), 16)

    assert pow(msg_int, rsa_key.e, rsa_key.n) == ct, (
        "Encrypting the claimed plaintext does not reproduce the ciphertext — "
        "the recovered key is incorrect."
    )


def test_remediation_verdict(assessment):
    """The proposed whiten_rounds=3 is sufficient; verdict must be ACCEPT."""
    verdict = assessment["remediation_verdict"].upper().strip()
    assert verdict == "ACCEPT", (
        f"Expected ACCEPT, got {verdict}. "
        "whiten_rounds=3 >= 1 (minimum), so the proposal is sufficient."
    )


def test_minimum_secure_rounds(assessment):
    """
    SHA-512 provides preimage resistance. A single round of whitening
    destroys the linear algebraic structure of LCG outputs, making
    state recovery infeasible. The minimum secure value is 1.
    """
    val = assessment["minimum_secure_rounds"]
    assert val == 1, (
        f"Expected minimum_secure_rounds=1, got {val}. "
        "One round of SHA-512 whitening prevents LCG state recovery."
    )


def test_attack_vector_description(assessment):
    """The attack vector must be a substantive description."""
    vec = assessment["attack_vector"]
    assert isinstance(vec, str) and len(vec) >= 20, (
        "attack_vector must be a meaningful description (>= 20 chars)"
    )


def test_flag_file_exists():
    """The agent must also write /app/flag.txt."""
    assert os.path.isfile("/app/flag.txt"), "/app/flag.txt not found"


def test_flag_matches_assessment():
    """flag.txt must match the decrypted_message in assessment.json."""
    with open("/app/assessment.json", "r") as f:
        data = json.load(f)
    with open("/app/flag.txt", "r") as f:
        flag = f.read().strip()
    assert flag == data["decrypted_message"].strip(), (
        "flag.txt does not match assessment.json decrypted_message"
    )
