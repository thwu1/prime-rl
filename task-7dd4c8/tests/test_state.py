
import json
import os
import re
import pytest
import ipaddress


AUDIT_PATH = '/app/audit.json'
RULES_PATH = '/app/rules.nft'

FLOW_IDS = [f'capture_{i:02d}' for i in range(1, 11)]

EXPECTED = {
    'capture_01': {'classification': 'legitimate',              'severity': 'none',     'ext': []},
    'capture_02': {'classification': 'legitimate',              'severity': 'none',     'ext': ['hop-by-hop', 'destination']},
    'capture_03': {'classification': 'deprecated_routing',      'severity': 'high',     'ext': ['routing']},
    'capture_04': {'classification': 'fragment_evasion',        'severity': 'high',     'ext': ['fragment']},
    'capture_05': {'classification': 'legitimate',              'severity': 'none',     'ext': ['fragment']},
    'capture_06': {'classification': 'oversized_reassembly',    'severity': 'critical', 'ext': ['fragment']},
    'capture_07': {'classification': 'header_chain_violation',  'severity': 'medium',   'ext': ['routing', 'hop-by-hop']},
    'capture_08': {'classification': 'header_chain_violation',  'severity': 'medium',   'ext': ['routing', 'routing']},
    'capture_09': {'classification': 'fragment_evasion',        'severity': 'high',     'ext': ['fragment']},
    'capture_10': {'classification': 'legitimate',              'severity': 'none',     'ext': []},
}

SEVERITY_ORDER = {'none': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}

EXPECTED_ADDRS = {
    'capture_01': ('2001:db8:a::1', '2001:db8:b::1'),
    'capture_02': ('2001:db8:a::2', '2001:db8:b::2'),
    'capture_03': ('2001:db8:a::3', '2001:db8:b::3'),
    'capture_04': ('2001:db8:a::4', '2001:db8:b::4'),
    'capture_05': ('2001:db8:a::5', '2001:db8:b::5'),
    'capture_06': ('2001:db8:a::6', '2001:db8:b::6'),
    'capture_07': ('2001:db8:a::7', '2001:db8:b::7'),
    'capture_08': ('2001:db8:a::8', '2001:db8:b::8'),
    'capture_09': ('2001:db8:a::9', '2001:db8:b::9'),
    'capture_10': ('fe80::1', 'ff02::1:ff00:1'),
}


def norm(addr):
    return str(ipaddress.IPv6Address(addr))


@pytest.fixture(scope='module')
def audit():
    assert os.path.exists(AUDIT_PATH), f"{AUDIT_PATH} not found"
    with open(AUDIT_PATH) as f:
        data = json.load(f)
    assert 'flows' in data, "audit.json missing 'flows' key"
    assert 'summary' in data, "audit.json missing 'summary' key"
    return data


@pytest.fixture(scope='module')
def rules():
    assert os.path.exists(RULES_PATH), f"{RULES_PATH} not found"
    with open(RULES_PATH) as f:
        return f.read()


# ===================== Structure =====================

class TestAuditStructure:
    def test_all_flows_present(self, audit):
        for fid in FLOW_IDS:
            assert fid in audit['flows'], f"Flow {fid} missing from audit.json"

    def test_flow_count(self, audit):
        assert len(audit['flows']) >= 10


# ===================== Classification =====================

class TestClassification:
    @pytest.mark.parametrize("fid", FLOW_IDS)
    def test_classification(self, audit, fid):
        flow = audit['flows'][fid]
        expected_class = EXPECTED[fid]['classification']
        assert flow['classification'] == expected_class, \
            f"{fid}: expected '{expected_class}', got '{flow['classification']}'"


# ===================== Addresses =====================

class TestAddresses:
    @pytest.mark.parametrize("fid", ['capture_01', 'capture_03', 'capture_06', 'capture_10'])
    def test_src_addr(self, audit, fid):
        flow = audit['flows'][fid]
        expected_src = EXPECTED_ADDRS[fid][0]
        assert norm(flow['src_addr']) == norm(expected_src), \
            f"{fid} src: expected {expected_src}, got {flow['src_addr']}"

    @pytest.mark.parametrize("fid", ['capture_01', 'capture_03', 'capture_06', 'capture_10'])
    def test_dst_addr(self, audit, fid):
        flow = audit['flows'][fid]
        expected_dst = EXPECTED_ADDRS[fid][1]
        assert norm(flow['dst_addr']) == norm(expected_dst), \
            f"{fid} dst: expected {expected_dst}, got {flow['dst_addr']}"


# ===================== Extension Headers =====================

