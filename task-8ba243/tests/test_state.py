
import json
import os
import re

import pytest
from jsonschema import validate, ValidationError


# ============================================================
# Helpers
# ============================================================

def _read_fixed(name):
    path = f"/app/configs_fixed/{name}"
    assert os.path.isfile(path), f"Fixed config not found: {path}"
    with open(path) as f:
        return f.read()


def _load_drift_report():
    with open("/app/drift_report.json") as f:
        return json.load(f)


def _load_schema():
    with open("/app/schema/drift_report.schema.json") as f:
        return json.load(f)


def _get_interfaces_with_channel_group(content, cg_id):
    """Return set of interface names that have the given channel-group."""
    members = []
    current_intf = None
    for line in content.split("\n"):
        m = re.match(r"^interface\s+(\S+)", line)
        if m:
            current_intf = m.group(1)
        elif line.strip() == "!" or (line and not line[0].isspace()):
            current_intf = None
        elif current_intf and f"channel-group {cg_id}" in line:
            members.append(current_intf)
    return set(members)


def _get_interface_section(content, intf_name):
    """Extract lines belonging to a specific interface section."""
    lines = content.split("\n")
    in_section = False
    section = []
    for line in lines:
        if re.match(rf"^interface\s+{re.escape(intf_name)}\s*$", line):
            in_section = True
            continue
        if in_section:
            if line.strip() == "!" or re.match(r"^[a-zA-Z]", line):
                break
            section.append(line.strip())
    return "\n".join(section)


# ============================================================
# Schema Validation Tests
# ============================================================

class TestSchemaValidation:
    def test_drift_report_validates_against_schema(self):
        report = _load_drift_report()
        schema = _load_schema()
        try:
            validate(instance=report, schema=schema)
        except ValidationError as e:
            pytest.fail(f"drift_report.json does not validate against schema: {e.message}")

    def test_all_findings_have_valid_device(self):
        report = _load_drift_report()
        valid_devices = {
            "dc1-spine1", "dc1-spine2",
            "dc1-leaf1a", "dc1-leaf1b",
            "dc1-leaf2a", "dc1-leaf2b",
        }
        for f in report:
            assert f["device"] in valid_devices, f"Invalid device: {f['device']}"

    def test_all_findings_have_valid_section(self):
        report = _load_drift_report()
        valid_sections = {"bgp", "interface", "vxlan", "mlag", "vrf"}
        for f in report:
            assert f["section"] in valid_sections, f"Invalid section: {f['section']}"


# ============================================================
# Drift Report Tests
# ============================================================

class TestDriftReport:
    def test_drift_report_exists(self):
        assert os.path.isfile("/app/drift_report.json")

    def test_drift_report_valid_json_list(self):
        data = _load_drift_report()
        assert isinstance(data, list), "drift_report.json should be a JSON array"

    def test_drift_report_has_10_findings(self):
        findings = _load_drift_report()
        assert len(findings) == 10, (
            f"Expected exactly 10 drift findings, got {len(findings)}"
        )

    def test_drift_report_covers_all_devices(self):
        findings = _load_drift_report()
        devices = {f["device"] for f in findings}
        expected_devices = {
            "dc1-spine1", "dc1-spine2",
            "dc1-leaf1a", "dc1-leaf1b",
            "dc1-leaf2a", "dc1-leaf2b",
        }
        assert devices == expected_devices, (
            f"Findings should cover all 6 devices. Got: {devices}"
        )


# ============================================================
# Unified Diff Tests
# ============================================================

