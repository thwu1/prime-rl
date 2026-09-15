
import json
import os
import re
import subprocess
import pytest

BINARY_ALPHA = "/app/license_check_alpha"
BINARY_BETA = "/app/license_check_beta"
KEYGEN_ALPHA = "/app/keygen_alpha.py"
KEYGEN_BETA = "/app/keygen_beta.py"
ANALYSIS_FILE = "/app/analysis.json"
COLLISION_FILE = "/app/collision.json"
PATCHED_BINARY = "/app/license_check_patched"
PATCHED_SOURCE = "/app/license_check_patched.c"
PATCHED_KEYGEN = "/app/keygen_patched.py"
AUDIT_FILE = "/app/audit.json"

TEST_USERNAMES = [
    "admin",
    "root",
    "alice",
    "bob",
    "testuser1",
    "John Doe",
    "CrackMe",
    "x",
]

# The exact beta S-box bytes for verifying the patched binary preserves it
BETA_SBOX_BYTES = bytes([
    0xB7, 0x0E, 0xCF, 0x39, 0x2F, 0x85, 0xF8, 0x0D, 0xDC, 0x9A, 0x50, 0x27, 0xC9, 0x3A, 0x94, 0x91,
    0x41, 0x75, 0x78, 0x57, 0x1A, 0x80, 0xA8, 0xD3, 0x09, 0xD7, 0xA7, 0xEC, 0x5C, 0x5A, 0x06, 0xD1,
    0x18, 0x3B, 0x88, 0x77, 0x1D, 0xAA, 0xBB, 0x8D, 0x17, 0xB4, 0x98, 0x34, 0x9D, 0x70, 0x99, 0x25,
    0x15, 0x12, 0x16, 0xD0, 0x93, 0xA5, 0x68, 0xB8, 0x28, 0x86, 0xB6, 0x23, 0xF1, 0xFD, 0x0A, 0x6C,
    0x7E, 0xC5, 0x56, 0xF0, 0x11, 0x29, 0x1F, 0x46, 0xC7, 0x6B, 0xF4, 0x24, 0x92, 0x08, 0xC1, 0x3C,
    0x51, 0xCA, 0xB9, 0xE7, 0x4A, 0x2A, 0xCC, 0xD8, 0x87, 0x14, 0x42, 0x96, 0x53, 0x66, 0xDA, 0xF5,
    0xA4, 0x79, 0xC3, 0xAD, 0xC4, 0x13, 0xFC, 0x8B, 0xDB, 0xBD, 0x97, 0xAC, 0x4E, 0xE2, 0x4C, 0x3F,
    0x20, 0x38, 0x43, 0xD5, 0x21, 0xBC, 0x73, 0xBF, 0x30, 0x71, 0xA6, 0x55, 0xC8, 0x47, 0xE4, 0x59,
    0x3E, 0x62, 0xEE, 0x04, 0x33, 0x6F, 0x2B, 0x19, 0x89, 0xEA, 0xC2, 0x9F, 0x0F, 0x1C, 0x7A, 0x31,
    0xB1, 0x9B, 0x2C, 0x05, 0xF6, 0x01, 0xCD, 0x00, 0xE9, 0x44, 0x72, 0xDD, 0x02, 0x84, 0x83, 0xA1,
    0x63, 0xD4, 0x5F, 0x82, 0xDF, 0xCE, 0x0B, 0xE6, 0xE8, 0xE3, 0x8A, 0x52, 0xFA, 0x7B, 0x22, 0xBA,
    0xFF, 0xAF, 0x32, 0x49, 0xCB, 0xBE, 0xAB, 0x9E, 0x90, 0x03, 0xDE, 0x5E, 0xA2, 0x4D, 0xB5, 0xB0,
    0x64, 0xFB, 0xD9, 0xB3, 0x1B, 0x6D, 0xE0, 0x65, 0x69, 0x61, 0x8F, 0xA0, 0x3D, 0x5B, 0xE1, 0xC0,
    0x6E, 0x74, 0x48, 0xF9, 0xB2, 0x67, 0x6A, 0x2E, 0xF2, 0x45, 0xD6, 0x58, 0x36, 0xEB, 0x81, 0x1E,
    0xF3, 0x10, 0x35, 0xED, 0x95, 0x7D, 0x8C, 0xA9, 0x7C, 0x40, 0xE5, 0xD2, 0x4B, 0xA3, 0x76, 0x7F,
    0x07, 0x8E, 0x37, 0x2D, 0xFE, 0xF7, 0x5D, 0x26, 0x54, 0xEF, 0x9C, 0xAE, 0x0C, 0x4F, 0x60, 0xC6,
])


