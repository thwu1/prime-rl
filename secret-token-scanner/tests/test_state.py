
"""
Verification tests for the git repository secret audit.
Independently computes expected tokens and validates the solver's audit output.
"""

import json
import os
import re
import subprocess
import zlib
import pytest

# ---------------------------------------------------------------------------
# Reference implementations (same algorithms as the token spec)
# ---------------------------------------------------------------------------

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def base62_encode(num, length=6):
    if num == 0:
        return BASE62[0] * length
    chars = []
    while num > 0:
        chars.append(BASE62[num % 62])
        num //= 62
    chars.reverse()
    return "".join(chars).rjust(length, "0")


def fnv1a_32(data):
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def make_apx(payload24):
    prefix = "apx_"
    crc = zlib.crc32((prefix + payload24).encode()) & 0xFFFFFFFF
    return prefix + payload24 + base62_encode(crc, 6)


def make_nxs(payload_hex40):
    raw = bytes.fromhex(payload_hex40)
    adler = zlib.adler32(raw) & 0xFFFFFFFF
    return f"nxs-{payload_hex40}-{format(adler, '08x')}"


def make_vlt(variant, payload22):
    prefix = f"vlt_{variant}_"
    h = fnv1a_32((prefix + payload22).encode())
    return prefix + payload22 + base62_encode(h, 6)


def make_apx_bad(payload24):
    prefix = "apx_"
    crc = zlib.crc32((prefix + payload24).encode()) & 0xFFFFFFFF
    wrong = (crc ^ 0x12345678) & 0xFFFFFFFF
    return prefix + payload24 + base62_encode(wrong, 6)


def make_nxs_bad(payload_hex40):
    raw = bytes.fromhex(payload_hex40)
    adler = zlib.adler32(raw) & 0xFFFFFFFF
    wrong = (adler ^ 0xDEADBEEF) & 0xFFFFFFFF
    return f"nxs-{payload_hex40}-{format(wrong, '08x')}"


def make_vlt_bad(variant, payload22):
    prefix = f"vlt_{variant}_"
    h = fnv1a_32((prefix + payload22).encode())
    wrong = (h ^ 0xCAFEBABE) & 0xFFFFFFFF
    return prefix + payload22 + base62_encode(wrong, 6)


# ---------------------------------------------------------------------------
# Checksum verification (independent of setup)
# ---------------------------------------------------------------------------

def verify_apx(token):
    if not re.fullmatch(r"apx_[A-Za-z0-9]{30}", token):
        return False
    payload = token[4:28]
    checksum = token[28:]
    crc = zlib.crc32(("apx_" + payload).encode()) & 0xFFFFFFFF
    return checksum == base62_encode(crc, 6)


def verify_nxs(token):
    m = re.fullmatch(r"nxs-([0-9a-f]{40})-([0-9a-f]{8})", token)
    if not m:
        return False
    raw = bytes.fromhex(m.group(1))
    adler = zlib.adler32(raw) & 0xFFFFFFFF
    return m.group(2) == format(adler, "08x")


def verify_vlt(token):
    for prefix in ("vlt_live_", "vlt_test_"):
        if token.startswith(prefix):
            body = token[len(prefix):]
            if not re.fullmatch(r"[A-Za-z0-9]{28}", body):
                return False
            payload = body[:22]
            checksum = body[22:]
            h = fnv1a_32((prefix + payload).encode())
            return checksum == base62_encode(h, 6)
    return False


def classify_token(token):
    if verify_apx(token):
        return "apx"
    if verify_nxs(token):
        return "nxs"
    if verify_vlt(token):
        return "vlt"
    return None


# ---------------------------------------------------------------------------
# Expected tokens and their metadata
# ---------------------------------------------------------------------------

EXPECTED_TOKENS = {
    make_apx("AbCdEfGhIjKlMnOpQrStUvWx"): {
        "provider": "apx", "location_type": "blob", "reachable": True,
    },
    make_apx("Zy0x1w2v3u4t5s6r7q8p9oNm"): {
        "provider": "apx", "location_type": "blob", "reachable": True,
    },
    make_apx("R4nD0mP4yL04dF0rSt4shK3y"): {
        "provider": "apx", "location_type": "stash", "reachable": True,
    },
    make_nxs("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"): {
        "provider": "nxs", "location_type": "blob", "reachable": True,
    },
    make_nxs("1234567890abcdef1234567890abcdef12345678"): {
        "provider": "nxs", "location_type": "blob", "reachable": True,
    },
    make_nxs("fedcba0987654321fedcba0987654321fedcba09"): {
        "provider": "nxs", "location_type": "tag_annotation", "reachable": True,
    },
    make_vlt("live", "K3yF0rP4yM3nTsS3rv1c3x"): {
        "provider": "vlt", "location_type": "blob", "reachable": True,
    },
    make_vlt("test", "T3st1ngK3yF0rD3vM0d3zz"): {
        "provider": "vlt", "location_type": "blob", "reachable": False,
    },
    make_vlt("live", "Pr0dUcT10nD4t4b4s3Crdz"): {
        "provider": "vlt", "location_type": "note", "reachable": True,
    },
}

