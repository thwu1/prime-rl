#!/usr/bin/env python3
"""
Tests for encrypted session recovery and protocol variant analysis task.
Independently computes expected values from incident data.

"""
import hashlib
import hmac as hmac_mod
import json
import os
import struct

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# === Independent key schedule implementation ===

def hkdf_extract(salt, ikm):
    return hmac_mod.new(salt, ikm, hashlib.sha256).digest()

def hkdf_expand(prk, info, length):
    n = (length + 31) // 32
    okm, t = b"", b""
    for i in range(1, n + 1):
        t = hmac_mod.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]

def hkdf_expand_label(secret, label, context, length):
    tls_label = b"tls13 " + label.encode("ascii")
    hkdf_label = (
        struct.pack(">H", length)
        + struct.pack("B", len(tls_label))
        + tls_label
        + struct.pack("B", len(context))
        + context
    )
    return hkdf_expand(secret, hkdf_label, length)

def derive_secret(secret, label, messages):
    return hkdf_expand_label(secret, label, hashlib.sha256(messages).digest(), 32)

def make_nonce(iv, seq_num):
    seq_bytes = seq_num.to_bytes(12, "big")
    return bytes(a ^ b for a, b in zip(iv, seq_bytes))

def extract_server_pubkey(server_hello_bytes):
    """Parse ServerHello to extract public key from key_share extension."""
    offset = 4  # type(1) + length(3)
    offset += 2  # version
    offset += 32  # random
    sid_len = server_hello_bytes[offset]
    offset += 1 + sid_len
    offset += 2  # cipher suite
    offset += 1  # compression
    ext_total = struct.unpack(">H", server_hello_bytes[offset:offset + 2])[0]
    offset += 2
    ext_end = offset + ext_total

    while offset < ext_end:
        et = struct.unpack(">H", server_hello_bytes[offset:offset + 2])[0]
        el = struct.unpack(">H", server_hello_bytes[offset + 2:offset + 4])[0]
        if et == 0x0033:
            ke_len = struct.unpack(">H", server_hello_bytes[offset + 6:offset + 8])[0]
            return server_hello_bytes[offset + 8:offset + 8 + ke_len]
        offset += 4 + el
    raise ValueError("key_share extension not found")


def compute_handshake_secret(shared_secret, use_standard):
    """Compute handshake_secret via standard or modified key schedule."""
    zeros = b"\x00" * 32
    if use_standard:
        early_secret = hkdf_extract(zeros, zeros)
        derived_1 = derive_secret(early_secret, "derived", b"")
        return hkdf_extract(derived_1, shared_secret)
    else:
        return hkdf_extract(zeros, shared_secret)


def try_decrypt_session(session, private_key_hex, use_standard):
    """Try to decrypt a session with a candidate key and key schedule variant."""
    ch = bytes.fromhex(session["client_hello"])
    sh = bytes.fromhex(session["server_hello"])

    try:
        spub = extract_server_pubkey(sh)
        cpk = X25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
        shared = cpk.exchange(X25519PublicKey.from_public_bytes(spub))
    except Exception:
        return None

    handshake_secret = compute_handshake_secret(shared, use_standard)

    transcript_ch_sh = ch + sh
    s_hs_traffic = derive_secret(handshake_secret, "s hs traffic", transcript_ch_sh)
    s_hs_key = hkdf_expand_label(s_hs_traffic, "key", b"", 16)
    s_hs_iv = hkdf_expand_label(s_hs_traffic, "iv", b"", 12)

    # Try decrypting first encrypted record (handshake)
    rec0 = bytes.fromhex(session["encrypted_records"][0])
    aad0, ct0 = rec0[:5], rec0[5:]
    try:
        inner = AESGCM(s_hs_key).decrypt(make_nonce(s_hs_iv, 0), ct0, aad0)
    except Exception:
        return None  # Wrong key or wrong variant

    hs_plaintext = inner[:-1]

    # Derive application keys
    transcript_full = ch + sh + hs_plaintext
    derived_2 = derive_secret(handshake_secret, "derived", b"")
    master_secret = hkdf_extract(derived_2, b"\x00" * 32)
    s_ap_traffic = derive_secret(master_secret, "s ap traffic", transcript_full)
    s_ap_key = hkdf_expand_label(s_ap_traffic, "key", b"", 16)
    s_ap_iv = hkdf_expand_label(s_ap_traffic, "iv", b"", 12)

    # Decrypt application records
    aesgcm_app = AESGCM(s_ap_key)
    parts = []
    for i, rec_hex in enumerate(session["encrypted_records"][1:]):
        rec = bytes.fromhex(rec_hex)
        aad, ct = rec[:5], rec[5:]
        try:
            dec = aesgcm_app.decrypt(make_nonce(s_ap_iv, i), ct, aad)
            parts.append(dec[:-1])
        except Exception:
            parts.append(None)

    text = b"".join(p for p in parts if p is not None).decode("utf-8", errors="replace")
    has_loss = any(p is None for p in parts)
    return {"text": text, "has_loss": has_loss, "standard": use_standard}


