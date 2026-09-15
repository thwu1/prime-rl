"""
Tests for Enterprise Network Risk Assessment and Remediation Design.
Validates audit report, remediation patches, migration plan, and topology diagram.

"""
import json
import os
import re
import pytest

REPORT_PATH = "/app/audit_report.json"
MIGRATION_PLAN_PATH = "/app/migration_plan.json"
TOPOLOGY_SVG_PATH = "/app/topology.svg"
TOPOLOGY_DOT_PATH = "/app/topology.dot"
PATCHES_DIR = "/app/remediation_patches"


def load_report():
    """Load the audit report JSON."""
    assert os.path.exists(REPORT_PATH), f"Audit report not found at {REPORT_PATH}"
    with open(REPORT_PATH, "r") as f:
        report = json.load(f)
    assert "defects" in report, "Report must contain a 'defects' array"
    assert isinstance(report["defects"], list), "'defects' must be a list"
    return report


def defect_text(defect):
    """Concatenate all text fields of a defect entry for flexible matching."""
    parts = []
    for key in [
        "description",
        "affected_config",
        "remediation",
        "category",
        "severity",
        "router",
    ]:
        val = defect.get(key, "")
        if val:
            parts.append(str(val))
    return " ".join(parts).lower()


def find_defect(defects, router, pattern_groups):
    """
    Find a defect for a given router matching ALL pattern groups.
    Each pattern group is a list of regex alternatives (OR within group).
    All groups must match (AND across groups).
    """
    for defect in defects:
        if defect.get("router", "").upper() != router.upper():
            continue
        text = defect_text(defect)
        all_match = True
        for group in pattern_groups:
            if not any(re.search(p, text) for p in group):
                all_match = False
                break
        if all_match:
            return defect
    return None


class TestAuditReportStructure:
    """Verify the audit report has correct structure."""

    def test_report_exists_and_valid(self):
        report = load_report()
        defects = report["defects"]
        assert len(defects) >= 10, (
            f"Expected at least 10 defects, found {len(defects)}"
        )

    def test_defect_fields(self):
        report = load_report()
        required_keys = {
            "router",
            "category",
            "severity",
            "description",
            "affected_config",
            "remediation",
            "risk_score",
            "migration_phase",
        }
        for i, defect in enumerate(report["defects"]):
            missing = required_keys - set(defect.keys())
            assert not missing, (
                f"Defect {i} missing fields: {missing}"
            )

    def test_risk_scores_valid(self):
        report = load_report()
        for i, defect in enumerate(report["defects"]):
            rs = defect.get("risk_score")
            assert isinstance(rs, int), (
                f"Defect {i} risk_score must be integer, got {type(rs).__name__}"
            )
            assert 1 <= rs <= 10, (
                f"Defect {i} risk_score {rs} not in range 1-10"
            )

    def test_migration_phases_valid(self):
        report = load_report()
        for i, defect in enumerate(report["defects"]):
            mp = defect.get("migration_phase")
            assert isinstance(mp, int), (
                f"Defect {i} migration_phase must be integer, got {type(mp).__name__}"
            )
            assert mp >= 1, (
                f"Defect {i} migration_phase {mp} must be >= 1"
            )

    def test_categories_valid(self):
        report = load_report()
        valid_cats = {"security", "routing", "operational"}
        for i, defect in enumerate(report["defects"]):
            cat = defect.get("category", "")
            assert cat in valid_cats, (
                f"Defect {i} category '{cat}' not in {valid_cats}"
            )

    def test_severities_valid(self):
        report = load_report()
        valid_sevs = {"critical", "high", "medium"}
        for i, defect in enumerate(report["defects"]):
            sev = defect.get("severity", "")
            assert sev in valid_sevs, (
                f"Defect {i} severity '{sev}' not in {valid_sevs}"
            )


