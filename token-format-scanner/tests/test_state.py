
import json
import os
import zlib


# ---------------------------------------------------------------------------
# Independent checksum verification (not imported from agent code)
# ---------------------------------------------------------------------------

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _base62_encode(num, length=6):
    result = []
    for _ in range(length):
        result.append(CHARSET[num % 62])
        num //= 62
    return "".join(reversed(result))


def _verify_checksum(token):
    """Return True if the token's embedded checksum matches a fresh computation."""
    if len(token) != 40 or token[3] != "_" or token[:3] not in (
        "ghp", "gho", "ghu", "ghs", "ghr",
    ):
        return False
    crc = zlib.crc32(token[:34].encode()) & 0xFFFFFFFF
    return _base62_encode(crc, 6) == token[34:]


# ---------------------------------------------------------------------------
# Expected token sets (ground truth)
# ---------------------------------------------------------------------------

# Tokens discoverable in the file corpus (plaintext, base64, base64→JSON,
# URL query params, and inside an AES-256-CBC encrypted vault)
CORPUS_TOKENS = {
    # app.py — plaintext
    "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012339KRed",
    # app.py — plaintext, invalid checksum (rotated copy)
    "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012339KRee",
    # config.yaml — plaintext
    "gho_X5v8tG2aMnKpYeRcHdFjBwLqNz1S9U1vlLjs",
    # .env — plaintext
    "ghr_kW4nT8yHqM2vXjRf6BdLpS0cGiA5eZ35PrS2",
    # secrets.json — base64 encoded
    "ghu_p7Qm2KxRfN3sYhTv9WbJdL0cGiA5eZ1LCYai",
    # secrets.json — base64 → JSON blob
    "ghs_mN3xR7vKpL9sYhTf2WbJdQ0cGiA5eZ20vLsV",
    # access.log — in URL query string
    "ghp_rJ6bV3wFtP8xZlNk1CdMqU0hGiA5eY3q4zth",
    # deploy.sh — plaintext
    "gho_sK9dW2yHuQ4vXmRf7BeLpT0cGjA5fZ0tLYXR",
    # terraform.tf — plaintext
    "ghs_tL1eX5zIvR3wYnSg8CfMqU0dHkB6gA2YpjB1",
    # docker-compose.yml — plaintext, invalid checksum
    "gho_X5v8tG2aMnKpYeRcHdFjBwLqNz1S9U1vlLjt",
    # notebook.sql — plaintext, invalid checksum
    "ghs_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA000000",
    # vault.enc — AES-256-CBC encrypted, passphrase from .env SECRET_KEY_BASE[:32]
    "ghr_k2VnR6rKpL9sYhTf8WcJdQ0dHiB5fA291kwV",
    # vault.enc — same encrypted vault
    "ghs_p1WyS7tLqM0xZiUg4CfMqU0eIjC6gB4ENsHt",
}

# Tokens only discoverable via git history examination
GIT_HISTORY_TOKENS = {
    # Deleted commit (git log -p --all shows the diff)
    "ghp_w9TkR3mNvJ6xYbHf2QdLpS0cGiA5eZ48nwy3",
    # Deleted commit (same)
    "ghs_n4FyQ8wKtM1vXjRg5BdLpS0cGiA5eZ32mlSA",
    # Dangling commit — only reachable via reflog or fsck (amended away)
    "ghu_h2VxN6rKpL9sYhTf3WcJdQ0dHiB5fA4Qf4WR",
    # Git stash entry — requires git stash list / git stash show -p
    "ghp_v9TkQ8wNpJ6xYbHf5RdLpS0cGiA7eZ4GLs3f",
    # Git notes on first commit — requires git notes list / git log --show-notes
    "gho_f4UxP9sKqL8wYhTg3BeLpR0cHiA5fZ24HcZA",
}

# Tokens discoverable in the SQLite audit database
AUDIT_DB_TOKENS = {
    # Authorization header in http_requests table
    "gho_j7MxP4sKqL8wYhTg6BeLpR0cHiA5fZ4ccSFC",
    # POST body in http_requests table
    "ghr_q3RtY9vHuN5wXkSf8CdMpU0bFjA7gE30M4HM",
    # URL query param in path column, invalid checksum
    "ghp_L8mNvJ6xYbHf2QdKpS0cGiA5eZw9TkZZZZZZ",
    # Base64-encoded in Set-Cookie response header (response_headers table)
    "ghu_n8XzW3yJvR5tYkSh6DgNqU1fHlB4eC1bD990",
}

ALL_TOKENS = CORPUS_TOKENS | GIT_HISTORY_TOKENS | AUDIT_DB_TOKENS

