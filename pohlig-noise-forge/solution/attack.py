#!/usr/bin/env python3
"""
Reference attack for VaultSync challenge.

Attack chain:
  1. Pohlig-Hellman on the smooth-order DH group to recover the master secret
  2. SHA-512 KDF to derive the Noise X25519 static private key
  3. Forge a Noise K-pattern handshake using DH commutativity

"""

import json
import base64
import sys
from math import isqrt
from functools import reduce

sys.path.insert(0, "/app")
from vaultsync import DH_MOD, DH_GEN, derive_keys, ECDSA

from dissononce.processing.impl.symmetricstate import SymmetricState
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.cipher.chachapoly import ChaChaPolyCipher
from dissononce.dh.x25519.x25519 import X25519DH
from dissononce.hash.sha512 import SHA512Hash
from tinyec.registry import get_curve


# ===================================================================
# Stage 1 — Pohlig-Hellman discrete-log attack
# ===================================================================

def baby_step_giant_step(mod, gen, order, target):
    """
    Baby-step-giant-step algorithm for discrete log in Z*_mod.
    Finds x in [0, order) such that gen^x ≡ target (mod mod).
    """
    m = isqrt(order) + 1

    # Baby steps: table[gen^j mod mod] = j
    table = {}
    power = 1
    for j in range(m):
        table[power] = j
        power = (power * gen) % mod

    # Giant steps: check target * gen^{-im} for i = 0..m-1
    gen_inv_m = pow(gen, -m, mod)
    gamma = target
    for i in range(m):
        if gamma in table:
            x = (i * m + table[gamma]) % order
            return x
        gamma = (gamma * gen_inv_m) % mod

    raise RuntimeError("BSGS failed — no discrete log found")


