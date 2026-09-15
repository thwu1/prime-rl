
"""Tests for Noise Protocol forensic analysis results."""

import json
import os
import pytest


RESULTS_PATH = "/app/results.json"

# Expected results derived from cacophony test vectors
EXPECTED = [
    {
        "protocol": "Noise_XX_25519_ChaChaPoly_BLAKE2s",
        "handshake_hash": "6c4c56cf71612f72d05ceb96c0155e6f4ea54a26b504c93de632a2db4a49d200",
        "transport_payloads": [
            "4361726c204d656e676572",
            "4a65616e2d426170746973746520536179",
            "457567656e2042f6686d20766f6e2042617765726b",
        ],
    },
    {
        "protocol": "Noise_IK_25519_AESGCM_SHA256",
        "handshake_hash": "669c8640d9e42a3cda2f232f78597ceefb01daa6e3df81181ccce6fc6b5026bf",
        "transport_payloads": [
            "462e20412e20486179656b",
            "4361726c204d656e676572",
            "4a65616e2d426170746973746520536179",
            "457567656e2042f6686d20766f6e2042617765726b",
        ],
    },
    {
        "protocol": "Noise_NNpsk0_25519_ChaChaPoly_SHA256",
        "handshake_hash": "f4d03dc34495c95729ea6de9e1b59004b59733102488b3e24bc441e0be208eaf",
        "transport_payloads": [
            "462e20412e20486179656b",
            "4361726c204d656e676572",
            "4a65616e2d426170746973746520536179",
            "457567656e2042f6686d20766f6e2042617765726b",
        ],
    },
    {
        "protocol": "Noise_KK_25519_ChaChaPoly_BLAKE2b",
        "handshake_hash": "76dbc866183c8ee7363dbf0ebab8d6355010245f9817aa78359818a03a052586d7e8b4bb2ae5622a1a61212df90af04bb2b2cc189ce0e819ba0c4970c9f71805",
        "transport_payloads": [
            "462e20412e20486179656b",
            "4361726c204d656e676572",
            "4a65616e2d426170746973746520536179",
            "457567656e2042f6686d20766f6e2042617765726b",
        ],
    },
    {
        "protocol": "Noise_NK_25519_AESGCM_BLAKE2s",
        "handshake_hash": "ffc57d6f944a5d4bb85695b8e5adb722c705ac5131c8ab6d52e6754c87725fec",
        "transport_payloads": [
            "462e20412e20486179656b",
            "4361726c204d656e676572",
            "4a65616e2d426170746973746520536179",
            "457567656e2042f6686d20766f6e2042617765726b",
        ],
    },
]


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH, "r") as f:
        data = json.load(f)
    assert isinstance(data, list), "Results must be a JSON array"
    assert len(data) == 5, f"Expected 5 session results, got {len(data)}"
    return data


class TestHandshakeHashes:
    """Verify handshake hashes for all sessions."""

    def test_xx_chachapoly_blake2s_hash(self, results):
        actual = results[0]["handshake_hash"].lower()
        expected = EXPECTED[0]["handshake_hash"]
        assert actual == expected, (
            f"XX/ChaChaPoly/BLAKE2s handshake_hash mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )

    def test_ik_aesgcm_sha256_hash(self, results):
        actual = results[1]["handshake_hash"].lower()
        expected = EXPECTED[1]["handshake_hash"]
        assert actual == expected, (
            f"IK/AESGCM/SHA256 handshake_hash mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )

    def test_nnpsk0_chachapoly_sha256_hash(self, results):
        actual = results[2]["handshake_hash"].lower()
        expected = EXPECTED[2]["handshake_hash"]
        assert actual == expected, (
            f"NNpsk0/ChaChaPoly/SHA256 handshake_hash mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )

    def test_kk_chachapoly_blake2b_hash(self, results):
        actual = results[3]["handshake_hash"].lower()
        expected = EXPECTED[3]["handshake_hash"]
        assert actual == expected, (
            f"KK/ChaChaPoly/BLAKE2b handshake_hash mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )

    def test_kk_blake2b_hash_length(self, results):
        """BLAKE2b produces a 64-byte (128 hex char) handshake hash."""
        h = results[3]["handshake_hash"]
        assert len(h) == 128, f"BLAKE2b hash should be 128 hex chars, got {len(h)}"

    def test_nk_aesgcm_blake2s_hash(self, results):
        actual = results[4]["handshake_hash"].lower()
        expected = EXPECTED[4]["handshake_hash"]
        assert actual == expected, (
            f"NK/AESGCM/BLAKE2s handshake_hash mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )


class TestTransportPayloads:
    """Verify decrypted transport payloads for all sessions."""

    def test_xx_transport_count(self, results):
        payloads = results[0]["transport_payloads"]
        assert len(payloads) == 3, (
            f"XX pattern should have 3 transport messages, got {len(payloads)}"
        )

    def test_xx_transport_payloads(self, results):
        actual = [p.lower() for p in results[0]["transport_payloads"]]
        expected = EXPECTED[0]["transport_payloads"]
        assert actual == expected, (
            f"XX transport payload mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )

    def test_ik_transport_count(self, results):
        payloads = results[1]["transport_payloads"]
        assert len(payloads) == 4, (
            f"IK pattern should have 4 transport messages, got {len(payloads)}"
        )

    def test_ik_transport_payloads(self, results):
        actual = [p.lower() for p in results[1]["transport_payloads"]]
        expected = EXPECTED[1]["transport_payloads"]
        assert actual == expected, (
            f"IK transport payload mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )

    def test_nnpsk0_transport_payloads(self, results):
        actual = [p.lower() for p in results[2]["transport_payloads"]]
        expected = EXPECTED[2]["transport_payloads"]
        assert actual == expected, (
            f"NNpsk0 transport payload mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )

    def test_kk_transport_payloads(self, results):
        actual = [p.lower() for p in results[3]["transport_payloads"]]
        expected = EXPECTED[3]["transport_payloads"]
        assert actual == expected, (
            f"KK transport payload mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )

    def test_nk_transport_payloads(self, results):
        actual = [p.lower() for p in results[4]["transport_payloads"]]
        expected = EXPECTED[4]["transport_payloads"]
        assert actual == expected, (
            f"NK transport payload mismatch:\n"
            f"  expected: {expected}\n  got:      {actual}"
        )


class TestResultsStructure:
    """Verify the overall structure of results.json."""

    def test_all_sessions_have_handshake_hash(self, results):
        for i, r in enumerate(results):
            assert "handshake_hash" in r, f"Session {i} missing handshake_hash"
            assert isinstance(r["handshake_hash"], str), (
                f"Session {i} handshake_hash must be a string"
            )

    def test_all_sessions_have_transport_payloads(self, results):
        for i, r in enumerate(results):
            assert "transport_payloads" in r, (
                f"Session {i} missing transport_payloads"
            )
            assert isinstance(r["transport_payloads"], list), (
                f"Session {i} transport_payloads must be a list"
            )

    def test_all_hashes_are_hex(self, results):
        for i, r in enumerate(results):
            h = r["handshake_hash"]
            try:
                bytes.fromhex(h)
            except ValueError:
                pytest.fail(f"Session {i} handshake_hash is not valid hex: {h}")

    def test_all_payloads_are_hex(self, results):
        for i, r in enumerate(results):
            for j, p in enumerate(r["transport_payloads"]):
                try:
                    bytes.fromhex(p)
                except ValueError:
                    pytest.fail(
                        f"Session {i} transport_payload[{j}] is not valid hex: {p}"
                    )
