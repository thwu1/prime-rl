#!/usr/bin/env python3
"""
Complete solution for iperf3 authentication protocol security audit.

Produces all four deliverables:
1. /app/forensics_report.json — token decryption, password cracking, timeline
2. /app/security_assessment.json — vulnerability evaluation
3. /app/hardened_auth.py — hardened auth module (copied from /solution/)
4. /app/migrated_credentials.txt + /app/migration_report.json — credential migration
"""

import base64
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

# Ensure /app is on the path so we can import hardened_auth
sys.path.insert(0, '/app')


# ==========================================================================
# Part 1: Forensic Analysis
# ==========================================================================

def iperf3_password_hash(username, password):
    salted = "{%s}%s" % (username, password)
    return hashlib.sha256(salted.encode()).hexdigest()


def load_private_key(path):
    with open(path, 'rb') as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def decrypt_token(token_b64, private_key):
    encrypted = base64.b64decode(token_b64)
    plaintext = private_key.decrypt(encrypted, asym_padding.PKCS1v15())
    return plaintext.decode('utf-8')


def parse_auth_plaintext(plaintext):
    lines = plaintext.split('\n')
    username = lines[0][len('user: '):]
    password = lines[1][len('pwd:  '):]
    timestamp = int(lines[2][len('ts:   '):])
    return username, password, timestamp


def load_authorized_users(path):
    users = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            comma = line.index(',')
            users[line[:comma]] = line[comma + 1:]
    return users


def crack_passwords(auth_users, wordlist_path):
    with open(wordlist_path) as f:
        words = [line.strip() for line in f if line.strip()]
    cracked = {}
    for username, expected_hash in auth_users.items():
        for word in words:
            if iperf3_password_hash(username, word) == expected_hash:
                cracked[username] = word
                break
    return cracked


def find_shared_passwords(cracked):
    pw_to_users = defaultdict(list)
    for username, password in cracked.items():
        pw_to_users[password].append(username)
    return sorted([sorted(users) for users in pw_to_users.values() if len(users) > 1])


