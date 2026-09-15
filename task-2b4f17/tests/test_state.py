"""Verify firmware crypto assessment and hardening results."""

import hashlib
import json
import os
import struct
import subprocess

import pytest


# --------------- FWPK parsing helper ---------------

def parse_fwpk(data: bytes) -> dict:
    """Parse FWPK binary container, return {name: {offset, size, flags, data}}."""
    assert data[:4] == b"FWPK", f"Bad magic: {data[:4]}"
    _version, num_sections = struct.unpack_from("<HH", data, 4)
    sections = {}
    for i in range(num_sections):
        base = 12 + i * 32
        raw_name = data[base:base + 16]
        name = raw_name.rstrip(b"\x00").decode("ascii")
        offset, size, flags = struct.unpack_from("<III", data, base + 16)
        sections[name] = {
            "offset": offset,
            "size": size,
            "flags": flags,
            "data": data[offset:offset + size],
        }
    return sections


# =============== Phase 1: Recovered diagnostic data ===============

class TestRecoveredData:

    def test_file_exists(self):
        assert os.path.exists("/app/recovered_data.txt"), \
            "recovered_data.txt not found"

    def test_sha256_matches(self):
        with open("/app/.diag_verify") as f:
            expected = f.read().strip()
        with open("/app/recovered_data.txt", "rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
        assert actual == expected, \
            f"SHA256 mismatch: expected {expected}, got {actual}"

    def test_valid_utf8(self):
        with open("/app/recovered_data.txt", "rb") as f:
            f.read().decode("utf-8")

    def test_structure_markers(self):
        with open("/app/recovered_data.txt") as f:
            text = f.read()
        for marker in [
            "VEHICLE DIAGNOSTIC DATABASE",
            "DIAGNOSTIC RECORD",
            "SECURITY AUDIT SECTION",
            "END OF DIAGNOSTIC DATABASE",
        ]:
            assert marker in text, f"Missing marker: {marker}"

    def test_all_seven_records(self):
        with open("/app/recovered_data.txt") as f:
            text = f.read()
        for i in range(1, 8):
            tag = f"DIAGNOSTIC RECORD {i:03d}"
            assert tag in text, f"{tag} not found"


# =============== Phase 1: Security token ===============

class TestSecurityToken:

    def test_file_exists(self):
        assert os.path.exists("/app/security_token.txt"), \
            "security_token.txt not found"

    def test_hash_matches(self):
        with open("/app/.token_verify") as f:
            expected = f.read().strip()
        with open("/app/security_token.txt") as f:
            token = f.read().strip()
        assert hashlib.sha256(token.encode()).hexdigest() == expected, \
            "Token hash mismatch"

    def test_format(self):
        with open("/app/security_token.txt") as f:
            token = f.read().strip()
        assert token.startswith("DIAG-"), \
            f"Token should start with 'DIAG-', got: {token[:10]}"
        assert len(token) == 41, \
            f"Token length should be 41, got {len(token)}"


# =============== Phase 1: RSA private key ===============

class TestRSAPrivateKey:

    def test_file_exists(self):
        assert os.path.exists("/app/rsa_private.pem"), \
            "rsa_private.pem not found"

    def test_openssl_check(self):
        """Verify PEM is a mathematically consistent RSA private key."""
        r = subprocess.run(
            ["openssl", "rsa", "-in", "/app/rsa_private.pem",
             "-check", "-noout"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"openssl rsa -check failed: {r.stderr}"

    def test_signature_matches(self):
        """Verify the key produces the expected deterministic signature."""
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding as ap

        with open("/app/rsa_private.pem", "rb") as f:
            privkey = serialization.load_pem_private_key(f.read(), password=None)

        msg = b"fwpk-key-verification-challenge-v3"
        sig = privkey.sign(msg, ap.PKCS1v15(), hashes.SHA256())

        with open("/app/.sig_verify", "rb") as f:
            expected_sig = f.read()

        assert sig == expected_sig, "RSA signature mismatch"

    def test_key_matches_pubkey(self):
        """Verify the private key corresponds to the firmware public key."""
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding as ap

        with open("/app/rsa_private.pem", "rb") as f:
            privkey = serialization.load_pem_private_key(f.read(), password=None)
        with open("/app/.pubkey_der", "rb") as f:
            pubkey = serialization.load_der_public_key(f.read())

        msg = b"fwpk-key-verification-challenge-v3"
        sig = privkey.sign(msg, ap.PKCS1v15(), hashes.SHA256())
        # verify() raises InvalidSignature on mismatch
        pubkey.verify(sig, msg, ap.PKCS1v15(), hashes.SHA256())


# =============== Phase 2: Hardened firmware ===============

class TestHardenedFirmware:

    def test_file_exists(self):
        assert os.path.exists("/app/hardened_firmware.bin"), \
            "hardened_firmware.bin not found"

    def test_valid_fwpk_format(self):
        """Hardened container must be a valid FWPK with all required sections."""
        with open("/app/hardened_firmware.bin", "rb") as f:
            data = f.read()
        assert data[:4] == b"FWPK", f"Bad magic: {data[:4]}"
        sections = parse_fwpk(data)
        required = {"manifest", "rsa_pubkey", "wrapped_aeskey",
                     "partition_0", "partition_1", "partition_2"}
        assert required.issubset(sections.keys()), \
            f"Missing sections: {required - sections.keys()}"

    def test_rsa_2048_pubkey_embedded(self):
        """Container must embed an RSA-2048 public key."""
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        with open("/app/hardened_firmware.bin", "rb") as f:
            sections = parse_fwpk(f.read())
        pubkey = load_der_public_key(sections["rsa_pubkey"]["data"])
        assert pubkey.key_size == 2048, \
            f"Expected RSA-2048, got RSA-{pubkey.key_size}"

    def test_pubkey_matches_provided(self):
        """Embedded pubkey must match /app/hardened_pubkey.pem."""
        from cryptography.hazmat.primitives.serialization import (
            load_der_public_key, load_pem_public_key,
        )
        with open("/app/hardened_firmware.bin", "rb") as f:
            sections = parse_fwpk(f.read())
        embedded = load_der_public_key(sections["rsa_pubkey"]["data"])
        with open("/app/hardened_pubkey.pem", "rb") as f:
            provided = load_pem_public_key(f.read())
        assert embedded.public_numbers().n == provided.public_numbers().n, \
            "Embedded pubkey does not match hardened_pubkey.pem"

    def test_oaep_unwrap_succeeds(self):
        """AES key must be wrapped with RSA-OAEP SHA-256 (not PKCS1v15)."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric import padding as ap
        from cryptography.hazmat.primitives import hashes as h
        with open("/app/hardened_firmware.bin", "rb") as f:
            sections = parse_fwpk(f.read())
        with open("/app/.hardened_privkey.pem", "rb") as f:
            privkey = load_pem_private_key(f.read(), password=None)
        aes_key = privkey.decrypt(
            sections["wrapped_aeskey"]["data"],
            ap.OAEP(
                mgf=ap.MGF1(algorithm=h.SHA256()),
                algorithm=h.SHA256(),
                label=None,
            ),
        )
        assert len(aes_key) == 32, f"AES key should be 32 bytes, got {len(aes_key)}"

    def test_deterministic_aes_key(self):
        """AES key must be derived from the diagnostic data hash."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric import padding as ap
        from cryptography.hazmat.primitives import hashes as h
        with open("/app/hardened_firmware.bin", "rb") as f:
            sections = parse_fwpk(f.read())
        with open("/app/.hardened_privkey.pem", "rb") as f:
            privkey = load_pem_private_key(f.read(), password=None)
        aes_key = privkey.decrypt(
            sections["wrapped_aeskey"]["data"],
            ap.OAEP(
                mgf=ap.MGF1(algorithm=h.SHA256()),
                algorithm=h.SHA256(),
                label=None,
            ),
        )
        with open("/app/.diag_verify") as f:
            diag_hash = f.read().strip()
        expected = hashlib.sha256(
            ("hardened-session-key-" + diag_hash).encode()
        ).digest()
        assert aes_key == expected, "AES key derivation mismatch"

    def test_gcm_decryption_and_integrity(self):
        """Partitions must use AES-256-GCM; decrypted data must match original."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric import padding as ap
        from cryptography.hazmat.primitives import hashes as h
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        with open("/app/hardened_firmware.bin", "rb") as f:
            sections = parse_fwpk(f.read())
        with open("/app/.hardened_privkey.pem", "rb") as f:
            privkey = load_pem_private_key(f.read(), password=None)
        aes_key = privkey.decrypt(
            sections["wrapped_aeskey"]["data"],
            ap.OAEP(
                mgf=ap.MGF1(algorithm=h.SHA256()),
                algorithm=h.SHA256(),
                label=None,
            ),
        )
        aesgcm = AESGCM(aes_key)
        parts = []
        for i in range(3):
            blob = sections[f"partition_{i}"]["data"]
            nonce = blob[:12]
            ct_tag = blob[12:]
            pt = aesgcm.decrypt(nonce, ct_tag, None)
            parts.append(pt)
        recovered = b"".join(parts)
        with open("/app/.diag_verify") as f:
            expected_hash = f.read().strip()
        actual_hash = hashlib.sha256(recovered).hexdigest()
        assert actual_hash == expected_hash, \
            f"Decrypted data hash mismatch: {actual_hash} != {expected_hash}"

    def test_correct_nonce_derivation(self):
        """GCM nonces must be SHA-256 derived per partition index."""
        with open("/app/hardened_firmware.bin", "rb") as f:
            sections = parse_fwpk(f.read())
        for i in range(3):
            blob = sections[f"partition_{i}"]["data"]
            nonce = blob[:12]
            expected = hashlib.sha256(f"gcm-nonce-{i}".encode()).digest()[:12]
            assert nonce == expected, f"Nonce mismatch for partition {i}"

    def test_manifest_indicates_hardened_crypto(self):
        """Manifest JSON must reflect the hardened crypto primitives."""
        with open("/app/hardened_firmware.bin", "rb") as f:
            sections = parse_fwpk(f.read())
        manifest = json.loads(sections["manifest"]["data"].decode("utf-8"))
        crypto = manifest.get("crypto", {})
        key_wrap = crypto.get("key_wrap", "").upper()
        data_cipher = crypto.get("data_cipher", "").upper()
        assert "OAEP" in key_wrap, \
            f"Manifest key_wrap must indicate OAEP, got: {crypto.get('key_wrap')}"
        assert "GCM" in data_cipher, \
            f"Manifest data_cipher must indicate GCM, got: {crypto.get('data_cipher')}"
