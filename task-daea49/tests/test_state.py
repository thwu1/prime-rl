"""Tests for XAES-256-GCM Python implementation, CMAC-AES256, and file encryption tool.

Verifies the Python implementation at /app/py_impl/xaes256gcm.py against hardcoded
test vectors, reference CMAC implementation, accumulated test vector hash, and
cross-language interoperability with the Go implementation. Also tests the file
encryption tool at /app/file_tool/xaes_file.py.

"""

import hashlib
import os
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, "/app/py_impl")


# ---- Deterministic PRNG (SHA-256 in counter mode) ----

def sha256_ctr_prng(seed: bytes, n: int) -> bytes:
    """Deterministic PRNG using SHA-256 in counter mode."""
    result = bytearray()
    ctr = 0
    while len(result) < n:
        h = hashlib.sha256(seed + struct.pack('>I', ctr)).digest()
        result.extend(h)
        ctr += 1
    return bytes(result[:n])


def reference_cmac(key: bytes, message: bytes) -> bytes:
    """Compute CMAC-AES256 using the cryptography library as reference."""
    from cryptography.hazmat.primitives.cmac import CMAC
    from cryptography.hazmat.primitives.ciphers.algorithms import AES
    c = CMAC(AES(key))
    c.update(message)
    return c.finalize()


# ---- Hardcoded XAES-256-GCM test vectors ----

TV1_KEY = bytes.fromhex(
    "df3f619804a92fdb4057192dc43dd748ea778adc52bc498ce80524c014b81119"
)
TV1_NONCE = b"\xaa" * 24
TV1_PLAINTEXT = b"test vector one"
TV1_AAD = b"aad1"
TV1_CIPHERTEXT = bytes.fromhex(
    "bf69fc60fa8d13d40d0fa9865bca7d222dfcac5e8a147a54300fcdbf0bcbe8"
)

TV2_KEY = bytes.fromhex(
    "b40711a88c7039756fb8a73827eabe2c0fe5a0346ca7e0a104adc0fc764f528d"
)
TV2_NONCE = b"\xbb" * 24
TV2_PLAINTEXT = b"test vector two"
TV2_AAD = b"aad2"
TV2_CIPHERTEXT = bytes.fromhex(
    "de34f0984522b2433ac92666e39414156ce57090de85652ec13b28dd90a858"
)

TV3_KEY = b"\x00" * 32
TV3_NONCE = b"\xff" * 24
TV3_PLAINTEXT = b""
TV3_AAD = b"only-aad"
TV3_CIPHERTEXT = bytes.fromhex("199509ea809003e7a053d4a342111fac")

TV4_KEY = b"\x42" * 32
TV4_NONCE = b"\x13" * 24
TV4_PLAINTEXT = b"no aad here"
TV4_AAD = b""
TV4_CIPHERTEXT = bytes.fromhex(
    "24221eea02c5f8c8554122bd7aeb30021fdd715698225871b325d0"
)

INTEROP_KEY = bytes.fromhex(
    "e2e41db53dfd24e4bc267e0e1e7753bf4b1d37a5dc1ba5e63579e04a7dc94e9c"
)
INTEROP_NONCE = bytes.fromhex(
    "aabbccddeeff00112233445566778899aabbccddeeff0011"
)
INTEROP_PT = b"cross-language interoperability test"
INTEROP_AAD = b"interop-aad-v1"
INTEROP_CT = bytes.fromhex(
    "127e63e742db6b3d117ef0198a578dcebb64354dd376e0a8a47e5671"
    "984fa78695cd53f69ea80afa720e521d1938fd5f5fa1cb57"
)

ACCUMULATED_HASH = "2bdb71ed2de2ae4f98d641893903eb11668079586e10a07a02259d5430909b2c"


# ---- CMAC-AES256 Tests ----