DECOY_STRINGS = {
    "a94a8fe5ccb19ba61c4c0873d391e987982fbbd3",
    "da39a3ee5e6b4b0d3255bfef95601890afd80709",
    "sk_live_4eC39HqLyjWDarjtT1zdp7dc",
    "xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx",
    "AKIAIOSFODNN7EXAMPLE",
}


def _load_report():
    with open("/app/incident_report.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test: report file exists and is parseable
# ---------------------------------------------------------------------------

class TestReportExists:
    def test_file_exists(self):
        assert os.path.exists("/app/incident_report.json"), (
            "/app/incident_report.json does not exist"
        )

    def test_parseable_json(self):
        report = _load_report()
        assert "findings" in report, "report missing 'findings' key"
        assert "summary" in report, "report missing 'summary' key"

    def test_findings_have_required_fields(self):
        report = _load_report()
        required = {"token", "token_type", "checksum_valid", "vector"}
        for i, finding in enumerate(report["findings"]):
            missing = required - set(finding.keys())
            assert not missing, (
                f"finding[{i}] missing keys: {missing}"
            )


# ---------------------------------------------------------------------------
# Test: all expected tokens are found — no missing, no extras
# ---------------------------------------------------------------------------

class TestTokenCompleteness:
    def test_total_unique_count(self):
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        assert len(found) == 22, (
            f"Expected 22 unique tokens, got {len(found)}"
        )

    def test_all_expected_tokens_present(self):
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        missing = ALL_TOKENS - found
        assert not missing, f"Missing tokens: {missing}"

    def test_no_unexpected_tokens(self):
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        extra = found - ALL_TOKENS
        assert not extra, f"Unexpected tokens: {extra}"

    def test_no_decoy_strings(self):
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        leaked = found & DECOY_STRINGS
        assert not leaked, f"Decoy strings in findings: {leaked}"


# ---------------------------------------------------------------------------
# Test: checksum validation is correct
# ---------------------------------------------------------------------------

class TestChecksumValidation:
    def test_valid_count(self):
        report = _load_report()
        valid = sum(1 for f in report["findings"] if f["checksum_valid"])
        assert valid == 18, f"Expected 18 valid, got {valid}"

    def test_invalid_count(self):
        report = _load_report()
        invalid = sum(1 for f in report["findings"] if not f["checksum_valid"])
        assert invalid == 4, f"Expected 4 invalid, got {invalid}"

    def test_each_checksum_independently(self):
        """Recompute every checksum and verify the agent's classification."""
        report = _load_report()
        for finding in report["findings"]:
            token = finding["token"]
            expected = _verify_checksum(token)
            assert finding["checksum_valid"] == expected, (
                f"{token}: reported {finding['checksum_valid']}, "
                f"independently computed {expected}"
            )


# ---------------------------------------------------------------------------
# Test: vector attribution
# ---------------------------------------------------------------------------

class TestVectorAttribution:
    def test_git_history_tokens_attributed(self):
        report = _load_report()
        by_token = {f["token"]: f for f in report["findings"]}
        for token in GIT_HISTORY_TOKENS:
            assert token in by_token, f"Git token not found: {token}"
            assert by_token[token]["vector"] == "git_history", (
                f"{token}: expected vector 'git_history', "
                f"got '{by_token[token]['vector']}'"
            )

    def test_audit_db_tokens_attributed(self):
        report = _load_report()
        by_token = {f["token"]: f for f in report["findings"]}
        for token in AUDIT_DB_TOKENS:
            assert token in by_token, f"Audit DB token not found: {token}"
            assert by_token[token]["vector"] == "audit_db", (
                f"{token}: expected vector 'audit_db', "
                f"got '{by_token[token]['vector']}'"
            )

    def test_corpus_tokens_attributed(self):
        report = _load_report()
        by_token = {f["token"]: f for f in report["findings"]}
        for token in CORPUS_TOKENS:
            assert token in by_token, f"Corpus token not found: {token}"
            assert by_token[token]["vector"] == "file", (
                f"{token}: expected vector 'file', "
                f"got '{by_token[token]['vector']}'"
            )


# ---------------------------------------------------------------------------
# Test: summary statistics
# ---------------------------------------------------------------------------

class TestSummary:
    def test_total_findings(self):
        report = _load_report()
        assert report["summary"]["total_findings"] == 22

    def test_valid_tokens(self):
        report = _load_report()
        assert report["summary"]["valid_tokens"] == 18

    def test_invalid_checksums(self):
        report = _load_report()
        assert report["summary"]["invalid_checksums"] == 4

    def test_by_type_counts(self):
        report = _load_report()
        bt = report["summary"]["by_type"]
        assert bt.get("ghp", 0) == 6, f"ghp: expected 6, got {bt.get('ghp')}"
        assert bt.get("gho", 0) == 5, f"gho: expected 5, got {bt.get('gho')}"
        assert bt.get("ghu", 0) == 3, f"ghu: expected 3, got {bt.get('ghu')}"
        assert bt.get("ghs", 0) == 5, f"ghs: expected 5, got {bt.get('ghs')}"
        assert bt.get("ghr", 0) == 3, f"ghr: expected 3, got {bt.get('ghr')}"

    def test_by_vector_counts(self):
        report = _load_report()
        bv = report["summary"]["by_vector"]
        assert bv.get("file", 0) == 13, (
            f"file: expected 13, got {bv.get('file')}"
        )
        assert bv.get("git_history", 0) == 5, (
            f"git_history: expected 5, got {bv.get('git_history')}"
        )
        assert bv.get("audit_db", 0) == 4, (
            f"audit_db: expected 4, got {bv.get('audit_db')}"
        )


# ---------------------------------------------------------------------------
# Test: encoded and hidden tokens were found (depth checks)
# ---------------------------------------------------------------------------

class TestEncodedTokens:
    def test_base64_token_direct(self):
        """The token encoded directly as base64 in secrets.json."""
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        assert "ghu_p7Qm2KxRfN3sYhTv9WbJdL0cGiA5eZ1LCYai" in found

    def test_base64_nested_json_token(self):
        """The token inside a base64-encoded JSON blob in secrets.json."""
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        assert "ghs_mN3xR7vKpL9sYhTf2WbJdQ0cGiA5eZ20vLsV" in found

    def test_dangling_commit_token(self):
        """The token only reachable via git reflog / fsck (amended away)."""
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        assert "ghu_h2VxN6rKpL9sYhTf3WcJdQ0dHiB5fA4Qf4WR" in found


class TestEncryptedVaultTokens:
    """Tokens inside an AES-256-CBC encrypted vault file."""

    def test_vault_token_1(self):
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        assert "ghr_k2VnR6rKpL9sYhTf8WcJdQ0dHiB5fA291kwV" in found, (
            "Encrypted vault token ghr_k2Vn... not found — "
            "agent must decrypt /app/corpus/vault.enc"
        )

    def test_vault_token_2(self):
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        assert "ghs_p1WyS7tLqM0xZiUg4CfMqU0eIjC6gB4ENsHt" in found, (
            "Encrypted vault token ghs_p1Wy... not found — "
            "agent must decrypt /app/corpus/vault.enc"
        )

    def test_vault_tokens_attributed_as_file(self):
        report = _load_report()
        by_token = {f["token"]: f for f in report["findings"]}
        for tok in [
            "ghr_k2VnR6rKpL9sYhTf8WcJdQ0dHiB5fA291kwV",
            "ghs_p1WyS7tLqM0xZiUg4CfMqU0eIjC6gB4ENsHt",
        ]:
            if tok in by_token:
                assert by_token[tok]["vector"] == "file", (
                    f"Vault token {tok[:10]}... should have vector 'file'"
                )


class TestGitStashAndNotes:
    """Tokens hidden in git stash entries and git notes."""

    def test_stash_token(self):
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        assert "ghp_v9TkQ8wNpJ6xYbHf5RdLpS0cGiA7eZ4GLs3f" in found, (
            "Git stash token not found — agent must examine git stash entries"
        )

    def test_notes_token(self):
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        assert "gho_f4UxP9sKqL8wYhTg3BeLpR0cHiA5fZ24HcZA" in found, (
            "Git notes token not found — agent must examine git notes"
        )

    def test_stash_token_attributed(self):
        report = _load_report()
        by_token = {f["token"]: f for f in report["findings"]}
        tok = "ghp_v9TkQ8wNpJ6xYbHf5RdLpS0cGiA7eZ4GLs3f"
        if tok in by_token:
            assert by_token[tok]["vector"] == "git_history"

    def test_notes_token_attributed(self):
        report = _load_report()
        by_token = {f["token"]: f for f in report["findings"]}
        tok = "gho_f4UxP9sKqL8wYhTg3BeLpR0cHiA5fZ24HcZA"
        if tok in by_token:
            assert by_token[tok]["vector"] == "git_history"


class TestAuditDbBase64Cookie:
    """Token hidden as base64-encoded value in a Set-Cookie response header."""

    def test_base64_cookie_token(self):
        report = _load_report()
        found = {f["token"] for f in report["findings"]}
        assert "ghu_n8XzW3yJvR5tYkSh6DgNqU1fHlB4eC1bD990" in found, (
            "Base64-encoded cookie token not found — "
            "agent must decode Set-Cookie values in response_headers table"
        )

    def test_base64_cookie_token_attributed(self):
        report = _load_report()
        by_token = {f["token"]: f for f in report["findings"]}
        tok = "ghu_n8XzW3yJvR5tYkSh6DgNqU1fHlB4eC1bD990"
        if tok in by_token:
            assert by_token[tok]["vector"] == "audit_db"
