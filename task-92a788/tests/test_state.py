
import hashlib
import importlib.util
import json
import math
import os
import re
import pytest


# ============================================================
# Constants — verified via SHA-256 hashes to prevent leaking
# ============================================================

# V1 answer
V1_ANSWER_SHA256 = "c884d425fd8a0fec18b550a315a853583dd73333749ef8819042804f5ff57a4b"
V1_ANSWER_LENGTH = 48
V1_ANSWER_PATH = "/app/answer.txt"

# V2 answer
V2_ANSWER_SHA256 = "847c6974427dfb409124440e933e0ef40bc1094041e7a5a011d016b8c738d16a"
V2_ANSWER_LENGTH = 48
V2_ANSWER_PATH = "/app/answer_v2.txt"

# Assessment
ASSESSMENT_PATH = "/app/assessment.json"

# Algorithm hash (normalized "aes128ecb")
EXPECTED_ALGO_HASH = "feb604a5568cd2857a9154c69dd5d9ab3747c1028f4580d9ef488f82ae1b067b"

# Key hashes
V1_KEY_HASH = "001153b04cb706029dc639f4cd859b46562162b4707da8e5ad300c087091fb23"
V2_KEY_HASH = "ff25d2389ab7917a77cc0c3546331401054d53cb7b2edeedb7b4e7742bb5286d"

# V3 keywrap module path
V3_MODULE_PATH = "/app/v3_keywrap.py"


# ============================================================
# Helper
# ============================================================
def strip_trailing_newline(data: bytes) -> bytes:
    if data.endswith(b"\n"):
        return data[:-1]
    return data


def normalize_algo(raw: str) -> str:
    return re.sub(r'[^a-z0-9]', '', raw.lower())


# ============================================================
# V1 answer tests
# ============================================================

class TestV1Answer:
    def test_file_exists(self):
        assert os.path.isfile(V1_ANSWER_PATH), f"V1 answer not found at {V1_ANSWER_PATH}"

    def test_hash(self):
        with open(V1_ANSWER_PATH, "rb") as f:
            content = strip_trailing_newline(f.read())
        h = hashlib.sha256(content).hexdigest()
        assert h == V1_ANSWER_SHA256, (
            f"V1 answer hash mismatch: got {h}"
        )

    def test_length(self):
        with open(V1_ANSWER_PATH, "rb") as f:
            content = strip_trailing_newline(f.read())
        assert len(content) == V1_ANSWER_LENGTH

    def test_printable_ascii(self):
        with open(V1_ANSWER_PATH, "rb") as f:
            content = strip_trailing_newline(f.read())
        for i, b in enumerate(content):
            assert 0x20 <= b < 0x7f, f"Non-printable byte 0x{b:02x} at position {i}"


# ============================================================
# V2 answer tests
# ============================================================

class TestV2Answer:
    def test_file_exists(self):
        assert os.path.isfile(V2_ANSWER_PATH), f"V2 answer not found at {V2_ANSWER_PATH}"

    def test_hash(self):
        with open(V2_ANSWER_PATH, "rb") as f:
            content = strip_trailing_newline(f.read())
        h = hashlib.sha256(content).hexdigest()
        assert h == V2_ANSWER_SHA256, (
            f"V2 answer hash mismatch: got {h}"
        )

    def test_length(self):
        with open(V2_ANSWER_PATH, "rb") as f:
            content = strip_trailing_newline(f.read())
        assert len(content) == V2_ANSWER_LENGTH

    def test_printable_ascii(self):
        with open(V2_ANSWER_PATH, "rb") as f:
            content = strip_trailing_newline(f.read())
        for i, b in enumerate(content):
            assert 0x20 <= b < 0x7f, f"Non-printable byte 0x{b:02x} at position {i}"


# ============================================================
# Assessment tests — comparative security evaluation
# ============================================================

