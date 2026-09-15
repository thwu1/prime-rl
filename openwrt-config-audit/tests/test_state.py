
"""
Tests for OpenWrt multi-zone network configuration with DMZ design.
Validates bug fixes across existing zones AND correct design/implementation
of the DMZ zone (bridge-VLAN, interface, firewall zone, forwarding,
port forwards, DHCP, traffic rules).
"""

import re
import pytest
import yaml


NETWORK_FILE = "/app/etc/config/network"
FIREWALL_FILE = "/app/etc/config/firewall"
DHCP_FILE = "/app/etc/config/dhcp"
STUBBY_FILE = "/app/etc/stubby/stubby.yml"


def parse_uci(filepath):
    """Parse an OpenWrt UCI config file into a list of section dicts."""
    sections = []
    current = None
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"config\s+(\S+)(?:\s+'([^']*)')?", line)
            if m:
                current = {
                    "type": m.group(1),
                    "name": m.group(2),
                    "options": {},
                    "lists": {},
                }
                sections.append(current)
                continue
            if current is None:
                continue
            m = re.match(r"option\s+(\S+)\s+'([^']*)'", line)
            if m:
                current["options"][m.group(1)] = m.group(2)
                continue
            m = re.match(r"list\s+(\S+)\s+'([^']*)'", line)
            if m:
                current["lists"].setdefault(m.group(1), []).append(m.group(2))
    return sections


def get_sections_by_type(sections, type_name):
    return [s for s in sections if s["type"] == type_name]


def get_section(sections, type_name, name):
    for s in sections:
        if s["type"] == type_name and s["name"] == name:
            return s
    return None


def find_zone(sections, zone_name):
    """Find a firewall zone section by its 'name' option."""
    for s in sections:
        if s["type"] == "zone" and s["options"].get("name") == zone_name:
            return s
    return None


# ================================================================
# EXISTING BUG FIX TESTS
# ================================================================


class TestNetworkVLAN:
    """Bug 1: VLAN 50 bridge-vlan must have lan4 UNTAGGED (no :t)."""

    def test_iot_vlan_port_untagged(self):
        sections = parse_uci(NETWORK_FILE)
        bvlans = get_sections_by_type(sections, "bridge-vlan")
        vlan50 = None
        for bv in bvlans:
            if bv["options"].get("vlan") == "50":
                vlan50 = bv
                break
        assert vlan50 is not None, "bridge-vlan for VLAN 50 not found"
        ports = vlan50["lists"].get("ports", [])
        assert "lan4" in ports, (
            f"lan4 must be untagged in VLAN 50, got: {ports}"
        )
        assert "lan4:t" not in ports, (
            "lan4 must NOT be tagged (:t) in VLAN 50 — IoT end-devices send untagged"
        )


class TestNetworkGuest:
    """Bug 2: Guest interface device must be br-lan.30 (not br-lan.3)."""

    def test_guest_device_vlan_id(self):
        sections = parse_uci(NETWORK_FILE)
        guest = get_section(sections, "interface", "guest")
        assert guest is not None, "guest interface section not found"
        device = guest["options"].get("device", "")
        assert device == "br-lan.30", (
            f"guest device must be 'br-lan.30' (VLAN 30), got: '{device}'"
        )


class TestNetworkIoT:
    """Bug 3: IoT interface must be proto static with correct IP."""

    def test_iot_proto_static(self):
        sections = parse_uci(NETWORK_FILE)
        iot = get_section(sections, "interface", "iot")
        assert iot is not None, "iot interface section not found"
        assert iot["options"].get("proto") == "static", (
            f"iot proto must be 'static', got: '{iot['options'].get('proto')}'"
        )

    def test_iot_has_gateway_ip(self):
        sections = parse_uci(NETWORK_FILE)
        iot = get_section(sections, "interface", "iot")
        assert iot is not None, "iot interface section not found"
        ipaddrs = iot["lists"].get("ipaddr", [])
        opt_ip = iot["options"].get("ipaddr", "")
        all_ips = ipaddrs + ([opt_ip] if opt_ip else [])
        has_ip = any("192.168.50.1" in ip for ip in all_ips)
        assert has_ip, f"iot must have 192.168.50.1 assigned, got: {all_ips}"


