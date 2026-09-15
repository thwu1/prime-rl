"""
Tests for VaultSync cryptographic attack challenge.

Verifies:
1. The recovered DH private key satisfies g^x mod p == Y
2. The derived ECDSA key matches the stored public key and verifies signatures
3. A forged Noise K-pattern handshake decrypts to the target payload

"""

import json
import base64
import sys
import os

import pytest

sys.path.insert(0, "/app")
from vaultsync import (
    DH_MOD,
    DH_GEN,
    derive_keys,
    KHandShakeState,
    ECDSA,
)
from dissononce.processing.impl.symmetricstate import SymmetricState
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.x25519 import X25519DH
from dissononce.hash.sha512 import SHA512Hash
from tinyec.registry import get_curve


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def public_data():
    with open("/app/public_data.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def attack_results():
    path = "/app/results.json"
    assert os.path.exists(path), (
        "Attack results not found at /app/results.json — "
        "the attack script must write this file"
    )
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Stage 1: DH Key Recovery
# ---------------------------------------------------------------------------

class TestDHKeyRecovery:
    def test_dh_key_field_present(self, attack_results):
        assert "dh_private_key" in attack_results, (
            "results.json must contain 'dh_private_key'"
        )

    def test_dh_key_is_correct(self, attack_results, public_data):
        """g^recovered_key mod p must equal the stored DH public key."""
        dh_sk = int(attack_results["dh_private_key"])
        expected_pk = int(public_data["dh_public_key"])
        computed_pk = pow(DH_GEN, dh_sk, DH_MOD)
        assert computed_pk == expected_pk, (
            f"DH key verification failed: pow(g, x, p) = {computed_pk} "
            f"but expected {expected_pk}"
        )


# ---------------------------------------------------------------------------
# Stage 2: Key Derivation Verification
# ---------------------------------------------------------------------------

class TestKeyDerivation:
    def test_ecdsa_public_key_matches(self, attack_results, public_data):
        """ECDSA public key derived from recovered DH key must match."""
        dh_sk = int(attack_results["dh_private_key"])
        ecdsa_sk, _ = derive_keys(dh_sk)

        curve = get_curve("secp256r1")
        computed_pk = ecdsa_sk * curve.g

        expected_x = int(public_data["ecdsa_public_key"]["x"])
        expected_y = int(public_data["ecdsa_public_key"]["y"])

        assert computed_pk.x == expected_x and computed_pk.y == expected_y, (
            "Derived ECDSA public key does not match stored public key"
        )

    def test_ecdsa_signatures_verify(self, attack_results, public_data):
        """Stored ECDSA signatures must verify under the derived key."""
        dh_sk = int(attack_results["dh_private_key"])
        ecdsa_sk, _ = derive_keys(dh_sk)

        curve = get_curve("secp256r1")
        ecdsa_pk = ecdsa_sk * curve.g

        for i, update in enumerate(public_data["signed_updates"][:5]):
            msg = base64.b64decode(update["message"])
            sig = (int(update["signature_r"]), int(update["signature_s"]))
            assert ECDSA.verify(ecdsa_pk, msg, sig), (
                f"ECDSA signature verification failed for update #{i}"
            )


# ---------------------------------------------------------------------------
# Stage 3: Noise Handshake Forgery
# ---------------------------------------------------------------------------

class TestNoiseHandshakeForgery:
    def test_forged_handshake_field_present(self, attack_results):
        assert "forged_handshake" in attack_results, (
            "results.json must contain 'forged_handshake'"
        )

    def test_forged_handshake_decrypts_to_target(
        self, attack_results, public_data
    ):
        """
        Set up a Noise K-pattern responder with the derived server key and
        verify the forged handshake decrypts to the target payload.
        """
        dh_sk = int(attack_results["dh_private_key"])
        _, noise_private = derive_keys(dh_sk)

        dh = X25519DH()
        noise_keypair = dh.generate_keypair(noise_private)
        client_pk = dh.create_public(
            base64.b64decode(public_data["client_noise_public_key"])
        )

        # Construct the responder exactly as the server would
        responder = KHandShakeState(
            SymmetricState(
                CipherState(ChaChaPolyCipher()), SHA512Hash()
            ),
            X25519DH(),
        )
        responder.initialize(False, s=noise_keypair, rs=client_pk)

        forged = base64.b64decode(attack_results["forged_handshake"])
        payload = bytearray()
        try:
            responder.read_message(forged, payload)
        except Exception as exc:
            pytest.fail(
                f"Forged handshake decryption/authentication failed: {exc}"
            )

        target = base64.b64decode(public_data["target_payload"])
        assert bytes(payload) == target, (
            f"Payload mismatch.\n"
            f"  Expected: {target!r}\n"
            f"  Got:      {bytes(payload)!r}"
        )
