
import subprocess
import struct
import hashlib
import hmac as hmac_mod
import json
import os
import pytest


# ---------------------------------------------------------------------------
# ACVP binary protocol helpers
# ---------------------------------------------------------------------------

def write_request(proc, *args):
    """Write an ACVP-framed request: [N] [len0..lenN-1] [data0..dataN-1]."""
    n = len(args)
    buf = struct.pack('<I', n)
    for a in args:
        buf += struct.pack('<I', len(a))
    for a in args:
        buf += a
    proc.stdin.write(buf)
    proc.stdin.flush()


def read_response(proc):
    """Read an ACVP-framed response. Returns list of byte strings."""
    raw = proc.stdout.read(4)
    assert len(raw) == 4, "Failed to read response arg count"
    n = struct.unpack('<I', raw)[0]
    lengths = []
    for _ in range(n):
        raw = proc.stdout.read(4)
        assert len(raw) == 4, "Failed to read arg length"
        lengths.append(struct.unpack('<I', raw)[0])
    result = []
    for l in lengths:
        if l > 0:
            data = proc.stdout.read(l)
            assert len(data) == l, f"Short read: wanted {l}, got {len(data)}"
            result.append(data)
        else:
            result.append(b'')
    return result


def send_command(proc, cmd_name, *args):
    """Send a named ACVP command."""
    all_args = [cmd_name.encode('utf-8')] + list(args)
    write_request(proc, *all_args)


