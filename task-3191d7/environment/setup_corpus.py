#!/usr/bin/env python3
"""Generate the NexAuth secret scanning corpus.

Sets up /app/codebase/ as a git repository with NexAuth tokens hidden
across source files, encoded blobs, version control history/features,
encrypted files, unusual archive formats, and hex dumps.

NO ground truth is written to the image.

"""

import json
import os
import random
import zlib
import base64
import hashlib
import subprocess
import sqlite3
import tarfile
import zipfile
import bz2
import io
import tempfile

SEED = 73219486
random.seed(SEED)

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

TOKEN_DEFS = {
    "nxa": {"prefix": "nxa_", "payload_len": 30, "cksum_input": "full_prefix",
            "complement": False},
    "nxs": {"prefix": "nxs_", "payload_len": 30, "cksum_input": "prefix_letters",
            "complement": False},
    "nxr": {"prefix": "nxr_", "payload_len": 36, "cksum_input": "full_prefix",
            "complement": False},
    "nxd": {"prefix": "nxd_", "payload_len": 30, "cksum_input": "payload_only",
            "complement": False},
    "nxi": {"prefix": "nxi_", "payload_len": 30, "cksum_input": "full_prefix",
            "complement": True},
}


def b62enc(n, width=6):
    if n == 0:
        return BASE62[0] * width
    d = []
    while n:
        d.append(BASE62[n % 62])
        n //= 62
    d.reverse()
    return "".join(d).rjust(width, BASE62[0])


def rand_payload(length):
    return "".join(random.choice(BASE62) for _ in range(length))


def crc_for(ttype, prefix, payload):
    td = TOKEN_DEFS[ttype]
    ci = td["cksum_input"]
    if ci == "full_prefix":
        data = prefix + payload
    elif ci == "prefix_letters":
        data = prefix.rstrip("_") + payload
    elif ci == "payload_only":
        data = payload
    c = zlib.crc32(data.encode()) & 0xFFFFFFFF
    if td["complement"]:
        c = (~c) & 0xFFFFFFFF
    return c


def mk_token(ttype, valid=True):
    td = TOKEN_DEFS[ttype]
    payload = rand_payload(td["payload_len"])
    c = crc_for(ttype, td["prefix"], payload)
    cksum = b62enc(c)
    tok = td["prefix"] + payload + cksum
    if not valid:
        i = BASE62.index(tok[-1])
        tok = tok[:-1] + BASE62[(i + 7) % 62]
    return tok


# Generate tokens: 10 valid + 3 invalid per type = 65 total
tokens = []
for ttype in sorted(TOKEN_DEFS.keys()):
    for _ in range(10):
        tokens.append({"token": mk_token(ttype), "type": ttype, "valid": True})
    for _ in range(3):
        tokens.append({"token": mk_token(ttype, valid=False), "type": ttype,
                        "valid": False})

random.shuffle(tokens)

# Directory structure
CB = "/app/codebase"
for d in ["src", "config", "logs", "deploy", "scripts", "data", "backups"]:
    os.makedirs(f"{CB}/{d}", exist_ok=True)

token_idx = 0


def use_token():
    global token_idx
    t = tokens[token_idx]
    token_idx += 1
    return t


# Git helpers
subprocess.run(["git", "config", "--global", "init.defaultBranch", "main"],
               check=True, capture_output=True)
subprocess.run(["git", "init", CB], check=True, capture_output=True)
subprocess.run(["git", "-C", CB, "config", "user.email", "dev@example.com"],
               check=True, capture_output=True)
subprocess.run(["git", "-C", CB, "config", "user.name", "Developer"],
               check=True, capture_output=True)


def git_commit(message, date):
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "Developer",
           "GIT_AUTHOR_EMAIL": "dev@example.com",
           "GIT_COMMITTER_NAME": "Developer",
           "GIT_COMMITTER_EMAIL": "dev@example.com",
           "GIT_AUTHOR_DATE": date,
           "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-C", CB, "add", "-A"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", CB, "commit", "-m", message,
                    "--allow-empty"],
                   check=True, capture_output=True, env=env)


