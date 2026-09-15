#!/usr/bin/env python3
"""
SMART Backend Services Authorization Server with FHIR Bulk Data Export.
Uses only stdlib + cryptography (no Flask, no PyJWT at runtime).
"""

import json
import os
import time
import uuid
import base64
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding, utils
from cryptography.hazmat.backends import default_backend


# ---------------------------------------------------------------------------
# Base64URL helpers
# ---------------------------------------------------------------------------

def b64url_encode(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def b64url_decode(s):
    if isinstance(s, bytes):
        s = s.decode('ascii')
    rem = len(s) % 4
    if rem:
        s += '=' * (4 - rem)
    return base64.urlsafe_b64decode(s)


# ---------------------------------------------------------------------------
# JWK → cryptography key helpers
# ---------------------------------------------------------------------------

def jwk_to_rsa_private(jwk):
    n = int.from_bytes(b64url_decode(jwk['n']), 'big')
    e = int.from_bytes(b64url_decode(jwk['e']), 'big')
    d = int.from_bytes(b64url_decode(jwk['d']), 'big')
    p = int.from_bytes(b64url_decode(jwk['p']), 'big')
    q = int.from_bytes(b64url_decode(jwk['q']), 'big')
    dp = int.from_bytes(b64url_decode(jwk['dp']), 'big')
    dq = int.from_bytes(b64url_decode(jwk['dq']), 'big')
    qi = int.from_bytes(b64url_decode(jwk['qi']), 'big')
    pub = rsa.RSAPublicNumbers(e, n)
    priv = rsa.RSAPrivateNumbers(p, q, d, dp, dq, qi, pub)
    return priv.private_key(default_backend())


def jwk_to_rsa_public(jwk):
    n = int.from_bytes(b64url_decode(jwk['n']), 'big')
    e = int.from_bytes(b64url_decode(jwk['e']), 'big')
    pub = rsa.RSAPublicNumbers(e, n)
    return pub.public_key(default_backend())


def jwk_to_ec_public(jwk):
    x = int.from_bytes(b64url_decode(jwk['x']), 'big')
    y = int.from_bytes(b64url_decode(jwk['y']), 'big')
    pub = ec.EllipticCurvePublicNumbers(x, y, ec.SECP384R1())
    return pub.public_key(default_backend())


# ---------------------------------------------------------------------------
# JWT helpers (pure stdlib + cryptography, no PyJWT)
# ---------------------------------------------------------------------------

def jwt_encode_rs256(payload_dict, rsa_priv_key, kid):
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    h = b64url_encode(json.dumps(header, separators=(',', ':')))
    p = b64url_encode(json.dumps(payload_dict, separators=(',', ':')))
    signing_input = f"{h}.{p}".encode('ascii')
    sig = rsa_priv_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{b64url_encode(sig)}"


def jwt_decode_parts(token):
    parts = token.split('.')
    if len(parts) != 3:
        raise ValueError("Invalid JWT")
    header = json.loads(b64url_decode(parts[0]))
    payload = json.loads(b64url_decode(parts[1]))
    return header, payload


def jwt_verify_es384(token, ec_pub_key):
    parts = token.split('.')
    signing_input = f"{parts[0]}.{parts[1]}".encode('ascii')
    sig_bytes = b64url_decode(parts[2])
    # ES384/P-384: r (48 bytes) || s (48 bytes)
    if len(sig_bytes) != 96:
        raise ValueError("Bad ES384 signature length")
    r = int.from_bytes(sig_bytes[:48], 'big')
    s = int.from_bytes(sig_bytes[48:], 'big')
    der_sig = utils.encode_dss_signature(r, s)
    ec_pub_key.verify(der_sig, signing_input, ec.ECDSA(hashes.SHA384()))


def jwt_verify_rs256(token, rsa_pub_key):
    parts = token.split('.')
    signing_input = f"{parts[0]}.{parts[1]}".encode('ascii')
    sig_bytes = b64url_decode(parts[2])
    rsa_pub_key.verify(sig_bytes, signing_input, padding.PKCS1v15(), hashes.SHA256())


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _load(path):
    with open(path) as f:
        return json.load(f)


INSTANCE_CONFIG     = _load('/app/config/instance.json')
SERVER_PRIVATE_JWK  = _load('/app/config/server_private_jwk.json')
SERVER_JWKS         = _load('/app/config/server_jwks.json')
REGISTERED_CLIENTS  = _load('/app/config/registered_clients.json')

INSTANCE_ID             = INSTANCE_CONFIG['instance_id']
TOKEN_ISSUER            = INSTANCE_CONFIG['token_issuer']
CUSTOM_HEADER           = INSTANCE_CONFIG['custom_header']
MAX_ASSERTION_LIFETIME  = INSTANCE_CONFIG['max_assertion_lifetime_sec']
ACCESS_TOKEN_LIFETIME   = INSTANCE_CONFIG['access_token_lifetime_sec']
TOKEN_ENDPOINT_URL      = REGISTERED_CLIENTS['token_endpoint']

# Pre-load crypto keys
SERVER_RSA_PRIVATE = jwk_to_rsa_private(SERVER_PRIVATE_JWK)
SERVER_RSA_PUBLICS = [jwk_to_rsa_public(k) for k in SERVER_JWKS['keys']]

CLIENT_EC_KEYS = {}
for _cid, _cdata in REGISTERED_CLIENTS['clients'].items():
    CLIENT_EC_KEYS[_cid] = [
        (k.get('kid'), jwk_to_ec_public(k)) for k in _cdata['jwks']['keys']
    ]


# ---------------------------------------------------------------------------
# FHIR resources (dynamic type discovery)
# ---------------------------------------------------------------------------

def _load_fhir():
    resources = {}
    base = '/app/data/fhir'
    for rtype in sorted(os.listdir(base)):
        rdir = os.path.join(base, rtype)
        if not os.path.isdir(rdir) or rtype == 'Group':
            continue
        items = []
        for fname in sorted(os.listdir(rdir)):
            if fname.endswith('.json'):
                with open(os.path.join(rdir, fname)) as f:
                    items.append(json.load(f))
        if items:
            resources[rtype] = items
    return resources


FHIR_RESOURCES = _load_fhir()


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_used_jtis = set()
_export_jobs = {}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress per-request logging

    # --- response helpers ---

    def _send_json(self, code, obj, extra=None):
        body = json.dumps(obj, separators=(',', ':')).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, code, extra=None):
        self.send_response(code)
        self.send_header('Content-Length', '0')
        if extra:
            for k, v in extra.items():
                self.send_header(k, str(v))
        self.end_headers()

    def _send_ndjson(self, code, text, extra=None):
        body = text.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/fhir+ndjson')
        self.send_header('Content-Length', str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    # --- auth helpers ---

    def _verify_bearer(self):
        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return None
        token = auth[7:]
        try:
            header, payload = jwt_decode_parts(token)
        except Exception:
            return None
        if header.get('alg') != 'RS256':
            return None
        for pub in SERVER_RSA_PUBLICS:
            try:
                jwt_verify_rs256(token, pub)
                if payload.get('exp', 0) <= time.time():
                    return None
                return payload
            except Exception:
                continue
        return None

    def _validate_client_jwt(self, token_str):
        try:
            header, payload = jwt_decode_parts(token_str)
        except Exception:
            return None, "Invalid JWT format"

        for claim in ('iss', 'sub', 'aud', 'exp', 'jti'):
            if claim not in payload:
                return None, f"Missing claim: {claim}"

        if payload['iss'] != payload['sub']:
            return None, "iss != sub"

        client_id = payload['iss']
        if client_id not in REGISTERED_CLIENTS['clients']:
            return None, "Unknown client"

        aud = payload['aud']
        if isinstance(aud, list):
            if TOKEN_ENDPOINT_URL not in aud:
                return None, "Bad audience"
        elif aud != TOKEN_ENDPOINT_URL:
            return None, "Bad audience"

        now = time.time()
        if payload['exp'] <= now:
            return None, "JWT expired"
        if payload['exp'] - now > MAX_ASSERTION_LIFETIME:
            return None, "exp exceeds max lifetime"

        with _lock:
            if payload['jti'] in _used_jtis:
                return None, "jti replay"

        verified = False
        kid = header.get('kid')
        for k_kid, k_pub in CLIENT_EC_KEYS.get(client_id, []):
            if kid is not None and k_kid != kid:
                continue
            try:
                jwt_verify_es384(token_str, k_pub)
                verified = True
                break
            except Exception:
                continue

        if not verified:
            return None, "Invalid signature"

        with _lock:
            _used_jtis.add(payload['jti'])

        return payload, None

    # --- body reading ---

    def _read_form(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')
        return parse_qs(body, keep_blank_values=True)

    # --- routing ---

    def do_GET(self):
        if self.path == '/.well-known/jwks.json':
            self._jwks()
        elif self.path.startswith('/fhir/bulk-status/'):
            self._export_status()
        elif self.path.startswith('/fhir/bulk-data/'):
            self._bulk_download()
        else:
            self._send_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == '/auth/token':
            self._token()
        elif self.path == '/fhir/Group/1/$export':
            self._export_kickoff()
        else:
            self._send_json(404, {"error": "not_found"})

    def do_DELETE(self):
        if self.path.startswith('/fhir/bulk-status/'):
            self._export_cancel()
        else:
            self._send_json(404, {"error": "not_found"})

    # --- endpoints ---

    def _jwks(self):
        self._send_json(200, SERVER_JWKS)

    def _token(self):
        params = self._read_form()
        gt = params.get('grant_type', [''])[0]
        at = params.get('client_assertion_type', [''])[0]
        assertion = params.get('client_assertion', [''])[0]
        scope_req = params.get('scope', [''])[0]

        if gt != 'client_credentials':
            self._send_json(400, {"error": "unsupported_grant_type"})
            return
        if at != 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer':
            self._send_json(400, {"error": "invalid_request",
                                  "error_description": "Bad assertion type"})
            return
        if not assertion:
            self._send_json(400, {"error": "invalid_request",
                                  "error_description": "Missing assertion"})
            return

        claims, err = self._validate_client_jwt(assertion)
        if err:
            self._send_json(401, {"error": "invalid_client",
                                  "error_description": err})
            return

        client_id = claims['iss']
        allowed = set(REGISTERED_CLIENTS['clients'][client_id].get('allowed_scopes', []))
        granted = set(scope_req.split()) & allowed if scope_req else allowed
        granted_scope = ' '.join(sorted(granted))

        now = int(time.time())
        token_payload = {
            'iss': TOKEN_ISSUER,
            'sub': client_id,
            'deployment_id': INSTANCE_ID,
            'scope': granted_scope,
            'exp': now + ACCESS_TOKEN_LIFETIME,
            'iat': now,
            'jti': str(uuid.uuid4()),
        }
        access_token = jwt_encode_rs256(token_payload, SERVER_RSA_PRIVATE,
                                        SERVER_PRIVATE_JWK['kid'])

        self._send_json(200, {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_LIFETIME,
            "scope": granted_scope,
        })

    def _export_kickoff(self):
        if self._verify_bearer() is None:
            self._send_json(401, {"error": "unauthorized"})
            return
        if 'respond-async' not in self.headers.get('Prefer', ''):
            self._send_json(400, {"error": "Prefer: respond-async required"})
            return

        job_id = str(uuid.uuid4())
        output_files = []
        file_store = {}

        for rtype, items in FHIR_RESOURCES.items():
            file_id = str(uuid.uuid4())
            ndjson = '\n'.join(json.dumps(r, separators=(',', ':')) for r in items) + '\n'
            output_files.append({
                'type': rtype,
                'url': f'http://localhost:8080/fhir/bulk-data/{file_id}',
                'file_id': file_id,
            })
            file_store[file_id] = ndjson

        with _lock:
            _export_jobs[job_id] = {
                'status': 'complete',
                'transactionTime': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'request': '/fhir/Group/1/$export',
                'output': output_files,
                'files': file_store,
            }

        self._send_empty(202, {
            'Content-Location': f'http://localhost:8080/fhir/bulk-status/{job_id}',
            CUSTOM_HEADER: INSTANCE_ID,
        })

    def _export_status(self):
        if self._verify_bearer() is None:
            self._send_json(401, {"error": "unauthorized"})
            return

        job_id = self.path.split('/fhir/bulk-status/')[-1]
        with _lock:
            job = _export_jobs.get(job_id)
        if job is None:
            self._send_json(404, {"error": "not_found"})
            return
        if job['status'] == 'cancelled':
            self._send_json(404, {"error": "Job cancelled"})
            return
        if job['status'] != 'complete':
            self._send_empty(202, {CUSTOM_HEADER: INSTANCE_ID})
            return

        manifest = {
            'transactionTime': job['transactionTime'],
            'request': job['request'],
            'requiresAccessToken': True,
            'output': [{'type': f['type'], 'url': f['url']} for f in job['output']],
            'error': [],
        }
        self._send_json(200, manifest, {CUSTOM_HEADER: INSTANCE_ID})

    def _export_cancel(self):
        if self._verify_bearer() is None:
            self._send_json(401, {"error": "unauthorized"})
            return

        job_id = self.path.split('/fhir/bulk-status/')[-1]
        with _lock:
            job = _export_jobs.get(job_id)
        if job is None:
            self._send_json(404, {"error": "not_found"})
            return
        job['status'] = 'cancelled'
        self._send_empty(202, {CUSTOM_HEADER: INSTANCE_ID})

    def _bulk_download(self):
        if self._verify_bearer() is None:
            self._send_json(401, {"error": "unauthorized"})
            return

        file_id = self.path.split('/fhir/bulk-data/')[-1]
        content = None
        with _lock:
            for job in _export_jobs.values():
                content = job.get('files', {}).get(file_id)
                if content is not None:
                    break

        if content is not None:
            self._send_ndjson(200, content, {CUSTOM_HEADER: INSTANCE_ID})
        else:
            self._send_json(404, {"error": "not_found"})


if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', 8080), Handler)
    print("Server listening on 0.0.0.0:8080", flush=True)
    server.serve_forever()