def pohlig_hellman_prime_power(mod, full_gen, full_order, p, e, target):
    """
    Compute discrete log modulo p^e using the Pohlig-Hellman lifting
    technique for prime powers.
    """
    result = 0
    gamma = target
    # h is the fixed generator of the order-p subgroup
    h = pow(full_gen, full_order // p, mod)

    for k in range(e):
        # Project gamma into the order-p subgroup
        exp = full_order // (p ** (k + 1))
        t = pow(gamma, exp, mod)

        # Solve DL in subgroup of order p
        d_k = baby_step_giant_step(mod, h, p, t)

        result += d_k * (p ** k)

        # Remove the contribution of d_k
        gamma = (gamma * pow(full_gen, -(d_k * (p ** k)), mod)) % mod

    return result


def crt(residues, moduli):
    """Chinese Remainder Theorem: solve x ≡ r_i (mod m_i) for coprime m_i."""
    M = reduce(lambda a, b: a * b, moduli, 1)
    x = 0
    for r, m in zip(residues, moduli):
        Mi = M // m
        yi = pow(Mi, -1, m)
        x = (x + r * Mi * yi) % M
    return x


def pohlig_hellman(mod, gen, factors, target):
    """
    Full Pohlig-Hellman algorithm.
    Recovers x such that gen^x ≡ target (mod mod), given that
    the group order factors as ∏ p_i^{e_i} with small p_i.
    """
    order = reduce(lambda a, pf: a * pf[0] ** pf[1], factors, 1)

    residues = []
    moduli = []

    for p, e in factors:
        sub_order = p ** e
        exp = order // sub_order
        sub_gen = pow(gen, exp, mod)
        sub_target = pow(target, exp, mod)

        x_i = pohlig_hellman_prime_power(
            mod, sub_gen, sub_order, p, e, sub_target
        )
        residues.append(x_i)
        moduli.append(sub_order)

    return crt(residues, moduli)


# ===================================================================
# Stage 3 — Noise K-pattern handshake forgery
# ===================================================================

def forge_handshake(server_noise_sk, server_noise_pk, client_noise_pk,
                    target_data):
    """
    Forge a Noise K-pattern handshake message that the server will accept
    as coming from the registered client.

    Key insight: the K-pattern's 'ss' token requires
        DH(initiator_static, responder_static)
    which the legitimate client would compute as DH(client_sk, server_pk).
    We don't have client_sk, but by DH commutativity:
        DH(client_sk, server_pk) == DH(server_sk, client_pk)
    and we DO have server_sk (recovered via Pohlig-Hellman + KDF).
    """
    dh = X25519DH()

    # Manually build the symmetric state (same as both sides would)
    ss = SymmetricState(CipherState(ChaChaPolyCipher()), SHA512Hash())
    ss.initialize_symmetric(b"Noise_K_25519_ChaChaPoly_SHA512")
    ss.mix_hash(b"")  # empty prologue

    # Pre-messages: initiator (client) static pk, then responder (server)
    # static pk — same order on both sides
    ss.mix_hash(client_noise_pk.data)
    ss.mix_hash(server_noise_pk.data)

    # Token: e — generate a fresh ephemeral keypair
    e_keypair = dh.generate_keypair()
    msg = bytearray()
    msg.extend(e_keypair.public.data)
    ss.mix_hash(e_keypair.public.data)

    # Token: es — DH(ephemeral, server_static)
    # The server will compute DH(server_static, ephemeral) — same value
    ss.mix_key(dh.dh(e_keypair, server_noise_pk))

    # Token: ss — DH(client_static, server_static)
    # We use DH(server_static, client_pk) instead (commutativity)
    server_keypair = dh.generate_keypair(server_noise_sk)
    ss.mix_key(dh.dh(server_keypair, client_noise_pk))

    # Encrypt the target payload
    msg.extend(ss.encrypt_and_hash(target_data))

    return bytes(msg)


# ===================================================================
# Main attack
# ===================================================================

def main():
    # Load public data
    with open("/app/public_data.json") as f:
        data = json.load(f)

    p = int(data["dh_params"]["mod"])
    g = int(data["dh_params"]["gen"])
    Y = int(data["dh_public_key"])
    factors = [tuple(f) for f in data["dh_params"]["order_factorization"]]

    # ------------------------------------------------------------------
    # Stage 1: Recover DH master secret via Pohlig-Hellman
    # ------------------------------------------------------------------
    print("Stage 1: Pohlig-Hellman DH key recovery...")
    dh_sk = pohlig_hellman(p, g, factors, Y)
    assert pow(g, dh_sk, p) == Y, "DH key recovery verification failed"
    print(f"  Recovered DH private key: {dh_sk}")

    # ------------------------------------------------------------------
    # Stage 2: Derive subordinate keys via KDF
    # ------------------------------------------------------------------
    print("Stage 2: Deriving ECDSA and Noise keys...")
    ecdsa_sk, noise_private = derive_keys(dh_sk)

    # Verify ECDSA key against stored signatures
    curve = get_curve("secp256r1")
    ecdsa_pk = ecdsa_sk * curve.g
    for update in data["signed_updates"][:3]:
        msg_bytes = base64.b64decode(update["message"])
        sig = (int(update["signature_r"]), int(update["signature_s"]))
        assert ECDSA.verify(ecdsa_pk, msg_bytes, sig), (
            "ECDSA signature verification failed — key derivation error"
        )
    print("  ECDSA key verified against stored signatures")

    # ------------------------------------------------------------------
    # Stage 3: Forge Noise K-pattern handshake
    # ------------------------------------------------------------------
    print("Stage 3: Forging Noise K-pattern handshake...")
    dh_x = X25519DH()
    server_noise_pk = dh_x.create_public(
        base64.b64decode(data["noise_static_public_key"])
    )
    client_noise_pk = dh_x.create_public(
        base64.b64decode(data["client_noise_public_key"])
    )
    target = base64.b64decode(data["target_payload"])

    forged = forge_handshake(
        noise_private, server_noise_pk, client_noise_pk, target
    )
    print(f"  Forged handshake: {len(forged)} bytes")

    # ------------------------------------------------------------------
    # Write results
    # ------------------------------------------------------------------
    results = {
        "dh_private_key": str(dh_sk),
        "forged_handshake": base64.b64encode(forged).decode(),
    }
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Attack complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
