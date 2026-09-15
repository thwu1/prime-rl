"""
Identity resolver for the Cilium eBPF datapath simulator.

Maps IP addresses to numeric security identities used for policy
enforcement. Endpoint addresses are mapped directly via the endpoint
table. External addresses are resolved using CIDR identity ranges.

CIDR identity resolution semantics (from Cilium):
  - Multiple CIDR ranges can overlap (e.g., 192.168.0.0/16 and 192.168.1.0/24)
  - Resolution MUST use longest-prefix-match (LPM): the most specific
    matching prefix determines the identity
  - If no CIDR range matches, the address gets WORLD_ID (2)
"""

import ipaddress
from typing import List


WORLD_ID = 2
HOST_ID = 1


class CIDRIdentityEntry:
    """A CIDR range mapped to a security identity."""
    def __init__(self, cidr: str, prefix_len: int, identity: int):
        self.network = ipaddress.IPv4Network(f"{cidr}/{prefix_len}", strict=False)
        self.prefix_len = prefix_len
        self.identity = identity


class IdentityResolver:
    """Resolves IP addresses to security identities."""

    def __init__(self):
        self._endpoints = {}  # addr -> identity
        self._cidr_entries: List[CIDRIdentityEntry] = []

    def add_endpoint(self, addr: str, identity: int):
        """Register a known endpoint address."""
        self._endpoints[addr] = identity

    def add_cidr_identity(self, cidr: str, prefix_len: int, identity: int):
        """Register a CIDR range to identity mapping."""
        self._cidr_entries.append(CIDRIdentityEntry(cidr, prefix_len, identity))

    def resolve(self, addr: str) -> int:
        """Resolve an IP address to its security identity.

        Checks endpoint table first (exact match), then CIDR ranges.
        """
        if addr in self._endpoints:
            return self._endpoints[addr]
        return self._resolve_cidr(addr)

    def _resolve_cidr(self, addr: str) -> int:
        """Resolve an IP via CIDR identity ranges using longest-prefix-match.

        When multiple CIDR ranges match an address, the range with the
        longest prefix length (most specific) must win. For example:
          - 192.168.0.0/16 -> identity 5001
          - 192.168.1.0/24 -> identity 5002
          - resolve(192.168.1.5) MUST return 5002 (not 5001)
        """
        ip = ipaddress.IPv4Address(addr)
        for entry in self._cidr_entries:
            if ip in entry.network:
                return entry.identity
        return WORLD_ID