class TestAssessment:
    def _load(self):
        with open(ASSESSMENT_PATH, "r") as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.isfile(ASSESSMENT_PATH), f"Assessment not found at {ASSESSMENT_PATH}"

    def test_valid_json_structure(self):
        data = self._load()
        assert isinstance(data, dict)
        required = {
            "v1_algorithm", "v1_key_hex", "v1_key_protection",
            "v1_attack_complexity",
            "v2_algorithm", "v2_key_hex", "v2_key_protection",
            "v2_attack_complexity",
            "more_secure_version", "justification",
            "rejected_candidates"
        }
        missing = required - set(data.keys())
        assert not missing, f"Missing required fields: {missing}"

    def test_v1_algorithm(self):
        data = self._load()
        raw = data.get("v1_algorithm", "")
        assert isinstance(raw, str) and len(raw) > 0
        h = hashlib.sha256(normalize_algo(raw).encode()).hexdigest()
        assert h == EXPECTED_ALGO_HASH, (
            f"V1 algorithm wrong: '{raw}' (normalized: '{normalize_algo(raw)}')"
        )

    def test_v2_algorithm(self):
        data = self._load()
        raw = data.get("v2_algorithm", "")
        assert isinstance(raw, str) and len(raw) > 0
        h = hashlib.sha256(normalize_algo(raw).encode()).hexdigest()
        assert h == EXPECTED_ALGO_HASH, (
            f"V2 algorithm wrong: '{raw}' (normalized: '{normalize_algo(raw)}')"
        )

    def test_v1_key(self):
        data = self._load()
        key_hex = data.get("v1_key_hex", "").lower().strip()
        assert len(key_hex) > 0, "v1_key_hex must be non-empty"
        h = hashlib.sha256(key_hex.encode()).hexdigest()
        assert h == V1_KEY_HASH, f"V1 key mismatch: '{key_hex}'"

    def test_v2_key(self):
        data = self._load()
        key_hex = data.get("v2_key_hex", "").lower().strip()
        assert len(key_hex) > 0, "v2_key_hex must be non-empty"
        h = hashlib.sha256(key_hex.encode()).hexdigest()
        assert h == V2_KEY_HASH, f"V2 key mismatch: '{key_hex}'"

    def test_v1_key_protection_described(self):
        data = self._load()
        desc = data.get("v1_key_protection", "")
        assert isinstance(desc, str) and len(desc) >= 20, (
            "v1_key_protection must substantively describe the key protection scheme (>= 20 chars)"
        )

    def test_v2_key_protection_described(self):
        data = self._load()
        desc = data.get("v2_key_protection", "")
        assert isinstance(desc, str) and len(desc) >= 20, (
            "v2_key_protection must substantively describe the key protection scheme (>= 20 chars)"
        )

    def test_attack_complexity_values(self):
        """Attack complexity must be one of low/medium/high."""
        data = self._load()
        valid = {"low", "medium", "high"}
        v1c = data.get("v1_attack_complexity", "").lower().strip()
        v2c = data.get("v2_attack_complexity", "").lower().strip()
        assert v1c in valid, f"v1_attack_complexity '{v1c}' not in {valid}"
        assert v2c in valid, f"v2_attack_complexity '{v2c}' not in {valid}"

    def test_v1_attack_complexity_correct(self):
        """V1 uses single-byte XOR obfuscation — attack complexity should be low."""
        data = self._load()
        v1c = data.get("v1_attack_complexity", "").lower().strip()
        assert v1c == "low", (
            f"V1 uses single-byte XOR, a trivially breakable scheme. "
            f"Expected complexity 'low', got '{v1c}'"
        )

    def test_v2_attack_complexity_not_low(self):
        """V2 uses split storage + bit rotation — should be harder than low."""
        data = self._load()
        v2c = data.get("v2_attack_complexity", "").lower().strip()
        assert v2c in ("medium", "high"), (
            f"V2 uses split key storage with bit rotation across separated regions. "
            f"Expected complexity 'medium' or 'high', got '{v2c}'"
        )

    def test_more_secure_version_correct(self):
        """V2's split+rotate scheme is objectively more secure than V1's single-byte XOR."""
        data = self._load()
        verdict = data.get("more_secure_version", "").lower().strip()
        assert verdict == "v2", (
            f"Expected 'v2' as the more secure version (split key + rotation "
            f"vs single-byte XOR), got '{verdict}'"
        )

    def test_justification_substantive(self):
        """Justification must be detailed and reference specific weaknesses."""
        data = self._load()
        j = data.get("justification", "")
        assert isinstance(j, str) and len(j) >= 50, (
            "justification must be a substantive explanation (>= 50 chars)"
        )

    def test_rejected_candidates_count(self):
        """Must evaluate and reject at least 3 key candidates across both firmwares."""
        data = self._load()
        rejected = data.get("rejected_candidates", [])
        assert isinstance(rejected, list)
        assert len(rejected) >= 3, (
            f"Must reject at least 3 key candidates across both firmware versions, "
            f"found {len(rejected)}"
        )

    def test_rejected_candidates_structure(self):
        """Each rejected candidate must have hex, reason, and firmware_version fields."""
        data = self._load()
        rejected = data.get("rejected_candidates", [])
        for i, entry in enumerate(rejected):
            assert isinstance(entry, dict), f"rejected_candidates[{i}] must be an object"
            assert "hex" in entry and isinstance(entry["hex"], str), (
                f"rejected_candidates[{i}] must have a 'hex' string"
            )
            assert "reason" in entry and isinstance(entry["reason"], str), (
                f"rejected_candidates[{i}] must have a 'reason' string"
            )
            assert len(entry["reason"]) >= 10, (
                f"rejected_candidates[{i}].reason must be substantive (>= 10 chars)"
            )

    def test_rejected_from_both_versions(self):
        """Rejected candidates should come from both firmware versions."""
        data = self._load()
        rejected = data.get("rejected_candidates", [])
        versions_seen = set()
        for entry in rejected:
            fv = entry.get("firmware_version", "")
            if isinstance(fv, str):
                versions_seen.add(fv.lower().strip())
        assert "v1" in versions_seen or any("v1" in str(e).lower() for e in rejected), (
            "Must include rejected candidates from V1 firmware"
        )
        assert "v2" in versions_seen or any("v2" in str(e).lower() for e in rejected), (
            "Must include rejected candidates from V2 firmware"
        )


