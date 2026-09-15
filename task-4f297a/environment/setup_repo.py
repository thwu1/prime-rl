#!/usr/bin/env python3
"""Build git repository with scattered secret tokens for forensic audit task."""

import binascii
import hashlib
import hmac
import os
import struct
import subprocess

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
MASTER_KEY_HEX = "a3f7e9c1b2d4a6e8f0c2d4b6a8e0f2c4d6b8a0e2c4f6d8b0a2e4c6f8d0b2a4"


def base62_encode(num, length=6):
    if num == 0:
        return BASE62[0] * length
    result = []
    while num > 0:
        result.append(BASE62[num % 62])
        num //= 62
    result.reverse()
    return "".join(result).rjust(length, BASE62[0])


def crc32_base62(data):
    crc = binascii.crc32(data.encode()) & 0xFFFFFFFF
    return base62_encode(crc, 6)


def hkdf_sha256(ikm, salt, info, length):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    t = b""
    okm = b""
    for i in range(1, (length + 31) // 32 + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def hmac_hkdf_trunc(data, mk, salt_s, info_s):
    dk = hkdf_sha256(mk, salt_s.encode(), info_s.encode(), 32)
    return hmac.new(dk, data.encode(), hashlib.sha256).hexdigest()[:8]


def sha256_base62(data):
    d = hashlib.sha256(data.encode()).digest()
    num = struct.unpack(">I", d[:4])[0]
    return base62_encode(num, 6)


def git(*args):
    subprocess.run(["git"] + list(args), cwd="/app/repo",
                    check=True, capture_output=True)


def wf(path, content):
    full = os.path.join("/app/repo", path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)


def sd(d):
    os.environ["GIT_AUTHOR_DATE"] = d
    os.environ["GIT_COMMITTER_DATE"] = d


def main():
    mk = bytes.fromhex(MASTER_KEY_HEX)

    # Generate tokens with correct checksums
    t1 = "ghp_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123" + crc32_base62("ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123")
    t2 = "isv_" + "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0" + hmac_hkdf_trunc("isv_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0", mk, "internal_svc_v1", "token_signing")
    t3 = "ghs_" + "9z8y7x6w5v4u3t2s1r0qPoNmLkJiHg" + crc32_base62("ghs_9z8y7x6w5v4u3t2s1r0qPoNmLkJiHg")
    t4 = "art_" + "XyZ123AbC456dEf789GhI012" + sha256_base62("art_XyZ123AbC456dEf789GhI012")
    t5 = "art_" + "JkL345MnO678pQr901StU234" + sha256_base62("art_JkL345MnO678pQr901StU234")
    t6 = "gho_" + "aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0" + crc32_base62("gho_aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0")
    t7 = "ghp_ZzYyXxWwVvUuTtSsRrQqPpOoNnMmLl000000"  # invalid checksum

    # Write providers.yaml
    os.makedirs("/app", exist_ok=True)
    with open("/app/providers.yaml", "w") as f:
        f.write('providers:\n')
        f.write('  - name: github\n')
        f.write('    description: "GitHub authentication tokens (CRC32-Base62 checksum)"\n')
        f.write('    prefixes:\n')
        f.write('      - "ghp_"\n')
        f.write('      - "gho_"\n')
        f.write('      - "ghs_"\n')
        f.write('    body_charset: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"\n')
        f.write('    body_length: 30\n')
        f.write('    checksum:\n')
        f.write('      algorithm: crc32_base62\n')
        f.write('      length: 6\n')
        f.write('      base62_charset: "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"\n')
        f.write('\n')
        f.write('  - name: internal_svc\n')
        f.write('    description: "Internal service tokens (HMAC-SHA256 with HKDF-derived key)"\n')
        f.write('    prefixes:\n')
        f.write('      - "isv_"\n')
        f.write('    body_charset: "0123456789abcdef"\n')
        f.write('    body_length: 40\n')
        f.write('    checksum:\n')
        f.write('      algorithm: hmac_sha256_hkdf_trunc\n')
        f.write('      length: 8\n')
        f.write('      hkdf_master_key_file: "/app/vault/master.key"\n')
        f.write('      hkdf_salt: "internal_svc_v1"\n')
        f.write('      hkdf_info: "token_signing"\n')
        f.write('      hkdf_key_length: 32\n')
        f.write('\n')
        f.write('  - name: artifact_registry\n')
        f.write('    description: "Artifact registry tokens (SHA256-Base62 checksum)"\n')
        f.write('    prefixes:\n')
        f.write('      - "art_"\n')
        f.write('    body_charset: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"\n')
        f.write('    body_length: 24\n')
        f.write('    checksum:\n')
        f.write('      algorithm: sha256_base62\n')
        f.write('      length: 6\n')
        f.write('      base62_charset: "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"\n')

    # Write master key
    os.makedirs("/app/vault", exist_ok=True)
    with open("/app/vault/master.key", "w") as f:
        f.write(MASTER_KEY_HEX + "\n")

    # Init repo
    os.makedirs("/app/repo", exist_ok=True)
    git("init", "-b", "main")
    git("config", "user.email", "dev@example.com")
    git("config", "user.name", "Developer")

    # Commit 1: Initial setup
    wf("README.md", "# Project Alpha\n\nInternal service platform.\n")
    wf("src/__init__.py", "")
    wf("requirements.txt", "flask==2.3.0\nrequests==2.31.0\n")
    git("add", ".")
    sd("2024-01-15T10:00:00+00:00")
    git("commit", "-m", "Initial project setup")

    # Commit 2: Config with TOKEN_1 (ghp_, valid, stays in HEAD)
    wf("src/config.py",
       '"""Application configuration."""\n'
       'import os\n\n'
       '# TODO: move to env var\n'
       'API_TOKEN = "' + t1 + '"\n\n'
       'DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///app.db")\n'
       'DEBUG = os.environ.get("DEBUG", "false").lower() == "true"\n')
    git("add", ".")
    sd("2024-01-20T14:30:00+00:00")
    git("commit", "-m", "Add configuration module")

    # Commit 3: Deployment with TOKEN_2 (isv_, HKDF checksum, stays in HEAD)
    wf("deploy/env.sh",
       '#!/bin/bash\n'
       '# Deployment environment setup\n'
       'export APP_ENV=production\n'
       'export SERVICE_TOKEN="' + t2 + '"\n'
       'export LOG_LEVEL=info\n')
    wf("deploy/Makefile", "deploy:\n\t./env.sh && kubectl apply -f k8s/\n")
    git("add", ".")
    sd("2024-02-05T09:15:00+00:00")
    git("commit", "-m", "Add deployment infrastructure")

    # Tag v1.0.0
    git("tag", "v1.0.0")

    # Branch feat/api
    git("checkout", "-b", "feat/api")

    # Commit 4: API client with TOKEN_3 (ghs_, valid, later removed)
    wf("src/api_client.py",
       '"""GitHub API client."""\n'
       'import requests\n\n'
       'class GitHubClient:\n'
       '    def __init__(self):\n'
       '        self.token = "' + t3 + '"\n'
       '        self.base_url = "https://api.github.com"\n\n'
       '    def get_repos(self, org):\n'
       '        headers = {"Authorization": f"token {self.token}"}\n'
       '        return requests.get(f"{self.base_url}/orgs/{org}/repos", headers=headers)\n')
    git("add", ".")
    sd("2024-02-10T11:00:00+00:00")
    git("commit", "-m", "Implement API client authentication")

    # Commit 5: Remove TOKEN_3
    wf("src/api_client.py",
       '"""GitHub API client."""\n'
       'import os\n'
       'import requests\n\n'
       'class GitHubClient:\n'
       '    def __init__(self):\n'
       '        self.token = os.environ["GITHUB_TOKEN"]\n'
       '        self.base_url = "https://api.github.com"\n\n'
       '    def get_repos(self, org):\n'
       '        headers = {"Authorization": f"token {self.token}"}\n'
       '        return requests.get(f"{self.base_url}/orgs/{org}/repos", headers=headers)\n')
    git("add", ".")
    sd("2024-02-10T15:30:00+00:00")
    git("commit", "-m", "Remove hardcoded credentials from API client")

    # Merge feat/api into main
    git("checkout", "main")
    sd("2024-02-12T10:00:00+00:00")
    git("merge", "feat/api", "--no-ff", "-m", "Merge feat/api: API client integration")

    # Commit 7: CI pipeline with TOKEN_4 (art_, valid, later removed)
    wf(".github/workflows/deploy.yml",
       'name: Deploy\n'
       'on:\n'
       '  push:\n'
       '    branches: [main]\n'
       'jobs:\n'
       '  deploy:\n'
       '    runs-on: ubuntu-latest\n'
       '    steps:\n'
       '      - uses: actions/checkout@v4\n'
       '      - name: Push to registry\n'
       '        env:\n'
       '          REGISTRY_TOKEN: "' + t4 + '"\n'
       '        run: |\n'
       '          docker build -t app:latest .\n'
       '          docker push registry.example.com/app:latest\n')
    git("add", ".")
    sd("2024-03-01T08:00:00+00:00")
    git("commit", "-m", "Add CI/CD pipeline")

    # Commit 8: Remove TOKEN_4
    wf(".github/workflows/deploy.yml",
       'name: Deploy\n'
       'on:\n'
       '  push:\n'
       '    branches: [main]\n'
       'jobs:\n'
       '  deploy:\n'
       '    runs-on: ubuntu-latest\n'
       '    steps:\n'
       '      - uses: actions/checkout@v4\n'
       '      - name: Push to registry\n'
       '        env:\n'
       '          REGISTRY_TOKEN: ${{ secrets.REGISTRY_TOKEN }}\n'
       '        run: |\n'
       '          docker build -t app:latest .\n'
       '          docker push registry.example.com/app:latest\n')
    git("add", ".")
    sd("2024-03-01T16:00:00+00:00")
    git("commit", "-m", "Secure CI pipeline credentials")

    # Branch feat/registry with TOKEN_5, amend to remove (creates dangling commit)
    git("checkout", "-b", "feat/registry")
    wf("src/registry.py",
       '"""Registry client."""\n'
       'REGISTRY_KEY = "' + t5 + '"\n')
    git("add", ".")
    sd("2024-03-05T10:00:00+00:00")
    git("commit", "-m", "Add registry integration")

    # Amend to remove TOKEN_5 (original commit becomes dangling)
    wf("src/registry.py",
       '"""Registry client."""\n'
       'import os\n'
       'REGISTRY_KEY = os.environ["REGISTRY_KEY"]\n')
    git("add", ".")
    sd("2024-03-05T11:00:00+00:00")
    git("commit", "--amend", "-m", "Add registry integration (cleaned)")

    # Delete branch to make both commits unreachable
    git("checkout", "main")
    git("branch", "-D", "feat/registry")

    # Commit 9: Test file with TOKEN_7 (invalid checksum)
    wf("tests/test_auth.py",
       '"""Auth tests with test credentials."""\n'
       'import unittest\n\n'
       '# Test token for mocking API responses\n'
       'TEST_TOKEN = "' + t7 + '"\n\n'
       'class TestAuth(unittest.TestCase):\n'
       '    def test_token_validation(self):\n'
       '        assert len(TEST_TOKEN) == 40\n')
    git("add", ".")
    sd("2024-03-10T14:00:00+00:00")
    git("commit", "-m", "Add authentication tests")

    # Stash with TOKEN_6 (gho_, valid, only discoverable via stash)
    wf("src/config.py",
       '"""Application configuration."""\n'
       'import os\n\n'
       '# TODO: move to env var\n'
       'API_TOKEN = "' + t1 + '"\n'
       'OAUTH_TOKEN = "' + t6 + '"\n\n'
       'DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///app.db")\n'
       'DEBUG = os.environ.get("DEBUG", "false").lower() == "true"\n')
    sd("2024-03-12T09:00:00+00:00")
    git("stash", "push", "-m", "WIP: adding oauth support")

    # Expire reflogs so dangling commits are truly unreachable
    git("reflog", "expire", "--expire=now", "--all")

    # Write rotation log
    t3_hash = hashlib.sha256(t3.encode()).hexdigest()
    t5_hash = hashlib.sha256(t5.encode()).hexdigest()
    with open("/app/rotation_log.csv", "w") as f:
        f.write("token_sha256,rotation_date,provider\n")
        f.write(t3_hash + ",2024-03-15T00:00:00Z,github\n")
        f.write(t5_hash + ",2024-04-01T00:00:00Z,artifact_registry\n")

    # Clean env
    for v in ["GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"]:
        os.environ.pop(v, None)

    print("Repository setup complete.")


if __name__ == "__main__":
    main()
