"""Tests verifying OpenWrt UCI configuration after audit and remediation of CR-2024-047.

Validates the structural properties of the final configuration across network
and firewall subsystems. Tests verify correct zone model, masquerade placement,
routing table design, forwarding topology, DNS leak prevention, selective IPv6
deployment, VPN tunnel parameters, and IoT restriction rule ordering.

"""

import pytest


def parse_uci_config(filepath):
    """Parse an OpenWrt UCI configuration file into structured sections.

    Returns a list of dicts, each with keys:
      type (str), name (str|None), options (dict), lists (dict of lists)
    """
    sections = []
    current = None
    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if stripped.startswith('config '):
                parts = stripped.split(None, 2)
                stype = parts[1] if len(parts) > 1 else ''
                sname = parts[2].strip("'\"") if len(parts) > 2 else None
                current = {
                    'type': stype,
                    'name': sname,
                    'options': {},
                    'lists': {},
                }
                sections.append(current)
            elif current is not None:
                if stripped.startswith('option '):
                    parts = stripped.split(None, 2)
                    if len(parts) >= 3:
                        current['options'][parts[1]] = parts[2].strip("'\"")
                elif stripped.startswith('list '):
                    parts = stripped.split(None, 2)
                    if len(parts) >= 3:
                        key = parts[1]
                        val = parts[2].strip("'\"")
                        current['lists'].setdefault(key, []).append(val)
    return sections


def find_zone(sections, name):
    """Find a firewall zone by name."""
    for s in sections:
        if s['type'] == 'zone' and s['options'].get('name') == name:
            return s
    return None


def find_interface(sections, name):
    """Find a network interface by name."""
    for s in sections:
        if s['type'] == 'interface' and s['name'] == name:
            return s
    return None


def get_forwardings(sections):
    """Return all forwarding pairs as a set of (src, dest) tuples."""
    pairs = set()
    for s in sections:
        if s['type'] == 'forwarding':
            src = s['options'].get('src', '')
            dest = s['options'].get('dest', '')
            if src and dest:
                pairs.add((src, dest))
    return pairs


NETWORK_CONFIG = '/app/config/network'
FIREWALL_CONFIG = '/app/config/firewall'


# ---------------------------------------------------------------------------
# 1. Dual-WAN Architecture
# ---------------------------------------------------------------------------
class TestDualWAN:
    """Verify backup WAN interface and its firewall zone."""

    def test_wan_backup_interface_exists(self):
        sections = parse_uci_config(NETWORK_CONFIG)
        iface = find_interface(sections, 'wan_backup')
        assert iface is not None, "Interface 'wan_backup' not found in network config"
        assert iface['options'].get('device') == 'eth1', \
            f"wan_backup must use device eth1, got {iface['options'].get('device')}"
        assert iface['options'].get('proto') == 'static', \
            f"wan_backup must use proto static, got {iface['options'].get('proto')}"

    def test_wan_backup_ip_config(self):
        sections = parse_uci_config(NETWORK_CONFIG)
        iface = find_interface(sections, 'wan_backup')
        assert iface is not None, "wan_backup interface not found"
        assert iface['options'].get('ipaddr') == '100.64.0.2', \
            f"wan_backup ipaddr must be 100.64.0.2, got {iface['options'].get('ipaddr')}"
        netmask = iface['options'].get('netmask', '')
        assert netmask in ('255.255.255.252', '/30'), \
            f"wan_backup netmask must be 255.255.255.252, got {netmask}"

    def test_wan_backup_gateway(self):
        sections = parse_uci_config(NETWORK_CONFIG)
        iface = find_interface(sections, 'wan_backup')
        assert iface is not None, "wan_backup interface not found"
        assert iface['options'].get('gateway') == '100.64.0.1', \
            f"wan_backup gateway must be 100.64.0.1, got {iface['options'].get('gateway')}"

    def test_wan_backup_zone_exists(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'wan_backup')
        assert zone is not None, "Firewall zone 'wan_backup' not found"
        networks = zone['lists'].get('network', [])
        assert 'wan_backup' in networks, \
            f"wan_backup zone must bind to network 'wan_backup', got {networks}"

    def test_wan_backup_zone_masquerade(self):
        """CGNAT address space requires masquerade for outbound traffic."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'wan_backup')
        assert zone is not None, "wan_backup zone not found"
        assert zone['options'].get('masq') == '1', \
            "wan_backup zone must have masquerade enabled (CGNAT requires NAT)"


# ---------------------------------------------------------------------------
# 2. HQ VPN Architecture
# ---------------------------------------------------------------------------
class TestVPNHQ:
    """Verify HQ WireGuard tunnel configuration and firewall zone."""

    def test_vpn_hq_peer_exists(self):
        sections = parse_uci_config(NETWORK_CONFIG)
        peer = None
        for s in sections:
            if s['type'] == 'wireguard_vpn_hq':
                peer = s
                break
        assert peer is not None, "WireGuard peer section 'wireguard_vpn_hq' not found"
        assert peer['options'].get('public_key') == \
            'xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=', \
            "HQ peer has incorrect public key"

    def test_vpn_hq_allowed_ips_scoped(self):
        """AllowedIPs must be scoped to HQ range, NOT 0.0.0.0/0."""
        sections = parse_uci_config(NETWORK_CONFIG)
        for s in sections:
            if s['type'] == 'wireguard_vpn_hq':
                allowed = s['lists'].get('allowed_ips', [])
                assert '0.0.0.0/0' not in allowed, \
                    "HQ VPN AllowedIPs must NOT be 0.0.0.0/0 — would capture " \
                    "all traffic and conflict with commercial VPN"
                has_hq = any('172.16' in ip for ip in allowed)
                assert has_hq, \
                    f"HQ VPN AllowedIPs must include 172.16.0.0/12, got {allowed}"
                return
        pytest.fail("wireguard_vpn_hq peer section not found")

    def test_vpn_hq_zone_exists(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'vpn_hq')
        assert zone is not None, "Firewall zone 'vpn_hq' not found"
        networks = zone['lists'].get('network', [])
        assert 'vpn_hq' in networks, \
            f"vpn_hq zone must bind to network 'vpn_hq', got {networks}"

    def test_vpn_hq_no_masquerade(self):
        """HQ has return routes — no NAT needed on this tunnel."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'vpn_hq')
        assert zone is not None, "vpn_hq zone not found"
        masq = zone['options'].get('masq', '0')
        assert masq != '1', \
            "vpn_hq zone must NOT have masquerade — HQ network has " \
            "static routes back to our subnets, NAT is unnecessary"


