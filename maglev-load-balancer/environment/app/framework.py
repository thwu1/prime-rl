"""
L4 Load Balancer Framework
==========================


Provides the abstract interface and hash utilities for implementing an L4
load balancer with connection tracking.
"""

import hashlib
import struct
from abc import ABC, abstractmethod
from typing import Optional


TABLE_SIZE = 65537  # Lookup table size (prime)


def lb_hash(key: bytes, seed: int) -> int:
    """Deterministic hash function for load balancer operations.

    Args:
        key: Bytes to hash.
        seed: Integer seed for producing independent hash values from the
              same input.

    Returns:
        32-bit unsigned integer hash value.
    """
    h = hashlib.sha256(seed.to_bytes(4, 'big') + key).digest()
    return struct.unpack('>I', h[:4])[0]


def five_tuple_key(packet: dict) -> str:
    """Generate a canonical connection key from a packet's 5-tuple.

    Args:
        packet: Dict with keys src_ip, dst_ip, src_port, dst_port, protocol.

    Returns:
        Pipe-delimited string identifying the flow.
    """
    return (
        f"{packet['src_ip']}|{packet['dst_ip']}|"
        f"{packet['src_port']}|{packet['dst_port']}|{packet['protocol']}"
    )


class LoadBalancerBase(ABC):
    """Abstract base class for an L4 load balancer."""

    @abstractmethod
    def add_service(self, service_id: str) -> None:
        """Register a new virtual service. No-op if already exists."""

    @abstractmethod
    def add_backend(
        self, service_id: str, backend_id: str, weight: int = 1
    ) -> None:
        """Add a healthy backend to a service and rebuild the lookup table."""

    @abstractmethod
    def remove_backend(self, service_id: str, backend_id: str) -> None:
        """Remove a backend entirely from a service."""

    @abstractmethod
    def set_backend_health(
        self, service_id: str, backend_id: str, healthy: bool
    ) -> None:
        """Update backend health status and rebuild the lookup table."""

    @abstractmethod
    def select_backend(
        self, service_id: str, packet: dict
    ) -> Optional[str]:
        """Select a backend for the given packet.

        Returns backend id string, or None if no backend is available.
        """

    @abstractmethod
    def get_lookup_table(self, service_id: str) -> list:
        """Return the current lookup table as a list of backend id strings."""

    @abstractmethod
    def get_connection_count(self, service_id: str) -> int:
        """Return the number of currently tracked connections."""