class TestFirewallGuestZone:
    """Bug 4: Guest zone forward policy must be REJECT."""

    def test_guest_forward_reject(self):
        sections = parse_uci(FIREWALL_FILE)
        guest = find_zone(sections, "guest")
        assert guest is not None, "guest firewall zone not found"
        assert guest["options"].get("forward") == "REJECT", (
            f"guest forward must be 'REJECT', got: '{guest['options'].get('forward')}'"
        )


class TestFirewallGuestForwarding:
    """Bug 5: Must have forwarding from guest to wan."""

    def test_guest_to_wan_forwarding_exists(self):
        sections = parse_uci(FIREWALL_FILE)
        forwardings = get_sections_by_type(sections, "forwarding")
        found = any(
            fw["options"].get("src") == "guest"
            and fw["options"].get("dest") == "wan"
            and fw["options"].get("enabled", "1") != "0"
            for fw in forwardings
        )
        assert found, "Missing enabled forwarding rule from guest to wan"


class TestFirewallIoTZone:
    """Bug 6: IoT zone input must be DROP."""

    def test_iot_input_drop(self):
        sections = parse_uci(FIREWALL_FILE)
        iot = find_zone(sections, "iot")
        assert iot is not None, "iot firewall zone not found"
        assert iot["options"].get("input") == "DROP", (
            f"iot input must be 'DROP', got: '{iot['options'].get('input')}'"
        )


class TestDHCPGuest:
    """Bug 8: Guest DHCP pool must be bound to 'guest' interface."""

    def test_guest_dhcp_interface(self):
        sections = parse_uci(DHCP_FILE)
        guest_dhcp = get_section(sections, "dhcp", "guest")
        assert guest_dhcp is not None, "guest DHCP section not found"
        assert guest_dhcp["options"].get("interface") == "guest", (
            f"guest DHCP interface must be 'guest', got: "
            f"'{guest_dhcp['options'].get('interface')}'"
        )


class TestDNSMasq:
    """Bug 9: dnsmasq must forward to stubby on port 5453."""

    def test_dnsmasq_ipv4_server_port(self):
        sections = parse_uci(DHCP_FILE)
        dnsmasq_sections = get_sections_by_type(sections, "dnsmasq")
        assert len(dnsmasq_sections) > 0, "dnsmasq config section not found"
        servers = dnsmasq_sections[0]["lists"].get("server", [])
        ipv4_servers = [s for s in servers if s.startswith("127.0.0.1")]
        assert len(ipv4_servers) > 0, "No IPv4 server entry in dnsmasq"
        assert any("#5453" in s for s in ipv4_servers), (
            f"dnsmasq IPv4 server must use port 5453, got: {ipv4_servers}"
        )


class TestStubby:
    """Bug 10: stubby must listen on port 5453 (not 5353)."""

    def test_stubby_listen_port_5453(self):
        with open(STUBBY_FILE) as f:
            config = yaml.safe_load(f)
        listen = config.get("listen_addresses", [])
        assert len(listen) > 0, "stubby has no listen_addresses"
        listen_strs = [str(a) for a in listen]
        assert any("5453" in a for a in listen_strs), (
            f"stubby must listen on port 5453, got: {listen_strs}"
        )
        assert not any("5353" in a for a in listen_strs), (
            f"stubby must NOT listen on 5353, got: {listen_strs}"
        )


class TestWanZoneNetworks:
    """Bug 11: wan zone must include both wan and wan6 interfaces."""

    def test_wan_zone_has_wan(self):
        sections = parse_uci(FIREWALL_FILE)
        wan = find_zone(sections, "wan")
        assert wan is not None, "wan firewall zone not found"
        networks = wan["lists"].get("network", [])
        assert "wan" in networks, (
            f"wan zone must include 'wan' interface, got networks: {networks}"
        )

    def test_wan_zone_has_wan6(self):
        sections = parse_uci(FIREWALL_FILE)
        wan = find_zone(sections, "wan")
        assert wan is not None, "wan firewall zone not found"
        networks = wan["lists"].get("network", [])
        assert "wan6" in networks, (
            f"wan zone must include 'wan6' for IPv6 firewall coverage, got: {networks}"
        )


