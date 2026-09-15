
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys

import pytest

SOLUTION_FILE = '/app/solution.txt'
REPORT_FILE = '/app/audit_report.json'
DB_PATH = '/app/data/audit.db'
ENGINE_FILE = '/app/remediation/secure_engine.py'
MIGRATE_FILE = '/app/remediation/migrate.py'
KEY_FILE = '/app/remediation/migration_key.bin'

# SHA-256 of the correct token — one-way, so reading this test
# does not reveal the answer.
EXPECTED_HASH = '20bc9407291a5c3734e91e599dabe26e0e7dc580daee60d93f7c8a6bc0b0add1'


# ═══════════════════════════════════════════════════════════════════
#  Helper: load the solver's engine module by file path
# ═══════════════════════════════════════════════════════════════════

def _load_engine_module(alias='secure_engine'):
    spec = importlib.util.spec_from_file_location(alias, ENGINE_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════════════════════════
#  Solution file tests
# ═══════════════════════════════════════════════════════════════════

def test_solution_file_exists():
    assert os.path.isfile(SOLUTION_FILE), (
        f"Expected solution file at {SOLUTION_FILE}"
    )


def test_solution_is_nonempty():
    with open(SOLUTION_FILE, 'r') as fh:
        content = fh.read().strip()
    assert len(content) > 0, "Solution file is empty"


def test_token_format():
    with open(SOLUTION_FILE, 'r') as fh:
        token = fh.read().strip()
    assert token.startswith('tk_'), (
        "Token should start with 'tk_' prefix"
    )


def test_token_correct():
    with open(SOLUTION_FILE, 'r') as fh:
        token = fh.read().strip()
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    assert token_hash == EXPECTED_HASH, (
        "Recovered token does not match expected value"
    )


# ═══════════════════════════════════════════════════════════════════
#  Audit report — structure and classification tests
# ═══════════════════════════════════════════════════════════════════

def _load_report():
    with open(REPORT_FILE, 'r') as fh:
        return json.load(fh)


def test_report_exists():
    assert os.path.isfile(REPORT_FILE), (
        f"Expected audit report at {REPORT_FILE}"
    )


def test_report_valid_json():
    data = _load_report()
    assert isinstance(data, dict), "Report should be a JSON object"


def test_report_has_three_engines():
    data = _load_report()
    assert 'engines' in data, "Report must contain 'engines' key"
    assert len(data['engines']) == 3, (
        f"Report should have exactly 3 engines, got {len(data['engines'])}"
    )


def test_report_engine_fields():
    """Each engine entry must include quantitative risk fields."""
    data = _load_report()
    required = {'version', 'cipher_suite', 'vulnerability_class',
                'weakness_description', 'collision_probability',
                'data_at_risk_count'}
    for eng in data['engines']:
        missing = required - set(eng.keys())
        assert not missing, (
            f"Engine v{eng.get('version', '?')} missing fields: {missing}"
        )


def test_report_collision_probability_types():
    data = _load_report()
    for eng in data['engines']:
        prob = eng['collision_probability']
        assert isinstance(prob, (int, float)), (
            f"v{eng['version']} collision_probability must be numeric"
        )
        assert 0 <= prob <= 1.0, (
            f"v{eng['version']} collision_probability must be in [0,1]"
        )


def test_report_data_at_risk_types():
    data = _load_report()
    for eng in data['engines']:
        count = eng['data_at_risk_count']
        assert isinstance(count, int), (
            f"v{eng['version']} data_at_risk_count must be int"
        )
        assert count >= 0


def test_report_v1_collision_probability_high():
    """ECB is deterministic — collision probability must reflect this."""
    data = _load_report()
    v1 = next((e for e in data['engines'] if e['version'] == 1), None)
    assert v1 is not None, "Engine v1 not found"
    assert v1['collision_probability'] > 0.5, (
        "ECB determinism should yield high collision probability"
    )


def test_report_v1_data_at_risk_matches_db():
    """v1 key was fully recovered — all v1 entries are at risk."""
    data = _load_report()
    v1 = next((e for e in data['engines'] if e['version'] == 1), None)
    assert v1 is not None, "Engine v1 not found"
    conn = sqlite3.connect(DB_PATH)
    actual = conn.execute(
        "SELECT COUNT(*) FROM log_entries WHERE engine_version = 1"
    ).fetchone()[0]
    conn.close()
    assert v1['data_at_risk_count'] == actual, (
        f"v1 data_at_risk_count should be {actual} (all entries recoverable "
        f"via unwrapped key), got {v1['data_at_risk_count']}"
    )


def test_report_v3_collision_probability_negligible():
    """GCM with random 12-byte nonces: birthday bound is negligible."""
    data = _load_report()
    v3 = next((e for e in data['engines'] if e['version'] == 3), None)
    assert v3 is not None, "Engine v3 not found"
    assert v3['collision_probability'] < 1e-10, (
        f"v3 GCM collision probability should be negligible, "
        f"got {v3['collision_probability']}"
    )


def test_report_v3_data_at_risk_zero():
    data = _load_report()
    v3 = next((e for e in data['engines'] if e['version'] == 3), None)
    assert v3 is not None, "Engine v3 not found"
    assert v3['data_at_risk_count'] == 0, (
        f"v3 data_at_risk_count should be 0, got {v3['data_at_risk_count']}"
    )


def test_report_engine_v1_critical():
    data = _load_report()
    v1 = next((e for e in data['engines'] if e['version'] == 1), None)
    assert v1 is not None, "Engine v1 not found in report"
    assert v1['vulnerability_class'] == 'CRITICAL', (
        f"ECB engine v1 should be classified CRITICAL, "
        f"got {v1['vulnerability_class']}"
    )


def test_report_engine_v2_high_or_critical():
    data = _load_report()
    v2 = next((e for e in data['engines'] if e['version'] == 2), None)
    assert v2 is not None, "Engine v2 not found in report"
    assert v2['vulnerability_class'] in ('HIGH', 'CRITICAL'), (
        f"CTR nonce-reuse engine v2 should be classified HIGH or CRITICAL, "
        f"got {v2['vulnerability_class']}"
    )


def test_report_engine_v3_secure():
    data = _load_report()
    v3 = next((e for e in data['engines'] if e['version'] == 3), None)
    assert v3 is not None, "Engine v3 not found in report"
    assert v3['vulnerability_class'] in ('NONE', 'LOW'), (
        f"GCM engine v3 should be classified NONE or LOW, "
        f"got {v3['vulnerability_class']}"
    )


def test_report_recovered_secrets():
    data = _load_report()
    assert 'recovered_secrets' in data, (
        "Report must contain 'recovered_secrets'"
    )
    assert isinstance(data['recovered_secrets'], list)
    assert len(data['recovered_secrets']) > 0
    found = any(
        hashlib.sha256(s.encode('utf-8')).hexdigest() == EXPECTED_HASH
        for s in data['recovered_secrets']
    )
    assert found, (
        "The correct API token was not found in recovered_secrets"
    )


def test_report_recommended_engine():
    data = _load_report()
    assert 'recommended_engine' in data
    assert data['recommended_engine'] == 3, (
        f"Recommended engine should be v3 (GCM), "
        f"got v{data['recommended_engine']}"
    )


# ═══════════════════════════════════════════════════════════════════
#  Remediation engine — design verification
# ═══════════════════════════════════════════════════════════════════

def test_engine_file_exists():
    assert os.path.isfile(ENGINE_FILE), (
        f"Expected secure engine at {ENGINE_FILE}"
    )


def test_engine_uses_hkdf():
    """Engine must derive keys using HKDF."""
    with open(ENGINE_FILE, 'r') as f:
        source = f.read()
    assert 'HKDF' in source, (
        "Engine must use HKDF for key derivation"
    )


def test_engine_uses_gcm():
    """Engine must use AES-GCM for authenticated encryption."""
    with open(ENGINE_FILE, 'r') as f:
        source = f.read()
    assert 'GCM' in source or 'gcm' in source.lower(), (
        "Engine must use AES-GCM"
    )


def test_engine_importable():
    mod = _load_engine_module('se_import')
    assert hasattr(mod, 'SecureEngine'), (
        "Module must expose a SecureEngine class"
    )


def test_engine_encrypt_decrypt_roundtrip():
    """SecureEngine must correctly round-trip arbitrary plaintext."""
    mod = _load_engine_module('se_roundtrip')
    key = os.urandom(32)
    engine = mod.SecureEngine(key, 'test-context')
    messages = [
        b'Hello, World!',
        b'',
        os.urandom(256),
        b'HEARTBEAT|OK|sid=00000001|seq=00000001|ts=1700000000',
    ]
    for pt in messages:
        ct = engine.encrypt(pt)
        recovered = engine.decrypt(ct)
        assert recovered == pt, (
            f"Round-trip failed for {len(pt)}-byte message"
        )


def test_engine_nonce_uniqueness():
    """Each encryption must use a unique random nonce."""
    mod = _load_engine_module('se_nonce')
    key = os.urandom(32)
    engine = mod.SecureEngine(key, 'nonce-test')
    nonces = set()
    for i in range(100):
        ct = engine.encrypt(f"msg-{i}".encode())
        nonce = bytes(ct[:12])
        nonces.add(nonce)
    assert len(nonces) == 100, (
        f"Expected 100 unique nonces, got {len(nonces)}"
    )


def test_engine_context_isolation():
    """Different contexts with the same master key must produce
    different derived keys — decryption must fail across contexts."""
    mod = _load_engine_module('se_ctx')
    key = os.urandom(32)
    engine_a = mod.SecureEngine(key, 'context-alpha')
    engine_b = mod.SecureEngine(key, 'context-beta')
    ct = engine_a.encrypt(b'secret data')
    with pytest.raises(Exception):
        engine_b.decrypt(ct)


# ═══════════════════════════════════════════════════════════════════
#  Migration — execution verification
# ═══════════════════════════════════════════════════════════════════

def test_migrate_script_exists():
    assert os.path.isfile(MIGRATE_FILE), (
        f"Expected migration script at {MIGRATE_FILE}"
    )


def test_migration_key_exists():
    assert os.path.isfile(KEY_FILE), (
        f"Migration master key must be stored at {KEY_FILE}"
    )
    with open(KEY_FILE, 'rb') as f:
        key = f.read()
    assert len(key) == 32, (
        f"Master key must be 32 bytes, got {len(key)}"
    )


def test_migration_table_exists():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='migrated_entries'"
    )
    row = cur.fetchone()
    conn.close()
    assert row is not None, (
        "migrated_entries table must exist in the audit database"
    )


