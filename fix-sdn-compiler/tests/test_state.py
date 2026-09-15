"""Tests for the SDN configuration compiler.

Validates that the compiler correctly generates network and FRR
configurations for EVPN/VXLAN overlay networks, following Proxmox VE
SDN implementation patterns.
"""


import sys
import os

sys.path.insert(0, '/srv/sdn')

from sdn_compiler.parser import parse_cluster_config, parse_sdn_config
from sdn_compiler.frr import (
    generate_frr_config, generate_route_maps, generate_vrf_config
)
from sdn_compiler.generator import (
    generate_network_config, generate_vxlan_interface,
    generate_bridge_interface
)
from sdn_compiler.validator import validate_subnet, validate_config
from sdn_compiler.models import (
    Node, Zone, VNet, Subnet, SDNConfig, ClusterConfig
)


def _load_configs():
    """Load test configuration files."""
    cluster = parse_cluster_config('/srv/sdn/configs/cluster.yaml')
    sdn = parse_sdn_config('/srv/sdn/configs/sdn.yaml')
    return cluster, sdn


class TestEVPNRouteTargets:
    """Test that EVPN route targets use the zone's VRF VXLAN ID.

    All VNets within the same EVPN zone share a single L3 VRF. The route
    targets for this VRF must be based on the zone's vrf_vxlan (L3 VNI),
    not the individual VNet tags (L2 VNI). Using VNet tags would give each
    VNet a different route target, breaking L3 connectivity within the VRF.
    """

    def test_vrf_route_targets_use_zone_vrf_vxlan(self):
        """Route targets should be 65000:<vrf_vxlan>, not 65000:<vnet_tag>."""
        zone = Zone(
            name="test-evpn", type="evpn", vrf_vxlan=4000,
            peers=["10.0.0.1", "10.0.0.2"], anycast_mac="AA:BB:CC:DD:EE:FF"
        )
        vnets = [
            VNet(name="net-a", zone="test-evpn", tag=1000),
            VNet(name="net-b", zone="test-evpn", tag=2000),
        ]
        subnets = [
            Subnet(cidr="10.0.1.0/24", vnet="net-a", gateway="10.0.1.1"),
            Subnet(cidr="10.0.2.0/24", vnet="net-b", gateway="10.0.2.1"),
        ]

        config_lines = generate_vrf_config(zone, vnets, subnets)
        config_text = "\n".join(config_lines)

        # Should use zone.vrf_vxlan (4000) in route targets
        assert "65000:4000" in config_text, (
            f"Route target should use VRF VXLAN ID 4000, not VNet tags. "
            f"Got:\n{config_text}"
        )

        # Should NOT use vnet tags as route targets
        assert "65000:1000" not in config_text, (
            "Route target incorrectly uses VNet tag 1000 instead of "
            "VRF VXLAN ID 4000"
        )
        assert "65000:2000" not in config_text, (
            "Route target incorrectly uses VNet tag 2000 instead of "
            "VRF VXLAN ID 4000"
        )

    def test_all_vnets_share_same_route_target(self):
        """All VNets in same zone must have identical route targets."""
        zone = Zone(
            name="prod", type="evpn", vrf_vxlan=5000,
            peers=["10.0.0.1", "10.0.0.2"], anycast_mac="AA:BB:CC:DD:EE:FF"
        )
        vnets = [
            VNet(name="v1", zone="prod", tag=100),
            VNet(name="v2", zone="prod", tag=200),
            VNet(name="v3", zone="prod", tag=300),
        ]

        config_lines = generate_vrf_config(zone, vnets, [])

        # Count import/export lines - should all reference same RT
        rt_lines = [l.strip() for l in config_lines
                    if 'route-target' in l]
        rt_values = set()
        for line in rt_lines:
            parts = line.split()
            rt_values.add(parts[-1])

        assert len(rt_values) == 1, (
            f"Expected all route targets to be the same value, "
            f"but got multiple: {rt_values}"
        )
        assert "65000:5000" in rt_values, (
            f"Route target should be 65000:5000, got {rt_values}"
        )

    def test_single_rt_pair_per_zone(self):
        """VRF should have exactly one import and one export route target.

        The L3 VRF needs a single route target pair (import + export)
        derived from the zone-level L3 VNI. Emitting one RT per VNet
        creates duplicate entries that inflate the config and confuse
        debugging of route import/export behavior.
        """
        zone = Zone(
            name="test-evpn", type="evpn", vrf_vxlan=4000,
            peers=["10.0.0.1", "10.0.0.2"], anycast_mac="AA:BB:CC:DD:EE:FF"
        )
        vnets = [
            VNet(name="net-a", zone="test-evpn", tag=1000),
            VNet(name="net-b", zone="test-evpn", tag=2000),
            VNet(name="net-c", zone="test-evpn", tag=3000),
        ]

        config_lines = generate_vrf_config(zone, vnets, [])

        import_lines = [l for l in config_lines
                        if 'route-target import' in l]
        export_lines = [l for l in config_lines
                        if 'route-target export' in l]

        assert len(import_lines) == 1, (
            f"Expected exactly 1 route-target import line, "
            f"got {len(import_lines)}: {import_lines}"
        )
        assert len(export_lines) == 1, (
            f"Expected exactly 1 route-target export line, "
            f"got {len(export_lines)}: {export_lines}"
        )


