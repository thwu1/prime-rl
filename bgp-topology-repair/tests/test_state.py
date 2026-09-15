"""
Tests for BGP dual-homed traffic engineering design task.
Verifies FRR configuration files implement all required routing policies.
"""

import re
import os
import ipaddress
import pytest

CONFIG_DIR = "/app/configs"


# ===== Config Parsing Helpers =====

def read_config(router):
    path = os.path.join(CONFIG_DIR, f"{router}.conf")
    with open(path) as f:
        return f.read()


def get_bgp_block(config):
    """Extract full BGP block (stops at bare '!' at column 0)."""
    result = []
    in_block = False
    for line in config.split('\n'):
        if re.match(r'^router bgp\s', line):
            in_block = True
            result.append(line)
        elif in_block:
            if line == '!':
                break
            result.append(line)
    return '\n'.join(result)


def get_af_block(config):
    """Extract address-family ipv4 unicast content."""
    m = re.search(
        r'address-family ipv4 unicast\s*\n(.*?)exit-address-family',
        config, re.DOTALL
    )
    return m.group(1) if m else ""


def get_ospf_block(config):
    result = []
    in_block = False
    for line in config.split('\n'):
        if re.match(r'^router ospf', line):
            in_block = True
            result.append(line)
        elif in_block:
            if line == '!':
                break
            result.append(line)
    return '\n'.join(result)


def has_in_bgp(config, pattern):
    return bool(re.search(pattern, get_bgp_block(config)))


def has_in_af(config, pattern):
    return bool(re.search(pattern, get_af_block(config)))


def has_in_ospf(config, pattern):
    return bool(re.search(pattern, get_ospf_block(config)))


def get_af_routemap(config, neighbor, direction):
    af = get_af_block(config)
    m = re.search(
        rf'neighbor\s+{re.escape(neighbor)}\s+route-map\s+(\S+)\s+{direction}',
        af
    )
    return m.group(1) if m else None


def get_routemap_entries(config, mapname):
    """Get all route-map entries for a given map name."""
    entries = []
    current = None
    for line in config.split('\n'):
        if re.match(rf'^route-map\s+{re.escape(mapname)}\s+', line):
            current = [line]
        elif current is not None:
            if line == '!' or (line and not line.startswith(' ')):
                entries.append('\n'.join(current))
                if re.match(rf'^route-map\s+{re.escape(mapname)}\s+', line):
                    current = [line]
                else:
                    current = None
            else:
                current.append(line)
    if current:
        entries.append('\n'.join(current))
    return entries


def get_prefix_list_entries(config, name):
    entries = []
    for line in config.split('\n'):
        m = re.match(rf'\s*ip\s+prefix-list\s+{re.escape(name)}\s+(.*)', line)
        if m:
            entries.append(m.group(1))
    return entries


def prefix_list_could_permit(config, name, target_prefix):
    """Check if a prefix-list could permit a specific prefix (handles le/ge)."""
    target_net = ipaddress.ip_network(target_prefix)
    for entry in get_prefix_list_entries(config, name):
        m = re.match(r'(?:seq\s+\d+\s+)?(permit|deny)\s+(\S+)', entry.strip())
        if not m or m.group(1) != 'permit':
            continue
        try:
            net = ipaddress.ip_network(m.group(2))
        except ValueError:
            continue
        le_m = re.search(r'le\s+(\d+)', entry)
        ge_m = re.search(r'ge\s+(\d+)', entry)
        min_len = int(ge_m.group(1)) if ge_m else net.prefixlen
        max_len = int(le_m.group(1)) if le_m else (32 if ge_m else net.prefixlen)
        if (target_net.network_address in net and
                min_len <= target_net.prefixlen <= max_len):
            return True
    return False


def get_prefixlists_in_routemap(config, mapname):
    """Get all prefix-list names referenced in a route-map's match clauses."""
    pfx_lists = set()
    for entry in get_routemap_entries(config, mapname):
        for m in re.finditer(r'match\s+ip\s+address\s+prefix-list\s+(\S+)', entry):
            pfx_lists.add(m.group(1))
    return pfx_lists


