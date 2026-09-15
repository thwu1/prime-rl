
import json
import hashlib
import os
import subprocess
import pytest


def extended_gcd(a, b):
    """Extended Euclidean algorithm (iterative)."""
    old_r, r = a, b
    old_s, s = 1, 0
    while r != 0:
        quotient = old_r // r
        old_r, r = r, old_r - quotient * r
        old_s, s = s, old_s - quotient * s
    return old_r, old_s


def modinv(a, m):
    a = a % m
    g, x = extended_gcd(a, m)
    if g != 1:
        raise ValueError("Modular inverse does not exist")
    return x % m


def compute_correct_montgomery(prime, wlen=64):
    bitlen = prime.bit_length()
    pbitlen = ((bitlen + wlen - 1) // wlen) * wlen
    r = pow(2, pbitlen, prime)
    r_square = pow(2, 2 * pbitlen, prime)
    p_low = prime % (2**wlen)
    mpinv = (2**wlen - modinv(p_low, 2**wlen)) % (2**wlen)
    return r, r_square, mpinv, pbitlen


# ========================================================
# Challenge 1: Montgomery Representation Audit
# ========================================================

class TestMontgomeryAudit:

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/data/montgomery_challenge.json") as f:
            self.challenge = json.load(f)
        with open("/app/results/montgomery_results.json") as f:
            self.results = json.load(f)
        self.wlen = self.challenge["wlen"]

    def test_all_curves_present(self):
        """Every curve in the challenge must have a result entry."""
        for name in self.challenge["curves"]:
            assert name in self.results, f"Missing result for curve {name}"

    def test_correctness_identification(self):
        """Agent must correctly identify which curves have wrong params."""
        for name, curve_data in self.challenge["curves"].items():
            prime = int(curve_data["prime"], 16)
            r_c, r_sq_c, mpinv_c, pbitlen_c = compute_correct_montgomery(
                prime, self.wlen
            )

            alleged_r = int(curve_data["alleged_r"], 16)
            alleged_r_sq = int(curve_data["alleged_r_square"], 16)
            alleged_mpinv = int(curve_data["alleged_mpinv"], 16)
            alleged_pbitlen = curve_data["alleged_pbitlen"]

            is_correct = (
                alleged_r == r_c
                and alleged_r_sq == r_sq_c
                and alleged_mpinv == mpinv_c
                and alleged_pbitlen == pbitlen_c
            )

            result = self.results[name]
            assert result["correct"] == is_correct, (
                f"Curve {name}: expected correct={is_correct}, got {result['correct']}"
            )

    def test_corrected_values(self):
        """For curves flagged as incorrect, the corrected values must be right."""
        for name, curve_data in self.challenge["curves"].items():
            prime = int(curve_data["prime"], 16)
            r_c, r_sq_c, mpinv_c, pbitlen_c = compute_correct_montgomery(
                prime, self.wlen
            )

            result = self.results[name]
            if not result["correct"]:
                assert int(result["correct_r"], 16) == r_c, (
                    f"{name}: wrong corrected r"
                )
                assert int(result["correct_r_square"], 16) == r_sq_c, (
                    f"{name}: wrong corrected r_square"
                )
                assert int(result["correct_mpinv"], 16) == mpinv_c, (
                    f"{name}: wrong corrected mpinv"
                )
                assert result["correct_pbitlen"] == pbitlen_c, (
                    f"{name}: wrong corrected pbitlen"
                )


# ========================================================
# Challenge 2: ECRDSA Endianness Classification
# ========================================================

class TestECRDSAClassification:

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/data/ecrdsa_challenge.json") as f:
            self.challenge = json.load(f)
        with open("/app/results/ecrdsa_results.json") as f:
            self.results = json.load(f)

    def test_hash_consistency(self):
        """Verify the SHA-256 hash in challenge data matches the message."""
        message = bytes.fromhex(self.challenge["message_hex"])
        computed = hashlib.sha256(message).hexdigest()
        assert computed == self.challenge["hash_sha256_hex"], "Hash mismatch"

    def test_all_signatures_classified(self):
        """Every signature must have a classification."""
        for sig_data in self.challenge["signatures"]:
            sig_id = sig_data["id"]
            assert sig_id in self.results, f"Missing classification for {sig_id}"

    def test_classification_correct(self):
        """Each signature must be correctly classified as ISO or RFC."""
        q = int(self.challenge["curve_order_q"], 16)
        x = int(self.challenge["private_key_x"], 16)
        h_bytes = bytes.fromhex(self.challenge["hash_sha256_hex"])

        # ISO 14888-3: big-endian hash interpretation
        e_iso = int.from_bytes(h_bytes, 'big') % q
        # RFC 7091: byte-reversed hash interpretation
        e_rfc = int.from_bytes(h_bytes[::-1], 'big') % q

        for sig_data in self.challenge["signatures"]:
            sig_id = sig_data["id"]
            r = int(sig_data["r"], 16)
            s = int(sig_data["s"], 16)
            k = int(sig_data["k"], 16)

            s_iso = (r * x + k * e_iso) % q
            s_rfc = (r * x + k * e_rfc) % q

            if s == s_iso:
                expected = "ISO"
            elif s == s_rfc:
                expected = "RFC"
            else:
                pytest.fail(
                    f"Internal error: {sig_id} doesn't match either mode"
                )

            assert self.results[sig_id] == expected, (
                f"{sig_id}: expected {expected}, got {self.results[sig_id]}"
            )


# ========================================================
# Challenge 3: ECDSA Private Key Recovery
# ========================================================

class TestECDSARecovery:

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/data/ecdsa_signatures.json") as f:
            self.challenge = json.load(f)
        with open("/app/results/ecdsa_recovery.json") as f:
            self.results = json.load(f)

    def test_hash_consistency(self):
        """Verify the e values match SHA-256 of the messages."""
        q = int(self.challenge["curve_order_q"], 16)

        m1 = bytes.fromhex(self.challenge["signature_1"]["message_hex"])
        m2 = bytes.fromhex(self.challenge["signature_2"]["message_hex"])

        e1_computed = int.from_bytes(
            hashlib.sha256(m1).digest(), 'big'
        ) % q
        e2_computed = int.from_bytes(
            hashlib.sha256(m2).digest(), 'big'
        ) % q

        assert e1_computed == int(self.challenge["signature_1"]["e"], 16)
        assert e2_computed == int(self.challenge["signature_2"]["e"], 16)

    def test_recovered_key_correct(self):
        """The recovered private key and nonce must be correct."""
        q = int(self.challenge["curve_order_q"], 16)
        e1 = int(self.challenge["signature_1"]["e"], 16)
        e2 = int(self.challenge["signature_2"]["e"], 16)
        r = int(self.challenge["signature_1"]["r"], 16)
        s1 = int(self.challenge["signature_1"]["s"], 16)
        s2 = int(self.challenge["signature_2"]["s"], 16)

        # Independent recovery
        ds = (s1 - s2) % q
        de = (e1 - e2) % q
        k_correct = (de * modinv(ds, q)) % q
        x_correct = ((s1 * k_correct - e1) * modinv(r, q)) % q

        # Verify recovery is self-consistent
        k_inv = modinv(k_correct, q)
        assert (k_inv * (e1 + x_correct * r)) % q == s1, (
            "Recovery self-check failed for s1"
        )
        assert (k_inv * (e2 + x_correct * r)) % q == s2, (
            "Recovery self-check failed for s2"
        )

        # Check agent's answer
        agent_x = int(self.results["recovered_x"], 16)
        agent_k = int(self.results["recovered_k"], 16)

        assert agent_x == x_correct, "Wrong recovered private key"
        assert agent_k == k_correct, "Wrong recovered nonce"


# ========================================================
# Challenge 4: Security Assessment
# ========================================================

class TestSecurityAssessment:

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/results/security_assessment.json") as f:
            self.assessment = json.load(f)

    def test_has_findings(self):
        """Assessment must contain findings covering all challenge areas."""
        assert "findings" in self.assessment
        assert isinstance(self.assessment["findings"], list)
        assert len(self.assessment["findings"]) >= 3, (
            "Expected at least 3 findings (one per challenge area)"
        )

    def test_finding_structure(self):
        """Each finding must have required fields with valid values."""
        valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        for finding in self.assessment["findings"]:
            assert "id" in finding, "Finding missing 'id' field"
            assert "severity" in finding, "Finding missing 'severity' field"
            assert "category" in finding, "Finding missing 'category' field"
            assert "impact" in finding, "Finding missing 'impact' field"
            assert finding["severity"] in valid_severities, (
                f"Invalid severity: {finding['severity']}"
            )
            assert len(finding["impact"]) > 10, (
                "Impact description too short"
            )

    def test_has_critical_finding(self):
        """At least one finding must be CRITICAL (key compromise is critical)."""
        severities = [f["severity"] for f in self.assessment["findings"]]
        assert "CRITICAL" in severities, (
            "No CRITICAL finding — the ECDSA key recovery vulnerability "
            "warrants CRITICAL severity"
        )

    def test_overall_risk(self):
        """Overall risk must be CRITICAL given key compromise is possible."""
        assert "overall_risk" in self.assessment
        assert self.assessment["overall_risk"] == "CRITICAL", (
            "Overall risk should be CRITICAL when private key compromise exists"
        )

    def test_risk_justification(self):
        """Risk justification must be present and substantive."""
        assert "risk_justification" in self.assessment
        assert isinstance(self.assessment["risk_justification"], str)
        assert len(self.assessment["risk_justification"]) > 20, (
            "Risk justification too short"
        )


# ========================================================
# Challenge 5: Automated Detection Script
# ========================================================

class TestDetectionScript:

    def test_script_exists(self):
        """Detection script must exist."""
        assert os.path.isfile("/app/results/detect.sh"), (
            "detect.sh not found in /app/results/"
        )

    def test_detects_invalid_curves(self):
        """Script must detect invalid curves when run against challenge data."""
        script_path = "/app/results/detect.sh"
        os.chmod(script_path, 0o755)
        result = subprocess.run(
            ["bash", script_path, "/app/data/montgomery_challenge.json"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 1, (
            f"Expected exit code 1 (invalid params found), got {result.returncode}. "
            f"stderr: {result.stderr[:500]}"
        )
        output = result.stdout
        assert "FRP256V1" in output, (
            "Script did not detect FRP256V1 as invalid"
        )
        assert "SECP521R1" in output, (
            "Script did not detect SECP521R1 as invalid"
        )

    def test_no_false_positives(self):
        """Script must not flag valid curves."""
        script_path = "/app/results/detect.sh"
        os.chmod(script_path, 0o755)
        result = subprocess.run(
            ["bash", script_path, "/app/data/montgomery_challenge.json"],
            capture_output=True, text=True, timeout=60
        )
        # Parse output lines — only invalid curve names should appear
        output_lines = [
            line.strip() for line in result.stdout.strip().split("\n")
            if line.strip()
        ]
        valid_curves = {"SECP192R1", "SECP256K1", "BRAINPOOLP256R1"}
        for line in output_lines:
            for vc in valid_curves:
                if line == vc:
                    pytest.fail(
                        f"False positive: valid curve {vc} reported as invalid"
                    )