def start_module():
    """Launch the ACVP module subprocess."""
    return subprocess.Popen(
        ['/app/acvp_module'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def hkdf_sha256_python(ikm, salt, info, length):
    """Pure-Python HKDF-SHA256 (RFC 5869)."""
    if len(salt) == 0:
        salt = b'\x00' * 32
    prk = hmac_mod.new(salt, ikm, hashlib.sha256).digest()
    t = b''
    okm = b''
    for i in range(1, (length + 31) // 32 + 1):
        t = hmac_mod.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBinaryExists:
    def test_binary_exists(self):
        assert os.path.isfile('/app/acvp_module'), "/app/acvp_module not found"

    def test_binary_executable(self):
        assert os.access('/app/acvp_module', os.X_OK), "/app/acvp_module not executable"


class TestGetConfig:
    def test_returns_valid_json(self):
        proc = start_module()
        try:
            send_command(proc, 'getConfig')
            resp = read_response(proc)
            assert len(resp) == 1
            config = json.loads(resp[0].decode('utf-8'))
            assert isinstance(config, (list, dict))
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_lists_all_algorithms(self):
        proc = start_module()
        try:
            send_command(proc, 'getConfig')
            resp = read_response(proc)
            text = resp[0].decode('utf-8').lower()
            for alg in ['sha2-256', 'hmac-sha2-256', 'aes-256-gcm',
                        'hkdf/sha2-256', 'cmac-aes-256', 'pbkdf2-hmac-sha256']:
                assert alg in text, f"Algorithm {alg} not listed in getConfig"
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)


class TestSHA256:
    def _check(self, msg):
        proc = start_module()
        try:
            send_command(proc, 'SHA2-256', msg)
            resp = read_response(proc)
            assert len(resp) == 1
            assert resp[0] == hashlib.sha256(msg).digest()
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_empty(self):
        self._check(b'')

    def test_hello_world(self):
        self._check(b'Hello, World!')

    def test_long_message(self):
        self._check(b'A' * 10000)

    def test_binary_data(self):
        self._check(bytes(range(256)))


class TestHMACSHA256:
    def _check(self, key, msg):
        proc = start_module()
        try:
            # ACVP order: message THEN key
            send_command(proc, 'HMAC-SHA2-256', msg, key)
            resp = read_response(proc)
            assert len(resp) == 1
            expected = hmac_mod.new(key, msg, hashlib.sha256).digest()
            assert resp[0] == expected
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_basic(self):
        self._check(b'secret_key_for_hmac_testing', b'Hello, HMAC!')

    def test_rfc4231_case1(self):
        self._check(b'\x0b' * 20, b'Hi There')

    def test_rfc4231_case2(self):
        self._check(b'Jefe', b'what do ya want for nothing?')

    def test_empty_message(self):
        self._check(b'key', b'')


class TestAES256GCMSeal:
    def test_seal_then_open_roundtrip(self):
        proc = start_module()
        try:
            key = bytes(range(32))
            nonce = bytes(range(12))
            pt = b'Hello, AES-256-GCM!'
            aad = b'additional authenticated data'
            tag_len_bytes = struct.pack('<I', 16)

            # Seal
            send_command(proc, 'AES-256-GCM/seal', tag_len_bytes, key, pt, nonce, aad)
            resp = read_response(proc)
            assert len(resp) == 1
            ct_tag = resp[0]
            assert len(ct_tag) == len(pt) + 16

            # Open
            send_command(proc, 'AES-256-GCM/open', tag_len_bytes, key, ct_tag, nonce, aad)
            resp = read_response(proc)
            assert len(resp) == 2
            assert resp[0] == b'\x01'
            assert resp[1] == pt
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_nist_sp800_38d_case13(self):
        """NIST SP 800-38D Test Case 13: AES-256-GCM, all-zero key/nonce, empty PT."""
        proc = start_module()
        try:
            key = b'\x00' * 32
            nonce = b'\x00' * 12
            pt = b''
            aad = b''
            tag_len_bytes = struct.pack('<I', 16)

            send_command(proc, 'AES-256-GCM/seal', tag_len_bytes, key, pt, nonce, aad)
            resp = read_response(proc)
            ct_tag = resp[0]
            assert len(ct_tag) == 16
            expected_tag = bytes.fromhex('530f8afbc74536b9a963b4f1c4cb738b')
            assert ct_tag == expected_tag, (
                f"Tag mismatch: got {ct_tag.hex()}, expected {expected_tag.hex()}"
            )
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_nist_sp800_38d_case14(self):
        """NIST SP 800-38D Test Case 14: AES-256-GCM, all-zero key/nonce, 16-byte PT."""
        proc = start_module()
        try:
            key = b'\x00' * 32
            nonce = b'\x00' * 12
            pt = b'\x00' * 16
            aad = b''
            tag_len_bytes = struct.pack('<I', 16)

            send_command(proc, 'AES-256-GCM/seal', tag_len_bytes, key, pt, nonce, aad)
            resp = read_response(proc)
            ct_tag = resp[0]
            assert len(ct_tag) == 32, f"Expected 32 bytes (16 ct + 16 tag), got {len(ct_tag)}"

            expected_ct = bytes.fromhex('cea7403d4d606b6e074ec5d3baf39d18')
            expected_tag = bytes.fromhex('d0d1c8a799996bf0265b98b5d48ab919')
            expected_output = expected_ct + expected_tag  # ct || tag
            assert ct_tag == expected_output, (
                f"Output mismatch: got {ct_tag.hex()}, expected {expected_output.hex()}"
            )
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_tampered_ciphertext_fails(self):
        proc = start_module()
        try:
            key = bytes(range(32))
            nonce = bytes(range(12))
            pt = b'Tamper test'
            tag_len_bytes = struct.pack('<I', 16)

            send_command(proc, 'AES-256-GCM/seal', tag_len_bytes, key, pt, nonce, b'')
            resp = read_response(proc)
            ct_tag = resp[0]

            # Flip a bit
            tampered = bytearray(ct_tag)
            tampered[0] ^= 0xFF
            tampered = bytes(tampered)

            send_command(proc, 'AES-256-GCM/open', tag_len_bytes, key, tampered, nonce, b'')
            resp = read_response(proc)
            assert resp[0] == b'\x00', "Tampered ciphertext must fail authentication"
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_wrong_aad_fails(self):
        proc = start_module()
        try:
            key = bytes(range(32))
            nonce = bytes(range(12))
            pt = b'aad test'
            aad = b'correct aad'
            tag_len_bytes = struct.pack('<I', 16)

            send_command(proc, 'AES-256-GCM/seal', tag_len_bytes, key, pt, nonce, aad)
            resp = read_response(proc)
            ct_tag = resp[0]

            send_command(proc, 'AES-256-GCM/open', tag_len_bytes, key, ct_tag, nonce, b'wrong')
            resp = read_response(proc)
            assert resp[0] == b'\x00', "Wrong AAD must fail authentication"
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)


class TestAES256GCMOpen:
    def test_open_nist_sp800_38d_case14(self):
        """Decrypt NIST SP 800-38D Test Case 14 using externally-known ct||tag."""
        proc = start_module()
        try:
            key = b'\x00' * 32
            nonce = b'\x00' * 12
            ct = bytes.fromhex('cea7403d4d606b6e074ec5d3baf39d18')
            tag = bytes.fromhex('d0d1c8a799996bf0265b98b5d48ab919')
            ct_tag = ct + tag  # ct || tag per ACVP format
            tag_len_bytes = struct.pack('<I', 16)

            send_command(proc, 'AES-256-GCM/open', tag_len_bytes, key, ct_tag, nonce, b'')
            resp = read_response(proc)
            assert resp[0] == b'\x01', "Decryption should succeed for valid NIST test vector"
            assert resp[1] == b'\x00' * 16, f"Expected 16 zero bytes, got {resp[1].hex()}"
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_open_rejects_invalid_tag(self):
        """Open must reject when authentication tag is invalid."""
        proc = start_module()
        try:
            key = b'\x00' * 32
            nonce = b'\x00' * 12
            ct = bytes.fromhex('cea7403d4d606b6e074ec5d3baf39d18')
            bad_tag = b'\xff' * 16
            ct_tag = ct + bad_tag
            tag_len_bytes = struct.pack('<I', 16)

            send_command(proc, 'AES-256-GCM/open', tag_len_bytes, key, ct_tag, nonce, b'')
            resp = read_response(proc)
            assert resp[0] == b'\x00', "Invalid tag must cause authentication failure"
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)