def routemap_entry_has_match(entry):
    return bool(re.search(r'^\s+match\s+', entry, re.MULTILINE))


def all_permit_entries_have_match(config, mapname):
    """Every permit entry must have a match clause (no catch-all)."""
    for entry in get_routemap_entries(config, mapname):
        if re.search(r'route-map\s+\S+\s+permit\s+', entry):
            if not routemap_entry_has_match(entry):
                return False
    return True


def routemap_sets_locpref(config, mapname, value):
    for entry in get_routemap_entries(config, mapname):
        if re.search(rf'set\s+local-preference\s+{value}', entry):
            return True
    return False


# ===== OSPF Tests =====

class TestOSPF:
    """OSPF within AS 65100 for iBGP loopback reachability."""

    def test_r1_ospf_loopback(self):
        assert has_in_ospf(read_config("r1"), r'network\s+10\.255\.0\.1'), \
            "R1 missing OSPF loopback network"

    def test_r1_ospf_r3_link(self):
        assert has_in_ospf(read_config("r1"), r'network\s+10\.0\.13\.'), \
            "R1 missing OSPF network for R1-R3 link"

    def test_r2_ospf_loopback(self):
        assert has_in_ospf(read_config("r2"), r'network\s+10\.255\.0\.2'), \
            "R2 missing OSPF loopback network"

    def test_r2_ospf_r3_link(self):
        assert has_in_ospf(read_config("r2"), r'network\s+10\.0\.23\.'), \
            "R2 missing OSPF network for R2-R3 link"

    def test_r3_ospf_loopback(self):
        assert has_in_ospf(read_config("r3"), r'network\s+10\.255\.0\.3'), \
            "R3 missing OSPF loopback network"

    def test_r3_ospf_r1_link(self):
        assert has_in_ospf(read_config("r3"), r'network\s+10\.0\.13\.'), \
            "R3 missing OSPF network for R3-R1 link"

    def test_r3_ospf_r2_link(self):
        assert has_in_ospf(read_config("r3"), r'network\s+10\.0\.23\.'), \
            "R3 missing OSPF network for R3-R2 link"


# ===== BGP Peering Tests =====

class TestBGPPeering:
    """All required BGP sessions with correct ASNs and update-source."""

    def test_r1_ibgp_r3(self):
        assert has_in_bgp(read_config("r1"),
                          r'neighbor\s+10\.255\.0\.3\s+remote-as\s+65100')

    def test_r1_ibgp_update_source(self):
        assert has_in_bgp(read_config("r1"),
                          r'neighbor\s+10\.255\.0\.3\s+update-source')

    def test_r1_ebgp_r4(self):
        assert has_in_bgp(read_config("r1"),
                          r'neighbor\s+10\.0\.14\.4\s+remote-as\s+65200')

    def test_r2_ibgp_r3(self):
        assert has_in_bgp(read_config("r2"),
                          r'neighbor\s+10\.255\.0\.3\s+remote-as\s+65100')

    def test_r2_ibgp_update_source(self):
        assert has_in_bgp(read_config("r2"),
                          r'neighbor\s+10\.255\.0\.3\s+update-source')

    def test_r2_ebgp_r5(self):
        assert has_in_bgp(read_config("r2"),
                          r'neighbor\s+10\.0\.25\.5\s+remote-as\s+65300')

    def test_r3_ibgp_r1(self):
        assert has_in_bgp(read_config("r3"),
                          r'neighbor\s+10\.255\.0\.1\s+remote-as\s+65100')

    def test_r3_ibgp_r1_update_source(self):
        assert has_in_bgp(read_config("r3"),
                          r'neighbor\s+10\.255\.0\.1\s+update-source')

    def test_r3_ibgp_r2(self):
        assert has_in_bgp(read_config("r3"),
                          r'neighbor\s+10\.255\.0\.2\s+remote-as\s+65100')

    def test_r3_ibgp_r2_update_source(self):
        assert has_in_bgp(read_config("r3"),
                          r'neighbor\s+10\.255\.0\.2\s+update-source')

    def test_r4_ebgp_r1(self):
        assert has_in_bgp(read_config("r4"),
                          r'neighbor\s+10\.0\.14\.1\s+remote-as\s+65100')

    def test_r5_ebgp_r2(self):
        assert has_in_bgp(read_config("r5"),
                          r'neighbor\s+10\.0\.25\.2\s+remote-as\s+65100')


