"""Verify all forensic analysis and threat assessment outputs."""


import base64
import hashlib
import hmac
import json
import os
import sqlite3
import struct
import subprocess


# ---------------------------------------------------------------------------
# Z85 helpers (ZeroMQ RFC 32)
# ---------------------------------------------------------------------------

Z85_CHARS = ("0123456789abcdefghijklmnopqrstuvwxyz"
             "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
             ".-:+=^!/*?&<>()[]{}@%$#")

Z85_MAP = {c: i for i, c in enumerate(Z85_CHARS)}


def z85_decode(s):
    """Decode a z85-encoded string to bytes."""
    assert len(s) % 5 == 0, f"Invalid z85 length: {len(s)}"
    result = bytearray()
    for i in range(0, len(s), 5):
        value = 0
        for j in range(5):
            value = value * 85 + Z85_MAP[s[i + j]]
        result.extend(struct.pack('>I', value))
    return bytes(result)


# ---------------------------------------------------------------------------
# Base64url helpers
# ---------------------------------------------------------------------------

def base64url_decode(s):
    """Base64url decode with automatic padding."""
    s += '=' * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


# ---------------------------------------------------------------------------
# Test: cracked credentials
# ---------------------------------------------------------------------------

def test_cracked_credentials():
    """Every claimed crack is correct, and key accounts are cracked."""
    result_path = '/app/results/cracked_credentials.json'
    assert os.path.exists(result_path), "cracked_credentials.json not found"

    with open(result_path) as f:
        creds = json.load(f)
    assert isinstance(creds, list), "cracked_credentials.json must be a JSON array"

    db_path = '/app/incident/juiceshop.sqlite'
    conn = sqlite3.connect(db_path)

    for cred in creds:
        assert 'email' in cred and 'password' in cred, \
            f"Each entry needs email and password: {cred}"

        row = conn.execute(
            'SELECT password FROM Users WHERE email = ?', (cred['email'],)
        ).fetchone()
        assert row is not None, f"User {cred['email']} not in database"

        computed_hash = hashlib.md5(cred['password'].encode()).hexdigest()
        assert computed_hash == row[0], \
            f"Wrong password for {cred['email']}: md5({cred['password']!r}) = {computed_hash} != {row[0]}"

    conn.close()

    cracked_emails = {c['email'] for c in creds}
    required = {
        'admin@juice-sh.op',
        'jim@juice-sh.op',
        'mc.safesearch@juice-sh.op',
        'accountant@juice-sh.op',
    }
    missing = required - cracked_emails
    assert not missing, f"Required accounts not cracked: {missing}"


# ---------------------------------------------------------------------------
# Test: forged JWT (algorithm confusion RS256 -> HS256)
# ---------------------------------------------------------------------------

def test_forged_token():
    """Forged JWT has correct structure, email, and valid HS256 signature."""
    result_path = '/app/results/forged_token.txt'
    assert os.path.exists(result_path), "forged_token.txt not found"

    with open(result_path) as f:
        token = f.read().strip()

    parts = token.split('.')
    assert len(parts) == 3, f"JWT must have 3 parts, got {len(parts)}"

    # Verify header
    header = json.loads(base64url_decode(parts[0]))
    assert header.get('alg') == 'HS256', \
        f"Expected alg=HS256, got {header.get('alg')}"
    assert header.get('typ') == 'JWT', \
        f"Expected typ=JWT, got {header.get('typ')}"

    # Verify payload
    payload = json.loads(base64url_decode(parts[1]))
    email = payload.get('data', {}).get('email')
    assert email == 'rsa_lord@juice-sh.op', \
        f"Expected email=rsa_lord@juice-sh.op, got {email}"

    # Verify HS256 signature using public key as HMAC secret
    with open('/app/incident/public.pem') as f:
        key = f.read()

    signing_input = (parts[0] + '.' + parts[1]).encode()
    expected_sig = hmac.new(
        key.encode(), signing_input, hashlib.sha256
    ).digest()
    actual_sig = base64url_decode(parts[2])
    assert actual_sig == expected_sig, "JWT HS256 signature is invalid"


# ---------------------------------------------------------------------------
# Test: forged coupon (z85-encoded)
# ---------------------------------------------------------------------------

VALID_MONTHS = {
    'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
    'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
}


def test_forged_coupon():
    """Coupon z85-decodes to valid MMMYY-PP format with discount >= 80%."""
    result_path = '/app/results/forged_coupon.txt'
    assert os.path.exists(result_path), "forged_coupon.txt not found"

    with open(result_path) as f:
        code = f.read().strip()

    assert len(code) > 0, "Coupon code is empty"
    assert len(code) % 5 == 0, f"Invalid z85 length: {len(code)}"

    decoded_bytes = z85_decode(code)
    decoded = decoded_bytes.decode('ascii').rstrip('\x00')

    parts = decoded.split('-')
    assert len(parts) == 2, \
        f"Expected MMMYY-PP format, got: {decoded}"

    month_year = parts[0]
    assert len(month_year) == 5, \
        f"Expected 5-char month+year, got: {month_year}"

    month = month_year[:3]
    year = month_year[3:]
    percentage = int(parts[1])

    assert month in VALID_MONTHS, f"Invalid month: {month}"
    assert year.isdigit() and len(year) == 2, f"Invalid year: {year}"
    assert percentage >= 80, f"Discount {percentage}% is less than required 80%"


