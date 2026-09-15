"""
VaultSync — cloud storage service with ECDSA-authenticated updates
and Noise protocol K-pattern handshake-based secure storage.
"""

import os
import hashlib
from datetime import datetime
import json
from tinyec.registry import get_curve
from Crypto.Cipher import AES
from dissononce.processing.impl.symmetricstate import SymmetricState
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.x25519 import X25519DH, PrivateKey
from dissononce.hash.sha512 import SHA512Hash


class ECDSA:
    """ECDSA signing and verification using secp256r1."""

    def __init__(self, sk):
        self.sk = sk
        self.rgen = AES.new(os.urandom(16), AES.MODE_ECB)

    @staticmethod
    def hash_msg_to_int(message, N):
        return int.from_bytes(hashlib.sha256(message).digest(), "big") % N

    def sign(self, message):
        curve = get_curve("secp256r1")
        N = curve.field.n
        e = ECDSA.hash_msg_to_int(message, N)

        while True:
            rbyte = os.urandom(1)
            k = int.from_bytes(
                self.rgen.encrypt(rbyte + 15 * b"0" + rbyte + 15 * b"1"), "big"
            ) % N
            if k == 0:
                continue

            R = k * curve.g
            r = R.x % N
            if r == 0:
                continue

            k_inv = pow(k, -1, N)
            s = (r * self.sk) % N
            s = (s + e) % N
            s = (s * k_inv) % N

            return (r, s)

    @staticmethod
    def verify(pk, message, signature):
        curve = get_curve("secp256r1")
        N = curve.field.n
        (r, s) = signature

        if not (1 <= r < N and 1 <= s < N):
            return False

        e = ECDSA.hash_msg_to_int(message, N)
        s_inv = pow(s, -1, N)
        u1 = (e * s_inv) % N
        u2 = (r * s_inv) % N

        R = (u1 * curve.g) + (u2 * pk)

        if R.x % N == r:
            return True
        return False


class KHandShakeState:
    """Simplified Noise protocol K-pattern handshake state.

    Implements one-way (initiator -> responder) authenticated key exchange.
    The K-pattern pre-shares both parties' static public keys.
    See https://noiseprotocol.org/noise.html for the full specification.
    """

    def __init__(self, symmetricstate, dh):
        self.symmetricstate = symmetricstate
        self.dh = dh
        self.s = None
        self.e = None
        self.rs = None
        self.re = None
        self.initiator = None
        self.protocol_name = "Noise_K_25519_ChaChaPoly_SHA256"

    def initialize(self, initiator, s=None, e=None, rs=None, re=None):
        self.symmetricstate.initialize_symmetric(self.protocol_name.encode())
        prologue = b""
        self.symmetricstate.mix_hash(prologue)

        self.initiator = initiator
        self.s = s
        self.e = e
        self.rs = rs
        self.re = re

        # Pre-messages: both static public keys
        if initiator:
            self.symmetricstate.mix_hash(s.public.data)
            assert rs is not None
            self.symmetricstate.mix_hash(rs.data)
        else:
            assert rs is not None
            self.symmetricstate.mix_hash(rs.data)
            self.symmetricstate.mix_hash(s.public.data)

    def write_message(self, payload, message_buffer):
        assert self.initiator

        # e: generate ephemeral key
        self.e = self.dh.generate_keypair()
        message_buffer.extend(self.e.public.data)
        self.symmetricstate.mix_hash(self.e.public.data)

        # es: DH(e, rs)
        self.symmetricstate.mix_key(self.dh.dh(self.e, self.rs))

        # ss: DH(s, rs)
        self.symmetricstate.mix_key(self.dh.dh(self.s, self.rs))

        # Encrypt payload
        message_buffer.extend(self.symmetricstate.encrypt_and_hash(payload))

    def read_message(self, message, payload_buffer):
        assert not self.initiator

        # e
        self.re = self.dh.create_public(message[: self.dh.dhlen])
        self.symmetricstate.mix_hash(self.re.data)
        message = message[self.dh.dhlen :]

        # es
        self.symmetricstate.mix_key(self.dh.dh(self.s, self.re))

        # ss
        self.symmetricstate.mix_key(self.dh.dh(self.s, self.rs))

        # Decrypt payload
        payload_buffer.extend(self.symmetricstate.decrypt_and_hash(message))


class Server:
    """VaultSync cloud storage server.

    Provides two services:
    - check_update(): returns ECDSA-signed software update status
    - update_storage(msg): accepts Noise K-pattern handshake to update user vault
    """

    def __init__(self):
        curve = get_curve("secp256r1")

        # Generate signing key and static handshake key from shared material
        sk = os.urandom(16)
        self.ecdsa_sk = int.from_bytes(sk, "big") % curve.field.n
        self.ecdsa_pk = self.ecdsa_sk * curve.g
        self.static_sk = PrivateKey(sk + b"0" * 16)

        self.ecdsa = ECDSA(self.ecdsa_sk)
        self.static_keypair = X25519DH().generate_keypair(self.static_sk)

        self.db = None
        self.user_static_pk = None

    def get_ecdsa_pk(self):
        return self.ecdsa_pk

    def get_static_pk(self):
        return self.static_keypair.public

    def get_user_storage(self):
        return self.db

    def register_user(self, user_pk):
        self.user_static_pk = user_pk

    def check_update(self):
        """Returns an ECDSA-signed software update status message."""
        message = json.dumps(
            {"time": datetime.now().isoformat(), "status": "No update"}
        ).encode()
        return message, self.ecdsa.sign(message)

    def update_storage(self, msg):
        """Accepts a Noise K-pattern handshake message to update vault storage."""
        responder = KHandShakeState(
            SymmetricState(CipherState(ChaChaPolyCipher()), SHA512Hash()), X25519DH()
        )
        responder.initialize(False, s=self.static_keypair, rs=self.user_static_pk)

        payload = bytearray()
        try:
            responder.read_message(msg, payload)
            self.db = bytes(payload)
        except Exception:
            print("Malformed upload request")


def client(keypair, server_static_pk):
    """Creates a valid storage update handshake message."""
    initiator = KHandShakeState(
        SymmetricState(CipherState(ChaChaPolyCipher()), SHA512Hash()), X25519DH()
    )
    initiator.initialize(True, s=keypair, rs=server_static_pk)

    data = b"super secret file"
    msg = bytearray()
    initiator.write_message(data, msg)
    return bytes(msg)


class AttackParams:
    """Interface available to the security auditor."""

    def __init__(self, client_keypair, server):
        self.client_static_pk = client_keypair.public
        self.server_static_pk = server.get_static_pk()
        self.check_update = server.check_update
        self.update_storage = server.update_storage
