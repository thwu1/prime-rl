"""
VaultSync - Secure Cloud Storage Service

This module implements the VaultSync server, providing:
1. Authenticated cloud storage updates via Noise protocol K-pattern handshake
2. Signed software update notifications via ECDSA on secp256r1

Key Infrastructure:
- A Diffie-Hellman key agreement in Z*_p establishes the server's master secret.
- The ECDSA signing key and the Noise static key are both derived from this
  DH master secret through a SHA-512 based key derivation function.
- Registered users authenticate and establish secure channels using the
  Noise K-pattern handshake over X25519.

"""

import os
import hashlib
import json
from datetime import datetime

from tinyec.registry import get_curve
from dissononce.processing.impl.symmetricstate import SymmetricState
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.x25519 import X25519DH, PrivateKey
from dissononce.hash.sha512 import SHA512Hash


###############################################################################
# Diffie-Hellman Group Parameters
###############################################################################
# Legacy DH group used for master key agreement with older infrastructure.
# Prime: p = 927561315432648769274106771080177774153  (~130 bits)
# Group order: p - 1 = 2^3 * 67^3 * 131^5 * 257^3 * 521 * 1031^4
# Generator: g is a generator of Z*_p
DH_MOD = 927561315432648769274106771080177774153
DH_GEN = 216606503944793770949515456773896502127


###############################################################################
# ECDSA Signing (secp256r1)
###############################################################################
class ECDSA:
    """ECDSA signature scheme over the NIST P-256 (secp256r1) curve."""

    def __init__(self, sk):
        self.sk = sk

    @staticmethod
    def hash_msg_to_int(message, N):
        """Hash a message to an integer in [0, N-1]."""
        return int.from_bytes(hashlib.sha256(message).digest(), "big") % N

    def sign(self, message):
        """Produce an ECDSA signature (r, s) on the given message."""
        curve = get_curve("secp256r1")
        N = curve.field.n
        e = ECDSA.hash_msg_to_int(message, N)

        while True:
            k = int.from_bytes(os.urandom(32), "big") % N
            if k == 0:
                continue
            R = k * curve.g
            r = R.x % N
            if r == 0:
                continue
            k_inv = pow(k, -1, N)
            s = (k_inv * (e + r * self.sk)) % N
            if s == 0:
                continue
            return (r, s)

    @staticmethod
    def verify(pk, message, signature):
        """Verify an ECDSA signature against a public key."""
        curve = get_curve("secp256r1")
        N = curve.field.n
        r, s = signature
        if not (1 <= r < N and 1 <= s < N):
            return False
        e = ECDSA.hash_msg_to_int(message, N)
        s_inv = pow(s, -1, N)
        u1 = (e * s_inv) % N
        u2 = (r * s_inv) % N
        R = (u1 * curve.g) + (u2 * pk)
        return R.x % N == r


###############################################################################
# Noise Protocol K-Pattern Handshake
###############################################################################
class KHandShakeState:
    """
    Simplified Noise K-pattern handshake.

    The K-pattern assumes both parties already know each other's static public
    keys (pre-message). The handshake pattern is a single message from the
    initiator to the responder:

        Pre-messages:
            -> s   (initiator's static public key is known to responder)
            <- s   (responder's static public key is known to initiator)

        Handshake message:
            -> e, es, ss

    Tokens:
        e  : initiator generates an ephemeral key, sends public part
        es : DH(initiator_ephemeral, responder_static)
        ss : DH(initiator_static, responder_static)

    The handshake authenticates the initiator (who must possess the registered
    static key) and establishes a secure channel.

    See https://noiseprotocol.org/noise.html for the full specification.
    """

    PROTOCOL_NAME = "Noise_K_25519_ChaChaPoly_SHA512"

    def __init__(self, symmetricstate, dh):
        self.symmetricstate = symmetricstate
        self.dh = dh
        self.s = None    # local static keypair
        self.e = None    # local ephemeral keypair
        self.rs = None   # remote static public key
        self.re = None   # remote ephemeral public key
        self.initiator = None

    def initialize(self, initiator, s=None, e=None, rs=None, re=None):
        """Initialize the handshake state. Must be called before read/write."""
        self.symmetricstate.initialize_symmetric(self.PROTOCOL_NAME.encode())
        # Empty prologue
        self.symmetricstate.mix_hash(b"")

        self.initiator = initiator
        self.s = s
        self.e = e
        self.rs = rs
        self.re = re

        # Process pre-messages: both sides mix in the initiator's static
        # public key first, then the responder's static public key.
        if initiator:
            self.symmetricstate.mix_hash(s.public.data)
            assert rs is not None, "K-pattern requires responder static key"
            self.symmetricstate.mix_hash(rs.data)
        else:
            assert rs is not None, "K-pattern requires initiator static key"
            self.symmetricstate.mix_hash(rs.data)
            self.symmetricstate.mix_hash(s.public.data)

    def write_message(self, payload, message_buffer):
        """Write the initiator's handshake message (-> e, es, ss)."""
        assert self.initiator, "Only the initiator writes in K-pattern"

        # Token: e — generate ephemeral key, include public part in message
        self.e = self.dh.generate_keypair()
        message_buffer.extend(self.e.public.data)
        self.symmetricstate.mix_hash(self.e.public.data)

        # Token: es — DH(ephemeral, remote_static)
        self.symmetricstate.mix_key(self.dh.dh(self.e, self.rs))

        # Token: ss — DH(static, remote_static)
        self.symmetricstate.mix_key(self.dh.dh(self.s, self.rs))

        # Encrypt and authenticate the payload
        message_buffer.extend(self.symmetricstate.encrypt_and_hash(payload))

    def read_message(self, message, payload_buffer):
        """Read and process the initiator's handshake message (responder)."""
        assert not self.initiator, "Only the responder reads in K-pattern"

        # Token: e — read remote ephemeral public key
        self.re = self.dh.create_public(message[: self.dh.dhlen])
        self.symmetricstate.mix_hash(self.re.data)
        message = message[self.dh.dhlen :]

        # Token: es — DH(static, remote_ephemeral)
        self.symmetricstate.mix_key(self.dh.dh(self.s, self.re))

        # Token: ss — DH(static, remote_static)
        self.symmetricstate.mix_key(self.dh.dh(self.s, self.rs))

        # Decrypt and verify the payload
        payload_buffer.extend(self.symmetricstate.decrypt_and_hash(message))


