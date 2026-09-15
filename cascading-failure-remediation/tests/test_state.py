"""Tests for cascading failure remediation.

Verifies that all components of the service-control cascading failure
have been properly diagnosed and fixed:
  - Corrupt database records handled
  - Null-safe policy loading
  - Feature flag consistency
  - Exponential backoff with jitter
  - Connection pool cleanup
  - End-to-end service health

"""

import importlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_path():
    """Make sure /app/service_control is importable."""
    sc_path = '/app/service_control'
    if sc_path not in sys.path:
        sys.path.insert(0, sc_path)


def _fresh_import(module_name):
    """(Re)import a module so we always get the latest on-disk version."""
    _ensure_path()
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# 1. Corrupt record handled in all regional databases
# ---------------------------------------------------------------------------

def test_corrupt_record_handled():
    """The corrupt policy record must be removed or its metadata must be
    fixed (non-null rate_limit with valid subfields) in every regional DB."""
    for region in ('region1', 'region2', 'region3'):
        db_path = f'/app/data/policies_{region}.db'
        assert os.path.exists(db_path), f"Database missing: {db_path}"

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT metadata_json FROM policies "
            "WHERE service_name = 'internal-quota-sync'"
        )
        row = cursor.fetchone()
        conn.close()

        if row is not None:
            # Record still exists — its metadata must be valid
            metadata = json.loads(row[0])
            rate_limit = metadata.get('rate_limit')
            assert rate_limit is not None, (
                f"rate_limit is still null in {region}"
            )
            assert isinstance(rate_limit, dict), (
                f"rate_limit is not a dict in {region}"
            )
            assert 'tier' in rate_limit, (
                f"rate_limit missing 'tier' in {region}"
            )
            assert 'burst' in rate_limit, (
                f"rate_limit missing 'burst' in {region}"
            )
            assert 'window_seconds' in rate_limit, (
                f"rate_limit missing 'window_seconds' in {region}"
            )


# ---------------------------------------------------------------------------
# 2. Policy loader does not crash on null metadata
# ---------------------------------------------------------------------------

def test_policy_loader_null_safety():
    """PolicyLoader.load_all_policies must not crash when a policy record
    has null rate_limit metadata."""
    policy_loader = _fresh_import('policy_loader')
    feature_flags = _fresh_import('feature_flags')

    # Build a throwaway DB with deliberately bad records
    test_db = '/tmp/_test_null_safety.db'
    conn = sqlite3.connect(test_db)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE policies ("
        "  id INTEGER PRIMARY KEY, service_name TEXT, quota_limit INTEGER,"
        "  policy_type TEXT, metadata_json TEXT, allowed_actions TEXT)"
    )
    # Record with null rate_limit
    cur.execute(
        "INSERT INTO policies VALUES "
        "(1, 'svc-a', 1000, 'standard', "
        "'{\"rate_limit\": null}', 'read,write')"
    )
    # Record with valid data
    cur.execute(
        "INSERT INTO policies VALUES "
        "(2, 'svc-b', 2000, 'standard', "
        "'{\"rate_limit\": {\"tier\": \"standard\", \"burst\": 50, "
        "\"window_seconds\": 60}}', '*')"
    )
    conn.commit()
    conn.close()

    flags = feature_flags.FeatureFlags('/app/config/flags.yaml')
    loader = policy_loader.PolicyLoader(test_db, flags)

    try:
        policies = loader.load_all_policies()
        assert isinstance(policies, dict), "Expected a dict of policies"
    except (TypeError, KeyError, json.JSONDecodeError, ValueError) as exc:
        pytest.fail(
            f"PolicyLoader still crashes on null metadata: {exc}"
        )
    finally:
        if os.path.exists(test_db):
            os.remove(test_db)


# ---------------------------------------------------------------------------
# 3. Feature-flag name consistency
# ---------------------------------------------------------------------------

def test_feature_flag_consistency():
    """Every flag name referenced via is_enabled() in policy_loader.py must
    exist as a top-level key in flags.yaml."""
    with open('/app/service_control/policy_loader.py') as fh:
        source = fh.read()

    flag_refs = re.findall(r"is_enabled\(['\"]([^'\"]+)['\"]\)", source)
    assert flag_refs, "No is_enabled() calls found in policy_loader.py"

    with open('/app/config/flags.yaml') as fh:
        flags_config = yaml.safe_load(fh)

    for name in flag_refs:
        assert name in flags_config, (
            f"Flag '{name}' used in code but missing from flags.yaml"
        )


# ---------------------------------------------------------------------------
# 4. Exponential backoff with jitter
# ---------------------------------------------------------------------------

def test_backoff_implementation():
    """db_connector.py must implement exponential backoff with jitter in its
    retry loop to prevent thundering-herd effects on recovery."""
    with open('/app/service_control/db_connector.py') as fh:
        source = fh.read()

    # Must have some form of delay between retries
    assert re.search(
        r'time\.sleep|sleep\(|tenacity|backoff|wait_exponential',
        source, re.IGNORECASE
    ), "No sleep / delay mechanism found in db_connector retry logic"

    # Must grow exponentially (or reference 'exponential')
    assert re.search(
        r'2\s*\*\*|pow\s*\(\s*2|exponential|\*\s*2\s*\*\*|\bbase\b.*\*.*attempt',
        source, re.IGNORECASE
    ), "No exponential growth pattern found in retry logic"

    # Must include randomization / jitter
    assert re.search(
        r'random\.|jitter|uniform|randint|random\(\)',
        source, re.IGNORECASE
    ), "No jitter / randomization found in retry logic"


# ---------------------------------------------------------------------------
# 5. Connection pool cleanup
# ---------------------------------------------------------------------------

def test_connection_cleanup():
    """Stale or failed connections must be explicitly closed instead of
    silently leaked."""
    with open('/app/service_control/db_connector.py') as fh:
        source = fh.read()

    # The original code has a bare `pass` after detecting a stale
    # connection. The fix should close it.
    close_calls = len(re.findall(r'\.close\(\)', source))
    assert close_calls >= 2, (
        f"Expected at least 2 .close() calls in db_connector.py, "
        f"found {close_calls}"
    )


# ---------------------------------------------------------------------------
# 6. Service Control starts and responds to health checks
# ---------------------------------------------------------------------------

def test_service_starts_successfully():
    """Service Control must start without crashing and respond to /health."""
    env = {**os.environ, 'INSTANCE_ID': 'test', 'REGION': 'region1',
           'PORT': '15001'}
    proc = subprocess.Popen(
        ['python3', '/app/service_control/server.py'],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(4)
        assert proc.poll() is None, (
            "Service crashed on startup.  stderr:\n"
            + proc.stderr.read().decode(errors='replace')
        )

        import requests
        resp = requests.get('http://localhost:15001/health', timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get('status') == 'healthy'
        assert data.get('policies_loaded', 0) >= 1
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# 7. Quota check API returns valid responses
# ---------------------------------------------------------------------------

def test_quota_check_functional():
    """The /check_quota endpoint must return an 'allowed' verdict for a
    known service."""
    env = {**os.environ, 'INSTANCE_ID': 'test2', 'REGION': 'region1',
           'PORT': '15002'}
    proc = subprocess.Popen(
        ['python3', '/app/service_control/server.py'],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(4)
        assert proc.poll() is None, "Service crashed on startup"

        import requests
        resp = requests.post(
            'http://localhost:15002/check_quota',
            json={'service': 'compute.googleapis.com',
                  'project_id': 'test-project'},
            timeout=5,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert 'allowed' in data, "Response missing 'allowed' field"
        assert data['allowed'] is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)