class TestRouteMapFiltering:
    """Test that route-maps correctly filter default routes.

    MAP_VTEP_IN must DENY default routes (0.0.0.0/0 and ::/0) from VTEP
    peers to prevent routing loops and unintended default route propagation
    in the EVPN fabric. The route-map should have exactly 3 sequences:
    deny IPv4 defaults, deny IPv6 defaults, permit all else.
    """

    def test_vtep_in_denies_default_routes(self):
        """MAP_VTEP_IN first IPv4 default match must use deny action."""
        route_map_lines = generate_route_maps()

        # Find the first MAP_VTEP_IN sequence that matches only_default (IPv4)
        for i, line in enumerate(route_map_lines):
            if 'MAP_VTEP_IN' in line and ('permit' in line or 'deny' in line):
                if (i + 1 < len(route_map_lines) and
                        'only_default' in route_map_lines[i + 1] and
                        'v6' not in route_map_lines[i + 1]):
                    assert 'deny' in line.lower(), (
                        f"MAP_VTEP_IN sequence matching only_default must "
                        f"use 'deny' action to block default routes, but "
                        f"got: '{line}'"
                    )
                    break

    def test_vtep_in_permits_non_default_routes(self):
        """MAP_VTEP_IN must have a permit-all rule after deny rules."""
        route_map_lines = generate_route_maps()

        has_permit_all = False
        for i, line in enumerate(route_map_lines):
            if 'MAP_VTEP_IN' in line and 'permit' in line:
                if i + 1 < len(route_map_lines):
                    next_line = route_map_lines[i + 1].strip()
                    if next_line == 'exit' or not next_line.startswith('match'):
                        has_permit_all = True
                        break

        assert has_permit_all, (
            "MAP_VTEP_IN must have a permit-all rule (no match clause) "
            "to allow non-default routes through"
        )

    def test_exactly_three_vtep_in_sequences(self):
        """MAP_VTEP_IN must have exactly 3 sequences.

        Only 3 route-map entries are needed: deny IPv4 default, deny IPv6
        default, permit everything else. Duplicate or redundant entries
        inflate the route-map, confuse hit-count debugging, and indicate
        copy-paste configuration errors.
        """
        route_map_lines = generate_route_maps()
        vtep_in_seqs = [
            l for l in route_map_lines
            if 'MAP_VTEP_IN' in l and ('permit' in l or 'deny' in l)
        ]

        assert len(vtep_in_seqs) == 3, (
            f"MAP_VTEP_IN should have exactly 3 sequences "
            f"(deny IPv4 default, deny IPv6 default, permit all), "
            f"got {len(vtep_in_seqs)}: {vtep_in_seqs}"
        )

    def test_no_duplicate_prefix_list_matches(self):
        """Each prefix-list should be matched at most once in MAP_VTEP_IN.

        Duplicate match clauses for the same prefix-list are copy-paste
        artifacts that waste route-map evaluation cycles and split
        hit counters, making operational debugging unreliable.
        """
        route_map_lines = generate_route_maps()

        # Collect match clauses within MAP_VTEP_IN context
        vtep_in_matches = []
        in_vtep_in = False
        for line in route_map_lines:
            stripped = line.strip()
            if 'MAP_VTEP_IN' in stripped:
                in_vtep_in = True
            elif 'MAP_VTEP_OUT' in stripped:
                in_vtep_in = False
            elif in_vtep_in and stripped.startswith('match'):
                vtep_in_matches.append(stripped)

        unique_matches = set(vtep_in_matches)
        assert len(vtep_in_matches) == len(unique_matches), (
            f"MAP_VTEP_IN has duplicate match clauses. "
            f"Total: {len(vtep_in_matches)}, Unique: {len(unique_matches)}. "
            f"Matches: {vtep_in_matches}"
        )

    def test_full_frr_config_denies_defaults(self):
        """Full FRR config must contain deny rule for default routes."""
        cluster, sdn = _load_configs()
        frr_config = generate_frr_config(sdn, cluster, "pve01")

        lines = frr_config.split("\n")
        vtep_in_first = None
        for line in lines:
            if 'MAP_VTEP_IN' in line and ('permit' in line or 'deny' in line):
                vtep_in_first = line.strip()
                break

        assert vtep_in_first is not None, "MAP_VTEP_IN not found in FRR config"
        assert 'deny' in vtep_in_first, (
            f"First MAP_VTEP_IN rule should be 'deny' but got: "
            f"'{vtep_in_first}'"
        )


