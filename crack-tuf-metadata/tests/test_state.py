#!/usr/bin/env python3
"""
Verification tests for the multi-key TUF repository compromise.
Validates recovered private keys (via openssl), forged repo structure,
per-role signature correctness, metadata chain, and target integrity.
"""


import json
import hashlib
import os
import base64
import subprocess
import pytest

ORIGINAL_REPO = "/app/repository"
FORGED_REPO = "/app/forged_repo"
PAYLOAD_PATH = "/app/payload.bin"
KEYS_DIR = "/app/recovered_keys"


# ======================== Utilities ========================


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def parse_der_tag_length(data, offset):
    """Parse a DER tag and length field, return (tag, length, new_offset)."""
    tag = data[offset]
    offset += 1
    length = data[offset]
    offset += 1
    if length & 0x80:
        num_bytes = length & 0x7F
        length = int.from_bytes(data[offset:offset + num_bytes], "big")
        offset += num_bytes
    return tag, length, offset


def parse_spki_pubkey(der):
    """Extract (n, e) from SubjectPublicKeyInfo DER (BEGIN PUBLIC KEY)."""
    tag, length, offset = parse_der_tag_length(der, 0)
    assert tag == 0x30
    # AlgorithmIdentifier SEQUENCE - skip
    tag, alg_len, alg_offset = parse_der_tag_length(der, offset)
    assert tag == 0x30
    offset = alg_offset + alg_len
    # BIT STRING
    tag, bs_len, offset = parse_der_tag_length(der, offset)
    assert tag == 0x03
    assert der[offset] == 0  # unused bits
    offset += 1
    # RSAPublicKey SEQUENCE
    tag, seq_len, offset = parse_der_tag_length(der, offset)
    assert tag == 0x30
    # INTEGER n
    tag, n_len, offset = parse_der_tag_length(der, offset)
    assert tag == 0x02
    n = int.from_bytes(der[offset:offset + n_len], "big")
    offset += n_len
    # INTEGER e
    tag, e_len, offset = parse_der_tag_length(der, offset)
    assert tag == 0x02
    e = int.from_bytes(der[offset:offset + e_len], "big")
    return n, e


def parse_pkcs1_pubkey(der):
    """Extract (n, e) from PKCS#1 RSAPublicKey DER (BEGIN RSA PUBLIC KEY)."""
    tag, length, offset = parse_der_tag_length(der, 0)
    assert tag == 0x30
    # INTEGER n
    tag, n_len, offset = parse_der_tag_length(der, offset)
    assert tag == 0x02
    n = int.from_bytes(der[offset:offset + n_len], "big")
    offset += n_len
    # INTEGER e
    tag, e_len, offset = parse_der_tag_length(der, offset)
    assert tag == 0x02
    e = int.from_bytes(der[offset:offset + e_len], "big")
    return n, e


def extract_pubkey_from_key_obj(key_obj):
    """Extract (n, e) from a TUF key object, auto-detecting PEM format."""
    pem = key_obj["keyval"]["public"]
    lines = pem.strip().split("\n")
    b64 = "".join(l for l in lines if not l.startswith("-----"))
    der = base64.b64decode(b64)

    if "BEGIN RSA PUBLIC KEY" in pem:
        return parse_pkcs1_pubkey(der)
    else:
        return parse_spki_pubkey(der)


def get_role_key_info():
    """Parse root.json to get key info and role-key assignments."""
    with open(f"{ORIGINAL_REPO}/root.json") as f:
        root = json.load(f)

    roles = root["signed"]["roles"]
    keys = root["signed"]["keys"]

    targets_keyid = roles["targets"]["keyids"][0]
    snapshot_keyid = roles["snapshot"]["keyids"][0]
    timestamp_keyid = roles["timestamp"]["keyids"][0]

    targets_n, targets_e = extract_pubkey_from_key_obj(keys[targets_keyid])
    timestamp_n, timestamp_e = extract_pubkey_from_key_obj(keys[timestamp_keyid])

    return {
        "targets": {"keyid": targets_keyid, "n": targets_n, "e": targets_e},
        "snapshot": {"keyid": snapshot_keyid, "n": targets_n, "e": targets_e},
        "timestamp": {"keyid": timestamp_keyid, "n": timestamp_n, "e": timestamp_e},
    }


