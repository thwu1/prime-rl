#!/usr/bin/env python3
"""
Set up a git repository with tokens embedded across various git object types
for the secret audit task. Tokens are placed in:
  - Regular blobs (source files in commit history)
  - An annotated tag message
  - A git note
  - A stash entry
  - An unreachable commit (from a git commit --amend)
Decoy tokens with invalid checksums are also scattered throughout.
"""

import os
import subprocess
import zlib

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
REPO = "/app/repo"


def base62_encode(num, length=6):
    if num == 0:
        return BASE62[0] * length
    chars = []
    while num > 0:
        chars.append(BASE62[num % 62])
        num //= 62
    chars.reverse()
    return "".join(chars).rjust(length, "0")


def fnv1a_32(data):
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


# --- Token generators ---

def make_apx(payload24):
    prefix = "apx_"
    crc = zlib.crc32((prefix + payload24).encode()) & 0xFFFFFFFF
    return prefix + payload24 + base62_encode(crc, 6)


def make_apx_bad(payload24):
    prefix = "apx_"
    crc = zlib.crc32((prefix + payload24).encode()) & 0xFFFFFFFF
    wrong = (crc ^ 0x12345678) & 0xFFFFFFFF
    return prefix + payload24 + base62_encode(wrong, 6)


def make_nxs(payload_hex40):
    raw = bytes.fromhex(payload_hex40)
    adler = zlib.adler32(raw) & 0xFFFFFFFF
    return f"nxs-{payload_hex40}-{format(adler, '08x')}"


def make_nxs_bad(payload_hex40):
    raw = bytes.fromhex(payload_hex40)
    adler = zlib.adler32(raw) & 0xFFFFFFFF
    wrong = (adler ^ 0xDEADBEEF) & 0xFFFFFFFF
    return f"nxs-{payload_hex40}-{format(wrong, '08x')}"


def make_vlt(variant, payload22):
    prefix = f"vlt_{variant}_"
    h = fnv1a_32((prefix + payload22).encode())
    return prefix + payload22 + base62_encode(h, 6)


def make_vlt_bad(variant, payload22):
    prefix = f"vlt_{variant}_"
    h = fnv1a_32((prefix + payload22).encode())
    wrong = (h ^ 0xCAFEBABE) & 0xFFFFFFFF
    return prefix + payload22 + base62_encode(wrong, 6)


# --- Git helpers ---

ENV = os.environ.copy()
ENV["GIT_AUTHOR_NAME"] = "Dev Team"
ENV["GIT_AUTHOR_EMAIL"] = "dev@example.com"
ENV["GIT_COMMITTER_NAME"] = "Dev Team"
ENV["GIT_COMMITTER_EMAIL"] = "dev@example.com"