class TestHKDF:
    def test_rfc5869_case1(self):
        proc = start_module()
        try:
            ikm = bytes.fromhex('0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b')
            salt = bytes.fromhex('000102030405060708090a0b0c')
            info = bytes.fromhex('f0f1f2f3f4f5f6f7f8f9')
            length = 42
            out_len = struct.pack('<I', length)

            send_command(proc, 'HKDF/SHA2-256', ikm, salt, info, out_len)
            resp = read_response(proc)
            assert len(resp) == 1

            expected = bytes.fromhex(
                '3cb25f25faacd57a90434f64d0362f2a'
                '2d2d0a90cf1a5a4c5db02d56ecc4c5bf'
                '34007208d5b887185865'
            )
            assert resp[0] == expected, f"HKDF case 1: got {resp[0].hex()}"
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_rfc5869_case2(self):
        proc = start_module()
        try:
            ikm = bytes.fromhex(
                '000102030405060708090a0b0c0d0e0f'
                '101112131415161718191a1b1c1d1e1f'
                '202122232425262728292a2b2c2d2e2f'
                '303132333435363738393a3b3c3d3e3f'
                '404142434445464748494a4b4c4d4e4f'
            )
            salt = bytes.fromhex(
                '606162636465666768696a6b6c6d6e6f'
                '707172737475767778797a7b7c7d7e7f'
                '808182838485868788898a8b8c8d8e8f'
                '909192939495969798999a9b9c9d9e9f'
                'a0a1a2a3a4a5a6a7a8a9aaabacadaeaf'
            )
            info = bytes.fromhex(
                'b0b1b2b3b4b5b6b7b8b9babbbcbdbebf'
                'c0c1c2c3c4c5c6c7c8c9cacbcccdcecf'
                'd0d1d2d3d4d5d6d7d8d9dadbdcdddedf'
                'e0e1e2e3e4e5e6e7e8e9eaebecedeeef'
                'f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff'
            )
            length = 82
            out_len = struct.pack('<I', length)

            send_command(proc, 'HKDF/SHA2-256', ikm, salt, info, out_len)
            resp = read_response(proc)

            expected = bytes.fromhex(
                'b11e398dc80327a1c8e7f78c596a4934'
                '4f012eda2d4efad8a050cc4c19afa97c'
                '59045a99cac7827271cb41c65e590e09'
                'da3275600c2f09b8367793a9aca3db71'
                'cc30c58179ec3e87c14c01d5c1f3434f'
                '1d87'
            )
            assert resp[0] == expected, f"HKDF case 2: got {resp[0].hex()}"
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_rfc5869_case3_empty_salt_and_info(self):
        proc = start_module()
        try:
            ikm = bytes.fromhex('0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b')
            salt = b''
            info = b''
            length = 42
            out_len = struct.pack('<I', length)

            send_command(proc, 'HKDF/SHA2-256', ikm, salt, info, out_len)
            resp = read_response(proc)

            expected = bytes.fromhex(
                '8da4e775a563c18f715f802a063c5a31'
                'b8a11f5c5ee1879ec3454e5f3c738d2d'
                '9d201395faa4b61a96c8'
            )
            assert resp[0] == expected, f"HKDF case 3: got {resp[0].hex()}"
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_matches_python_reference(self):
        """Cross-check against pure-Python HKDF implementation."""
        proc = start_module()
        try:
            ikm = b'input keying material for cross-check'
            salt = b'a salt value'
            info = b'context info'
            length = 64
            out_len = struct.pack('<I', length)

            send_command(proc, 'HKDF/SHA2-256', ikm, salt, info, out_len)
            resp = read_response(proc)
            expected = hkdf_sha256_python(ikm, salt, info, length)
            assert resp[0] == expected
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)