class TestCMAC:
    """Verify standalone cmac_aes256 function against cryptography library reference."""

    CMAC_KEY_A = bytes(range(32))
    CMAC_KEY_B = b'\xff' * 32

    @pytest.mark.parametrize("msg_len", [0, 1, 7, 15, 16, 17, 31, 32, 33, 47, 48, 64, 100])
    def test_various_lengths_key_a(self, msg_len):
        from xaes256gcm import cmac_aes256
        msg = bytes(range(msg_len))
        expected = reference_cmac(self.CMAC_KEY_A, msg)
        got = cmac_aes256(self.CMAC_KEY_A, msg)
        assert got == expected, (
            f"CMAC mismatch at length {msg_len}.\n"
            f"  Got:      {got.hex()}\n"
            f"  Expected: {expected.hex()}"
        )

    @pytest.mark.parametrize("msg_len", [0, 1, 15, 16, 17, 32, 64])
    def test_various_lengths_key_b(self, msg_len):
        from xaes256gcm import cmac_aes256
        msg = bytes([0x42] * msg_len)
        expected = reference_cmac(self.CMAC_KEY_B, msg)
        got = cmac_aes256(self.CMAC_KEY_B, msg)
        assert got == expected, f"CMAC mismatch at length {msg_len}"

    def test_deterministic(self):
        from xaes256gcm import cmac_aes256
        key = b'\x42' * 32
        msg = b'deterministic test message for CMAC-AES256'
        assert cmac_aes256(key, msg) == cmac_aes256(key, msg)

    def test_tag_is_16_bytes(self):
        from xaes256gcm import cmac_aes256
        tag = cmac_aes256(self.CMAC_KEY_A, b'test')
        assert len(tag) == 16, f"Tag should be 16 bytes, got {len(tag)}"

    def test_invalid_key_size(self):
        from xaes256gcm import cmac_aes256
        with pytest.raises(ValueError):
            cmac_aes256(b'\x00' * 16, b'test')

    def test_different_messages_different_tags(self):
        from xaes256gcm import cmac_aes256
        key = self.CMAC_KEY_A
        tag1 = cmac_aes256(key, b'message one')
        tag2 = cmac_aes256(key, b'message two')
        assert tag1 != tag2, "Different messages should produce different tags"


class TestNoCMACImport:
    """Verify CMAC is implemented from scratch, not using a library."""

    def test_no_cmac_library_import(self):
        with open("/app/py_impl/xaes256gcm.py") as f:
            source = f.read()
        forbidden = [
            "from cryptography.hazmat.primitives.cmac",
            "from cryptography.hazmat.primitives import cmac",
            "primitives.cmac.CMAC",
        ]
        for pattern in forbidden:
            assert pattern not in source, (
                f"Forbidden CMAC library import found: {pattern}\n"
                "CMAC must be implemented from scratch using raw AES-ECB."
            )


# ---- XAES-256-GCM Known Vectors ----

class TestPythonKnownVectors:
    """Verify Python encryption output matches hardcoded test vectors."""

    def test_vector_msb0(self):
        from xaes256gcm import XAES256GCM
        ct = XAES256GCM(TV1_KEY).encrypt(TV1_NONCE, TV1_PLAINTEXT, TV1_AAD)
        assert ct == TV1_CIPHERTEXT, (
            f"MSB=0 vector mismatch.\n  Got:      {ct.hex()}\n  Expected: {TV1_CIPHERTEXT.hex()}"
        )

    def test_vector_msb1(self):
        from xaes256gcm import XAES256GCM
        ct = XAES256GCM(TV2_KEY).encrypt(TV2_NONCE, TV2_PLAINTEXT, TV2_AAD)
        assert ct == TV2_CIPHERTEXT, (
            f"MSB=1 vector mismatch.\n  Got:      {ct.hex()}\n  Expected: {TV2_CIPHERTEXT.hex()}"
        )

    def test_vector_empty_plaintext(self):
        from xaes256gcm import XAES256GCM
        ct = XAES256GCM(TV3_KEY).encrypt(TV3_NONCE, TV3_PLAINTEXT, TV3_AAD)
        assert ct == TV3_CIPHERTEXT

    def test_vector_no_aad(self):
        from xaes256gcm import XAES256GCM
        ct = XAES256GCM(TV4_KEY).encrypt(TV4_NONCE, TV4_PLAINTEXT, TV4_AAD)
        assert ct == TV4_CIPHERTEXT

    def test_interop_vector(self):
        from xaes256gcm import XAES256GCM
        ct = XAES256GCM(INTEROP_KEY).encrypt(INTEROP_NONCE, INTEROP_PT, INTEROP_AAD)
        assert ct == INTEROP_CT


