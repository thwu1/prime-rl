
import hashlib
import os
import subprocess
import pytest

EXPECTED_COMBINED_HASH = "d38066147b68b0d59719726c4b294b75c180d1c0a1b564fb68685ca903f04f6c"


class TestEnvironment:
    def test_identity_key_exists(self):
        assert os.path.isfile("/app/identity.key"), "Identity key missing"

    def test_corpus_file_count(self):
        files = [f for f in os.listdir("/app/corpus") if f.endswith(".age")]
        assert len(files) == 5, f"Expected 5 .age files, found {len(files)}"

    def test_age_cli_available(self):
        r = subprocess.run(["age", "--version"], capture_output=True)
        assert r.returncode == 0, "age CLI not available"

    def test_some_files_decrypt_with_cli(self):
        """At least some files should decrypt with the reference CLI."""
        files = sorted(os.listdir("/app/corpus"))
        ok = 0
        for f in files:
            r = subprocess.run(
                ["age", "-d", "-i", "/app/identity.key", f"/app/corpus/{f}"],
                capture_output=True,
            )
            if r.returncode == 0:
                ok += 1
        assert ok >= 2, f"Expected >=2 conformant files, only {ok} decrypted"

    def test_some_files_fail_with_cli(self):
        """At least some files should fail with the reference CLI."""
        files = sorted(os.listdir("/app/corpus"))
        fail = 0
        for f in files:
            r = subprocess.run(
                ["age", "-d", "-i", "/app/identity.key", f"/app/corpus/{f}"],
                capture_output=True,
            )
            if r.returncode != 0:
                fail += 1
        assert fail >= 3, f"Expected >=3 non-conformant files, only {fail} failed"


class TestRecovery:
    def test_recovered_file_exists(self):
        assert os.path.isfile("/app/recovered.txt"), "/app/recovered.txt not found"

    def test_recovered_token_count(self):
        with open("/app/recovered.txt") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 3, f"Expected 3 recovered tokens, got {len(lines)}"

    def test_tokens_are_sorted(self):
        with open("/app/recovered.txt") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert lines == sorted(lines), "Tokens must be in sorted order"

    def test_token_format(self):
        with open("/app/recovered.txt") as f:
            lines = [l.strip() for l in f if l.strip()]
        for line in lines:
            assert line.startswith("RECOVERED-"), f"Unexpected token format: {line}"
            assert len(line.split("-", 1)[1]) == 6, f"Token value wrong length: {line}"

    def test_correct_token_values(self):
        with open("/app/recovered.txt") as f:
            lines = sorted(l.strip() for l in f if l.strip())
        combined = "\n".join(lines) + "\n"
        actual_hash = hashlib.sha256(combined.encode()).hexdigest()
        assert actual_hash == EXPECTED_COMBINED_HASH, (
            "Recovered token values are incorrect"
        )
