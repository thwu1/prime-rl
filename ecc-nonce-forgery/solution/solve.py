#!/usr/bin/env python3

"""
Solution: ECDSA nonce reuse key recovery + ECRDSA signature forgery on FRP256V1.

Steps:
1. Load challenge data (curve params, public key, ECDSA signatures, challenge msg)
2. Detect nonce reuse by finding two signatures with the same r value
3. Recover the nonce k and private key d using the nonce reuse attack
4. Forge an ECRDSA signature (RFC/GOST variant) on the challenge message
"""

import hashlib
import json
import os


# ---------------------------------------------------------------------------
# Modular arithmetic
# ---------------------------------------------------------------------------

def extended_gcd(a, b):
    old_r, r = a, b
    old_s, s = 1, 0
    while r != 0:
        quotient = old_r // r
        old_r, r = r, old_r - quotient * r
        old_s, s = s, old_s - quotient * s
    return old_r, old_s


def modinv(val, mod):
    val = val % mod
    g, x = extended_gcd(val, mod)
    if g != 1:
        raise ValueError("No modular inverse")
    return x % mod


# ---------------------------------------------------------------------------
# EC point arithmetic
# ---------------------------------------------------------------------------

class ECPoint:
    """Lightweight wrapper for affine EC point operations."""

    def __init__(self, p, a):
        self.p = p
        self.a = a

    def add(self, P, Q):
        INF = (None, None)
        if P == INF:
            return Q
        if Q == INF:
            return P
        x1, y1 = P
        x2, y2 = Q
        if x1 == x2:
            if (y1 + y2) % self.p == 0:
                return INF
            lam = (3 * x1 * x1 + self.a) * modinv(2 * y1, self.p) % self.p
        else:
            lam = (y2 - y1) * modinv((x2 - x1) % self.p, self.p) % self.p
        x3 = (lam * lam - x1 - x2) % self.p
        y3 = (lam * (x1 - x3) - y1) % self.p
        return (x3, y3)

    def mul(self, k, P):
        INF = (None, None)
        R = INF
        Q = P
        while k > 0:
            if k & 1:
                R = self.add(R, Q)
            Q = self.add(Q, Q)
            k >>= 1
        return R


# ---------------------------------------------------------------------------
# Main solution
# ---------------------------------------------------------------------------

def main():
    # Load challenge data
    with open("/app/challenge/data.json") as f:
        data = json.load(f)

    curve = data["curve"]
    p = int(curve["p"], 16)
    a = int(curve["a"], 16)
    q = int(curve["q"], 16)
    Gx = int(curve["Gx"], 16)
    Gy = int(curve["Gy"], 16)
    G = (Gx, Gy)

    pub_Qx = int(data["public_key"]["Qx"], 16)
    pub_Qy = int(data["public_key"]["Qy"], 16)
    Q_pub = (pub_Qx, pub_Qy)

    ec = ECPoint(p, a)

    sigs = data["ecdsa_signatures"]
    challenge_msg = data["challenge"]["message"]

    # -----------------------------------------------------------------------
    # Step 1: Detect nonce reuse (find two signatures with matching r values)
    # -----------------------------------------------------------------------
    r_to_index = {}
    reuse_i, reuse_j = None, None
    for i, sig in enumerate(sigs):
        r_hex = sig["r"]
        if r_hex in r_to_index:
            reuse_i = r_to_index[r_hex]
            reuse_j = i
            break
        r_to_index[r_hex] = i

    if reuse_i is None:
        raise RuntimeError("No nonce reuse detected")

    print(f"Nonce reuse detected: signatures {reuse_i} and {reuse_j}")

    # -----------------------------------------------------------------------
    # Step 2: Recover nonce k and private key d
    # -----------------------------------------------------------------------
    r = int(sigs[reuse_i]["r"], 16)
    s1 = int(sigs[reuse_i]["s"], 16)
    s2 = int(sigs[reuse_j]["s"], 16)
    m1 = sigs[reuse_i]["message"]
    m2 = sigs[reuse_j]["message"]

    # ECDSA: s = k^{-1} * (d*r + e) mod q
    # With same k:
    #   s1 - s2 = k^{-1} * (e1 - e2) mod q
    #   k = (e1 - e2) * (s1 - s2)^{-1} mod q
    e1 = int.from_bytes(hashlib.sha256(m1.encode()).digest(), "big") % q
    e2 = int.from_bytes(hashlib.sha256(m2.encode()).digest(), "big") % q

    k = ((e1 - e2) * modinv((s1 - s2) % q, q)) % q

    # d = (s1*k - e1) * r^{-1} mod q
    d = ((s1 * k - e1) * modinv(r, q)) % q

    print(f"Recovered k: {hex(k)[:24]}...")
    print(f"Recovered d: {hex(d)[:24]}...")

    # -----------------------------------------------------------------------
    # Step 3: Verify recovery by checking d*G == Q_pub
    # -----------------------------------------------------------------------
    Q_check = ec.mul(d, G)
    assert Q_check == Q_pub, "Key recovery verification failed: d*G != Q_pub"
    print("Key recovery verified: d*G matches public key")

    # -----------------------------------------------------------------------
    # Step 4: Forge ECRDSA signature (RFC/GOST R 34.10-2012)
    #
    # ECRDSA sign (RFC standard):
    #   1. h = SHA-256(message)
    #   2. Reverse hash bytes (RFC vs ISO endianness)
    #   3. e = int(reversed_h) mod q; if e == 0: e = 1
    #   4. Pick random k, compute W = kG, r = W.x mod q
    #   5. s = (r*d + k*e) mod q   (NOTE: no k^{-1}, unlike ECDSA)
    # -----------------------------------------------------------------------
    h = hashlib.sha256(challenge_msg.encode()).digest()
    h_reversed = h[::-1]  # RFC: reverse byte order
    e = int.from_bytes(h_reversed, "big") % q
    if e == 0:
        e = 1

    # Deterministic nonce for the forgery (derived from key + message)
    nonce_material = hashlib.sha256(
        d.to_bytes(32, "big") + challenge_msg.encode()
    ).digest()
    k_forge = int.from_bytes(nonce_material, "big") % (q - 1) + 1

    W = ec.mul(k_forge, G)
    r_forge = W[0] % q
    assert r_forge != 0, "Bad r in forgery"

    s_forge = (r_forge * d + k_forge * e) % q
    assert s_forge != 0, "Bad s in forgery"

    print(f"Forged ECRDSA r: {format(r_forge, '064x')[:24]}...")
    print(f"Forged ECRDSA s: {format(s_forge, '064x')[:24]}...")

    # -----------------------------------------------------------------------
    # Step 5: Write outputs
    # -----------------------------------------------------------------------
    with open("/app/recovered_key.txt", "w") as f:
        f.write(format(d, '064x'))

    with open("/app/forged_signature.json", "w") as f:
        json.dump({
            "r": format(r_forge, '064x'),
            "s": format(s_forge, '064x'),
        }, f, indent=2)

    print("\nSolution complete.")
    print(f"  Private key written to /app/recovered_key.txt")
    print(f"  Forged ECRDSA signature written to /app/forged_signature.json")


if __name__ == "__main__":
    main()