# ---- XAES-256-GCM Decryption ----

class TestPythonDecryption:
    """Verify Python decryption recovers plaintext from known ciphertexts."""

    def test_decrypt_msb0(self):
        from xaes256gcm import XAES256GCM
        pt = XAES256GCM(TV1_KEY).decrypt(TV1_NONCE, TV1_CIPHERTEXT, TV1_AAD)
        assert pt == TV1_PLAINTEXT

    def test_decrypt_msb1(self):
        from xaes256gcm import XAES256GCM
        pt = XAES256GCM(TV2_KEY).decrypt(TV2_NONCE, TV2_CIPHERTEXT, TV2_AAD)
        assert pt == TV2_PLAINTEXT

    def test_decrypt_empty_plaintext(self):
        from xaes256gcm import XAES256GCM
        pt = XAES256GCM(TV3_KEY).decrypt(TV3_NONCE, TV3_CIPHERTEXT, TV3_AAD)
        assert pt == TV3_PLAINTEXT

    def test_decrypt_no_aad(self):
        from xaes256gcm import XAES256GCM
        pt = XAES256GCM(TV4_KEY).decrypt(TV4_NONCE, TV4_CIPHERTEXT, TV4_AAD)
        assert pt == TV4_PLAINTEXT


# ---- XAES-256-GCM Round Trip ----

class TestPythonRoundTrip:
    """Verify Python encrypt-then-decrypt round-trip for various inputs."""

    def test_roundtrip_basic(self):
        from xaes256gcm import XAES256GCM
        key = os.urandom(32)
        nonce = os.urandom(24)
        cipher = XAES256GCM(key)
        ct = cipher.encrypt(nonce, b"round trip test data", b"some metadata")
        recovered = cipher.decrypt(nonce, ct, b"some metadata")
        assert recovered == b"round trip test data"

    def test_roundtrip_empty_plaintext(self):
        from xaes256gcm import XAES256GCM
        key = os.urandom(32)
        nonce = os.urandom(24)
        cipher = XAES256GCM(key)
        ct = cipher.encrypt(nonce, b"", b"aad-only")
        recovered = cipher.decrypt(nonce, ct, b"aad-only")
        assert recovered == b""

    def test_roundtrip_large_plaintext(self):
        from xaes256gcm import XAES256GCM
        key = os.urandom(32)
        nonce = os.urandom(24)
        pt = os.urandom(65536)
        cipher = XAES256GCM(key)
        ct = cipher.encrypt(nonce, pt, b"")
        recovered = cipher.decrypt(nonce, ct, b"")
        assert recovered == pt


# ---- Accumulated Test Vectors ----

class TestPythonAccumulated:
    """Accumulated test vectors: deterministic SHA-256 CTR PRNG, SHA-256 accumulator."""

    def test_accumulated_1000(self):
        from xaes256gcm import XAES256GCM

        seed = hashlib.sha256(b"XAES-256-GCM accumulated test vectors v2").digest()
        rng = sha256_ctr_prng(seed, 500000)
        offset = 0

        def draw(n):
            nonlocal offset
            result = rng[offset:offset + n]
            offset += n
            return result

        acc = hashlib.sha256()

        for i in range(1000):
            key = draw(32)
            nonce = draw(24)
            pt_len = i % 128
            aad_len = i % 64
            plaintext = draw(pt_len)
            aad = draw(aad_len)

            cipher = XAES256GCM(key)
            ct = cipher.encrypt(nonce, plaintext, aad)
            acc.update(ct)

            recovered = cipher.decrypt(nonce, ct, aad)
            assert recovered == plaintext, f"Round-trip failed at iteration {i}"

        got = acc.hexdigest()
        assert got == ACCUMULATED_HASH, (
            f"Accumulated hash mismatch after 1000 iterations.\n"
            f"  Got:      {got}\n"
            f"  Expected: {ACCUMULATED_HASH}"
        )