def compute_expected():
    """Compute all expected values by independently decrypting the incident data."""
    with open("/app/incident/captures.json") as f:
        captures = json.load(f)
    with open("/app/incident/leaked_keys.json") as f:
        leaked_keys = json.load(f)

    key_mapping = {}
    decrypted = {}
    variants = {}
    data_loss = {}

    for session in captures["sessions"]:
        sid = session["id"]
        for key_entry in leaked_keys:
            # Try standard first, then modified
            for use_std in [True, False]:
                result = try_decrypt_session(session, key_entry["private_key_hex"], use_std)
                if result is not None:
                    key_mapping[sid] = key_entry["id"]
                    decrypted[sid] = result["text"]
                    variants[sid] = "standard" if result["standard"] else "modified"
                    data_loss[sid] = result["has_loss"]
                    break
            if sid in key_mapping:
                break

    # Find shared server sessions
    server_pubkeys = {}
    for session in captures["sessions"]:
        sh = bytes.fromhex(session["server_hello"])
        spub = extract_server_pubkey(sh).hex()
        if spub not in server_pubkeys:
            server_pubkeys[spub] = []
        server_pubkeys[spub].append(session["id"])

    shared_sessions = []
    for spub, sids in server_pubkeys.items():
        if len(sids) > 1:
            shared_sessions = sorted(sids)

    return {
        "key_mapping": key_mapping,
        "decrypted": decrypted,
        "variants": variants,
        "data_loss": data_loss,
        "shared_sessions": shared_sessions,
    }


@pytest.fixture(scope="module")
def expected():
    return compute_expected()


# === Key Mapping Tests ===

class TestKeyMapping:
    def test_file_exists(self):
        assert os.path.exists("/app/output/key_mapping.json"), \
            "Missing /app/output/key_mapping.json"

    def test_alpha_key(self, expected):
        with open("/app/output/key_mapping.json") as f:
            actual = json.load(f)
        assert actual.get("alpha") == expected["key_mapping"]["alpha"]

    def test_beta_key(self, expected):
        with open("/app/output/key_mapping.json") as f:
            actual = json.load(f)
        assert actual.get("beta") == expected["key_mapping"]["beta"]

    def test_gamma_key(self, expected):
        with open("/app/output/key_mapping.json") as f:
            actual = json.load(f)
        assert actual.get("gamma") == expected["key_mapping"]["gamma"]

    def test_delta_key(self, expected):
        with open("/app/output/key_mapping.json") as f:
            actual = json.load(f)
        assert actual.get("delta") == expected["key_mapping"]["delta"]

    def test_all_sessions_mapped(self, expected):
        with open("/app/output/key_mapping.json") as f:
            actual = json.load(f)
        assert set(actual.keys()) == {"alpha", "beta", "gamma", "delta"}


# === Decrypted Content Tests ===

class TestDecryptedAlpha:
    def test_file_exists(self):
        assert os.path.exists("/app/output/decrypted/alpha.txt")

    def test_contains_db_host(self):
        with open("/app/output/decrypted/alpha.txt") as f:
            content = f.read()
        assert "db-prod-master.internal" in content

    def test_contains_db_password(self):
        with open("/app/output/decrypted/alpha.txt") as f:
            content = f.read()
        assert "Kj8#mP2$vL9nQ4wR" in content

    def test_contains_stripe_key(self):
        with open("/app/output/decrypted/alpha.txt") as f:
            content = f.read()
        assert "sk_live_4eC39HqLyjWDarjtT1zdp7dc" in content

    def test_contains_aws_key(self):
        with open("/app/output/decrypted/alpha.txt") as f:
            content = f.read()
        assert "AKIAIOSFODNN7EXAMPLE" in content

    def test_full_content(self, expected):
        with open("/app/output/decrypted/alpha.txt") as f:
            actual = f.read().strip().replace("\r\n", "\n")
        exp = expected["decrypted"]["alpha"].strip().replace("\r\n", "\n")
        assert actual == exp


class TestDecryptedBeta:
    def test_file_exists(self):
        assert os.path.exists("/app/output/decrypted/beta.txt")

    def test_contains_intranet_title(self):
        with open("/app/output/decrypted/beta.txt") as f:
            content = f.read()
        assert "<title>Intranet</title>" in content

    def test_contains_meeting_info(self):
        with open("/app/output/decrypted/beta.txt") as f:
            content = f.read()
        assert "Q4 planning meeting" in content

    def test_full_content(self, expected):
        with open("/app/output/decrypted/beta.txt") as f:
            actual = f.read().strip().replace("\r\n", "\n")
        exp = expected["decrypted"]["beta"].strip().replace("\r\n", "\n")
        assert actual == exp


