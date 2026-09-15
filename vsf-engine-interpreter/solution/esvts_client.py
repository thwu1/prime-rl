#!/usr/bin/env python3

"""
ESVTS Protocol Client

Demonstrates the full login -> register -> status-check flow over mTLS.
"""

import json
import ssl
import sys
import urllib.request

sys.path.insert(0, "/app")
from esvts_auth import generate_totp, create_jwt

PKI_DIR = "/app/pki"
BASE_URL = "https://localhost:7443"
TOTP_SEED = bytes.fromhex(open("/app/totp_seed.txt").read().strip())
JWT_SECRET = open("/app/jwt_secret.txt").read().strip()


def _make_ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_cert_chain(f"{PKI_DIR}/client.crt", f"{PKI_DIR}/client.key")
    ctx.load_verify_locations(f"{PKI_DIR}/ca.crt")
    return ctx


def _post(path, data, token=None):
    ctx = _make_ssl_context()
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read())


def _get(path, token):
    ctx = _make_ssl_context()
    req = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read())


def main():
    # Step 1: Login with TOTP
    totp_code = generate_totp(TOTP_SEED)
    print(f"[1] Logging in with TOTP code: {totp_code}")
    login_resp = _post("/esv/v1/login", [
        {"esvVersion": "1.0"},
        {"password": totp_code},
    ])
    session_jwt = login_resp[1]["accessToken"]
    print(f"    Session JWT received: {session_jwt[:40]}...")

    # Step 2: Register entropy source
    print("[2] Registering entropy source")
    reg_resp = _post("/esv/v1/entropyAssessments", [
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
    ], token=session_jwt)
    ea = reg_resp[1][0]
    ea_url = ea["url"]
    ea_jwt = ea["accessToken"]
    print(f"    Assessment URL: {ea_url}")
    print(f"    Data file URLs: {json.dumps(ea['dataFileUrls'], indent=4)}")

    # Step 3: Get status
    print(f"[3] Getting status for {ea_url}")
    status_resp = _get(ea_url, token=session_jwt)
    print(f"    Status: {json.dumps(status_resp[1], indent=4)}")

    print("\nProtocol flow completed successfully.")


if __name__ == "__main__":
    main()
