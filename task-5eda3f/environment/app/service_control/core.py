"""Core policy-checking engine for the Service Control system.

PolicyChecker is the central component that evaluates every incoming API
request against the project's quota and rate-limit policies.  It reads
policy data from a RegionalDataStore and is protected by a CircuitBreaker
that should allow emergency bypass of all checks.
"""

import logging

from .models import QuotaResult
from .data_store import RegionalDataStore
from .circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class PolicyChecker:
    """Evaluates API requests against quota and rate-limit policies."""

    def __init__(self, data_store: RegionalDataStore,
                 circuit_breaker: CircuitBreaker):
        self.data_store = data_store
        self.circuit_breaker = circuit_breaker
        self._consecutive_failures = 0

    def check_quota(self, project_id: str, api_name: str,
                    request_count: int = 1) -> QuotaResult:
        """Check whether a request is within quota and rate limits.

        Design contract
        ---------------
        * If any check **cannot** be performed (data error, store
          unavailable, etc.) the request MUST be **allowed** — this is
          the fail-open principle.
        * When the circuit breaker is open the method MUST return an
          allow-all result **without** touching the data store.

        Parameters
        ----------
        project_id : str
            Cloud project whose policies should be checked.
        api_name : str
            Fully-qualified API name (e.g. "compute.googleapis.com").
        request_count : int
            Number of requests in this batch (default 1).

        Returns
        -------
        QuotaResult
        """
        try:
            policies = self.data_store.get_policies(project_id)

            for policy in policies:
                if policy.api_name == api_name or policy.api_name == "*":
                    # --- quota check ---
                    remaining = policy.max_requests - policy.current_usage
                    if remaining < request_count:
                        return QuotaResult(
                            allowed=False,
                            reason="quota_exceeded",
                            remaining=max(0, remaining),
                        )

                    # --- rate-limit check ---
                    effective_rate = request_count / policy.rate_limit_window
                    if effective_rate > policy.rate_limit:
                        return QuotaResult(
                            allowed=False,
                            reason="rate_limited",
                            remaining=remaining,
                        )

            if self.circuit_breaker.is_open:
                logger.warning("Circuit breaker is open, bypassing checks")
                return QuotaResult(allowed=True,
                                   reason="circuit_breaker_bypass")

            self._consecutive_failures = 0
            return QuotaResult(allowed=True, remaining=-1)

        except Exception as e:
            self._consecutive_failures += 1
            self.circuit_breaker.record_failure()
            logger.error("PolicyChecker error: %s", e)
            raise