def verify_pkcs1v15_sha256(message, signature_hex, n, e):
    """Verify an RSASSA-PKCS1-v1_5 SHA-256 signature."""
    k = (n.bit_length() + 7) // 8
    sig_bytes = bytes.fromhex(signature_hex)
    assert len(sig_bytes) == k, f"Signature length {len(sig_bytes)} != key length {k}"

    s_int = int.from_bytes(sig_bytes, "big")
    m_int = pow(s_int, e, n)
    em = m_int.to_bytes(k, "big")

    h = hashlib.sha256(message).digest()
    digest_info = (
        b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01"
        b"\x65\x03\x04\x02\x01\x05\x00\x04\x20"
    ) + h
    expected_suffix = b"\x00" + digest_info

    assert em[0:2] == b"\x00\x01", "Invalid PKCS1v15 padding header"
    sep_idx = em.index(b"\x00", 2)
    assert sep_idx >= 10, "PS too short"
    assert em[2:sep_idx] == b"\xff" * (sep_idx - 2), "Invalid PS padding"
    assert em[sep_idx:] == expected_suffix, "DigestInfo mismatch"


def verify_metadata_signature(metadata, n, e, keyid):
    """Verify that a TUF metadata dict has a valid signature for the given key."""
    signed_bytes = canonical_json(metadata["signed"])
    matching = [s for s in metadata["signatures"] if s["keyid"] == keyid]
    assert len(matching) >= 1, f"No signature found for keyid {keyid[:16]}..."
    verify_pkcs1v15_sha256(signed_bytes, matching[0]["sig"], n, e)


# ======================== Tests: Recovered Keys ========================


