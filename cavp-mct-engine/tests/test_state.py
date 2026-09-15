
"""
Test suite for the AES-CBC MCT engine.
Independently computes expected MCT outputs and verifies /app/results.json.
"""

import json
import os
import re
import pytest
from Crypto.Cipher import AES


# ---------------------------------------------------------------------------
# MCT core implementation (reference)
# ---------------------------------------------------------------------------

def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def mct_cbc_encrypt_inner(key: bytes, iv: bytes, pt: bytes):
    """Run 1000 inner-loop iterations for AES-CBC MCT encrypt.

    Returns (ct_998, ct_999) — the last two ciphertext blocks.
    """
    cipher = AES.new(key, AES.MODE_ECB)
    # j = 0
    ct_0 = cipher.encrypt(xor_bytes(pt, iv))
    # j = 1: PT[1] = IV
    ct_1 = cipher.encrypt(xor_bytes(iv, ct_0))
    # j >= 2: CT[j] = E_K(CT[j-2] XOR CT[j-1])
    prev_prev = ct_0
    prev = ct_1
    for _ in range(2, 1000):
        curr = cipher.encrypt(xor_bytes(prev_prev, prev))
        prev_prev = prev
        prev = curr
    return prev_prev, prev  # ct_998, ct_999


def mct_cbc_decrypt_inner(key: bytes, iv: bytes, ct: bytes):
    """Run 1000 inner-loop iterations for AES-CBC MCT decrypt.

    Returns (pt_998, pt_999) — the last two plaintext blocks.
    """
    cipher = AES.new(key, AES.MODE_ECB)
    # j = 0: PT[0] = D_K(CT[0]) XOR IV
    pt_0 = xor_bytes(cipher.decrypt(ct), iv)
    # j = 1: CT[1] = IV, PT[1] = D_K(IV) XOR PT[0]
    pt_1 = xor_bytes(cipher.decrypt(iv), pt_0)
    # j >= 2: PT[j] = D_K(PT[j-2]) XOR PT[j-1]
    prev_prev = pt_0
    prev = pt_1
    for _ in range(2, 1000):
        curr = xor_bytes(cipher.decrypt(prev_prev), prev)
        prev_prev = prev
        prev = curr
    return prev_prev, prev  # pt_998, pt_999


def derive_key(key: bytes, block_998: bytes, block_999: bytes, key_bits: int) -> bytes:
    if key_bits == 128:
        return xor_bytes(key, block_999)
    elif key_bits == 192:
        return xor_bytes(key, block_998[-8:] + block_999)
    elif key_bits == 256:
        return xor_bytes(key, block_998 + block_999)
    else:
        raise ValueError(f"Unsupported key size: {key_bits}")


def run_mct_encrypt(key_hex: str, iv_hex: str, pt_hex: str, key_bits: int,
                    required_counts: list) -> dict:
    """Run full 100-iteration MCT encrypt and return states at required counts."""
    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(iv_hex)
    pt = bytes.fromhex(pt_hex)
    results = {}
    for i in range(100):
        ct_998, ct_999 = mct_cbc_encrypt_inner(key, iv, pt)
        if i in required_counts:
            results[str(i)] = {
                "KEY": key.hex(),
                "IV": iv.hex(),
                "PLAINTEXT": pt.hex(),
                "CIPHERTEXT": ct_999.hex(),
            }
        # Derive next outer-loop state
        key = derive_key(key, ct_998, ct_999, key_bits)
        iv = ct_999
        pt = ct_998
    return results


def run_mct_decrypt(key_hex: str, iv_hex: str, ct_hex: str, key_bits: int,
                    required_counts: list) -> dict:
    """Run full 100-iteration MCT decrypt and return states at required counts."""
    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(iv_hex)
    ct = bytes.fromhex(ct_hex)
    results = {}
    for i in range(100):
        pt_998, pt_999 = mct_cbc_decrypt_inner(key, iv, ct)
        if i in required_counts:
            results[str(i)] = {
                "KEY": key.hex(),
                "IV": iv.hex(),
                "CIPHERTEXT": ct.hex(),
                "PLAINTEXT": pt_999.hex(),
            }
        key = derive_key(key, pt_998, pt_999, key_bits)
        iv = pt_999
        ct = pt_998
    return results


# ---------------------------------------------------------------------------
# .rsp parser for audit verification
# ---------------------------------------------------------------------------

def parse_rsp(path: str) -> list:
    """Parse a CAVP .rsp file and return a list of entry dicts."""
    entries = []
    current = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or line.startswith("[") or not line:
                if current:
                    entries.append(current)
                    current = {}
                continue
            m = re.match(r"(\w+)\s*=\s*(.+)", line)
            if m:
                current[m.group(1)] = m.group(2).strip()
    if current:
        entries.append(current)
    return entries