class TestCMACAES256:
    """CMAC-AES-256 tests using NIST SP 800-38B D.2 test vectors."""

    NIST_KEY = bytes.fromhex(
        '603deb1015ca71be2b73aef0857d7781'
        '1f352c073b6108d72d9810a30914dff4'
    )

    def _check_cmac(self, key, msg, expected_mac, out_len=16):
        proc = start_module()
        try:
            out_len_bytes = struct.pack('<I', out_len)
            send_command(proc, 'CMAC-AES-256', out_len_bytes, key, msg)
            resp = read_response(proc)
            assert len(resp) == 1
            assert len(resp[0]) == out_len, (
                f"Expected {out_len} bytes, got {len(resp[0])}"
            )
            assert resp[0] == expected_mac[:out_len], (
                f"CMAC mismatch: got {resp[0].hex()}, "
                f"expected {expected_mac[:out_len].hex()}"
            )
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_nist_d2_example1_empty_message(self):
        """NIST SP 800-38B D.2 Example 1: Mlen=0."""
        expected = bytes.fromhex('028962f61b7bf89efc6b551f4667d983')
        self._check_cmac(self.NIST_KEY, b'', expected)

    def test_nist_d2_example2_16byte_message(self):
        """NIST SP 800-38B D.2 Example 2: Mlen=128 bits."""
        msg = bytes.fromhex('6bc1bee22e409f96e93d7e117393172a')
        expected = bytes.fromhex('28a7023f452e8f82bd4bf28d8c37c35c')
        self._check_cmac(self.NIST_KEY, msg, expected)

    def test_nist_d2_example4_64byte_message(self):
        """NIST SP 800-38B D.2 Example 4: Mlen=512 bits."""
        msg = bytes.fromhex(
            '6bc1bee22e409f96e93d7e117393172a'
            'ae2d8a571e03ac9c9eb76fac45af8e51'
            '30c81c46a35ce411e5fbc1191a0a52ef'
            'f69f2445df4f9b17ad2b417be66c3710'
        )
        expected = bytes.fromhex('e1992190549f6ed5696a2c056c315410')
        self._check_cmac(self.NIST_KEY, msg, expected)

    def test_truncated_output(self):
        """Request only 8 bytes of MAC output (truncated CMAC)."""
        msg = bytes.fromhex('6bc1bee22e409f96e93d7e117393172a')
        full_mac = bytes.fromhex('28a7023f452e8f82bd4bf28d8c37c35c')
        self._check_cmac(self.NIST_KEY, msg, full_mac, out_len=8)