def run_keygen(keygen_path: str, username: str) -> str:
    result = subprocess.run(
        ["python3", keygen_path, username],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Keygen {keygen_path} failed for '{username}': stderr={result.stderr!r}"
    )
    key = result.stdout.strip()
    assert key, f"Keygen produced empty output for '{username}'"
    return key


def validate_key(binary: str, username: str, key: str) -> bool:
    stdin_data = f"{username}\n{key}\n"
    result = subprocess.run(
        [binary],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() == "VALID"


def check_key_format(key: str):
    parts = key.split("-")
    assert len(parts) == 4, f"Key should have 4 groups, got {len(parts)}: {key!r}"
    for part in parts:
        assert len(part) == 4, f"Each group should be 4 chars, got {len(part)}: {part!r}"
        assert all(c in "0123456789abcdef" for c in part), (
            f"Each group should be lowercase hex, got: {part!r}"
        )


# ── Alpha keygen tests ──


class TestAlphaKeygen:
    def test_keygen_exists(self):
        assert os.path.isfile(KEYGEN_ALPHA), f"Keygen not found at {KEYGEN_ALPHA}"

    def test_binary_exists(self):
        assert os.path.isfile(BINARY_ALPHA)
        assert os.access(BINARY_ALPHA, os.X_OK)

    @pytest.mark.parametrize("username", TEST_USERNAMES)
    def test_key_format(self, username):
        key = run_keygen(KEYGEN_ALPHA, username)
        check_key_format(key)

    @pytest.mark.parametrize("username", TEST_USERNAMES)
    def test_key_validates(self, username):
        key = run_keygen(KEYGEN_ALPHA, username)
        assert validate_key(BINARY_ALPHA, username, key), (
            f"Alpha key '{key}' not accepted for '{username}'"
        )

    @pytest.mark.parametrize("username", TEST_USERNAMES)
    def test_key_deterministic(self, username):
        key1 = run_keygen(KEYGEN_ALPHA, username)
        key2 = run_keygen(KEYGEN_ALPHA, username)
        assert key1 == key2, f"Non-deterministic for '{username}': '{key1}' vs '{key2}'"


# ── Beta keygen tests ──


class TestBetaKeygen:
    def test_keygen_exists(self):
        assert os.path.isfile(KEYGEN_BETA), f"Keygen not found at {KEYGEN_BETA}"

    def test_binary_exists(self):
        assert os.path.isfile(BINARY_BETA)
        assert os.access(BINARY_BETA, os.X_OK)

    @pytest.mark.parametrize("username", TEST_USERNAMES)
    def test_key_format(self, username):
        key = run_keygen(KEYGEN_BETA, username)
        check_key_format(key)

    @pytest.mark.parametrize("username", TEST_USERNAMES)
    def test_key_validates(self, username):
        key = run_keygen(KEYGEN_BETA, username)
        assert validate_key(BINARY_BETA, username, key), (
            f"Beta key '{key}' not accepted for '{username}'"
        )

    @pytest.mark.parametrize("username", TEST_USERNAMES)
    def test_key_deterministic(self, username):
        key1 = run_keygen(KEYGEN_BETA, username)
        key2 = run_keygen(KEYGEN_BETA, username)
        assert key1 == key2, f"Non-deterministic for '{username}': '{key1}' vs '{key2}'"


# ── Security analysis tests ──


class TestAnalysis:
    def test_analysis_file_exists(self):
        assert os.path.isfile(ANALYSIS_FILE), f"Analysis not found at {ANALYSIS_FILE}"

    def test_analysis_structure(self):
        with open(ANALYSIS_FILE) as f:
            data = json.load(f)
        assert "weak_scheme" in data, "Missing 'weak_scheme' field"
        assert "effective_bits" in data, "Missing 'effective_bits' field"
        assert "reason" in data, "Missing 'reason' field"

    def test_weak_scheme_identified_correctly(self):
        with open(ANALYSIS_FILE) as f:
            data = json.load(f)
        assert data["weak_scheme"] == "beta", (
            f"Wrong weak scheme identified: expected 'beta', got '{data['weak_scheme']}'"
        )

    def test_effective_bits_correct(self):
        with open(ANALYSIS_FILE) as f:
            data = json.load(f)
        bits = data["effective_bits"]
        assert isinstance(bits, int), f"effective_bits should be int, got {type(bits)}"
        assert bits <= 32, (
            f"effective_bits should be <= 32, got {bits}"
        )
        assert bits >= 16, (
            f"effective_bits implausibly low: {bits}"
        )

    def test_reason_is_substantive(self):
        with open(ANALYSIS_FILE) as f:
            data = json.load(f)
        reason = data["reason"]
        assert isinstance(reason, str), "reason should be a string"
        assert len(reason) >= 40, (
            f"reason too short ({len(reason)} chars), needs technical detail"
        )


# ── Collision tests ──


class TestCollision:
    def test_collision_file_exists(self):
        assert os.path.isfile(COLLISION_FILE), f"Collision file not at {COLLISION_FILE}"

    def test_collision_structure(self):
        with open(COLLISION_FILE) as f:
            data = json.load(f)
        assert "username1" in data, "Missing 'username1'"
        assert "username2" in data, "Missing 'username2'"
        assert "key" in data, "Missing 'key'"

    def test_usernames_are_distinct(self):
        with open(COLLISION_FILE) as f:
            data = json.load(f)
        assert data["username1"] != data["username2"], (
            f"Usernames must be different, both are '{data['username1']}'"
        )

    def test_usernames_are_valid(self):
        with open(COLLISION_FILE) as f:
            data = json.load(f)
        for field in ["username1", "username2"]:
            u = data[field]
            assert isinstance(u, str), f"{field} should be a string"
            assert 1 <= len(u) <= 64, f"{field} length {len(u)} out of range"
            assert u.isascii(), f"{field} contains non-ASCII characters"
            assert all(32 <= ord(c) <= 126 for c in u), (
                f"{field} contains non-printable characters"
            )

    def test_key_format_valid(self):
        with open(COLLISION_FILE) as f:
            data = json.load(f)
        check_key_format(data["key"])

    def test_collision_verified_by_binary(self):
        """Both usernames must produce the same key under the beta binary."""
        with open(COLLISION_FILE) as f:
            data = json.load(f)
        u1, u2, claimed_key = data["username1"], data["username2"], data["key"]

        assert validate_key(BINARY_BETA, u1, claimed_key), (
            f"Beta binary rejected key '{claimed_key}' for username1 '{u1}'"
        )
        assert validate_key(BINARY_BETA, u2, claimed_key), (
            f"Beta binary rejected key '{claimed_key}' for username2 '{u2}'"
        )

    def test_collision_finder_exists(self):
        assert os.path.isfile("/app/find_collision.py"), (
            "find_collision.py not found at /app/find_collision.py"
        )


# ── Patched scheme tests ──


class TestPatchedScheme:
    """Verify the solver designed a correct hardened replacement for the weak scheme."""

    def test_source_exists(self):
        assert os.path.isfile(PATCHED_SOURCE), (
            f"Patched source not found at {PATCHED_SOURCE}"
        )

    def test_binary_compiled(self):
        """Patched source must compile (compilation performed in test.sh)."""
        assert os.path.isfile(PATCHED_BINARY) and os.access(PATCHED_BINARY, os.X_OK), (
            "Patched binary not found or not executable — compilation may have failed. "
            "Check /app/compile_errors.txt for details."
        )

    def test_keygen_exists(self):
        assert os.path.isfile(PATCHED_KEYGEN), (
            f"Patched keygen not found at {PATCHED_KEYGEN}"
        )

    @pytest.mark.parametrize("username", TEST_USERNAMES)
    def test_key_format(self, username):
        key = run_keygen(PATCHED_KEYGEN, username)
        check_key_format(key)

    @pytest.mark.parametrize("username", TEST_USERNAMES)
    def test_key_validates(self, username):
        """Patched keygen must produce keys accepted by the patched binary."""
        key = run_keygen(PATCHED_KEYGEN, username)
        assert validate_key(PATCHED_BINARY, username, key), (
            f"Patched binary rejected key '{key}' for '{username}'"
        )

    @pytest.mark.parametrize("username", TEST_USERNAMES[:4])
    def test_old_beta_keys_rejected(self, username):
        """Keys from the original weak scheme must NOT work on the patched binary."""
        old_key = run_keygen(KEYGEN_BETA, username)
        assert not validate_key(PATCHED_BINARY, username, old_key), (
            f"Patched binary accepted old beta key for '{username}' — "
            f"hash function may not have been changed"
        )

    def test_preserves_beta_sbox_in_binary(self):
        """The compiled patched binary must contain beta's exact 256-byte S-box."""
        with open(PATCHED_BINARY, "rb") as f:
            binary_data = f.read()
        assert BETA_SBOX_BYTES in binary_data, (
            "Patched binary does not contain beta's S-box — "
            "the S-box must be preserved unchanged"
        )

    def test_preserves_feistel_constants_in_source(self):
        """Verify the patched source retains beta's Feistel round constants."""
        with open(PATCHED_SOURCE) as f:
            source = f.read().upper()
        for const in ["CAFEBABE", "8BADF00D", "DEADC0DE", "31415926",
                      "BAADF00D", "1BADB002", "FEE1DEAD", "0D15EA5E"]:
            assert const in source, (
                f"Missing Feistel constant 0x{const} in patched source"
            )

    def test_preserves_finalization_in_source(self):
        """Verify the patched source retains beta's finalization constants."""
        with open(PATCHED_SOURCE) as f:
            source = f.read().upper()
        assert "BF58476D1CE4E5B9" in source, (
            "Missing finalization constant 0xBF58476D1CE4E5B9"
        )
        assert "94D049BB133111EB" in source, (
            "Missing finalization constant 0x94D049BB133111EB"
        )

    def test_no_32bit_hash_bottleneck(self):
        """Verify the hash function no longer uses beta's 32-bit FNV-1 init."""
        with open(PATCHED_SOURCE) as f:
            source = f.read()
        # Strip comments to avoid false positives from explanatory text
        source_clean = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)
        source_clean = re.sub(r'//.*$', '', source_clean, flags=re.MULTILINE)
        source_upper = source_clean.upper().replace(" ", "")
        assert "0X811C9DC5" not in source_upper, (
            "Patched hash_username still contains beta's 32-bit FNV-1 init value "
            "0x811C9DC5 — the entropy bottleneck has not been eliminated"
        )

    @pytest.mark.parametrize("username", TEST_USERNAMES)
    def test_key_deterministic(self, username):
        key1 = run_keygen(PATCHED_KEYGEN, username)
        key2 = run_keygen(PATCHED_KEYGEN, username)
        assert key1 == key2, (
            f"Patched keygen non-deterministic for '{username}': '{key1}' vs '{key2}'"
        )


