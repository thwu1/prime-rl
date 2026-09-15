"""
Tests for QUIC Initial Packet Analysis Tool.

"""

import sys
import pytest

sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Key Derivation Tests — RFC 9001 Appendix A.1 (v1) and dynamic reference (v2)
# ---------------------------------------------------------------------------

class TestKeyDerivationV1:
    """Verify Initial key derivation against RFC 9001 Appendix A.1 test vectors."""

    DCID = bytes.fromhex("8394c8f03e515708")

    def test_client_key(self):
        from quic_crypto import derive_initial_keys
        r = derive_initial_keys(self.DCID, 0x00000001, "client")
        assert r["key"] == bytes.fromhex("1f369613dd76d5467730efcbe3b1a22d")

    def test_client_iv(self):
        from quic_crypto import derive_initial_keys
        r = derive_initial_keys(self.DCID, 0x00000001, "client")
        assert r["iv"] == bytes.fromhex("fa044b2f42a3fd3b46fb255c")

    def test_client_hp(self):
        from quic_crypto import derive_initial_keys
        r = derive_initial_keys(self.DCID, 0x00000001, "client")
        assert r["hp"] == bytes.fromhex("9f50449e04a0e810283a1e9933adedd2")

    def test_server_key(self):
        from quic_crypto import derive_initial_keys
        r = derive_initial_keys(self.DCID, 0x00000001, "server")
        assert r["key"] == bytes.fromhex("cf3a5331653c364c88f0f379b6067e37")

    def test_server_iv(self):
        from quic_crypto import derive_initial_keys
        r = derive_initial_keys(self.DCID, 0x00000001, "server")
        assert r["iv"] == bytes.fromhex("0ac1493ca1905853b0bba03e")

    def test_server_hp(self):
        from quic_crypto import derive_initial_keys
        r = derive_initial_keys(self.DCID, 0x00000001, "server")
        assert r["hp"] == bytes.fromhex("c206b8d9b9f0f37644430b490eeaa314")


class TestKeyDerivationV2:
    """Verify v2 key derivation against a dynamically computed reference."""

    DCID = bytes.fromhex("8394c8f03e515708")

    @staticmethod
    def _ref_expand(secret, label, length):
        """Minimal reference HKDF-Expand-Label for verification."""
        import struct
        from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
        from cryptography.hazmat.primitives import hashes
        full_label = b"tls13 " + label
        info = struct.pack(">H", length) + bytes([len(full_label)]) + full_label + b"\x00"
        return HKDFExpand(
            algorithm=hashes.SHA256(), length=length, info=info
        ).derive(secret)

    def test_v2_client(self):
        import hmac, hashlib
        from quic_crypto import derive_initial_keys

        salt_v2 = bytes.fromhex("0dede3def700a6db819381be6e269dcbf9bd2ed9")
        initial_secret = hmac.new(salt_v2, self.DCID, hashlib.sha256).digest()
        cs = self._ref_expand(initial_secret, b"client in", 32)
        exp_key = self._ref_expand(cs, b"quicv2 key", 16)
        exp_iv = self._ref_expand(cs, b"quicv2 iv", 12)
        exp_hp = self._ref_expand(cs, b"quicv2 hp", 16)

        r = derive_initial_keys(self.DCID, 0x6b3343cf, "client")
        assert r["key"] == exp_key
        assert r["iv"] == exp_iv
        assert r["hp"] == exp_hp

    def test_v2_server(self):
        import hmac, hashlib
        from quic_crypto import derive_initial_keys

        salt_v2 = bytes.fromhex("0dede3def700a6db819381be6e269dcbf9bd2ed9")
        initial_secret = hmac.new(salt_v2, self.DCID, hashlib.sha256).digest()
        ss = self._ref_expand(initial_secret, b"server in", 32)
        exp_key = self._ref_expand(ss, b"quicv2 key", 16)
        exp_iv = self._ref_expand(ss, b"quicv2 iv", 12)
        exp_hp = self._ref_expand(ss, b"quicv2 hp", 16)

        r = derive_initial_keys(self.DCID, 0x6b3343cf, "server")
        assert r["key"] == exp_key
        assert r["iv"] == exp_iv
        assert r["hp"] == exp_hp


