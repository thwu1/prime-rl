
import json
import os
import re
import subprocess
import pytest


# Pre-computed SHA-256 hashes of the full token strings (deterministic from setup)
TOKEN_IDS = {
    "t1_ghp_critical": "bda23faf6fb3c37f24bca16137b2781e137a8ac993a950163fb6e47ee32f6a8a",
    "t2_isv_critical": "ac3c91bd776fdd87cf1e42bab81316de87721d224d167a24b3f32d5234a3b8b7",
    "t3_ghs_medium":   "a27f11037508c2ad8a78efa2c4247e2086a90a6cd8fc6af853afdb3026ac59c2",
    "t4_art_high":     "4dc522423e4d09eef82406e5a832c4dabc173ca293c65eae99f9a1d1d11c0639",
    "t5_art_medium":   "fb1ff26c3236071cb8a997fd210ee973b741049ac729fc21fe467c2a90952763",
    "t6_gho_high":     "5ef56364a46199cdf462140276f8cbda6c34b284db59b1fa82a146301b115837",
    "t7_ghp_low":      "b233b4cd0b845fb9ea6c5fd08b3b6dc4204e4d38565360b698082e60e843edc3",
}

EXPECTED = {
    TOKEN_IDS["t1_ghp_critical"]: {
        "provider": "github", "checksum_valid": True,
        "present_at_head": True, "rotated": False, "risk_level": "critical",
        "redacted_prefix": "ghp_", "redacted_suffix": "3W9iub", "redacted_len": 40,
    },
    TOKEN_IDS["t2_isv_critical"]: {
        "provider": "internal_svc", "checksum_valid": True,
        "present_at_head": True, "rotated": False, "risk_level": "critical",
        "redacted_prefix": "isv_", "redacted_suffix": "6c7cb325", "redacted_len": 52,
    },
    TOKEN_IDS["t3_ghs_medium"]: {
        "provider": "github", "checksum_valid": True,
        "present_at_head": False, "rotated": True, "risk_level": "medium",
        "redacted_prefix": "ghs_", "redacted_suffix": "0Dadh7", "redacted_len": 40,
    },
    TOKEN_IDS["t4_art_high"]: {
        "provider": "artifact_registry", "checksum_valid": True,
        "present_at_head": False, "rotated": False, "risk_level": "high",
        "redacted_prefix": "art_", "redacted_suffix": "3aYVlc", "redacted_len": 34,
    },
    TOKEN_IDS["t5_art_medium"]: {
        "provider": "artifact_registry", "checksum_valid": True,
        "present_at_head": False, "rotated": True, "risk_level": "medium",
        "redacted_prefix": "art_", "redacted_suffix": "3a794x", "redacted_len": 34,
    },
    TOKEN_IDS["t6_gho_high"]: {
        "provider": "github", "checksum_valid": True,
        "present_at_head": False, "rotated": False, "risk_level": "high",
        "redacted_prefix": "gho_", "redacted_suffix": "19rbtW", "redacted_len": 40,
    },
    TOKEN_IDS["t7_ghp_low"]: {
        "provider": "github", "checksum_valid": False,
        "present_at_head": True, "rotated": False, "risk_level": "low",
        "redacted_prefix": "ghp_", "redacted_suffix": "000000", "redacted_len": 40,
    },
}

RISK_PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def load_report():
    with open("/app/audit_report.json") as f:
        return json.load(f)


def find_by_id(report, token_id):
    return [r for r in report if r["token_id"] == token_id]


class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists("/app/audit_report.json"), \
            "Audit report must be written to /app/audit_report.json"

    def test_report_is_json_array(self):
        report = load_report()
        assert isinstance(report, list), "Report must be a JSON array"

    def test_report_has_seven_entries(self):
        report = load_report()
        assert len(report) == 7, f"Expected 7 unique tokens, got {len(report)}"

    def test_required_fields_present(self):
        report = load_report()
        required = {"token_id", "provider", "token_redacted", "checksum_valid",
                     "first_seen_commit", "first_seen_date", "present_at_head",
                     "rotated", "risk_level"}
        for i, entry in enumerate(report):
            missing = required - set(entry.keys())
            assert not missing, f"Entry {i} missing fields: {missing}"

    def test_all_expected_tokens_found(self):
        report = load_report()
        found_ids = {r["token_id"] for r in report}
        for label, tid in TOKEN_IDS.items():
            assert tid in found_ids, f"Token {label} not found in report"


class TestSortOrder:
    def test_risk_priority_order(self):
        report = load_report()
        risk_vals = [RISK_PRIORITY[r["risk_level"]] for r in report]
        assert risk_vals == sorted(risk_vals), \
            "Report must be sorted by risk: critical, high, medium, low"

    def test_date_order_within_risk(self):
        report = load_report()
        by_risk = {}
        for r in report:
            by_risk.setdefault(r["risk_level"], []).append(r["first_seen_date"])
        for risk, dates in by_risk.items():
            assert dates == sorted(dates), \
                f"Within {risk}, entries must be sorted by first_seen_date ascending"


class TestCriticalTokens:
    """Tokens present at HEAD with valid checksums, not rotated."""

    def test_github_pat_crc32(self):
        """ghp_ token in src/config.py — CRC32-Base62 checksum validation."""
        report = load_report()
        tid = TOKEN_IDS["t1_ghp_critical"]
        matches = find_by_id(report, tid)
        assert len(matches) == 1, "ghp_ token at HEAD must be found"
        r = matches[0]
        assert r["provider"] == "github"
        assert r["checksum_valid"] is True
        assert r["present_at_head"] is True
        assert r["rotated"] is False
        assert r["risk_level"] == "critical"

    def test_internal_svc_hkdf_hmac(self):
        """isv_ token in deploy/env.sh — HKDF key derivation + HMAC-SHA256."""
        report = load_report()
        tid = TOKEN_IDS["t2_isv_critical"]
        matches = find_by_id(report, tid)
        assert len(matches) == 1, "isv_ token (HKDF checksum) at HEAD must be found"
        r = matches[0]
        assert r["provider"] == "internal_svc"
        assert r["checksum_valid"] is True
        assert r["present_at_head"] is True
        assert r["rotated"] is False
        assert r["risk_level"] == "critical"