# ===== Route Reflection Tests =====

class TestRouteReflection:
    """R3 must be route reflector with R1 and R2 as clients."""

    def test_r3_rr_r1(self):
        assert has_in_af(read_config("r3"),
                         r'neighbor\s+10\.255\.0\.1\s+route-reflector-client'), \
            "R3 missing route-reflector-client for R1"

    def test_r3_rr_r2(self):
        assert has_in_af(read_config("r3"),
                         r'neighbor\s+10\.255\.0\.2\s+route-reflector-client'), \
            "R3 missing route-reflector-client for R2"


# ===== Next-Hop-Self Tests =====

class TestNextHopSelf:
    """Border routers must rewrite next-hop for reflected eBGP routes."""

    def test_r1_nhs(self):
        assert has_in_af(read_config("r1"),
                         r'neighbor\s+10\.255\.0\.3\s+next-hop-self'), \
            "R1 missing next-hop-self for iBGP peer R3"

    def test_r2_nhs(self):
        assert has_in_af(read_config("r2"),
                         r'neighbor\s+10\.255\.0\.3\s+next-hop-self'), \
            "R2 missing next-hop-self for iBGP peer R3"


# ===== Network Origination Tests =====

class TestNetworks:
    """All prefixes originated from correct routers."""

    def test_r3_agg(self):
        assert has_in_af(read_config("r3"), r'network\s+10\.100\.0\.0/22')

    def test_r3_p0(self):
        assert has_in_af(read_config("r3"), r'network\s+10\.100\.0\.0/24')

    def test_r3_p1(self):
        assert has_in_af(read_config("r3"), r'network\s+10\.100\.1\.0/24')

    def test_r3_p2(self):
        assert has_in_af(read_config("r3"), r'network\s+10\.100\.2\.0/24')

    def test_r3_p3(self):
        assert has_in_af(read_config("r3"), r'network\s+10\.100\.3\.0/24')

    def test_r4_ispa_prefix(self):
        assert has_in_af(read_config("r4"), r'network\s+203\.0\.113\.0/24')

    def test_r4_dual_prefix(self):
        assert has_in_af(read_config("r4"), r'network\s+192\.0\.2\.0/24')

    def test_r5_ispb_prefix(self):
        assert has_in_af(read_config("r5"), r'network\s+198\.51\.100\.0/24')

    def test_r5_dual_prefix(self):
        assert has_in_af(read_config("r5"), r'network\s+192\.0\.2\.0/24')


# ===== Outbound TE: Local Preference =====

class TestOutboundTE:
    """R1 sets local-preference 200 on routes from ISP-Alpha (AS-wide effect)."""

    def test_r1_inbound_rm_exists(self):
        rm = get_af_routemap(read_config("r1"), "10.0.14.4", "in")
        assert rm is not None, "R1 missing inbound route-map from R4"

    def test_r1_locpref_200(self):
        config = read_config("r1")
        rm = get_af_routemap(config, "10.0.14.4", "in")
        assert rm and routemap_sets_locpref(config, rm, 200), \
            "R1 inbound route-map from R4 must set local-preference 200"


# ===== Inbound TE: AS-Path Prepending =====