# ---- Edge Cases ----

class TestPythonEdgeCases:
    """Input validation and error handling."""

    def test_invalid_key_size_short(self):
        from xaes256gcm import XAES256GCM
        with pytest.raises(ValueError):
            XAES256GCM(b"\x00" * 16)

    def test_invalid_key_size_long(self):
        from xaes256gcm import XAES256GCM
        with pytest.raises(ValueError):
            XAES256GCM(b"\x00" * 64)

    def test_invalid_nonce_size(self):
        from xaes256gcm import XAES256GCM
        cipher = XAES256GCM(b"\x00" * 32)
        with pytest.raises(ValueError):
            cipher.encrypt(b"\x00" * 12, b"data")

    def test_tampered_ciphertext_rejected(self):
        from xaes256gcm import XAES256GCM
        from cryptography.exceptions import InvalidTag

        key = os.urandom(32)
        nonce = os.urandom(24)
        cipher = XAES256GCM(key)
        ct = cipher.encrypt(nonce, b"secret data", b"aad")

        tampered = bytearray(ct)
        tampered[0] ^= 0xFF

        with pytest.raises(InvalidTag):
            cipher.decrypt(nonce, bytes(tampered), b"aad")

    def test_wrong_aad_rejected(self):
        from xaes256gcm import XAES256GCM
        from cryptography.exceptions import InvalidTag

        key = os.urandom(32)
        nonce = os.urandom(24)
        cipher = XAES256GCM(key)
        ct = cipher.encrypt(nonce, b"data", b"correct-aad")

        with pytest.raises(InvalidTag):
            cipher.decrypt(nonce, ct, b"wrong-aad")


# ---- Cross-language Interoperability ----

class TestInterop:
    """Cross-language interoperability tests between Go and Python."""

    GO_BINARY = "/tmp/xaesgcm_test_binary"

    @classmethod
    def setup_class(cls):
        result = subprocess.run(
            ["go", "build", "-o", cls.GO_BINARY, "./cmd/xaesgcm"],
            cwd="/app/go_impl",
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"Go build failed (exit {result.returncode}):\n{result.stderr}"
        )

    def _go_encrypt(self, key, nonce, plaintext, aad):
        args = [self.GO_BINARY, "encrypt", key.hex(), nonce.hex(),
                plaintext.hex(), aad.hex() if aad else ""]
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 0, f"Go encrypt failed: {result.stderr}"
        return bytes.fromhex(result.stdout.strip())

    def _go_decrypt(self, key, nonce, ciphertext, aad):
        args = [self.GO_BINARY, "decrypt", key.hex(), nonce.hex(),
                ciphertext.hex(), aad.hex() if aad else ""]
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 0, f"Go decrypt failed: {result.stderr}"
        return bytes.fromhex(result.stdout.strip())

    def test_go_matches_reference_vector(self):
        ct = self._go_encrypt(TV1_KEY, TV1_NONCE, TV1_PLAINTEXT, TV1_AAD)
        assert ct == TV1_CIPHERTEXT

    def test_go_encrypt_python_decrypt(self):
        from xaes256gcm import XAES256GCM
        go_ct = self._go_encrypt(INTEROP_KEY, INTEROP_NONCE, INTEROP_PT, INTEROP_AAD)
        recovered = XAES256GCM(INTEROP_KEY).decrypt(INTEROP_NONCE, go_ct, INTEROP_AAD)
        assert recovered == INTEROP_PT

    def test_python_encrypt_go_decrypt(self):
        from xaes256gcm import XAES256GCM
        py_ct = XAES256GCM(INTEROP_KEY).encrypt(INTEROP_NONCE, INTEROP_PT, INTEROP_AAD)
        recovered = self._go_decrypt(INTEROP_KEY, INTEROP_NONCE, py_ct, INTEROP_AAD)
        assert recovered == INTEROP_PT

    def test_both_produce_same_ciphertext(self):
        from xaes256gcm import XAES256GCM
        test_cases = [
            (TV1_KEY, TV1_NONCE, TV1_PLAINTEXT, TV1_AAD),
            (TV2_KEY, TV2_NONCE, TV2_PLAINTEXT, TV2_AAD),
            (TV3_KEY, TV3_NONCE, TV3_PLAINTEXT, TV3_AAD),
            (TV4_KEY, TV4_NONCE, TV4_PLAINTEXT, TV4_AAD),
            (INTEROP_KEY, INTEROP_NONCE, INTEROP_PT, INTEROP_AAD),
        ]
        for i, (key, nonce, pt, aad) in enumerate(test_cases):
            py_ct = XAES256GCM(key).encrypt(nonce, pt, aad)
            go_ct = self._go_encrypt(key, nonce, pt, aad)
            assert py_ct == go_ct, (
                f"Interop mismatch on test case {i}.\n"
                f"  Python: {py_ct.hex()}\n"
                f"  Go:     {go_ct.hex()}"
            )