###############################################################################
# Key Derivation Function
###############################################################################
def derive_keys(dh_secret):
    """
    Derive the ECDSA signing key and Noise static key from the DH master
    secret using a SHA-512 based KDF.

    The 64-byte SHA-512 output is split:
      - bytes [0:32]  -> ECDSA secret key (interpreted as integer mod curve order)
      - bytes [32:64] -> Noise X25519 static private key
    """
    key_material = hashlib.sha512(
        b"VaultSync-KDF-v1:" + dh_secret.to_bytes(20, "big")
    ).digest()

    # ECDSA key from first 32 bytes
    curve = get_curve("secp256r1")
    N = curve.field.n
    ecdsa_sk = int.from_bytes(key_material[:32], "big") % N
    if ecdsa_sk == 0:
        ecdsa_sk = 1

    # Noise static key from last 32 bytes
    noise_sk = PrivateKey(key_material[32:])

    return ecdsa_sk, noise_sk


###############################################################################
# VaultSync Server
###############################################################################
class VaultSyncServer:
    """
    VaultSync cloud storage server.

    Supports a single registered user. Services:
      - check_update(): returns a signed software update status message
      - update_storage(msg): accepts a Noise K-pattern handshake from the
        registered user to update their cloud storage
    """

    def __init__(self, dh_private_key):
        """Initialize server with the given DH master secret."""
        self.dh_sk = dh_private_key
        self.dh_pk = pow(DH_GEN, self.dh_sk, DH_MOD)

        # Derive subordinate keys from DH master secret
        self.ecdsa_sk, noise_private = derive_keys(self.dh_sk)

        curve = get_curve("secp256r1")
        self.ecdsa_pk = self.ecdsa_sk * curve.g
        self.ecdsa_signer = ECDSA(self.ecdsa_sk)

        self.noise_keypair = X25519DH().generate_keypair(noise_private)

        # User data
        self.db = None
        self.user_noise_pk = None

    def get_dh_public_key(self):
        return self.dh_pk

    def get_ecdsa_public_key(self):
        return self.ecdsa_pk

    def get_noise_public_key(self):
        return self.noise_keypair.public

    def register_user(self, user_noise_pk):
        """Register a user by storing their Noise static public key."""
        self.user_noise_pk = user_noise_pk

    def check_update(self):
        """Return a signed software update status message."""
        message = json.dumps({
            "timestamp": datetime.now().isoformat(),
            "status": "No updates available",
            "version": "2.4.1"
        }).encode()
        return message, self.ecdsa_signer.sign(message)

    def update_storage(self, msg):
        """
        Accept a Noise K-pattern handshake message and update user storage.
        Returns True if the handshake was valid and storage was updated.
        """
        responder = KHandShakeState(
            SymmetricState(CipherState(ChaChaPolyCipher()), SHA512Hash()),
            X25519DH()
        )
        responder.initialize(
            False, s=self.noise_keypair, rs=self.user_noise_pk
        )
        payload = bytearray()
        try:
            responder.read_message(msg, payload)
            self.db = bytes(payload)
            return True
        except Exception:
            return False

    def get_storage(self):
        return self.db


def make_client_message(client_keypair, server_noise_pk, data):
    """Create a Noise K-pattern handshake message as the registered client."""
    initiator = KHandShakeState(
        SymmetricState(CipherState(ChaChaPolyCipher()), SHA512Hash()),
        X25519DH()
    )
    initiator.initialize(True, s=client_keypair, rs=server_noise_pk)
    msg = bytearray()
    initiator.write_message(data, msg)
    return bytes(msg)
