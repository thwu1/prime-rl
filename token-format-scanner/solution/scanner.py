#!/usr/bin/env python3
"""
Multi-vector token exposure forensics scanner.

Scans five data source types for leaked GitHub authentication tokens:
  1. File corpus (/app/corpus/) — plaintext tokens in various file formats
  2. Base64-encoded tokens — in JSON vault exports and other encoded blobs
  3. Encrypted vault (/app/corpus/vault.enc) — AES-256-CBC encrypted archive
  4. Git repository history (/app/repo/) — commits, reflog, dangling objects,
     stash entries, and git notes
  5. SQLite audit database (/app/audit/http_requests.db) — HTTP request logs
     including response headers with base64-encoded cookie tokens

Validates each token's integrity checksum per /app/spec.md and produces
a consolidated incident report at /app/incident_report.json.
"""
import base64
import json
import os
import re
import sqlite3
import subprocess
import zlib

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
TOKEN_RE = re.compile(r"gh[posur]_[0-9A-Za-z]{36}")
B64_RE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")


def base62_encode(num, length=6):
    result = []
    for _ in range(length):
        result.append(CHARSET[num % 62])
        num //= 62
    return "".join(reversed(result))


def validate_token(token):
    if len(token) != 40 or token[3] != "_":
        return False
    if token[:3] not in ("ghp", "gho", "ghu", "ghs", "ghr"):
        return False
    crc = zlib.crc32(token[:34].encode()) & 0xFFFFFFFF
    return base62_encode(crc, 6) == token[34:]


def extract_tokens(text):
    return set(TOKEN_RE.findall(text))


# ---------------------------------------------------------------------------
# Source 1: File corpus (plaintext + base64 + encrypted vault)
# ---------------------------------------------------------------------------

def scan_corpus(corpus_dir):
    findings = []
    for root, _dirs, files in os.walk(corpus_dir):
        for fname in files:
            fpath = os.path.join(root, fname)

            # Handle encrypted vault separately
            if fname.endswith(".enc"):
                vault_findings = decrypt_and_scan_vault(fpath)
                findings.extend(vault_findings)
                continue

            try:
                with open(fpath, "r", errors="ignore") as fh:
                    content = fh.read()
            except Exception:
                continue

            # Direct regex scan
            for tok in extract_tokens(content):
                findings.append({"token": tok, "source": fpath, "vector": "file"})

            # Base64-encoded blobs
            for m in B64_RE.finditer(content):
                try:
                    decoded = base64.b64decode(m.group()).decode("utf-8", errors="ignore")
                    for tok in extract_tokens(decoded):
                        findings.append({"token": tok, "source": fpath, "vector": "file"})
                    # Check for nested base64 (e.g., base64 → JSON containing tokens)
                    if decoded.startswith("{") or decoded.startswith("["):
                        for tok in extract_tokens(decoded):
                            findings.append({"token": tok, "source": fpath, "vector": "file"})
                except Exception:
                    pass

    return findings


