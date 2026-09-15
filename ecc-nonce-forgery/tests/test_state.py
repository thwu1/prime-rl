
"""
Verification tests for the ECDSA nonce reuse key recovery + ECRDSA forgery task.
Checks: recovered private key validity, public key match, ECDSA signature
verification, and ECRDSA forged signature validity (RFC/GOST standard).
"""

import hashlib
import json
import os

import pytest


# ---------------------------------------------------------------------------
# Elliptic curve arithmetic helpers (FRP256V1)
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
    assert g == 1, "modular inverse does not exist"
    return x % mod


class FRP256V1:
    """Minimal EC arithmetic on FRP256V1."""

    def __init__(self, params):
        self.p = int(params["p"], 16)
        self.a = int(params["a"], 16)
        self.b = int(params["b"], 16)
        self.Gx = int(params["Gx"], 16)
        self.Gy = int(params["Gy"], 16)
        self.q = int(params["q"], 16)
        self.G = (self.Gx, self.Gy)
        self.INF = (None, None)

    def on_curve(self, P):
        if P == self.INF:
            return True
        x, y = P
        return (y * y - x * x * x - self.a * x - self.b) % self.p == 0

    def add(self, P, Q):
        if P == self.INF:
            return Q
        if Q == self.INF:
            return P
        x1, y1 = P
        x2, y2 = Q
        if x1 == x2:
            if (y1 + y2) % self.p == 0:
                return self.INF
            lam = (3 * x1 * x1 + self.a) * modinv(2 * y1, self.p) % self.p
        else:
            lam = (y2 - y1) * modinv((x2 - x1) % self.p, self.p) % self.p
        x3 = (lam * lam - x1 - x2) % self.p
        y3 = (lam * (x1 - x3) - y1) % self.p
        return (x3, y3)

    def mul(self, k, P):
        R = self.INF
        Q = P
        while k > 0:
            if k & 1:
                R = self.add(R, Q)
            Q = self.add(Q, Q)
            k >>= 1
        return R


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def challenge_data():
    with open("/app/challenge/data.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ec(challenge_data):
    return FRP256V1(challenge_data["curve"])


@pytest.fixture(scope="module")
def public_key(challenge_data):
    qx = int(challenge_data["public_key"]["Qx"], 16)
    qy = int(challenge_data["public_key"]["Qy"], 16)
    return (qx, qy)


@pytest.fixture(scope="module")
def recovered_key():
    with open("/app/recovered_key.txt") as f:
        return int(f.read().strip(), 16)


@pytest.fixture(scope="module")
def forged_sig():
    with open("/app/forged_signature.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFileExistence:
    def test_recovered_key_file_exists(self):
        assert os.path.exists("/app/recovered_key.txt"), \
            "recovered_key.txt not found"

    def test_forged_signature_file_exists(self):
        assert os.path.exists("/app/forged_signature.json"), \
            "forged_signature.json not found"


class TestRecoveredKey:
    def test_key_is_valid_hex(self, recovered_key, ec):
        assert isinstance(recovered_key, int)
        assert 0 < recovered_key < ec.q, "Private key out of range [1, q-1]"

    def test_key_matches_public_key(self, ec, recovered_key, public_key):
        """d * G must equal the given public key Q."""
        Q_computed = ec.mul(recovered_key, ec.G)
        assert Q_computed[0] == public_key[0], \
            f"Qx mismatch: got {hex(Q_computed[0])}"
        assert Q_computed[1] == public_key[1], \
            f"Qy mismatch: got {hex(Q_computed[1])}"

    def test_key_verifies_all_ecdsa_signatures(self, ec, recovered_key,
                                                challenge_data):
        """Recovered key should verify every original ECDSA signature."""
        Q = ec.mul(recovered_key, ec.G)
        for sig_entry in challenge_data["ecdsa_signatures"]:
            r = int(sig_entry["r"], 16)
            s = int(sig_entry["s"], 16)
            msg = sig_entry["message"]

            h = hashlib.sha256(msg.encode()).digest()
            e = int.from_bytes(h, "big") % ec.q

            s_inv = modinv(s, ec.q)
            u1 = (e * s_inv) % ec.q
            u2 = (r * s_inv) % ec.q

            W = ec.add(ec.mul(u1, ec.G), ec.mul(u2, Q))
            assert W != ec.INF, f"Verification hit infinity for: {msg[:40]}"
            r_check = W[0] % ec.q
            assert r_check == r, \
                f"ECDSA verification failed for: {msg[:40]}"


class TestForgedSignature:
    def test_signature_fields_present(self, forged_sig):
        assert "r" in forged_sig, "Missing 'r' in forged signature"
        assert "s" in forged_sig, "Missing 's' in forged signature"

    def test_signature_values_in_range(self, forged_sig, ec):
        r = int(forged_sig["r"], 16)
        s = int(forged_sig["s"], 16)
        assert 0 < r < ec.q, "r out of range"
        assert 0 < s < ec.q, "s out of range"

    def test_ecrdsa_rfc_verification(self, ec, forged_sig, public_key,
                                      challenge_data):
        """
        ECRDSA verification (RFC/GOST R 34.10-2012):
        1. h = SHA-256(message)
        2. Reverse hash byte order (RFC standard)
        3. e_raw = int(reversed_h) mod q; if 0 set to 1
        4. e = e_raw^{-1} mod q
        5. u = e*s mod q,  v = -e*r mod q
        6. W' = u*G + v*Q
        7. Check W'.x mod q == r
        """
        r = int(forged_sig["r"], 16)
        s = int(forged_sig["s"], 16)
        Q = public_key
        msg = challenge_data["challenge"]["message"]

        h = hashlib.sha256(msg.encode()).digest()
        h_reversed = h[::-1]
        e_raw = int.from_bytes(h_reversed, "big") % ec.q
        if e_raw == 0:
            e_raw = 1
        e = modinv(e_raw, ec.q)

        u = (e * s) % ec.q
        v = (-e * r) % ec.q

        W_prime = ec.add(ec.mul(u, ec.G), ec.mul(v, Q))
        assert W_prime != ec.INF, "ECRDSA verification: point at infinity"

        r_prime = W_prime[0] % ec.q
        assert r == r_prime, \
            "ECRDSA signature verification failed (RFC/GOST variant)"
