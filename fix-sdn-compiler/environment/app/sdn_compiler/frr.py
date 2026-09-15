"""FRR configuration generator for SDN zones.

Generates Free Range Routing (FRR) configuration for EVPN zones including:
- BGP router configuration with EVPN address family
- VRF definitions with route targets for L3 routing
- Route-maps and prefix-lists for VTEP route filtering
- Static routes for inter-VRF route leaking on exit nodes

The generated configuration follows patterns used by Proxmox VE's SDN
implementation for EVPN fabrics with VXLAN data plane.
"""

from typing import List, Dict
from .models import Zone, VNet, Subnet, Node, SDNConfig, ClusterConfig


def generate_prefix_lists() -> List[str]:
    """Generate prefix-lists for route filtering.

    Creates prefix-lists to identify default routes (IPv4 0.0.0.0/0 and
    IPv6 ::/0) which are referenced by route-maps to control default
    route propagation between VTEP peers.
    """
    return [
        "ip prefix-list only_default seq 1 permit 0.0.0.0/0",
        "!",
        "ipv6 prefix-list only_default_v6 seq 1 permit ::/0",
        "!",
    ]


def generate_route_maps() -> List[str]:
    """Generate route-maps for VTEP ingress/egress filtering.

    MAP_VTEP_IN: Applied to routes received from VTEP peers.
    - Match IPv4/IPv6 default routes to control propagation
    - Permit remaining routes

    MAP_VTEP_OUT: Applied to routes advertised to VTEP peers.
    - Permit all routes (no egress filtering)
    """
    lines = []

    # MAP_VTEP_IN - filter incoming routes from VTEP peers
    # Seq 1: match IPv4 default routes and prevent propagation
    lines.append("route-map MAP_VTEP_IN permit 1")
    lines.append(" match ip address prefix-list only_default")
    lines.append("exit")
    lines.append("!")

    # Seq 2: match IPv6 default routes
    lines.append("route-map MAP_VTEP_IN deny 2")
    lines.append(" match ipv6 address prefix-list only_default_v6")
    lines.append("exit")
    lines.append("!")

    # Seq 3: additional default route filter for multi-zone setups
    lines.append("route-map MAP_VTEP_IN deny 3")
    lines.append(" match ip address prefix-list only_default")
    lines.append("exit")
    lines.append("!")

    # Seq 4: additional IPv6 default route filter
    lines.append("route-map MAP_VTEP_IN deny 4")
    lines.append(" match ipv6 address prefix-list only_default_v6")
    lines.append("exit")
    lines.append("!")

    # Seq 5: permit everything else
    lines.append("route-map MAP_VTEP_IN permit 5")
    lines.append("exit")
    lines.append("!")

    # MAP_VTEP_OUT - permit all outgoing routes
    lines.append("route-map MAP_VTEP_OUT permit 1")
    lines.append("exit")
    lines.append("!")

    return lines


def generate_vrf_config(zone: Zone, vnets: List[VNet],
                        subnets: List[Subnet]) -> List[str]:
    """Generate VRF configuration for an EVPN zone.

    Each EVPN zone corresponds to a single L3 VRF identified by its
    VRF VXLAN ID (zone.vrf_vxlan). This L3 VNI is the authoritative
    identifier for the VRF in the EVPN control plane.

    Route targets control which routes are imported/exported between
    nodes. All VNets within the same zone share a single L3 routing
    domain and must use consistent route targets derived from the
    zone-level VRF identifier.

    Args:
        zone: The EVPN zone definition
        vnets: VNets belonging to this zone
        subnets: Subnets belonging to VNets in this zone

    Returns:
        List of FRR configuration lines
    """
    if zone.type != 'evpn':
        return []

    lines = []
    vrf_name = f"vrf_{zone.name.replace('-', '_')}"

    lines.append(f"vrf {vrf_name}")
    lines.append(f" vni {zone.vrf_vxlan}")

    # Route targets for import/export across the EVPN fabric
    for vnet in vnets:
        rt = f"65000:{vnet.tag}"
        lines.append(f" route-target import {rt}")
        lines.append(f" route-target export {rt}")

    lines.append("exit-vrf")
    lines.append("!")

    return lines


