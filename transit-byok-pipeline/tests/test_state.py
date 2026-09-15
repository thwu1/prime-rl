
import json
import base64
import os
import subprocess
import time
import pytest
import requests

BAO_ADDR = "http://127.0.0.1:8200"


def get_init_data():
    with open("/app/state/init.json") as f:
        return json.load(f)


def get_root_token():
    return get_init_data()["root_token"]


def bao_api(method, path, data=None):
    headers = {"X-Vault-Token": get_root_token()}
    url = f"{BAO_ADDR}/v1/{path}"
    if method == "GET":
        r = requests.get(url, headers=headers)
    elif method == "POST":
        r = requests.post(url, headers=headers, json=data)
    elif method == "LIST":
        r = requests.request("LIST", url, headers=headers)
    else:
        raise ValueError(f"Unsupported method: {method}")
    return r


@pytest.fixture(scope="session", autouse=True)
def ensure_bao():
    if not os.path.exists("/app/state/init.json"):
        pytest.fail("OpenBao not initialized - /app/state/init.json missing")
    try:
        r = requests.get(f"{BAO_ADDR}/v1/sys/health", timeout=5)
        if r.status_code not in [200, 429, 472, 473]:
            pytest.fail(f"OpenBao unhealthy: status {r.status_code}")
    except requests.ConnectionError:
        pytest.fail("OpenBao not running")


# ---- Key existence and configuration tests ----

def test_transit_enabled():
    r = bao_api("GET", "sys/mounts")
    assert r.status_code == 200
    assert "transit/" in r.json()["data"]


def test_key_data_enc():
    r = bao_api("GET", "transit/keys/data-enc")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["type"] == "aes256-gcm96"
    assert data["derived"] is True
    assert data["latest_version"] == 4
    assert data["min_decryption_version"] == 3
    assert data["min_encryption_version"] == 4


def test_key_hmac_auth():
    r = bao_api("GET", "transit/keys/hmac-auth")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["type"] == "hmac"


def test_key_imported_rsa():
    """Verify RSA-4096 key was imported with exportable and allow_plaintext_backup flags."""
    r = bao_api("GET", "transit/keys/imported-rsa")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["type"] == "rsa-4096"
    assert data["exportable"] is True
    assert data["allow_plaintext_backup"] is True


def test_key_imported_ed25519():
    """Verify ed25519 key exists with correct type and is at version 1 (imported, not rotated)."""
    r = bao_api("GET", "transit/keys/imported-ed25519")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["type"] == "ed25519"
    assert data["latest_version"] == 1


# ---- Encrypted records tests ----

def test_encrypted_records_exist():
    assert os.path.exists("/app/output/encrypted_records.json")
    with open("/app/output/encrypted_records.json") as f:
        data = json.load(f)
    assert "records" in data
    assert len(data["records"]) == 5
    for record in data["records"]:
        assert "id" in record
        assert "ciphertext" in record
        assert record["ciphertext"].startswith("vault:v4:")


def test_encrypted_records_decrypt():
    with open("/app/output/encrypted_records.json") as f:
        enc_data = json.load(f)
    with open("/app/data/records.json") as f:
        orig_data = json.load(f)

    orig_map = {r["id"]: r["data"] for r in orig_data["records"]}

    for record in enc_data["records"]:
        context = base64.b64encode(record["id"].encode()).decode()
        r = bao_api("POST", "transit/decrypt/data-enc", {
            "ciphertext": record["ciphertext"],
            "context": context
        })
        assert r.status_code == 200, f"Decrypt failed for {record['id']}: {r.text}"
        plaintext = base64.b64decode(r.json()["data"]["plaintext"]).decode()
        assert plaintext == orig_map[record["id"]]


def test_convergent_same_context():
    """Same plaintext + same context should produce same ciphertext."""
    with open("/app/data/records.json") as f:
        orig_data = json.load(f)
    with open("/app/output/encrypted_records.json") as f:
        enc_data = json.load(f)

    rec1_data = next(r["data"] for r in orig_data["records"] if r["id"] == "rec-001")
    rec1_ct = next(r["ciphertext"] for r in enc_data["records"] if r["id"] == "rec-001")

    plaintext_b64 = base64.b64encode(rec1_data.encode()).decode()
    context = base64.b64encode(b"rec-001").decode()

    r = bao_api("POST", "transit/encrypt/data-enc", {
        "plaintext": plaintext_b64,
        "context": context
    })
    assert r.status_code == 200
    assert r.json()["data"]["ciphertext"] == rec1_ct


