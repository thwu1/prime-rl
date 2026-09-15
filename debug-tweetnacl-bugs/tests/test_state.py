"""
Verification tests for the NaCl Vault multi-recipient encryption tool.

Compiles the agent's nacl_vault.c and exercises keygen, encrypt, decrypt,
tamper detection, and format compliance.

"""

import os
import struct
import subprocess
import tempfile

import pytest

VAULT = "/app/nacl_vault"
CHUNK_SIZE = 65536


@pytest.fixture(scope="session", autouse=True)
def build_vault():
    """Compile nacl_vault before running any tests."""
    result = subprocess.run(
        ["make", "-C", "/app", "clean", "nacl_vault"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Build failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert os.path.isfile(VAULT), "nacl_vault binary not found after build"


def run_vault(args, timeout=30):
    """Run the nacl_vault binary with given arguments."""
    return subprocess.run(
        [VAULT] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def make_keypair(base_dir, name):
    """Generate a keypair, return (sk_path, pk_path)."""
    sk = os.path.join(base_dir, f"{name}.sk")
    pk = os.path.join(base_dir, f"{name}.pk")
    r = run_vault(["keygen", sk, pk])
    assert r.returncode == 0, f"keygen failed: {r.stderr}"
    return sk, pk


# ── Keygen ────────────────────────────────────────────────────────────────

class TestKeygen:
    def test_creates_files_of_correct_size(self, tmp_path):
        sk = str(tmp_path / "test.sk")
        pk = str(tmp_path / "test.pk")
        r = run_vault(["keygen", sk, pk])
        assert r.returncode == 0
        assert os.path.getsize(sk) == 32
        assert os.path.getsize(pk) == 32

    def test_keypairs_are_unique(self, tmp_path):
        sk1, pk1 = make_keypair(str(tmp_path), "a")
        sk2, pk2 = make_keypair(str(tmp_path), "b")
        assert open(pk1, "rb").read() != open(pk2, "rb").read()


# ── Round-trip encrypt/decrypt ────────────────────────────────────────────

class TestRoundTrip:
    def _round_trip(self, tmp_path, data):
        d = str(tmp_path)
        sk, pk = make_keypair(d, "user")
        infile = os.path.join(d, "plain.bin")
        encfile = os.path.join(d, "encrypted.vault")
        decfile = os.path.join(d, "decrypted.bin")

        with open(infile, "wb") as f:
            f.write(data)

        r = run_vault(["encrypt", "-r", pk, "-o", encfile, infile])
        assert r.returncode == 0, f"Encrypt failed: {r.stderr}"

        r = run_vault(["decrypt", "-k", sk, "-o", decfile, encfile])
        assert r.returncode == 0, f"Decrypt failed: {r.stderr}"

        with open(decfile, "rb") as f:
            result = f.read()
        assert result == data, (
            f"Round-trip mismatch: expected {len(data)} bytes, got {len(result)}"
        )
        return encfile

    def test_empty_file(self, tmp_path):
        self._round_trip(tmp_path, b"")

    def test_one_byte(self, tmp_path):
        self._round_trip(tmp_path, b"\x42")

    def test_small_file(self, tmp_path):
        self._round_trip(tmp_path, b"Hello, NaCl Vault!")

    def test_255_bytes(self, tmp_path):
        self._round_trip(tmp_path, bytes(range(256))[:255])

    def test_exact_chunk(self, tmp_path):
        self._round_trip(tmp_path, os.urandom(CHUNK_SIZE))

    def test_chunk_plus_one(self, tmp_path):
        self._round_trip(tmp_path, os.urandom(CHUNK_SIZE + 1))

    def test_two_full_chunks(self, tmp_path):
        self._round_trip(tmp_path, os.urandom(CHUNK_SIZE * 2))

    def test_multi_chunk_unaligned(self, tmp_path):
        self._round_trip(tmp_path, os.urandom(CHUNK_SIZE * 3 + 1234))

    def test_large_file(self, tmp_path):
        self._round_trip(tmp_path, os.urandom(CHUNK_SIZE * 5 + 7))


# ── Multi-recipient ──────────────────────────────────────────────────────

class TestMultiRecipient:
    def test_two_recipients_both_decrypt(self, tmp_path):
        d = str(tmp_path)
        sk1, pk1 = make_keypair(d, "alice")
        sk2, pk2 = make_keypair(d, "bob")

        data = b"Secret message for Alice and Bob"
        infile = os.path.join(d, "secret.txt")
        encfile = os.path.join(d, "encrypted.vault")
        with open(infile, "wb") as f:
            f.write(data)

        r = run_vault(["encrypt", "-r", pk1, "-r", pk2, "-o", encfile, infile])
        assert r.returncode == 0

        for i, sk in enumerate([sk1, sk2]):
            decfile = os.path.join(d, f"dec{i}.bin")
            r = run_vault(["decrypt", "-k", sk, "-o", decfile, encfile])
            assert r.returncode == 0, f"Recipient {i} decrypt failed: {r.stderr}"
            with open(decfile, "rb") as f:
                assert f.read() == data

    def test_three_recipients_multi_chunk(self, tmp_path):
        d = str(tmp_path)
        keys = [make_keypair(d, f"user{i}") for i in range(3)]
        data = os.urandom(CHUNK_SIZE + 500)

        infile = os.path.join(d, "data.bin")
        encfile = os.path.join(d, "encrypted.vault")
        with open(infile, "wb") as f:
            f.write(data)

        pk_args = []
        for _, pk in keys:
            pk_args.extend(["-r", pk])
        r = run_vault(["encrypt"] + pk_args + ["-o", encfile, infile])
        assert r.returncode == 0

        for i, (sk, _) in enumerate(keys):
            decfile = os.path.join(d, f"dec{i}.bin")
            r = run_vault(["decrypt", "-k", sk, "-o", decfile, encfile])
            assert r.returncode == 0, f"Recipient {i} failed: {r.stderr}"
            with open(decfile, "rb") as f:
                assert f.read() == data

    def test_wrong_key_rejected(self, tmp_path):
        d = str(tmp_path)
        sk1, pk1 = make_keypair(d, "alice")
        sk_eve, _ = make_keypair(d, "eve")

        infile = os.path.join(d, "secret.txt")
        encfile = os.path.join(d, "encrypted.vault")
        with open(infile, "wb") as f:
            f.write(b"For Alice only")

        r = run_vault(["encrypt", "-r", pk1, "-o", encfile, infile])
        assert r.returncode == 0

        decfile = os.path.join(d, "dec_eve.bin")
        r = run_vault(["decrypt", "-k", sk_eve, "-o", decfile, encfile])
        assert r.returncode != 0, "Decryption with wrong key should fail"


# ── Tamper detection ─────────────────────────────────────────────────────

class TestTamperDetection:
    def _make_vault(self, tmp_path, data):
        d = str(tmp_path)
        sk, pk = make_keypair(d, "user")
        infile = os.path.join(d, "plain.bin")
        encfile = os.path.join(d, "encrypted.vault")
        with open(infile, "wb") as f:
            f.write(data)
        r = run_vault(["encrypt", "-r", pk, "-o", encfile, infile])
        assert r.returncode == 0
        return sk, encfile

    def test_corrupted_magic(self, tmp_path):
        sk, encfile = self._make_vault(tmp_path, b"test data here")
        with open(encfile, "r+b") as f:
            f.seek(0)
            f.write(b"XXXX")
        decfile = str(tmp_path / "dec.bin")
        r = run_vault(["decrypt", "-k", sk, "-o", decfile, encfile])
        assert r.returncode != 0

    def test_flipped_bit_in_chunk(self, tmp_path):
        data = os.urandom(1000)
        sk, encfile = self._make_vault(tmp_path, data)
        with open(encfile, "rb") as f:
            enc = bytearray(f.read())
        # Flip a byte inside the encrypted chunk region
        chunk_offset = 40 + 104 + 20  # header + 1 recipient record + 20 bytes in
        enc[chunk_offset] ^= 0xFF
        with open(encfile, "wb") as f:
            f.write(bytes(enc))
        decfile = str(tmp_path / "dec.bin")
        r = run_vault(["decrypt", "-k", sk, "-o", decfile, encfile])
        assert r.returncode != 0

    def test_truncation_detected(self, tmp_path):
        data = os.urandom(CHUNK_SIZE * 2 + 100)
        sk, encfile = self._make_vault(tmp_path, data)
        with open(encfile, "rb") as f:
            enc = f.read()
        # Remove the last 50 bytes
        with open(encfile, "wb") as f:
            f.write(enc[:-50])
        decfile = str(tmp_path / "dec.bin")
        r = run_vault(["decrypt", "-k", sk, "-o", decfile, encfile])
        assert r.returncode != 0


# ── Format compliance ────────────────────────────────────────────────────

class TestFormatCompliance:
    def test_header_fields(self, tmp_path):
        d = str(tmp_path)
        sk, pk = make_keypair(d, "user")
        data = os.urandom(100)
        infile = os.path.join(d, "plain.bin")
        encfile = os.path.join(d, "encrypted.vault")
        with open(infile, "wb") as f:
            f.write(data)
        r = run_vault(["encrypt", "-r", pk, "-o", encfile, infile])
        assert r.returncode == 0

        with open(encfile, "rb") as f:
            hdr = f.read(40)
        assert hdr[:4] == b"NV01", f"Bad magic: {hdr[:4]}"
        assert hdr[4] == 0x01, f"Bad version: {hdr[4]}"
        n_recip = struct.unpack("<H", hdr[6:8])[0]
        assert n_recip == 1, f"Expected 1 recipient, got {n_recip}"
        pt_len = struct.unpack("<Q", hdr[32:40])[0]
        assert pt_len == 100, f"Expected plaintext_len=100, got {pt_len}"

    def test_file_size_single_chunk(self, tmp_path):
        d = str(tmp_path)
        sk, pk = make_keypair(d, "user")
        data_len = 1000
        infile = os.path.join(d, "plain.bin")
        encfile = os.path.join(d, "encrypted.vault")
        with open(infile, "wb") as f:
            f.write(os.urandom(data_len))
        r = run_vault(["encrypt", "-r", pk, "-o", encfile, infile])
        assert r.returncode == 0
        # header(40) + 1×recipient(104) + 1×chunk(16 + 1000)
        expected = 40 + 104 + 16 + data_len
        actual = os.path.getsize(encfile)
        assert actual == expected, f"Expected {expected}, got {actual}"

    def test_file_size_multi_chunk(self, tmp_path):
        d = str(tmp_path)
        sk, pk = make_keypair(d, "user")
        data_len = CHUNK_SIZE + 500
        infile = os.path.join(d, "plain.bin")
        encfile = os.path.join(d, "encrypted.vault")
        with open(infile, "wb") as f:
            f.write(os.urandom(data_len))
        r = run_vault(["encrypt", "-r", pk, "-o", encfile, infile])
        assert r.returncode == 0
        # header(40) + 1×recipient(104) + chunk1(16+65536) + chunk2(16+500)
        expected = 40 + 104 + (16 + CHUNK_SIZE) + (16 + 500)
        actual = os.path.getsize(encfile)
        assert actual == expected, f"Expected {expected}, got {actual}"

    def test_file_size_multi_recipient(self, tmp_path):
        d = str(tmp_path)
        keys = [make_keypair(d, f"u{i}") for i in range(3)]
        data_len = 200
        infile = os.path.join(d, "plain.bin")
        encfile = os.path.join(d, "encrypted.vault")
        with open(infile, "wb") as f:
            f.write(os.urandom(data_len))
        pk_args = []
        for _, pk in keys:
            pk_args.extend(["-r", pk])
        r = run_vault(["encrypt"] + pk_args + ["-o", encfile, infile])
        assert r.returncode == 0
        # header(40) + 3×recipient(312) + 1×chunk(16+200)
        expected = 40 + 3 * 104 + 16 + data_len
        actual = os.path.getsize(encfile)
        assert actual == expected, f"Expected {expected}, got {actual}"

    def test_empty_file_format(self, tmp_path):
        d = str(tmp_path)
        sk, pk = make_keypair(d, "user")
        infile = os.path.join(d, "empty.bin")
        encfile = os.path.join(d, "encrypted.vault")
        with open(infile, "wb") as f:
            pass
        r = run_vault(["encrypt", "-r", pk, "-o", encfile, infile])
        assert r.returncode == 0
        # header(40) + 1×recipient(104) + no chunks
        expected = 40 + 104
        actual = os.path.getsize(encfile)
        assert actual == expected, f"Expected {expected}, got {actual}"

        decfile = os.path.join(d, "dec.bin")
        r = run_vault(["decrypt", "-k", sk, "-o", decfile, encfile])
        assert r.returncode == 0
        assert os.path.getsize(decfile) == 0
