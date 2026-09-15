
"""Tests for ECC Cross-Algorithm Signature Forensics — verify output correctness."""

import json
import hashlib
import os
import pytest


# ---------- EC math ----------

def egcd(a, b):
    x0, x1, y0, y1 = 1, 0, 0, 1
    while b != 0:
        qq, a, b = a // b, b, a % b
        x0, x1 = x1, x0 - qq * x1
        y0, y1 = y1, y0 - qq * y1
    return a, x0, y0


def modinv(a, m):
    g, x, _ = egcd(a % m, m)
    if g != 1:
        raise ValueError("No modular inverse")
    return x % m


def ec_add(P, Q, a_coeff, p):
    if P is None:
        return Q
    if Q is None:
        return P
    x1, y1 = P
    x2, y2 = Q
    if x1 == x2:
        if (y1 + y2) % p == 0:
            return None
        lam = ((3 * x1 * x1 + a_coeff) * modinv(2 * y1, p)) % p
    else:
        lam = ((y2 - y1) * modinv((x2 - x1) % p, p)) % p
    x3 = (lam * lam - x1 - x2) % p
    y3 = (lam * (x1 - x3) - y1) % p
    return (x3, y3)


def ec_mul(k, P, a_coeff, p):
    R = None
    Q = P
    while k > 0:
        if k & 1:
            R = ec_add(R, Q, a_coeff, p)
        Q = ec_add(Q, Q, a_coeff, p)
        k >>= 1
    return R


# ---------- crypto helpers ----------

def sha256_str(msg):
    return hashlib.sha256(msg.encode('utf-8')).digest()


def ecdsa_verify(msg, r, s, Q, curve):
    p = curve["p"]
    a = curve["a"]
    n = curve["order"]
    G = (curve["Gx"], curve["Gy"])
    if r <= 0 or r >= n or s <= 0 or s >= n:
        return False
    h = int.from_bytes(sha256_str(msg), 'big') % n
    si = modinv(s, n)
    u = (si * h) % n
    v = (si * r) % n
    W = ec_add(ec_mul(u, G, a, p), ec_mul(v, Q, a, p), a, p)
    if W is None:
        return False
    return W[0] % n == r


def ecrdsa_verify(msg, r, s, Q, curve, iso):
    p = curve["p"]
    a = curve["a"]
    n = curve["order"]
    G = (curve["Gx"], curve["Gy"])
    if r <= 0 or r >= n or s <= 0 or s >= n:
        return False
    hb = sha256_str(msg)
    h_int = int.from_bytes(hb, 'big') if iso else int.from_bytes(hb[::-1], 'big')
    e = h_int % n
    if e == 0:
        e = 1
    ei = modinv(e, n)
    u = (ei * s) % n
    v = (-ei * r) % n
    W = ec_add(ec_mul(u, G, a, p), ec_mul(v, Q, a, p), a, p)
    if W is None:
        return False
    return W[0] % n == r


# ---------- data loaders ----------

def load_curve():
    with open("/challenge/curve_params.json") as f:
        d = json.load(f)
    return {
        "p": int(d["p"], 16),
        "a": int(d["a"], 16),
        "b": int(d["b"], 16),
        "Gx": int(d["Gx"], 16),
        "Gy": int(d["Gy"], 16),
        "order": int(d["order"], 16),
        "cofactor": d["cofactor"],
    }


def load_captures():
    with open("/challenge/captures.json") as f:
        return json.load(f)


def load_output():
    with open("/app/output.json") as f:
        return json.load(f)


def load_challenge():
    with open("/challenge/challenge_message.txt") as f:
        return f.read().strip()


# ---------- Montgomery / Barrett helpers ----------

