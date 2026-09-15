"""
Tests for SMART Backend Services Authorization Server with FHIR Bulk Data Export.

Verifies JWT assertion validation, instance-specific deployment configuration (DNA),
access token claims, and the full FHIR Bulk Data Export lifecycle.
"""

import pytest
import requests
import json
import time
import uuid
import subprocess
import socket
import os
import signal
import base64
import jwt as pyjwt
from jwt import PyJWK

BASE_URL = "http://localhost:8080"
TOKEN_ENDPOINT = f"{BASE_URL}/auth/token"


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope='session')
def instance_config():
    with open('/app/config/instance.json') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def resource_manifest():
    with open('/app/config/resource_manifest.json') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def client_private_jwk():
    with open('/app/config/test_client_private_jwk.json') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def server_process():
    """Start the server via /app/start.sh and wait for port 8080."""
    assert os.path.exists('/app/start.sh'), \
        "/app/start.sh not found — did solve.sh run?"

    proc = subprocess.Popen(
        ['bash', '/app/start.sh'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        preexec_fn=os.setsid
    )

    ready = False
    for _ in range(45):
        if proc.poll() is not None:
            break
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('localhost', 8080))
            sock.close()
            if result == 0:
                ready = True
                break
        except Exception:
            pass
        time.sleep(1)

    if not ready:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass
        try:
            out, _ = proc.communicate(timeout=5)
            out_text = out.decode(errors='replace')[:3000] if out else "(empty)"
        except Exception:
            out_text = "(could not capture)"
        raise RuntimeError(
            f"Server did not start within 45s.\nOutput:\n{out_text}"
        )

    yield proc

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass


# ============================================================
# Helpers
# ============================================================

def create_jwt_token(private_jwk, claims, headers=None):
    jwk = PyJWK(private_jwk)
    alg = private_jwk.get('alg', 'ES384')
    hdr = {'kid': private_jwk.get('kid'), 'typ': 'JWT'}
    if headers:
        hdr.update(headers)
    return pyjwt.encode(claims, jwk.key, algorithm=alg, headers=hdr)


def create_valid_assertion(private_jwk, client_id="test-backend-service", jti=None):
    now = int(time.time())
    return create_jwt_token(private_jwk, {
        'iss': client_id, 'sub': client_id,
        'aud': TOKEN_ENDPOINT,
        'exp': now + 120,
        'jti': jti or str(uuid.uuid4()),
    })


def obtain_access_token(private_jwk,
                        scope="system/Patient.read system/Observation.read "
                              "system/Condition.read system/AllergyIntolerance.read"):
    assertion = create_valid_assertion(private_jwk)
    resp = requests.post(TOKEN_ENDPOINT, data={
        'grant_type': 'client_credentials',
        'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
        'client_assertion': assertion,
        'scope': scope,
    })
    assert resp.status_code in [200, 201], \
        f"Token request failed: {resp.status_code} {resp.text}"
    body = resp.json()
    assert 'access_token' in body
    return body['access_token']


def run_export(token):
    resp = requests.post(
        f"{BASE_URL}/fhir/Group/1/$export",
        headers={'Authorization': f'Bearer {token}', 'Prefer': 'respond-async'},
    )
    assert resp.status_code == 202
    status_url = resp.headers.get('Content-Location') or resp.headers.get('content-location')
    assert status_url

    for _ in range(30):
        sr = requests.get(status_url, headers={'Authorization': f'Bearer {token}'})
        if sr.status_code == 200:
            return sr.json(), status_url
        assert sr.status_code in [200, 202]
        time.sleep(1)
    raise TimeoutError("Export did not complete within 30s")


def generate_wrong_ec_key():
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP384R1())
    pub = key.public_key().public_numbers()
    priv = key.private_numbers()
    cs = 48
    return {
        "kty": "EC", "crv": "P-384", "kid": "test-client-key-1",
        "alg": "ES384",
        "x": base64.urlsafe_b64encode(pub.x.to_bytes(cs, 'big')).rstrip(b'=').decode(),
        "y": base64.urlsafe_b64encode(pub.y.to_bytes(cs, 'big')).rstrip(b'=').decode(),
        "d": base64.urlsafe_b64encode(priv.private_value.to_bytes(cs, 'big')).rstrip(b'=').decode(),
    }


