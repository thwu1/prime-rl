#!/usr/bin/env python3
"""Comprehensive fix for the Service Control cascading failure.

Addresses all root causes identified in the post-mortem:
  1. Corrupt policy record in all regional databases
  2. Feature flag name mismatch preventing kill-switch activation
  3. Missing null-safety in _apply_enhanced_quota_check
  4. No exponential backoff with jitter in db_connector retry loop
  5. Connection pool leak of stale connections
  6. No input validation for policy records

"""
import os
import sqlite3


# ── 1. Fix corrupt records in all regional databases ────────────────────

def fix_databases():
    """Remove the corrupt 'internal-quota-sync' record from all regions."""
    for region in ('region1', 'region2', 'region3'):
        db_path = f'/app/data/policies_{region}.db'
        if not os.path.exists(db_path):
            print(f"  SKIP {db_path} (not found)")
            continue
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM policies WHERE service_name = 'internal-quota-sync'"
        )
        conn.commit()
        conn.close()
        print(f"  FIXED {db_path}: removed corrupt record")


# ── 2. Fix feature flag name ────────────────────────────────────────────

def fix_feature_flags():
    """Rename 'enhanced_quota_check' to 'enhanced_quota_checks' in
    flags.yaml so the kill-switch can actually be found by the code."""
    path = '/app/config/flags.yaml'
    with open(path) as fh:
        content = fh.read()

    content = content.replace('enhanced_quota_check:', 'enhanced_quota_checks:')
    # The null-safety fix in policy_loader.py (step 3) is the real
    # protection.  We fix the flag name so the kill switch *could* be
    # used in the future if needed, but leave it disabled since the
    # code now handles bad data gracefully.

    with open(path, 'w') as fh:
        fh.write(content)
    print("  FIXED flags.yaml: renamed flag to 'enhanced_quota_checks'")


# ── 3. Fix policy_loader.py ─────────────────────────────────────────────

def fix_policy_loader():
    """Add null-safety to _apply_enhanced_quota_check and _parse_policy_row,
    plus a validate_policy_record function."""
    path = '/app/service_control/policy_loader.py'

    new_content = '''#!/usr/bin/env python3
"""Policy Loader - Reads quota and policy configurations from regional databases.

Loads policy records from SQLite databases that simulate the globally-replicated
Spanner tables used in the production API management platform.

History:
  2025-05-15  Initial implementation with basic quota/policy loading.
  2025-05-29  Added enhanced quota check for rate-limit tier validation.
  2025-06-12  FIXED: Added null-safety, validation, and fail-open semantics.
"""
import json
import logging
from db_connector import DatabaseConnector

logger = logging.getLogger('service_control.policy_loader')


def validate_policy_record(row):
    """Validate that a raw policy database row has all required fields.

    Returns (True, None) if valid, or (False, reason) if invalid.
    """
    if row is None:
        return False, "row is None"
    if len(row) < 6:
        return False, f"expected 6 columns, got {len(row)}"
    _id, service_name, quota_limit, policy_type, metadata_json, allowed_actions = (
        row[0], row[1], row[2], row[3], row[4], row[5]
    )
    if not service_name:
        return False, "service_name is empty"
    if quota_limit is None:
        return False, "quota_limit is NULL"
    if not metadata_json:
        return False, "metadata_json is empty"
    try:
        metadata = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return False, "metadata_json is not valid JSON"
    if not isinstance(metadata, dict):
        return False, "metadata_json is not a JSON object"
    return True, None


class PolicyLoader:
    """Loads and parses policy records from a regional SQLite database."""

    def __init__(self, db_path, feature_flags):
        self.db_path = db_path
        self.flags = feature_flags
        self.connector = DatabaseConnector(db_path)

    def load_all_policies(self):
        """Load all policy records from the database.

        Returns:
            dict: Mapping of service_name -> policy dict.
        """
        logger.info("Loading all policies from database")
        conn = self.connector.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, service_name, quota_limit, policy_type, "
            "metadata_json, allowed_actions FROM policies"
        )

        policies = {}
        for row in cursor.fetchall():
            logger.info(f"Processing policy for service: {row[1]}")

            # Validate before processing
            valid, reason = validate_policy_record(row)
            if not valid:
                logger.warning(
                    f"Skipping invalid policy record id={row[0]} "
                    f"service={row[1]}: {reason}"
                )
                continue

            try:
                policy = self._parse_policy_row(row)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    f"Failed to parse policy for {row[1]}: {exc}; skipping"
                )
                continue

            if self.flags.is_enabled('enhanced_quota_checks'):
                policy = self._apply_enhanced_quota_check(policy, row)

            policies[policy['service_name']] = policy

        self.connector.return_connection(conn)
        return policies

    def _parse_policy_row(self, row):
        """Parse a raw database row into a policy dict."""
        quota = int(row[2]) if row[2] is not None else 0
        try:
            metadata = json.loads(row[4]) if row[4] else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return {
            'id': row[0],
            'service_name': row[1],
            'quota_limit': quota,
            'quota_remaining': quota,
            'policy_type': row[3],
            'metadata': metadata,
            'allowed_actions': row[5].split(',') if row[5] else ['*'],
        }

    def _apply_enhanced_quota_check(self, policy, row):
        """Apply enhanced quota validation with rate limiting.

        Fails open: if the metadata is missing or malformed the policy
        is returned unchanged rather than crashing the process.
        """
        try:
            metadata = json.loads(row[4]) if row[4] else {}
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                f"Invalid metadata for {policy['service_name']}; "
                "skipping enhanced quota check"
            )
            return policy

        rate_config = metadata.get('rate_limit')
        if not isinstance(rate_config, dict):
            logger.warning(
                f"Missing or invalid rate_limit for "
                f"{policy['service_name']}; skipping enhanced check"
            )
            return policy

        tier = rate_config.get('tier')
        burst = rate_config.get('burst')
        window = rate_config.get('window_seconds')

        if tier is None or burst is None or window is None:
            logger.warning(
                f"Incomplete rate_limit config for "
                f"{policy['service_name']}; skipping enhanced check"
            )
            return policy

        policy['rate_limit_tier'] = tier
        policy['burst_allowance'] = burst
        policy['rate_window_seconds'] = window

        tier_multipliers = {
            'standard': 1.0,
            'premium': 2.0,
            'enterprise': 5.0,
        }
        multiplier = tier_multipliers.get(tier, 1.0)
        policy['quota_limit'] = int(policy['quota_limit'] * multiplier)
        policy['quota_remaining'] = policy['quota_limit']

        return policy
'''

    with open(path, 'w') as fh:
        fh.write(new_content)
    print("  FIXED policy_loader.py: null-safety + validation + fail-open")


