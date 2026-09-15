"""
L4 Load Balancer Implementation Stub
=====================================


Implement the LoadBalancer class below. See framework.py for the interface.
"""

from framework import LoadBalancerBase
from typing import Optional


class LoadBalancer(LoadBalancerBase):
    """L4 load balancer with consistent hashing and connection tracking.

    TODO: Implement all abstract methods from LoadBalancerBase.
    """

    def __init__(self):
        raise NotImplementedError("Implement the LoadBalancer")

    def add_service(self, service_id: str) -> None:
        raise NotImplementedError

    def add_backend(
        self, service_id: str, backend_id: str, weight: int = 1
    ) -> None:
        raise NotImplementedError

    def remove_backend(self, service_id: str, backend_id: str) -> None:
        raise NotImplementedError

    def set_backend_health(
        self, service_id: str, backend_id: str, healthy: bool
    ) -> None:
        raise NotImplementedError

    def select_backend(
        self, service_id: str, packet: dict
    ) -> Optional[str]:
        raise NotImplementedError

    def get_lookup_table(self, service_id: str) -> list:
        raise NotImplementedError

    def get_connection_count(self, service_id: str) -> int:
        raise NotImplementedError