class TestPBKDF2:
    """PBKDF2-HMAC-SHA256 tests using RFC 7914 and standard test vectors."""

    def _derive(self, password, salt, iterations, dk_len):
        proc = start_module()
        try:
            iter_bytes = struct.pack('<I', iterations)
            len_bytes = struct.pack('<I', dk_len)
            send_command(proc, 'PBKDF2-HMAC-SHA256',
                         password, salt, iter_bytes, len_bytes)
            resp = read_response(proc)
            assert len(resp) == 1
            assert len(resp[0]) == dk_len, (
                f"Expected {dk_len} bytes, got {len(resp[0])}"
            )
            return resp[0]
        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_rfc7914_case1(self):
        """RFC 7914 Section 11: P='passwd', S='salt', c=1, dkLen=64."""
        expected = bytes.fromhex(
            '55ac046e56e3089fec1691c22544b605'
            'f94185216dde0465e68b9d57c20dacbc'
            '49ca9cccf179b645991664b39d77ef31'
            '7c71b845b1e30bd509112041d3a19783'
        )
        result = self._derive(b'passwd', b'salt', 1, 64)
        assert result == expected, (
            f"PBKDF2 RFC7914#1: got {result.hex()}"
        )

    def test_standard_c4096(self):
        """P='password', S='salt', c=4096, dkLen=32 — standard test vector."""
        expected = hashlib.pbkdf2_hmac('sha256', b'password', b'salt',
                                       4096, dklen=32)
        result = self._derive(b'password', b'salt', 4096, 32)
        assert result == expected, (
            f"PBKDF2 c=4096: got {result.hex()}, "
            f"expected {expected.hex()}"
        )

    def test_cross_check_with_python(self):
        """Cross-check against Python's hashlib.pbkdf2_hmac."""
        password = b'cryptographic key material'
        salt = b'unique salt for this test vector'
        iterations = 10000
        dk_len = 48

        expected = hashlib.pbkdf2_hmac('sha256', password, salt,
                                       iterations, dklen=dk_len)
        result = self._derive(password, salt, iterations, dk_len)
        assert result == expected

    def test_single_iteration_short_salt(self):
        """c=1 with 4-byte salt — requires the module to accept arbitrary
        iteration counts and salt lengths per ACVP requirements."""
        expected = hashlib.pbkdf2_hmac('sha256', b'pass', b'salt',
                                       1, dklen=20)
        result = self._derive(b'pass', b'salt', 1, 20)
        assert result == expected


class TestMultiCommandSession:
    def test_multiple_commands_single_session(self):
        """Module must handle many sequential commands in one session."""
        proc = start_module()
        try:
            # 1: SHA-256
            msg = b'first message'
            send_command(proc, 'SHA2-256', msg)
            r = read_response(proc)
            assert r[0] == hashlib.sha256(msg).digest()

            # 2: HMAC
            send_command(proc, 'HMAC-SHA2-256', b'data', b'key')
            r = read_response(proc)
            assert r[0] == hmac_mod.new(b'key', b'data', hashlib.sha256).digest()

            # 3: Another SHA-256
            msg2 = b'second'
            send_command(proc, 'SHA2-256', msg2)
            r = read_response(proc)
            assert r[0] == hashlib.sha256(msg2).digest()

            # 4: AES-GCM round-trip
            key = bytes(range(32))
            nonce = bytes(range(12))
            pt = b'multi-cmd test'
            tl = struct.pack('<I', 16)

            send_command(proc, 'AES-256-GCM/seal', tl, key, pt, nonce, b'')
            r = read_response(proc)
            ct_tag = r[0]

            send_command(proc, 'AES-256-GCM/open', tl, key, ct_tag, nonce, b'')
            r = read_response(proc)
            assert r[0] == b'\x01'
            assert r[1] == pt

            # 5: HKDF
            ikm = b'ikm'
            salt = b'salt'
            info = b'info'
            ol = struct.pack('<I', 32)
            send_command(proc, 'HKDF/SHA2-256', ikm, salt, info, ol)
            r = read_response(proc)
            assert r[0] == hkdf_sha256_python(ikm, salt, info, 32)

            # 6: CMAC
            cmac_key = bytes.fromhex(
                '603deb1015ca71be2b73aef0857d7781'
                '1f352c073b6108d72d9810a30914dff4'
            )
            cmac_msg = bytes.fromhex('6bc1bee22e409f96e93d7e117393172a')
            cmac_ol = struct.pack('<I', 16)
            send_command(proc, 'CMAC-AES-256', cmac_ol, cmac_key, cmac_msg)
            r = read_response(proc)
            assert r[0] == bytes.fromhex('28a7023f452e8f82bd4bf28d8c37c35c')

            # 7: PBKDF2
            pbkdf2_iter = struct.pack('<I', 4096)
            pbkdf2_dklen = struct.pack('<I', 32)
            send_command(proc, 'PBKDF2-HMAC-SHA256', b'password', b'salt',
                         pbkdf2_iter, pbkdf2_dklen)
            r = read_response(proc)
            expected_dk = hashlib.pbkdf2_hmac('sha256', b'password', b'salt',
                                              4096, dklen=32)
            assert r[0] == expected_dk

        finally:
            proc.stdin.close()
            proc.wait(timeout=5)

    def test_clean_exit_on_eof(self):
        """Module should exit 0 when stdin is closed."""
        proc = start_module()
        send_command(proc, 'SHA2-256', b'x')
        read_response(proc)
        proc.stdin.close()
        rc = proc.wait(timeout=5)
        assert rc == 0, f"Module exited with status {rc}, expected 0"