def audit_rsp(path: str, key_bits: int = 128) -> list:
    """Audit an MCT encrypt .rsp file. Return list of corrupted entries."""
    entries = parse_rsp(path)
    corruptions = []
    for entry in entries:
        count = int(entry["COUNT"])
        key = bytes.fromhex(entry["KEY"])
        iv = bytes.fromhex(entry["IV"])
        pt = bytes.fromhex(entry["PLAINTEXT"])
        file_ct = entry["CIPHERTEXT"].lower()
        _, ct_999 = mct_cbc_encrypt_inner(key, iv, pt)
        expected_ct = ct_999.hex()
        if file_ct != expected_ct:
            corruptions.append({
                "count": count,
                "found": file_ct,
                "expected": expected_ct,
            })
    return corruptions


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), f"Results file not found at {results_path}"
    with open(results_path) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def challenge():
    with open("/app/challenge.json") as f:
        return json.load(f)


class TestResultsStructure:
    def test_results_has_compute(self, results):
        assert "compute" in results, "results.json missing 'compute' key"

    def test_results_has_audit(self, results):
        assert "audit" in results, "results.json missing 'audit' key"

    def test_compute_has_all_tasks(self, results, challenge):
        for task in challenge["compute"]:
            assert task["id"] in results["compute"], \
                f"compute results missing task '{task['id']}'"

    def test_audit_has_all_tasks(self, results, challenge):
        for task in challenge["audit"]:
            assert task["id"] in results["audit"], \
                f"audit results missing task '{task['id']}'"


