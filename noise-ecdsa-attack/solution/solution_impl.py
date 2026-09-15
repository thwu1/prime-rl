
"""
VaultSync exploit: ECDSA nonce reuse key recovery + Noise K-pattern handshake forgery.
"""

import hashlib
import sys
sys.path.insert(0, '/app')

from tinyec.registry import get_curve
from dissononce.processing.impl.symmetricstate import SymmetricState
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.x25519 import X25519DH, PrivateKey
from dissononce.hash.sha512 import SHA512Hash


def recover_signing_key(params):
    """
    Exploit ECDSA nonce reuse to recover the server's signing key.

    The server's nonce generator feeds only 1 byte of randomness into AES-ECB,
    producing at most 256 distinct nonces. The birthday paradox guarantees a
    collision within ~20 signatures (>50% probability). Two signatures sharing
    the same nonce k have the same r value, enabling algebraic key recovery:

        k = (e1 - e2) / (s1 - s2)  mod N
        sk = (s * k - e) / r        mod N
    """
    curve = get_curve("secp256r1")
    N = curve.field.n

    sigs = []
    msgs = []
    r_to_idx = {}

    for _ in range(200):
        msg, sig = params.check_update()
        r, s = sig

        if r in r_to_idx:
            j = r_to_idx[r]
            r_j, s_j = sigs[j]

            # Skip identical signatures (same message + same nonce)
            if s == s_j:
                continue

            e_i = int.from_bytes(hashlib.sha256(msg).digest(), "big") % N
            e_j = int.from_bytes(hashlib.sha256(msgs[j]).digest(), "big") % N

            # Recover nonce from the two equations:
            #   s_i = k^{-1} * (e_i + r * sk)
            #   s_j = k^{-1} * (e_j + r * sk)
            # Subtract: (s_i - s_j) * k = (e_i - e_j)
            k = ((e_i - e_j) * pow(s - s_j, -1, N)) % N

            # Recover secret key: sk = (s * k - e) * r^{-1}
            sk = ((s * k - e_i) * pow(r, -1, N)) % N

            return sk

        r_to_idx[r] = len(sigs)
        sigs.append(sig)
        msgs.append(msg)

    raise RuntimeError("No nonce collision found in 200 signatures")


def forge_vault_update(params, target_data):
    """
    Forge a Noise K-pattern handshake to overwrite a registered user's vault.

    Attack chain:
    1. Recover ECDSA secret key via nonce reuse
    2. Derive server's Noise static key — the server generates both keys from
       the same 16-byte master secret:
         ecdsa_sk = int.from_bytes(master, "big")  (no reduction since 128 < 256 bits)
         static_sk = PrivateKey(master + b"0" * 16)
    3. Construct a valid K-pattern handshake. The ss token requires
       DH(s_client, pk_server), but we lack s_client. By DH commutativity,
       DH(s_client, pk_server) == DH(s_server, pk_client), which we can compute
       with the recovered server key.
    """
    ecdsa_sk = recover_signing_key(params)

    # Derive Noise static key from ECDSA key material
    master = ecdsa_sk.to_bytes(16, "big")
    server_static_sk = PrivateKey(master + b"0" * 16)
    server_static_keypair = X25519DH().generate_keypair(server_static_sk)

    # Build Noise K-pattern handshake state manually
    dh = X25519DH()
    sym = SymmetricState(CipherState(ChaChaPolyCipher()), SHA512Hash())

    # Initialize — note: protocol name says SHA256 but implementation uses SHA512
    sym.initialize_symmetric(b"Noise_K_25519_ChaChaPoly_SHA256")
    sym.mix_hash(b"")  # empty prologue

    # K-pattern pre-messages: initiator (client) static pk, responder (server) static pk
    sym.mix_hash(params.client_static_pk.data)
    sym.mix_hash(params.server_static_pk.data)

    # Token: e — generate ephemeral keypair
    e = dh.generate_keypair()
    msg = bytearray()
    msg.extend(e.public.data)
    sym.mix_hash(e.public.data)

    # Token: es — DH(e_initiator, pk_server)
    sym.mix_key(dh.dh(e, params.server_static_pk))

    # Token: ss — DH(s_server, pk_client) == DH(s_client, pk_server)
    sym.mix_key(dh.dh(server_static_keypair, params.client_static_pk))

    # Encrypt payload
    msg.extend(sym.encrypt_and_hash(target_data))

    # Send forged handshake
    params.update_storage(bytes(msg))
