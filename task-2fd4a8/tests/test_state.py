
import json
import os
import sys
import hmac
import hashlib

import pytest
from Crypto.Cipher import AES


# ===========================================================================
# Known-correct XAES-256-GCM reference implementation (used by tests only)
# ===========================================================================

def _ref_aes256_ecb(key, block):
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def _ref_derive_key(key, nonce):
    L = _ref_aes256_ecb(key, b"\x00" * 16)
    L_int = int.from_bytes(L, "big")
    msb = L_int >> 127
    K1_int = (L_int << 1) & ((1 << 128) - 1)
    if msb == 1:
        K1_int ^= 0x87
    K1 = K1_int.to_bytes(16, "big")
    M1 = b"\x00\x01\x58\x00" + nonce[:12]
    M2 = b"\x00\x02\x58\x00" + nonce[:12]
    M1_x = bytes(a ^ b for a, b in zip(M1, K1))
    M2_x = bytes(a ^ b for a, b in zip(M2, K1))
    Kx = _ref_aes256_ecb(key, M1_x) + _ref_aes256_ecb(key, M2_x)
    Nx = nonce[12:]
    return Kx, Nx


def _ref_encrypt(key, nonce, plaintext, aad):
    Kx, Nx = _ref_derive_key(key, nonce)
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(plaintext)
    return ct + tag


def _ref_decrypt(key, nonce, ciphertext, aad):
    Kx, Nx = _ref_derive_key(key, nonce)
    ct_body = ciphertext[:-16]
    tag = ciphertext[-16:]
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    return cipher.decrypt_and_verify(ct_body, tag)


# ===========================================================================
# HKDF-SHA256 (matching /app/service/keymanager.py)
# ===========================================================================

SALT = b"xaes-audit-service-v1"