# ============================================================
# V3 key wrapping module — design creation tests
# ============================================================

class TestV3KeyWrap:
    """Verify that the solver designed a key wrapping module that addresses
    the specific weaknesses found in firmware V1 and V2."""

    def _load_module(self):
        spec = importlib.util.spec_from_file_location("v3_keywrap", V3_MODULE_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_module_exists(self):
        assert os.path.isfile(V3_MODULE_PATH), (
            f"V3 key wrapping module not found at {V3_MODULE_PATH}"
        )

    def test_has_wrap_key(self):
        mod = self._load_module()
        assert hasattr(mod, "wrap_key") and callable(mod.wrap_key), (
            "Module must define a callable wrap_key function"
        )

    def test_has_unwrap_key(self):
        mod = self._load_module()
        assert hasattr(mod, "unwrap_key") and callable(mod.unwrap_key), (
            "Module must define a callable unwrap_key function"
        )

    def test_roundtrip_sequential_key(self):
        """wrap then unwrap must recover the original key."""
        mod = self._load_module()
        key = bytes(range(16))
        blob = mod.wrap_key(key)
        recovered = mod.unwrap_key(blob)
        assert recovered == key, (
            f"Round-trip failed: input {key.hex()}, got {recovered.hex()}"
        )

    def test_roundtrip_all_ff(self):
        mod = self._load_module()
        key = bytes([0xFF] * 16)
        blob = mod.wrap_key(key)
        recovered = mod.unwrap_key(blob)
        assert recovered == key

    def test_roundtrip_all_zeros(self):
        mod = self._load_module()
        key = bytes(16)
        blob = mod.wrap_key(key)
        recovered = mod.unwrap_key(blob)
        assert recovered == key

    def test_roundtrip_realistic_key(self):
        """Round-trip with a key resembling the V1/V2 style."""
        mod = self._load_module()
        key = b'\xDE\xAD\xC0\xDE\x13\x37\xBE\xEF\xCA\xFE\xF0\x0D\x42\x42\x42\x42'
        blob = mod.wrap_key(key)
        recovered = mod.unwrap_key(blob)
        assert recovered == key

    def test_blob_minimum_size(self):
        """Blob must be at least 512 bytes — non-trivial wrapping required."""
        mod = self._load_module()
        key = bytes(range(16))
        blob = mod.wrap_key(key)
        assert len(blob) >= 512, (
            f"Blob is {len(blob)} bytes, must be >= 512 to prevent trivial storage"
        )

    def test_key_not_contiguous_in_blob(self):
        """V1 weakness: key stored as contiguous bytes. V3 must not do this."""
        mod = self._load_module()
        key = b'\xDE\xAD\xC0\xDE\x13\x37\xBE\xEF\xCA\xFE\xF0\x0D\x42\x42\x42\x42'
        blob = mod.wrap_key(key)
        assert key not in blob, (
            "Raw key bytes appear as a contiguous 16-byte sequence in the blob — "
            "this is the same weakness as V1 firmware (no obfuscation)"
        )

    def test_single_byte_xor_resistant(self):
        """V1 weakness: single-byte XOR protection. V3 must resist this attack.
        Test that no single XOR constant applied to the key produces a contiguous
        match in the blob."""
        mod = self._load_module()
        key = b'\xDE\xAD\xC0\xDE\x13\x37\xBE\xEF\xCA\xFE\xF0\x0D\x42\x42\x42\x42'
        blob = mod.wrap_key(key)
        for xor_byte in range(256):
            xored = bytes(b ^ xor_byte for b in key)
            assert xored not in blob, (
                f"Key recoverable via single-byte XOR with 0x{xor_byte:02x} — "
                f"same class of weakness as V1 firmware's XOR obfuscation"
            )

    def test_corruption_detected(self):
        """Both V1 and V2 lack tamper detection. V3 must detect corruption —
        either raise an exception or return incorrect key material."""
        mod = self._load_module()
        key = bytes(range(16))
        blob = mod.wrap_key(key)

        # Corrupt every 16th byte throughout the blob
        corrupted = bytearray(blob)
        for i in range(0, len(corrupted), 16):
            corrupted[i] ^= 0xFF

        try:
            recovered = mod.unwrap_key(bytes(corrupted))
            assert recovered != key, (
                "Scheme returned correct key despite extensive corruption "
                "(every 16th byte flipped). V3 must include integrity "
                "verification to detect tampering."
            )
        except Exception:
            pass  # Raising an exception on corruption is correct behavior

    def test_blob_entropy(self):
        """Blob should have meaningful entropy — not mostly zeros or a simple pattern."""
        mod = self._load_module()
        key = bytes(range(16))
        blob = mod.wrap_key(key)

        byte_counts = [0] * 256
        for b in blob:
            byte_counts[b] += 1
        entropy = 0.0
        n = len(blob)
        for count in byte_counts:
            if count > 0:
                p = count / n
                entropy -= p * math.log2(p)
        assert entropy >= 4.0, (
            f"Blob Shannon entropy is {entropy:.2f} bits/byte (need >= 4.0). "
            f"A secure wrapping scheme should produce high-entropy output."
        )

    def test_different_keys_different_blobs(self):
        """Different input keys must produce different blob content."""
        mod = self._load_module()
        key_a = bytes(range(16))
        key_b = bytes(range(16, 32))
        blob_a = mod.wrap_key(key_a)
        blob_b = mod.wrap_key(key_b)
        assert blob_a != blob_b, (
            "Two different keys produced identical blobs — "
            "the wrapping scheme must be key-dependent"
        )