def analyze_timeline(tokens_data):
    sorted_tokens = sorted(tokens_data, key=lambda x: x['timestamp'])
    chronological_order = [t['id'] for t in sorted_tokens]
    timestamps = [t['timestamp'] for t in sorted_tokens]
    time_span = timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0

    anomalous_gaps = []
    if len(sorted_tokens) >= 2:
        gaps = []
        for i in range(1, len(sorted_tokens)):
            gap = sorted_tokens[i]['timestamp'] - sorted_tokens[i - 1]['timestamp']
            gaps.append((sorted_tokens[i - 1]['id'], sorted_tokens[i]['id'], gap))
        gap_values = sorted(g[2] for g in gaps)
        median_gap = gap_values[len(gap_values) // 2]
        threshold = max(median_gap * 10, 1000)
        for prev_id, curr_id, gap in gaps:
            if gap > threshold:
                anomalous_gaps.append({
                    "between_tokens": [prev_id, curr_id],
                    "gap_seconds": gap,
                })

    return {
        "chronological_order": chronological_order,
        "time_span_seconds": time_span,
        "anomalous_gaps": anomalous_gaps,
    }


def produce_forensics_report():
    print("=== Forensic Analysis ===")
    private_key = load_private_key('/app/forensics/private.pem')
    auth_users = load_authorized_users('/app/forensics/authorized_users.csv')

    with open('/app/forensics/captured_tokens.json') as f:
        tokens = json.load(f)

    tokens_analysis = []
    for entry in tokens:
        plaintext = decrypt_token(entry['token'], private_key)
        username, password, timestamp = parse_auth_plaintext(plaintext)
        valid_user = username in auth_users
        valid_creds = False
        if valid_user:
            valid_creds = iperf3_password_hash(username, password) == auth_users[username]

        tokens_analysis.append({
            "id": entry['id'],
            "username": username,
            "password": password,
            "timestamp": timestamp,
            "timestamp_utc": datetime.fromtimestamp(
                timestamp, tz=timezone.utc
            ).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "valid_user": valid_user,
            "valid_credentials": valid_creds,
        })

    cracked = crack_passwords(auth_users, '/app/forensics/wordlist.txt')
    uncracked = sorted(u for u in auth_users if u not in cracked)
    shared = find_shared_passwords(cracked)
    timeline = analyze_timeline(tokens_analysis)

    report = {
        "tokens": tokens_analysis,
        "password_audit": {
            "cracked": cracked,
            "uncracked": uncracked,
            "total_users": len(auth_users),
            "cracked_count": len(cracked),
        },
        "shared_passwords": shared,
        "timeline": timeline,
    }

    with open('/app/forensics_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("  Tokens analyzed: %d" % len(tokens_analysis))
    print("  Passwords cracked: %d / %d" % (len(cracked), len(auth_users)))
    print("  Shared password groups: %d" % len(shared))
    print("  Anomalous gaps: %d" % len(timeline['anomalous_gaps']))
    return cracked


# ==========================================================================
# Part 2: Security Assessment
# ==========================================================================

def produce_security_assessment():
    print("\n=== Security Assessment ===")

    assessment = {
        "vulnerabilities": [
            {
                "id": "VULN-001",
                "title": "RSA PKCS#1 v1.5 Padding Enables Timing Side-Channel (Marvin Attack)",
                "category": "cryptographic",
                "severity": "high",
                "cve_references": ["CVE-2024-26306"],
                "affected_function": "encrypt_rsa_message / decrypt_rsa_message in iperf_auth.c",
                "description": "The authentication protocol uses RSA with PKCS#1 v1.5 padding "
                    "(use_pkcs1_padding=1 in t_auth.c line 123). When the server runs OpenSSL "
                    "< 3.2.0 (this deployment uses 3.0.2, which lacks implicit rejection), "
                    "RSA decryption is not constant-time. An attacker on the network can mount "
                    "a Bleichenbacher/Marvin timing attack by sending many crafted ciphertexts "
                    "and measuring decryption time, eventually recovering the plaintext "
                    "credentials from any captured authentication token.",
                "exploitability": "High — the server is accessible from 10.0.0.0/8 (any "
                    "internal host). The attack requires network access and sending ~10,000+ "
                    "crafted messages but no authentication. OpenSSL 3.0.2 lacks the implicit "
                    "rejection countermeasure added in 3.2.0.",
                "impact": "Complete credential disclosure. Attacker recovers plaintext "
                    "username and password from any intercepted authentication token, enabling "
                    "unauthorized iperf3 testing and potential lateral movement if passwords "
                    "are reused.",
                "recommendation": "Switch to OAEP padding (RSA_PKCS1_OAEP_PADDING). "
                    "iperf3 >= 3.17 defaults to OAEP. Remove the --use-pkcs1-padding "
                    "backward-compatibility option.",
            },
            {
                "id": "VULN-002",
                "title": "Off-by-One Heap Overflow in RSA Decryption Buffer",
                "category": "implementation",
                "severity": "high",
                "cve_references": ["CVE-2025-54349"],
                "affected_function": "decrypt_rsa_message in iperf_auth.c",
                "description": "The plaintext buffer in decrypt_rsa_message is allocated with "
                    "an off-by-one error. After decryption, the code writes a NULL terminator "
                    "at plaintext[plaintext_len], which can overflow the allocated buffer by "
                    "one byte. This is a heap overflow that can corrupt allocator metadata.",
                "exploitability": "Medium — requires sending a crafted authentication token "
                    "to an iperf3 server with authentication enabled. The single-byte overflow "
                    "is difficult to exploit for code execution but reliably causes heap "
                    "corruption. With auto_restart_on_crash enabled, repeated exploitation "
                    "could enable a more targeted attack.",
                "impact": "Server crash (denial of service). Potential for heap metadata "
                    "corruption leading to further exploitation in multi-threaded contexts.",
                "recommendation": "Upgrade to iperf3 >= 3.19.1 which correctly sizes the "
                    "plaintext buffer. Add bounds checking before NULL termination.",
            },
            {
                "id": "VULN-003",
                "title": "Malformed Base64 Authentication Token Causes Server Crash",
                "category": "implementation",
                "severity": "medium",
                "cve_references": ["CVE-2025-54350"],
                "affected_function": "decode_auth_setting / Base64Decode in iperf_auth.c",
                "description": "A malformed Base64-encoded authentication token triggers an "
                    "assertion failure in the server, crashing the process. The crash occurs "
                    "before any credential validation, so no authentication is needed to "
                    "exploit this. The calcDecodeLength function can return 0 or an incorrect "
                    "length for malformed input, and downstream code does not handle this.",
                "exploitability": "High — any unauthenticated client can send a malformed "
                    "token. Combined with systemd auto-restart, this enables a persistent "
                    "denial-of-service cycle.",
                "impact": "Server crash. With auto_restart_on_crash=true, the server restarts "
                    "but each crash interrupts active tests and may leak resources.",
                "recommendation": "Replace assert() with proper error handling. Return an "
                    "error code instead of aborting. Upgrade to iperf3 >= 3.19.1.",
            },
            {
                "id": "VULN-004",
                "title": "Password Storage Uses Single-Round SHA-256 Without Key Derivation Function",
                "category": "cryptographic",
                "severity": "critical",
                "cve_references": [],
                "affected_function": "check_authentication / sha256 in iperf_auth.c",
                "description": "Passwords in authorized_users.csv are stored as SHA-256 hashes "
                    "with no key stretching or iteration. SHA-256 can be computed at "
                    "~10 billion hashes/sec on modern GPUs. If the credential file is "
                    "compromised, an attacker can brute-force all passwords rapidly. "
                    "The code computes SHA256('{username}password') — a single hash invocation "
                    "with no KDF (no bcrypt, scrypt, argon2, or PBKDF2).",
                "exploitability": "High if the credential store is accessible (e.g., via "
                    "the compromised server). Dictionary and brute-force attacks are trivial "
                    "with commodity hardware. In this engagement, 7 of 20 passwords were "
                    "cracked in seconds from a 20K-word dictionary.",
                "impact": "Mass password recovery. Compromised passwords may be reused "
                    "across other systems (corporate credentials).",
                "recommendation": "Replace SHA-256 hashing with Argon2id (memory-hard KDF) "
                    "or bcrypt with a work factor >= 12. Migrate all existing credential "
                    "entries to the new scheme.",
            },
            {
                "id": "VULN-005",
                "title": "Username Used as Sole Salt for Password Hashing",
                "category": "protocol",
                "severity": "medium",
                "cve_references": [],
                "affected_function": "check_authentication in iperf_auth.c",
                "description": "The password hashing scheme uses the username as the only salt: "
                    "SHA256('{username}password'). Usernames are public/predictable, making "
                    "the salt effectively known. This means: (1) Identical passwords for the "
                    "same username always hash identically across different servers, enabling "
                    "cross-system credential correlation. (2) An attacker knowing the username "
                    "can precompute rainbow tables. (3) The format '{user}pass' is a simple "
                    "concatenation vulnerable to length-extension-like ambiguities.",
                "exploitability": "Medium — requires access to the credential store plus "
                    "knowledge of the usernames (which are public in the auth protocol since "
                    "they appear in plaintext in the token format).",
                "impact": "Facilitates targeted password cracking and cross-system credential "
                    "correlation.",
                "recommendation": "Use a cryptographically random salt (>= 16 bytes) "
                    "independent of the username. Store the salt alongside the hash. Modern "
                    "KDFs like Argon2id and bcrypt generate random salts automatically.",
            },
            {
                "id": "VULN-006",
                "title": "No Replay Protection — Timestamp-Only Authentication Without Nonce",
                "category": "protocol",
                "severity": "medium",
                "cve_references": [],
                "affected_function": "check_authentication / encode_auth_setting in iperf_auth.c",
                "description": "Authentication tokens contain only a username, password, and "
                    "timestamp. The server validates the timestamp within a configurable skew "
                    "threshold (10 seconds in this deployment). There is no random nonce, "
                    "sequence number, or session binding. An attacker who intercepts a valid "
                    "token can replay it within the skew window. Since the same RSA keypair "
                    "is used indefinitely and the token contains the actual password, there is "
                    "no mechanism to invalidate a captured token.",
                "exploitability": "Medium — requires network-level interception (ARP spoofing, "
                    "MITM on the internal LAN) and replaying the token within 10 seconds. "
                    "On an internal network (10.0.0.0/8), ARP spoofing is often trivial.",
                "impact": "Unauthorized access via replayed authentication token. The attacker "
                    "gains the same access as the original user without knowing the password.",
                "recommendation": "Include a cryptographically random nonce (>= 16 bytes) in "
                    "each authentication token. The server should maintain a short-lived cache "
                    "of seen nonces and reject duplicates. Consider binding tokens to the "
                    "client's IP address or a session identifier.",
            },
            {
                "id": "VULN-007",
                "title": "Plaintext Password Transmitted in Encrypted Token",
                "category": "protocol",
                "severity": "medium",
                "cve_references": [],
                "affected_function": "encode_auth_setting / auth_text_format in iperf_auth.c",
                "description": "The authentication token embeds the user's plaintext password, "
                    "encrypted under RSA. If the RSA private key is ever compromised (as in "
                    "this scenario), every captured token reveals the user's password in "
                    "cleartext. A more secure design would send a password hash, HMAC, or "
                    "zero-knowledge proof — so that even with key compromise, passwords "
                    "remain protected.",
                "exploitability": "Requires RSA private key compromise (already achieved in "
                    "this engagement) plus access to captured tokens.",
                "impact": "Complete password disclosure for all captured authentication "
                    "sessions. Combined with VULN-004 (weak password hashing), this means "
                    "the entire credential database is effectively compromised.",
                "recommendation": "Send a salted hash or HMAC of the password in the token "
                    "rather than the plaintext. The server can verify by recomputing the same "
                    "hash. This limits exposure even if the RSA key is compromised.",
            },
        ],
        "overall_risk_rating": "critical",
        "risk_justification": "The combination of PKCS#1 v1.5 timing attacks (VULN-001) with "
            "single-round SHA-256 password storage (VULN-004) and plaintext passwords in "
            "tokens (VULN-007) creates a cascading risk: an attacker can recover credentials "
            "from captured tokens via timing analysis, then use the weak password hashing to "
            "crack the entire credential store offline. The deployment on an internal network "
            "with 20 users and OpenSSL 3.0.2 (lacking implicit rejection) makes VULN-001 "
            "directly exploitable. Two additional implementation bugs (VULN-002, VULN-003) "
            "enable denial-of-service attacks that bypass authentication entirely. The "
            "protocol-level weaknesses (no nonce, predictable salt, plaintext password in "
            "token) compound the cryptographic issues to create an overall critical risk "
            "posture for this deployment.",
    }

    with open('/app/security_assessment.json', 'w') as f:
        json.dump(assessment, f, indent=2)

    print("  Vulnerabilities identified: %d" % len(assessment['vulnerabilities']))
    print("  Overall risk: %s" % assessment['overall_risk_rating'])


# ==========================================================================
# Part 3: Credential Migration
# ==========================================================================

def produce_migration(cracked):
    print("\n=== Credential Migration ===")
    import hardened_auth

    migration_result = hardened_auth.migrate_credentials(
        '/app/forensics/authorized_users.csv',
        cracked,
        '/app/migrated_credentials.txt',
    )

    with open('/app/migration_report.json', 'w') as f:
        json.dump(migration_result, f, indent=2)

    print("  Migrated: %d / %d" % (
        migration_result['migrated_count'],
        migration_result['total_users'],
    ))
    print("  Skipped (password unknown): %d" % migration_result['skipped_count'])


# ==========================================================================
# Main
# ==========================================================================

def main():
    cracked = produce_forensics_report()
    produce_security_assessment()
    produce_migration(cracked)
    print("\n=== All deliverables complete ===")


if __name__ == '__main__':
    main()
