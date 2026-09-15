"""Network interface configuration generator.

Generates Linux networking commands for SDN configuration including:
- VXLAN tunnel interfaces with proper encapsulation settings
- Bridge interfaces for L2 switching within VNets
- VRF interfaces for L3 routing isolation
- IP address assignments for subnet gateways
- SNAT rules for exit node traffic

Follows Proxmox VE SDN patterns for EVPN fabric setup with VXLAN
data plane and distributed anycast gateways.
"""

import hashlib
from typing import List, Dict
from .models import Zone, VNet, Subnet, Node, SDNConfig, ClusterConfig


def generate_vxlan_interface(vnet: VNet, zone: Zone, node: Node) -> List[str]:
    """Generate commands to create a VXLAN interface for a VNet.

    VXLAN interfaces encapsulate L2 frames in UDP packets for overlay
    networking. The local tunnel endpoint address determines which IP
    is used as the outer source for VXLAN-encapsulated packets.

    For EVPN zones, BGP handles remote VTEP discovery so no static
    remote peers are configured on the VXLAN interface itself.

    Args:
        vnet: VNet definition with L2 tag/VNI
        zone: Zone this VNet belongs to
        node: Node to generate config for

    Returns:
        List of shell commands
    """
    cmds = []
    vxlan_name = f"vxlan_{vnet.name.replace('-', '_')}"

    # Create VXLAN interface with local tunnel endpoint
    cmds.append(
        f"ip link add {vxlan_name} type vxlan "
        f"id {vnet.tag} local {node.management_ip} dstport 4789"
    )

    # For non-EVPN zones with static peering, add FDB entries
    if zone.type == 'vxlan':
        for peer_ip in zone.peers:
            if peer_ip != node.management_ip and peer_ip != node.vtep_ip:
                cmds.append(
                    f"bridge fdb append 00:00:00:00:00:00 "
                    f"dev {vxlan_name} dst {peer_ip}"
                )

    cmds.append(f"ip link set {vxlan_name} up")

    return cmds


def generate_bridge_interface(vnet: VNet, zone: Zone, node: Node,
                              subnets: List[Subnet]) -> List[str]:
    """Generate commands to create a bridge for a VNet.

    The bridge provides L2 connectivity between VMs/containers and the
    VXLAN overlay. In EVPN deployments, distributed anycast gateways
    require all nodes to present the same gateway MAC address so that
    VMs see a consistent L3 gateway regardless of their physical host.

    Args:
        vnet: VNet definition
        zone: Zone this VNet belongs to
        node: Node to generate config for
        subnets: Subnets assigned to this VNet

    Returns:
        List of shell commands
    """
    cmds = []
    bridge_name = f"br_{vnet.name.replace('-', '_')}"
    vxlan_name = f"vxlan_{vnet.name.replace('-', '_')}"

    # Create bridge
    cmds.append(f"ip link add {bridge_name} type bridge")
    cmds.append(f"ip link set {bridge_name} up")

    # Set bridge MAC address
    mac_input = f"{node.name}:{bridge_name}"
    mac_hash = hashlib.md5(mac_input.encode()).hexdigest()[:12]
    bridge_mac = ':'.join(mac_hash[i:i+2] for i in range(0, 12, 2))
    cmds.append(f"ip link set {bridge_name} address {bridge_mac}")

    # Add VXLAN interface to bridge
    cmds.append(f"ip link set {vxlan_name} master {bridge_name}")

    # Add VRF membership for EVPN zones
    if zone.type == 'evpn' and zone.vrf_vxlan:
        vrf_name = f"vrf_{zone.name.replace('-', '_')}"
        cmds.append(f"ip link set {bridge_name} master {vrf_name}")

    # Assign gateway IPs from subnets
    for subnet in subnets:
        if subnet.vnet == vnet.name:
            prefix_len = subnet.cidr.split('/')[1]
            cmds.append(
                f"ip addr add {subnet.gateway}/{prefix_len} dev {bridge_name}"
            )

    return cmds


def generate_vrf_interface(zone: Zone) -> List[str]:
    """Generate commands to create a VRF interface for an EVPN zone.

    Creates the VRF device and its associated L3 VXLAN interface
    that carries inter-subnet routed traffic across the fabric.
    """
    if zone.type != 'evpn' or not zone.vrf_vxlan:
        return []

    cmds = []
    vrf_name = f"vrf_{zone.name.replace('-', '_')}"

    # Create VRF device
    cmds.append(f"ip link add {vrf_name} type vrf table auto")
    cmds.append(f"ip link set {vrf_name} up")

    # Create L3 VXLAN for the VRF
    vxlan_vrf = f"vxlan_{vrf_name}"
    cmds.append(
        f"ip link add {vxlan_vrf} type vxlan "
        f"id {zone.vrf_vxlan} local 0.0.0.0 dstport 4789"
    )
    cmds.append(f"ip link set {vxlan_vrf} master {vrf_name}")
    cmds.append(f"ip link set {vxlan_vrf} up")

    return cmds


def generate_snat_rules(subnet: Subnet, zone: Zone,
                        node: Node) -> List[str]:
    """Generate SNAT rules for subnets that need outbound NAT."""
    if not subnet.snat:
        return []
    if node.name not in zone.exit_nodes:
        return []

    cmds = []
    cmds.append(
        f"iptables -t nat -A POSTROUTING -s {subnet.cidr} "
        f"-o eth0 -j MASQUERADE"
    )

    return cmds


def generate_network_config(sdn_config: SDNConfig,
                            cluster_config: ClusterConfig,
                            node_name: str) -> str:
    """Generate complete network configuration commands for a node.

    Produces a shell script with all ip/bridge commands needed to
    configure the SDN overlay network on the specified node.

    Args:
        sdn_config: SDN configuration
        cluster_config: Cluster configuration
        node_name: Node to generate config for

    Returns:
        Shell commands as a string, one per line
    """
    node = cluster_config.nodes[node_name]
    cmds = []

    cmds.append("#!/bin/bash")
    cmds.append(f"# Network configuration for node {node_name}")
    cmds.append("# Generated by SDN compiler")
    cmds.append("")

    for zone_name, zone in sorted(sdn_config.zones.items()):
        cmds.append(f"# Zone: {zone_name} (type: {zone.type})")

        # Create VRF first
        cmds.extend(generate_vrf_interface(zone))
        cmds.append("")

        # Create VXLAN and bridge for each VNet in this zone
        zone_vnets = [v for v in sdn_config.vnets.values()
                      if v.zone == zone_name]
        zone_subnets = [s for s in sdn_config.subnets
                        if any(v.name == s.vnet for v in zone_vnets)]

        for vnet in sorted(zone_vnets, key=lambda v: v.name):
            cmds.append(f"# VNet: {vnet.name} (tag: {vnet.tag})")
            cmds.extend(generate_vxlan_interface(vnet, zone, node))
            cmds.extend(generate_bridge_interface(vnet, zone, node,
                                                  zone_subnets))

            # SNAT rules
            for subnet in zone_subnets:
                if subnet.vnet == vnet.name:
                    cmds.extend(generate_snat_rules(subnet, zone, node))

            cmds.append("")

    return "\n".join(cmds)