# ---- File Encryption Tool Tests ----

class TestFileTool:
    """Tests for the file encryption CLI tool at /app/file_tool/xaes_file.py."""

    TOOL_PATH = "/app/file_tool/xaes_file.py"
    GO_BINARY = "/tmp/xaesgcm_test_binary_ft"

    @classmethod
    def setup_class(cls):
        result = subprocess.run(
            ["go", "build", "-o", cls.GO_BINARY, "./cmd/xaesgcm"],
            cwd="/app/go_impl",
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Go build failed: {result.stderr}"

    def test_tool_exists(self):
        assert os.path.isfile(self.TOOL_PATH), (
            "File tool not found at /app/file_tool/xaes_file.py"
        )

    def test_encrypt_decrypt_roundtrip(self):
        key_hex = "00" * 32
        plaintext = b"Hello, XAES-256-GCM file encryption!"

        with open("/tmp/ft_test_in.bin", "wb") as f:
            f.write(plaintext)

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "encrypt", "--key", key_hex,
             "/tmp/ft_test_in.bin", "/tmp/ft_test_enc.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Encrypt failed: {result.stderr}"

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "decrypt", "--key", key_hex,
             "/tmp/ft_test_enc.bin", "/tmp/ft_test_dec.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Decrypt failed: {result.stderr}"

        with open("/tmp/ft_test_dec.bin", "rb") as f:
            recovered = f.read()
        assert recovered == plaintext

    def test_with_aad(self):
        key_hex = "42" * 32
        plaintext = b"authenticated data test"

        with open("/tmp/ft_aad_in.bin", "wb") as f:
            f.write(plaintext)

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "encrypt", "--key", key_hex,
             "--aad", "my-metadata",
             "/tmp/ft_aad_in.bin", "/tmp/ft_aad_enc.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Encrypt with AAD failed: {result.stderr}"

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "decrypt", "--key", key_hex,
             "/tmp/ft_aad_enc.bin", "/tmp/ft_aad_dec.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Decrypt with AAD failed: {result.stderr}"

        with open("/tmp/ft_aad_dec.bin", "rb") as f:
            recovered = f.read()
        assert recovered == plaintext

    def test_format_structure(self):
        key_hex = "00" * 32
        aad_text = "format-test"
        plaintext = b"format test data"

        with open("/tmp/ft_fmt_in.bin", "wb") as f:
            f.write(plaintext)

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "encrypt", "--key", key_hex,
             "--aad", aad_text,
             "/tmp/ft_fmt_in.bin", "/tmp/ft_fmt_enc.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Encrypt failed: {result.stderr}"

        with open("/tmp/ft_fmt_enc.bin", "rb") as f:
            data = f.read()

        # Check magic bytes
        assert data[:8] == b"XAESFILE", f"Invalid magic: {data[:8]}"
        # Check version
        assert data[8] == 0x01, f"Invalid version: {data[8]}"
        # Nonce is 24 bytes at offset 9
        nonce = data[9:33]
        assert len(nonce) == 24
        # AAD length at offset 33
        aad_len = struct.unpack(">I", data[33:37])[0]
        assert aad_len == len(aad_text.encode()), f"AAD length mismatch: {aad_len}"
        # AAD content
        aad_bytes = data[37:37 + aad_len]
        assert aad_bytes == aad_text.encode()
        # Ciphertext + tag
        ct = data[37 + aad_len:]
        assert len(ct) == len(plaintext) + 16, (
            f"Ciphertext length mismatch: got {len(ct)}, expected {len(plaintext) + 16}"
        )

    def test_empty_file(self):
        key_hex = "00" * 32

        with open("/tmp/ft_empty_in.bin", "wb") as f:
            f.write(b"")

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "encrypt", "--key", key_hex,
             "/tmp/ft_empty_in.bin", "/tmp/ft_empty_enc.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Encrypt empty failed: {result.stderr}"

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "decrypt", "--key", key_hex,
             "/tmp/ft_empty_enc.bin", "/tmp/ft_empty_dec.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Decrypt empty failed: {result.stderr}"

        with open("/tmp/ft_empty_dec.bin", "rb") as f:
            recovered = f.read()
        assert recovered == b""

    def test_no_aad(self):
        key_hex = "13" * 32
        plaintext = b"no additional authenticated data"

        with open("/tmp/ft_noaad_in.bin", "wb") as f:
            f.write(plaintext)

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "encrypt", "--key", key_hex,
             "/tmp/ft_noaad_in.bin", "/tmp/ft_noaad_enc.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0

        # Verify AAD length is 0 in the format
        with open("/tmp/ft_noaad_enc.bin", "rb") as f:
            data = f.read()
        aad_len = struct.unpack(">I", data[33:37])[0]
        assert aad_len == 0, f"AAD length should be 0, got {aad_len}"

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "decrypt", "--key", key_hex,
             "/tmp/ft_noaad_enc.bin", "/tmp/ft_noaad_dec.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0

        with open("/tmp/ft_noaad_dec.bin", "rb") as f:
            recovered = f.read()
        assert recovered == plaintext

    def test_interop_with_go(self):
        """Encrypt with file tool, extract params, decrypt with Go CLI."""
        key_hex = INTEROP_KEY.hex()
        plaintext = b"interop file tool test data 12345"

        with open("/tmp/ft_interop_in.bin", "wb") as f:
            f.write(plaintext)

        result = subprocess.run(
            ["python3", self.TOOL_PATH, "encrypt", "--key", key_hex,
             "/tmp/ft_interop_in.bin", "/tmp/ft_interop_enc.bin"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"File tool encrypt failed: {result.stderr}"

        # Parse the encrypted file format
        with open("/tmp/ft_interop_enc.bin", "rb") as f:
            data = f.read()

        nonce = data[9:33]
        aad_len = struct.unpack(">I", data[33:37])[0]
        aad = data[37:37 + aad_len]
        ct = data[37 + aad_len:]

        # Decrypt with Go CLI
        result = subprocess.run(
            [self.GO_BINARY, "decrypt", key_hex, nonce.hex(), ct.hex(),
             aad.hex() if aad else ""],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Go decrypt failed: {result.stderr}"
        recovered = bytes.fromhex(result.stdout.strip())
        assert recovered == plaintext, (
            f"Interop mismatch.\n  Got:      {recovered}\n  Expected: {plaintext}"
        )
