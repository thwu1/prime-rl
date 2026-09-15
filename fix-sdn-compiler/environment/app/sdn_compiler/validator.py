"""SDN configuration validator.

Validates SDN configurations for correctness, including:
- Zone reference integrity (VNets reference existing zones)
- VNet reference integrity (Subnets reference existing VNets)
- Subnet CIDR validity and gateway address correctness
- EVPN zone completeness (required fields present)
- Tag/VNI uniqueness within zones
- Exit node and peer membership in the cluster
"""

import ipaddress
from typing import List, Tuple
from .models import SDNConfig, ClusterConfig, Zone, VNet, Subnet


def validate_zone(zone: Zone) -> List[str]:
    """Validate a zone definition.

    Returns list of error messages (empty if valid).
    """
    errors = []

    if zone.type not in ('simple', 'vxlan', 'evpn'):
        errors.append(f"Zone '{zone.name}': unknown type '{zone.type}'")

    if zone.type == 'evpn':
        if not zone.vrf_vxlan:
            errors.append(
                f"Zone '{zone.name}': EVPN zone requires vrf_vxlan"
            )
        if zone.vrf_vxlan and (zone.vrf_vxlan < 1 or zone.vrf_vxlan > 16777215):
            errors.append(
                f"Zone '{zone.name}': vrf_vxlan must be 1-16777215"
            )
        if not zone.peers or len(zone.peers) < 2:
            errors.append(
                f"Zone '{zone.name}': EVPN zone requires at least 2 peers"
            )

    if zone.type == 'vxlan':
        if not zone.peers:
            errors.append(
                f"Zone '{zone.name}': VXLAN zone requires peers list"
            )

    return errors


def validate_vnet(vnet: VNet, zones: dict) -> List[str]:
    """Validate a VNet definition."""
    errors = []

    if vnet.zone not in zones:
        errors.append(
            f"VNet '{vnet.name}': references non-existent zone '{vnet.zone}'"
        )

    if vnet.tag < 1 or vnet.tag > 16777215:
        errors.append(
            f"VNet '{vnet.name}': tag must be 1-16777215, got {vnet.tag}"
        )

    return errors


def validate_subnet(subnet: Subnet, vnets: dict) -> List[str]:
    """Validate a subnet definition.

    Checks that the CIDR is valid, the gateway IP is within the subnet,
    and the referenced VNet exists.
    """
    errors = []

    if subnet.vnet not in vnets:
        errors.append(
            f"Subnet '{subnet.cidr}': references non-existent VNet "
            f"'{subnet.vnet}'"
        )

    try:
        network = ipaddress.ip_network(subnet.cidr, strict=True)
    except ValueError as e:
        errors.append(f"Subnet '{subnet.cidr}': invalid CIDR: {e}")
        return errors

    try:
        gw = ipaddress.ip_address(subnet.gateway)
    except ValueError:
        errors.append(
            f"Subnet '{subnet.cidr}': invalid gateway '{subnet.gateway}'"
        )
        return errors

    # Verify gateway address is within the subnet
    if gw not in network:
        errors.append(
            f"Subnet '{subnet.cidr}': gateway {subnet.gateway} is not "
            f"within the subnet"
        )

    return errors


def validate_tag_uniqueness(vnets: dict, zones: dict) -> List[str]:
    """Validate that VNet tags are unique within each zone."""
    errors = []
    zone_tags = {}

    for vnet in vnets.values():
        key = (vnet.zone, vnet.tag)
        if key in zone_tags:
            errors.append(
                f"VNet '{vnet.name}': tag {vnet.tag} already used by "
                f"'{zone_tags[key]}' in zone '{vnet.zone}'"
            )
        else:
            zone_tags[key] = vnet.name

    return errors


def validate_config(sdn_config: SDNConfig,
                    cluster_config: ClusterConfig) -> Tuple[bool, List[str]]:
    """Validate complete SDN configuration.

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors = []

    # Validate zones
    for zone in sdn_config.zones.values():
        errors.extend(validate_zone(zone))

    # Validate VNets
    for vnet in sdn_config.vnets.values():
        errors.extend(validate_vnet(vnet, sdn_config.zones))

    # Validate subnets
    for subnet in sdn_config.subnets:
        errors.extend(validate_subnet(subnet, sdn_config.vnets))

    # Validate tag uniqueness
    errors.extend(validate_tag_uniqueness(sdn_config.vnets, sdn_config.zones))

    # Validate exit nodes exist in cluster
    for zone in sdn_config.zones.values():
        for exit_node in zone.exit_nodes:
            if exit_node not in cluster_config.nodes:
                errors.append(
                    f"Zone '{zone.name}': exit node '{exit_node}' not "
                    f"found in cluster"
                )

    # Validate peers are cluster nodes
    for zone in sdn_config.zones.values():
        for peer_ip in zone.peers:
            found = any(
                n.management_ip == peer_ip or n.vtep_ip == peer_ip
                for n in cluster_config.nodes.values()
            )
            if not found:
                errors.append(
                    f"Zone '{zone.name}': peer {peer_ip} not found in "
                    f"cluster nodes"
                )

    return (len(errors) == 0, errors)