# ============================================================
# JWKS Endpoint
# ============================================================

class TestJWKSEndpoint:
    def test_jwks_returns_valid_json(self, server_process):
        resp = requests.get(f"{BASE_URL}/.well-known/jwks.json")
        assert resp.status_code == 200
        assert 'keys' in resp.json()

    def test_jwks_key_has_required_fields(self, server_process):
        resp = requests.get(f"{BASE_URL}/.well-known/jwks.json")
        keys = resp.json()['keys']
        assert len(keys) >= 1
        key = keys[0]
        for f in ('kty', 'kid', 'alg'):
            assert f in key, f"JWK missing '{f}'"


# ============================================================
# Token Endpoint — Valid Requests
# ============================================================

class TestTokenValidRequest:
    def test_valid_jwt_returns_200(self, server_process, client_private_jwk):
        assertion = create_valid_assertion(client_private_jwk)
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
            'scope': 'system/Patient.read',
        })
        assert resp.status_code in [200, 201]

    def test_response_has_bearer_type(self, server_process, client_private_jwk):
        assertion = create_valid_assertion(client_private_jwk)
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
            'scope': 'system/Patient.read',
        })
        assert resp.json().get('token_type', '').lower() == 'bearer'

    def test_response_has_scope(self, server_process, client_private_jwk):
        assertion = create_valid_assertion(client_private_jwk)
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
            'scope': 'system/Patient.read',
        })
        assert 'scope' in resp.json()

    def test_expires_in_matches_instance_config(self, server_process, client_private_jwk,
                                                 instance_config):
        """DNA: expires_in must equal access_token_lifetime_sec from instance config."""
        assertion = create_valid_assertion(client_private_jwk)
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
            'scope': 'system/Patient.read',
        })
        body = resp.json()
        expected = instance_config['access_token_lifetime_sec']
        assert body.get('expires_in') == expected, \
            f"expires_in should be {expected} (from instance config), got {body.get('expires_in')}"


# ============================================================
# DNA: Instance-specific access token claims
# ============================================================

class TestTokenDNA:
    def test_access_token_contains_deployment_id(self, server_process, client_private_jwk,
                                                  instance_config):
        """DNA: Issued tokens must contain deployment_id matching instance_id."""
        token = obtain_access_token(client_private_jwk)
        claims = pyjwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        expected = instance_config['instance_id']
        assert claims.get('deployment_id') == expected, \
            f"Token must have deployment_id='{expected}', got '{claims.get('deployment_id')}'"

    def test_access_token_issuer_matches_config(self, server_process, client_private_jwk,
                                                 instance_config):
        """DNA: Token iss must equal token_issuer from instance config."""
        token = obtain_access_token(client_private_jwk)
        claims = pyjwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        expected = instance_config['token_issuer']
        assert claims.get('iss') == expected, \
            f"Token iss should be '{expected}', got '{claims.get('iss')}'"


# ============================================================
# Token Endpoint — Invalid Requests
# ============================================================

