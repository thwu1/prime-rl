"""
Tests for CLOS datacenter network health audit with fault/planned-change classification
and packet-level forensic evidence extraction.

"""

import json
import os
import pytest

ASSESSMENT_PATH = "/app/results/assessment.json"

# Ground truth: 6 genuine faults
EXPECTED_FAULTS = {
    "lf0": {
        "desc_keywords": ["asn", "as ", "autonomous", "65200", "65199", "as number", "as_number"],
        "fix_keywords": ["65200"],
    },
    "lf1": {
        "desc_keywords": ["static", "null", "blackhole", "null0", "10.0.2", "rib", "route"],
        "fix_keywords": ["10.0.2", "null", "route"],
    },
    "lf2": {
        "desc_keywords": ["password", "md5", "auth", "tcp", "secret", "mismatch"],
        "fix_keywords": ["password", "no neighbor", "remove", "delete"],
    },
    "sp1": {
        "desc_keywords": ["nftables", "firewall", "179", "bgp", "sec_hardening", "acl", "filter", "drop"],
        "fix_keywords": ["nft", "delete", "flush", "remove", "sec_hardening"],
    },
    "lf3": {
        "desc_keywords": ["network", "10.0.3", "advertis", "missing", "subnet"],
        "fix_keywords": ["network 10.0.3", "10.0.3.0"],
    },
    "h3": {
        "desc_keywords": ["mask", "netmask", "/16", "/24", "255.255", "subnet", "prefix"],
        "fix_keywords": ["/24", "255.255.255.0", "netmask", "mask"],
    },
}

# Ground truth: 3 documented planned changes
EXPECTED_PLANNED = {
    "ss0": {
        "keywords": ["timer", "keepalive", "hold", "10", "30", "convergence", "detection"],
        "ops_ids": ["ops-4499", "ops_4499", "4499"],
    },
    "sp0": {
        "keywords": ["icmp", "rate", "limit", "flood", "50"],
        "ops_ids": ["sec-0088", "sec_0088", "0088"],
    },
    "lf3": {
        "keywords": ["tc", "tbf", "rate", "bandwidth", "50", "tenant", "sla", "token"],
        "ops_ids": ["ops-4521", "ops_4521", "4521"],
    },
}


@pytest.fixture
def assessment():
    """Load the assessment JSON file."""
    assert os.path.exists(ASSESSMENT_PATH), (
        f"Assessment file not found at {ASSESSMENT_PATH}"
    )
    with open(ASSESSMENT_PATH, "r") as f:
        data = json.load(f)
    return data


def _kw_match(text, keywords):
    """Check if text contains any keyword (case-insensitive, normalized)."""
    t = text.lower().replace("-", "_").replace(" ", "_")
    return any(kw.lower().replace("-", "_").replace(" ", "_") in t for kw in keywords)


def test_assessment_file_exists():
    """The assessment JSON file must exist."""
    assert os.path.exists(ASSESSMENT_PATH), (
        f"Assessment file not found at {ASSESSMENT_PATH}"
    )


def test_valid_json_structure(assessment):
    """Assessment must have required top-level fields."""
    assert isinstance(assessment, dict), "Assessment must be a JSON object"
    assert "total_anomalies" in assessment, "Missing 'total_anomalies' field"
    assert "anomalies" in assessment, "Missing 'anomalies' field"
    assert "remediation_order" in assessment, "Missing 'remediation_order' field"
    assert isinstance(assessment["anomalies"], list), "'anomalies' must be an array"
    assert isinstance(assessment["remediation_order"], list), "'remediation_order' must be an array"


def test_total_anomaly_count(assessment):
    """Exactly 9 anomalies must be identified (6 faults + 3 planned changes)."""
    assert assessment["total_anomalies"] == 9, (
        f"Expected 9 total anomalies, got {assessment['total_anomalies']}"
    )


def test_anomaly_array_length(assessment):
    """The anomalies array length must match total_anomalies."""
    assert len(assessment["anomalies"]) == assessment["total_anomalies"], (
        f"anomalies array has {len(assessment['anomalies'])} entries but "
        f"total_anomalies is {assessment['total_anomalies']}"
    )


def test_fault_count(assessment):
    """Exactly 6 anomalies must be classified as 'fault'."""
    faults = [a for a in assessment["anomalies"] if a.get("classification") == "fault"]
    assert len(faults) == 6, (
        f"Expected 6 faults, got {len(faults)}"
    )


def test_planned_change_count(assessment):
    """Exactly 3 anomalies must be classified as 'planned_change'."""
    planned = [a for a in assessment["anomalies"]
               if a.get("classification") == "planned_change"]
    assert len(planned) == 3, (
        f"Expected 3 planned changes, got {len(planned)}"
    )


