"""
Verification tests for OpenBao Transit secrets engine compliance remediation.

Tests verify the final system state against the organization's key compliance
policy by querying the live OpenBao API and inspecting evidence artifacts.
"""

import json
import base64
import time
import requests
import pytest

BAO_ADDR = "http://127.0.0.1:8200"
BAO_TOKEN = "test-root-token"
HEADERS = {"X-Vault-Token": BAO_TOKEN}


@pytest.fixture(scope="session", autouse=True)
def wait_for_openbao():
    """Wait for OpenBao to become available before running tests."""
    for i in range(30):
        try:
            r = requests.get(f"{BAO_ADDR}/v1/sys/health", timeout=2)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    pytest.fail("OpenBao did not become available within 30 seconds")


class TestTransitEngineState:
    """Verify Transit engine is properly mounted."""

    def test_transit_engine_enabled(self):
        r = requests.get(f"{BAO_ADDR}/v1/sys/mounts", headers=HEADERS)
        assert r.status_code == 200
        mounts = r.json().get("data", r.json())
        assert "transit/" in mounts, (
            f"Transit engine not found in mounts: {list(mounts.keys())}"
        )


class TestPrimaryEncKey:
    """Policy sections 1-5: primary-enc key compliance."""

    def _get_key_data(self):
        r = requests.get(
            f"{BAO_ADDR}/v1/transit/keys/primary-enc", headers=HEADERS
        )
        assert r.status_code == 200, "primary-enc key not found"
        return r.json()["data"]

    def test_key_type(self):
        data = self._get_key_data()
        assert data["type"] == "aes256-gcm96"

    def test_minimum_five_versions(self):
        """Section 1: at least 5 key versions via rotation."""
        data = self._get_key_data()
        assert data["latest_version"] >= 5, (
            f"latest_version={data['latest_version']}, need >= 5"
        )

    def test_exportable(self):
        """Section 3: must be exportable for DR."""
        data = self._get_key_data()
        assert data["exportable"] is True, "Key must be exportable"

    def test_rolling_decryption_window(self):
        """Section 2: min_decryption_version enforces 3-version window."""
        data = self._get_key_data()
        latest = data["latest_version"]
        min_dec = data["min_decryption_version"]
        # Window of 3 most recent versions: min_dec >= latest - 2
        assert min_dec >= latest - 2, (
            f"min_decryption_version={min_dec} too low for "
            f"latest_version={latest} (need >= {latest - 2})"
        )
        assert min_dec >= 3, (
            f"min_decryption_version={min_dec}, need >= 3"
        )

    def test_encryption_locked_to_latest(self):
        """Section 2: min_encryption_version must equal latest."""
        data = self._get_key_data()
        assert data["min_encryption_version"] == data["latest_version"], (
            f"min_encryption_version={data['min_encryption_version']}, "
            f"expected {data['latest_version']}"
        )

    def test_old_versions_trimmed(self):
        """Section 5: versions outside window must be purged."""
        data = self._get_key_data()
        keys = data["keys"]
        min_dec = data["min_decryption_version"]
        for v in range(1, min_dec):
            assert str(v) not in keys, (
                f"Version {v} should be trimmed (min_decryption={min_dec})"
            )
        # The min_decryption_version itself must exist
        assert str(min_dec) in keys, (
            f"Version {min_dec} should exist in keyring"
        )


class TestTenantSignKey:
    """Verify tenant-sign ECDSA key exists."""

    def test_key_exists_and_type(self):
        r = requests.get(
            f"{BAO_ADDR}/v1/transit/keys/tenant-sign", headers=HEADERS
        )
        assert r.status_code == 200, "tenant-sign key not found"
        assert r.json()["data"]["type"] == "ecdsa-p256"


class TestAuthHmacKey:
    """Section 6: auth-hmac key provisioning."""

    def test_key_exists_and_type(self):
        r = requests.get(
            f"{BAO_ADDR}/v1/transit/keys/auth-hmac", headers=HEADERS
        )
        assert r.status_code == 200, "auth-hmac key not found"
        assert r.json()["data"]["type"] == "hmac"


class TestImportedLegacyKey:
    """Section 7: BYOK-imported legacy key."""

    def test_key_exists_and_type(self):
        r = requests.get(
            f"{BAO_ADDR}/v1/transit/keys/imported-legacy", headers=HEADERS
        )
        assert r.status_code == 200, "imported-legacy key not found"
        data = r.json()["data"]
        assert data["type"] == "aes256-gcm96"

    def test_key_is_imported(self):
        r = requests.get(
            f"{BAO_ADDR}/v1/transit/keys/imported-legacy", headers=HEADERS
        )
        data = r.json()["data"]
        imported = data.get("imported", data.get("imported_key", None))
        assert imported is True, (
            f"Key should be marked as imported, "
            f"relevant fields: {[k for k in data if 'import' in k.lower()]}"
        )

    def test_key_material_matches_original(self):
        """Exported key must match the original hex file."""
        r = requests.get(
            f"{BAO_ADDR}/v1/transit/export/encryption-key/imported-legacy",
            headers=HEADERS,
        )
        assert r.status_code == 200, (
            f"Failed to export imported-legacy: {r.status_code} {r.text}"
        )
        exported_b64 = r.json()["data"]["keys"]["1"]
        exported_hex = base64.b64decode(exported_b64).hex()

        with open("/app/external_key.hex") as f:
            original_hex = f.read().strip()

        assert exported_hex == original_hex, (
            "Imported key material does not match original"
        )