class TestVXLANTunnelEndpoint:
    """Test that VXLAN interfaces use the correct local tunnel IP.

    VXLAN tunnel endpoints (VTEPs) should use the dedicated VTEP source IP
    (typically a loopback address) rather than the management interface IP.
    Using the management IP breaks VTEP-to-VTEP communication because peers
    expect to reach each other via the VTEP IP, and it couples overlay
    traffic to the management plane.
    """

    def test_vxlan_uses_vtep_ip_not_management_ip(self):
        """VXLAN local IP must be the VTEP IP, not management IP."""
        node = Node(
            name="pve01",
            management_ip="10.10.12.10",
            vtep_ip="10.255.255.1"
        )
        zone = Zone(
            name="test-zone", type="evpn", vrf_vxlan=4000,
            peers=["10.10.12.10", "10.10.12.11"],
            anycast_mac="AA:BB:CC:DD:EE:FF"
        )
        vnet = VNet(name="test-net", zone="test-zone", tag=1000)

        cmds = generate_vxlan_interface(vnet, zone, node)
        vxlan_cmd = [c for c in cmds if 'ip link add' in c][0]

        assert "10.255.255.1" in vxlan_cmd, (
            f"VXLAN local IP should be VTEP IP 10.255.255.1, "
            f"got: {vxlan_cmd}"
        )
        assert "10.10.12.10" not in vxlan_cmd, (
            f"VXLAN should NOT use management IP 10.10.12.10 as local IP. "
            f"Got: {vxlan_cmd}"
        )

    def test_all_nodes_use_vtep_ip(self):
        """VXLAN commands for all nodes must use their VTEP IPs."""
        cluster, sdn = _load_configs()
        zone = sdn.zones["evpn-production"]
        vnet = sdn.vnets["infra-net"]

        for node_name, node in cluster.nodes.items():
            cmds = generate_vxlan_interface(vnet, zone, node)
            vxlan_cmd = [c for c in cmds if 'ip link add' in c][0]

            assert node.vtep_ip in vxlan_cmd, (
                f"Node {node_name}: VXLAN should use VTEP IP "
                f"{node.vtep_ip}, got: {vxlan_cmd}"
            )
            assert node.management_ip not in vxlan_cmd, (
                f"Node {node_name}: VXLAN should NOT use management IP "
                f"{node.management_ip}"
            )


