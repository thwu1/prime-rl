
import sys
import os
import json
import subprocess
import time
import signal
import copy
import pytest

sys.path.insert(0, "/app")


# ============================================================
# Section 1: PKI Infrastructure Tests
# ============================================================


class TestPKI:
    """Verify the PKI chain generated with openssl."""

    PKI_DIR = "/app/pki"

    def test_ca_cert_exists_and_self_signed(self):
        """CA certificate must exist and be verifiable against itself."""
        result = subprocess.run(
            ["openssl", "verify", "-CAfile",
             f"{self.PKI_DIR}/ca.crt", f"{self.PKI_DIR}/ca.crt"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"CA self-verify failed: {result.stderr}"
        assert "OK" in result.stdout

    def test_server_cert_signed_by_ca(self):
        """Server certificate must be signed by the root CA."""
        result = subprocess.run(
            ["openssl", "verify", "-CAfile",
             f"{self.PKI_DIR}/ca.crt", f"{self.PKI_DIR}/server.crt"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"Server cert verify failed: {result.stderr}"
        assert "OK" in result.stdout

    def test_client_cert_signed_by_ca(self):
        """Client certificate must be signed by the root CA."""
        result = subprocess.run(
            ["openssl", "verify", "-CAfile",
             f"{self.PKI_DIR}/ca.crt", f"{self.PKI_DIR}/client.crt"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"Client cert verify failed: {result.stderr}"
        assert "OK" in result.stdout

    def test_server_cert_has_san_localhost(self):
        """Server certificate must have SAN with localhost."""
        result = subprocess.run(
            ["openssl", "x509", "-in", f"{self.PKI_DIR}/server.crt",
             "-noout", "-text"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        # Check for DNS:localhost or IP:127.0.0.1 in SAN
        output = result.stdout
        assert "DNS:localhost" in output or "IP Address:127.0.0.1" in output, \
            f"Server cert missing SAN for localhost. Extensions:\n{output}"

    def test_server_cert_rsa_key_size(self):
        """Server key must be RSA >= 2048 bits."""
        result = subprocess.run(
            ["openssl", "rsa", "-in", f"{self.PKI_DIR}/server.key",
             "-text", "-noout"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        # Look for key size in output (e.g. "Private-Key: (2048 bit)")
        import re
        match = re.search(r"(\d+)\s*bit", result.stdout)
        assert match is not None, "Could not determine key size"
        key_bits = int(match.group(1))
        assert key_bits >= 2048, f"Key too small: {key_bits} bits"


# ============================================================
# Section 2: TOTP (RFC 6238) Tests
# ============================================================


class TestTOTP:
    """Verify TOTP implementation against RFC 6238 test vectors."""

    # RFC 6238 SHA-1 test seed: ASCII "12345678901234567890"
    SEED = bytes.fromhex("3132333435363738393031323334353637383930")

    def test_totp_rfc6238_time_59(self):
        """RFC 6238 test vector: time=59 should produce 94287082."""
        from esvts_auth import generate_totp
        code = generate_totp(self.SEED, timestamp=59, step=30, digits=8)
        assert code == "94287082", f"Expected 94287082, got {code}"

    def test_totp_rfc6238_time_1111111109(self):
        """RFC 6238 test vector: time=1111111109 should produce 07081804."""
        from esvts_auth import generate_totp
        code = generate_totp(self.SEED, timestamp=1111111109, step=30, digits=8)
        assert code == "07081804", f"Expected 07081804, got {code}"

    def test_totp_rfc6238_time_1234567890(self):
        """RFC 6238 test vector: time=1234567890 should produce 89005924."""
        from esvts_auth import generate_totp
        code = generate_totp(self.SEED, timestamp=1234567890, step=30, digits=8)
        assert code == "89005924", f"Expected 89005924, got {code}"

    def test_totp_verify_with_window(self):
        """verify_totp should accept codes within ±1 time step."""
        from esvts_auth import generate_totp, verify_totp
        # Generate code at T=59 (counter=1)
        code = generate_totp(self.SEED, timestamp=59, step=30, digits=8)
        # Should verify at T=59 (same step)
        assert verify_totp(self.SEED, code, timestamp=59, step=30, digits=8, window=1)
        # Should verify at T=31 (counter=1, within window of counter=1 at T=59)
        assert verify_totp(self.SEED, code, timestamp=31, step=30, digits=8, window=1)
        # Should NOT verify at T=120 (counter=4, outside window of counter=1)
        assert not verify_totp(self.SEED, code, timestamp=120, step=30, digits=8, window=1)

    def test_totp_zero_padding(self):
        """TOTP codes must be zero-padded to 8 digits."""
        from esvts_auth import generate_totp
        # time=1111111109 produces 07081804 (leading zero)
        code = generate_totp(self.SEED, timestamp=1111111109, step=30, digits=8)
        assert len(code) == 8, f"Code must be 8 digits, got {len(code)}: {code}"
        assert code[0] == "0", f"Expected leading zero, got: {code}"


# ============================================================
# Section 3: JWT Tests
# ============================================================


class TestJWT:
    """Verify JWT implementation (HMAC-SHA256)."""

    SECRET = "test-jwt-secret-key"

    def test_jwt_structure(self):
        """JWT must have three base64url-separated parts."""
        from esvts_auth import create_jwt
        token = create_jwt({"sub": "test"}, self.SECRET)
        parts = token.split(".")
        assert len(parts) == 3, f"JWT must have 3 parts, got {len(parts)}"
        # Each part should be valid base64url (alphanumeric + - + _)
        import re
        for i, part in enumerate(parts):
            assert re.match(r'^[A-Za-z0-9_-]+$', part), \
                f"Part {i} is not valid base64url: {part}"

    def test_jwt_roundtrip(self):
        """create_jwt followed by verify_jwt should return original claims."""
        from esvts_auth import create_jwt, verify_jwt
        claims = {"userId": 42, "eaId": 7, "type": "session"}
        token = create_jwt(claims, self.SECRET, expires_in=3600)
        decoded = verify_jwt(token, self.SECRET)
        assert decoded is not None, "verify_jwt returned None"
        assert decoded["userId"] == 42
        assert decoded["eaId"] == 7
        assert decoded["type"] == "session"
        assert "exp" in decoded
        assert "iat" in decoded

    def test_jwt_expired_token(self):
        """Expired JWT must return None from verify_jwt."""
        from esvts_auth import create_jwt, verify_jwt
        # Create a token that expired 100 seconds ago
        import time as time_mod
        claims = {"sub": "test", "exp": int(time_mod.time()) - 100}
        token = create_jwt(claims, self.SECRET)
        result = verify_jwt(token, self.SECRET)
        assert result is None, "Expired token should return None"

    def test_jwt_invalid_signature(self):
        """Token signed with wrong secret must return None."""
        from esvts_auth import create_jwt, verify_jwt
        token = create_jwt({"sub": "test"}, self.SECRET)
        result = verify_jwt(token, "wrong-secret")
        assert result is None, "Invalid signature should return None"


# ============================================================
# Section 4: Validation Engine Tests
# ============================================================


TREE_PATH = "/app/vsf_config/ValidationTrees/RegisterRequest/registerEntropySource.json"
RULES_DIR = "/app/vsf_config/RuleScripts"


def _make_valid_payload():
    return {
        "PrimaryNoiseSource": "ring oscillators",
        "IidClaim": False,
        "BitsPerSample": 4,
        "HMinEstimate": 3.1,
        "IsPhysical": True,
        "AdditionalNoiseSources": False,
        "NumberOfRestarts": 1000,
        "SamplesPerRestart": 1000,
        "OperatingEnvironmentIds": [1, 2],
        "Metadata": None,
        "ConditioningComponents": [
            {
                "SequencePosition": 1,
                "IsVetted": False,
                "Description": "custom XOR filter",
                "IsBijectiveClaim": False,
                "ValidationNumber": None,
                "MinNIn": 16,
                "NOut": 8,
                "HOut": 7.5,
            }
        ],
    }


class TestValidationEngine:
    """Verify the VSF engine against the entropy source validation tree."""

    @pytest.fixture
    def engine(self):
        from vsf_engine import VsfEngine
        return VsfEngine(RULES_DIR)

    def test_valid_payload_passes(self, engine):
        """A valid payload passes all rules."""
        from vsf_engine import ValidationResult
        payload = _make_valid_payload()
        result = engine.validate(TREE_PATH, payload)
        assert isinstance(result, ValidationResult)
        assert result.passed is True
        assert len(result.errors) == 0

    def test_null_payload_fails(self, engine):
        """Null payload fails root notNull check."""
        result = engine.validate(TREE_PATH, None)
        assert result.passed is False
        assert any(
            e.rule_text == "currentProperty != null" and e.property_path == ""
            for e in result.errors
        )

    def test_bits_per_sample_out_of_range(self, engine):
        """bitsPerSample=0 fails range check."""
        payload = _make_valid_payload()
        payload["BitsPerSample"] = 0
        payload["HMinEstimate"] = 0.0
        result = engine.validate(TREE_PATH, payload)
        assert result.passed is False
        assert any(e.property_path == "BitsPerSample" for e in result.errors)

    def test_vetted_cc_branch_logic(self, engine):
        """Vetted CC without validationNumber fails the vetted branch."""
        payload = _make_valid_payload()
        payload["ConditioningComponents"] = [
            {
                "SequencePosition": 1,
                "IsVetted": True,
                "Description": "AES-CBC-MAC",
                "IsBijectiveClaim": None,
                "ValidationNumber": None,
                "MinNIn": 128,
                "NOut": 128,
                "HOut": 120,
            }
        ]
        result = engine.validate(TREE_PATH, payload)
        assert result.passed is False
        assert any("ValidationNumber" in e.property_path for e in result.errors)

    def test_list_uniqueness(self, engine):
        """Duplicate OE IDs fail listIsUnique."""
        payload = _make_valid_payload()
        payload["OperatingEnvironmentIds"] = [1, 1, 2]
        result = engine.validate(TREE_PATH, payload)
        assert result.passed is False
        assert any(
            "OperatingEnvironmentIds" in e.property_path and "Distinct" in e.rule_text
            for e in result.errors
        )

    def test_cc_hout_exceeds_nout(self, engine):
        """CC where hOut > nOut fails cross-property check."""
        payload = _make_valid_payload()
        payload["ConditioningComponents"] = [
            {
                "SequencePosition": 1,
                "IsVetted": False,
                "Description": "custom filter",
                "IsBijectiveClaim": False,
                "ValidationNumber": None,
                "MinNIn": 16,
                "NOut": 8,
                "HOut": 9.0,
            }
        ]
        result = engine.validate(TREE_PATH, payload)
        assert result.passed is False
        assert any(
            "ConditioningComponents[0]" in e.property_path and "HOut" in e.rule_text
            for e in result.errors
        )


# ============================================================
# Section 5: Server Integration Tests
# ============================================================


class TestServerIntegration:
    """Test the ESVTS server via subprocess + curl with mTLS."""

    PKI = "/app/pki"
    BASE_URL = "https://localhost:7443"
    _server_proc = None

    @classmethod
    def setup_class(cls):
        """Start the ESVTS server in the background."""
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        cls._server_proc = subprocess.Popen(
            ["python3", "/app/esvts_server.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
            env=env,
        )
        # Wait for server to accept connections (up to 15 seconds)
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = subprocess.run(
                    ["curl", "-sk", "--max-time", "2",
                     "--cacert", f"{cls.PKI}/ca.crt",
                     "--cert", f"{cls.PKI}/client.crt",
                     "--key", f"{cls.PKI}/client.key",
                     "-o", "/dev/null", "-w", "%{http_code}",
                     f"{cls.BASE_URL}/esv/v1/login"],
                    capture_output=True, text=True, timeout=4,
                )
                if r.returncode == 0 and r.stdout.strip():
                    return  # server is up
            except Exception:
                pass
            time.sleep(1)
        pytest.fail("ESVTS server did not start within 15 seconds")

    @classmethod
    def teardown_class(cls):
        """Kill the server process group."""
        if cls._server_proc and cls._server_proc.poll() is None:
            try:
                os.killpg(os.getpgid(cls._server_proc.pid), signal.SIGTERM)
                cls._server_proc.wait(timeout=5)
            except Exception:
                cls._server_proc.kill()

    def _curl(self, method, path, data=None, token=None, expect_code=None):
        """Run curl with mTLS and return (http_code, response_body)."""
        cmd = [
            "curl", "-sk", "--max-time", "10",
            "--cacert", f"{self.PKI}/ca.crt",
            "--cert", f"{self.PKI}/client.crt",
            "--key", f"{self.PKI}/client.key",
            "-X", method,
            "-w", "\n%{http_code}",
            f"{self.BASE_URL}{path}",
        ]
        if data is not None:
            cmd.extend(["-H", "Content-Type: application/json",
                        "-d", json.dumps(data)])
        if token:
            cmd.extend(["-H", f"Authorization: Bearer {token}"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines = result.stdout.strip().rsplit("\n", 1)
        body = lines[0] if len(lines) > 1 else ""
        code = int(lines[-1]) if lines[-1].isdigit() else 0
        return code, body

    def _login(self):
        """Perform login and return session JWT."""
        from esvts_auth import generate_totp
        seed = bytes.fromhex(open("/app/totp_seed.txt").read().strip())
        totp_code = generate_totp(seed)
        code, body = self._curl("POST", "/esv/v1/login", [
            {"esvVersion": "1.0"},
            {"password": totp_code},
        ])
        assert code == 200, f"Login failed with {code}: {body}"
        resp = json.loads(body)
        return resp[1]["accessToken"]

    def test_login_valid_totp(self):
        """POST /esv/v1/login with valid TOTP returns 200 and a JWT."""
        token = self._login()
        assert token is not None
        assert len(token.split(".")) == 3, "Token is not a valid JWT"

    def test_login_invalid_totp(self):
        """POST /esv/v1/login with invalid TOTP returns 403."""
        code, body = self._curl("POST", "/esv/v1/login", [
            {"esvVersion": "1.0"},
            {"password": "00000000"},
        ])
        assert code == 403, f"Expected 403 for invalid TOTP, got {code}"

    def test_register_valid_payload(self):
        """POST /esv/v1/entropyAssessments with valid payload returns 200 with eaId."""
        token = self._login()
        payload = [
            {"esvVersion": "1.0"},
            {
                "primaryNoiseSource": "ring oscillators",
                "iidClaim": False,
                "bitsPerSample": 4,
                "hminEstimate": 3.1,
                "physical": True,
                "numberOfRestarts": 1000,
                "samplesPerRestart": 1000,
                "additionalNoiseSources": False,
                "conditioningComponent": [
                    {
                        "sequencePosition": 1,
                        "vetted": False,
                        "bijectiveClaim": False,
                        "description": "custom XOR filter",
                        "minNin": 16,
                        "nOut": 8,
                        "hOut": 7.5,
                    }
                ],
            },
        ]
        code, body = self._curl("POST", "/esv/v1/entropyAssessments",
                                data=payload, token=token)
        assert code == 200, f"Registration failed with {code}: {body}"
        resp = json.loads(body)
        # Response format: [version, [assessment_objects]]
        assessments = resp[1]
        assert isinstance(assessments, list) and len(assessments) >= 1
        ea = assessments[0]
        assert "url" in ea
        assert "accessToken" in ea
        assert "dataFileUrls" in ea

        # Verify the assessment JWT has eaId claim
        from esvts_auth import verify_jwt
        jwt_secret = open("/app/jwt_secret.txt").read().strip()
        ea_claims = verify_jwt(ea["accessToken"], jwt_secret)
        assert ea_claims is not None, "Assessment JWT is invalid"
        assert "eaId" in ea_claims, "Assessment JWT must contain eaId claim"

    def test_register_invalid_payload_rejected(self):
        """POST /esv/v1/entropyAssessments with invalid payload returns 400."""
        token = self._login()
        payload = [
            {"esvVersion": "1.0"},
            {
                "primaryNoiseSource": None,
                "iidClaim": False,
                "bitsPerSample": 0,
                "hminEstimate": 0.0,
                "physical": True,
                "numberOfRestarts": 500,
                "samplesPerRestart": 1000,
                "additionalNoiseSources": False,
                "conditioningComponent": [],
            },
        ]
        code, body = self._curl("POST", "/esv/v1/entropyAssessments",
                                data=payload, token=token)
        assert code == 400, f"Expected 400 for invalid payload, got {code}: {body}"

    def test_get_assessment_status(self):
        """GET /esv/v1/entropyAssessments/<eaId> returns assessment status."""
        token = self._login()
        # Register first
        reg_payload = [
            {"esvVersion": "1.0"},
            {
                "primaryNoiseSource": "thermal noise",
                "iidClaim": True,
                "bitsPerSample": 8,
                "hminEstimate": 7.0,
                "physical": True,
                "numberOfRestarts": 1000,
                "samplesPerRestart": 1000,
                "additionalNoiseSources": False,
                "conditioningComponent": [],
            },
        ]
        code, body = self._curl("POST", "/esv/v1/entropyAssessments",
                                data=reg_payload, token=token)
        assert code == 200, f"Setup registration failed: {code}: {body}"
        resp = json.loads(body)
        ea_url = resp[1][0]["url"]  # e.g. /esv/v1/entropyAssessments/1

        # GET status
        code, body = self._curl("GET", ea_url, token=token)
        assert code == 200, f"GET status failed: {code}: {body}"
        status_resp = json.loads(body)
        ea_data = status_resp[1]
        assert ea_data["status"] == "pendingEvaluation"
        assert ea_data["primaryNoiseSource"] == "thermal noise"
        assert ea_data["bitsPerSample"] == 8