class TestTokenInvalidRequests:
    def test_invalid_grant_type_rejected(self, server_process, client_private_jwk):
        assertion = create_valid_assertion(client_private_jwk)
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'authorization_code',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
        })
        assert resp.status_code in [400, 401]

    def test_invalid_assertion_type_rejected(self, server_process, client_private_jwk):
        assertion = create_valid_assertion(client_private_jwk)
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'invalid-assertion-type',
            'client_assertion': assertion,
        })
        assert resp.status_code in [400, 401]

    def test_expired_jwt_rejected(self, server_process, client_private_jwk):
        now = int(time.time())
        assertion = create_jwt_token(client_private_jwk, {
            'iss': 'test-backend-service', 'sub': 'test-backend-service',
            'aud': TOKEN_ENDPOINT, 'exp': now - 60, 'jti': str(uuid.uuid4()),
        })
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
        })
        assert resp.status_code in [400, 401]

    def test_wrong_audience_rejected(self, server_process, client_private_jwk):
        now = int(time.time())
        assertion = create_jwt_token(client_private_jwk, {
            'iss': 'test-backend-service', 'sub': 'test-backend-service',
            'aud': 'http://wrong-server.example.com/token',
            'exp': now + 120, 'jti': str(uuid.uuid4()),
        })
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
        })
        assert resp.status_code in [400, 401]

    def test_invalid_signature_rejected(self, server_process, client_private_jwk):
        wrong_jwk = generate_wrong_ec_key()
        assertion = create_valid_assertion(wrong_jwk)
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
        })
        assert resp.status_code in [400, 401]

    def test_replayed_jti_rejected(self, server_process, client_private_jwk):
        shared_jti = f"replay-{uuid.uuid4()}"
        a1 = create_valid_assertion(client_private_jwk, jti=shared_jti)
        r1 = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': a1, 'scope': 'system/Patient.read',
        })
        assert r1.status_code in [200, 201]

        a2 = create_valid_assertion(client_private_jwk, jti=shared_jti)
        r2 = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': a2, 'scope': 'system/Patient.read',
        })
        assert r2.status_code in [400, 401]

    def test_mismatched_iss_sub_rejected(self, server_process, client_private_jwk):
        now = int(time.time())
        assertion = create_jwt_token(client_private_jwk, {
            'iss': 'test-backend-service', 'sub': 'other-client',
            'aud': TOKEN_ENDPOINT, 'exp': now + 120, 'jti': str(uuid.uuid4()),
        })
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
        })
        assert resp.status_code in [400, 401]

    def test_exp_exceeds_configured_max_lifetime(self, server_process, client_private_jwk,
                                                  instance_config):
        """DNA: JWT exp beyond max_assertion_lifetime_sec must be rejected.

        Uses the configured maximum (not a hardcoded 300s) so this test fails
        against servers that ignore instance config.
        """
        now = int(time.time())
        max_lt = instance_config['max_assertion_lifetime_sec']
        assertion = create_jwt_token(client_private_jwk, {
            'iss': 'test-backend-service', 'sub': 'test-backend-service',
            'aud': TOKEN_ENDPOINT,
            'exp': now + max_lt + 60,
            'jti': str(uuid.uuid4()),
        })
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
        })
        assert resp.status_code in [400, 401], \
            f"JWT with exp {max_lt + 60}s in future should be rejected (config max={max_lt}s)"

    def test_missing_jti_rejected(self, server_process, client_private_jwk):
        now = int(time.time())
        assertion = create_jwt_token(client_private_jwk, {
            'iss': 'test-backend-service', 'sub': 'test-backend-service',
            'aud': TOKEN_ENDPOINT, 'exp': now + 120,
        })
        resp = requests.post(TOKEN_ENDPOINT, data={
            'grant_type': 'client_credentials',
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': assertion,
        })
        assert resp.status_code in [400, 401]


# ============================================================
# Bulk Data Export
# ============================================================