# ── Comparative security audit tests ──


class TestSecurityAudit:
    """Verify the solver produced a correct comparative security evaluation."""

    def test_audit_file_exists(self):
        assert os.path.isfile(AUDIT_FILE), f"Audit not found at {AUDIT_FILE}"

    def test_audit_top_level_structure(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        assert "schemes" in data, "Missing 'schemes' field"
        assert "recommended_scheme" in data, "Missing 'recommended_scheme' field"
        assert "recommendation_rationale" in data, "Missing 'recommendation_rationale'"
        assert isinstance(data["schemes"], list), "'schemes' must be an array"
        assert len(data["schemes"]) == 3, (
            f"Expected 3 schemes (alpha, beta, patched), got {len(data['schemes'])}"
        )

    def test_all_three_schemes_present(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        names = {s["name"] for s in data["schemes"]}
        assert names == {"alpha", "beta", "patched"}, (
            f"Expected schemes alpha, beta, patched — got {names}"
        )

    def test_scheme_entry_structure(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        required_fields = [
            "name", "hash_width_bits", "collision_complexity",
            "key_space_bits", "verdict", "justification"
        ]
        for scheme in data["schemes"]:
            for field in required_fields:
                assert field in scheme, (
                    f"Scheme '{scheme.get('name', '?')}' missing field '{field}'"
                )
            assert isinstance(scheme["hash_width_bits"], int)
            assert isinstance(scheme["key_space_bits"], int)
            assert scheme["verdict"] in ("secure", "insecure"), (
                f"Verdict must be 'secure' or 'insecure', got '{scheme['verdict']}'"
            )

    def test_beta_identified_insecure(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        beta = next(s for s in data["schemes"] if s["name"] == "beta")
        assert beta["verdict"] == "insecure", (
            f"Beta should be 'insecure', got '{beta['verdict']}'"
        )
        assert beta["hash_width_bits"] <= 32, (
            f"Beta hash width should be <= 32, got {beta['hash_width_bits']}"
        )
        assert beta["key_space_bits"] <= 32, (
            f"Beta key space should be <= 32, got {beta['key_space_bits']}"
        )

    def test_alpha_identified_secure(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        alpha = next(s for s in data["schemes"] if s["name"] == "alpha")
        assert alpha["verdict"] == "secure", (
            f"Alpha should be 'secure', got '{alpha['verdict']}'"
        )
        assert alpha["hash_width_bits"] >= 64, (
            f"Alpha hash width should be >= 64, got {alpha['hash_width_bits']}"
        )

    def test_patched_identified_secure(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        patched = next(s for s in data["schemes"] if s["name"] == "patched")
        assert patched["verdict"] == "secure", (
            f"Patched should be 'secure', got '{patched['verdict']}'"
        )
        assert patched["hash_width_bits"] >= 64, (
            f"Patched hash width should be >= 64, got {patched['hash_width_bits']}"
        )
        assert patched["key_space_bits"] >= 64, (
            f"Patched key space should be >= 64, got {patched['key_space_bits']}"
        )

    def test_recommended_scheme_not_beta(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        assert data["recommended_scheme"] in ("alpha", "patched"), (
            f"Recommended scheme should be 'alpha' or 'patched', "
            f"not '{data['recommended_scheme']}'"
        )

    def test_recommendation_rationale_substantive(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        rationale = data["recommendation_rationale"]
        assert isinstance(rationale, str), "recommendation_rationale should be a string"
        assert len(rationale) >= 80, (
            f"Rationale too short ({len(rationale)} chars), "
            f"needs substantive technical justification"
        )

    def test_justifications_substantive(self):
        with open(AUDIT_FILE) as f:
            data = json.load(f)
        for scheme in data["schemes"]:
            assert len(scheme["justification"]) >= 50, (
                f"Justification for '{scheme['name']}' too short "
                f"({len(scheme['justification'])} chars)"
            )
