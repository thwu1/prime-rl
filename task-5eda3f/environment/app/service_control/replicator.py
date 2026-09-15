"""Policy data replicator.

Replicates policy updates across all regional data stores so that quota
enforcement is consistent globally.  Data integrity is paramount —
corrupt or incomplete policy records propagating to every region can
cause Service Control to malfunction worldwide.
"""

import logging
from typing import Dict, List, Optional, Tuple

from .data_store import RegionalDataStore

logger = logging.getLogger(__name__)

REQUIRED_POLICY_FIELDS = [
    'policy_id', 'project_id', 'api_name',
    'max_requests', 'rate_limit', 'rate_limit_window',
]


class DataReplicator:
    """Replicates policy data to regional stores."""

    def __init__(self, regional_stores: Dict[str, RegionalDataStore]):
        self.regional_stores = regional_stores
        self._replication_log: list = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def replicate(self, policy_data: dict,
                  target_regions: Optional[List[str]] = None) -> Dict[str, bool]:
        """Replicate *policy_data* to every target region.

        Returns a dict mapping region name -> success boolean.
        """
        if target_regions is None:
            target_regions = list(self.regional_stores.keys())

        results: Dict[str, bool] = {}

        for region in target_regions:
            if region not in self.regional_stores:
                logger.warning("Unknown region: %s", region)
                results[region] = False
                continue

            try:
                store = self.regional_stores[region]
                store.insert_policy(policy_data)
                results[region] = True
                self._replication_log.append({
                    'region': region,
                    'policy_id': policy_data.get('policy_id'),
                    'status': 'success',
                })
                logger.info("Replicated policy %s to %s",
                            policy_data.get('policy_id'), region)
            except Exception as e:
                results[region] = False
                self._replication_log.append({
                    'region': region,
                    'policy_id': policy_data.get('policy_id'),
                    'status': 'failed',
                    'error': str(e),
                })
                logger.error("Failed to replicate to %s: %s", region, e)

        return results

    # ------------------------------------------------------------------
    # Validation helper
    # ------------------------------------------------------------------

    def validate_policy_data(self, policy_data: dict) -> Tuple[bool, str]:
        """Validate that *policy_data* is safe to replicate.

        Returns ``(is_valid, error_message)``.
        """
        errors: List[str] = []

        for field in REQUIRED_POLICY_FIELDS:
            if field not in policy_data:
                errors.append(f"Missing required field: {field}")
            elif policy_data[field] is None:
                errors.append(f"Field '{field}' cannot be None")

        # Numeric sanity
        for field in ('max_requests', 'rate_limit', 'rate_limit_window'):
            val = policy_data.get(field)
            if val is not None:
                try:
                    if float(val) <= 0:
                        errors.append(
                            f"Field '{field}' must be positive, got {val}")
                except (ValueError, TypeError):
                    errors.append(
                        f"Field '{field}' must be numeric, got {val}")

        if errors:
            return False, "; ".join(errors)
        return True, ""
