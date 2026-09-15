"""Tests for QUIC packet protection compliance evaluation task.
Verifies the compliance report and reference implementation against
RFC 9001 and RFC 9369 Appendix A test vectors.
"""

import json
import sys
import pytest

sys.path.insert(0, "/app")

# ---------------------------------------------------------------------------
# RFC test vector constants
# ---------------------------------------------------------------------------

DCID = bytes.fromhex("8394c8f03e515708")

CRYPTO_FRAME = bytes.fromhex(
    "060040f1010000ed0303ebf8fa56f129"
    "39b9584a3896472ec40bb863cfd3e868"
    "04fe3a47f06a2b69484c000004130113"
    "02010000c000000010000e00000b6578"
    "616d706c652e636f6dff01000100000a"
    "00080006001d00170018001000070005"
    "04616c706e0005000501000000000033"
    "00260024001d00209370b2c9caa47fba"
    "baf4559fedba753de171fa71f50f1ce1"
    "5d43e994ec74d748002b000302030400"
    "0d0010000e0403050306030203080408"
    "050806002d00020101001c0002400100"
    "3900320408ffffffffffffffff050480"
    "00ffff07048000ffff08011001048000"
    "75300901100f088394c8f03e51570806"
    "048000ffff"
)
CLIENT_PAYLOAD = CRYPTO_FRAME + b"\x00" * (1162 - len(CRYPTO_FRAME))

SERVER_PAYLOAD = bytes.fromhex(
    "02000000000600405a020000560303ee"
    "fce7f7b37ba1d1632e96677825ddf739"
    "88cfc79825df566dc5430b9a045a1200"
    "130100002e00330024001d00209d3c94"
    "0d89690b84d08a60993c144eca684d10"
    "81287c834d5311bcf32bb9da1a002b00"
    "020304"
)

CHACHA20_SECRET = bytes.fromhex(
    "9ac312a7f877468ebe69422748ad00a1"
    "5443f18203a07d6060f688f30f21632b"
)


# ===================================================================
# COMPLIANCE REPORT TESTS
# ===================================================================

class TestComplianceReport:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/compliance_report.json") as f:
            self.report = json.load(f)

    def test_alpha_passes(self):
        assert self.report["alpha"]["status"] == "PASS"
        assert self.report["alpha"]["violations"] == []

    def test_beta_v2_key_derivation(self):
        assert self.report["beta"]["status"] == "FAIL"
        assert set(self.report["beta"]["violations"]) == {"v2_key_derivation"}

    def test_gamma_nonce_construction(self):
        assert self.report["gamma"]["status"] == "FAIL"
        assert set(self.report["gamma"]["violations"]) == {"aead_nonce_construction"}

    def test_delta_sample_offset(self):
        assert self.report["delta"]["status"] == "FAIL"
        assert set(self.report["delta"]["violations"]) == {"header_protection_sample_offset"}

    def test_epsilon_retry_and_chacha(self):
        assert self.report["epsilon"]["status"] == "FAIL"
        assert set(self.report["epsilon"]["violations"]) == {
            "retry_pseudo_packet", "chacha20_header_protection"
        }


# ===================================================================
# REFERENCE IMPLEMENTATION TESTS
# ===================================================================

@pytest.fixture(scope="module")
def ref():
    import reference_impl
    return reference_impl


# ----- V1 Key Derivation (RFC 9001 A.1) -----

class TestRefV1Keys:
    def test_initial_secret(self, ref):
        keys = ref.derive_initial_keys(DCID, 1)
        assert keys["initial_secret"] == bytes.fromhex(
            "7db5df06e7a69e432496adedb0085192"
            "3595221596ae2ae9fb8115c1e9ed0a44"
        )

    def test_client_key(self, ref):
        keys = ref.derive_initial_keys(DCID, 1)
        assert keys["client_key"] == bytes.fromhex(
            "1f369613dd76d5467730efcbe3b1a22d"
        )

    def test_client_iv(self, ref):
        keys = ref.derive_initial_keys(DCID, 1)
        assert keys["client_iv"] == bytes.fromhex(
            "fa044b2f42a3fd3b46fb255c"
        )

    def test_server_key(self, ref):
        keys = ref.derive_initial_keys(DCID, 1)
        assert keys["server_key"] == bytes.fromhex(
            "cf3a5331653c364c88f0f379b6067e37"
        )


# ----- V2 Key Derivation (RFC 9369 A.1) -----

class TestRefV2Keys:
    def test_initial_secret(self, ref):
        keys = ref.derive_initial_keys(DCID, 2)
        assert keys["initial_secret"] == bytes.fromhex(
            "2062e8b3cd8d52092614b8071d0aa1fb"
            "7c2e3ac193f78b280e72d8f5751f6aba"
        )

    def test_client_key(self, ref):
        keys = ref.derive_initial_keys(DCID, 2)
        assert keys["client_key"] == bytes.fromhex(
            "8b1a0bc121284290a29e0971b5cd045d"
        )

    def test_client_iv(self, ref):
        keys = ref.derive_initial_keys(DCID, 2)
        assert keys["client_iv"] == bytes.fromhex(
            "91f73e2351d8fa91660e909f"
        )


# ----- V1 Client Initial (RFC 9001 A.2) -----