def git(*args):
    subprocess.run(["git"] + list(args), cwd=REPO, check=True, env=ENV,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def git_output(*args):
    r = subprocess.run(["git"] + list(args), cwd=REPO, env=ENV,
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def write_file(relpath, content):
    fullpath = os.path.join(REPO, relpath)
    os.makedirs(os.path.dirname(fullpath), exist_ok=True)
    with open(fullpath, "w") as f:
        f.write(content)


def main():
    # Generate valid tokens
    apx1 = make_apx("AbCdEfGhIjKlMnOpQrStUvWx")
    apx2 = make_apx("Zy0x1w2v3u4t5s6r7q8p9oNm")
    apx3 = make_apx("R4nD0mP4yL04dF0rSt4shK3y")

    nxs1 = make_nxs("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0")
    nxs2 = make_nxs("1234567890abcdef1234567890abcdef12345678")
    nxs3 = make_nxs("fedcba0987654321fedcba0987654321fedcba09")

    vlt1 = make_vlt("live", "K3yF0rP4yM3nTsS3rv1c3x")
    vlt2 = make_vlt("test", "T3st1ngK3yF0rD3vM0d3zz")
    vlt3 = make_vlt("live", "Pr0dUcT10nD4t4b4s3Crdz")

    # Generate decoy tokens (invalid checksums)
    apx_d1 = make_apx_bad("DecoyToken01ForTestingXx")
    apx_d2 = make_apx_bad("AnotherFakeTokenPayload0")
    nxs_d1 = make_nxs_bad("0000000000000000000000000000000000000000")
    vlt_d1 = make_vlt_bad("live", "F4k3T0k3nTh4tSh0uldF41")

    # --- Build the repository ---
    os.makedirs(REPO, exist_ok=True)
    git("init", "-b", "main")
    git("config", "user.name", "Dev Team")
    git("config", "user.email", "dev@example.com")

    # Commit 1: Initial
    write_file("README.md", "# MyApp\n\nA sample application.\n")
    write_file("Makefile", "all:\n\techo 'Building...'\n\ntest:\n\techo 'Testing...'\n")
    git("add", "-A")
    git("commit", "-m", "Initial commit")

    # Commit 2: database config with NXS #1
    write_file("config/database.yaml",
               f"database:\n"
               f"  host: db.internal.example.com\n"
               f"  port: 5432\n"
               f"  name: myapp_production\n"
               f"  # Legacy connection string (DO NOT USE):\n"
               f"  # connection_token: {nxs1}\n"
               f"  pool_size: 20\n"
               f"  timeout: 30\n"
               f"  ssl_mode: verify-full\n")
    git("add", "-A")
    git("commit", "-m", "Add database configuration")

    # Commit 3: terraform with APX #1 + decoy
    write_file("deploy/terraform.tf",
               f'provider "aws" {{\n'
               f'  region = "us-east-1"\n'
               f'}}\n\n'
               f'variable "api_token" {{\n'
               f'  default = "{apx1}"\n'
               f'  sensitive = true\n'
               f'}}\n\n'
               f'# Decoy from an old test:\n'
               f'# old_token = "{apx_d1}"\n\n'
               f'resource "aws_instance" "app" {{\n'
               f'  ami           = "ami-0c55b159cbfafe1f0"\n'
               f'  instance_type = "t3.medium"\n'
               f'  tags = {{ Name = "myapp-prod" }}\n'
               f'}}\n')
    git("add", "-A")
    git("commit", "-m", "Add infrastructure configuration")

    # Save commit 3 hash for tagging later
    commit3_hash = git_output("rev-parse", "HEAD")

    # Commit 4: utils.py with APX #2 + decoy
    write_file("src/__init__.py", "")
    write_file("src/utils.py",
               f'"""\n'
               f'Utility functions for the MyApp service.\n\n'
               f'Historical API tokens (for reference during migration):\n'
               f'  Production: {apx2}\n'
               f'  Staging: {apx_d2}\n'
               f'"""\n\n'
               f'import hashlib\n'
               f'import logging\n\n'
               f'logger = logging.getLogger(__name__)\n\n\n'
               f'def hash_payload(data: bytes) -> str:\n'
               f'    return hashlib.sha256(data).hexdigest()\n\n\n'
               f'def sanitize_input(text: str) -> str:\n'
               f'    return text.replace("<", "&lt;").replace(">", "&gt;")\n')
    git("add", "-A")
    git("commit", "-m", "Add utility functions")

    # Feature branch
    git("checkout", "-b", "feature/payments")

    # Commit 5: payment.py with VLT #1 + decoy
    write_file("services/__init__.py", "")
    write_file("services/payment.py",
               f'import requests\n\n'
               f'VAULT_TOKEN = "{vlt1}"\n'
               f'PAYMENT_API = "https://api.payments.example.com/v2"\n\n'
               f'# Previously used test credential: {vlt_d1}\n\n'
               f'def process_payment(amount, currency, customer_id):\n'
               f'    headers = {{"Authorization": f"Bearer {{VAULT_TOKEN}}"}}\n'
               f'    resp = requests.post(\n'
               f'        f"{{PAYMENT_API}}/charge",\n'
               f'        json={{"amount": amount, "currency": currency, "customer": customer_id}},\n'
               f'        headers=headers\n'
               f'    )\n'
               f'    return resp.json()\n')
    git("add", "-A")
    git("commit", "-m", "Add payment service integration")

    # Commit 6: webhook.py with NXS #2
    write_file("services/webhook.py",
               f'import hmac\n'
               f'import hashlib\n\n'
               f'WEBHOOK_SECRET = "{nxs2}"\n\n'
               f'def verify_webhook(payload, signature):\n'
               f'    expected = hmac.new(\n'
               f'        WEBHOOK_SECRET.encode(), payload.encode(), hashlib.sha256\n'
               f'    ).hexdigest()\n'
               f'    return hmac.compare_digest(expected, signature)\n\n'
               f'def handle_event(event_type, data):\n'
               f'    if event_type == "payment.completed":\n'
               f'        return {{"status": "processed", "id": data.get("id")}}\n'
               f'    return {{"status": "ignored"}}\n')
    git("add", "-A")
    git("commit", "-m", "Add webhook handler")

    # Back to main
    git("checkout", "main")

    # Commit 7: docs
    write_file("docs/api.md",
               "# API Documentation\n\n## Endpoints\n\n### POST /charge\n\nProcess a payment.\n")
    git("add", "-A")
    git("commit", "-m", "Add API documentation")

    # Merge feature branch
    git("merge", "feature/payments", "-m", "Merge feature/payments into main")

    # Delete feature branch
    git("branch", "-d", "feature/payments")

    # Commit 8: Security cleanup — remove all tokens from HEAD
    write_file("config/database.yaml",
               "database:\n"
               "  host: db.internal.example.com\n"
               "  port: 5432\n"
               "  name: myapp_production\n"
               "  pool_size: 20\n"
               "  timeout: 30\n"
               "  ssl_mode: verify-full\n")
    write_file("deploy/terraform.tf",
               'provider "aws" {\n'
               '  region = "us-east-1"\n'
               '}\n\n'
               'variable "api_token" {\n'
               '  default = ""\n'
               '  sensitive = true\n'
               '}\n\n'
               'resource "aws_instance" "app" {\n'
               '  ami           = "ami-0c55b159cbfafe1f0"\n'
               '  instance_type = "t3.medium"\n'
               '  tags = { Name = "myapp-prod" }\n'
               '}\n')
    write_file("src/utils.py",
               '"""\nUtility functions for the MyApp service.\n"""\n\n'
               'import hashlib\nimport logging\n\n'
               'logger = logging.getLogger(__name__)\n\n\n'
               'def hash_payload(data: bytes) -> str:\n'
               '    return hashlib.sha256(data).hexdigest()\n\n\n'
               'def sanitize_input(text: str) -> str:\n'
               '    return text.replace("<", "&lt;").replace(">", "&gt;")\n')
    # Remove payment service files
    for f in ["services/__init__.py", "services/payment.py", "services/webhook.py"]:
        fp = os.path.join(REPO, f)
        if os.path.exists(fp):
            os.remove(fp)
    sdir = os.path.join(REPO, "services")
    if os.path.isdir(sdir):
        os.rmdir(sdir)
    git("add", "-A")
    git("commit", "-m", "Security audit: remove leaked credentials")

    # Commit 9: monitoring with VLT #2 — will be amended to create unreachable
    write_file("monitoring/alerts.yaml",
               f"alerts:\n"
               f"  - name: high_latency\n"
               f"    threshold: 500ms\n"
               f'    channel: "#oncall"\n\n'
               f"  # Temporary debug credential\n"
               f"  debug_vault_token: {vlt2}\n\n"
               f"  - name: error_rate\n"
               f"    threshold: 5%\n"
               f'    channel: "#oncall"\n')
    git("add", "-A")
    git("commit", "-m", "Add monitoring alerts (with debug cred)")

    # Amend to remove VLT #2 — original commit becomes unreachable
    write_file("monitoring/alerts.yaml",
               "alerts:\n"
               "  - name: high_latency\n"
               "    threshold: 500ms\n"
               '    channel: "#oncall"\n\n'
               "  - name: error_rate\n"
               "    threshold: 5%\n"
               '    channel: "#oncall"\n')
    git("add", "-A")
    git("commit", "--amend", "-m", "Add monitoring alerts")

    # Commit 10: Update README
    write_file("README.md",
               "# MyApp\n\nA sample application.\n\n"
               "## Security\n\nAll credentials should be stored in a vault, "
               "never in source code.\n")
    git("add", "-A")
    git("commit", "-m", "Update README with security guidelines")

    # --- Annotated tag with NXS #3 in message ---
    tag_msg = (f"Release v1.0 - Production ready\n\n"
               f"Deploy with service token: {nxs3}\n"
               f"See docs/api.md for details.")
    git("tag", "-a", "v1.0", commit3_hash, "-m", tag_msg)

    # --- Git note with VLT #3 ---
    first_commit = git_output("rev-list", "--max-parents=0", "HEAD")
    note_msg = f"TODO: Rotate production credentials before GA. Current token: {vlt3}"
    git("notes", "add", first_commit, "-m", note_msg)

    # --- Stash with APX #3 ---
    write_file("temp_config.env",
               f"# Temporary configuration for load testing\n"
               f"LOAD_TEST_API_KEY={apx3}\n"
               f"CONCURRENT_USERS=1000\n"
               f"DURATION=300\n")
    git("add", "temp_config.env")
    git("stash", "push", "-m", "WIP: load testing config")

    # --- Archive branch with NXS decoy ---
    git("checkout", "-b", "archive/legacy-config", "HEAD~6")
    write_file("legacy/old_config.ini",
               f"[service]\n"
               f"endpoint = https://api.legacy.example.com\n"
               f"token = {nxs_d1}\n"
               f"timeout = 60\n")
    git("add", "-A")
    git("commit", "-m", "Archive legacy configuration")
    git("checkout", "main")

    print("Repository setup complete.")
    print(f"Valid tokens: APX({apx1}, {apx2}, {apx3})")
    print(f"Valid tokens: NXS({nxs1}, {nxs2}, {nxs3})")
    print(f"Valid tokens: VLT({vlt1}, {vlt2}, {vlt3})")


if __name__ == "__main__":
    main()
