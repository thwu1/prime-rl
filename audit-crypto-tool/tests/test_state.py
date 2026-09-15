
"""
Security-oriented tests for cryptvault.

Verifies both functional correctness (round-trip encrypt/decrypt) and
that all cryptographic vulnerabilities have been fixed:
  1. Password KDF uses memory-hard Argon2id (not fast BLAKE2b)
  2. Nonces are random (not derived deterministically from key)
  3. MAC verification failures cause decryption to abort
  4. Large-file encryption uses authenticated encryption (not bare stream cipher)
"""

import os
import subprocess
import tempfile
import time

import pytest

BINARY = "/app/cryptvault"


def run_cmd(args, timeout=60):
    """Run cryptvault with the given arguments."""
    return subprocess.run(
        [BINARY] + args,
        capture_output=True,
        timeout=timeout,
    )


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ------------------------------------------------------------------
# Functional tests
# ------------------------------------------------------------------

class TestFunctionality:
    """Basic encrypt/decrypt round-trip correctness."""

    def test_binary_exists(self):
        assert os.path.isfile(BINARY), f"Binary not found at {BINARY}"
        assert os.access(BINARY, os.X_OK), "Binary is not executable"

    def test_roundtrip_keyfile(self, tmpdir):
        keyfile = os.path.join(tmpdir, "test.key")
        pt_path = os.path.join(tmpdir, "plain.txt")
        ct_path = os.path.join(tmpdir, "cipher.bin")
        dec_path = os.path.join(tmpdir, "decrypted.txt")

        data = b"Hello, cryptvault! Round-trip test with a keyfile."
        with open(pt_path, "wb") as f:
            f.write(data)

        assert run_cmd(["keygen", keyfile]).returncode == 0
        assert run_cmd(["encrypt", "-k", keyfile, pt_path, ct_path]).returncode == 0
        assert run_cmd(["decrypt", "-k", keyfile, ct_path, dec_path]).returncode == 0

        with open(dec_path, "rb") as f:
            assert f.read() == data

    def test_roundtrip_password(self, tmpdir):
        pt_path = os.path.join(tmpdir, "plain.txt")
        ct_path = os.path.join(tmpdir, "cipher.bin")
        dec_path = os.path.join(tmpdir, "decrypted.txt")

        data = b"Password-based encryption round-trip test data."
        with open(pt_path, "wb") as f:
            f.write(data)

        pw = "correct-horse-battery-staple"
        assert run_cmd(["encrypt", "-p", pw, pt_path, ct_path]).returncode == 0
        assert run_cmd(["decrypt", "-p", pw, ct_path, dec_path]).returncode == 0

        with open(dec_path, "rb") as f:
            assert f.read() == data

    def test_roundtrip_large_file(self, tmpdir):
        keyfile = os.path.join(tmpdir, "test.key")
        pt_path = os.path.join(tmpdir, "large.bin")
        ct_path = os.path.join(tmpdir, "large.enc")
        dec_path = os.path.join(tmpdir, "large.dec")

        data = os.urandom(128 * 1024)  # 128 KB — above the 64 KB threshold
        with open(pt_path, "wb") as f:
            f.write(data)

        run_cmd(["keygen", keyfile])
        assert run_cmd(["encrypt", "-k", keyfile, pt_path, ct_path]).returncode == 0
        assert run_cmd(["decrypt", "-k", keyfile, ct_path, dec_path]).returncode == 0

        with open(dec_path, "rb") as f:
            assert f.read() == data


# ------------------------------------------------------------------
# Security tests
# ------------------------------------------------------------------

class TestPasswordKDF:
    """Vulnerability 1: password KDF must use memory-hard Argon2id."""

    def test_password_encryption_takes_measurable_time(self, tmpdir):
        """
        Argon2id (crypto_pwhash) is intentionally slow (hundreds of ms).
        A fast hash like BLAKE2b (crypto_generichash) completes in < 1 ms.
        """
        pt_path = os.path.join(tmpdir, "plain.txt")
        ct_path = os.path.join(tmpdir, "cipher.bin")

        with open(pt_path, "wb") as f:
            f.write(b"kdf timing test")

        start = time.monotonic()
        result = run_cmd(["encrypt", "-p", "password123", pt_path, ct_path])
        elapsed = time.monotonic() - start

        assert result.returncode == 0
        assert elapsed > 0.1, (
            f"Password-based encryption took only {elapsed:.4f}s — too fast. "
            f"This indicates a fast hash (like BLAKE2b) instead of Argon2id. "
            f"Use crypto_pwhash() with appropriate opslimit/memlimit."
        )