class TestExtensionHeaders:
    @pytest.mark.parametrize("fid", [
        'capture_01', 'capture_02', 'capture_03', 'capture_04',
        'capture_07', 'capture_08', 'capture_10'
    ])
    def test_extension_headers(self, audit, fid):
        flow = audit['flows'][fid]
        expected_ext = EXPECTED[fid]['ext']
        assert flow['extension_headers'] == expected_ext, \
            f"{fid}: expected ext {expected_ext}, got {flow['extension_headers']}"

    def test_fragment_flows_have_fragment_header(self, audit):
        """All fragment-related flows must list 'fragment' in extension_headers."""
        for fid in ['capture_04', 'capture_05', 'capture_06', 'capture_09']:
            flow = audit['flows'][fid]
            assert 'fragment' in flow['extension_headers'], \
                f"{fid} should have 'fragment' in extension_headers"


# ===================== Threat Severity =====================

class TestSeverity:
    def test_legitimate_flows_none(self, audit):
        for fid in ['capture_01', 'capture_02', 'capture_05', 'capture_10']:
            flow = audit['flows'][fid]
            assert flow['threat_severity'] == 'none', \
                f"{fid}: legitimate flow should have severity 'none', got '{flow['threat_severity']}'"

    def test_fragment_evasion_severity(self, audit):
        for fid in ['capture_04', 'capture_09']:
            flow = audit['flows'][fid]
            assert SEVERITY_ORDER.get(flow['threat_severity'], 0) >= SEVERITY_ORDER['high'], \
                f"{fid}: fragment_evasion should be 'high' or 'critical', got '{flow['threat_severity']}'"

    def test_deprecated_routing_severity(self, audit):
        flow = audit['flows']['capture_03']
        assert SEVERITY_ORDER.get(flow['threat_severity'], 0) >= SEVERITY_ORDER['high'], \
            f"capture_03: deprecated_routing should be 'high' or 'critical', got '{flow['threat_severity']}'"

    def test_oversized_reassembly_severity(self, audit):
        flow = audit['flows']['capture_06']
        assert SEVERITY_ORDER.get(flow['threat_severity'], 0) >= SEVERITY_ORDER['high'], \
            f"capture_06: oversized_reassembly should be 'high' or 'critical', got '{flow['threat_severity']}'"

    def test_header_chain_violation_severity(self, audit):
        for fid in ['capture_07', 'capture_08']:
            flow = audit['flows'][fid]
            assert SEVERITY_ORDER.get(flow['threat_severity'], 0) >= SEVERITY_ORDER['medium'], \
                f"{fid}: header_chain_violation should be >= 'medium', got '{flow['threat_severity']}'"


# ===================== Violation Descriptions =====================

class TestViolationDescriptions:
    def test_legitimate_null_description(self, audit):
        for fid in ['capture_01', 'capture_02', 'capture_05', 'capture_10']:
            flow = audit['flows'][fid]
            assert flow.get('violation_description') is None, \
                f"{fid}: legitimate flow should have null violation_description"

    def test_malicious_has_description(self, audit):
        for fid in ['capture_03', 'capture_04', 'capture_06', 'capture_07', 'capture_08', 'capture_09']:
            flow = audit['flows'][fid]
            desc = flow.get('violation_description')
            assert desc is not None and len(str(desc)) > 0, \
                f"{fid}: malicious flow should have non-empty violation_description"


# ===================== Summary =====================

class TestSummary:
    def test_total_flows(self, audit):
        assert audit['summary']['total_flows'] == 10

    def test_legitimate_count(self, audit):
        assert audit['summary']['legitimate_count'] == 4

    def test_malicious_count(self, audit):
        assert audit['summary']['malicious_count'] == 6

    def test_threat_categories_present(self, audit):
        cats = set(audit['summary']['threat_categories'])
        expected_cats = {'deprecated_routing', 'fragment_evasion',
                         'header_chain_violation', 'oversized_reassembly'}
        assert cats == expected_cats, \
            f"Expected categories {expected_cats}, got {cats}"


# ===================== Firewall Rules =====================

class TestFirewallRules:
    def test_rules_file_exists(self, rules):
        assert len(rules.strip()) > 0, "rules.nft is empty"

    def test_defines_table(self, rules):
        assert re.search(r'\btable\b', rules, re.IGNORECASE), \
            "rules.nft should define at least one nftables table"

    def test_defines_chain(self, rules):
        assert re.search(r'\bchain\b', rules, re.IGNORECASE), \
            "rules.nft should define at least one nftables chain"

    def test_blocks_rh0(self, rules):
        assert re.search(r'rt\s+type\s+0', rules), \
            "rules.nft should block Routing Header Type 0 (e.g., 'rt type 0 drop')"

    def test_handles_icmpv6(self, rules):
        assert re.search(r'icmpv6', rules, re.IGNORECASE), \
            "rules.nft should handle ICMPv6 traffic"

    def test_handles_fragments(self, rules):
        assert re.search(r'frag', rules, re.IGNORECASE), \
            "rules.nft should address IPv6 fragment handling"