class TestInboundTE:
    """R1 prepends AS 65100 >=3x for aggregate toward ISP-Alpha."""

    def test_r1_outbound_rm_exists(self):
        rm = get_af_routemap(read_config("r1"), "10.0.14.4", "out")
        assert rm is not None, "R1 missing outbound route-map to R4"

    def test_r1_prepend_targets_aggregate(self):
        """Prepend entry must match 10.100.0.0/22 via prefix-list."""
        config = read_config("r1")
        rm = get_af_routemap(config, "10.0.14.4", "out")
        assert rm is not None
        found = False
        for entry in get_routemap_entries(config, rm):
            if not re.search(r'set\s+as-path\s+prepend', entry):
                continue
            pfx_m = re.search(
                r'match\s+ip\s+address\s+prefix-list\s+(\S+)', entry)
            if pfx_m and prefix_list_could_permit(
                    config, pfx_m.group(1), "10.100.0.0/22"):
                found = True
                break
        assert found, \
            "R1 outbound to R4 must prepend AS-path for 10.100.0.0/22"

    def test_r1_prepend_count_gte_3(self):
        """Must prepend AS 65100 at least 3 times."""
        config = read_config("r1")
        rm = get_af_routemap(config, "10.0.14.4", "out")
        assert rm is not None
        for entry in get_routemap_entries(config, rm):
            m = re.search(r'set\s+as-path\s+prepend\s+([\d\s]+)', entry)
            if m:
                count = sum(1 for a in m.group(1).strip().split()
                            if a == "65100")
                if count >= 3:
                    return
        pytest.fail("R1 must prepend AS 65100 at least 3 times")


# ===== Selective Advertisement =====

