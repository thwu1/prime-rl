"""Tests for ECC Protocol Security Audit & Remediation challenge.

Verifies three deliverables:
  1. Cryptanalysis — correct decrypted plaintext and scalar
  2. Vulnerability audit — correct property classification and remediation verdicts
  3. Secure replacement — mathematically verified secure ECC configuration
"""

import json
import os
import subprocess


EXPECTED_PLAINTEXT = "RECOVERED{ch41n3d_3cc_f4ct0r_d3crypt}"
EXPECTED_SCALAR = 26301556143914030339103816908643767057168924061363837


def gp_eval(statements):
    """Execute PARI/GP statements and return stdout."""
    try:
        full_input = 'default(parisizemax, 268435456);\n' + statements + "\n"
        result = subprocess.run(
            ["gp", "-q"],
            input=full_input,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip()
        if result.returncode != 0 and not output:
            raise AssertionError(f"PARI/GP error: {result.stderr.strip()}")
        return output
    except subprocess.TimeoutExpired:
        raise AssertionError("PARI/GP computation timed out")
    except FileNotFoundError:
        raise AssertionError("PARI/GP (gp) is not installed")


# =====================================================
# Phase 1: Cryptanalysis verification
# =====================================================


class TestCryptanalysis:
    """Verify the decrypted plaintext and the recovered scalar."""

    def test_solution_file_exists(self):
        assert os.path.isfile("/app/solution.txt"), \
            "/app/solution.txt does not exist"

    def test_plaintext_content(self):
        with open("/app/solution.txt") as f:
            content = f.read().strip()
        assert content == EXPECTED_PLAINTEXT, \
            f"Plaintext mismatch: got '{content}'"

    def test_scalar_satisfies_ecdlp(self):
        """Verify Q = s * G on the curve over Z/nZ."""
        with open("/app/challenge/public_params.json") as f:
            params = json.load(f)

        n = int(params["n"])
        A = int(params["A"])
        B = int(params["B"])
        Gx = int(params["G"]["x"])
        Gy = int(params["G"]["y"])
        Qx_exp = int(params["Q"]["x"])
        Qy_exp = int(params["Q"]["y"])
        s = EXPECTED_SCALAR

        def _modinv(a, m):
            def _egcd(a, b):
                if a == 0:
                    return b, 0, 1
                g, x, y = _egcd(b % a, a)
                return g, y - (b // a) * x, x
            g, x, _ = _egcd(a % m, m)
            return None if g != 1 else x % m

        def _add(P, Q):
            if P is None:
                return Q
            if Q is None:
                return P
            px, py = P
            qx, qy = Q
            if px == qx:
                if (py + qy) % n == 0:
                    return None
                num = (3 * px * px + 2 * A * px + B) % n
                den = (2 * py) % n
            else:
                num = (qy - py) % n
                den = (qx - px) % n
            inv = _modinv(den, n)
            assert inv is not None, "Modular inverse failed"
            lam = (num * inv) % n
            x3 = (lam * lam - A - px - qx) % n
            y3 = (lam * (px - x3) - py) % n
            return (x3, y3)

        def _mul(k, P):
            R, T = None, P
            while k > 0:
                if k & 1:
                    R = _add(R, T)
                T = _add(T, T)
                k >>= 1
            return R

        Q = _mul(s, (Gx, Gy))
        assert Q is not None, "s * G = O (infinity)"
        assert Q[0] == Qx_exp, f"Q.x mismatch: {Q[0]} != {Qx_exp}"
        assert Q[1] == Qy_exp, f"Q.y mismatch: {Q[1]} != {Qy_exp}"


# =====================================================
# Phase 2: Vulnerability audit verification
# =====================================================


class TestAudit:
    """Verify vulnerability classification and remediation verdicts."""

    @classmethod
    def setup_class(cls):
        assert os.path.isfile("/app/audit.json"), "audit.json not found"
        with open("/app/audit.json") as f:
            cls.audit = json.load(f)

    def test_modulus_type(self):
        assert self.audit.get("modulus_type") == "composite", \
            f"Expected modulus_type='composite', got '{self.audit.get('modulus_type')}'"

    def test_cm_discriminant(self):
        assert self.audit.get("cm_discriminant") == -4, \
            f"Expected cm_discriminant=-4, got {self.audit.get('cm_discriminant')}"

    def test_j_invariant(self):
        assert self.audit.get("j_invariant") == 1728, \
            f"Expected j_invariant=1728, got {self.audit.get('j_invariant')}"

    def test_factoring_method(self):
        method = str(self.audit.get("factoring_method", "")).lower()
        keywords = ["p+1", "pp1", "p_plus_1", "williams"]
        assert any(kw in method for kw in keywords), \
            f"Expected a p+1/Williams factoring method, got '{method}'"

    def test_ecdlp_method(self):
        method = str(self.audit.get("ecdlp_method", "")).lower()
        assert "pohlig" in method, \
            f"Expected Pohlig-Hellman ECDLP method, got '{method}'"

    def test_R1_ineffective(self):
        """Scaling key size without changing smooth-order prime selection is ineffective."""
        assert self.audit.get("R1_verdict") == "INEFFECTIVE", \
            f"R1 should be INEFFECTIVE (smooth orders persist regardless of size)"

    def test_R2_effective(self):
        """Switching to prime-field ECC with near-prime order eliminates the attack."""
        assert self.audit.get("R2_verdict") == "EFFECTIVE", \
            f"R2 should be EFFECTIVE (prime modulus + near-prime order)"

    def test_R3_effective(self):
        """Hardening curve orders with large prime factors defeats Pohlig-Hellman."""
        assert self.audit.get("R3_verdict") == "EFFECTIVE", \
            f"R3 should be EFFECTIVE (non-smooth orders prevent Pohlig-Hellman)"

    def test_R4_ineffective(self):
        """Changing the symmetric cipher does not affect the ECC key exchange vulnerability."""
        assert self.audit.get("R4_verdict") == "INEFFECTIVE", \
            f"R4 should be INEFFECTIVE (vulnerability is in ECC, not symmetric cipher)"


# =====================================================
# Phase 3: Secure replacement verification
# =====================================================


class TestSecureConfig:
    """Verify the designed ECC configuration meets security requirements."""

    @classmethod
    def setup_class(cls):
        assert os.path.isfile("/app/secure_config.json"), \
            "secure_config.json not found"
        with open("/app/secure_config.json") as f:
            cfg = json.load(f)
        cls.p = int(cfg["p"])
        cls.q = int(cfg["q"])
        cls.a = int(cfg["a"])
        cls.b = int(cfg["b"])
        cls.Gx = int(cfg["Gx"])
        cls.Gy = int(cfg["Gy"])
        cls.n = cls.p * cls.q

    def test_p_is_prime(self):
        r = gp_eval(f"print(isprime({self.p}))")
        assert r == "1", f"p={self.p} is not prime"

    def test_q_is_prime(self):
        r = gp_eval(f"print(isprime({self.q}))")
        assert r == "1", f"q={self.q} is not prime"

    def test_p_min_bits(self):
        assert self.p.bit_length() >= 80, \
            f"p has {self.p.bit_length()} bits, need >= 80"

    def test_q_min_bits(self):
        assert self.q.bit_length() >= 80, \
            f"q has {self.q.bit_length()} bits, need >= 80"

    def test_distinct_primes(self):
        assert self.p != self.q, "p and q must be distinct"

    def test_curve_nonsingular_mod_p(self):
        d = (4 * pow(self.a, 3, self.p) + 27 * pow(self.b, 2, self.p)) % self.p
        assert d != 0, "Curve is singular mod p (4a^3 + 27b^2 = 0)"

    def test_curve_nonsingular_mod_q(self):
        d = (4 * pow(self.a, 3, self.q) + 27 * pow(self.b, 2, self.q)) % self.q
        assert d != 0, "Curve is singular mod q (4a^3 + 27b^2 = 0)"

    def test_point_on_curve(self):
        lhs = pow(self.Gy, 2, self.n)
        x3 = pow(self.Gx, 3, self.n)
        ax = (self.a * self.Gx) % self.n
        rhs = (x3 + ax + self.b) % self.n
        assert lhs == rhs, "Base point G is not on the curve y^2 = x^3 + ax + b mod n"

    def test_order_hardness_mod_p(self):
        r = gp_eval(
            f"op=ellcard(ellinit([{self.a},{self.b}],{self.p}));"
            f"f=factor(op);print(f[matsize(f)[1],1])"
        )
        lpf = int(r)
        assert lpf >= 2**59, \
            f"Largest prime factor of #E(Fp) is {lpf}, need >= 2^59"

    def test_order_hardness_mod_q(self):
        r = gp_eval(
            f"oq=ellcard(ellinit([{self.a},{self.b}],{self.q}));"
            f"f=factor(oq);print(f[matsize(f)[1],1])"
        )
        lpf = int(r)
        assert lpf >= 2**59, \
            f"Largest prime factor of #E(Fq) is {lpf}, need >= 2^59"
