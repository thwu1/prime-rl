
"""
Verify /app/results.json and /app/output/*.der contain valid ECDSA signatures
for all 3 signing challenges, cross-referencing the SQLite corpus and PEM keys.
"""

import json
import os
import sqlite3
import base64
import pytest
from ecdsa import SECP256k1, VerifyingKey
from ecdsa.util import sigdecode_string


CURVE_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
HALF_ORDER = CURVE_ORDER // 2

CORPUS_DB = "/app/corpus.db"
KEYS_DIR = "/app/keys"
RESULTS_PATH = "/app/results.json"
OUTPUT_DIR = "/app/output"


# ---- ASN.1 DER helpers ----

def parse_der_element(data, offset=0):
    """Parse one DER TLV, return (tag, value_bytes, next_offset)."""
    tag = data[offset]
    offset += 1
    length = data[offset]
    offset += 1
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[offset:offset + n], 'big')
        offset += n
    value = data[offset:offset + length]
    return tag, value, offset + length


def parse_der_signature(filepath):
    """Parse a DER-encoded ECDSA signature file, return (r_int, s_int)."""
    with open(filepath, 'rb') as f:
        data = f.read()
    # Outer SEQUENCE
    tag, seq_val, _ = parse_der_element(data, 0)
    assert tag == 0x30, f"Expected SEQUENCE (0x30), got 0x{tag:02x}"
    # First INTEGER (r)
    tag, r_bytes, next_off = parse_der_element(seq_val, 0)
    assert tag == 0x02, f"Expected INTEGER (0x02), got 0x{tag:02x}"
    r = int.from_bytes(r_bytes, 'big')
    # Second INTEGER (s)
    tag, s_bytes, _ = parse_der_element(seq_val, next_off)
    assert tag == 0x02, f"Expected INTEGER (0x02), got 0x{tag:02x}"
    s = int.from_bytes(s_bytes, 'big')
    return r, s


# ---- Fixtures ----

@pytest.fixture(scope="module")
def challenges():
    db = sqlite3.connect(CORPUS_DB)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT c.challenge_id, c.key_id, c.message_hash, k.pem_file "
        "FROM signing_challenges c JOIN ec_keys k ON c.key_id = k.key_id "
        "ORDER BY c.challenge_id"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@pytest.fixture(scope="module")
def results():
    with open(RESULTS_PATH, "r") as f:
        return json.load(f)


# ---- Format tests ----

class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_results_is_list(self, results):
        assert isinstance(results, list), "results.json must be a JSON array"

    def test_results_has_three_entries(self, results):
        assert len(results) == 3, f"Expected 3 results, got {len(results)}"

    def test_required_fields(self, results):
        required = {"key_pem_file", "message_hash", "signature_r", "signature_s"}
        for i, entry in enumerate(results):
            missing = required - set(entry.keys())
            assert not missing, f"Entry {i} missing: {missing}"

    def test_hex_format_r(self, results):
        for i, entry in enumerate(results):
            r = entry["signature_r"]
            assert len(r) == 64, f"Entry {i}: signature_r length {len(r)}, expected 64"
            assert r == r.lower(), f"Entry {i}: signature_r must be lowercase"
            int(r, 16)

    def test_hex_format_s(self, results):
        for i, entry in enumerate(results):
            s = entry["signature_s"]
            assert len(s) == 64, f"Entry {i}: signature_s length {len(s)}, expected 64"
            assert s == s.lower(), f"Entry {i}: signature_s must be lowercase"
            int(s, 16)

    def test_pem_file_exists(self, results):
        for i, entry in enumerate(results):
            path = os.path.join(KEYS_DIR, entry["key_pem_file"])
            assert os.path.exists(path), f"Entry {i}: PEM file {path} not found"


# ---- Challenge coverage ----