class TestDecryptedGamma:
    def test_file_exists(self):
        assert os.path.exists("/app/output/decrypted/gamma.txt")

    def test_contains_csv_header(self):
        with open("/app/output/decrypted/gamma.txt") as f:
            content = f.read()
        assert "name,email,ssn,account_number" in content

    def test_contains_records_after_corruption(self):
        with open("/app/output/decrypted/gamma.txt") as f:
            content = f.read()
        assert "John Smith" in content
        assert "Alice Brown" in content

    def test_corrupted_record_absent(self):
        with open("/app/output/decrypted/gamma.txt") as f:
            content = f.read()
        assert "Jane Doe" not in content

    def test_partial_content(self, expected):
        with open("/app/output/decrypted/gamma.txt") as f:
            actual = f.read().strip().replace("\r\n", "\n")
        exp = expected["decrypted"]["gamma"].strip().replace("\r\n", "\n")
        assert actual == exp


class TestDecryptedDelta:
    def test_file_exists(self):
        assert os.path.exists("/app/output/decrypted/delta.txt")

    def test_contains_architecture_info(self):
        with open("/app/output/decrypted/delta.txt") as f:
            content = f.read()
        assert "INTERNAL ARCHITECTURE REVIEW" in content
        assert "Istio" in content
        assert "HashiCorp Vault" in content

    def test_contains_firewall_rules(self):
        with open("/app/output/decrypted/delta.txt") as f:
            content = f.read()
        assert "Firewall rules" in content

    def test_full_content(self, expected):
        with open("/app/output/decrypted/delta.txt") as f:
            actual = f.read().strip().replace("\r\n", "\n")
        exp = expected["decrypted"]["delta"].strip().replace("\r\n", "\n")
        assert actual == exp


# === Exfiltration Report Tests ===

class TestExfiltrationReport:
    def test_file_exists(self):
        assert os.path.exists("/app/output/exfiltration_report.json")

    def test_exfiltrated_sessions(self):
        with open("/app/output/exfiltration_report.json") as f:
            report = json.load(f)
        exfil = sorted(report.get("exfiltrated_sessions", []))
        assert exfil == ["alpha", "delta", "gamma"], \
            f"Expected exfiltrated ['alpha', 'delta', 'gamma'], got {exfil}"

    def test_benign_sessions(self):
        with open("/app/output/exfiltration_report.json") as f:
            report = json.load(f)
        benign = sorted(report.get("benign_sessions", []))
        assert benign == ["beta"], \
            f"Expected benign ['beta'], got {benign}"


# === Vulnerability Assessment Tests ===

class TestVulnerabilityAssessment:
    def test_file_exists(self):
        assert os.path.exists("/app/output/vulnerability_assessment.json")

    def _load(self):
        with open("/app/output/vulnerability_assessment.json") as f:
            return json.load(f)

    def test_protocol_variant_alpha(self):
        va = self._load()
        assert va["sessions"]["alpha"]["protocol_variant"] == "standard"

    def test_protocol_variant_beta(self):
        va = self._load()
        assert va["sessions"]["beta"]["protocol_variant"] == "standard"

    def test_protocol_variant_gamma(self):
        va = self._load()
        assert va["sessions"]["gamma"]["protocol_variant"] == "modified"

    def test_protocol_variant_delta(self):
        va = self._load()
        assert va["sessions"]["delta"]["protocol_variant"] == "modified"

    def test_content_category_alpha(self):
        va = self._load()
        assert va["sessions"]["alpha"]["content_category"] == "credentials"

    def test_content_category_beta(self):
        va = self._load()
        assert va["sessions"]["beta"]["content_category"] == "public_info"

    def test_content_category_gamma(self):
        va = self._load()
        assert va["sessions"]["gamma"]["content_category"] == "pii"

    def test_content_category_delta(self):
        va = self._load()
        assert va["sessions"]["delta"]["content_category"] == "internal_docs"

    def test_severity_alpha(self):
        va = self._load()
        assert va["sessions"]["alpha"]["severity"] == "critical"

    def test_severity_beta(self):
        va = self._load()
        assert va["sessions"]["beta"]["severity"] == "low"

    def test_severity_gamma(self):
        va = self._load()
        assert va["sessions"]["gamma"]["severity"] == "high"

    def test_severity_delta(self):
        va = self._load()
        assert va["sessions"]["delta"]["severity"] == "medium"

    def test_gamma_data_loss(self):
        va = self._load()
        assert va["sessions"]["gamma"].get("data_loss") is True

    def test_shared_server_sessions(self):
        va = self._load()
        shared = sorted(va.get("shared_server_sessions", []))
        assert shared == ["alpha", "delta"], \
            f"Expected shared servers ['alpha', 'delta'], got {shared}"

    def test_incident_priority(self):
        va = self._load()
        priority = va.get("incident_priority", [])
        assert priority == ["alpha", "gamma", "delta", "beta"], \
            f"Expected priority ['alpha', 'gamma', 'delta', 'beta'], got {priority}"