class TestForwardingDirection:
    """Bug 12: lan->iot forwarding must exist; IoT must not forward to internal zones."""

    def test_lan_to_iot_forwarding_exists(self):
        sections = parse_uci(FIREWALL_FILE)
        forwardings = get_sections_by_type(sections, "forwarding")
        found = any(
            fw["options"].get("src") == "lan"
            and fw["options"].get("dest") == "iot"
            and fw["options"].get("enabled", "1") != "0"
            for fw in forwardings
        )
        assert found, "Missing forwarding rule from lan to iot (management access)"

    def test_no_iot_to_internal_forwarding(self):
        """IoT must only forward to wan — no lateral movement to lan/guest/dmz."""
        sections = parse_uci(FIREWALL_FILE)
        forwardings = get_sections_by_type(sections, "forwarding")
        internal_zones = {"lan", "guest", "dmz"}
        for fw in forwardings:
            if fw["options"].get("src") == "iot":
                dest = fw["options"].get("dest")
                enabled = fw["options"].get("enabled", "1")
                if enabled == "0":
                    continue
                assert dest not in internal_zones, (
                    f"IoT must NOT forward to '{dest}' — "
                    f"lateral movement from IoT to internal zones is prohibited"
                )


# ================================================================
# DMZ DESIGN TESTS
# ================================================================


class TestDMZVLAN:
    """DMZ must have a VLAN 20 bridge-vlan with lan2 tagged, while
    VLAN 1 retains lan2 untagged for LAN traffic coexistence."""

    def test_vlan20_bridge_vlan_exists(self):
        sections = parse_uci(NETWORK_FILE)
        bvlans = get_sections_by_type(sections, "bridge-vlan")
        vlan20 = None
        for bv in bvlans:
            if bv["options"].get("vlan") == "20":
                vlan20 = bv
                break
        assert vlan20 is not None, "bridge-vlan for VLAN 20 (DMZ) not found"

    def test_vlan20_has_tagged_lan2(self):
        sections = parse_uci(NETWORK_FILE)
        bvlans = get_sections_by_type(sections, "bridge-vlan")
        vlan20 = None
        for bv in bvlans:
            if bv["options"].get("vlan") == "20":
                vlan20 = bv
                break
        assert vlan20 is not None, "bridge-vlan for VLAN 20 not found"
        ports = vlan20["lists"].get("ports", [])
        assert "lan2:t" in ports, (
            f"VLAN 20 must have lan2 tagged (lan2:t), got: {ports}"
        )

    def test_vlan1_retains_untagged_lan2(self):
        sections = parse_uci(NETWORK_FILE)
        bvlans = get_sections_by_type(sections, "bridge-vlan")
        vlan1 = None
        for bv in bvlans:
            if bv["options"].get("vlan") == "1":
                vlan1 = bv
                break
        assert vlan1 is not None, "bridge-vlan for VLAN 1 not found"
        ports = vlan1["lists"].get("ports", [])
        assert "lan2" in ports, (
            f"VLAN 1 must retain lan2 as untagged, got: {ports}"
        )


class TestDMZInterface:
    """DMZ interface must bind to br-lan.20 with static IP 192.168.20.1."""

    def test_dmz_device(self):
        sections = parse_uci(NETWORK_FILE)
        dmz = get_section(sections, "interface", "dmz")
        assert dmz is not None, "dmz interface section not found"
        assert dmz["options"].get("device") == "br-lan.20", (
            f"dmz device must be 'br-lan.20', got: '{dmz['options'].get('device')}'"
        )

    def test_dmz_proto_static(self):
        sections = parse_uci(NETWORK_FILE)
        dmz = get_section(sections, "interface", "dmz")
        assert dmz is not None, "dmz interface section not found"
        assert dmz["options"].get("proto") == "static", (
            f"dmz proto must be 'static', got: '{dmz['options'].get('proto')}'"
        )

    def test_dmz_gateway_ip(self):
        sections = parse_uci(NETWORK_FILE)
        dmz = get_section(sections, "interface", "dmz")
        assert dmz is not None, "dmz interface section not found"
        ipaddrs = dmz["lists"].get("ipaddr", [])
        opt_ip = dmz["options"].get("ipaddr", "")
        all_ips = ipaddrs + ([opt_ip] if opt_ip else [])
        has_ip = any("192.168.20.1" in ip for ip in all_ips)
        assert has_ip, f"dmz must have 192.168.20.1 assigned, got: {all_ips}"