class TestSelectiveAdvertisement:
    """R1/R2 advertise only designated customer prefixes to their ISPs."""

    # --- R1 → ISP-Alpha: 10.100.0.0/22, /0, /1 only ---

    def test_r1_permits_aggregate(self):
        config = read_config("r1")
        rm = get_af_routemap(config, "10.0.14.4", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        assert any(prefix_list_could_permit(config, p, "10.100.0.0/22")
                    for p in pls), "R1 must permit 10.100.0.0/22 to ISP-Alpha"

    def test_r1_permits_p0(self):
        config = read_config("r1")
        rm = get_af_routemap(config, "10.0.14.4", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        assert any(prefix_list_could_permit(config, p, "10.100.0.0/24")
                    for p in pls), "R1 must permit 10.100.0.0/24 to ISP-Alpha"

    def test_r1_permits_p1(self):
        config = read_config("r1")
        rm = get_af_routemap(config, "10.0.14.4", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        assert any(prefix_list_could_permit(config, p, "10.100.1.0/24")
                    for p in pls), "R1 must permit 10.100.1.0/24 to ISP-Alpha"

    def test_r1_blocks_p2(self):
        config = read_config("r1")
        rm = get_af_routemap(config, "10.0.14.4", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        for p in pls:
            assert not prefix_list_could_permit(config, p, "10.100.2.0/24"), \
                "R1 must NOT advertise 10.100.2.0/24 to ISP-Alpha"

    def test_r1_blocks_p3(self):
        config = read_config("r1")
        rm = get_af_routemap(config, "10.0.14.4", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        for p in pls:
            assert not prefix_list_could_permit(config, p, "10.100.3.0/24"), \
                "R1 must NOT advertise 10.100.3.0/24 to ISP-Alpha"

    # --- R2 → ISP-Beta: 10.100.0.0/22, /2, /3 only ---

    def test_r2_outbound_rm(self):
        rm = get_af_routemap(read_config("r2"), "10.0.25.5", "out")
        assert rm is not None, "R2 missing outbound route-map to R5"

    def test_r2_permits_aggregate(self):
        config = read_config("r2")
        rm = get_af_routemap(config, "10.0.25.5", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        assert any(prefix_list_could_permit(config, p, "10.100.0.0/22")
                    for p in pls), "R2 must permit 10.100.0.0/22 to ISP-Beta"

    def test_r2_permits_p2(self):
        config = read_config("r2")
        rm = get_af_routemap(config, "10.0.25.5", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        assert any(prefix_list_could_permit(config, p, "10.100.2.0/24")
                    for p in pls), "R2 must permit 10.100.2.0/24 to ISP-Beta"

    def test_r2_permits_p3(self):
        config = read_config("r2")
        rm = get_af_routemap(config, "10.0.25.5", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        assert any(prefix_list_could_permit(config, p, "10.100.3.0/24")
                    for p in pls), "R2 must permit 10.100.3.0/24 to ISP-Beta"

    def test_r2_blocks_p0(self):
        config = read_config("r2")
        rm = get_af_routemap(config, "10.0.25.5", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        for p in pls:
            assert not prefix_list_could_permit(config, p, "10.100.0.0/24"), \
                "R2 must NOT advertise 10.100.0.0/24 to ISP-Beta"

    def test_r2_blocks_p1(self):
        config = read_config("r2")
        rm = get_af_routemap(config, "10.0.25.5", "out")
        assert rm
        pls = get_prefixlists_in_routemap(config, rm)
        for p in pls:
            assert not prefix_list_could_permit(config, p, "10.100.1.0/24"), \
                "R2 must NOT advertise 10.100.1.0/24 to ISP-Beta"


# ===== Transit Prevention =====

class TestTransitPrevention:
    """No catch-all permit in outbound eBGP route-maps."""

    def test_r1_no_catchall(self):
        config = read_config("r1")
        rm = get_af_routemap(config, "10.0.14.4", "out")
        assert rm and all_permit_entries_have_match(config, rm), \
            "R1 outbound to R4: permit entry without match clause (transit leak)"

    def test_r2_no_catchall(self):
        config = read_config("r2")
        rm = get_af_routemap(config, "10.0.25.5", "out")
        assert rm and all_permit_entries_have_match(config, rm), \
            "R2 outbound to R5: permit entry without match clause (transit leak)"


# ===== Config Integrity =====

class TestIntegrity:
    """Interface addressing and BGP ASNs are correct."""

    def test_r1_lo(self):
        assert "10.255.0.1/32" in read_config("r1")

    def test_r1_eth0(self):
        assert "10.0.13.1/24" in read_config("r1")

    def test_r1_eth1(self):
        assert "10.0.14.1/24" in read_config("r1")

    def test_r2_lo(self):
        assert "10.255.0.2/32" in read_config("r2")

    def test_r2_eth0(self):
        assert "10.0.23.2/24" in read_config("r2")

    def test_r2_eth1(self):
        assert "10.0.25.2/24" in read_config("r2")

    def test_r3_lo(self):
        assert "10.255.0.3/32" in read_config("r3")

    def test_r3_eth0(self):
        assert "10.0.13.3/24" in read_config("r3")

    def test_r3_eth1(self):
        assert "10.0.23.3/24" in read_config("r3")

    def test_r4_lo(self):
        assert "10.255.1.4/32" in read_config("r4")

    def test_r4_eth0(self):
        assert "10.0.14.4/24" in read_config("r4")

    def test_r5_lo(self):
        assert "10.255.2.5/32" in read_config("r5")

    def test_r5_eth0(self):
        assert "10.0.25.5/24" in read_config("r5")

    def test_r1_asn(self):
        assert re.search(r'^router bgp 65100', read_config("r1"), re.MULTILINE)

    def test_r2_asn(self):
        assert re.search(r'^router bgp 65100', read_config("r2"), re.MULTILINE)

    def test_r3_asn(self):
        assert re.search(r'^router bgp 65100', read_config("r3"), re.MULTILINE)

    def test_r4_asn(self):
        assert re.search(r'^router bgp 65200', read_config("r4"), re.MULTILINE)

    def test_r5_asn(self):
        assert re.search(r'^router bgp 65300', read_config("r5"), re.MULTILINE)