def get_head_sha():
    r = subprocess.run(["git", "-C", CB, "rev-parse", "HEAD"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


# ==================================================================
# PHASE 1: Files committed then deleted — only in git history
# (6 tokens, indices 0-5)
# ==================================================================

for i in range(3):
    t1, t2 = use_token(), use_token()
    content = (
        f"# Production secrets - environment {i}\n"
        f"DATABASE_URL=postgres://admin:s3cur3@db.prod:5432/main\n"
        f"NEXAUTH_API_KEY={t1['token']}\n"
        f"NEXAUTH_SERVICE_TOKEN={t2['token']}\n"
        f"REDIS_URL=redis://cache.prod:6379/0\n"
    )
    with open(f"{CB}/config/production_secrets_{i}.env", "w") as fh:
        fh.write(content)

with open(f"{CB}/README.md", "w") as fh:
    fh.write("# NexAuth Service\n\nInternal microservice configuration.\n")

git_commit("Initial project setup with configuration",
           "2024-03-15T10:00:00+00:00")
commit1_sha = get_head_sha()

# Delete sensitive files
for i in range(3):
    os.remove(f"{CB}/config/production_secrets_{i}.env")

git_commit("Remove hardcoded credentials per security review",
           "2024-03-16T09:00:00+00:00")

# ==================================================================
# PHASE 2: Plain text source files (14 tokens, indices 6-19)
# ==================================================================

# Python config files (6 tokens, 6-11)
for i in range(3):
    t1, t2 = use_token(), use_token()
    content = (
        f'"""Service configuration module {i}."""\n'
        f"import os\n\n"
        f"class ServiceConfig{i}:\n"
        f'    API_ENDPOINT = "https://api.nexauth.example.com/v2"\n'
        f'    API_KEY = "{t1["token"]}"\n'
        f'    SERVICE_TOKEN = "{t2["token"]}"\n'
        f"    RETRY_COUNT = 3\n"
        f"    TIMEOUT_MS = 5000\n\n"
        f"    @classmethod\n"
        f"    def get_headers(cls):\n"
        f'        return {{"Authorization": f"Bearer {{cls.API_KEY}}"}}\n'
    )
    with open(f"{CB}/src/service_config_{i}.py", "w") as fh:
        fh.write(content)

# JavaScript files (4 tokens, 12-15)
for i in range(2):
    t1, t2 = use_token(), use_token()
    content = (
        f"// API client configuration\n"
        f"const config = {{\n"
        f'  apiKey: "{t1["token"]}",\n'
        f'  deployKey: "{t2["token"]}",\n'
        f'  baseUrl: "https://api.nexauth.example.com",\n'
        f"  timeout: 30000,\n"
        f"}};\n\n"
        f"module.exports = config;\n"
    )
    with open(f"{CB}/src/api_client_{i}.js", "w") as fh:
        fh.write(content)

# YAML config (2 tokens, 16-17)
t1, t2 = use_token(), use_token()
content = (
    f"app:\n"
    f"  name: primary-service\n"
    f'  version: "2.1.0"\n\n'
    f"auth:\n"
    f"  provider: nexauth\n"
    f'  api_key: "{t1["token"]}"\n'
    f'  service_token: "{t2["token"]}"\n\n'
    f"database:\n"
    f"  host: db.internal.example.com\n"
    f"  port: 5432\n"
)
with open(f"{CB}/config/app_primary.yml", "w") as fh:
    fh.write(content)

# Shell script (2 tokens, 18-19)
t1, t2 = use_token(), use_token()
content = (
    f"#!/bin/bash\n"
    f"set -euo pipefail\n\n"
    f'NEXAUTH_KEY="{t1["token"]}"\n'
    f'DEPLOY_TOKEN="{t2["token"]}"\n\n'
    f'echo "Deploying with NexAuth credentials..."\n'
    f'curl -H "Authorization: Bearer $NEXAUTH_KEY" \\\n'
    f"     https://deploy.example.com/api/v2/deploy\n"
)
with open(f"{CB}/scripts/deploy.sh", "w") as fh:
    fh.write(content)

# ==================================================================
# PHASE 3: Base64 encoded (5 tokens, indices 20-24)
# ==================================================================

# Kubernetes Secret manifest (2 tokens, 20-21)
t1, t2 = use_token(), use_token()
b64_t1 = base64.b64encode(t1["token"].encode()).decode()
b64_t2 = base64.b64encode(t2["token"].encode()).decode()
content = (
    f"apiVersion: v1\n"
    f"kind: Secret\n"
    f"metadata:\n"
    f"  name: nexauth-credentials\n"
    f"  namespace: production\n"
    f"type: Opaque\n"
    f"data:\n"
    f"  api-key: {b64_t1}\n"
    f"  service-token: {b64_t2}\n"
)
with open(f"{CB}/deploy/k8s_secret.yaml", "w") as fh:
    fh.write(content)

# Base64 JSON blob (3 tokens, 22-24)
t1, t2, t3 = use_token(), use_token(), use_token()
inner_json = json.dumps({
    "auth": {"api_key": t1["token"], "refresh_token": t2["token"]},
    "deploy": {"key": t3["token"]},
    "version": "3.0",
})
b64_blob = base64.b64encode(inner_json.encode()).decode()
content = (
    f"# Encoded configuration blob\n"
    f"# Generated by deploy pipeline\n"
    f"CONFIG_BLOB={b64_blob}\n"
)
with open(f"{CB}/config/encoded_config.sh", "w") as fh:
    fh.write(content)

# ==================================================================
# PHASE 4: JWT payload (2 tokens, indices 25-26)
# ==================================================================

t1, t2 = use_token(), use_token()
jwt_header = base64.urlsafe_b64encode(
    json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
).decode().rstrip("=")
jwt_payload_data = {
    "sub": "service-account-42",
    "iss": "nexauth.example.com",
    "iat": 1700000000,
    "exp": 1700086400,
    "nexauth_api_key": t1["token"],
    "nexauth_deploy_key": t2["token"],
    "scope": "read:api write:deploy",
}
jwt_payload = base64.urlsafe_b64encode(
    json.dumps(jwt_payload_data).encode()
).decode().rstrip("=")
jwt_sig = base64.urlsafe_b64encode(
    hashlib.sha256(f"{jwt_header}.{jwt_payload}".encode()).digest()
).decode().rstrip("=")
jwt_full = f"{jwt_header}.{jwt_payload}.{jwt_sig}"
content = (
    f"const jwt = require('jsonwebtoken');\n\n"
    f"// Cached service JWT for internal API calls\n"
    f'const SERVICE_JWT = "{jwt_full}";\n\n'
    f"module.exports = {{ getAuth: () => SERVICE_JWT }};\n"
)
with open(f"{CB}/src/jwt_auth.js", "w") as fh:
    fh.write(content)

# ==================================================================
# PHASE 5: Tokens in log files (4 tokens, indices 27-30)
# ==================================================================

for i in range(2):
    t1, t2 = use_token(), use_token()
    content = (
        f"2024-03-15T10:23:45Z INFO  [http] GET /api/v2/repos?"
        f"auth_token={t1['token']}&page=1 200 45ms\n"
        f"2024-03-15T10:23:46Z INFO  [http] POST /api/v2/deploy?"
        f"token={t2['token']}&env=prod 201 123ms\n"
        f"2024-03-15T10:23:47Z WARN  [auth] Rate limit approaching "
        f"for service-{i}\n"
        f"2024-03-15T10:23:48Z INFO  [http] GET /health 200 2ms\n"
        f"2024-03-15T10:23:49Z DEBUG [db] Connection pool: 15/50 active\n"
    )
    with open(f"{CB}/logs/access_{i}.log", "w") as fh:
        fh.write(content)

# ==================================================================
# PHASE 6: Python string concatenation (2 tokens, indices 31-32)
# ==================================================================

t1, t2 = use_token(), use_token()
tok1_a, tok1_b = t1["token"][:18], t1["token"][18:]
tok2_a, tok2_b, tok2_c = (t2["token"][:12], t2["token"][12:28],
                           t2["token"][28:])
content = (
    f'"""Token management utilities."""\n\n'
    f"# Long tokens split for line length compliance\n"
    f"PRIMARY_TOKEN = (\n"
    f'    "{tok1_a}"\n'
    f'    "{tok1_b}"\n'
    f")\n\n"
    f"SECONDARY_TOKEN = (\n"
    f'    "{tok2_a}"\n'
    f'    "{tok2_b}"\n'
    f'    "{tok2_c}"\n'
    f")\n\n"
    f"def get_active_tokens():\n"
    f"    return [PRIMARY_TOKEN, SECONDARY_TOKEN]\n"
)
with open(f"{CB}/src/token_manager.py", "w") as fh:
    fh.write(content)

# ==================================================================
# PHASE 7: Hex encoded (2 tokens, indices 33-34)
# ==================================================================

t1, t2 = use_token(), use_token()
hex_t1 = t1["token"].encode().hex()
hex_t2 = t2["token"].encode().hex()
content = (
    f"# Security configuration\n"
    f"# Tokens stored in hex encoding for additional obfuscation\n"
    f"# Decode with: echo '<hex>' | xxd -r -p\n\n"
    f"[credentials]\n"
    f"# Primary API key (hex encoded)\n"
    f"api_key_hex = {hex_t1}\n\n"
    f"# Service token (hex encoded)\n"
    f"service_token_hex = {hex_t2}\n\n"
    f"[settings]\n"
    f"rotation_days = 90\n"
    f"audit_log = true\n"
)
with open(f"{CB}/config/security.conf", "w") as fh:
    fh.write(content)

# ==================================================================
# PHASE 8: JSON unicode escapes (2 tokens, indices 35-36)
# ==================================================================

t1, t2 = use_token(), use_token()
prefix_chars = t1["token"][:3]
escaped_prefix = "".join(f"\\u{ord(c):04x}" for c in prefix_chars)
esc_t1 = escaped_prefix + t1["token"][3:]
content = (
    f'{{\n'
    f'  "app_name": "nexauth-service",\n'
    f'  "version": "4.2.1",\n'
    f'  "credentials": {{\n'
    f'    "primary_key": "{esc_t1}",\n'
    f'    "backup_key": "{t2["token"]}"\n'
    f'  }},\n'
    f'  "settings": {{\n'
    f'    "timeout": 30,\n'
    f'    "retries": 3\n'
    f'  }}\n'
    f'}}\n'
)
with open(f"{CB}/config/credentials.json", "w") as fh:
    fh.write(content)

# ==================================================================
# PHASE 9: Double base64 (1 token, index 37)
# ==================================================================

t1 = use_token()
inner_b64 = base64.b64encode(t1["token"].encode()).decode()
outer_b64 = base64.b64encode(inner_b64.encode()).decode()
content = (
    f"# Encrypted credentials store\n"
    f"# Layer 1: base64, Layer 2: base64\n"
    f"# Decode: cat <file> | base64 -d | base64 -d\n"
    f"ENCRYPTED_CRED={outer_b64}\n"
)
with open(f"{CB}/config/encrypted_creds.dat", "w") as fh:
    fh.write(content)

# ==================================================================
# PHASE 10: SQLite database (6 tokens, indices 38-43)
# ==================================================================

db_path = f"{CB}/data/service_registry.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("""
    CREATE TABLE services (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        api_key TEXT,
        deploy_token TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT
    )
""")
cur.execute("""
    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY,
        service_id INTEGER,
        action TEXT,
        timestamp TEXT,
        details TEXT
    )
""")

for i in range(3):
    t1, t2 = use_token(), use_token()
    cur.execute(
        "INSERT INTO services (name, api_key, deploy_token, status, "
        "created_at) VALUES (?, ?, ?, ?, ?)",
        (f"service-{i}", t1["token"], t2["token"], "active",
         f"2024-0{i+1}-15")
    )
    cur.execute(
        "INSERT INTO audit_log (service_id, action, timestamp, details) "
        "VALUES (?, ?, ?, ?)",
        (i + 1, "key_rotation", f"2024-0{i+1}-20T10:00:00Z",
         f"Rotated API key for service-{i}")
    )

# Decoy rows
cur.execute(
    "INSERT INTO services (name, api_key, deploy_token, status) "
    "VALUES (?, ?, ?, ?)",
    ("legacy-service", "sk_test_not_a_nexauth_token_12345",
     "dp_fake_67890", "deprecated")
)
cur.execute(
    "INSERT INTO services (name, api_key, deploy_token, status) "
    "VALUES (?, ?, ?, ?)",
    ("retired-svc", "ghp_notarealtoken1234567890abcdef",
     "ghs_faketoken98765", "retired")
)

conn.commit()
conn.close()

# ==================================================================
# PHASE 11: Compressed archives (6 tokens, indices 44-49)
# ==================================================================

# tar.gz archive (4 tokens, 44-47)
tar_path = f"{CB}/backups/config_backup_20240301.tar.gz"
with tarfile.open(tar_path, "w:gz") as tar:
    for i in range(2):
        t1, t2 = use_token(), use_token()
        file_content = (
            f"# Backup configuration {i}\n"
            f"NEXAUTH_API_KEY={t1['token']}\n"
            f"NEXAUTH_DEPLOY_KEY={t2['token']}\n"
            f"APP_PORT=808{i}\n"
        ).encode()
        info = tarfile.TarInfo(name=f"configs/env_{i}.conf")
        info.size = len(file_content)
        tar.addfile(info, io.BytesIO(file_content))

# zip archive (2 tokens, 48-49)
t1, t2 = use_token(), use_token()
zip_path = f"{CB}/backups/deploy_secrets.zip"
with zipfile.ZipFile(zip_path, "w") as zf:
    zip_content = (
        f"[nexauth]\n"
        f"primary_key = {t1['token']}\n"
        f"secondary_key = {t2['token']}\n"
    )
    zf.writestr("secrets/nexauth.ini", zip_content)

# ==================================================================
# PHASE 12: OpenSSL encrypted file (2 tokens, indices 50-51)
# ==================================================================

t1, t2 = use_token(), use_token()
vault_passphrase = "nexauth-vault-kdf-2024-prod"

with open(f"{CB}/config/.vault_passphrase", "w") as fh:
    fh.write(vault_passphrase)

plaintext = (
    f"# NexAuth Sealed Credential Vault\n"
    f"# Generated: 2024-03-10\n"
    f"NEXAUTH_MASTER_KEY={t1['token']}\n"
    f"NEXAUTH_ROTATION_KEY={t2['token']}\n"
    f"VAULT_VERSION=2\n"
)

subprocess.run(
    ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt",
     "-pass", f"pass:{vault_passphrase}",
     "-out", f"{CB}/config/sealed_creds.enc"],
    input=plaintext.encode(), check=True, capture_output=True
)

# Makefile that documents the encryption scheme
with open(f"{CB}/Makefile", "w") as fh:
    fh.write(
        ".PHONY: seal-creds unseal-creds\n\n"
        "seal-creds:\n"
        "\t@openssl enc -aes-256-cbc -pbkdf2 -salt \\\n"
        "\t\t-pass file:config/.vault_passphrase \\\n"
        "\t\t-in config/raw_creds.txt \\\n"
        "\t\t-out config/sealed_creds.enc\n"
        "\t@rm -f config/raw_creds.txt\n"
        "\t@echo 'Credentials sealed.'\n\n"
        "unseal-creds:\n"
        "\t@openssl enc -d -aes-256-cbc -pbkdf2 \\\n"
        "\t\t-pass file:config/.vault_passphrase \\\n"
        "\t\t-in config/sealed_creds.enc\n"
    )

# ==================================================================
# PHASE 13: Git stash — consume tokens now, stash after commit
# (2 tokens, indices 52-53)
# ==================================================================

stash_t1, stash_t2 = use_token(), use_token()

# ==================================================================
# PHASE 14: cpio.bz2 archive (2 tokens, indices 54-55)
# ==================================================================

t1, t2 = use_token(), use_token()
cpio_content = (
    f"# Legacy migration credentials\n"
    f"LEGACY_API_KEY={t1['token']}\n"
    f"LEGACY_DEPLOY_TOKEN={t2['token']}\n"
    f"MIGRATED_FROM=nexauth-v1\n"
)

with tempfile.TemporaryDirectory() as tmpdir:
    cpio_file = os.path.join(tmpdir, "legacy_creds.conf")
    with open(cpio_file, "w") as fh:
        fh.write(cpio_content)

    cpio_result = subprocess.run(
        ["bash", "-c",
         f"cd {tmpdir} && echo legacy_creds.conf | cpio -o --quiet"],
        capture_output=True, check=True
    )
    compressed = bz2.compress(cpio_result.stdout)
    with open(f"{CB}/backups/legacy_config.cpio.bz2", "wb") as fh:
        fh.write(compressed)

# ==================================================================
# PHASE 15: xxd hex dump (2 tokens, indices 56-57)
# ==================================================================

t1, t2 = use_token(), use_token()
xxd_source = (
    f"# Memory snapshot - auth module heap dump\n"
    f"HEAP_API_KEY={t1['token']}\n"
    f"HEAP_SERVICE_TOKEN={t2['token']}\n"
    f"HEAP_TIMESTAMP=1710504000\n"
)

xxd_result = subprocess.run(
    ["xxd"], input=xxd_source.encode(),
    capture_output=True, check=True
)
with open(f"{CB}/data/memory_dump.hex", "wb") as fh:
    fh.write(xxd_result.stdout)

# ==================================================================
# PHASE 16: Git notes — consume tokens now, add after commit
# (2 tokens, indices 58-59)
# ==================================================================

notes_t1, notes_t2 = use_token(), use_token()

# ==================================================================
# PHASE 17: Additional plain text files (5 tokens, indices 60-64)
# ==================================================================

# CSV file (3 tokens, 60-62)
t1, t2, t3 = use_token(), use_token(), use_token()
content = (
    f"id,service_name,api_key,created_at,status\n"
    f"1,payment-service,{t1['token']},2024-01-15T08:00:00Z,active\n"
    f"2,notification-svc,sk_test_fake_not_a_real_token_1234567890,"
    f"2024-01-16T09:00:00Z,active\n"
    f"3,auth-gateway,{t2['token']},2024-02-01T10:00:00Z,active\n"
    f"4,data-pipeline,ghp_notarealtoken1234567890abcdefghijk,"
    f"2024-02-15T11:00:00Z,revoked\n"
    f"5,deploy-bot,{t3['token']},2024-03-01T12:00:00Z,active\n"
)
with open(f"{CB}/data/service_keys.csv", "w") as fh:
    fh.write(content)

# XML config (2 tokens, 63-64)
t1, t2 = use_token(), use_token()
content = (
    f'<?xml version="1.0" encoding="UTF-8"?>\n'
    f"<configuration>\n"
    f'  <service name="nexauth-integration">\n'
    f"    <credentials>\n"
    f"      <api-key><![CDATA[{t1['token']}]]></api-key>\n"
    f"      <service-token><![CDATA[{t2['token']}]]></service-token>\n"
    f"    </credentials>\n"
    f"    <endpoints>\n"
    f"      <auth>https://auth.nexauth.example.com</auth>\n"
    f"    </endpoints>\n"
    f"  </service>\n"
    f"</configuration>\n"
)
with open(f"{CB}/config/nexauth_integration.xml", "w") as fh:
    fh.write(content)

# -- All 65 tokens consumed --
assert token_idx == 65, f"Expected 65 tokens used, got {token_idx}"

# ==================================================================
# DECOY FILES (no real tokens)
# ==================================================================

decoy_fake = "".join(random.choice(BASE62) for _ in range(36))
with open(f"{CB}/src/constants.py", "w") as fh:
    fh.write(
        f'"""Internal constants — NOT credentials."""\n'
        f'SHA_HASH_1 = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"\n'
        f'SHA_HASH_2 = "1234567890abcdef1234567890abcdef12345678"\n'
        f'UUID_1 = "550e8400-e29b-41d4-a716-446655440000"\n\n'
        f"# These look like token prefixes but aren't valid\n"
        f'FAKE_1 = "nxa_thisisnotavalidtoken"  # too short\n'
        f'FAKE_2 = "nxz_{decoy_fake}"  # wrong prefix letter\n'
        f'FAKE_3 = "nxa{decoy_fake}"  # missing underscore separator\n'
    )

with open(f"{CB}/src/test_patterns.py", "w") as fh:
    fh.write(
        f"# Test fixtures — regex patterns, not real tokens\n"
        f'NXA_PATTERN = r"nxa_[A-Za-z0-9]{{36}}"\n'
        f'NXS_PATTERN = r"nxs_[A-Za-z0-9]{{36}}"\n'
        f'SAMPLE_HASH = "nxa_" + "x" * 36  # Placeholder\n'
    )

# Distractor files with no tokens
for i in range(12):
    with open(f"{CB}/src/utils_{i}.py", "w") as fh:
        fh.write(
            f'"""Utility module {i}."""\n\n'
            f"def process_data_{i}(items):\n"
            f'    """Process a batch of items."""\n'
            f"    results = []\n"
            f"    for item in items:\n"
            f'        if item.get("status") == "active":\n'
            f"            results.append(item)\n"
            f"    return results\n\n\n"
            f"class DataProcessor{i}:\n"
            f"    def __init__(self, config):\n"
            f"        self.config = config\n"
            f"        self.batch_size = 100\n\n"
            f"    def run(self):\n"
            f"        data = self.fetch_data()\n"
            f"        return process_data_{i}(data)\n\n"
            f"    def fetch_data(self):\n"
            f"        raise NotImplementedError\n"
        )

# ==================================================================
# GIT COMMIT 3: All filesystem files
# ==================================================================

git_commit("Add application source code and deployment configs",
           "2024-03-17T14:00:00+00:00")
commit3_sha = get_head_sha()

# ==================================================================
# POST-COMMIT: Phase 13 — Git stash
# ==================================================================

stash_content = (
    f"# WIP: Credential rotation in progress\n"
    f"# New keys for Q2 2024 rotation cycle\n"
    f"NEW_API_KEY={stash_t1['token']}\n"
    f"NEW_SERVICE_TOKEN={stash_t2['token']}\n"
    f"ROTATION_DATE=2024-04-01\n"
)
with open(f"{CB}/config/rotation_wip.env", "w") as fh:
    fh.write(stash_content)

subprocess.run(["git", "-C", CB, "add", "config/rotation_wip.env"],
               check=True, capture_output=True)
subprocess.run(["git", "-C", CB, "stash", "push", "-m",
                "WIP: Q2 credential rotation"],
               check=True, capture_output=True)

# ==================================================================
# POST-COMMIT: Phase 16 — Git notes on custom ref
# ==================================================================

note1 = (
    f"internal-audit: credential rotation audit\n"
    f"audited_key: {notes_t1['token']}\n"
    f"audit_date: 2024-03-20\n"
    f"auditor: security-bot\n"
)
note2 = (
    f"internal-audit: deployment key review\n"
    f"reviewed_key: {notes_t2['token']}\n"
    f"review_date: 2024-03-21\n"
    f"reviewer: compliance-bot\n"
)

subprocess.run(
    ["git", "-C", CB, "notes", "--ref=internal-audit", "add",
     "-m", note1, commit3_sha],
    check=True, capture_output=True
)
subprocess.run(
    ["git", "-C", CB, "notes", "--ref=internal-audit", "add",
     "-m", note2, commit1_sha],
    check=True, capture_output=True
)

print("Corpus generation complete:")
print(f"  Total tokens: 65 (50 valid, 15 invalid)")
print(f"  Distributed across source files, encoded blobs, git history,")
print(f"  git stash, git notes, SQLite database, compressed archives,")
print(f"  OpenSSL encrypted files, cpio/bzip2 archives, and xxd hex dumps.")