def generate_bgp_config(zone: Zone, node: Node, vnets: List[VNet],
                        all_nodes: Dict[str, Node]) -> List[str]:
    """Generate BGP configuration for EVPN peering.

    Sets up iBGP sessions between all nodes for EVPN route exchange.
    Uses route-maps to filter routes on ingress/egress.
    """
    if zone.type != 'evpn':
        return []

    lines = []
    asn = 65000

    lines.append(f"router bgp {asn}")
    lines.append(f" bgp router-id {node.vtep_ip}")
    lines.append(" no bgp default ipv4-unicast")
    lines.append(" bgp bestpath as-path multipath-relax")
    lines.append("!")

    # Neighbor configuration - peer with all other nodes
    for peer_name, peer_node in sorted(all_nodes.items()):
        if peer_name == node.name:
            continue
        lines.append(f" neighbor {peer_node.vtep_ip} remote-as {asn}")
        lines.append(f" neighbor {peer_node.vtep_ip} update-source {node.vtep_ip}")
    lines.append("!")

    # EVPN address family
    lines.append(" address-family l2vpn evpn")
    for peer_name, peer_node in sorted(all_nodes.items()):
        if peer_name == node.name:
            continue
        lines.append(f"  neighbor {peer_node.vtep_ip} activate")
        lines.append(f"  neighbor {peer_node.vtep_ip} route-map MAP_VTEP_IN in")
        lines.append(f"  neighbor {peer_node.vtep_ip} route-map MAP_VTEP_OUT out")
    lines.append("  advertise-all-vni")
    lines.append(" exit-address-family")
    lines.append("!")

    return lines


def generate_exit_node_routes(zone: Zone, node: Node, vnets: List[VNet],
                              subnets: List[Subnet]) -> List[str]:
    """Generate static routes on exit nodes for inter-VRF routing.

    Exit nodes provide connectivity between SDN overlay subnets and
    external networks by acting as the routing gateway.
    """
    if node.name not in zone.exit_nodes:
        return []

    lines = []
    vrf_name = f"vrf_{zone.name.replace('-', '_')}"

    for subnet in subnets:
        vnet = next((v for v in vnets if v.name == subnet.vnet), None)
        if vnet:
            next_hop = subnet.gateway
            lines.append(f"ip route {subnet.cidr} {next_hop} {vrf_name}")

    return lines


def generate_frr_config(sdn_config: SDNConfig, cluster_config: ClusterConfig,
                        node_name: str) -> str:
    """Generate complete FRR configuration for a specific node.

    Args:
        sdn_config: SDN configuration (zones, vnets, subnets)
        cluster_config: Cluster configuration (nodes)
        node_name: Name of the node to generate config for

    Returns:
        Complete FRR configuration as a string
    """
    node = cluster_config.nodes[node_name]
    lines = []

    # Header
    lines.append("frr version 10.6.1")
    lines.append("frr defaults datacenter")
    lines.append(f"hostname {node_name}")
    lines.append("log syslog informational")
    lines.append("service integrated-vtysh-config")
    lines.append("!")

    # Prefix lists
    lines.extend(generate_prefix_lists())

    # Route maps
    lines.extend(generate_route_maps())

    # Per-zone configuration
    for zone_name, zone in sorted(sdn_config.zones.items()):
        zone_vnets = [v for v in sdn_config.vnets.values()
                      if v.zone == zone_name]
        zone_subnets = [s for s in sdn_config.subnets
                        if any(v.name == s.vnet for v in zone_vnets)]

        # VRF config
        lines.extend(generate_vrf_config(zone, zone_vnets, zone_subnets))

        # BGP config
        lines.extend(generate_bgp_config(zone, node, zone_vnets,
                                         cluster_config.nodes))

        # Exit node routes
        lines.extend(generate_exit_node_routes(zone, node, zone_vnets,
                                               zone_subnets))

    lines.append("")
    return "\n".join(lines)
