
import hashlib
import json
import os

import pytest

# ── Ground truth ────────────────────────────────────────────────────────────

VULNERABILITY_MAP = {
    "cert_01": True,
    "cert_02": False,
    "cert_03": True,
    "cert_04": True,
    "cert_05": False,
    "cert_06": True,
    "cert_07": True,
    "cert_08": False,
    "cert_09": True,
    "cert_10": False,
}

# Expected decrypted plaintexts for each vulnerable key.
# m = int(sha256("CHALLENGE_<cert_id>").hexdigest(), 16) % 2**64
EXPECTED_PLAINTEXTS = {
    "cert_01": "13710377875005162203",
    "cert_03": "2982174593235590253",
    "cert_04": "16835070263403262601",
    "cert_06": "13395793426315689293",
    "cert_07": "6767246546427846054",
    "cert_09": "7196149334037559328",
}

ALL_KEY_IDS = sorted(VULNERABILITY_MAP.keys())
VULNERABLE_IDS = sorted(k for k, v in VULNERABILITY_MAP.items() if v)
SAFE_IDS = sorted(k for k, v in VULNERABILITY_MAP.items() if not v)


def _load_json(path):
    assert os.path.exists(path), f"Required output file {path} does not exist"
    with open(path) as f:
        return json.load(f)


# ── Audit classification tests ──────────────────────────────────────────────


class TestAuditClassification:
    """Verify the agent correctly classified every key."""

    def setup_method(self):
        self.audit = _load_json("/app/results/audit.json")

    def test_all_keys_present(self):
        """Every key ID must appear in the audit output."""
        for key_id in ALL_KEY_IDS:
            assert key_id in self.audit, f"{key_id} missing from audit.json"

    @pytest.mark.parametrize("key_id", VULNERABLE_IDS)
    def test_vulnerable_keys_detected(self, key_id):
        """Each genuinely vulnerable key must be flagged."""
        entry = self.audit.get(key_id, {})
        vuln = entry if isinstance(entry, bool) else entry.get("vulnerable")
        assert vuln is True, (
            f"{key_id} is vulnerable but was not flagged (got {entry})"
        )

    @pytest.mark.parametrize("key_id", SAFE_IDS)
    def test_safe_keys_not_flagged(self, key_id):
        """Secure keys must not be falsely flagged."""
        entry = self.audit.get(key_id, {})
        vuln = entry if isinstance(entry, bool) else entry.get("vulnerable")
        assert vuln is False, (
            f"{key_id} is secure but was flagged as vulnerable (got {entry})"
        )


# ── Challenge decryption tests ──────────────────────────────────────────────


class TestChallengeDecryption:
    """Verify the agent decrypted challenge ciphertexts for all broken keys."""

    def setup_method(self):
        self.decrypted = _load_json("/app/results/decrypted.json")

    @pytest.mark.parametrize("key_id", VULNERABLE_IDS)
    def test_vulnerable_key_decrypted(self, key_id):
        """Each vulnerable key's challenge must be decrypted."""
        assert key_id in self.decrypted, (
            f"{key_id} is vulnerable but no decrypted plaintext was provided"
        )

    @pytest.mark.parametrize("key_id", VULNERABLE_IDS)
    def test_plaintext_correct(self, key_id):
        """Decrypted plaintext must match the expected value."""
        expected = EXPECTED_PLAINTEXTS[key_id]
        actual = str(self.decrypted.get(key_id, ""))
        assert actual == expected, (
            f"{key_id}: expected plaintext {expected}, got {actual}"
        )

    def test_independent_plaintext_derivation(self):
        """Cross-check: recompute expected plaintexts from scratch."""
        for key_id in VULNERABLE_IDS:
            m = int(
                hashlib.sha256(f"CHALLENGE_{key_id}".encode()).hexdigest(), 16
            ) % (2**64)
            expected = str(m)
            actual = str(self.decrypted.get(key_id, ""))
            assert actual == expected, (
                f"{key_id}: independent derivation expected {expected}, got {actual}"
            )