def test_classification_values(assessment):
    """Every anomaly must have classification 'fault' or 'planned_change'."""
    for i, a in enumerate(assessment["anomalies"]):
        assert a.get("classification") in ("fault", "planned_change"), (
            f"Anomaly {i} has invalid classification: {a.get('classification')}"
        )


def test_fault_devices(assessment):
    """All 6 faulty devices must be identified."""
    faults = [a for a in assessment["anomalies"] if a["classification"] == "fault"]
    fault_devices = {f["device"] for f in faults}
    expected = set(EXPECTED_FAULTS.keys())
    missing = expected - fault_devices
    extra = fault_devices - expected
    assert not missing, (
        f"Missing fault devices: {missing}. Found: {fault_devices}"
    )
    assert not extra, (
        f"False positive fault devices: {extra}. Expected only: {expected}"
    )


def test_planned_change_devices(assessment):
    """All 3 planned change devices must be identified."""
    planned = [a for a in assessment["anomalies"]
               if a["classification"] == "planned_change"]
    planned_devices = {p["device"] for p in planned}
    expected = set(EXPECTED_PLANNED.keys())
    missing = expected - planned_devices
    extra = planned_devices - expected
    assert not missing, (
        f"Missing planned change devices: {missing}. Found: {planned_devices}"
    )
    assert not extra, (
        f"False positive planned change devices: {extra}. Expected only: {expected}"
    )


def test_lf0_fault_description(assessment):
    """lf0 fault must be identified as BGP ASN misconfiguration."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "lf0"]
    assert len(faults) == 1, f"Expected 1 fault for lf0, got {len(faults)}"
    desc = faults[0].get("description", "")
    assert _kw_match(desc, EXPECTED_FAULTS["lf0"]["desc_keywords"]), (
        f"lf0 description doesn't mention ASN issue: '{desc[:100]}...'"
    )


def test_lf0_corrected_config(assessment):
    """lf0 corrected config must contain correct ASN 65200."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "lf0"]
    config = faults[0].get("corrected_config") or ""
    assert _kw_match(config, EXPECTED_FAULTS["lf0"]["fix_keywords"]), (
        f"lf0 corrected_config missing '65200': '{config[:100]}...'"
    )


def test_lf1_fault_description(assessment):
    """lf1 fault must identify the static blackhole route."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "lf1"]
    assert len(faults) == 1, f"Expected 1 fault for lf1, got {len(faults)}"
    desc = faults[0].get("description", "")
    assert _kw_match(desc, EXPECTED_FAULTS["lf1"]["desc_keywords"]), (
        f"lf1 description doesn't mention static/blackhole/Null0 route: '{desc[:100]}...'"
    )


def test_lf1_corrected_config(assessment):
    """lf1 corrected config must address the static route removal."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "lf1"]
    config = faults[0].get("corrected_config") or ""
    assert _kw_match(config, EXPECTED_FAULTS["lf1"]["fix_keywords"]), (
        f"lf1 corrected_config doesn't reference the route: '{config[:100]}...'"
    )


def test_lf2_fault_description(assessment):
    """lf2 fault must identify the TCP-MD5 authentication mismatch."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "lf2"]
    assert len(faults) == 1, f"Expected 1 fault for lf2, got {len(faults)}"
    desc = faults[0].get("description", "")
    assert _kw_match(desc, EXPECTED_FAULTS["lf2"]["desc_keywords"]), (
        f"lf2 description doesn't mention password/MD5/auth: '{desc[:100]}...'"
    )


def test_lf2_corrected_config(assessment):
    """lf2 corrected config must address the password mismatch."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "lf2"]
    config = faults[0].get("corrected_config") or ""
    assert _kw_match(config, EXPECTED_FAULTS["lf2"]["fix_keywords"]), (
        f"lf2 corrected_config doesn't reference password: '{config[:100]}...'"
    )


def test_sp1_fault_description(assessment):
    """sp1 fault must identify the nftables BGP port block."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "sp1"]
    assert len(faults) == 1, f"Expected 1 fault for sp1, got {len(faults)}"
    desc = faults[0].get("description", "")
    assert _kw_match(desc, EXPECTED_FAULTS["sp1"]["desc_keywords"]), (
        f"sp1 description doesn't mention nftables/firewall/179: '{desc[:100]}...'"
    )


def test_sp1_corrected_config(assessment):
    """sp1 corrected config must address the nftables rule removal."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "sp1"]
    config = faults[0].get("corrected_config") or ""
    assert _kw_match(config, EXPECTED_FAULTS["sp1"]["fix_keywords"]), (
        f"sp1 corrected_config doesn't reference nftables removal: '{config[:100]}...'"
    )


