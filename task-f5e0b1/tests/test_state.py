"""
Verify the iperf3 auth security audit: forensic analysis, vulnerability
assessment, hardened auth module, and credential migration.

Tests independently compute ground truth for forensics and verify all
four deliverables.
"""

import json
import hashlib
import base64
import os
import re
import sys
import tempfile
import pytest
from collections import defaultdict
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iperf3_password_hash(username, password):
    """Reproduce iperf3's salting: SHA256('{username}password')"""
    salted = "{%s}%s" % (username, password)
    return hashlib.sha256(salted.encode()).hexdigest()


def load_private_key():
    with open('/app/forensics/private.pem', 'rb') as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def load_authorized_users():
    users = {}
    with open('/app/forensics/authorized_users.csv') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',', 1)
            if len(parts) == 2:
                users[parts[0]] = parts[1]
    return users


def decrypt_and_parse_token(token_b64, private_key):
    encrypted = base64.b64decode(token_b64)
    plaintext = private_key.decrypt(encrypted, asym_padding.PKCS1v15()).decode('utf-8')
    lines = plaintext.split('\n')
    username = lines[0][len('user: '):]
    password = lines[1][len('pwd:  '):]
    timestamp = int(lines[2][len('ts:   '):])
    return username, password, timestamp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def forensics_report():
    assert os.path.exists('/app/forensics_report.json'), \
        "/app/forensics_report.json not found"
    with open('/app/forensics_report.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def ground_truth():
    """Independently compute ground truth."""
    private_key = load_private_key()
    auth_users = load_authorized_users()

    with open('/app/forensics/captured_tokens.json') as f:
        tokens = json.load(f)

    decoded_tokens = []
    for t in tokens:
        username, password, timestamp = decrypt_and_parse_token(t['token'], private_key)
        valid_user = username in auth_users
        valid_creds = False
        if valid_user:
            valid_creds = iperf3_password_hash(username, password) == auth_users[username]
        decoded_tokens.append({
            'id': t['id'],
            'username': username,
            'password': password,
            'timestamp': timestamp,
            'valid_user': valid_user,
            'valid_credentials': valid_creds,
        })

    cracked = {}
    with open('/app/forensics/wordlist.txt') as f:
        wordlist = [line.strip() for line in f if line.strip()]
    for username, expected_hash in auth_users.items():
        for word in wordlist:
            if iperf3_password_hash(username, word) == expected_hash:
                cracked[username] = word
                break

    pw_to_users = defaultdict(list)
    for u, p in cracked.items():
        pw_to_users[p].append(u)
    shared = sorted(
        [sorted(users) for users in pw_to_users.values() if len(users) > 1]
    )

    return {
        'tokens': decoded_tokens,
        'cracked': cracked,
        'auth_users': auth_users,
        'shared': shared,
    }


# ---------------------------------------------------------------------------
# 1. Forensics Report Tests
# ---------------------------------------------------------------------------

class TestForensicsStructure:
    def test_report_exists(self):
        assert os.path.exists('/app/forensics_report.json')

    def test_has_required_sections(self, forensics_report):
        for key in ('tokens', 'password_audit', 'shared_passwords', 'timeline'):
            assert key in forensics_report, f"Missing section: {key}"


class TestTokenDecryption:
    def test_all_tokens_present(self, forensics_report, ground_truth):
        assert len(forensics_report['tokens']) == len(ground_truth['tokens'])

    def test_token_usernames(self, forensics_report, ground_truth):
        for gt in ground_truth['tokens']:
            rt = next((t for t in forensics_report['tokens'] if t['id'] == gt['id']), None)
            assert rt is not None, f"Token {gt['id']} missing"
            assert rt['username'] == gt['username'], \
                f"Token {gt['id']}: expected user '{gt['username']}', got '{rt.get('username')}'"

    def test_token_passwords(self, forensics_report, ground_truth):
        for gt in ground_truth['tokens']:
            rt = next((t for t in forensics_report['tokens'] if t['id'] == gt['id']), None)
            assert rt is not None
            assert rt['password'] == gt['password']

    def test_token_timestamps(self, forensics_report, ground_truth):
        for gt in ground_truth['tokens']:
            rt = next((t for t in forensics_report['tokens'] if t['id'] == gt['id']), None)
            assert rt is not None
            assert rt['timestamp'] == gt['timestamp']

    def test_valid_user_flags(self, forensics_report, ground_truth):
        for gt in ground_truth['tokens']:
            rt = next((t for t in forensics_report['tokens'] if t['id'] == gt['id']), None)
            assert rt is not None
            assert rt['valid_user'] == gt['valid_user'], \
                f"Token {gt['id']} ({gt['username']}): valid_user={gt['valid_user']}"

    def test_valid_credentials_flags(self, forensics_report, ground_truth):
        for gt in ground_truth['tokens']:
            rt = next((t for t in forensics_report['tokens'] if t['id'] == gt['id']), None)
            assert rt is not None
            assert rt['valid_credentials'] == gt['valid_credentials'], \
                f"Token {gt['id']} ({gt['username']}): valid_credentials={gt['valid_credentials']}"


class TestPasswordAudit:
    def test_all_crackable_found(self, forensics_report, ground_truth):
        report_cracked = set(forensics_report['password_audit']['cracked'].keys())
        expected = set(ground_truth['cracked'].keys())
        missing = expected - report_cracked
        assert not missing, f"Failed to crack: {missing}"

    def test_cracked_values_match(self, forensics_report, ground_truth):
        for user, expected_pw in ground_truth['cracked'].items():
            reported = forensics_report['password_audit']['cracked'].get(user)
            assert reported == expected_pw, \
                f"Wrong pw for '{user}': expected '{expected_pw}', got '{reported}'"

    def test_shared_passwords(self, forensics_report, ground_truth):
        report_shared = sorted(
            [sorted(g) for g in forensics_report['shared_passwords']]
        )
        assert report_shared == ground_truth['shared']


class TestTimeline:
    def test_chronological_order(self, forensics_report, ground_truth):
        expected = [t['id'] for t in sorted(ground_truth['tokens'], key=lambda x: x['timestamp'])]
        assert forensics_report['timeline']['chronological_order'] == expected

    def test_anomalous_gap_detected(self, forensics_report):
        gaps = forensics_report['timeline']['anomalous_gaps']
        assert len(gaps) >= 1, "Should detect at least one anomalous gap"
        pairs = [tuple(g['between_tokens']) for g in gaps]
        assert (6, 1) in pairs, f"Gap between tokens 6→1 should be flagged. Got: {pairs}"

    def test_anomalous_gap_size(self, forensics_report):
        for gap in forensics_report['timeline']['anomalous_gaps']:
            if tuple(gap['between_tokens']) == (6, 1):
                assert gap['gap_seconds'] == 10000


# ---------------------------------------------------------------------------
# 2. Security Assessment Tests
# ---------------------------------------------------------------------------

REQUIRED_VULN_PATTERNS = [
    {
        "name": "RSA PKCS1v1.5 timing/padding attack",
        "patterns": [
            r"pkcs.?1", r"timing", r"marvin", r"bleichenbacher",
            r"padding.?oracle", r"side.?channel",
        ],
        "expected_cve": "CVE-2024-26306",
    },
    {
        "name": "Off-by-one heap overflow in decryption",
        "patterns": [
            r"off.?by.?one", r"heap.?(overflow|corrupt)",
            r"buffer.?overflow", r"null.?terminat",
        ],
        "expected_cve": "CVE-2025-54349",
    },
    {
        "name": "Malformed base64 assertion crash",
        "patterns": [
            r"base64", r"malformed.{0,20}(token|auth)",
            r"assertion.{0,20}crash", r"denial.?of.?service",
        ],
        "expected_cve": "CVE-2025-54350",
    },
    {
        "name": "Weak password hashing (no KDF)",
        "patterns": [
            r"sha.?256.{0,30}(weak|fast|no.?kdf|single|iteration|brute)",
            r"key.?derivation", r"password.?hash.{0,20}(weak|insecure|fast)",
            r"(bcrypt|argon|scrypt|pbkdf).{0,20}(missing|absent|should|instead)",
            r"no.{0,10}(kdf|key.?derivation|iteration|stretching)",
        ],
        "expected_cve": None,
    },
    {
        "name": "Predictable salt derived from username",
        "patterns": [
            r"(username|user.?name).{0,20}salt",
            r"predictable.{0,20}salt",
            r"salt.{0,20}(public|predictable|username|known|weak)",
        ],
        "expected_cve": None,
    },
    {
        "name": "No replay protection / missing nonce",
        "patterns": [
            r"replay",
            r"no.{0,10}nonce",
            r"nonce.{0,20}(missing|absent|lack)",
            r"timestamp.{0,20}(only|insufficient|replay|window)",
        ],
        "expected_cve": None,
    },
]


class TestSecurityAssessment:
    @pytest.fixture(scope='class')
    def assessment(self):
        assert os.path.exists('/app/security_assessment.json'), \
            "security_assessment.json not found"
        with open('/app/security_assessment.json') as f:
            return json.load(f)

    def test_has_vulnerabilities(self, assessment):
        assert 'vulnerabilities' in assessment
        assert isinstance(assessment['vulnerabilities'], list)
        assert len(assessment['vulnerabilities']) >= 6, \
            f"Expected >=6 vulnerabilities, found {len(assessment['vulnerabilities'])}"

    def test_required_vulns_identified(self, assessment):
        """Each required vulnerability category must be covered."""
        vulns = assessment['vulnerabilities']
        for req in REQUIRED_VULN_PATTERNS:
            found = False
            for v in vulns:
                searchable = ' '.join([
                    v.get('title', ''),
                    v.get('description', ''),
                    v.get('category', ''),
                    v.get('recommendation', ''),
                ]).lower()
                if any(re.search(p, searchable, re.IGNORECASE) for p in req['patterns']):
                    found = True
                    break
            assert found, f"Required vulnerability not identified: {req['name']}"

    def test_cve_cross_references(self, assessment):
        """Known CVEs must be referenced."""
        required_cves = {'CVE-2024-26306', 'CVE-2025-54349', 'CVE-2025-54350'}
        found_cves = set()
        for v in assessment['vulnerabilities']:
            refs = v.get('cve_references', [])
            if isinstance(refs, str):
                refs = [refs]
            for ref in refs:
                found_cves.add(ref.upper().strip())
        for cve in required_cves:
            assert cve in found_cves, f"CVE {cve} not referenced"

    def test_severity_ratings_valid(self, assessment):
        valid = {'critical', 'high', 'medium', 'low'}
        for v in assessment['vulnerabilities']:
            sev = v.get('severity', '').lower()
            assert sev in valid, \
                f"Invalid severity '{sev}' for '{v.get('title', '?')}'"

    def test_overall_risk_rating(self, assessment):
        assert 'overall_risk_rating' in assessment
        assert assessment['overall_risk_rating'].lower() in {'critical', 'high', 'medium', 'low'}
        assert 'risk_justification' in assessment
        assert len(assessment['risk_justification']) > 20, \
            "Risk justification too short"


# ---------------------------------------------------------------------------
# 3. Hardened Auth Module Tests
# ---------------------------------------------------------------------------

class TestHardenedAuth:
    @pytest.fixture(scope='class')
    def mod(self):
        assert os.path.exists('/app/hardened_auth.py'), \
            "Agent must create /app/hardened_auth.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "hardened_auth", "/app/hardened_auth.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_has_required_functions(self, mod):
        required = [
            'generate_keypair', 'encode_token', 'decode_token',
            'create_credential_store', 'verify_credentials',
            'migrate_credentials',
        ]
        for fn in required:
            assert hasattr(mod, fn), f"Missing function: {fn}"

    def test_roundtrip_encode_decode(self, mod):
        """Encode then decode must recover original credentials."""
        priv, pub = mod.generate_keypair()
        token = mod.encode_token("alice", "s3cret!Pass", pub)
        result = mod.decode_token(token, priv)
        assert result['username'] == "alice"
        assert result['password'] == "s3cret!Pass"
        assert 'timestamp' in result
        assert 'nonce' in result

    def test_uses_oaep_not_pkcs1(self, mod):
        """Tokens must use OAEP padding — PKCS1v1.5 decryption must not recover plaintext."""
        priv_pem, pub_pem = mod.generate_keypair()
        token = mod.encode_token("oaep_probe_user", "oaep_probe_pw", pub_pem)

        encrypted = base64.b64decode(token)
        priv_bytes = priv_pem if isinstance(priv_pem, bytes) else priv_pem.encode()
        priv_key = serialization.load_pem_private_key(priv_bytes, password=None)

        # Attempting PKCS1v1.5 decryption on OAEP ciphertext should fail
        # or produce garbage that doesn't contain the original username
        pkcs1_recovered_plaintext = False
        try:
            result = priv_key.decrypt(encrypted, asym_padding.PKCS1v15())
            text = result.decode('utf-8', errors='replace')
            if 'oaep_probe_user' in text:
                pkcs1_recovered_plaintext = True
        except Exception:
            pass  # Expected: PKCS1v1.5 fails on OAEP data

        assert not pkcs1_recovered_plaintext, \
            "Token was decryptable with PKCS1v1.5 — must use OAEP"

    def test_nonce_uniqueness(self, mod):
        """Identical inputs must produce different tokens (nonce randomness)."""
        priv, pub = mod.generate_keypair()
        t1 = mod.encode_token("user", "pass", pub)
        t2 = mod.encode_token("user", "pass", pub)
        assert t1 != t2, "Same inputs produced identical tokens — no nonce?"

    def test_decoded_token_has_nonce(self, mod):
        """Decoded token must contain a nonce field."""
        priv, pub = mod.generate_keypair()
        token = mod.encode_token("user", "pass", pub)
        result = mod.decode_token(token, priv)
        assert 'nonce' in result
        assert result['nonce'] is not None
        assert len(str(result['nonce'])) > 0

    def test_credential_store_uses_kdf(self, mod):
        """Password hashes must not be raw SHA256 (64 hex chars)."""
        store = tempfile.mktemp(suffix='.store')
        mod.create_credential_store({"bob": "hunter2"}, store)
        with open(store) as f:
            content = f.read()
        for line in content.strip().split('\n'):
            if not line or line.startswith('#'):
                continue
            parts = line.split(',', 1)
            if len(parts) == 2:
                h = parts[1].strip()
                is_sha256 = (
                    len(h) == 64
                    and all(c in '0123456789abcdef' for c in h.lower())
                )
                assert not is_sha256, \
                    f"Hash looks like raw SHA256 — must use argon2id or bcrypt"

    def test_verify_correct_password(self, mod):
        store = tempfile.mktemp(suffix='.store')
        mod.create_credential_store({"carol": "p@ssW0rd"}, store)
        assert mod.verify_credentials("carol", "p@ssW0rd", store) is True

    def test_verify_wrong_password(self, mod):
        store = tempfile.mktemp(suffix='.store')
        mod.create_credential_store({"carol": "p@ssW0rd"}, store)
        assert mod.verify_credentials("carol", "wrong", store) is False

    def test_verify_nonexistent_user(self, mod):
        store = tempfile.mktemp(suffix='.store')
        mod.create_credential_store({"carol": "p@ssW0rd"}, store)
        assert mod.verify_credentials("nobody", "p@ssW0rd", store) is False


# ---------------------------------------------------------------------------
# 4. Credential Migration Tests
# ---------------------------------------------------------------------------

class TestCredentialMigration:
    def test_migrated_store_exists(self):
        assert os.path.exists('/app/migrated_credentials.txt'), \
            "migrated_credentials.txt not found"

    def test_migration_report_exists(self):
        assert os.path.exists('/app/migration_report.json'), \
            "migration_report.json not found"

    def test_migrated_hashes_not_sha256(self):
        with open('/app/migrated_credentials.txt') as f:
            entries = 0
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(',', 1)
                if len(parts) == 2:
                    entries += 1
                    h = parts[1].strip()
                    is_sha256 = (
                        len(h) == 64
                        and all(c in '0123456789abcdef' for c in h.lower())
                    )
                    assert not is_sha256, \
                        f"Migrated hash for '{parts[0]}' is raw SHA256"
            assert entries > 0, "No entries in migrated_credentials.txt"

    def test_migration_report_counts(self):
        with open('/app/migration_report.json') as f:
            report = json.load(f)
        assert 'migrated_count' in report
        assert 'total_users' in report
        assert report['total_users'] == 20
        assert report['migrated_count'] > 0

    def test_cracked_users_migrated(self, ground_truth):
        """All crackable users must be in the migrated store."""
        migrated_users = set()
        with open('/app/migrated_credentials.txt') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(',', 1)
                if len(parts) == 2:
                    migrated_users.add(parts[0])
        for username in ground_truth['cracked']:
            assert username in migrated_users, \
                f"Cracked user '{username}' missing from migrated store"

    def test_migration_count_matches_cracked(self, ground_truth):
        with open('/app/migration_report.json') as f:
            report = json.load(f)
        assert report['migrated_count'] == len(ground_truth['cracked']), \
            f"Expected {len(ground_truth['cracked'])} migrated, got {report['migrated_count']}"
