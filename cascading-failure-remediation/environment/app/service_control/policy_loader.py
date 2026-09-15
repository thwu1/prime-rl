#!/usr/bin/env python3
"""Policy Loader - Reads quota and policy configurations from regional databases.

Loads policy records from SQLite databases that simulate the globally-replicated
Spanner tables used in the production API management platform.  Each policy
record contains quota limits, allowed actions, and metadata for a specific
Google Cloud service.

History:
  2025-05-15  Initial implementation with basic quota/policy loading.
  2025-05-29  Added enhanced quota check for additional rate-limit tier
              validation (see _apply_enhanced_quota_check).
  2025-06-12  <<< CURRENT STATE: crash-looping due to bad policy data >>>
"""
import json
import logging
from db_connector import DatabaseConnector

logger = logging.getLogger('service_control.policy_loader')


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
            policy = self._parse_policy_row(row)
            if self.flags.is_enabled('enhanced_quota_checks'):
                policy = self._apply_enhanced_quota_check(policy, row)
            policies[policy['service_name']] = policy

        self.connector.return_connection(conn)
        return policies

    def _parse_policy_row(self, row):
        """Parse a raw database row into a policy dict."""
        return {
            'id': row[0],
            'service_name': row[1],
            'quota_limit': int(row[2]),
            'quota_remaining': int(row[2]),
            'policy_type': row[3],
            'metadata': json.loads(row[4]),
            'allowed_actions': row[5].split(',') if row[5] else ['*']
        }

    def _apply_enhanced_quota_check(self, policy, row):
        """Apply enhanced quota validation with rate limiting.

        Added 2025-05-29 for additional policy compliance checks.  Performs
        deeper validation of quota metadata including rate-limit tiers and
        burst allowances so that tier-based multipliers can be applied.

        NOTE: this code path was introduced without feature-flag gating and
        without defensive null checks on the metadata fields.
        """
        metadata = json.loads(row[4])
        rate_config = metadata['rate_limit']

        policy['rate_limit_tier'] = rate_config['tier']
        policy['burst_allowance'] = rate_config['burst']
        policy['rate_window_seconds'] = rate_config['window_seconds']

        # Apply tier-based quota adjustment
        tier_multipliers = {
            'standard': 1.0,
            'premium': 2.0,
            'enterprise': 5.0,
        }
        multiplier = tier_multipliers.get(rate_config['tier'], 1.0)
        policy['quota_limit'] = int(policy['quota_limit'] * multiplier)
        policy['quota_remaining'] = policy['quota_limit']

        return policy