# ── 4 & 5. Fix db_connector.py ─────────────────────────────────────────

def fix_db_connector():
    """Add jittered exponential backoff and proper connection cleanup."""
    path = '/app/service_control/db_connector.py'

    new_content = '''#!/usr/bin/env python3
"""Database Connector - Connection pooling for regional policy databases.

Provides a connection pool with jittered exponential backoff for retries.

FIXED 2025-06-12:
  - Added exponential backoff with jitter to prevent thundering herd.
  - Stale connections are now properly closed instead of leaked.
"""
import random
import sqlite3
import time
import logging

logger = logging.getLogger('service_control.db_connector')


class DatabaseConnector:
    """SQLite connection pool with jittered exponential backoff."""

    def __init__(self, db_path, pool_size=5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool = []
        self._max_retries = 10
        self._base_delay = 0.1     # 100ms initial delay
        self._max_delay = 10.0     # cap at 10s

    def get_connection(self):
        """Obtain a database connection from the pool or create a new one.

        Uses jittered exponential backoff on failure to avoid thundering
        herd when many instances restart simultaneously.

        Returns:
            sqlite3.Connection

        Raises:
            ConnectionError: if all retry attempts fail.
        """
        # Try to reuse a pooled connection
        if self._pool:
            conn = self._pool.pop()
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                # Stale connection — close it properly
                try:
                    conn.close()
                except Exception:
                    pass

        # Create a new connection with jittered exponential backoff
        for attempt in range(self._max_retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=5)
                conn.row_factory = sqlite3.Row
                return conn
            except sqlite3.Error as e:
                logger.warning(
                    f"Connection attempt {attempt + 1}/{self._max_retries} "
                    f"failed: {e}"
                )
                # Jittered exponential backoff
                delay = min(
                    self._base_delay * (2 ** attempt)
                    + random.uniform(0, self._base_delay),
                    self._max_delay,
                )
                time.sleep(delay)

        raise ConnectionError(
            f"Failed to connect to {self.db_path} after "
            f"{self._max_retries} attempts"
        )

    def return_connection(self, conn):
        """Return a connection to the pool for reuse."""
        if len(self._pool) < self.pool_size:
            self._pool.append(conn)
        else:
            conn.close()
'''

    with open(path, 'w') as fh:
        fh.write(new_content)
    print("  FIXED db_connector.py: jittered exponential backoff + cleanup")


# ── Main ────────────────────────────────────────────────────────────────

def main():
    print("Applying cascading-failure remediation...\n")

    print("[1/4] Fixing corrupt database records")
    fix_databases()

    print("[2/4] Fixing feature flag configuration")
    fix_feature_flags()

    print("[3/4] Fixing policy_loader.py")
    fix_policy_loader()

    print("[4/4] Fixing db_connector.py")
    fix_db_connector()

    print("\nAll fixes applied.")


if __name__ == '__main__':
    main()