class TestHighRiskTokens:
    """Valid tokens reachable from refs but not at HEAD, not rotated."""

    def test_artifact_registry_in_history(self):
        """art_ token removed from deploy.yml but in reachable git history."""
        report = load_report()
        tid = TOKEN_IDS["t4_art_high"]
        matches = find_by_id(report, tid)
        assert len(matches) == 1, "art_ token in reachable history must be found"
        r = matches[0]
        assert r["provider"] == "artifact_registry"
        assert r["checksum_valid"] is True
        assert r["present_at_head"] is False
        assert r["rotated"] is False
        assert r["risk_level"] == "high"

    def test_oauth_token_in_stash(self):
        """gho_ token only in git stash — requires stash traversal."""
        report = load_report()
        tid = TOKEN_IDS["t6_gho_high"]
        matches = find_by_id(report, tid)
        assert len(matches) == 1, "gho_ token in stash must be found"
        r = matches[0]
        assert r["provider"] == "github"
        assert r["checksum_valid"] is True
        assert r["present_at_head"] is False
        assert r["rotated"] is False
        assert r["risk_level"] == "high"


class TestMediumRiskTokens:
    """Rotated tokens and dangling-only tokens."""

    def test_rotated_github_token_in_history(self):
        """ghs_ token removed and rotated — rotation log cross-reference."""
        report = load_report()
        tid = TOKEN_IDS["t3_ghs_medium"]
        matches = find_by_id(report, tid)
        assert len(matches) == 1, "ghs_ rotated token must be found"
        r = matches[0]
        assert r["provider"] == "github"
        assert r["checksum_valid"] is True
        assert r["rotated"] is True
        assert r["risk_level"] == "medium"

    def test_dangling_commit_token(self):
        """art_ token only in dangling commit from amended branch — requires git fsck."""
        report = load_report()
        tid = TOKEN_IDS["t5_art_medium"]
        matches = find_by_id(report, tid)
        assert len(matches) == 1, "art_ token in dangling commit must be found"
        r = matches[0]
        assert r["provider"] == "artifact_registry"
        assert r["checksum_valid"] is True
        assert r["present_at_head"] is False
        assert r["risk_level"] == "medium"


class TestLowRiskToken:
    """Token with invalid checksum."""

    def test_invalid_checksum_detected(self):
        """ghp_ token with fabricated checksum — should be low risk."""
        report = load_report()
        tid = TOKEN_IDS["t7_ghp_low"]
        matches = find_by_id(report, tid)
        assert len(matches) == 1, "ghp_ token with invalid checksum must be found"
        r = matches[0]
        assert r["provider"] == "github"
        assert r["checksum_valid"] is False
        assert r["present_at_head"] is True
        assert r["risk_level"] == "low"


class TestCommitReferences:
    """Validate first_seen_commit and first_seen_date fields."""

    def test_commit_hashes_are_40_hex(self):
        report = load_report()
        pat = re.compile(r"^[0-9a-f]{40}$")
        for r in report:
            assert pat.match(r["first_seen_commit"]), \
                f"first_seen_commit must be 40-char hex, got: {r['first_seen_commit']}"

    def test_commits_exist_in_repo(self):
        report = load_report()
        for r in report:
            result = subprocess.run(
                ["git", "cat-file", "-t", r["first_seen_commit"]],
                capture_output=True, text=True, cwd="/app/repo"
            )
            assert result.stdout.strip() == "commit", \
                f"Commit {r['first_seen_commit'][:12]} does not exist in repo"

    def test_dates_are_iso8601(self):
        report = load_report()
        for r in report:
            assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", r["first_seen_date"]), \
                f"first_seen_date must be ISO 8601, got: {r['first_seen_date']}"


class TestTokenRedaction:
    """Verify token_redacted format: prefix + asterisks + checksum."""

    def test_redaction_length_and_prefix(self):
        report = load_report()
        for r in report:
            tid = r["token_id"]
            if tid not in EXPECTED:
                continue
            exp = EXPECTED[tid]
            redacted = r["token_redacted"]
            assert len(redacted) == exp["redacted_len"], \
                f"Redacted length for {exp['redacted_prefix']} token: expected {exp['redacted_len']}, got {len(redacted)}"
            assert redacted.startswith(exp["redacted_prefix"]), \
                f"Redacted should start with {exp['redacted_prefix']}"

    def test_redaction_body_asterisks(self):
        report = load_report()
        for r in report:
            tid = r["token_id"]
            if tid not in EXPECTED:
                continue
            exp = EXPECTED[tid]
            redacted = r["token_redacted"]
            prefix_len = len(exp["redacted_prefix"])
            suffix_len = len(exp["redacted_suffix"])
            body = redacted[prefix_len:-suffix_len]
            assert all(c == "*" for c in body), \
                f"Body portion should be all asterisks, got: {body[:20]}..."

    def test_redaction_checksum_preserved(self):
        report = load_report()
        for r in report:
            tid = r["token_id"]
            if tid not in EXPECTED:
                continue
            exp = EXPECTED[tid]
            redacted = r["token_redacted"]
            assert redacted.endswith(exp["redacted_suffix"]), \
                f"Checksum suffix should be {exp['redacted_suffix']}, got: {redacted[-8:]}"