class TestKeyDerivationCustomDCID:
    """Ensure the implementation does not hardcode RFC test-vector values."""

    @staticmethod
    def _ref_expand(secret, label, length):
        import struct
        from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
        from cryptography.hazmat.primitives import hashes
        full_label = b"tls13 " + label
        info = struct.pack(">H", length) + bytes([len(full_label)]) + full_label + b"\x00"
        return HKDFExpand(
            algorithm=hashes.SHA256(), length=length, info=info
        ).derive(secret)

    def test_custom_dcid_v1_client(self):
        import hmac, hashlib
        from quic_crypto import derive_initial_keys

        dcid = bytes.fromhex("deadbeef01020304")
        salt = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")
        initial_secret = hmac.new(salt, dcid, hashlib.sha256).digest()
        cs = self._ref_expand(initial_secret, b"client in", 32)
        exp_key = self._ref_expand(cs, b"quic key", 16)
        exp_iv = self._ref_expand(cs, b"quic iv", 12)
        exp_hp = self._ref_expand(cs, b"quic hp", 16)

        r = derive_initial_keys(dcid, 0x00000001, "client")
        assert r["key"] == exp_key
        assert r["iv"] == exp_iv
        assert r["hp"] == exp_hp

    def test_custom_dcid_v1_server(self):
        import hmac, hashlib
        from quic_crypto import derive_initial_keys

        dcid = bytes.fromhex("abcdef1234567890")
        salt = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")
        initial_secret = hmac.new(salt, dcid, hashlib.sha256).digest()
        ss = self._ref_expand(initial_secret, b"server in", 32)
        exp_key = self._ref_expand(ss, b"quic key", 16)
        exp_iv = self._ref_expand(ss, b"quic iv", 12)
        exp_hp = self._ref_expand(ss, b"quic hp", 16)

        r = derive_initial_keys(dcid, 0x00000001, "server")
        assert r["key"] == exp_key
        assert r["iv"] == exp_iv
        assert r["hp"] == exp_hp

    def test_custom_dcid_v2(self):
        import hmac, hashlib
        from quic_crypto import derive_initial_keys

        dcid = bytes.fromhex("f00dcafe99887766")
        salt = bytes.fromhex("0dede3def700a6db819381be6e269dcbf9bd2ed9")
        initial_secret = hmac.new(salt, dcid, hashlib.sha256).digest()
        cs = self._ref_expand(initial_secret, b"client in", 32)
        exp_key = self._ref_expand(cs, b"quicv2 key", 16)
        exp_iv = self._ref_expand(cs, b"quicv2 iv", 12)

        r = derive_initial_keys(dcid, 0x6b3343cf, "client")
        assert r["key"] == exp_key
        assert r["iv"] == exp_iv


# ---------------------------------------------------------------------------
# Variable-Length Integer Tests — RFC 9000 Section 16
# ---------------------------------------------------------------------------

class TestVarint:
    def test_1byte(self):
        from quic_crypto import parse_quic_varint
        val, n = parse_quic_varint(bytes([0x25]), 0)
        assert val == 37 and n == 1

    def test_2byte(self):
        from quic_crypto import parse_quic_varint
        val, n = parse_quic_varint(bytes.fromhex("7bbd"), 0)
        assert val == 15293 and n == 2

    def test_4byte(self):
        from quic_crypto import parse_quic_varint
        val, n = parse_quic_varint(bytes.fromhex("9d7f3e7d"), 0)
        assert val == 494878333 and n == 4

    def test_8byte(self):
        from quic_crypto import parse_quic_varint
        val, n = parse_quic_varint(bytes.fromhex("c2197c5eff14e88c"), 0)
        assert val == 151288809941952652 and n == 8

    def test_zero(self):
        from quic_crypto import parse_quic_varint
        val, n = parse_quic_varint(bytes([0x00]), 0)
        assert val == 0 and n == 1

    def test_with_offset(self):
        from quic_crypto import parse_quic_varint
        data = bytes([0xFF, 0xFF, 0x25, 0x00])
        val, n = parse_quic_varint(data, 2)
        assert val == 37 and n == 1

    def test_max_1byte(self):
        from quic_crypto import parse_quic_varint
        val, n = parse_quic_varint(bytes([0x3f]), 0)
        assert val == 63 and n == 1

    def test_min_2byte(self):
        from quic_crypto import parse_quic_varint
        val, n = parse_quic_varint(bytes.fromhex("4040"), 0)
        assert val == 64 and n == 2