class TestRefV1ClientInitial:
    def test_first_64_bytes(self, ref):
        keys = ref.derive_initial_keys(DCID, 1)
        header = bytes.fromhex(
            "c300000001088394c8f03e5157080000449e00000002"
        )
        protected = ref.protect_initial_packet(
            header, CLIENT_PAYLOAD,
            keys["client_key"], keys["client_iv"], keys["client_hp"],
        )
        assert protected[:64] == bytes.fromhex(
            "c000000001088394c8f03e5157080000"
            "449e7b9aec34d1b1c98dd7689fb8ec11"
            "d242b123dc9bd8bab936b47d92ec356c"
            "0bab7df5976d27cd449f63300099f399"
        )

    def test_last_16_bytes(self, ref):
        keys = ref.derive_initial_keys(DCID, 1)
        header = bytes.fromhex(
            "c300000001088394c8f03e5157080000449e00000002"
        )
        protected = ref.protect_initial_packet(
            header, CLIENT_PAYLOAD,
            keys["client_key"], keys["client_iv"], keys["client_hp"],
        )
        assert protected[-16:] == bytes.fromhex(
            "e221af44860018ab0856972e194cd934"
        )


# ----- V2 Client Initial (RFC 9369 A.2) -----

class TestRefV2ClientInitial:
    def test_first_64_bytes(self, ref):
        keys = ref.derive_initial_keys(DCID, 2)
        header = bytes.fromhex(
            "d36b3343cf088394c8f03e5157080000449e00000002"
        )
        protected = ref.protect_initial_packet(
            header, CLIENT_PAYLOAD,
            keys["client_key"], keys["client_iv"], keys["client_hp"],
        )
        assert protected[:64] == bytes.fromhex(
            "d76b3343cf088394c8f03e5157080000"
            "449ea0c95e82ffe67b6abcdb4298b485"
            "dd04de806071bf03dceebfa162e75d6c"
            "96058bdbfb127cdfcbf903388e99ad04"
        )


# ----- V1 Server Initial (RFC 9001 A.3) -----

class TestRefV1ServerInitial:
    def test_complete_packet(self, ref):
        keys = ref.derive_initial_keys(DCID, 1)
        header = bytes.fromhex(
            "c1000000010008f067a5502a4262b50040750001"
        )
        protected = ref.protect_initial_packet(
            header, SERVER_PAYLOAD,
            keys["server_key"], keys["server_iv"], keys["server_hp"],
        )
        expected = bytes.fromhex(
            "cf000000010008f067a5502a4262b500"
            "4075c0d95a482cd0991cd25b0aac406a"
            "5816b6394100f37a1c69797554780bb3"
            "8cc5a99f5ede4cf73c3ec2493a1839b3"
            "dbcba3f6ea46c5b7684df3548e7ddeb9"
            "c3bf9c73cc3f3bded74b562bfb19fb84"
            "022f8ef4cdd93795d77d06edbb7aaf2f"
            "58891850abbdca3d20398c276456cbc4"
            "2158407dd074ee"
        )
        assert protected == expected


# ----- Retry Integrity Tags -----

class TestRefRetryTags:
    def test_v1_retry_tag(self, ref):
        retry_no_tag = bytes.fromhex(
            "ff000000010008f067a5502a4262b574"
            "6f6b656e"
        )
        tag = ref.compute_retry_integrity_tag(DCID, retry_no_tag, 1)
        assert tag == bytes.fromhex(
            "04a265ba2eff4d829058fb3f0f2496ba"
        )

    def test_v2_retry_tag(self, ref):
        retry_no_tag = bytes.fromhex(
            "cf6b3343cf0008f067a5502a4262b574"
            "6f6b656e"
        )
        tag = ref.compute_retry_integrity_tag(DCID, retry_no_tag, 2)
        assert tag == bytes.fromhex(
            "c8646ce8bfe33952d955543665dcc7b6"
        )


# ----- ChaCha20-Poly1305 Short Header -----

class TestRefChaCha20:
    def test_v1_short_header(self, ref):
        keys = ref.derive_keys_from_secret(CHACHA20_SECRET, 1, 32)
        protected = ref.protect_short_header_chacha20(
            bytes.fromhex("4200bff4"), bytes.fromhex("01"), 654360564,
            keys["key"], keys["iv"], keys["hp"],
        )
        assert protected == bytes.fromhex(
            "4cfe4189655e5cd55c41f69080575d79"
            "99c25a5bfb"
        )

    def test_v2_short_header(self, ref):
        keys = ref.derive_keys_from_secret(CHACHA20_SECRET, 2, 32)
        protected = ref.protect_short_header_chacha20(
            bytes.fromhex("4200bff4"), bytes.fromhex("01"), 654360564,
            keys["key"], keys["iv"], keys["hp"],
        )
        assert protected == bytes.fromhex(
            "5558b1c60ae7b6b932bc27d786f4bc2b"
            "b20f2162ba"
        )


# ----- Unprotect Round-Trip -----

class TestRefUnprotect:
    def test_v1_roundtrip(self, ref):
        keys = ref.derive_initial_keys(DCID, 1)
        header = bytes.fromhex(
            "c300000001088394c8f03e5157080000449e00000002"
        )
        protected = ref.protect_initial_packet(
            header, CLIENT_PAYLOAD,
            keys["client_key"], keys["client_iv"], keys["client_hp"],
        )
        dec_header, dec_payload = ref.unprotect_initial_packet(
            protected,
            keys["client_key"], keys["client_iv"], keys["client_hp"],
        )
        assert dec_header == header
        assert dec_payload == CLIENT_PAYLOAD

    def test_v2_roundtrip(self, ref):
        keys = ref.derive_initial_keys(DCID, 2)
        header = bytes.fromhex(
            "d36b3343cf088394c8f03e5157080000449e00000002"
        )
        protected = ref.protect_initial_packet(
            header, CLIENT_PAYLOAD,
            keys["client_key"], keys["client_iv"], keys["client_hp"],
        )
        dec_header, dec_payload = ref.unprotect_initial_packet(
            protected,
            keys["client_key"], keys["client_iv"], keys["client_hp"],
        )
        assert dec_header == header
        assert dec_payload == CLIENT_PAYLOAD
