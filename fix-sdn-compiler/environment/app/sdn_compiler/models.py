"""Data models for SDN configuration.

Represents the configuration objects used in Proxmox VE SDN:
- Nodes: Physical cluster members with management and VTEP IPs
- Zones: Network isolation domains (Simple, VXLAN, or EVPN)
- VNets: Virtual networks within zones, identified by VXLAN tags
- Subnets: IP subnets assigned to VNets with gateway addresses
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class Node:
    """A cluster node with management and VTEP addresses."""
    name: str
    management_ip: str
    vtep_ip: str


@dataclass
class Zone:
    """An SDN zone defining a network isolation domain.

    For EVPN zones:
    - vrf_vxlan: L3 VNI identifying the VRF across all nodes
    - peers: List of peer node IPs for EVPN peering
    - anycast_mac: Shared gateway MAC for distributed anycast gateway
    - exit_nodes: Nodes that route traffic out of the overlay
    """
    name: str
    type: str  # 'simple', 'vxlan', 'evpn'
    vrf_vxlan: Optional[int] = None
    peers: List[str] = field(default_factory=list)
    anycast_mac: Optional[str] = None
    exit_nodes: List[str] = field(default_factory=list)
    controller: Optional[str] = None


@dataclass
class VNet:
    """A virtual network within a zone.

    The tag serves as the L2 VXLAN Network Identifier (VNI) for this
    specific virtual network segment. Multiple VNets can exist within
    the same zone, sharing the zone's L3 VRF but having separate L2
    broadcast domains.
    """
    name: str
    zone: str
    tag: int
    alias: Optional[str] = None


@dataclass
class Subnet:
    """An IP subnet assigned to a VNet."""
    cidr: str
    vnet: str
    gateway: str
    snat: bool = False
    dns_zone_prefix: Optional[str] = None


@dataclass
class ClusterConfig:
    """Cluster-level configuration with all nodes."""
    nodes: Dict[str, Node]


@dataclass
class SDNConfig:
    """Complete SDN configuration with zones, vnets, and subnets."""
    zones: Dict[str, Zone]
    vnets: Dict[str, VNet]
    subnets: List[Subnet]