# ---------------------------------------------------------------------------
# 3. Commercial VPN Architecture
# ---------------------------------------------------------------------------
class TestVPNExt:
    """Verify commercial VPN tunnel configuration and firewall zone."""

    def test_vpn_ext_interface_exists(self):
        sections = parse_uci_config(NETWORK_CONFIG)
        iface = find_interface(sections, 'vpn_ext')
        assert iface is not None, "Interface 'vpn_ext' not found"
        assert iface['options'].get('proto') == 'wireguard', \
            f"vpn_ext must use proto wireguard, got {iface['options'].get('proto')}"

    def test_vpn_ext_private_key(self):
        """Private key must match the one specified in the change request."""
        sections = parse_uci_config(NETWORK_CONFIG)
        iface = find_interface(sections, 'vpn_ext')
        assert iface is not None, "vpn_ext interface not found"
        key = iface['options'].get('private_key', '')
        assert key == 'gN65BkIKy1eCE9pP1wdc8ROUgxU3ZdQbFmcqEIa7cFo=', \
            f"vpn_ext private key is incorrect: '{key}'. " \
            "Tunnel will silently fail to establish with a mismatched key."

    def test_vpn_ext_peer_exists(self):
        sections = parse_uci_config(NETWORK_CONFIG)
        peer = None
        for s in sections:
            if s['type'] == 'wireguard_vpn_ext':
                peer = s
                break
        assert peer is not None, "WireGuard peer section 'wireguard_vpn_ext' not found"
        assert peer['options'].get('public_key') == \
            'HIgo9xNzJMWLKASShiTqIybxR0V1tB1YBjMBOAtiSw4='
        allowed = peer['lists'].get('allowed_ips', [])
        assert '0.0.0.0/0' in allowed, \
            f"Commercial VPN peer AllowedIPs must include 0.0.0.0/0, got {allowed}"

    def test_vpn_ext_zone_exists(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'vpn_ext')
        assert zone is not None, "Firewall zone 'vpn_ext' not found"
        networks = zone['lists'].get('network', [])
        assert 'vpn_ext' in networks, \
            f"vpn_ext zone must bind to network 'vpn_ext', got {networks}"

    def test_vpn_ext_masquerade(self):
        """Commercial VPN expects traffic from tunnel address — NAT required."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'vpn_ext')
        assert zone is not None, "vpn_ext zone not found"
        assert zone['options'].get('masq') == '1', \
            "vpn_ext zone must have masquerade — provider expects " \
            "traffic from tunnel endpoint address only"


# ---------------------------------------------------------------------------
# 4. Policy Routing Architecture
# ---------------------------------------------------------------------------
class TestPolicyRouting:
    """Verify routing table design and ip rule configuration."""

    def test_hq_route_table(self):
        """Route to HQ network via vpn_hq in table 100."""
        sections = parse_uci_config(NETWORK_CONFIG)
        found = False
        for s in sections:
            if s['type'] == 'route':
                iface = s['options'].get('interface', '')
                target = s['options'].get('target', '')
                table = s['options'].get('table', '')
                if iface == 'vpn_hq' and '172.16' in target and table == '100':
                    found = True
                    break
        assert found, \
            "Route missing: 172.16.0.0/12 via vpn_hq in table 100"

    def test_ext_route_table(self):
        """Default route via vpn_ext in table 200."""
        sections = parse_uci_config(NETWORK_CONFIG)
        found = False
        for s in sections:
            if s['type'] == 'route':
                iface = s['options'].get('interface', '')
                target = s['options'].get('target', '')
                table = s['options'].get('table', '')
                if iface == 'vpn_ext' and target == '0.0.0.0/0' and table == '200':
                    found = True
                    break
        assert found, \
            "Route missing: 0.0.0.0/0 via vpn_ext in table 200"

    def test_corp_to_hq_rule(self):
        """IP rule: corporate traffic to HQ uses table 100."""
        sections = parse_uci_config(NETWORK_CONFIG)
        found = False
        for s in sections:
            if s['type'] == 'rule':
                src = s['options'].get('src', '')
                dest = s['options'].get('dest', '')
                lookup = s['options'].get('lookup', '') or s['options'].get('table', '')
                if '10.0.20' in src and '172.16' in dest and lookup == '100':
                    found = True
                    break
        assert found, \
            "IP rule missing: src 10.0.20.0/24 dest 172.16.0.0/12 -> table 100"

    def test_guest_to_vpn_rule(self):
        """IP rule: all guest traffic uses table 200."""
        sections = parse_uci_config(NETWORK_CONFIG)
        found = False
        for s in sections:
            if s['type'] == 'rule':
                src = s['options'].get('src', '')
                lookup = s['options'].get('lookup', '') or s['options'].get('table', '')
                if '10.0.40' in src and lookup == '200':
                    found = True
                    break
        assert found, \
            "IP rule missing: src 10.0.40.0/24 -> table 200. " \
            "Without this, guest traffic exits via primary WAN."


# ---------------------------------------------------------------------------
# 5. Forwarding Topology
# ---------------------------------------------------------------------------
class TestForwardingTopology:
    """Verify the complete forwarding rule architecture."""

    def test_mgmt_forwardings(self):
        """Management needs: WAN, backup WAN, HQ VPN, IoT management."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        pairs = get_forwardings(sections)
        assert ('mgmt', 'wan') in pairs, "Missing: mgmt -> wan"
        assert ('mgmt', 'wan_backup') in pairs, "Missing: mgmt -> wan_backup (failover)"
        assert ('mgmt', 'vpn_hq') in pairs, "Missing: mgmt -> vpn_hq (HQ access)"
        assert ('mgmt', 'iot') in pairs, "Missing: mgmt -> iot (device management)"

    def test_corp_forwardings(self):
        """Corporate needs: WAN, backup WAN, HQ VPN."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        pairs = get_forwardings(sections)
        assert ('corp', 'wan') in pairs, "Missing: corp -> wan"
        assert ('corp', 'wan_backup') in pairs, "Missing: corp -> wan_backup (failover)"
        assert ('corp', 'vpn_hq') in pairs, "Missing: corp -> vpn_hq (HQ access)"

    def test_iot_forwardings(self):
        """IoT needs: WAN (restricted), backup WAN."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        pairs = get_forwardings(sections)
        assert ('iot', 'wan') in pairs, "Missing: iot -> wan"
        assert ('iot', 'wan_backup') in pairs, "Missing: iot -> wan_backup (failover)"

    def test_guest_forwardings(self):
        """Guest needs: commercial VPN only, backup WAN as failover."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        pairs = get_forwardings(sections)
        assert ('guest', 'vpn_ext') in pairs, "Missing: guest -> vpn_ext (VPN routing)"
        assert ('guest', 'wan_backup') in pairs, \
            "Missing: guest -> wan_backup (failover)"

    def test_guest_isolation(self):
        """Guest must not reach primary WAN, internal zones, or HQ VPN."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        pairs = get_forwardings(sections)
        assert ('guest', 'wan') not in pairs, \
            "guest -> wan MUST be removed: guest traffic must never exit " \
            "through primary WAN, only through vpn_ext or wan_backup"
        assert ('guest', 'mgmt') not in pairs, \
            "guest -> mgmt violates zone isolation"
        assert ('guest', 'corp') not in pairs, \
            "guest -> corp violates zone isolation"
        assert ('guest', 'iot') not in pairs, \
            "guest -> iot violates zone isolation"
        assert ('guest', 'vpn_hq') not in pairs, \
            "guest -> vpn_hq violates zone isolation"