def aligned_bitlen(prime, wlen):
    pbitlen = prime.bit_length()
    byte_size = (pbitlen + 7) // 8
    word_bytes = wlen // 8
    if byte_size % word_bytes != 0:
        ab = ((byte_size // word_bytes) + 1) * word_bytes
    else:
        ab = byte_size
    return ab * 8


def compute_montgomery_r(prime, wlen):
    abl = aligned_bitlen(prime, wlen)
    return (1 << abl) % prime


def compute_montgomery_r_sq(prime, wlen):
    abl = aligned_bitlen(prime, wlen)
    return (1 << (2 * abl)) % prime


def compute_mpinv(prime, wlen):
    return (1 << wlen) - modinv(prime, 1 << wlen)


def compute_p_reciprocal(prime, wlen):
    abl = aligned_bitlen(prime, wlen)
    cnt = prime.bit_length()
    p_shift = abl - cnt
    p_norm = prime << p_shift
    B = 1 << wlen
    return B ** 3 // ((p_norm >> (abl - 2 * wlen)) + 1) - B


# ========== TESTS ==========

class TestOutputStructure:
    def test_output_file_exists(self):
        assert os.path.exists("/app/output.json"), "output.json not found at /app/output.json"

    def test_output_has_required_fields(self):
        out = load_output()
        for key in ("curve_name", "classifications", "recovered_private_key",
                     "forged_signature", "internal_params_64bit",
                     "internal_params_32bit", "vulnerability_type",
                     "nonce_reuse_pair"):
            assert key in out, f"Missing required field: {key}"


class TestCurveIdentification:
    def test_curve_name_is_frp256v1(self):
        out = load_output()
        name = out["curve_name"].lower().replace("_", "").replace("-", "").replace(" ", "")
        assert name == "frp256v1", \
            f"Expected FRP256V1, got '{out['curve_name']}'"


class TestSignatureClassification:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.curve = load_curve()
        self.captures = load_captures()
        self.output = load_output()
        Qx = int(self.captures["public_key"]["Qx"], 16)
        Qy = int(self.captures["public_key"]["Qy"], 16)
        self.Q = (Qx, Qy)

    def test_classification_count(self):
        assert len(self.output["classifications"]) == 8, \
            f"Expected 8 classifications, got {len(self.output['classifications'])}"

    def _verify_classification(self, idx):
        sig = self.captures["signatures"][idx]
        algo = self.output["classifications"][idx]
        msg = sig["message"]
        r = int(sig["r"], 16)
        s = int(sig["s"], 16)
        assert algo in ("ecdsa", "ecrdsa_rfc", "ecrdsa_iso"), \
            f"Sig {idx}: invalid label '{algo}'"
        if algo == "ecdsa":
            ok = ecdsa_verify(msg, r, s, self.Q, self.curve)
        elif algo == "ecrdsa_rfc":
            ok = ecrdsa_verify(msg, r, s, self.Q, self.curve, False)
        else:
            ok = ecrdsa_verify(msg, r, s, self.Q, self.curve, True)
        assert ok, f"Sig {idx} does not verify as {algo}"

    def test_classification_sig_0(self):
        self._verify_classification(0)

    def test_classification_sig_1(self):
        self._verify_classification(1)

    def test_classification_sig_2(self):
        self._verify_classification(2)

    def test_classification_sig_3(self):
        self._verify_classification(3)

    def test_classification_sig_4(self):
        self._verify_classification(4)

    def test_classification_sig_5(self):
        self._verify_classification(5)

    def test_classification_sig_6(self):
        self._verify_classification(6)

    def test_classification_sig_7(self):
        self._verify_classification(7)


class TestVulnerabilityAnalysis:
    def test_vulnerability_type_mentions_cross_algorithm(self):
        out = load_output()
        vtype = out["vulnerability_type"].lower()
        assert "cross" in vtype and "algorithm" in vtype, \
            f"vulnerability_type must describe cross-algorithm nonce reuse, got '{out['vulnerability_type']}'"

    def test_nonce_reuse_pair_valid(self):
        out = load_output()
        pair = out["nonce_reuse_pair"]
        assert isinstance(pair, list) and len(pair) == 2, \
            "nonce_reuse_pair must be a list of 2 indices"
        assert set(pair) == {0, 3}, \
            f"Expected nonce reuse between indices 0 and 3, got {pair}"

    def test_reuse_pair_have_same_r(self):
        out = load_output()
        cap = load_captures()
        i, j = out["nonce_reuse_pair"]
        r_i = cap["signatures"][i]["r"]
        r_j = cap["signatures"][j]["r"]
        assert r_i == r_j, \
            f"Signatures {i} and {j} must share the same r value"

    def test_reuse_pair_different_algorithms(self):
        out = load_output()
        i, j = out["nonce_reuse_pair"]
        algo_i = out["classifications"][i]
        algo_j = out["classifications"][j]
        assert algo_i != algo_j, \
            f"Cross-algorithm reuse requires different algorithms, both are '{algo_i}'"


class TestKeyRecovery:
    def test_private_key_produces_public_key(self):
        out = load_output()
        curve = load_curve()
        cap = load_captures()
        d = int(out["recovered_private_key"], 16)
        assert 0 < d < curve["order"], \
            "Private key out of valid range"
        G = (curve["Gx"], curve["Gy"])
        Q_computed = ec_mul(d, G, curve["a"], curve["p"])
        Q_expected = (
            int(cap["public_key"]["Qx"], 16),
            int(cap["public_key"]["Qy"], 16)
        )
        assert Q_computed == Q_expected, \
            "d*G does not match the given public key"


class TestForgedSignature:
    def test_forged_sig_verifies_ecrdsa_rfc(self):
        out = load_output()
        curve = load_curve()
        cap = load_captures()
        challenge = load_challenge()
        r = int(out["forged_signature"]["r"], 16)
        s = int(out["forged_signature"]["s"], 16)
        Qx = int(cap["public_key"]["Qx"], 16)
        Qy = int(cap["public_key"]["Qy"], 16)
        Q = (Qx, Qy)
        assert ecrdsa_verify(challenge, r, s, Q, curve, False), \
            "Forged ECRDSA-RFC signature does not verify"

    def test_forged_sig_uses_deterministic_nonce(self):
        out = load_output()
        curve = load_curve()
        challenge = load_challenge()
        d = int(out["recovered_private_key"], 16)
        n = curve["order"]
        p = curve["p"]
        a = curve["a"]
        G = (curve["Gx"], curve["Gy"])
        k = int.from_bytes(
            hashlib.sha256(b"deterministic_forge_nonce").digest(), 'big'
        ) % n
        W = ec_mul(k, G, a, p)
        r_exp = W[0] % n
        hb = sha256_str(challenge)
        h_rfc = int.from_bytes(hb[::-1], 'big')
        e = h_rfc % n
        if e == 0:
            e = 1
        s_exp = (r_exp * d + k * e) % n
        r_got = int(out["forged_signature"]["r"], 16)
        s_got = int(out["forged_signature"]["s"], 16)
        assert r_got == r_exp, \
            f"Forged r mismatch: expected {hex(r_exp)}, got {hex(r_got)}"
        assert s_got == s_exp, \
            f"Forged s mismatch: expected {hex(s_exp)}, got {hex(s_got)}"


class TestInternalParams64Bit:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.curve = load_curve()
        self.output = load_output()
        self.prime = self.curve["p"]

    def test_montgomery_r(self):
        expected = compute_montgomery_r(self.prime, 64)
        got = int(self.output["internal_params_64bit"]["r"], 16)
        assert got == expected, \
            f"64-bit Montgomery R: expected {hex(expected)}, got {hex(got)}"

    def test_montgomery_r_squared(self):
        expected = compute_montgomery_r_sq(self.prime, 64)
        got = int(self.output["internal_params_64bit"]["r_squared"], 16)
        assert got == expected, \
            f"64-bit Montgomery R²: expected {hex(expected)}, got {hex(got)}"

    def test_mpinv(self):
        expected = compute_mpinv(self.prime, 64)
        got = int(self.output["internal_params_64bit"]["mpinv"], 16)
        assert got == expected, \
            f"64-bit mpinv: expected {hex(expected)}, got {hex(got)}"

    def test_p_reciprocal(self):
        expected = compute_p_reciprocal(self.prime, 64)
        got = int(self.output["internal_params_64bit"]["p_reciprocal"], 16)
        assert got == expected, \
            f"64-bit p_reciprocal: expected {hex(expected)}, got {hex(got)}"


class TestInternalParams32Bit:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.curve = load_curve()
        self.output = load_output()
        self.prime = self.curve["p"]

    def test_montgomery_r_32(self):
        expected = compute_montgomery_r(self.prime, 32)
        got = int(self.output["internal_params_32bit"]["r"], 16)
        assert got == expected, \
            f"32-bit Montgomery R: expected {hex(expected)}, got {hex(got)}"

    def test_montgomery_r_squared_32(self):
        expected = compute_montgomery_r_sq(self.prime, 32)
        got = int(self.output["internal_params_32bit"]["r_squared"], 16)
        assert got == expected, \
            f"32-bit Montgomery R²: expected {hex(expected)}, got {hex(got)}"

    def test_mpinv_32(self):
        expected = compute_mpinv(self.prime, 32)
        got = int(self.output["internal_params_32bit"]["mpinv"], 16)
        assert got == expected, \
            f"32-bit mpinv: expected {hex(expected)}, got {hex(got)}"

    def test_p_reciprocal_32(self):
        expected = compute_p_reciprocal(self.prime, 32)
        got = int(self.output["internal_params_32bit"]["p_reciprocal"], 16)
        assert got == expected, \
            f"32-bit p_reciprocal: expected {hex(expected)}, got {hex(got)}"