class TestChallengesCovered:
    def test_all_challenges_covered(self, challenges, results):
        ch_set = {(ch["pem_file"], ch["message_hash"]) for ch in challenges}
        res_set = {(r["key_pem_file"], r["message_hash"]) for r in results}
        missing = ch_set - res_set
        assert not missing, f"Missing challenges: {missing}"

    def test_order_matches_challenge_id(self, challenges, results):
        for i, (ch, res) in enumerate(zip(challenges, results)):
            assert res["key_pem_file"] == ch["pem_file"], (
                f"Entry {i}: expected key {ch['pem_file']}, got {res['key_pem_file']}"
            )
            assert res["message_hash"] == ch["message_hash"], (
                f"Entry {i}: message_hash mismatch"
            )


# ---- Signature validity ----

class TestSignatureValidity:
    def _verify_one(self, entry):
        pem_path = os.path.join(KEYS_DIR, entry["key_pem_file"])
        with open(pem_path, 'r') as f:
            pem_data = f.read()

        vk = VerifyingKey.from_pem(pem_data)
        msg_hash = bytes.fromhex(entry["message_hash"])
        r_int = int(entry["signature_r"], 16)
        s_int = int(entry["signature_s"], 16)

        assert s_int <= HALF_ORDER, "s not low-s normalized"
        assert 1 <= r_int < CURVE_ORDER, "r out of range"
        assert 1 <= s_int < CURVE_ORDER, "s out of range"

        sig_bytes = r_int.to_bytes(32, "big") + s_int.to_bytes(32, "big")
        vk.verify_digest(sig_bytes, msg_hash, sigdecode=sigdecode_string)

    def test_signature_0(self, results):
        self._verify_one(results[0])

    def test_signature_1(self, results):
        self._verify_one(results[1])

    def test_signature_2(self, results):
        self._verify_one(results[2])


# ---- DER output files ----

class TestDEROutput:
    def test_der_files_exist(self):
        for i in range(1, 4):
            path = os.path.join(OUTPUT_DIR, f"challenge_{i}.der")
            assert os.path.exists(path), f"{path} not found"

    def test_der_files_parse(self):
        for i in range(1, 4):
            path = os.path.join(OUTPUT_DIR, f"challenge_{i}.der")
            r, s = parse_der_signature(path)
            assert 1 <= r < CURVE_ORDER, f"challenge_{i}.der: r out of range"
            assert 1 <= s < CURVE_ORDER, f"challenge_{i}.der: s out of range"

    def test_der_matches_json(self, results):
        for i, entry in enumerate(results):
            path = os.path.join(OUTPUT_DIR, f"challenge_{i + 1}.der")
            r_der, s_der = parse_der_signature(path)
            r_json = int(entry["signature_r"], 16)
            s_json = int(entry["signature_s"], 16)
            assert r_der == r_json, (
                f"challenge_{i+1}.der r mismatch: DER={r_der:#x} JSON={r_json:#x}"
            )
            assert s_der == s_json, (
                f"challenge_{i+1}.der s mismatch: DER={s_der:#x} JSON={s_json:#x}"
            )

    def test_der_signatures_verify(self, results):
        """Verify the DER file signatures independently using ecdsa library."""
        for i, entry in enumerate(results):
            path = os.path.join(OUTPUT_DIR, f"challenge_{i + 1}.der")
            r, s = parse_der_signature(path)
            pem_path = os.path.join(KEYS_DIR, entry["key_pem_file"])
            with open(pem_path) as f:
                vk = VerifyingKey.from_pem(f.read())
            msg_hash = bytes.fromhex(entry["message_hash"])
            sig_bytes = r.to_bytes(32, "big") + s.to_bytes(32, "big")
            vk.verify_digest(sig_bytes, msg_hash, sigdecode=sigdecode_string)


# ---- Distinct keys ----

class TestDistinctKeys:
    def test_three_distinct_keys(self, results):
        pks = {r["key_pem_file"] for r in results}
        assert len(pks) == 3, f"Expected 3 distinct keys, got {len(pks)}"
