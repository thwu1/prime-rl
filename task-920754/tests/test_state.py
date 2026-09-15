import subprocess
import time
import json
import os
import copy
import signal
import pytest


PKI_DIR = "/app/pki"
SERVER_SCRIPT = "/app/esv_server/server.py"
SERVER_URL = "https://localhost:8443"
CA_CERT = os.path.join(PKI_DIR, "ca.pem")
CLIENT_CERT = os.path.join(PKI_DIR, "client.pem")
CLIENT_KEY = os.path.join(PKI_DIR, "client.key")
TOTP_SEED_FILE = "/app/config/totp_seed.txt"

# ====================================================================
# PKI Infrastructure Tests
# ====================================================================

class TestPKIInfrastructure:
    """Verify that the PKI files exist and have correct X.509 properties."""

    def test_ca_cert_exists(self):
        assert os.path.isfile(os.path.join(PKI_DIR, "ca.pem")), "CA certificate not found"
        assert os.path.isfile(os.path.join(PKI_DIR, "ca.key")), "CA private key not found"

    def test_server_cert_exists(self):
        assert os.path.isfile(os.path.join(PKI_DIR, "server.pem")), "Server certificate not found"
        assert os.path.isfile(os.path.join(PKI_DIR, "server.key")), "Server private key not found"

    def test_client_cert_exists(self):
        assert os.path.isfile(os.path.join(PKI_DIR, "client.pem")), "Client certificate not found"
        assert os.path.isfile(os.path.join(PKI_DIR, "client.key")), "Client private key not found"

    def test_ca_has_basic_constraints_ca_true(self):
        result = subprocess.run(
            ["openssl", "x509", "-in", os.path.join(PKI_DIR, "ca.pem"), "-text", "-noout"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"openssl failed: {result.stderr}"
        assert "CA:TRUE" in result.stdout, "CA certificate missing basicConstraints CA:TRUE"

    def test_server_cert_has_san_localhost(self):
        result = subprocess.run(
            ["openssl", "x509", "-in", os.path.join(PKI_DIR, "server.pem"), "-text", "-noout"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"openssl failed: {result.stderr}"
        assert "DNS:localhost" in result.stdout, "Server cert missing SAN DNS:localhost"
        assert "127.0.0.1" in result.stdout, "Server cert missing SAN IP:127.0.0.1"

    def test_client_cert_cn(self):
        result = subprocess.run(
            ["openssl", "x509", "-in", os.path.join(PKI_DIR, "client.pem"), "-subject", "-noout"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"openssl failed: {result.stderr}"
        assert "ESVTestClient" in result.stdout, "Client cert CN must be ESVTestClient"

    def test_server_cert_signed_by_ca(self):
        result = subprocess.run(
            ["openssl", "verify", "-CAfile", os.path.join(PKI_DIR, "ca.pem"),
             os.path.join(PKI_DIR, "server.pem")],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"Server cert chain verification failed: {result.stderr}"

    def test_client_cert_signed_by_ca(self):
        result = subprocess.run(
            ["openssl", "verify", "-CAfile", os.path.join(PKI_DIR, "ca.pem"),
             os.path.join(PKI_DIR, "client.pem")],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"Client cert chain verification failed: {result.stderr}"


# ====================================================================
# Server Fixture
# ====================================================================

@pytest.fixture(scope="module")
def running_server():
    """Start the ESV server and wait for it to accept connections."""
    import requests as req
    proc = subprocess.Popen(
        ["python3", SERVER_SCRIPT],
        stdout=open("/tmp/esv_server_stdout.log", "w"),
        stderr=open("/tmp/esv_server_stderr.log", "w"),
        preexec_fn=os.setsid,
    )
    ready = False
    for _ in range(40):
        try:
            req.post(
                f"{SERVER_URL}/esv/v1/login",
                json=[{"esvVersion": "1.0"}, {"password": "00000000"}],
                verify=CA_CERT,
                cert=(CLIENT_CERT, CLIENT_KEY),
                timeout=2,
            )
            ready = True
            break
        except Exception:
            time.sleep(0.5)
    if not ready:
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail("Server did not start within 20 seconds")
    yield proc
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    proc.wait(timeout=5)


def _get_jwt():
    """Obtain a valid JWT by logging in with the current TOTP."""
    import requests as req
    import pyotp
    seed = open(TOTP_SEED_FILE).read().strip()
    totp = pyotp.TOTP(seed, digits=8)
    password = totp.now()
    resp = req.post(
        f"{SERVER_URL}/esv/v1/login",
        json=[{"esvVersion": "1.0"}, {"password": password}],
        verify=CA_CERT,
        cert=(CLIENT_CERT, CLIENT_KEY),
        timeout=10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    return data[1]["accessToken"]


# ====================================================================
# mTLS Enforcement Tests
# ====================================================================

class TestMTLSEnforcement:
    """Verify the server enforces mutual TLS."""

    def test_accepts_valid_client_cert(self, running_server):
        import requests as req
        resp = req.post(
            f"{SERVER_URL}/esv/v1/login",
            json=[{"esvVersion": "1.0"}, {"password": "00000000"}],
            verify=CA_CERT,
            cert=(CLIENT_CERT, CLIENT_KEY),
            timeout=10,
        )
        # Server should respond (even if TOTP is invalid) — connection accepted
        assert resp.status_code in (200, 400, 403), f"Unexpected status: {resp.status_code}"

    def test_rejects_missing_client_cert(self, running_server):
        import requests as req
        with pytest.raises((req.exceptions.SSLError, req.exceptions.ConnectionError)):
            req.post(
                f"{SERVER_URL}/esv/v1/login",
                json=[{"esvVersion": "1.0"}, {"password": "00000000"}],
                verify=CA_CERT,
                timeout=5,
            )


# ====================================================================
# Login / TOTP / JWT Tests
# ====================================================================

class TestLoginAuthentication:
    """Verify TOTP login and JWT issuance."""

    def test_valid_totp_returns_jwt(self, running_server):
        import requests as req
        import pyotp
        seed = open(TOTP_SEED_FILE).read().strip()
        totp = pyotp.TOTP(seed, digits=8)
        password = totp.now()
        resp = req.post(
            f"{SERVER_URL}/esv/v1/login",
            json=[{"esvVersion": "1.0"}, {"password": password}],
            verify=CA_CERT,
            cert=(CLIENT_CERT, CLIENT_KEY),
            timeout=10,
        )
        assert resp.status_code == 200, f"Login failed with valid TOTP: {resp.text}"
        data = resp.json()
        assert isinstance(data, list) and len(data) >= 2
        assert "accessToken" in data[1]
        token = data[1]["accessToken"]
        assert len(token) > 20, "JWT token seems too short"

    def test_invalid_totp_rejected(self, running_server):
        import requests as req
        resp = req.post(
            f"{SERVER_URL}/esv/v1/login",
            json=[{"esvVersion": "1.0"}, {"password": "00000000"}],
            verify=CA_CERT,
            cert=(CLIENT_CERT, CLIENT_KEY),
            timeout=10,
        )
        assert resp.status_code == 403, f"Expected 403 for invalid TOTP, got {resp.status_code}"

    def test_jwt_contains_correct_sub_claim(self, running_server):
        import jwt as pyjwt
        import hashlib
        token = _get_jwt()
        # Derive the JWT secret the same way the server should
        ca_key_data = open(os.path.join(PKI_DIR, "ca.key")).read()
        secret = hashlib.sha256(ca_key_data.encode()).hexdigest()
        decoded = pyjwt.decode(token, secret, algorithms=["HS256"])
        assert decoded.get("sub") == "ESVTestClient", \
            f"JWT sub should be 'ESVTestClient', got '{decoded.get('sub')}'"


# ====================================================================
# Entropy Source Registration Validation Tests
# ====================================================================

VALID_VETTED_PAYLOAD = {
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
            "vetted": True,
            "description": "AES-CBC-MAC",
            "validationNumber": "A0000",
            "minNin": 128,
            "minHin": 4,
            "nw": 128,
            "nOut": 128,
            "hOut": 120
        }
    ]
}


class TestEntropyRegistration:
    """Verify payload validation through the server endpoint."""

    def _post_assessment(self, payload, token):
        import requests as req
        return req.post(
            f"{SERVER_URL}/esv/v1/entropyAssessments",
            json=[{"esvVersion": "1.0"}, payload],
            headers={"Authorization": f"Bearer {token}"},
            verify=CA_CERT,
            cert=(CLIENT_CERT, CLIENT_KEY),
            timeout=15,
        )

    def test_valid_payload_accepted(self, running_server):
        token = _get_jwt()
        resp = self._post_assessment(VALID_VETTED_PAYLOAD, token)
        assert resp.status_code == 200, \
            f"Valid payload should return 200, got {resp.status_code}: {resp.text}"

    def test_no_auth_header_rejected(self, running_server):
        import requests as req
        resp = req.post(
            f"{SERVER_URL}/esv/v1/entropyAssessments",
            json=[{"esvVersion": "1.0"}, VALID_VETTED_PAYLOAD],
            verify=CA_CERT,
            cert=(CLIENT_CERT, CLIENT_KEY),
            timeout=10,
        )
        assert resp.status_code == 401

    def test_invalid_jwt_rejected(self, running_server):
        import requests as req
        resp = req.post(
            f"{SERVER_URL}/esv/v1/entropyAssessments",
            json=[{"esvVersion": "1.0"}, VALID_VETTED_PAYLOAD],
            headers={"Authorization": "Bearer invalid.jwt.token"},
            verify=CA_CERT,
            cert=(CLIENT_CERT, CLIENT_KEY),
            timeout=10,
        )
        assert resp.status_code == 401

    def test_bps_out_of_range_rejected(self, running_server):
        token = _get_jwt()
        p = copy.deepcopy(VALID_VETTED_PAYLOAD)
        p["bitsPerSample"] = 0
        resp = self._post_assessment(p, token)
        assert resp.status_code == 400
        data = resp.json()
        assert data["valid"] is False

    def test_hmin_exceeds_bps_rejected(self, running_server):
        token = _get_jwt()
        p = copy.deepcopy(VALID_VETTED_PAYLOAD)
        p["hminEstimate"] = 5.0  # > bitsPerSample (4)
        resp = self._post_assessment(p, token)
        assert resp.status_code == 400
        data = resp.json()
        assert data["valid"] is False

    def test_vetted_cc_with_bijective_rejected(self, running_server):
        token = _get_jwt()
        p = copy.deepcopy(VALID_VETTED_PAYLOAD)
        p["conditioningComponent"][0]["bijectiveClaim"] = True
        resp = self._post_assessment(p, token)
        assert resp.status_code == 400
        data = resp.json()
        assert data["valid"] is False

    def test_missing_primary_noise_rejected(self, running_server):
        token = _get_jwt()
        p = copy.deepcopy(VALID_VETTED_PAYLOAD)
        del p["primaryNoiseSource"]
        resp = self._post_assessment(p, token)
        assert resp.status_code == 400
        data = resp.json()
        assert data["valid"] is False