def test_migration_row_count():
    """Every v1 entry must have been migrated."""
    conn = sqlite3.connect(DB_PATH)
    v1_count = conn.execute(
        "SELECT COUNT(*) FROM log_entries WHERE engine_version = 1"
    ).fetchone()[0]
    migrated_count = conn.execute(
        "SELECT COUNT(*) FROM migrated_entries"
    ).fetchone()[0]
    conn.close()
    assert migrated_count == v1_count, (
        f"Expected {v1_count} migrated rows, got {migrated_count}"
    )


def test_migration_references_v1():
    """All migrated entries must reference valid v1 log entries."""
    conn = sqlite3.connect(DB_PATH)
    orphans = conn.execute("""
        SELECT COUNT(*) FROM migrated_entries m
        LEFT JOIN log_entries l
            ON m.original_id = l.id AND l.engine_version = 1
        WHERE l.id IS NULL
    """).fetchone()[0]
    conn.close()
    assert orphans == 0, (
        f"Found {orphans} migrated entries not referencing v1 log entries"
    )


def test_migration_nonces_unique():
    """All migrated ciphertexts must have distinct 12-byte nonce prefixes."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT ciphertext FROM migrated_entries"
    ).fetchall()
    conn.close()
    nonces = set()
    for (ct,) in rows:
        nonce = bytes(ct[:12])
        nonces.add(nonce)
    assert len(nonces) == len(rows), (
        f"Expected {len(rows)} unique nonces, got {len(nonces)}"
    )


def test_migration_entries_decryptable():
    """At least one migrated entry must decrypt to valid plaintext."""
    mod = _load_engine_module('se_migrate_check')
    with open(KEY_FILE, 'rb') as f:
        master_key = f.read()
    engine = mod.SecureEngine(master_key, 'v1-migration')

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT ciphertext FROM migrated_entries LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None, "No migrated entries found"

    plaintext = engine.decrypt(row[0])
    decoded = plaintext.decode('utf-8', errors='replace')
    valid_types = ('AUDIT', 'HEARTBEAT', 'ALERT', 'SECRET', 'ACCESS')
    assert any(decoded.startswith(t) for t in valid_types), (
        f"Decrypted plaintext must start with a valid entry type, "
        f"got: {decoded[:60]}"
    )