class TestAnycastGatewayMAC:
    """Test that EVPN bridges use the zone's anycast MAC.

    In EVPN fabrics, the gateway bridge on each node must use the same
    anycast MAC address so that VMs see a consistent gateway MAC regardless
    of which node they reside on. This is essential for seamless VM
    live migration and distributed anycast gateway functionality.
    """

    def test_evpn_bridge_uses_anycast_mac(self):
        """EVPN bridge MAC must match zone.anycast_mac."""
        zone = Zone(
            name="test-evpn", type="evpn", vrf_vxlan=4000,
            peers=["10.0.0.1", "10.0.0.2"],
            anycast_mac="AA:BB:CC:11:22:33"
        )
        vnet = VNet(name="test-net", zone="test-evpn", tag=1000)
        node = Node(name="pve01", management_ip="10.0.0.1",
                     vtep_ip="10.255.255.1")
        subnets = [
            Subnet(cidr="10.0.1.0/24", vnet="test-net", gateway="10.0.1.1")
        ]

        cmds = generate_bridge_interface(vnet, zone, node, subnets)
        mac_cmds = [c for c in cmds if 'address' in c and 'addr add' not in c]

        assert len(mac_cmds) > 0, "No bridge MAC address command found"
        mac_cmd = mac_cmds[0]

        assert "AA:BB:CC:11:22:33".lower() in mac_cmd.lower() or \
               "AA:BB:CC:11:22:33" in mac_cmd, (
            f"Bridge MAC should be anycast MAC AA:BB:CC:11:22:33, "
            f"got: {mac_cmd}"
        )

    def test_same_mac_on_all_nodes(self):
        """All nodes must have the same bridge MAC for the same VNet."""
        zone = Zone(
            name="evpn-zone", type="evpn", vrf_vxlan=4000,
            peers=["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            anycast_mac="DE:AD:BE:EF:00:01"
        )
        vnet = VNet(name="shared-net", zone="evpn-zone", tag=500)
        nodes = [
            Node(name="n1", management_ip="10.0.0.1", vtep_ip="10.1.0.1"),
            Node(name="n2", management_ip="10.0.0.2", vtep_ip="10.1.0.2"),
            Node(name="n3", management_ip="10.0.0.3", vtep_ip="10.1.0.3"),
        ]

        macs = []
        for node in nodes:
            cmds = generate_bridge_interface(vnet, zone, node, [])
            mac_cmds = [c for c in cmds
                        if 'address' in c and 'addr add' not in c]
            assert len(mac_cmds) > 0
            macs.append(mac_cmds[0])

        assert macs[0] == macs[1] == macs[2], (
            f"All nodes must have the same bridge MAC. Got:\n"
            f"  n1: {macs[0]}\n  n2: {macs[1]}\n  n3: {macs[2]}"
        )


class TestSubnetGatewayValidation:
    """Test that gateway validation rejects network/broadcast addresses.

    A gateway IP must be a usable host address within the subnet. The
    network address (e.g., 172.16.61.0 in a /28) and broadcast address
    (e.g., 172.16.61.15 in a /28) are not valid gateway addresses.
    """

    def test_rejects_network_address_as_gateway(self):
        """Gateway cannot be the subnet's network address."""
        subnet = Subnet(
            cidr="172.16.61.0/28",
            vnet="test-net",
            gateway="172.16.61.0"
        )
        errors = validate_subnet(subnet, {"test-net": None})

        assert len(errors) > 0, (
            "Validator should reject network address 172.16.61.0 as gateway "
            "for subnet 172.16.61.0/28"
        )

    def test_rejects_broadcast_address_as_gateway(self):
        """Gateway cannot be the subnet's broadcast address."""
        subnet = Subnet(
            cidr="172.16.61.0/28",
            vnet="test-net",
            gateway="172.16.61.15"
        )
        errors = validate_subnet(subnet, {"test-net": None})

        assert len(errors) > 0, (
            "Validator should reject broadcast address 172.16.61.15 as "
            "gateway for subnet 172.16.61.0/28"
        )

    def test_accepts_valid_host_gateway(self):
        """Valid host addresses should be accepted as gateways."""
        subnet = Subnet(
            cidr="172.16.61.0/28",
            vnet="test-net",
            gateway="172.16.61.1"
        )
        errors = validate_subnet(subnet, {"test-net": None})

        assert len(errors) == 0, (
            f"Validator should accept 172.16.61.1 as valid gateway. "
            f"Got errors: {errors}"
        )

    def test_rejects_gateway_outside_subnet(self):
        """Gateway outside the subnet must be rejected."""
        subnet = Subnet(
            cidr="172.16.61.0/28",
            vnet="test-net",
            gateway="172.16.62.1"
        )
        errors = validate_subnet(subnet, {"test-net": None})

        assert len(errors) > 0, (
            "Validator should reject gateway 172.16.62.1 which is "
            "outside subnet 172.16.61.0/28"
        )


class TestVNIConflicts:
    """Test VNI namespace conflict detection.

    In VXLAN-based fabrics, every VNI occupies a shared namespace in the
    VXLAN header. An L2 VNI (VNet tag) that collides with an L3 VNI
    (zone vrf_vxlan) causes the receiving VTEP to misinterpret traffic
    type. Reusing the same L2 VNI across different zones merges their
    broadcast domains, breaking tenant isolation.
    """

    def test_detects_l2_l3_vni_collision(self):
        """Must flag when a VNet tag equals a zone's vrf_vxlan."""
        from sdn_compiler.validator import validate_vni_conflicts

        sdn = SDNConfig(
            zones={
                "zone-a": Zone(
                    name="zone-a", type="evpn", vrf_vxlan=1000,
                    peers=["10.0.0.1", "10.0.0.2"],
                    anycast_mac="AA:BB:CC:DD:EE:FF"
                ),
            },
            vnets={
                "net-x": VNet(name="net-x", zone="zone-a", tag=1000),
            },
            subnets=[]
        )

        errors = validate_vni_conflicts(sdn)
        assert len(errors) > 0, (
            "Should detect L2/L3 VNI collision when VNet tag equals "
            "zone vrf_vxlan (both 1000)"
        )

    def test_detects_l2_l3_collision_across_zones(self):
        """Must flag L2 VNI collision with L3 VNI of a different zone."""
        from sdn_compiler.validator import validate_vni_conflicts

        sdn = SDNConfig(
            zones={
                "zone-a": Zone(
                    name="zone-a", type="evpn", vrf_vxlan=3000,
                    peers=["10.0.0.1", "10.0.0.2"],
                    anycast_mac="AA:BB:CC:DD:EE:FF"
                ),
                "zone-b": Zone(
                    name="zone-b", type="evpn", vrf_vxlan=5000,
                    peers=["10.0.0.1", "10.0.0.2"],
                    anycast_mac="AA:BB:CC:DD:EE:00"
                ),
            },
            vnets={
                "net-in-b": VNet(name="net-in-b", zone="zone-b", tag=3000),
            },
            subnets=[]
        )

        errors = validate_vni_conflicts(sdn)
        assert len(errors) > 0, (
            "Should detect VNet tag 3000 colliding with zone-a's L3 VNI 3000"
        )

    def test_detects_cross_zone_tag_reuse(self):
        """Must flag same L2 VNI used across different zones."""
        from sdn_compiler.validator import validate_vni_conflicts

        sdn = SDNConfig(
            zones={
                "zone-a": Zone(
                    name="zone-a", type="evpn", vrf_vxlan=4000,
                    peers=["10.0.0.1", "10.0.0.2"],
                    anycast_mac="AA:BB:CC:DD:EE:FF"
                ),
                "zone-b": Zone(
                    name="zone-b", type="evpn", vrf_vxlan=5000,
                    peers=["10.0.0.1", "10.0.0.2"],
                    anycast_mac="AA:BB:CC:DD:EE:00"
                ),
            },
            vnets={
                "net-x": VNet(name="net-x", zone="zone-a", tag=500),
                "net-y": VNet(name="net-y", zone="zone-b", tag=500),
            },
            subnets=[]
        )

        errors = validate_vni_conflicts(sdn)
        assert len(errors) > 0, (
            "Should detect cross-zone L2 VNI reuse: tag 500 in both "
            "zone-a and zone-b"
        )

    def test_no_false_positives(self):
        """Valid config with no VNI conflicts should pass."""
        from sdn_compiler.validator import validate_vni_conflicts

        sdn = SDNConfig(
            zones={
                "zone-a": Zone(
                    name="zone-a", type="evpn", vrf_vxlan=4000,
                    peers=["10.0.0.1", "10.0.0.2"],
                    anycast_mac="AA:BB:CC:DD:EE:FF"
                ),
            },
            vnets={
                "net-x": VNet(name="net-x", zone="zone-a", tag=1000),
                "net-y": VNet(name="net-y", zone="zone-a", tag=2000),
            },
            subnets=[]
        )

        errors = validate_vni_conflicts(sdn)
        assert len(errors) == 0, (
            f"Should not flag valid config with no VNI conflicts: {errors}"
        )

    def test_production_config_clean(self):
        """Production config should have no VNI conflicts."""
        from sdn_compiler.validator import validate_vni_conflicts

        cluster, sdn = _load_configs()
        errors = validate_vni_conflicts(sdn)
        assert len(errors) == 0, (
            f"Production config has VNI conflicts: {errors}"
        )


class TestEndToEnd:
    """Test the complete compiler pipeline produces correct output.

    Validates that all modules work together to produce a coherent,
    correct configuration for a real multi-node cluster.
    """

    def test_frr_config_structure(self):
        """Full FRR config should have correct structure and values."""
        cluster, sdn = _load_configs()
        frr_config = generate_frr_config(sdn, cluster, "pve01")

        # Should contain required FRR sections
        assert "ip prefix-list only_default" in frr_config
        assert "route-map MAP_VTEP_IN" in frr_config
        assert "vrf vrf_evpn_production" in frr_config
        assert "router bgp 65000" in frr_config

        # VRF should have correct VNI
        assert "vni 4000" in frr_config

        # Route targets should use L3 VNI 4000, not L2 VNIs
        assert "65000:4000" in frr_config
        assert "65000:1000" not in frr_config, (
            "FRR config contains route target with L2 VNI 1000 "
            "instead of L3 VNI 4000"
        )
        assert "65000:2000" not in frr_config, (
            "FRR config contains route target with L2 VNI 2000 "
            "instead of L3 VNI 4000"
        )

    def test_network_config_uses_vtep_ips(self):
        """Network config should use VTEP IPs for VXLAN interfaces."""
        cluster, sdn = _load_configs()
        net_config = generate_network_config(sdn, cluster, "pve01")

        # VXLAN local should be VTEP IP, not management IP
        lines = net_config.split('\n')
        vxlan_lines = [
            l for l in lines
            if 'vxlan' in l and 'local' in l and 'id' in l
        ]

        for line in vxlan_lines:
            assert "10.10.12.10" not in line, (
                f"VXLAN should use VTEP IP (10.255.255.1), not "
                f"management IP (10.10.12.10): {line}"
            )

    def test_validation_passes_clean_config(self):
        """Production config should pass full validation."""
        cluster, sdn = _load_configs()
        is_valid, errors = validate_config(sdn, cluster)
        assert is_valid, f"Validation should pass on clean config: {errors}"