def test_lf3_fault_description(assessment):
    """lf3 fault must identify the missing network advertisement."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "lf3"]
    assert len(faults) == 1, f"Expected 1 fault for lf3, got {len(faults)}"
    desc = faults[0].get("description", "")
    assert _kw_match(desc, EXPECTED_FAULTS["lf3"]["desc_keywords"]), (
        f"lf3 fault description doesn't mention missing network/10.0.3: '{desc[:100]}...'"
    )


def test_lf3_corrected_config(assessment):
    """lf3 corrected config must include the network statement."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "lf3"]
    config = faults[0].get("corrected_config") or ""
    assert _kw_match(config, EXPECTED_FAULTS["lf3"]["fix_keywords"]), (
        f"lf3 corrected_config missing 'network 10.0.3': '{config[:100]}...'"
    )


def test_h3_fault_description(assessment):
    """h3 fault must identify the incorrect subnet mask."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "h3"]
    assert len(faults) == 1, f"Expected 1 fault for h3, got {len(faults)}"
    desc = faults[0].get("description", "")
    assert _kw_match(desc, EXPECTED_FAULTS["h3"]["desc_keywords"]), (
        f"h3 description doesn't mention mask/netmask issue: '{desc[:100]}...'"
    )


def test_h3_corrected_config(assessment):
    """h3 corrected config must specify /24 mask."""
    faults = [a for a in assessment["anomalies"]
              if a["classification"] == "fault" and a["device"] == "h3"]
    config = faults[0].get("corrected_config") or ""
    assert _kw_match(config, EXPECTED_FAULTS["h3"]["fix_keywords"]), (
        f"h3 corrected_config doesn't reference /24 or correct mask: '{config[:100]}...'"
    )


def test_planned_changes_have_ops_reference(assessment):
    """Each planned_change must have a non-empty ops_reference."""
    planned = [a for a in assessment["anomalies"]
               if a["classification"] == "planned_change"]
    for p in planned:
        ref = p.get("ops_reference") or ""
        assert len(ref) >= 3, (
            f"Planned change on {p['device']} has empty/missing ops_reference"
        )


def test_planned_ss0_description(assessment):
    """ss0 planned change must reference BGP timer modification."""
    planned = [a for a in assessment["anomalies"]
               if a["classification"] == "planned_change" and a["device"] == "ss0"]
    assert len(planned) == 1, f"Expected 1 planned change for ss0, got {len(planned)}"
    desc = planned[0].get("description", "")
    assert _kw_match(desc, EXPECTED_PLANNED["ss0"]["keywords"]), (
        f"ss0 planned change doesn't mention timers: '{desc[:100]}...'"
    )


def test_planned_sp0_description(assessment):
    """sp0 planned change must reference ICMP rate limiting."""
    planned = [a for a in assessment["anomalies"]
               if a["classification"] == "planned_change" and a["device"] == "sp0"]
    assert len(planned) == 1, f"Expected 1 planned change for sp0, got {len(planned)}"
    desc = planned[0].get("description", "")
    assert _kw_match(desc, EXPECTED_PLANNED["sp0"]["keywords"]), (
        f"sp0 planned change doesn't mention ICMP rate limiting: '{desc[:100]}...'"
    )


def test_planned_lf3_description(assessment):
    """lf3 planned change must reference tc/tbf bandwidth enforcement."""
    planned = [a for a in assessment["anomalies"]
               if a["classification"] == "planned_change" and a["device"] == "lf3"]
    assert len(planned) == 1, f"Expected 1 planned change for lf3, got {len(planned)}"
    desc = planned[0].get("description", "")
    assert _kw_match(desc, EXPECTED_PLANNED["lf3"]["keywords"]), (
        f"lf3 planned change doesn't mention tc/tbf/bandwidth: '{desc[:100]}...'"
    )


def test_remediation_order_contains_all_faults(assessment):
    """remediation_order must contain all 6 faulty devices."""
    order = assessment["remediation_order"]
    expected = set(EXPECTED_FAULTS.keys())
    order_set = set(order)
    missing = expected - order_set
    assert not missing, (
        f"remediation_order missing devices: {missing}. Order: {order}"
    )


def test_remediation_order_no_extras(assessment):
    """remediation_order must not contain non-fault devices."""
    order = assessment["remediation_order"]
    expected = set(EXPECTED_FAULTS.keys())
    extra = set(order) - expected
    assert not extra, (
        f"remediation_order contains non-fault devices: {extra}"
    )


def test_remediation_order_sp1_before_lf3(assessment):
    """sp1 must be remediated before lf3 (sp1's ACL fix enables lf3's redundant uplink)."""
    order = assessment["remediation_order"]
    assert "sp1" in order and "lf3" in order, (
        f"Both sp1 and lf3 must be in remediation_order: {order}"
    )
    assert order.index("sp1") < order.index("lf3"), (
        f"sp1 must come before lf3 in remediation_order (sp1 ACL blocks lf3's sp1 session). "
        f"Got: {order}"
    )


def test_descriptions_non_empty(assessment):
    """Each anomaly description must be non-empty and substantive."""
    for i, a in enumerate(assessment["anomalies"]):
        desc = a.get("description", "")
        assert len(desc) >= 20, (
            f"Anomaly {i} ({a.get('device')}) description too short: '{desc}'"
        )


# ========== Packet Forensics Tests ==========

def test_packet_forensics_exists(assessment):
    """Assessment must include a packet_forensics section."""
    assert "packet_forensics" in assessment, (
        "Missing 'packet_forensics' section — PCAP analysis with tshark is required"
    )
    assert isinstance(assessment["packet_forensics"], dict), (
        "'packet_forensics' must be a JSON object"
    )


def test_pf_lf0_bgp_open_as(assessment):
    """packet_forensics must report the correct BGP OPEN AS from lf0_eth0.pcap."""
    pf = assessment.get("packet_forensics", {})
    assert "lf0_bgp_open_as" in pf, (
        "Missing lf0_bgp_open_as in packet_forensics"
    )
    assert pf["lf0_bgp_open_as"] == 65199, (
        f"lf0_bgp_open_as should be 65199, got {pf['lf0_bgp_open_as']}"
    )


def test_pf_lf0_notification_codes(assessment):
    """packet_forensics must report correct BGP NOTIFICATION codes."""
    pf = assessment.get("packet_forensics", {})
    assert pf.get("lf0_bgp_notification_code") == 2, (
        f"lf0_bgp_notification_code should be 2, got {pf.get('lf0_bgp_notification_code')}"
    )
    assert pf.get("lf0_bgp_notification_subcode") == 2, (
        f"lf0_bgp_notification_subcode should be 2, got {pf.get('lf0_bgp_notification_subcode')}"
    )


def test_pf_lf2_tcp_md5_detected(assessment):
    """packet_forensics must detect TCP MD5 option in lf2_eth0.pcap."""
    pf = assessment.get("packet_forensics", {})
    assert pf.get("lf2_tcp_md5_present") is True, (
        f"lf2_tcp_md5_present should be true, got {pf.get('lf2_tcp_md5_present')}"
    )


def test_pf_lf2_syn_analysis(assessment):
    """packet_forensics must show SYN-only traffic (no SYN-ACK) for lf2."""
    pf = assessment.get("packet_forensics", {})
    syn_count = pf.get("lf2_tcp_syn_count", 0)
    synack_count = pf.get("lf2_tcp_synack_count", -1)
    assert syn_count >= 2, (
        f"lf2_tcp_syn_count should be >= 2, got {syn_count}"
    )
    assert synack_count == 0, (
        f"lf2_tcp_synack_count should be 0 (no response), got {synack_count}"
    )


def test_pf_sp1_syn_analysis(assessment):
    """packet_forensics must show SYN-only traffic (no SYN-ACK) for sp1_eth4."""
    pf = assessment.get("packet_forensics", {})
    syn_count = pf.get("sp1_eth4_syn_count", 0)
    synack_count = pf.get("sp1_eth4_synack_count", -1)
    assert syn_count >= 2, (
        f"sp1_eth4_syn_count should be >= 2, got {syn_count}"
    )
    assert synack_count == 0, (
        f"sp1_eth4_synack_count should be 0, got {synack_count}"
    )


def test_pf_h3_arp_targets(assessment):
    """packet_forensics must identify ARP targets outside h3's correct /24 subnet."""
    pf = assessment.get("packet_forensics", {})
    targets = pf.get("h3_arp_targets_outside_24", [])
    assert isinstance(targets, list), (
        f"h3_arp_targets_outside_24 must be a list, got {type(targets)}"
    )
    assert len(targets) >= 2, (
        f"Expected at least 2 ARP targets outside /24, got {len(targets)}: {targets}"
    )
    # All targets must be outside 10.0.3.0/24
    for t in targets:
        parts = t.split('.')
        assert len(parts) == 4, f"Invalid IP format: {t}"
        assert not (parts[0] == '10' and parts[1] == '0' and parts[2] == '3'), (
            f"ARP target {t} is within 10.0.3.0/24 — should only list targets OUTSIDE /24"
        )