class TestPlantedDefects:
    """Verify each of the 10 planted defects is correctly identified."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report()
        self.defects = self.report["defects"]

    def test_r1_ospf_area1_plaintext_auth(self):
        """Defect 1: R1 OSPF Area 1 uses plaintext auth instead of MD5."""
        d = find_defect(
            self.defects,
            "R1",
            [
                [r"auth", r"md5", r"message.digest", r"plaintext"],
                [r"area.1", r"area 1", r"ospf"],
            ],
        )
        assert d is not None, (
            "Missing defect: R1 OSPF Area 1 uses plaintext authentication "
            "instead of message-digest (MD5)"
        )

    def test_r2_undefined_prefix_list(self):
        """Defect 2: R2 route-map references undefined prefix-list ALLOWED_OUT."""
        d = find_defect(
            self.defects,
            "R2",
            [
                [r"prefix.list", r"allowed.out", r"export.policy"],
                [
                    r"miss",
                    r"undef",
                    r"not.def",
                    r"dangl",
                    r"not.exist",
                    r"nonexist",
                    r"absent",
                    r"no.*defin",
                    r"not.*found",
                    r"does.not",
                    r"implicit.*deny",
                    r"never.*match",
                    r"block",
                    r"no.*match",
                    r"not.*config",
                    r"not.*creat",
                    r"unreferenc",
                    r"without.*defin",
                    r"deny.*all",
                    r"no.*permit",
                    r"empty",
                    r"lack",
                ],
            ],
        )
        assert d is not None, (
            "Missing defect: R2 route-map EXPORT_POLICY references "
            "prefix-list ALLOWED_OUT which is not defined"
        )

    def test_r2_redistribution_loop_prevention(self):
        """Defect 3: R2 mutual redistribution without route tag loop prevention."""
        d = find_defect(
            self.defects,
            "R2",
            [
                [r"redistrib", r"mutual", r"bgp.*ospf", r"ospf.*bgp"],
                [r"tag", r"loop", r"prevent"],
            ],
        )
        assert d is not None, (
            "Missing defect: R2 mutual redistribution between OSPF and BGP "
            "without route tag-based loop prevention"
        )

    def test_r5_ospf_cost_mismatch(self):
        """Defect 4: R5 OSPF cost on GigabitEthernet2 is 500 instead of 10."""
        d = find_defect(
            self.defects,
            "R5",
            [
                [r"cost", r"metric"],
                [r"500", r"gigabitethernet\s*2", r"gi.*2"],
            ],
        )
        assert d is not None, (
            "Missing defect: R5 OSPF cost on GigabitEthernet2 is 500 "
            "instead of design-specified 10"
        )

    def test_r6_vty_acl_too_broad(self):
        """Defect 5: R6 VTY ACL permits entire 10.0.0.0/8 instead of mgmt /24."""
        d = find_defect(
            self.defects,
            "R6",
            [
                [
                    r"vty",
                    r"acl",
                    r"access.list",
                    r"access.class",
                    r"management",
                    r"vty_access",
                ],
                [
                    r"0\.255\.255\.255",
                    r"10\.0\.0\.0",
                    r"permissive",
                    r"broad",
                    r"over",
                    r"/8",
                    r"10\.1\.1",
                    r"0\.0\.0\.255",
                    r"restrict",
                    r"scope",
                    r"wide",
                ],
            ],
        )
        assert d is not None, (
            "Missing defect: R6 VTY ACL permits 10.0.0.0/8 instead of "
            "management subnet 10.1.1.0/24"
        )

    def test_r6_ntp_trusted_key_missing(self):
        """Defect 6: R6 NTP authentication-key set but trusted-key missing."""
        d = find_defect(
            self.defects,
            "R6",
            [
                [r"ntp"],
                [r"trusted", r"trusted.key"],
            ],
        )
        assert d is not None, (
            "Missing defect: R6 NTP authentication-key configured but "
            "ntp trusted-key command is missing"
        )

    def test_r3_copp_wrong_direction(self):
        """Defect 7: R3 CoPP service-policy applied as output instead of input."""
        d = find_defect(
            self.defects,
            "R3",
            [
                [r"copp", r"control.plane", r"service.policy", r"cop"],
                [r"output", r"direction", r"input"],
            ],
        )
        assert d is not None, (
            "Missing defect: R3 CoPP service-policy direction is 'output' "
            "instead of required 'input'"
        )

    def test_r1_bfd_disabled_on_gi1(self):
        """Defect 8: R1 BFD explicitly disabled on GigabitEthernet1."""
        d = find_defect(
            self.defects,
            "R1",
            [
                [r"bfd"],
                [
                    r"disab",
                    r"no.bfd",
                    r"gigabitethernet\s*1",
                    r"gi.*1",
                    r"missing",
                    r"not.*config",
                    r"not.*enabl",
                    r"absent",
                    r"remov",
                ],
            ],
        )
        assert d is not None, (
            "Missing defect: R1 BFD explicitly disabled on GigabitEthernet1 "
            "via 'no bfd interval'"
        )

    def test_r4_passive_interface_swapped(self):
        """Defect 9: R4 passive-interface on wrong interface (uplink passive, LAN active)."""
        d = find_defect(
            self.defects,
            "R4",
            [
                [r"passive", r"adjacen"],
                [
                    r"gigabitethernet",
                    r"wrong",
                    r"uplink",
                    r"swap",
                    r"invert",
                    r"incorrect",
                    r"should",
                    r"host",
                    r"misconfig",
                ],
            ],
        )
        assert d is not None, (
            "Missing defect: R4 passive-interface default with "
            "no passive-interface on GigabitEthernet2 (host-facing) instead of "
            "GigabitEthernet1 (uplink)"
        )

    def test_r5_network_statement_conflict(self):
        """Defect 10: R5 OSPF network statement includes external network as intra-area."""
        d = find_defect(
            self.defects,
            "R5",
            [
                [r"network", r"172\.16", r"statement"],
                [
                    r"intra",
                    r"extern",
                    r"nssa",
                    r"type.7",
                    r"redistrib",
                    r"conflict",
                    r"override",
                    r"precedence",
                    r"should.*not",
                    r"incorrectly",
                    r"overlap",
                ],
            ],
        )
        assert d is not None, (
            "Missing defect: R5 OSPF network statement "
            "'network 172.16.0.0 0.0.255.255 area 2' includes external network "
            "as intra-area instead of NSSA Type-7 external via redistribution"
        )


class TestRemediationPatches:
    """Verify remediation patches are generated correctly."""

    def test_patches_directory_exists(self):
        assert os.path.isdir(PATCHES_DIR), (
            f"Remediation patches directory not found at {PATCHES_DIR}"
        )

    def test_at_least_four_patches(self):
        patch_files = [
            f for f in os.listdir(PATCHES_DIR)
            if f.endswith(".patch")
        ]
        assert len(patch_files) >= 4, (
            f"Expected at least 4 patch files, found {len(patch_files)}: {patch_files}"
        )

    def test_patches_are_unified_diff(self):
        patch_files = [
            f for f in os.listdir(PATCHES_DIR)
            if f.endswith(".patch")
        ]
        for pf in patch_files:
            path = os.path.join(PATCHES_DIR, pf)
            with open(path, "r") as f:
                content = f.read()
            assert "---" in content and "+++" in content, (
                f"Patch {pf} does not appear to be unified diff format "
                f"(missing --- or +++ markers)"
            )

    def test_affected_routers_have_patches(self):
        """At least R1, R2, R4, R5 should have patches (multiple defects each)."""
        patch_files = set(os.listdir(PATCHES_DIR))
        for router in ["R1", "R2", "R4", "R5"]:
            assert f"{router}.patch" in patch_files, (
                f"Expected patch file {router}.patch in {PATCHES_DIR}"
            )

    def test_r3_patch_references_input(self):
        """R3 patch should contain the CoPP direction fix."""
        path = os.path.join(PATCHES_DIR, "R3.patch")
        if not os.path.exists(path):
            pytest.skip("R3.patch not found")
        with open(path, "r") as f:
            content = f.read().lower()
        assert "input" in content, (
            "R3.patch should reference 'input' for CoPP direction fix"
        )


class TestMigrationPlan:
    """Verify the migration plan is correctly structured."""

    def test_plan_exists(self):
        assert os.path.exists(MIGRATION_PLAN_PATH), (
            f"Migration plan not found at {MIGRATION_PLAN_PATH}"
        )

    def test_plan_is_valid_json_array(self):
        with open(MIGRATION_PLAN_PATH, "r") as f:
            plan = json.load(f)
        assert isinstance(plan, list), "Migration plan must be a JSON array"
        assert len(plan) >= 2, (
            f"Expected at least 2 migration phases, found {len(plan)}"
        )

    def test_plan_fields(self):
        with open(MIGRATION_PLAN_PATH, "r") as f:
            plan = json.load(f)
        required = {"phase", "routers", "changes_summary", "dependency_reason", "rollback_risk"}
        for i, phase_obj in enumerate(plan):
            missing = required - set(phase_obj.keys())
            assert not missing, (
                f"Phase {i} missing fields: {missing}"
            )
            assert isinstance(phase_obj["phase"], int), (
                f"Phase {i} 'phase' must be integer"
            )
            assert isinstance(phase_obj["routers"], list), (
                f"Phase {i} 'routers' must be list"
            )
            assert phase_obj["rollback_risk"] in ("low", "medium", "high"), (
                f"Phase {i} rollback_risk must be low/medium/high"
            )

    def test_phases_sequential(self):
        with open(MIGRATION_PLAN_PATH, "r") as f:
            plan = json.load(f)
        phases = [p["phase"] for p in plan]
        assert phases == sorted(phases), (
            f"Phases must be in ascending order, got {phases}"
        )

    def test_dependency_reasons_non_empty(self):
        with open(MIGRATION_PLAN_PATH, "r") as f:
            plan = json.load(f)
        for i, phase_obj in enumerate(plan):
            reason = phase_obj.get("dependency_reason", "")
            assert len(reason) > 10, (
                f"Phase {i} dependency_reason too short: '{reason}'"
            )


class TestTopologyDiagram:
    """Verify the topology diagram is generated correctly."""

    def test_dot_file_exists(self):
        assert os.path.exists(TOPOLOGY_DOT_PATH), (
            f"Topology DOT file not found at {TOPOLOGY_DOT_PATH}"
        )

    def test_svg_file_exists(self):
        assert os.path.exists(TOPOLOGY_SVG_PATH), (
            f"Topology SVG file not found at {TOPOLOGY_SVG_PATH}"
        )

    def test_dot_contains_graph(self):
        with open(TOPOLOGY_DOT_PATH, "r") as f:
            content = f.read()
        assert re.search(r"(di)?graph\s", content, re.IGNORECASE), (
            "DOT file does not contain a graph definition"
        )
        for router in ["R1", "R2", "R3", "R4", "R5", "R6"]:
            assert router in content, (
                f"DOT file does not reference router {router}"
            )

    def test_svg_is_valid(self):
        with open(TOPOLOGY_SVG_PATH, "r") as f:
            content = f.read()
        assert "<svg" in content.lower(), (
            "SVG file does not contain <svg tag"
        )

    def test_dot_annotates_defects(self):
        """DOT file should contain annotations for at least some defects."""
        with open(TOPOLOGY_DOT_PATH, "r") as f:
            content = f.read().lower()
        defect_indicators = 0
        for keyword in ["defect", "issue", "error", "warning", "critical",
                        "high", "auth", "bfd", "copp", "acl", "cost",
                        "passive", "prefix", "ntp", "tag", "loop"]:
            if keyword in content:
                defect_indicators += 1
        assert defect_indicators >= 3, (
            "DOT file should annotate discovered defects on nodes/edges "
            f"(found only {defect_indicators} defect-related keywords)"
        )