def decrypt_and_scan_vault(vault_path):
    """Decrypt an openssl-encrypted vault file and scan for tokens.

    The passphrase is derived from the SECRET_KEY_BASE environment variable
    found in the .env file — first 32 characters.
    """
    findings = []

    # Read passphrase from .env
    env_path = os.path.join(os.path.dirname(vault_path), ".env")
    passphrase = None
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("SECRET_KEY_BASE="):
                    full_key = line.strip().split("=", 1)[1]
                    passphrase = full_key[:32]
                    break

    if not passphrase:
        return findings

    # Try decrypting with openssl
    try:
        result = subprocess.run(
            ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
             "-pass", f"pass:{passphrase}", "-in", vault_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            decrypted = result.stdout
            for tok in extract_tokens(decrypted):
                findings.append({"token": tok, "source": vault_path, "vector": "file"})
    except Exception:
        pass

    return findings


# ---------------------------------------------------------------------------
# Source 2: Git repository history (commits, reflog, stash, notes)
# ---------------------------------------------------------------------------

def _git(repo, *args):
    result = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout


def scan_git_repo(repo_dir):
    findings = []

    # 1. Full commit history including all branches
    log_output = _git(repo_dir, "log", "-p", "--all", "--full-history")
    for tok in extract_tokens(log_output):
        findings.append({"token": tok, "source": "git commit history", "vector": "git_history"})

    # 2. Reflog — recovers amended/reset commits
    reflog_hashes = _git(repo_dir, "reflog", "--format=%H").strip().split("\n")
    for sha in reflog_hashes:
        sha = sha.strip()
        if not sha:
            continue
        show_output = _git(repo_dir, "show", sha)
        for tok in extract_tokens(show_output):
            findings.append({"token": tok, "source": f"git reflog ({sha[:8]})", "vector": "git_history"})

    # 3. Unreachable objects via fsck
    fsck_output = _git(repo_dir, "fsck", "--unreachable", "--no-reflogs")
    for line in fsck_output.split("\n"):
        if "unreachable" in line:
            parts = line.split()
            if len(parts) >= 3:
                obj_sha = parts[2]
                cat_output = _git(repo_dir, "cat-file", "-p", obj_sha)
                for tok in extract_tokens(cat_output):
                    findings.append({"token": tok, "source": f"git unreachable ({obj_sha[:8]})", "vector": "git_history"})

    # 4. Git stash entries
    stash_list = _git(repo_dir, "stash", "list").strip()
    if stash_list:
        for line in stash_list.split("\n"):
            stash_ref = line.split(":")[0].strip()
            if stash_ref:
                stash_diff = _git(repo_dir, "stash", "show", "-p", stash_ref)
                for tok in extract_tokens(stash_diff):
                    findings.append({"token": tok, "source": f"git stash ({stash_ref})", "vector": "git_history"})

    # 5. Git notes
    notes_output = _git(repo_dir, "log", "--all", "--show-notes", "--format=%N")
    for tok in extract_tokens(notes_output):
        findings.append({"token": tok, "source": "git notes", "vector": "git_history"})

    return findings


# ---------------------------------------------------------------------------
# Source 3: SQLite audit database (all tables, base64 decoding)
# ---------------------------------------------------------------------------

def scan_audit_db(db_path):
    findings = []
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]

    for table in tables:
        cursor.execute(f"SELECT * FROM {table}")
        for row in cursor.fetchall():
            for cell in row:
                if isinstance(cell, str):
                    # Direct regex match
                    for tok in extract_tokens(cell):
                        findings.append({"token": tok, "source": f"audit_db:{table}", "vector": "audit_db"})

                    # Try base64 decoding on long base64-like substrings
                    for m in B64_RE.finditer(cell):
                        try:
                            decoded = base64.b64decode(m.group()).decode("utf-8", errors="ignore")
                            for tok in extract_tokens(decoded):
                                findings.append({"token": tok, "source": f"audit_db:{table} (base64)", "vector": "audit_db"})
                        except Exception:
                            pass

    conn.close()
    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_findings = []
    all_findings.extend(scan_corpus("/app/corpus"))
    all_findings.extend(scan_git_repo("/app/repo"))
    all_findings.extend(scan_audit_db("/app/audit/http_requests.db"))

    # Deduplicate by token value, keeping first occurrence
    seen = set()
    deduped = []
    for f in all_findings:
        if f["token"] not in seen:
            seen.add(f["token"])
            deduped.append({
                "token": f["token"],
                "token_type": f["token"][:3],
                "checksum_valid": validate_token(f["token"]),
                "source": f["source"],
                "vector": f["vector"],
            })

    by_type = {}
    by_vector = {}
    valid_count = 0
    invalid_count = 0
    for f in deduped:
        by_type[f["token_type"]] = by_type.get(f["token_type"], 0) + 1
        by_vector[f["vector"]] = by_vector.get(f["vector"], 0) + 1
        if f["checksum_valid"]:
            valid_count += 1
        else:
            invalid_count += 1

    report = {
        "findings": deduped,
        "summary": {
            "total_findings": len(deduped),
            "valid_tokens": valid_count,
            "invalid_checksums": invalid_count,
            "by_type": by_type,
            "by_vector": by_vector,
        },
    }

    with open("/app/incident_report.json", "w") as fh:
        json.dump(report, fh, indent=2)

    print(f"Incident report: /app/incident_report.json")
    print(f"  Total: {len(deduped)} | Valid: {valid_count} | Invalid: {invalid_count}")
    print(f"  By type:   {by_type}")
    print(f"  By vector: {by_vector}")


if __name__ == "__main__":
    main()