class TestNonceUniqueness:
    """Vulnerability 2: nonces must be random, not derived from the key."""

    def test_small_file_nonce_is_random(self, tmpdir):
        """Two encryptions of identical data with the same key must differ."""
        keyfile = os.path.join(tmpdir, "test.key")
        pt_path = os.path.join(tmpdir, "plain.txt")
        ct1 = os.path.join(tmpdir, "enc1.bin")
        ct2 = os.path.join(tmpdir, "enc2.bin")

        with open(pt_path, "wb") as f:
            f.write(b"Nonce uniqueness test - small file")

        run_cmd(["keygen", keyfile])
        run_cmd(["encrypt", "-k", keyfile, pt_path, ct1])
        run_cmd(["encrypt", "-k", keyfile, pt_path, ct2])

        with open(ct1, "rb") as f:
            data1 = f.read()
        with open(ct2, "rb") as f:
            data2 = f.read()

        assert data1 != data2, (
            "Two encryptions of the same plaintext with the same key produced "
            "identical ciphertext. Nonces must be generated randomly with "
            "randombytes_buf(), not derived deterministically from the key."
        )

    def test_large_file_nonce_is_random(self, tmpdir):
        """Large-file path must also use unique randomness per encryption."""
        keyfile = os.path.join(tmpdir, "test.key")
        pt_path = os.path.join(tmpdir, "large.bin")
        ct1 = os.path.join(tmpdir, "enc1.bin")
        ct2 = os.path.join(tmpdir, "enc2.bin")

        with open(pt_path, "wb") as f:
            f.write(os.urandom(128 * 1024))

        run_cmd(["keygen", keyfile])
        run_cmd(["encrypt", "-k", keyfile, pt_path, ct1])
        run_cmd(["encrypt", "-k", keyfile, pt_path, ct2])

        with open(ct1, "rb") as f:
            data1 = f.read()
        with open(ct2, "rb") as f:
            data2 = f.read()

        assert data1 != data2, (
            "Two encryptions of the same large file with the same key produced "
            "identical ciphertext. Each encryption must use fresh randomness."
        )


class TestMACVerification:
    """Vulnerability 3: MAC failures must cause decryption to abort."""

    def test_tampered_small_file_rejected(self, tmpdir):
        """Flipping a bit in the ciphertext must cause decryption to fail."""
        keyfile = os.path.join(tmpdir, "test.key")
        pt_path = os.path.join(tmpdir, "plain.txt")
        ct_path = os.path.join(tmpdir, "cipher.bin")
        dec_path = os.path.join(tmpdir, "dec.txt")

        with open(pt_path, "wb") as f:
            f.write(b"MAC verification test - authenticate everything")

        run_cmd(["keygen", keyfile])
        run_cmd(["encrypt", "-k", keyfile, pt_path, ct_path])

        # Tamper with the ciphertext payload
        with open(ct_path, "rb") as f:
            data = bytearray(f.read())
        data[-5] ^= 0x01
        with open(ct_path, "wb") as f:
            f.write(data)

        result = run_cmd(["decrypt", "-k", keyfile, ct_path, dec_path])
        assert result.returncode != 0, (
            "Decryption of tampered ciphertext succeeded (exit 0). "
            "crypto_secretbox_open_easy() returns -1 on MAC failure — "
            "this return value must be checked and the error propagated."
        )

    def test_wrong_password_rejected(self, tmpdir):
        """Decryption with the wrong password must fail, not produce garbage."""
        pt_path = os.path.join(tmpdir, "plain.txt")
        ct_path = os.path.join(tmpdir, "cipher.bin")
        dec_path = os.path.join(tmpdir, "dec.txt")

        with open(pt_path, "wb") as f:
            f.write(b"Secret data that must stay confidential")

        run_cmd(["encrypt", "-p", "right-password", pt_path, ct_path])
        result = run_cmd(["decrypt", "-p", "wrong-password", ct_path, dec_path])

        assert result.returncode != 0, (
            "Decryption with the wrong password succeeded (exit 0). "
            "The MAC check must detect the wrong key and abort."
        )


class TestLargeFileAuthentication:
    """Vulnerability 4: large files must use authenticated encryption."""

    def test_tampered_large_file_rejected(self, tmpdir):
        """
        Flipping a bit in the middle of an encrypted large file must be
        detected. crypto_stream_xor provides no authentication — use
        crypto_secretstream_xchacha20poly1305 instead.
        """
        keyfile = os.path.join(tmpdir, "test.key")
        pt_path = os.path.join(tmpdir, "large.bin")
        ct_path = os.path.join(tmpdir, "large.enc")
        dec_path = os.path.join(tmpdir, "large.dec")

        with open(pt_path, "wb") as f:
            f.write(os.urandom(128 * 1024))

        run_cmd(["keygen", keyfile])
        run_cmd(["encrypt", "-k", keyfile, pt_path, ct_path])

        # Tamper with a byte in the middle of the encrypted payload
        with open(ct_path, "rb") as f:
            data = bytearray(f.read())
        data[len(data) // 2] ^= 0x42
        with open(ct_path, "wb") as f:
            f.write(data)

        result = run_cmd(["decrypt", "-k", keyfile, ct_path, dec_path])
        assert result.returncode != 0, (
            "Decryption of a tampered large file succeeded. "
            "crypto_stream_xor provides no authentication — use "
            "crypto_secretstream_xchacha20poly1305 for authenticated "
            "chunked encryption."
        )