class TestDMZFirewallZone:
    """DMZ firewall zone must exist with input DROP and forward REJECT."""

    def test_dmz_zone_exists(self):
        sections = parse_uci(FIREWALL_FILE)
        dmz = find_zone(sections, "dmz")
        assert dmz is not None, "dmz firewall zone not found"

    def test_dmz_zone_input_drop(self):
        sections = parse_uci(FIREWALL_FILE)
        dmz = find_zone(sections, "dmz")
        assert dmz is not None, "dmz firewall zone not found"
        assert dmz["options"].get("input") == "DROP", (
            f"dmz input must be 'DROP', got: '{dmz['options'].get('input')}'"
        )

    def test_dmz_zone_forward_reject(self):
        sections = parse_uci(FIREWALL_FILE)
        dmz = find_zone(sections, "dmz")
        assert dmz is not None, "dmz firewall zone not found"
        assert dmz["options"].get("forward") == "REJECT", (
            f"dmz forward must be 'REJECT', got: '{dmz['options'].get('forward')}'"
        )


class TestDMZForwarding:
    """DMZ must have forwarding to wan and from lan, but NOT to internal zones."""

    def test_dmz_to_wan_forwarding(self):
        sections = parse_uci(FIREWALL_FILE)
        forwardings = get_sections_by_type(sections, "forwarding")
        found = any(
            fw["options"].get("src") == "dmz"
            and fw["options"].get("dest") == "wan"
            and fw["options"].get("enabled", "1") != "0"
            for fw in forwardings
        )
        assert found, "Missing forwarding rule from dmz to wan"

    def test_lan_to_dmz_forwarding(self):
        sections = parse_uci(FIREWALL_FILE)
        forwardings = get_sections_by_type(sections, "forwarding")
        found = any(
            fw["options"].get("src") == "lan"
            and fw["options"].get("dest") == "dmz"
            and fw["options"].get("enabled", "1") != "0"
            for fw in forwardings
        )
        assert found, "Missing forwarding rule from lan to dmz"

    def test_no_dmz_to_internal_forwarding(self):
        """DMZ must never forward to lan, guest, or iot (isolation constraint)."""
        sections = parse_uci(FIREWALL_FILE)
        forwardings = get_sections_by_type(sections, "forwarding")
        internal_zones = {"lan", "guest", "iot"}
        for fw in forwardings:
            if fw["options"].get("src") == "dmz":
                dest = fw["options"].get("dest")
                enabled = fw["options"].get("enabled", "1")
                if enabled == "0":
                    continue
                assert dest not in internal_zones, (
                    f"DMZ must NOT forward to internal zone '{dest}' — "
                    f"isolation constraint violated"
                )


class TestDMZPortForwards:
    """HTTPS must target DMZ (relocated server), HTTP must also exist."""

    def test_https_redirect_to_dmz(self):
        """Bug 7 + design: HTTPS redirect must target DMZ server."""
        sections = parse_uci(FIREWALL_FILE)
        redirects = get_sections_by_type(sections, "redirect")
        https_redir = None
        for r in redirects:
            if (r["options"].get("src_dport") == "443"
                    or r["options"].get("name") == "HTTPS-Forward"):
                https_redir = r
                break
        assert https_redir is not None, "HTTPS redirect rule not found"
        assert https_redir["options"].get("dest") == "dmz", (
            f"HTTPS redirect dest must be 'dmz', got: "
            f"'{https_redir['options'].get('dest')}'"
        )
        assert https_redir["options"].get("dest_ip") == "192.168.20.10", (
            f"HTTPS redirect dest_ip must be '192.168.20.10', got: "
            f"'{https_redir['options'].get('dest_ip')}'"
        )

    def test_http_redirect_to_dmz(self):
        """HTTP port forward must exist, targeting DMZ server."""
        sections = parse_uci(FIREWALL_FILE)
        redirects = get_sections_by_type(sections, "redirect")
        http_redir = None
        for r in redirects:
            if r["options"].get("src_dport") == "80":
                http_redir = r
                break
        assert http_redir is not None, "HTTP redirect rule (port 80) not found"
        assert http_redir["options"].get("dest") == "dmz", (
            f"HTTP redirect dest must be 'dmz', got: "
            f"'{http_redir['options'].get('dest')}'"
        )
        assert http_redir["options"].get("dest_ip") == "192.168.20.10", (
            f"HTTP redirect dest_ip must be '192.168.20.10', got: "
            f"'{http_redir['options'].get('dest_ip')}'"
        )