# ---------------------------------------------------------------------------
# Test: deleted (soft-erased) accounts
# ---------------------------------------------------------------------------

def test_deleted_accounts():
    """Identifies all soft-deleted accounts from the database."""
    result_path = '/app/results/deleted_accounts.json'
    assert os.path.exists(result_path), "deleted_accounts.json not found"

    with open(result_path) as f:
        accounts = json.load(f)
    assert isinstance(accounts, list), "deleted_accounts.json must be a JSON array"

    # Get ground truth from database
    conn = sqlite3.connect('/app/incident/juiceshop.sqlite')
    rows = conn.execute(
        'SELECT email, deletedAt FROM Users WHERE deletedAt IS NOT NULL'
    ).fetchall()
    conn.close()

    expected = {email for email, _ in rows}
    actual = {a['email'] for a in accounts}

    assert expected == actual, \
        f"Expected deleted accounts {expected}, got {actual}"

    # Verify deletedAt values
    expected_map = {email: dt for email, dt in rows}
    for account in accounts:
        assert account['deletedAt'] == expected_map[account['email']], \
            f"Wrong deletedAt for {account['email']}"


# ---------------------------------------------------------------------------
# Test: decrypted progress data
# ---------------------------------------------------------------------------

def test_decrypted_progress():
    """Decrypted progress matches independent decryption of the encrypted blob."""
    result_path = '/app/results/decrypted_progress.json'
    assert os.path.exists(result_path), "decrypted_progress.json not found"

    # Independent decryption using openssl
    with open('/app/incident/app_config.json') as f:
        config = json.load(f)
    ctf_key = config['challenges']['ctfKey']

    key_hex = hashlib.sha256(ctf_key.encode()).hexdigest()

    with open('/app/incident/encrypted_progress.b64') as f:
        raw = base64.b64decode(f.read().strip())

    iv_hex = raw[:16].hex()
    ciphertext = raw[16:]

    result = subprocess.run(
        ['openssl', 'enc', '-d', '-aes-256-cbc',
         '-K', key_hex, '-iv', iv_hex],
        input=ciphertext, capture_output=True
    )
    assert result.returncode == 0, \
        f"openssl decryption failed: {result.stderr.decode()}"

    expected = json.loads(result.stdout.decode())

    with open(result_path) as f:
        actual = json.load(f)

    assert actual == expected, \
        f"Decrypted progress does not match.\nExpected: {expected}\nActual: {actual}"


# ---------------------------------------------------------------------------
# Test: threat assessment
# ---------------------------------------------------------------------------

def test_threat_assessment():
    """Threat assessment contains valid evaluations with proper structure."""
    result_path = '/app/results/threat_assessment.json'
    assert os.path.exists(result_path), "threat_assessment.json not found"

    with open(result_path) as f:
        assessment = json.load(f)

    assert isinstance(assessment, dict), "threat_assessment.json must be a JSON object"

    # Check overall_risk_score
    assert 'overall_risk_score' in assessment, "Missing overall_risk_score"
    score = assessment['overall_risk_score']
    assert isinstance(score, (int, float)), "overall_risk_score must be numeric"
    assert 1 <= score <= 10, f"overall_risk_score must be 1-10, got {score}"
    # Given critical auth bypass and credential compromise, score must be high
    assert score >= 5, \
        f"overall_risk_score of {score} is unreasonably low given critical auth vulnerabilities"

    # Check prioritized_order
    assert 'prioritized_order' in assessment, "Missing prioritized_order"
    porder = assessment['prioritized_order']
    assert isinstance(porder, list), "prioritized_order must be a list"
    assert len(porder) >= 4, \
        f"prioritized_order must list at least 4 findings, got {len(porder)}"

    # Check findings
    assert 'findings' in assessment, "Missing findings"
    findings = assessment['findings']
    assert isinstance(findings, list), "findings must be a list"
    assert len(findings) >= 4, f"Must have at least 4 findings, got {len(findings)}"

    required_fields = {'title', 'severity', 'attack_complexity',
                       'business_impact', 'remediation'}
    valid_severities = {'critical', 'high', 'medium', 'low'}

    has_critical_or_high = False
    finding_titles = set()
    for i, finding in enumerate(findings):
        assert isinstance(finding, dict), f"Finding {i} must be a dict"
        missing = required_fields - set(finding.keys())
        assert not missing, f"Finding {i} missing fields: {missing}"

        sev = finding['severity'].lower()
        assert sev in valid_severities, \
            f"Finding {i} severity '{finding['severity']}' not valid"

        if sev in ('critical', 'high'):
            has_critical_or_high = True

        finding_titles.add(finding['title'])

        # Each field should have substantive content (not placeholder text)
        for field in ('attack_complexity', 'business_impact', 'remediation'):
            assert len(finding[field]) >= 20, \
                f"Finding {i} '{field}' is too short - provide substantive analysis"

    assert has_critical_or_high, \
        "At least one finding must be rated critical or high severity"

    # All prioritized_order entries must correspond to actual finding titles
    for title in porder:
        assert title in finding_titles, \
            f"Prioritized item '{title}' not found in findings titles"