class TestCBC128Encrypt:
    TASK_ID = "cbc128_enc"

    @pytest.fixture(scope="class")
    def expected(self, challenge):
        task = next(t for t in challenge["compute"] if t["id"] == self.TASK_ID)
        return run_mct_encrypt(
            task["key"], task["iv"], task["plaintext"],
            task["key_bits"], task["required_counts"],
        )

    def test_count_0(self, results, expected):
        actual = results["compute"][self.TASK_ID]["0"]
        exp = expected["0"]
        for field in ("KEY", "IV", "PLAINTEXT", "CIPHERTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC128 enc COUNT=0 {field}: got {actual[field]}, expected {exp[field]}"

    def test_count_49(self, results, expected):
        actual = results["compute"][self.TASK_ID]["49"]
        exp = expected["49"]
        for field in ("KEY", "IV", "PLAINTEXT", "CIPHERTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC128 enc COUNT=49 {field}: got {actual[field]}, expected {exp[field]}"

    def test_count_99(self, results, expected):
        actual = results["compute"][self.TASK_ID]["99"]
        exp = expected["99"]
        for field in ("KEY", "IV", "PLAINTEXT", "CIPHERTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC128 enc COUNT=99 {field}: got {actual[field]}, expected {exp[field]}"


class TestCBC192Encrypt:
    TASK_ID = "cbc192_enc"

    @pytest.fixture(scope="class")
    def expected(self, challenge):
        task = next(t for t in challenge["compute"] if t["id"] == self.TASK_ID)
        return run_mct_encrypt(
            task["key"], task["iv"], task["plaintext"],
            task["key_bits"], task["required_counts"],
        )

    def test_count_0(self, results, expected):
        actual = results["compute"][self.TASK_ID]["0"]
        exp = expected["0"]
        for field in ("KEY", "IV", "PLAINTEXT", "CIPHERTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC192 enc COUNT=0 {field}: got {actual[field]}, expected {exp[field]}"

    def test_count_49(self, results, expected):
        actual = results["compute"][self.TASK_ID]["49"]
        exp = expected["49"]
        for field in ("KEY", "IV", "PLAINTEXT", "CIPHERTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC192 enc COUNT=49 {field}: got {actual[field]}, expected {exp[field]}"

    def test_count_99(self, results, expected):
        actual = results["compute"][self.TASK_ID]["99"]
        exp = expected["99"]
        for field in ("KEY", "IV", "PLAINTEXT", "CIPHERTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC192 enc COUNT=99 {field}: got {actual[field]}, expected {exp[field]}"


class TestCBC256Encrypt:
    TASK_ID = "cbc256_enc"

    @pytest.fixture(scope="class")
    def expected(self, challenge):
        task = next(t for t in challenge["compute"] if t["id"] == self.TASK_ID)
        return run_mct_encrypt(
            task["key"], task["iv"], task["plaintext"],
            task["key_bits"], task["required_counts"],
        )

    def test_count_0(self, results, expected):
        actual = results["compute"][self.TASK_ID]["0"]
        exp = expected["0"]
        for field in ("KEY", "IV", "PLAINTEXT", "CIPHERTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC256 enc COUNT=0 {field}: got {actual[field]}, expected {exp[field]}"

    def test_count_49(self, results, expected):
        actual = results["compute"][self.TASK_ID]["49"]
        exp = expected["49"]
        for field in ("KEY", "IV", "PLAINTEXT", "CIPHERTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC256 enc COUNT=49 {field}: got {actual[field]}, expected {exp[field]}"

    def test_count_99(self, results, expected):
        actual = results["compute"][self.TASK_ID]["99"]
        exp = expected["99"]
        for field in ("KEY", "IV", "PLAINTEXT", "CIPHERTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC256 enc COUNT=99 {field}: got {actual[field]}, expected {exp[field]}"


class TestCBC128Decrypt:
    TASK_ID = "cbc128_dec"

    @pytest.fixture(scope="class")
    def expected(self, challenge):
        task = next(t for t in challenge["compute"] if t["id"] == self.TASK_ID)
        return run_mct_decrypt(
            task["key"], task["iv"], task["ciphertext"],
            task["key_bits"], task["required_counts"],
        )

    def test_count_0(self, results, expected):
        actual = results["compute"][self.TASK_ID]["0"]
        exp = expected["0"]
        for field in ("KEY", "IV", "CIPHERTEXT", "PLAINTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC128 dec COUNT=0 {field}: got {actual[field]}, expected {exp[field]}"

    def test_count_49(self, results, expected):
        actual = results["compute"][self.TASK_ID]["49"]
        exp = expected["49"]
        for field in ("KEY", "IV", "CIPHERTEXT", "PLAINTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC128 dec COUNT=49 {field}: got {actual[field]}, expected {exp[field]}"

    def test_count_99(self, results, expected):
        actual = results["compute"][self.TASK_ID]["99"]
        exp = expected["99"]
        for field in ("KEY", "IV", "CIPHERTEXT", "PLAINTEXT"):
            assert actual[field].lower() == exp[field].lower(), \
                f"CBC128 dec COUNT=99 {field}: got {actual[field]}, expected {exp[field]}"


class TestAudit:
    TASK_ID = "audit_cbc128"

    @pytest.fixture(scope="class")
    def expected_corruptions(self):
        return audit_rsp("/app/audit/CBCMCT128_suspect.rsp", key_bits=128)

    def test_audit_correct_count(self, results, expected_corruptions):
        actual = results["audit"][self.TASK_ID]
        assert len(actual) == len(expected_corruptions), \
            f"Expected {len(expected_corruptions)} corrupted entries, got {len(actual)}"

    def test_audit_correct_counts_identified(self, results, expected_corruptions):
        actual = results["audit"][self.TASK_ID]
        expected_counts = sorted([e["count"] for e in expected_corruptions])
        actual_counts = sorted([e["count"] for e in actual])
        assert actual_counts == expected_counts, \
            f"Corrupted COUNT indices differ: got {actual_counts}, expected {expected_counts}"

    def test_audit_correct_expected_values(self, results, expected_corruptions):
        actual = results["audit"][self.TASK_ID]
        actual_by_count = {e["count"]: e for e in actual}
        for exp in expected_corruptions:
            c = exp["count"]
            assert c in actual_by_count, f"Missing corruption report for COUNT={c}"
            assert actual_by_count[c]["expected"].lower() == exp["expected"].lower(), \
                f"COUNT={c}: expected CT {exp['expected']}, agent reported {actual_by_count[c]['expected']}"

    def test_audit_correct_found_values(self, results, expected_corruptions):
        actual = results["audit"][self.TASK_ID]
        actual_by_count = {e["count"]: e for e in actual}
        for exp in expected_corruptions:
            c = exp["count"]
            assert actual_by_count[c]["found"].lower() == exp["found"].lower(), \
                f"COUNT={c}: found value should be {exp['found']}, agent reported {actual_by_count[c]['found']}"


class TestReferenceVectorValidation:
    """Verify that the reference NIST vectors in /app/vectors/ are consistent
    with our MCT implementation (sanity check on the test itself)."""

    def _validate_rsp(self, path, key_bits):
        entries = parse_rsp(path)
        for entry in entries:
            key = bytes.fromhex(entry["KEY"])
            iv = bytes.fromhex(entry["IV"])
            pt = bytes.fromhex(entry["PLAINTEXT"])
            expected_ct = entry["CIPHERTEXT"].lower()
            _, ct_999 = mct_cbc_encrypt_inner(key, iv, pt)
            assert ct_999.hex() == expected_ct, \
                f"Reference vector COUNT={entry['COUNT']} in {path} failed validation"

    def test_ref_128(self):
        self._validate_rsp("/app/vectors/CBCMCT128.rsp", 128)

    def test_ref_192(self):
        self._validate_rsp("/app/vectors/CBCMCT192.rsp", 192)

    def test_ref_256(self):
        self._validate_rsp("/app/vectors/CBCMCT256.rsp", 256)