# ---------------------------------------------------------------------------
# 6. IoT Outbound Restrictions
# ---------------------------------------------------------------------------
class TestIoTRestrictions:
    """Verify IoT outbound port filtering rules and ordering."""

    def test_iot_allow_http_https(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        found = False
        for s in sections:
            if s['type'] == 'rule':
                src = s['options'].get('src', '')
                dest = s['options'].get('dest', '')
                proto = s['options'].get('proto', '')
                dest_port = s['options'].get('dest_port', '')
                target = s['options'].get('target', '')
                if (src == 'iot' and dest == 'wan' and 'tcp' in proto
                        and '80' in dest_port and '443' in dest_port
                        and target == 'ACCEPT'):
                    found = True
                    break
        assert found, \
            "Missing rule: allow IoT -> WAN TCP ports 80,443"

    def test_iot_allow_ntp(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        found = False
        for s in sections:
            if s['type'] == 'rule':
                src = s['options'].get('src', '')
                dest = s['options'].get('dest', '')
                proto = s['options'].get('proto', '')
                dest_port = s['options'].get('dest_port', '')
                target = s['options'].get('target', '')
                if (src == 'iot' and dest == 'wan' and 'udp' in proto
                        and '123' in dest_port and target == 'ACCEPT'):
                    found = True
                    break
        assert found, \
            "Missing rule: allow IoT -> WAN UDP port 123 (NTP)"

    def test_iot_block_other(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        found = False
        for s in sections:
            if s['type'] == 'rule':
                src = s['options'].get('src', '')
                dest = s['options'].get('dest', '')
                target = s['options'].get('target', '')
                proto = s['options'].get('proto', '')
                dest_port = s['options'].get('dest_port', '')
                if (src == 'iot' and dest == 'wan'
                        and target == 'REJECT' and not proto and not dest_port):
                    found = True
                    break
        assert found, \
            "Missing rule: reject all other IoT -> WAN traffic (catch-all)"

    def test_iot_restriction_order(self):
        """Reject-all MUST come AFTER allow rules, or allows are shadowed."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        allow_positions = []
        reject_position = None
        for i, s in enumerate(sections):
            if s['type'] == 'rule':
                src = s['options'].get('src', '')
                dest = s['options'].get('dest', '')
                target = s['options'].get('target', '')
                if src == 'iot' and dest == 'wan':
                    if target == 'ACCEPT':
                        allow_positions.append(i)
                    elif target == 'REJECT':
                        reject_position = i
        assert allow_positions, "No IoT allow rules found"
        assert reject_position is not None, "No IoT reject-all rule found"
        assert all(pos < reject_position for pos in allow_positions), \
            "IoT allow rules must appear BEFORE the reject-all rule — " \
            "firewall rules are evaluated in order, a reject-all placed " \
            "first shadows all subsequent allows"


# ---------------------------------------------------------------------------
# 7. DNS Leak Prevention
# ---------------------------------------------------------------------------
class TestDNSLeakPrevention:
    """Verify DNS DNAT redirects for guest and IoT zones."""

    def _find_dns_redirect(self, sections, src_zone):
        for s in sections:
            if s['type'] == 'redirect':
                src = s['options'].get('src', '')
                src_dport = s['options'].get('src_dport', '')
                target = s['options'].get('target', '')
                if src == src_zone and '53' in src_dport and target == 'DNAT':
                    return s
        return None

    def test_guest_dns_redirect(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        redir = self._find_dns_redirect(sections, 'guest')
        assert redir is not None, \
            "Missing DNS DNAT redirect for guest zone — DNS queries " \
            "would leak through the VPN tunnel to external resolvers"

    def test_iot_dns_redirect(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        redir = self._find_dns_redirect(sections, 'iot')
        assert redir is not None, \
            "Missing DNS DNAT redirect for IoT zone — IoT devices " \
            "could exfiltrate data via DNS tunneling to external servers"


# ---------------------------------------------------------------------------
# 8. IPv6 ULA Architecture
# ---------------------------------------------------------------------------
class TestIPv6Architecture:
    """Verify selective IPv6 ULA deployment."""

    def test_ula_prefix_configured(self):
        sections = parse_uci_config(NETWORK_CONFIG)
        for s in sections:
            if s['type'] == 'globals':
                ula = s['options'].get('ula_prefix', '')
                assert ula.startswith('fd'), \
                    f"ULA prefix must start with 'fd', got '{ula}'"
                return
        pytest.fail("globals section not found in network config")

    def test_ula_prefix_exact(self):
        """ULA prefix must be exactly fd12:3456:789a::/48 per the change request."""
        sections = parse_uci_config(NETWORK_CONFIG)
        for s in sections:
            if s['type'] == 'globals':
                ula = s['options'].get('ula_prefix', '')
                assert ula == 'fd12:3456:789a::/48', \
                    f"ULA prefix must be 'fd12:3456:789a::/48', got '{ula}'"
                return
        pytest.fail("globals section not found in network config")

    def test_mgmt_has_ipv6(self):
        sections = parse_uci_config(NETWORK_CONFIG)
        iface = find_interface(sections, 'mgmt')
        assert iface is not None, "mgmt interface not found"
        assert 'ip6assign' in iface['options'], \
            "mgmt interface must have ip6assign for IPv6 ULA"

    def test_corp_has_ipv6(self):
        sections = parse_uci_config(NETWORK_CONFIG)
        iface = find_interface(sections, 'corp')
        assert iface is not None, "corp interface not found"
        assert 'ip6assign' in iface['options'], \
            "corp interface must have ip6assign for IPv6 ULA"

    def test_iot_no_ipv6(self):
        """IoT must not have IPv6 — would bypass IPv4 policy routing."""
        sections = parse_uci_config(NETWORK_CONFIG)
        iface = find_interface(sections, 'iot')
        assert iface is not None, "iot interface not found"
        assert 'ip6assign' not in iface['options'], \
            "iot interface must NOT have ip6assign — IPv6 would " \
            "bypass the IPv4 outbound port restrictions"

    def test_guest_no_ipv6(self):
        """Guest must not have IPv6 — would bypass VPN policy routing."""
        sections = parse_uci_config(NETWORK_CONFIG)
        iface = find_interface(sections, 'guest')
        assert iface is not None, "guest interface not found"
        assert 'ip6assign' not in iface['options'], \
            "guest interface must NOT have ip6assign — IPv6 would " \
            "bypass the VPN tunnel and leak traffic to the WAN"


# ---------------------------------------------------------------------------
# 9. Masquerade Architecture
# ---------------------------------------------------------------------------
class TestMasqueradeArchitecture:
    """Verify masquerade is placed only on zones that require NAT."""

    def test_wan_has_masquerade(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'wan')
        assert zone is not None, "wan zone not found"
        assert zone['options'].get('masq') == '1'

    def test_wan_backup_has_masquerade(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'wan_backup')
        assert zone is not None, "wan_backup zone not found"
        assert zone['options'].get('masq') == '1'

    def test_vpn_ext_has_masquerade(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'vpn_ext')
        assert zone is not None, "vpn_ext zone not found"
        assert zone['options'].get('masq') == '1'

    def test_vpn_hq_no_masquerade(self):
        """HQ has return routes to our subnets — NAT would hide source IPs."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        zone = find_zone(sections, 'vpn_hq')
        assert zone is not None, "vpn_hq zone not found"
        masq = zone['options'].get('masq', '0')
        assert masq != '1', \
            "vpn_hq zone must NOT have masquerade — HQ has static " \
            "return routes, NAT is unnecessary and hides source IPs"

    def test_internal_zones_no_masquerade(self):
        """Internal zones should not have masquerade."""
        sections = parse_uci_config(FIREWALL_CONFIG)
        for zone_name in ('mgmt', 'corp', 'iot', 'guest'):
            zone = find_zone(sections, zone_name)
            assert zone is not None, f"zone {zone_name} not found"
            masq = zone['options'].get('masq', '0')
            assert masq != '1', \
                f"Internal zone '{zone_name}' should not have masquerade"


# ---------------------------------------------------------------------------
# 10. WAN Hardening
# ---------------------------------------------------------------------------
class TestWANHardening:
    """Verify WAN ingress security controls."""

    def test_wan_rate_limit(self):
        sections = parse_uci_config(FIREWALL_CONFIG)
        found = False
        for s in sections:
            if s['type'] == 'rule':
                src = s['options'].get('src', '')
                limit = s['options'].get('limit', '')
                if src == 'wan' and '25' in limit:
                    found = True
                    break
        assert found, \
            "Missing WAN rate limit rule: incoming TCP should be " \
            "limited to 25/min to mitigate connection floods"