DECOY_TOKENS = {
    make_apx_bad("DecoyToken01ForTestingXx"),
    make_apx_bad("AnotherFakeTokenPayload0"),
    make_nxs_bad("0000000000000000000000000000000000000000"),
    make_vlt_bad("live", "F4k3T0k3nTh4tSh0uldF41"),
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def audit_data():
    path = "/app/audit.json"
    assert os.path.exists(path), "audit.json does not exist at /app/audit.json"
    with open(path) as f:
        data = json.load(f)
    assert "findings" in data, "audit.json must contain a 'findings' key"
    return data


@pytest.fixture(scope="module")
def findings(audit_data):
    return audit_data["findings"]


@pytest.fixture(scope="module")
def findings_by_token(findings):
    return {f["token"]: f for f in findings}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutputStructure:
    """Validate the output format."""

    def test_findings_is_list(self, findings):
        assert isinstance(findings, list)

    def test_finding_has_required_keys(self, findings):
        required = {"token", "provider", "location_type", "reachable"}
        for f in findings:
            missing = required - set(f.keys())
            assert not missing, f"Finding missing keys {missing}: {f}"

    def test_location_type_values(self, findings):
        valid = {"blob", "tag_annotation", "note", "stash"}
        for f in findings:
            assert f["location_type"] in valid, (
                f"Invalid location_type '{f['location_type']}' for {f['token']}"
            )

    def test_reachable_is_bool(self, findings):
        for f in findings:
            assert isinstance(f["reachable"], bool), (
                f"reachable must be bool, got {type(f['reachable'])} for {f['token']}"
            )


class TestTokenCounts:
    """Verify exact token counts by provider."""

    def test_total_count(self, findings):
        assert len(findings) == 9, f"Expected 9 findings, got {len(findings)}"

    def test_apx_count(self, findings):
        n = sum(1 for f in findings if f["provider"] == "apx")
        assert n == 3, f"Expected 3 apx tokens, got {n}"

    def test_nxs_count(self, findings):
        n = sum(1 for f in findings if f["provider"] == "nxs")
        assert n == 3, f"Expected 3 nxs tokens, got {n}"

    def test_vlt_count(self, findings):
        n = sum(1 for f in findings if f["provider"] == "vlt")
        assert n == 3, f"Expected 3 vlt tokens, got {n}"


class TestExpectedTokensPresent:
    """Every expected valid token must appear in findings."""

    def test_all_expected_tokens_found(self, findings_by_token):
        for token in EXPECTED_TOKENS:
            assert token in findings_by_token, (
                f"Missing expected token (provider={EXPECTED_TOKENS[token]['provider']}, "
                f"location={EXPECTED_TOKENS[token]['location_type']}): {token}"
            )


class TestProviderClassification:
    """Verify each token's provider is correct."""

    def test_providers_match(self, findings_by_token):
        for token, expected in EXPECTED_TOKENS.items():
            if token in findings_by_token:
                assert findings_by_token[token]["provider"] == expected["provider"], (
                    f"Wrong provider for {token}: "
                    f"expected {expected['provider']}, "
                    f"got {findings_by_token[token]['provider']}"
                )


class TestLocationTypes:
    """Verify each token's location_type is correct."""

    def test_blob_tokens(self, findings_by_token):
        for token, expected in EXPECTED_TOKENS.items():
            if expected["location_type"] == "blob" and token in findings_by_token:
                assert findings_by_token[token]["location_type"] == "blob", (
                    f"Token {token} should be location_type=blob"
                )

    def test_stash_token(self, findings_by_token):
        stash_token = make_apx("R4nD0mP4yL04dF0rSt4shK3y")
        assert stash_token in findings_by_token, "Stash token not found"
        assert findings_by_token[stash_token]["location_type"] == "stash", (
            f"Stash token has wrong location_type: "
            f"{findings_by_token[stash_token]['location_type']}"
        )

    def test_tag_annotation_token(self, findings_by_token):
        tag_token = make_nxs("fedcba0987654321fedcba0987654321fedcba09")
        assert tag_token in findings_by_token, "Tag annotation token not found"
        assert findings_by_token[tag_token]["location_type"] == "tag_annotation", (
            f"Tag token has wrong location_type: "
            f"{findings_by_token[tag_token]['location_type']}"
        )

    def test_note_token(self, findings_by_token):
        note_token = make_vlt("live", "Pr0dUcT10nD4t4b4s3Crdz")
        assert note_token in findings_by_token, "Note token not found"
        assert findings_by_token[note_token]["location_type"] == "note", (
            f"Note token has wrong location_type: "
            f"{findings_by_token[note_token]['location_type']}"
        )


class TestReachability:
    """Verify reachability flags."""

    def test_unreachable_token(self, findings_by_token):
        unreachable_token = make_vlt("test", "T3st1ngK3yF0rD3vM0d3zz")
        assert unreachable_token in findings_by_token, "Unreachable token not found"
        assert findings_by_token[unreachable_token]["reachable"] is False, (
            "Token from amended commit should be unreachable (reachable=false)"
        )

    def test_reachable_tokens(self, findings_by_token):
        unreachable_token = make_vlt("test", "T3st1ngK3yF0rD3vM0d3zz")
        for token, expected in EXPECTED_TOKENS.items():
            if expected["reachable"] and token in findings_by_token:
                assert findings_by_token[token]["reachable"] is True, (
                    f"Token {token} should be reachable"
                )


class TestChecksumValidation:
    """Every reported token must have a valid integrity checksum."""

    def test_all_findings_pass_checksum(self, findings):
        for f in findings:
            provider = classify_token(f["token"])
            assert provider is not None, (
                f"Token fails checksum validation: {f['token']}"
            )
            assert provider == f["provider"], (
                f"Provider mismatch: reported {f['provider']}, verified {provider}"
            )


class TestDecoyExclusion:
    """Tokens with invalid checksums must be excluded."""

    def test_no_decoy_tokens_in_findings(self, findings_by_token):
        for decoy in DECOY_TOKENS:
            assert decoy not in findings_by_token, (
                f"Decoy token with invalid checksum should be excluded: {decoy}"
            )


class TestNoDuplicates:
    """No duplicate token values allowed."""

    def test_unique_token_values(self, findings):
        tokens = [f["token"] for f in findings]
        assert len(tokens) == len(set(tokens)), (
            f"Duplicate tokens found: {[t for t in tokens if tokens.count(t) > 1]}"
        )


class TestRepoSanityChecks:
    """Verify the git repo has the expected structure for this audit."""

    def test_repo_exists(self):
        assert os.path.isdir("/app/repo/.git"), "Git repo not found at /app/repo"

    def test_has_stash_entries(self):
        r = subprocess.run(
            ["git", "stash", "list"], cwd="/app/repo",
            capture_output=True, text=True
        )
        assert r.stdout.strip(), "No stash entries found in repo"

    def test_has_git_notes(self):
        r = subprocess.run(
            ["git", "notes", "list"], cwd="/app/repo",
            capture_output=True, text=True
        )
        assert r.stdout.strip(), "No git notes found in repo"

    def test_has_annotated_tag(self):
        r = subprocess.run(
            ["git", "for-each-ref", "--format=%(objecttype)", "refs/tags/v1.0"],
            cwd="/app/repo", capture_output=True, text=True
        )
        assert r.stdout.strip() == "tag", "v1.0 is not an annotated tag"

    def test_has_unreachable_objects(self):
        r = subprocess.run(
            ["git", "fsck", "--unreachable", "--no-reflogs"],
            cwd="/app/repo", capture_output=True, text=True
        )
        combined = r.stdout + r.stderr
        assert "unreachable" in combined or "dangling" in combined, (
            "No unreachable objects found — amended commit should exist"
        )

    def test_head_is_clean(self):
        """HEAD should not contain any valid tokens."""
        r = subprocess.run(
            ["git", "grep", "-E",
             r"apx_[A-Za-z0-9]{30}|nxs-[0-9a-f]{40}-[0-9a-f]{8}|vlt_(live|test)_[A-Za-z0-9]{28}",
             "HEAD"],
            cwd="/app/repo", capture_output=True, text=True
        )
        # git grep may find decoys, but no VALID tokens should be at HEAD
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                # Extract potential tokens and verify none are valid
                for pat in [
                    re.compile(r"apx_[A-Za-z0-9]{30}"),
                    re.compile(r"nxs-[0-9a-f]{40}-[0-9a-f]{8}"),
                    re.compile(r"vlt_(?:live|test)_[A-Za-z0-9]{28}"),
                ]:
                    for m in pat.finditer(line):
                        assert classify_token(m.group()) is None, (
                            f"Valid token found at HEAD (should be cleaned): {m.group()}"
                        )