class TestDiffs:
    def test_diffs_directory_exists(self):
        assert os.path.isdir("/app/diffs"), "diffs/ directory not found"

    @pytest.mark.parametrize("name", [
        "dc1-spine1.diff", "dc1-spine2.diff",
        "dc1-leaf1a.diff", "dc1-leaf1b.diff",
        "dc1-leaf2a.diff", "dc1-leaf2b.diff",
    ])
    def test_diff_file_exists(self, name):
        path = f"/app/diffs/{name}"
        assert os.path.isfile(path), f"Diff file not found: {path}"

    @pytest.mark.parametrize("name", [
        "dc1-spine1.diff", "dc1-spine2.diff",
        "dc1-leaf1a.diff", "dc1-leaf1b.diff",
        "dc1-leaf2a.diff", "dc1-leaf2b.diff",
    ])
    def test_diff_is_nonempty(self, name):
        path = f"/app/diffs/{name}"
        assert os.path.getsize(path) > 0, f"Diff file is empty: {path}"

    @pytest.mark.parametrize("name", [
        "dc1-spine1.diff", "dc1-spine2.diff",
        "dc1-leaf1a.diff", "dc1-leaf1b.diff",
        "dc1-leaf2a.diff", "dc1-leaf2b.diff",
    ])
    def test_diff_is_unified_format(self, name):
        path = f"/app/diffs/{name}"
        with open(path) as f:
            content = f.read()
        assert "---" in content, f"Diff {name} missing unified diff '---' header"
        assert "+++" in content, f"Diff {name} missing unified diff '+++' header"
        assert "@@" in content, f"Diff {name} missing unified diff '@@' hunk header"


# ============================================================
# Fixed Configs — Existence
# ============================================================

class TestFixedConfigsExist:
    def test_configs_fixed_directory(self):
        assert os.path.isdir("/app/configs_fixed")

    @pytest.mark.parametrize("name", [
        "dc1-spine1.cfg", "dc1-spine2.cfg",
        "dc1-leaf1a.cfg", "dc1-leaf1b.cfg",
        "dc1-leaf2a.cfg", "dc1-leaf2b.cfg",
    ])
    def test_fixed_config_present(self, name):
        assert os.path.isfile(f"/app/configs_fixed/{name}"), f"Missing {name}"


# ============================================================
# Fixed Configs — Error 1: dc1-spine1 BGP overlay remote-as
# ============================================================

class TestFixSpine1BgpRemoteAs:
    """Overlay neighbor 10.255.0.3 should have remote-as 65101, not 65102."""

    def test_correct_remote_as(self):
        c = _read_fixed("dc1-spine1.cfg")
        assert "neighbor 10.255.0.3 remote-as 65101" in c

    def test_wrong_remote_as_absent(self):
        c = _read_fixed("dc1-spine1.cfg")
        assert "neighbor 10.255.0.3 remote-as 65102" not in c


# ============================================================
# Fixed Configs — Error 2: dc1-spine1 missing underlay neighbor
# ============================================================

class TestFixSpine1MissingNeighbor:
    """Underlay neighbor 172.31.255.7 (dc1-leaf2b) should exist."""

    def test_neighbor_present(self):
        c = _read_fixed("dc1-spine1.cfg")
        assert "neighbor 172.31.255.7" in c

    def test_neighbor_correct_remote_as(self):
        c = _read_fixed("dc1-spine1.cfg")
        assert "neighbor 172.31.255.7 remote-as 65102" in c


# ============================================================
# Fixed Configs — Error 3: dc1-spine2 Ethernet4 IP
# ============================================================

class TestFixSpine2InterfaceIp:
    """Ethernet4 should have 172.31.255.14/31, not 172.31.255.15/31."""

    def test_correct_ip_in_interface_section(self):
        c = _read_fixed("dc1-spine2.cfg")
        section = _get_interface_section(c, "Ethernet4")
        assert "172.31.255.14/31" in section, (
            f"Ethernet4 section should contain 172.31.255.14/31, got:\n{section}"
        )

    def test_wrong_ip_not_in_interface_section(self):
        c = _read_fixed("dc1-spine2.cfg")
        section = _get_interface_section(c, "Ethernet4")
        assert "172.31.255.15/31" not in section


# ============================================================
# Fixed Configs — Error 4: dc1-leaf1a missing VXLAN VNI
# ============================================================