def test_convergent_different_context():
    """Same data but different context (different ID) should produce different ciphertext."""
    with open("/app/output/encrypted_records.json") as f:
        enc_data = json.load(f)

    rec1_ct = next(r["ciphertext"] for r in enc_data["records"] if r["id"] == "rec-001")
    rec5_ct = next(r["ciphertext"] for r in enc_data["records"] if r["id"] == "rec-005")
    # rec-001 and rec-005 have identical data but different IDs (contexts)
    assert rec1_ct != rec5_ct


# ---- Signature tests ----

def test_signatures_exist():
    assert os.path.exists("/app/output/signatures.json")
    with open("/app/output/signatures.json") as f:
        data = json.load(f)
    assert "signatures" in data
    assert len(data["signatures"]) == 5
    for sig in data["signatures"]:
        assert "id" in sig
        assert "signature" in sig
        assert sig["signature"].startswith("vault:v1:")


def test_signatures_verify():
    with open("/app/output/signatures.json") as f:
        sig_data = json.load(f)
    with open("/app/output/encrypted_records.json") as f:
        enc_data = json.load(f)

    enc_map = {r["id"]: r["ciphertext"] for r in enc_data["records"]}

    for sig_record in sig_data["signatures"]:
        ciphertext = enc_map[sig_record["id"]]
        input_b64 = base64.b64encode(ciphertext.encode()).decode()
        r = bao_api("POST", "transit/verify/imported-ed25519", {
            "input": input_b64,
            "signature": sig_record["signature"]
        })
        assert r.status_code == 200, f"Verify failed for {sig_record['id']}: {r.text}"
        assert r.json()["data"]["valid"] is True


# ---- HMAC tests ----

def test_hmacs_exist():
    assert os.path.exists("/app/output/hmacs.json")
    with open("/app/output/hmacs.json") as f:
        data = json.load(f)
    assert "hmacs" in data
    assert len(data["hmacs"]) == 5
    for hmac_entry in data["hmacs"]:
        assert "id" in hmac_entry
        assert "hmac" in hmac_entry
        assert hmac_entry["hmac"].startswith("vault:v1:")


def test_hmacs_verify():
    with open("/app/output/hmacs.json") as f:
        hmac_data = json.load(f)
    with open("/app/data/records.json") as f:
        orig_data = json.load(f)

    orig_map = {r["id"]: r["data"] for r in orig_data["records"]}

    for hmac_record in hmac_data["hmacs"]:
        input_b64 = base64.b64encode(orig_map[hmac_record["id"]].encode()).decode()
        r = bao_api("POST", "transit/verify/hmac-auth/sha2-512", {
            "input": input_b64,
            "hmac": hmac_record["hmac"]
        })
        assert r.status_code == 200, f"HMAC verify failed for {hmac_record['id']}: {r.text}"
        assert r.json()["data"]["valid"] is True


# ---- RSA public key test ----

def test_rsa_public_key():
    assert os.path.exists("/app/output/rsa_public_key.pem")
    with open("/app/output/rsa_public_key.pem") as f:
        pem = f.read().strip()
    assert "-----BEGIN PUBLIC KEY-----" in pem or "-----BEGIN RSA PUBLIC KEY-----" in pem
    assert "-----END PUBLIC KEY-----" in pem or "-----END RSA PUBLIC KEY-----" in pem
    pem_lines = [l for l in pem.split("\n") if not l.startswith("-----")]
    pem_b64 = "".join(pem_lines)
    raw_bytes = base64.b64decode(pem_b64)
    assert len(raw_bytes) > 500


# ---- Key status test ----

def test_key_status():
    assert os.path.exists("/app/output/key_status.json")
    with open("/app/output/key_status.json") as f:
        status = json.load(f)
    assert "keys" in status
    assert len(status["keys"]) == 4

    key_map = {k["name"]: k for k in status["keys"]}

    assert "data-enc" in key_map
    assert key_map["data-enc"]["type"] == "aes256-gcm96"
    assert key_map["data-enc"]["latest_version"] == 4
    assert key_map["data-enc"]["min_decryption_version"] == 3
    assert key_map["data-enc"]["min_encryption_version"] == 4
    assert key_map["data-enc"]["supports_encryption"] is True

    assert "hmac-auth" in key_map
    assert key_map["hmac-auth"]["type"] == "hmac"

    assert "imported-rsa" in key_map
    assert key_map["imported-rsa"]["exportable"] is True
    assert key_map["imported-rsa"]["allow_plaintext_backup"] is True
    assert key_map["imported-rsa"]["type"] == "rsa-4096"
    assert key_map["imported-rsa"]["supports_signing"] is True

    assert "imported-ed25519" in key_map
    assert key_map["imported-ed25519"]["type"] == "ed25519"
    assert key_map["imported-ed25519"]["supports_signing"] is True