class TestRecoveredKeys:
    def test_targets_key_pem_exists(self):
        assert os.path.isfile(f"{KEYS_DIR}/targets_key.pem"), \
            "targets_key.pem not found"

    def test_timestamp_key_pem_exists(self):
        assert os.path.isfile(f"{KEYS_DIR}/timestamp_key.pem"), \
            "timestamp_key.pem not found"

    def test_targets_key_openssl_check(self):
        result = subprocess.run(
            ["openssl", "rsa", "-in", f"{KEYS_DIR}/targets_key.pem",
             "-check", "-noout"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"openssl rsa -check failed for targets_key.pem: {result.stderr}"

    def test_timestamp_key_openssl_check(self):
        result = subprocess.run(
            ["openssl", "rsa", "-in", f"{KEYS_DIR}/timestamp_key.pem",
             "-check", "-noout"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"openssl rsa -check failed for timestamp_key.pem: {result.stderr}"

    def test_targets_key_modulus_matches_public(self):
        """Private key modulus must match the targets public key in root.json."""
        result = subprocess.run(
            ["openssl", "rsa", "-in", f"{KEYS_DIR}/targets_key.pem",
             "-modulus", "-noout"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"openssl failed: {result.stderr}"
        mod_hex = result.stdout.strip().split("=")[1]
        priv_n = int(mod_hex, 16)

        role_keys = get_role_key_info()
        assert priv_n == role_keys["targets"]["n"], \
            "targets_key.pem modulus does not match the targets public key"

    def test_timestamp_key_modulus_matches_public(self):
        """Private key modulus must match the timestamp public key in root.json."""
        result = subprocess.run(
            ["openssl", "rsa", "-in", f"{KEYS_DIR}/timestamp_key.pem",
             "-modulus", "-noout"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"openssl failed: {result.stderr}"
        mod_hex = result.stdout.strip().split("=")[1]
        priv_n = int(mod_hex, 16)

        role_keys = get_role_key_info()
        assert priv_n == role_keys["timestamp"]["n"], \
            "timestamp_key.pem modulus does not match the timestamp public key"


# ======================== Tests: Forged Repo Structure ========================


class TestForgedRepoStructure:
    def test_forged_repo_exists(self):
        assert os.path.isdir(FORGED_REPO), f"{FORGED_REPO} does not exist"

    def test_root_json_exists(self):
        assert os.path.isfile(f"{FORGED_REPO}/root.json")

    def test_targets_json_exists(self):
        assert os.path.isfile(f"{FORGED_REPO}/targets.json")

    def test_snapshot_json_exists(self):
        assert os.path.isfile(f"{FORGED_REPO}/snapshot.json")

    def test_timestamp_json_exists(self):
        assert os.path.isfile(f"{FORGED_REPO}/timestamp.json")

    def test_firmware_v2_target_file_exists(self):
        assert os.path.isfile(f"{FORGED_REPO}/targets/firmware_v2.0.bin")


# ======================== Tests: Root Metadata ========================


class TestRootMetadata:
    def test_root_unchanged(self):
        with open(f"{ORIGINAL_REPO}/root.json") as f:
            original = json.load(f)
        with open(f"{FORGED_REPO}/root.json") as f:
            forged = json.load(f)
        assert original == forged, "root.json must be identical to original"


# ======================== Tests: Targets Metadata ========================


class TestTargetsMetadata:
    def test_targets_signature_valid(self):
        role_keys = get_role_key_info()
        with open(f"{FORGED_REPO}/targets.json") as f:
            targets = json.load(f)
        verify_metadata_signature(
            targets,
            role_keys["targets"]["n"],
            role_keys["targets"]["e"],
            role_keys["targets"]["keyid"]
        )

    def test_firmware_v2_listed(self):
        with open(f"{FORGED_REPO}/targets.json") as f:
            targets = json.load(f)
        assert "firmware_v2.0.bin" in targets["signed"]["targets"], \
            "firmware_v2.0.bin not found in targets metadata"

    def test_firmware_v2_hash_correct(self):
        with open(f"{FORGED_REPO}/targets.json") as f:
            targets = json.load(f)
        with open(PAYLOAD_PATH, "rb") as f:
            payload = f.read()
        info = targets["signed"]["targets"]["firmware_v2.0.bin"]
        assert info["hashes"]["sha256"] == sha256_hex(payload), "SHA-256 mismatch"
        assert info["length"] == len(payload), "Length mismatch"

    def test_firmware_v2_file_matches_payload(self):
        with open(PAYLOAD_PATH, "rb") as f:
            payload = f.read()
        with open(f"{FORGED_REPO}/targets/firmware_v2.0.bin", "rb") as f:
            target_file = f.read()
        assert payload == target_file, "Target file content != payload"

    def test_original_targets_preserved(self):
        with open(f"{ORIGINAL_REPO}/targets.json") as f:
            original = json.load(f)
        with open(f"{FORGED_REPO}/targets.json") as f:
            forged = json.load(f)
        for name, info in original["signed"]["targets"].items():
            assert name in forged["signed"]["targets"], \
                f"Original target '{name}' missing"
            assert forged["signed"]["targets"][name]["hashes"]["sha256"] \
                == info["hashes"]["sha256"], \
                f"Hash for '{name}' was altered"

    def test_targets_version_incremented(self):
        with open(f"{ORIGINAL_REPO}/targets.json") as f:
            original = json.load(f)
        with open(f"{FORGED_REPO}/targets.json") as f:
            forged = json.load(f)
        assert forged["signed"]["version"] > original["signed"]["version"]

    def test_targets_type_field(self):
        with open(f"{FORGED_REPO}/targets.json") as f:
            targets = json.load(f)
        assert targets["signed"]["_type"] == "targets"


# ======================== Tests: Snapshot Metadata ========================


class TestSnapshotMetadata:
    def test_snapshot_signature_valid(self):
        role_keys = get_role_key_info()
        with open(f"{FORGED_REPO}/snapshot.json") as f:
            snapshot = json.load(f)
        verify_metadata_signature(
            snapshot,
            role_keys["snapshot"]["n"],
            role_keys["snapshot"]["e"],
            role_keys["snapshot"]["keyid"]
        )

    def test_snapshot_references_targets_version(self):
        with open(f"{FORGED_REPO}/targets.json") as f:
            targets = json.load(f)
        with open(f"{FORGED_REPO}/snapshot.json") as f:
            snapshot = json.load(f)
        assert snapshot["signed"]["meta"]["targets.json"]["version"] == \
            targets["signed"]["version"]

    def test_snapshot_version_incremented(self):
        with open(f"{ORIGINAL_REPO}/snapshot.json") as f:
            original = json.load(f)
        with open(f"{FORGED_REPO}/snapshot.json") as f:
            forged = json.load(f)
        assert forged["signed"]["version"] > original["signed"]["version"]

    def test_snapshot_type_field(self):
        with open(f"{FORGED_REPO}/snapshot.json") as f:
            snapshot = json.load(f)
        assert snapshot["signed"]["_type"] == "snapshot"


# ======================== Tests: Timestamp Metadata ========================


class TestTimestampMetadata:
    def test_timestamp_signature_valid(self):
        role_keys = get_role_key_info()
        with open(f"{FORGED_REPO}/timestamp.json") as f:
            timestamp = json.load(f)
        verify_metadata_signature(
            timestamp,
            role_keys["timestamp"]["n"],
            role_keys["timestamp"]["e"],
            role_keys["timestamp"]["keyid"]
        )

    def test_timestamp_references_snapshot_version(self):
        with open(f"{FORGED_REPO}/snapshot.json") as f:
            snapshot = json.load(f)
        with open(f"{FORGED_REPO}/timestamp.json") as f:
            timestamp = json.load(f)
        assert timestamp["signed"]["meta"]["snapshot.json"]["version"] == \
            snapshot["signed"]["version"]

    def test_timestamp_type_field(self):
        with open(f"{FORGED_REPO}/timestamp.json") as f:
            timestamp = json.load(f)
        assert timestamp["signed"]["_type"] == "timestamp"


# ======================== Tests: Multi-Key Correctness ========================


class TestMultiKeyCorrectness:
    def test_different_keys_assigned_to_roles(self):
        """root.json assigns distinct keys to targets vs timestamp."""
        role_keys = get_role_key_info()
        assert role_keys["targets"]["keyid"] != role_keys["timestamp"]["keyid"], \
            "Targets and timestamp must use different keys"

    def test_targets_signed_by_targets_key_not_timestamp(self):
        """targets.json signature must use the targets keyid."""
        role_keys = get_role_key_info()
        with open(f"{FORGED_REPO}/targets.json") as f:
            targets = json.load(f)
        sig_keyids = {s["keyid"] for s in targets["signatures"]}
        assert role_keys["targets"]["keyid"] in sig_keyids, \
            "targets.json must be signed by the targets key"

    def test_timestamp_signed_by_timestamp_key_not_targets(self):
        """timestamp.json signature must use the timestamp keyid."""
        role_keys = get_role_key_info()
        with open(f"{FORGED_REPO}/timestamp.json") as f:
            timestamp = json.load(f)
        sig_keyids = {s["keyid"] for s in timestamp["signatures"]}
        assert role_keys["timestamp"]["keyid"] in sig_keyids, \
            "timestamp.json must be signed by the timestamp key"


# ======================== Tests: Metadata Chain Consistency ========================


class TestMetadataChainConsistency:
    def test_all_metadata_has_valid_structure(self):
        for name in ["root.json", "targets.json", "snapshot.json", "timestamp.json"]:
            with open(f"{FORGED_REPO}/{name}") as f:
                meta = json.load(f)
            assert "signed" in meta, f"{name} missing 'signed'"
            assert "signatures" in meta, f"{name} missing 'signatures'"
            assert "_type" in meta["signed"], f"{name} missing '_type'"
            assert "version" in meta["signed"], f"{name} missing 'version'"
            assert "spec_version" in meta["signed"], f"{name} missing 'spec_version'"
            assert "expires" in meta["signed"], f"{name} missing 'expires'"

    def test_all_forged_signatures_use_correct_role_keyids(self):
        """Each forged metadata file's signature uses the keyid assigned to its role."""
        role_keys = get_role_key_info()
        checks = {
            "targets.json": role_keys["targets"]["keyid"],
            "snapshot.json": role_keys["snapshot"]["keyid"],
            "timestamp.json": role_keys["timestamp"]["keyid"],
        }
        for name, expected_keyid in checks.items():
            with open(f"{FORGED_REPO}/{name}") as f:
                meta = json.load(f)
            assert any(s["keyid"] == expected_keyid for s in meta["signatures"]), \
                f"{name} missing signature for its assigned role keyid"