class TestCiphertextEvidence:
    """Section 4: ciphertext currency evidence."""

    def _load_entries(self):
        with open("/app/results/ciphertexts.json") as f:
            return json.load(f)

    def test_file_exists_with_entries(self):
        entries = self._load_entries()
        assert len(entries) >= 3, f"Expected >= 3 entries, got {len(entries)}"

    def test_entries_have_required_fields(self):
        for i, e in enumerate(self._load_entries()):
            assert "plaintext" in e, f"Entry {i} missing 'plaintext'"
            assert "ciphertext" in e, f"Entry {i} missing 'ciphertext'"
            assert e["ciphertext"].startswith("vault:"), (
                f"Entry {i} ciphertext format invalid"
            )

    def test_ciphertexts_decrypt_to_correct_plaintext(self):
        for i, entry in enumerate(self._load_entries()):
            r = requests.post(
                f"{BAO_ADDR}/v1/transit/decrypt/primary-enc",
                headers=HEADERS,
                json={"ciphertext": entry["ciphertext"]},
            )
            assert r.status_code == 200, (
                f"Failed to decrypt entry {i}: {r.text}"
            )
            decrypted = base64.b64decode(
                r.json()["data"]["plaintext"]
            ).decode().strip()
            assert decrypted == entry["plaintext"].strip(), (
                f"Entry {i}: decrypted '{decrypted}' != '{entry['plaintext']}'"
            )

    def test_ciphertexts_at_current_version(self):
        """All ciphertexts must use the latest key version."""
        r = requests.get(
            f"{BAO_ADDR}/v1/transit/keys/primary-enc", headers=HEADERS
        )
        latest = r.json()["data"]["latest_version"]

        for i, entry in enumerate(self._load_entries()):
            ct = entry["ciphertext"]
            parts = ct.split(":")
            assert len(parts) >= 3, f"Entry {i}: malformed ciphertext"
            version = int(parts[1].lstrip("v"))
            assert version == latest, (
                f"Entry {i}: encrypted at v{version}, expected v{latest}"
            )


class TestSignatureEvidence:
    """Section 8: digital signature evidence."""

    def test_signature_file_structure(self):
        with open("/app/results/signature.json") as f:
            data = json.load(f)
        assert "input" in data, "Missing 'input' field"
        assert "signature" in data, "Missing 'signature' field"
        assert data["signature"].startswith("vault:"), "Invalid signature format"

    def test_signature_verifies(self):
        with open("/app/results/signature.json") as f:
            data = json.load(f)
        r = requests.post(
            f"{BAO_ADDR}/v1/transit/verify/tenant-sign",
            headers=HEADERS,
            json={"input": data["input"], "signature": data["signature"]},
        )
        assert r.status_code == 200, f"Verify request failed: {r.text}"
        assert r.json()["data"]["valid"] is True, "Signature invalid"


class TestHmacEvidence:
    """Section 6: HMAC evidence."""

    def test_hmac_file_structure(self):
        with open("/app/results/hmac_result.json") as f:
            data = json.load(f)
        assert "hmac" in data, "Missing 'hmac' field"
        assert data["hmac"].startswith("vault:v1:"), "Invalid HMAC format"

    def test_hmac_cross_verification(self):
        """Recompute HMAC and verify it matches."""
        with open("/app/results/hmac_result.json") as f:
            stored = json.load(f)

        with open("/app/data/hmac_data.txt") as f:
            raw = f.read().rstrip("\n")
        hmac_b64 = base64.b64encode(raw.encode()).decode()

        r = requests.post(
            f"{BAO_ADDR}/v1/transit/verify/auth-hmac",
            headers=HEADERS,
            json={"input": hmac_b64, "hmac": stored["hmac"]},
        )
        assert r.status_code == 200, f"HMAC verify failed: {r.text}"
        assert r.json()["data"]["valid"] is True, "HMAC verification failed"


class TestDatakeyEvidence:
    """Section 9: wrapped data encryption key."""

    def test_datakey_file_structure(self):
        with open("/app/results/datakey.json") as f:
            data = json.load(f)
        assert "ciphertext" in data, "Missing 'ciphertext' field"
        assert data["ciphertext"].startswith("vault:"), "Invalid format"


class TestImportVerificationEvidence:
    """Section 7: import verification evidence file."""

    def test_verification_file_matches_original(self):
        with open("/app/results/imported_key_verification.json") as f:
            data = json.load(f)
        assert "exported_hex" in data, "Missing 'exported_hex' field"

        with open("/app/external_key.hex") as f:
            original_hex = f.read().strip()

        assert data["exported_hex"] == original_hex, (
            "Verification file hex does not match original key"
        )
