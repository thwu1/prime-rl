"""Data models for the Service Control system."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Policy:
    """Represents a quota/rate-limit policy for an API."""
    policy_id: str
    project_id: str
    api_name: str
    max_requests: Optional[int]
    current_usage: int
    rate_limit: Optional[float]        # max requests per window
    rate_limit_window: Optional[float]  # window duration in seconds
    enabled: bool = True


@dataclass
class QuotaResult:
    """Result of a quota/rate-limit check."""
    allowed: bool
    reason: str = ""
    remaining: int = 0


@dataclass
class ReplicationResult:
    """Result of a policy replication operation."""
    region: str
    success: bool
    error: str = ""