class TestDMZDHCP:
    """DMZ DHCP pool must exist and be bound to 'dmz' interface."""

    def test_dmz_dhcp_pool_exists(self):
        sections = parse_uci(DHCP_FILE)
        dmz_dhcp = get_section(sections, "dhcp", "dmz")
        assert dmz_dhcp is not None, "dmz DHCP section not found"
        assert dmz_dhcp["options"].get("interface") == "dmz", (
            f"dmz DHCP interface must be 'dmz', got: "
            f"'{dmz_dhcp['options'].get('interface')}'"
        )


class TestDMZTrafficRules:
    """DMZ zone needs DNS and DHCP traffic rules to reach the router."""

    def test_dmz_dns_rule(self):
        sections = parse_uci(FIREWALL_FILE)
        rules = get_sections_by_type(sections, "rule")
        found = any(
            r["options"].get("src") == "dmz"
            and r["options"].get("dest_port") == "53"
            and r["options"].get("target") == "ACCEPT"
            for r in rules
        )
        assert found, "DMZ zone needs a traffic rule allowing DNS (port 53)"

    def test_dmz_dhcp_rule(self):
        sections = parse_uci(FIREWALL_FILE)
        rules = get_sections_by_type(sections, "rule")
        found = any(
            r["options"].get("src") == "dmz"
            and r["options"].get("dest_port") == "67"
            and r["options"].get("target") == "ACCEPT"
            for r in rules
        )
        assert found, "DMZ zone needs a traffic rule allowing DHCP (port 67)"


# ================================================================
# CROSS-VALIDATION TESTS
# ================================================================


class TestDNSChainConsistency:
    """dnsmasq server port must match stubby listen port."""

    def test_dnsmasq_stubby_port_match(self):
        sections = parse_uci(DHCP_FILE)
        dnsmasq_sections = get_sections_by_type(sections, "dnsmasq")
        servers = dnsmasq_sections[0]["lists"].get("server", [])
        dnsmasq_ports = set()
        for s in servers:
            m = re.search(r"#(\d+)", s)
            if m:
                dnsmasq_ports.add(m.group(1))

        with open(STUBBY_FILE) as f:
            config = yaml.safe_load(f)
        listen = config.get("listen_addresses", [])
        stubby_ports = set()
        for addr in listen:
            m = re.search(r"@(\d+)", str(addr))
            if m:
                stubby_ports.add(m.group(1))

        overlap = dnsmasq_ports & stubby_ports
        assert overlap, (
            f"DNS chain broken: dnsmasq forwards to ports {dnsmasq_ports}, "
            f"stubby listens on {stubby_ports}"
        )


class TestAllZonesForwardWAN:
    """Every internal zone (lan, dmz, guest, iot) must forward to wan."""

    def test_all_internal_zones_have_wan_forwarding(self):
        sections = parse_uci(FIREWALL_FILE)
        forwardings = get_sections_by_type(sections, "forwarding")
        forwarded_to_wan = set()
        for fw in forwardings:
            if (fw["options"].get("dest") == "wan"
                    and fw["options"].get("enabled", "1") != "0"):
                forwarded_to_wan.add(fw["options"].get("src"))

        for zone in ["lan", "dmz", "guest", "iot"]:
            assert zone in forwarded_to_wan, (
                f"Zone '{zone}' is missing an enabled forwarding rule to wan"
            )


class TestRedirectSubnetMatch:
    """Port forward dest_ip must fall within the destination zone's subnet."""

    def test_redirect_dest_ip_in_zone_subnet(self):
        fw_sections = parse_uci(FIREWALL_FILE)
        net_sections = parse_uci(NETWORK_FILE)

        redirects = get_sections_by_type(fw_sections, "redirect")
        for redir in redirects:
            dest_zone = redir["options"].get("dest")
            dest_ip = redir["options"].get("dest_ip")
            if not dest_zone or not dest_ip:
                continue

            iface = get_section(net_sections, "interface", dest_zone)
            if not iface:
                continue

            ipaddrs = iface["lists"].get("ipaddr", [])
            opt_ip = iface["options"].get("ipaddr", "")
            if opt_ip:
                ipaddrs.append(opt_ip)

            if not ipaddrs:
                continue

            for zone_ip in ipaddrs:
                zone_prefix = ".".join(zone_ip.split(".")[:3])
                dest_prefix = ".".join(dest_ip.split(".")[:3])
                assert zone_prefix == dest_prefix, (
                    f"Redirect to zone '{dest_zone}' has dest_ip {dest_ip} "
                    f"but zone subnet is {zone_ip}"
                )