class TestFixLeaf1aVxlanVlan30:
    """VLAN 30 -> VNI 10030 mapping must be present."""

    def test_vlan30_vni_present(self):
        c = _read_fixed("dc1-leaf1a.cfg")
        assert "vxlan vlan 30 vni 10030" in c


# ============================================================
# Fixed Configs — Error 5: dc1-leaf1b Loopback0 IP
# ============================================================

class TestFixLeaf1bLoopback0:
    """Loopback0 should be 10.255.0.4/32, not 10.255.0.5/32."""

    def test_correct_loopback_ip(self):
        c = _read_fixed("dc1-leaf1b.cfg")
        section = _get_interface_section(c, "Loopback0")
        assert "10.255.0.4/32" in section

    def test_wrong_loopback_ip_absent(self):
        c = _read_fixed("dc1-leaf1b.cfg")
        # 10.255.0.5/32 should not appear as any interface IP
        # (it legitimately appears in dc1-leaf2a, but not in leaf1b)
        assert "ip address 10.255.0.5/32" not in c


# ============================================================
# Fixed Configs — Error 6: dc1-leaf1b MLAG member interfaces
# ============================================================

class TestFixLeaf1bMlagMembers:
    """MLAG channel-group 1000 should use Ethernet3+Ethernet4, not Ethernet3+Ethernet5."""

    def test_correct_members(self):
        c = _read_fixed("dc1-leaf1b.cfg")
        members = _get_interfaces_with_channel_group(c, 1000)
        assert members == {"Ethernet3", "Ethernet4"}, (
            f"Expected {{Ethernet3, Ethernet4}} in channel-group 1000, got {members}"
        )


# ============================================================
# Fixed Configs — Error 7: dc1-leaf2a VLAN 20 VNI
# ============================================================

class TestFixLeaf2aVxlanVlan20:
    """VLAN 20 should map to VNI 10020, not 10021."""

    def test_correct_vni(self):
        c = _read_fixed("dc1-leaf2a.cfg")
        assert "vxlan vlan 20 vni 10020" in c

    def test_wrong_vni_absent(self):
        c = _read_fixed("dc1-leaf2a.cfg")
        assert "vxlan vlan 20 vni 10021" not in c


# ============================================================
# Fixed Configs — Error 8: dc1-leaf2a VXLAN source interface
# ============================================================

class TestFixLeaf2aVxlanSource:
    """VXLAN source should be Loopback1 (VTEP), not Loopback0."""

    def test_correct_source(self):
        c = _read_fixed("dc1-leaf2a.cfg")
        assert "vxlan source-interface Loopback1" in c

    def test_wrong_source_absent(self):
        c = _read_fixed("dc1-leaf2a.cfg")
        assert "vxlan source-interface Loopback0" not in c


# ============================================================
# Fixed Configs — Error 9: dc1-leaf2b MLAG domain-id
# ============================================================

class TestFixLeaf2bMlagDomain:
    """MLAG domain-id should be DC1_LEAF2, not DC1_LEAF1."""

    def test_correct_domain_id(self):
        c = _read_fixed("dc1-leaf2b.cfg")
        assert "domain-id DC1_LEAF2" in c

    def test_wrong_domain_id_absent(self):
        c = _read_fixed("dc1-leaf2b.cfg")
        assert "domain-id DC1_LEAF1" not in c


# ============================================================
# Fixed Configs — Error 10: dc1-leaf2b VRF route-target
# ============================================================

class TestFixLeaf2bVrfRt:
    """VRF Tenant_A route-targets should be 100:100, not 65102:100."""

    def test_correct_import_rt(self):
        c = _read_fixed("dc1-leaf2b.cfg")
        assert "route-target import evpn 100:100" in c

    def test_correct_export_rt(self):
        c = _read_fixed("dc1-leaf2b.cfg")
        assert "route-target export evpn 100:100" in c

    def test_wrong_rt_absent(self):
        c = _read_fixed("dc1-leaf2b.cfg")
        assert "65102:100" not in c