class TestBulkDataExport:
    def test_export_without_token_401(self, server_process):
        resp = requests.post(
            f"{BASE_URL}/fhir/Group/1/$export",
            headers={'Prefer': 'respond-async'},
        )
        assert resp.status_code == 401

    def test_export_kickoff_returns_202(self, server_process, client_private_jwk):
        token = obtain_access_token(client_private_jwk)
        resp = requests.post(
            f"{BASE_URL}/fhir/Group/1/$export",
            headers={'Authorization': f'Bearer {token}', 'Prefer': 'respond-async'},
        )
        assert resp.status_code == 202

    def test_export_kickoff_has_content_location(self, server_process, client_private_jwk):
        token = obtain_access_token(client_private_jwk)
        resp = requests.post(
            f"{BASE_URL}/fhir/Group/1/$export",
            headers={'Authorization': f'Bearer {token}', 'Prefer': 'respond-async'},
        )
        loc = resp.headers.get('Content-Location') or resp.headers.get('content-location')
        assert loc and len(loc) > 0

    def test_export_kickoff_custom_header(self, server_process, client_private_jwk,
                                          instance_config):
        """DNA: Export response must carry the instance-specific custom header."""
        token = obtain_access_token(client_private_jwk)
        resp = requests.post(
            f"{BASE_URL}/fhir/Group/1/$export",
            headers={'Authorization': f'Bearer {token}', 'Prefer': 'respond-async'},
        )
        header_name = instance_config['custom_header']
        header_val = resp.headers.get(header_name)
        assert header_val == instance_config['instance_id'], \
            f"Expected header {header_name}='{instance_config['instance_id']}', got '{header_val}'"

    def test_manifest_structure(self, server_process, client_private_jwk):
        token = obtain_access_token(client_private_jwk)
        manifest, _ = run_export(token)
        assert 'transactionTime' in manifest
        assert 'output' in manifest
        assert 'requiresAccessToken' in manifest
        for entry in manifest['output']:
            assert 'type' in entry
            assert 'url' in entry

    def test_export_contains_all_resource_types(self, server_process, client_private_jwk):
        """DNA: Export must include AllergyIntolerance alongside standard types."""
        token = obtain_access_token(client_private_jwk)
        manifest, _ = run_export(token)
        types = {e['type'] for e in manifest['output']}
        for rt in ('Patient', 'Observation', 'Condition', 'AllergyIntolerance'):
            assert rt in types, f"Expected {rt} in export types, got {types}"

    def test_ndjson_resource_ids_match_manifest(self, server_process, client_private_jwk,
                                                 resource_manifest):
        """DNA: Exported resource IDs must exactly match the instance-generated manifest."""
        token = obtain_access_token(client_private_jwk)
        manifest, _ = run_export(token)

        exported_ids = {}
        for entry in manifest['output']:
            resp = requests.get(entry['url'], headers={'Authorization': f'Bearer {token}'})
            assert resp.status_code == 200
            lines = [l for l in resp.text.strip().split('\n') if l.strip()]
            exported_ids[entry['type']] = set()
            for line in lines:
                resource = json.loads(line)
                assert resource['resourceType'] == entry['type']
                assert 'id' in resource
                exported_ids[entry['type']].add(resource['id'])

        for rtype in ('Patient', 'Observation', 'Condition', 'AllergyIntolerance'):
            expected = set(resource_manifest[rtype])
            actual = exported_ids.get(rtype, set())
            assert actual == expected, \
                f"{rtype} IDs mismatch: expected {expected}, got {actual}"

    def test_ndjson_total_resource_count(self, server_process, client_private_jwk,
                                         resource_manifest):
        """DNA: Total exported resources must match the instance manifest count."""
        token = obtain_access_token(client_private_jwk)
        manifest, _ = run_export(token)
        total = 0
        for entry in manifest['output']:
            resp = requests.get(entry['url'], headers={'Authorization': f'Bearer {token}'})
            lines = [l for l in resp.text.strip().split('\n') if l.strip()]
            total += len(lines)
        expected = resource_manifest['total_resources']
        assert total == expected, f"Expected {expected} total resources, got {total}"

    def test_ndjson_download_requires_auth(self, server_process, client_private_jwk):
        token = obtain_access_token(client_private_jwk)
        manifest, _ = run_export(token)
        for entry in manifest['output']:
            resp = requests.get(entry['url'])
            assert resp.status_code == 401

    def test_export_cancel_returns_202(self, server_process, client_private_jwk):
        token = obtain_access_token(client_private_jwk)
        resp = requests.post(
            f"{BASE_URL}/fhir/Group/1/$export",
            headers={'Authorization': f'Bearer {token}', 'Prefer': 'respond-async'},
        )
        status_url = resp.headers.get('Content-Location') or resp.headers.get('content-location')
        cancel = requests.delete(status_url, headers={'Authorization': f'Bearer {token}'})
        assert cancel.status_code == 202

    def test_status_without_token_401(self, server_process, client_private_jwk):
        token = obtain_access_token(client_private_jwk)
        resp = requests.post(
            f"{BASE_URL}/fhir/Group/1/$export",
            headers={'Authorization': f'Bearer {token}', 'Prefer': 'respond-async'},
        )
        status_url = resp.headers.get('Content-Location') or resp.headers.get('content-location')
        assert requests.get(status_url).status_code == 401