# ---------------------------------------------------------------------------
# Frame Parsing Tests
# ---------------------------------------------------------------------------

class TestFrameParsing:
    def test_padding_only(self):
        from quic_crypto import parse_frames
        frames = parse_frames(bytes(5))
        padding = [f for f in frames if f["type"] == "PADDING"]
        assert len(padding) >= 1  # at least some PADDING recognized

    def test_ping(self):
        from quic_crypto import parse_frames
        frames = parse_frames(bytes([0x01]))
        assert any(f["type"] == "PING" for f in frames)

    def test_crypto_frame(self):
        from quic_crypto import parse_frames
        # CRYPTO frame: type=0x06, offset=varint(0)=0x00, length=varint(5)=0x05, data=b"hello"
        payload = bytes([0x06, 0x00, 0x05]) + b"hello"
        frames = parse_frames(payload)
        crypto = [f for f in frames if f["type"] == "CRYPTO"]
        assert len(crypto) == 1
        assert crypto[0]["offset"] == 0
        assert crypto[0]["length"] == 5
        assert crypto[0]["data"] == b"hello"

    def test_crypto_with_nonzero_offset(self):
        from quic_crypto import parse_frames
        # CRYPTO frame with offset=100 (varint 0x4064), length=3, data=b"xyz"
        payload = bytes.fromhex("06") + bytes.fromhex("4064") + bytes([0x03]) + b"xyz"
        frames = parse_frames(payload)
        crypto = [f for f in frames if f["type"] == "CRYPTO"]
        assert len(crypto) == 1
        assert crypto[0]["offset"] == 100
        assert crypto[0]["length"] == 3
        assert crypto[0]["data"] == b"xyz"

    def test_mixed_frames(self):
        from quic_crypto import parse_frames
        # PADDING + CRYPTO(offset=0, len=3, "abc") + PING + PADDING
        payload = bytes([0x00, 0x06, 0x00, 0x03]) + b"abc" + bytes([0x01, 0x00])
        frames = parse_frames(payload)
        crypto = [f for f in frames if f["type"] == "CRYPTO"]
        assert len(crypto) == 1
        assert crypto[0]["data"] == b"abc"
        assert any(f["type"] == "PING" for f in frames)

    def test_ack_frame(self):
        from quic_crypto import parse_frames
        # ACK frame (type=0x02): largest=10, delay=5, count=0, first_range=2
        payload = bytes([0x02, 0x0a, 0x05, 0x00, 0x02])
        frames = parse_frames(payload)
        ack = [f for f in frames if f["type"] == "ACK"]
        assert len(ack) == 1