def _hkdf_sha256(ikm, salt, info, length=32):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    t = b""
    okm = b""
    for i in range(1, (length + 31) // 32 + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


# ===========================================================================
# Helpers
# ===========================================================================

CONFIG_PATH = "/app/service/config.json"
PLAINTEXT_DIR = "/app/data/plaintext"
CORRECTED_DIR = "/app/data/corrected"
AUDIT_REPORT_PATH = "/app/audit_report.json"
NUM_RECORDS = 30

# Known intermediate values from the spec for test_key 0x01*32
TEST_KEY_HEX = "0101010101010101010101010101010101010101010101010101010101010101"
EXPECTED_L_HEX = "7298caa565031eadc6ce23d23ea66378"
EXPECTED_K1_HEX = "e531954aca063d5b8d9c47a47d4cc6f0"


@pytest.fixture
def master_key():
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    return bytes.fromhex(config["master_key_hex"])


@pytest.fixture
def audit_report():
    with open(AUDIT_REPORT_PATH) as f:
        return json.load(f)


def _load_solver_crypto():
    """Import the solver's (hopefully fixed) crypto module."""
    if "/app/service" not in sys.path:
        sys.path.insert(0, "/app/service")
    if "crypto" in sys.modules:
        del sys.modules["crypto"]
    import crypto
    return crypto


# ===========================================================================
# Test: audit report structure and verdicts
# ===========================================================================

class TestAuditReport:
    def test_report_exists(self):
        assert os.path.isfile(AUDIT_REPORT_PATH), f"{AUDIT_REPORT_PATH} does not exist"

    def test_report_valid_json(self):
        with open(AUDIT_REPORT_PATH) as f:
            data = json.load(f)
        assert "implementations" in data, "Report missing 'implementations' key"

    def test_alpha_non_compliant(self, audit_report):
        impls = audit_report["implementations"]
        alpha = impls.get("alpha", {})
        verdict = alpha.get("verdict", "").lower().replace("_", "-").replace(" ", "-")
        assert verdict in ("non-compliant", "noncompliant", "fail", "broken", "incorrect", "non_compliant"), \
            f"Alpha should be non-compliant, got: {alpha.get('verdict')}"

    def test_alpha_bug_identified(self, audit_report):
        desc = audit_report["implementations"]["alpha"].get("description", "").lower()
        has_cmac = any(kw in desc for kw in ["cmac", "subkey", "k1", "sub-key", "sub_key"])
        has_order = any(kw in desc for kw in ["shift", "xor", "order", "before", "swap", "reversed"])
        assert has_cmac and has_order, \
            f"Alpha bug description should mention CMAC/subkey AND shift/xor order issue. Got: {desc}"

    def test_beta_compliant(self, audit_report):
        impls = audit_report["implementations"]
        beta = impls.get("beta", {})
        verdict = beta.get("verdict", "").lower().replace("_", "-").replace(" ", "-")
        assert verdict in ("compliant", "pass", "correct"), \
            f"Beta should be compliant, got: {beta.get('verdict')}"

    def test_gamma_non_compliant(self, audit_report):
        impls = audit_report["implementations"]
        gamma = impls.get("gamma", {})
        verdict = gamma.get("verdict", "").lower().replace("_", "-").replace(" ", "-")
        assert verdict in ("non-compliant", "noncompliant", "fail", "broken", "incorrect", "non_compliant"), \
            f"Gamma should be non-compliant, got: {gamma.get('verdict')}"

    def test_gamma_bug_identified(self, audit_report):
        desc = audit_report["implementations"]["gamma"].get("description", "").lower()
        has_nonce = any(kw in desc for kw in ["nonce", "n[", "n:", "12 byte", "12-byte"])
        has_split = any(kw in desc for kw in ["split", "swap", "reversed", "first", "last",
                                                "halves", "half", "wrong", "inverted", "flipped"])
        assert has_nonce and has_split, \
            f"Gamma bug description should mention nonce AND split/swap issue. Got: {desc}"


# ===========================================================================
# Test: verification intermediate values
# ===========================================================================

class TestVerificationValues:
    def test_verification_section_exists(self, audit_report):
        assert "verification" in audit_report, "Report missing 'verification' key"

    def test_L_value(self, audit_report):
        v = audit_report["verification"]
        reported_L = v.get("L_hex", "").lower().strip()
        assert reported_L == EXPECTED_L_HEX, \
            f"L_hex should be {EXPECTED_L_HEX}, got {reported_L}"

    def test_K1_value(self, audit_report):
        v = audit_report["verification"]
        reported_K1 = v.get("K1_hex", "").lower().strip()
        assert reported_K1 == EXPECTED_K1_HEX, \
            f"K1_hex should be {EXPECTED_K1_HEX}, got {reported_K1}"


# ===========================================================================
# Test: corrected encrypted records exist and decrypt correctly
# ===========================================================================

class TestCorrectedRecordsExist:
    def test_directory_exists(self):
        assert os.path.isdir(CORRECTED_DIR), f"{CORRECTED_DIR} does not exist"

    def test_all_records_present(self):
        for i in range(NUM_RECORDS):
            path = os.path.join(CORRECTED_DIR, f"record_{i:03d}.enc")
            assert os.path.isfile(path), f"Missing corrected record: {path}"


class TestCorrectedRecordsDecrypt:
    @pytest.mark.parametrize("record_idx", range(NUM_RECORDS))
    def test_decrypt_record(self, record_idx, master_key):
        record_id = f"record_{record_idx:03d}"

        pt_path = os.path.join(PLAINTEXT_DIR, f"{record_id}.json")
        with open(pt_path, "rb") as f:
            expected_plaintext = f.read()

        enc_path = os.path.join(CORRECTED_DIR, f"{record_id}.enc")
        with open(enc_path) as f:
            enc_data = json.load(f)

        nonce = bytes.fromhex(enc_data["nonce_hex"])
        ciphertext = bytes.fromhex(enc_data["ciphertext_hex"])
        aad = enc_data["aad"].encode()

        key = _hkdf_sha256(master_key, SALT, record_id.encode())
        plaintext = _ref_decrypt(key, nonce, ciphertext, aad)
        assert plaintext == expected_plaintext, \
            f"Record {record_id}: decrypted plaintext does not match original"


# ===========================================================================
# Test: fixed crypto.py passes C2SP reference test vectors
# ===========================================================================

class TestFixedCryptoVectors:
    def test_vector1_msb0(self):
        crypto = _load_solver_crypto()
        key = bytes.fromhex(
            "0101010101010101010101010101010101010101010101010101010101010101"
        )
        nonce = b"ABCDEFGHIJKLMNOPQRSTUVWX"
        pt = b"XAES-256-GCM"
        aad = b""
        ct = crypto.encrypt(key, nonce, pt, aad)
        assert ct.hex() == "ce546ef63c9cc60765923609b33a9a1974e96e52daf2fcf7075e2271"

    def test_vector2_msb1(self):
        crypto = _load_solver_crypto()
        key = bytes.fromhex(
            "0303030303030303030303030303030303030303030303030303030303030303"
        )
        nonce = b"ABCDEFGHIJKLMNOPQRSTUVWX"
        pt = b"XAES-256-GCM"
        aad = b"c2sp.org/XAES-256-GCM"
        ct = crypto.encrypt(key, nonce, pt, aad)
        assert ct.hex() == "986ec1832593df5443a179437fd083bf3fdb41abd740a21f71eb769d"

    def test_decrypt_vector1(self):
        crypto = _load_solver_crypto()
        key = bytes.fromhex(
            "0101010101010101010101010101010101010101010101010101010101010101"
        )
        nonce = b"ABCDEFGHIJKLMNOPQRSTUVWX"
        ct = bytes.fromhex(
            "ce546ef63c9cc60765923609b33a9a1974e96e52daf2fcf7075e2271"
        )
        pt = crypto.decrypt(key, nonce, ct, b"")
        assert pt == b"XAES-256-GCM"

    def test_decrypt_vector2(self):
        crypto = _load_solver_crypto()
        key = bytes.fromhex(
            "0303030303030303030303030303030303030303030303030303030303030303"
        )
        nonce = b"ABCDEFGHIJKLMNOPQRSTUVWX"
        ct = bytes.fromhex(
            "986ec1832593df5443a179437fd083bf3fdb41abd740a21f71eb769d"
        )
        pt = crypto.decrypt(key, nonce, ct, b"c2sp.org/XAES-256-GCM")
        assert pt == b"XAES-256-GCM"


# ===========================================================================
# Test: accumulated randomized test vectors (10,000 iterations)
# ===========================================================================

class TestAccumulated:
    def test_10000_iterations(self):
        crypto = _load_solver_crypto()

        rng_output = hashlib.shake_128(b"").digest(6_000_000)
        pos = 0

        def read_rng(n):
            nonlocal pos
            result = rng_output[pos : pos + n]
            pos += n
            return result

        acc = hashlib.shake_128()

        for _ in range(10_000):
            key = read_rng(32)
            nonce = read_rng(24)
            pt_len = read_rng(1)[0]
            pt = read_rng(pt_len)
            aad_len = read_rng(1)[0]
            aad = read_rng(aad_len)
            ct = crypto.encrypt(key, nonce, pt, aad)
            acc.update(ct)

        result = acc.digest(32)
        expected = "e6b9edf2df6cec60c8cbd864e2211b597fb69a529160cd040d56c0c210081939"
        assert result.hex() == expected, (
            f"Accumulated hash mismatch after 10,000 iterations.\n"
            f"  Expected: {expected}\n"
            f"  Got:      {result.hex()}"
        )
