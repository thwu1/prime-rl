"""Configuration parser for SDN YAML files.

Reads cluster and SDN configuration from YAML files and constructs
the corresponding model objects.
"""

import yaml
from .models import Node, Zone, VNet, Subnet, ClusterConfig, SDNConfig


def parse_cluster_config(path: str) -> ClusterConfig:
    """Parse cluster configuration from a YAML file.

    Expected format:
        nodes:
          pve01:
            management_ip: "10.10.12.10"
            vtep_ip: "10.255.255.1"
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    nodes = {}
    for name, node_data in data['nodes'].items():
        nodes[name] = Node(
            name=name,
            management_ip=node_data['management_ip'],
            vtep_ip=node_data['vtep_ip']
        )
    return ClusterConfig(nodes=nodes)


def parse_sdn_config(path: str) -> SDNConfig:
    """Parse SDN configuration from a YAML file.

    Expected format:
        zones:
          zone-name:
            type: evpn
            vrf_vxlan: 4000
            ...
        vnets:
          vnet-name:
            zone: zone-name
            tag: 1000
            ...
        subnets:
          - cidr: "172.16.1.0/24"
            vnet: vnet-name
            gateway: "172.16.1.1"
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    zones = {}
    for name, zone_data in data.get('zones', {}).items():
        zones[name] = Zone(
            name=name,
            type=zone_data['type'],
            vrf_vxlan=zone_data.get('vrf_vxlan'),
            peers=zone_data.get('peers', []),
            anycast_mac=zone_data.get('anycast_mac'),
            exit_nodes=zone_data.get('exit_nodes', []),
            controller=zone_data.get('controller')
        )

    vnets = {}
    for name, vnet_data in data.get('vnets', {}).items():
        vnets[name] = VNet(
            name=name,
            zone=vnet_data['zone'],
            tag=vnet_data['tag'],
            alias=vnet_data.get('alias')
        )

    subnets = []
    for sub_data in data.get('subnets', []):
        subnets.append(Subnet(
            cidr=sub_data['cidr'],
            vnet=sub_data['vnet'],
            gateway=sub_data['gateway'],
            snat=sub_data.get('snat', False),
            dns_zone_prefix=sub_data.get('dns_zone_prefix')
        ))

    return SDNConfig(zones=zones, vnets=vnets, subnets=subnets)