# ---------------------------------------------------------------------------
# Full Pipeline Tests — header protection removal + AEAD decryption
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """
    Build a valid encrypted + header-protected QUIC v1 Initial packet
    using raw crypto primitives, then verify the implementation can
    reverse all operations and recover the plaintext.
    """

    @staticmethod
    def _ref_derive(dcid, perspective="client"):
        """Reference key derivation using raw crypto (for test-packet construction)."""
        import hmac, hashlib, struct
        from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
        from cryptography.hazmat.primitives import hashes

        salt = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")
        initial_secret = hmac.new(salt, dcid, hashlib.sha256).digest()

        def _exp(secret, label, length):
            fl = b"tls13 " + label
            info = struct.pack(">H", length) + bytes([len(fl)]) + fl + b"\x00"
            return HKDFExpand(algorithm=hashes.SHA256(), length=length, info=info).derive(secret)

        ps = _exp(initial_secret, b"client in" if perspective == "client" else b"server in", 32)
        return {
            "key": _exp(ps, b"quic key", 16),
            "iv": _exp(ps, b"quic iv", 12),
            "hp": _exp(ps, b"quic hp", 16),
        }

    @staticmethod
    def _build_protected_packet(dcid, scid, pn, pn_length, plaintext, keys):
        """Construct a protected QUIC v1 Initial packet from plaintext payload."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        # --- Build unprotected header ---
        first_byte = 0xC0 | (pn_length - 1)
        pn_bytes = pn.to_bytes(pn_length, "big")

        header = bytes([first_byte])
        header += (0x00000001).to_bytes(4, "big")          # Version
        header += bytes([len(dcid)]) + dcid                # DCID
        header += bytes([len(scid)]) + scid                # SCID
        header += bytes([0])                                # Token length = 0
        total_len = pn_length + len(plaintext) + 16         # PN + ciphertext + tag
        header += (0x4000 | total_len).to_bytes(2, "big")   # Length (2-byte varint)
        header += pn_bytes                                  # Packet number

        # --- AEAD encrypt ---
        nonce = bytearray(keys["iv"])
        pn_pad = pn.to_bytes(len(nonce), "big")
        for i in range(len(nonce)):
            nonce[i] ^= pn_pad[i]
        ct = AESGCM(keys["key"]).encrypt(bytes(nonce), plaintext, header)

        # --- Apply header protection ---
        pn_offset = len(header) - pn_length
        full = header + ct
        sample = full[pn_offset + 4: pn_offset + 4 + 16]

        cipher_obj = Cipher(algorithms.AES(keys["hp"]), modes.ECB())
        mask = cipher_obj.encryptor().update(sample)

        pf = first_byte ^ (mask[0] & 0x0F)
        ppn = bytearray(pn_bytes)
        for i in range(pn_length):
            ppn[i] ^= mask[1 + i]

        protected = bytes([pf]) + full[1:pn_offset] + bytes(ppn) + ct
        return protected

    # ---- actual tests ----

    def test_1byte_pn_basic(self):
        from quic_crypto import derive_initial_keys, remove_header_protection, decrypt_payload, parse_frames

        dcid = bytes.fromhex("0102030405060708")
        scid = bytes.fromhex("aabbccdd")
        pn, pn_length = 0, 1
        plaintext = bytes([0x06, 0x00, 0x05]) + b"hello" + bytes(50)

        keys = self._ref_derive(dcid)
        pkt = self._build_protected_packet(dcid, scid, pn, pn_length, plaintext, keys)

        # Student decryption
        sk = derive_initial_keys(dcid, 0x00000001, "client")
        hdr, decoded_pn, decoded_pn_len, ps = remove_header_protection(pkt, sk["hp"])
        assert decoded_pn == 0
        assert decoded_pn_len == 1

        dec = decrypt_payload(pkt[ps:], decoded_pn, sk["key"], sk["iv"], hdr)
        assert dec == plaintext

        frames = parse_frames(dec)
        crypto = [f for f in frames if f["type"] == "CRYPTO"]
        assert len(crypto) == 1
        assert crypto[0]["data"] == b"hello"
        assert crypto[0]["offset"] == 0
        assert crypto[0]["length"] == 5

    def test_2byte_pn(self):
        from quic_crypto import derive_initial_keys, remove_header_protection, decrypt_payload

        dcid = bytes.fromhex("aabbccddeeff0011")
        scid = bytes.fromhex("1234")
        pn, pn_length = 300, 2
        plaintext = bytes([0x06, 0x00, 0x03]) + b"xyz" + bytes(40)

        keys = self._ref_derive(dcid)
        pkt = self._build_protected_packet(dcid, scid, pn, pn_length, plaintext, keys)

        sk = derive_initial_keys(dcid, 0x00000001, "client")
        hdr, decoded_pn, decoded_pn_len, ps = remove_header_protection(pkt, sk["hp"])
        assert decoded_pn == 300
        assert decoded_pn_len == 2

        dec = decrypt_payload(pkt[ps:], decoded_pn, sk["key"], sk["iv"], hdr)
        assert dec == plaintext

    def test_4byte_pn(self):
        from quic_crypto import derive_initial_keys, remove_header_protection, decrypt_payload

        dcid = bytes.fromhex("1111222233334444")
        scid = bytes.fromhex("aa")
        pn, pn_length = 70000, 4
        plaintext = bytes([0x01]) + bytes(60)  # PING + PADDING

        keys = self._ref_derive(dcid)
        pkt = self._build_protected_packet(dcid, scid, pn, pn_length, plaintext, keys)

        sk = derive_initial_keys(dcid, 0x00000001, "client")
        hdr, decoded_pn, decoded_pn_len, ps = remove_header_protection(pkt, sk["hp"])
        assert decoded_pn == 70000
        assert decoded_pn_len == 4

        dec = decrypt_payload(pkt[ps:], decoded_pn, sk["key"], sk["iv"], hdr)
        assert dec == plaintext

    def test_server_perspective(self):
        """Encrypt as server, decrypt as server."""
        from quic_crypto import derive_initial_keys, remove_header_protection, decrypt_payload

        dcid = bytes.fromhex("5566778899aabbcc")
        scid = bytes.fromhex("ddee")
        pn, pn_length = 1, 1
        plaintext = bytes([0x06, 0x00, 0x06]) + b"server" + bytes(30)

        keys = self._ref_derive(dcid, "server")
        pkt = self._build_protected_packet(dcid, scid, pn, pn_length, plaintext, keys)

        sk = derive_initial_keys(dcid, 0x00000001, "server")
        hdr, decoded_pn, decoded_pn_len, ps = remove_header_protection(pkt, sk["hp"])
        assert decoded_pn == 1

        dec = decrypt_payload(pkt[ps:], decoded_pn, sk["key"], sk["iv"], hdr)
        assert dec == plaintext

    def test_large_payload(self):
        """Test with a larger payload closer to real Initial packet sizes."""
        from quic_crypto import derive_initial_keys, remove_header_protection, decrypt_payload, parse_frames

        dcid = bytes.fromhex("0a0b0c0d0e0f0102")
        scid = bytes.fromhex("ff")
        pn, pn_length = 42, 1

        # Simulate a TLS ClientHello-like blob inside a CRYPTO frame
        fake_ch = bytes(range(256)) * 2  # 512 bytes of patterned data
        # CRYPTO: type=0x06, offset=0, length=varint(512)=0x4200, data=512 bytes
        crypto_frame = bytes([0x06, 0x00]) + (0x4000 | 512).to_bytes(2, "big") + fake_ch
        # Pad to ~1100 bytes total (near QUIC minimum)
        pad_len = 1100 - len(crypto_frame)
        plaintext = crypto_frame + bytes(max(0, pad_len))

        keys = self._ref_derive(dcid)
        pkt = self._build_protected_packet(dcid, scid, pn, pn_length, plaintext, keys)

        sk = derive_initial_keys(dcid, 0x00000001, "client")
        hdr, decoded_pn, decoded_pn_len, ps = remove_header_protection(pkt, sk["hp"])
        assert decoded_pn == 42

        dec = decrypt_payload(pkt[ps:], decoded_pn, sk["key"], sk["iv"], hdr)
        assert dec == plaintext

        frames = parse_frames(dec)
        crypto_list = [f for f in frames if f["type"] == "CRYPTO"]
        assert len(crypto_list) == 1
        assert crypto_list[0]["length"] == 512
        assert crypto_list[0]["data"] == fake_ch


# ---------------------------------------------------------------------------
# Captured Packet Decryption Test
# ---------------------------------------------------------------------------

class TestCapturedPacketDecryption:
    """Verify the agent correctly decrypted the captured packet."""

    @staticmethod
    def _ref_expand(secret, label, length):
        import struct
        from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
        from cryptography.hazmat.primitives import hashes
        full_label = b"tls13 " + label
        info = struct.pack(">H", length) + bytes([len(full_label)]) + full_label + b"\x00"
        return HKDFExpand(
            algorithm=hashes.SHA256(), length=length, info=info
        ).derive(secret)

    def _ref_derive_v1(self, dcid, perspective="client"):
        import hmac, hashlib
        salt = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")
        initial_secret = hmac.new(salt, dcid, hashlib.sha256).digest()
        label = b"client in" if perspective == "client" else b"server in"
        ps = self._ref_expand(initial_secret, label, 32)
        return {
            "key": self._ref_expand(ps, b"quic key", 16),
            "iv": self._ref_expand(ps, b"quic iv", 12),
            "hp": self._ref_expand(ps, b"quic hp", 16),
        }

    def test_decrypted_json_exists_and_valid(self):
        import json, os
        assert os.path.exists("/app/capture/decrypted.json"), \
            "decrypted.json not found at /app/capture/decrypted.json"
        with open("/app/capture/decrypted.json") as f:
            result = json.load(f)
        assert "crypto_data" in result, "missing 'crypto_data' key"
        assert isinstance(result["crypto_data"], str), "crypto_data must be a string"
        bytes.fromhex(result["crypto_data"])  # must be valid hex

    def test_decrypted_content_correct(self):
        """Independently decrypt the captured packet and compare with agent output."""
        import json
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        # Read inputs
        with open("/app/capture/metadata.json") as f:
            meta = json.load(f)
        dcid = bytes.fromhex(meta["dcid"])
        with open("/app/capture/packet.hex") as f:
            pkt = bytes.fromhex(f.read().strip())

        keys = self._ref_derive_v1(dcid)

        # Parse header to locate packet number
        off = 5  # first byte + 4-byte version
        dcid_len = pkt[off]; off += 1 + dcid_len
        scid_len = pkt[off]; off += 1 + scid_len
        # Token length (varint — expect 0 for this capture)
        fb = pkt[off]; pfx = fb >> 6
        if pfx == 0:
            tok_len = fb & 0x3f; off += 1
        elif pfx == 1:
            tok_len = int.from_bytes(pkt[off:off + 2], "big") & 0x3fff; off += 2
        else:
            raise ValueError("unexpected token varint prefix")
        off += tok_len
        # Payload length (varint)
        fb = pkt[off]; pfx = fb >> 6
        if pfx == 0:
            off += 1
        elif pfx == 1:
            off += 2
        else:
            raise ValueError("unexpected payload length varint prefix")

        pn_offset = off

        # Remove header protection
        sample = pkt[pn_offset + 4: pn_offset + 20]
        mask = Cipher(algorithms.AES(keys["hp"]), modes.ECB()).encryptor().update(sample)
        uf = pkt[0] ^ (mask[0] & 0x0f)
        pn_len = (uf & 0x03) + 1
        pn_bytes = bytearray(pkt[pn_offset:pn_offset + pn_len])
        for i in range(pn_len):
            pn_bytes[i] ^= mask[1 + i]
        pn = int.from_bytes(pn_bytes, "big")
        hdr = bytes([uf]) + pkt[1:pn_offset] + bytes(pn_bytes)
        ps = pn_offset + pn_len

        # Decrypt
        nonce = bytearray(keys["iv"])
        pn_pad = pn.to_bytes(12, "big")
        for i in range(12):
            nonce[i] ^= pn_pad[i]
        dec = AESGCM(keys["key"]).decrypt(bytes(nonce), pkt[ps:], hdr)

        # Find first CRYPTO frame (skip leading PADDING)
        foff = 0
        while foff < len(dec) and dec[foff] == 0:
            foff += 1
        assert foff < len(dec) and dec[foff] == 0x06, "Expected CRYPTO frame"
        foff += 1  # skip type
        # Offset varint
        fb = dec[foff]; pfx = fb >> 6
        if pfx == 0:
            foff += 1
        elif pfx == 1:
            foff += 2
        # Length varint
        fb = dec[foff]; pfx = fb >> 6
        if pfx == 0:
            clen = fb & 0x3f; foff += 1
        elif pfx == 1:
            clen = int.from_bytes(dec[foff:foff + 2], "big") & 0x3fff; foff += 2
        expected_data = dec[foff:foff + clen]

        # Compare with agent output
        with open("/app/capture/decrypted.json") as f:
            result = json.load(f)
        assert bytes.fromhex(result["crypto_data"]) == expected_data, \
            "Decrypted CRYPTO frame data does not match independently computed result"
