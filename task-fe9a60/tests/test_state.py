
import json
import os
import re

import pytest

OUTPUT_DIR = "/app/output"


class TestBugsReport:
    """Verify that all configuration bugs are identified."""

    @pytest.fixture(autouse=True)
    def load_bugs(self):
        bugs_path = os.path.join(OUTPUT_DIR, "bugs.json")
        assert os.path.exists(bugs_path), f"bugs.json not found at {bugs_path}"
        with open(bugs_path) as f:
            self.bugs = json.load(f)

    def _bug_matches(self, router_pattern, vrf_pattern=None, text_patterns=None):
        """Check if any bug entry matches the given keyword patterns."""
        for bug in self.bugs:
            bug_str = json.dumps(bug).lower()
            if router_pattern.lower() not in bug_str:
                continue
            if vrf_pattern and vrf_pattern.lower() not in bug_str:
                continue
            if text_patterns:
                if all(p.lower() in bug_str for p in text_patterns):
                    return True
            else:
                return True
        return False

    def test_bugs_is_list(self):
        assert isinstance(self.bugs, list), "bugs.json must be a JSON array"

    def test_bugs_count(self):
        assert len(self.bugs) >= 5, f"Expected at least 5 bugs, found {len(self.bugs)}"

    def test_bugs_have_required_fields(self):
        for i, bug in enumerate(self.bugs):
            assert "router" in bug, f"Bug {i} missing 'router' field"
            assert "bug" in bug, f"Bug {i} missing 'bug' field"
            assert "fix" in bug, f"Bug {i} missing 'fix' field"

    def test_bug_r1_default_bgp_instance(self):
        """R1 is missing the default BGP instance required for VPN route-leak."""
        found = (
            self._bug_matches("r1", text_patterns=["default", "bgp"])
            or self._bug_matches("r1", text_patterns=["default", "instance"])
            or self._bug_matches("r1", text_patterns=["router bgp 65001"])
            or self._bug_matches("r1", text_patterns=["vpn", "rib"])
        )
        assert found, "Bug not found: R1 missing default BGP instance"

    def test_bug_r2_cust_router_id(self):
        """R2 CUST VRF is missing bgp router-id."""
        found = (
            self._bug_matches("r2", "cust", ["router-id"])
            or self._bug_matches("r2", "cust", ["router id"])
        )
        assert found, "Bug not found: R2 CUST missing bgp router-id"

    def test_bug_r2_internal_import_vpn(self):
        """R2 INTERNAL VRF is missing 'import vpn'."""
        found = (
            self._bug_matches("r2", "internal", ["import vpn"])
            or self._bug_matches("r2", "internal", ["import", "missing"])
        )
        assert found, "Bug not found: R2 INTERNAL missing 'import vpn'"

    def test_bug_r3_services_rt_typo(self):
        """R3 SERVICES has RT export typo (65001:3000 vs 65001:300)."""
        found = (
            self._bug_matches("r3", "services", ["3000"])
            or self._bug_matches("r3", "services", ["rt", "export", "typo"])
            or self._bug_matches("r3", "services", ["route target", "export"])
            or self._bug_matches("r3", "services", ["rt", "export", "mismatch"])
            or self._bug_matches("r3", "services", ["rt", "export", "incorrect"])
            or self._bug_matches("r3", "services", ["rt", "export", "wrong"])
        )
        assert found, "Bug not found: R3 SERVICES RT export typo (65001:3000)"

    def test_bug_r3_prod_import_vrf_incompatible(self):
        """R3 PROD uses 'import vrf' which is incompatible with 'export vpn' on SERVICES."""
        found = (
            self._bug_matches("r3", "prod", ["import vrf"])
            or self._bug_matches("r3", "prod", ["incompatible"])
            or self._bug_matches("r3", "prod", ["shortcut"])
        )
        assert found, "Bug not found: R3 PROD 'import vrf' incompatible with 'export vpn'"


class TestReachability:
    """Verify the VRF reachability matrix after all bugs are fixed and new VRFs added."""

    @pytest.fixture(autouse=True)
    def load_reachability(self):
        reach_path = os.path.join(OUTPUT_DIR, "reachability.json")
        assert os.path.exists(reach_path), f"reachability.json not found at {reach_path}"
        with open(reach_path) as f:
            self.reachability = json.load(f)

    def _normalize_key(self, key):
        return key.strip().upper()

    def _get_normalized(self):
        result = {}
        for k, v in self.reachability.items():
            nk = self._normalize_key(k)
            nv = sorted([self._normalize_key(x) for x in v])
            result[nk] = nv
        return result

    def test_all_vrfs_present(self):
        """All 8 VRFs (6 original + QUARANTINE + MONITOR) must be keys."""
        norm = self._get_normalized()
        expected = {
            "R1:CUST", "R1:MGMT", "R1:QUARANTINE",
            "R2:CUST", "R2:INTERNAL", "R2:MONITOR",
            "R3:SERVICES", "R3:PROD",
        }
        actual = set(norm.keys())
        assert expected == actual, f"Expected VRFs {expected}, got {actual}"

    def test_r1_cust_receives_from_mgmt_only(self):
        """R1:CUST imports RT 65001:200 from MGMT. Must NOT include QUARANTINE."""
        norm = self._get_normalized()
        r1_cust = norm.get("R1:CUST", [])
        assert r1_cust == ["R1:MGMT"], (
            f"R1:CUST should only receive from R1:MGMT, got: {r1_cust}"
        )

    def test_r1_mgmt_receives_nothing(self):
        """R1:MGMT imports RT 65001:200 but no other VRF exports it."""
        norm = self._get_normalized()
        r1_mgmt = norm.get("R1:MGMT", [])
        assert len(r1_mgmt) == 0, f"R1:MGMT should receive from nobody, got: {r1_mgmt}"

    def test_r1_quarantine_receives_from_mgmt(self):
        """R1:QUARANTINE must import routes from MGMT (constraint)."""
        norm = self._get_normalized()
        r1_q = norm.get("R1:QUARANTINE", [])
        assert "R1:MGMT" in r1_q, (
            f"R1:QUARANTINE should receive from R1:MGMT, got: {r1_q}"
        )

    def test_r1_quarantine_does_not_receive_from_cust(self):
        """R1:QUARANTINE should not receive customer routes."""
        norm = self._get_normalized()
        r1_q = norm.get("R1:QUARANTINE", [])
        assert "R1:CUST" not in r1_q, (
            f"R1:QUARANTINE should not receive from R1:CUST, got: {r1_q}"
        )

    def test_r1_quarantine_receives_only_from_mgmt(self):
        """R1:QUARANTINE should receive from MGMT only."""
        norm = self._get_normalized()
        r1_q = norm.get("R1:QUARANTINE", [])
        assert r1_q == ["R1:MGMT"], (
            f"R1:QUARANTINE should only receive from R1:MGMT, got: {r1_q}"
        )

    def test_r2_cust_receives_nothing(self):
        """R2:CUST imports RT 65001:100 but no other VRF on R2 exports it."""
        norm = self._get_normalized()
        r2_cust = norm.get("R2:CUST", [])
        assert len(r2_cust) == 0, f"R2:CUST should receive from nobody, got: {r2_cust}"

    def test_r2_internal_receives_from_cust_only(self):
        """R2:INTERNAL imports RT 65001:100 from CUST. Must NOT include MONITOR."""
        norm = self._get_normalized()
        r2_internal = norm.get("R2:INTERNAL", [])
        assert r2_internal == ["R2:CUST"], (
            f"R2:INTERNAL should only receive from R2:CUST, got: {r2_internal}"
        )

    def test_r2_monitor_receives_from_cust_and_internal(self):
        """R2:MONITOR must aggregate routes from both CUST and INTERNAL."""
        norm = self._get_normalized()
        r2_mon = norm.get("R2:MONITOR", [])
        assert "R2:CUST" in r2_mon, (
            f"R2:MONITOR should receive from R2:CUST, got: {r2_mon}"
        )
        assert "R2:INTERNAL" in r2_mon, (
            f"R2:MONITOR should receive from R2:INTERNAL, got: {r2_mon}"
        )

    def test_r2_monitor_receives_only_from_cust_and_internal(self):
        """R2:MONITOR should only receive from CUST and INTERNAL."""
        norm = self._get_normalized()
        r2_mon = norm.get("R2:MONITOR", [])
        assert r2_mon == ["R2:CUST", "R2:INTERNAL"], (
            f"R2:MONITOR should receive from [R2:CUST, R2:INTERNAL], got: {r2_mon}"
        )

    def test_r3_services_receives_nothing(self):
        """R3:SERVICES imports RT 65001:300 but only itself exports it."""
        norm = self._get_normalized()
        r3_services = norm.get("R3:SERVICES", [])
        assert len(r3_services) == 0, (
            f"R3:SERVICES should receive from nobody, got: {r3_services}"
        )

    def test_r3_prod_receives_from_services_only(self):
        """R3:PROD imports RT 65001:300 from SERVICES."""
        norm = self._get_normalized()
        r3_prod = norm.get("R3:PROD", [])
        assert r3_prod == ["R3:SERVICES"], (
            f"R3:PROD should only receive from R3:SERVICES, got: {r3_prod}"
        )


class TestCorrectedConfigs:
    """Verify that corrected configs contain the specific fixes."""

    def _read_config(self, router):
        path = os.path.join(OUTPUT_DIR, "corrected", f"{router}.conf")
        assert os.path.exists(path), f"Corrected config not found: {path}"
        with open(path) as f:
            return f.read()

    def _find_bgp_section(self, config, vrf=None):
        """Extract lines belonging to a specific BGP section."""
        lines = config.split("\n")
        if vrf:
            pattern = re.compile(
                r"^router\s+bgp\s+\d+\s+vrf\s+" + re.escape(vrf) + r"\s*$",
                re.IGNORECASE,
            )
        else:
            pattern = re.compile(r"^router\s+bgp\s+\d+\s*$")

        in_section = False
        section_lines = []
        depth = 0
        for line in lines:
            stripped = line.strip()
            if not in_section and pattern.match(stripped):
                in_section = True
                section_lines.append(line)
                continue
            if in_section:
                section_lines.append(line)
                if stripped == "exit" and depth == 0:
                    break
                if stripped.startswith("address-family"):
                    depth += 1
                if stripped == "exit-address-family":
                    depth -= 1
        return "\n".join(section_lines)

    def _extract_export_rts(self, section):
        """Extract all RT values that would be exported (from export and both)."""
        rts = set()
        for line in section.split("\n"):
            stripped = line.strip()
            m = re.match(r"rt\s+vpn\s+export\s+(.*)", stripped)
            if m:
                rts.update(m.group(1).split())
            m = re.match(r"rt\s+vpn\s+both\s+(.*)", stripped)
            if m:
                rts.update(m.group(1).split())
        return rts

    def _extract_import_rts(self, section):
        """Extract all RT values that would be imported (from import and both)."""
        rts = set()
        for line in section.split("\n"):
            stripped = line.strip()
            m = re.match(r"rt\s+vpn\s+import\s+(.*)", stripped)
            if m:
                rts.update(m.group(1).split())
            m = re.match(r"rt\s+vpn\s+both\s+(.*)", stripped)
            if m:
                rts.update(m.group(1).split())
        return rts

    # --- R1 Original Fixes ---

    def test_r1_has_default_bgp_instance(self):
        """R1 must have a default BGP instance (router bgp 65001 without vrf)."""
        config = self._read_config("r1")
        lines = config.split("\n")
        found = any(
            re.match(r"^router\s+bgp\s+65001\s*$", line.strip()) for line in lines
        )
        assert found, "R1 corrected config must have 'router bgp 65001' (default instance)"

    def test_r1_default_bgp_has_router_id(self):
        """R1 default BGP instance should have a bgp router-id."""
        config = self._read_config("r1")
        section = self._find_bgp_section(config, vrf=None)
        assert section, "Could not find default BGP section in R1"
        assert "router-id" in section.lower(), (
            "R1 default BGP instance should have bgp router-id"
        )

    # --- R2 Original Fixes ---

    def test_r2_cust_has_router_id(self):
        """R2 CUST VRF should have bgp router-id."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="CUST")
        assert section, "Could not find CUST BGP section in R2"
        assert "router-id" in section.lower(), (
            "R2 CUST BGP section should have bgp router-id"
        )

    def test_r2_internal_has_import_vpn(self):
        """R2 INTERNAL VRF should have 'import vpn'."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="INTERNAL")
        assert section, "Could not find INTERNAL BGP section in R2"
        assert "import vpn" in section, (
            "R2 INTERNAL BGP section should have 'import vpn'"
        )

    # --- R3 Original Fixes ---

    def test_r3_services_rt_not_typo(self):
        """R3 SERVICES should NOT have the typo RT 65001:3000."""
        config = self._read_config("r3")
        assert "65001:3000" not in config, (
            "R3 corrected config should not contain RT 65001:3000 (typo)"
        )

    def test_r3_services_rt_correct(self):
        """R3 SERVICES should have 'rt vpn export 65001:300'."""
        config = self._read_config("r3")
        section = self._find_bgp_section(config, vrf="SERVICES")
        assert section, "Could not find SERVICES BGP section in R3"
        assert re.search(r"rt\s+vpn\s+export\s+65001:300\b", section), (
            "R3 SERVICES should have 'rt vpn export 65001:300'"
        )

    def test_r3_prod_no_import_vrf(self):
        """R3 PROD should NOT use 'import vrf' (incompatible with export vpn)."""
        config = self._read_config("r3")
        section = self._find_bgp_section(config, vrf="PROD")
        assert section, "Could not find PROD BGP section in R3"
        assert "import vrf" not in section.lower(), (
            "R3 PROD should not use 'import vrf' (incompatible with 'export vpn' on SERVICES)"
        )

    def test_r3_prod_has_import_vpn(self):
        """R3 PROD should use 'import vpn' instead of 'import vrf'."""
        config = self._read_config("r3")
        section = self._find_bgp_section(config, vrf="PROD")
        assert section, "Could not find PROD BGP section in R3"
        assert "import vpn" in section, (
            "R3 PROD should have 'import vpn'"
        )

    def test_r3_prod_has_rt_import(self):
        """R3 PROD should import RT 65001:300 from SERVICES."""
        config = self._read_config("r3")
        section = self._find_bgp_section(config, vrf="PROD")
        assert section, "Could not find PROD BGP section in R3"
        assert re.search(r"rt\s+vpn\s+import\s+65001:300\b", section), (
            "R3 PROD should have 'rt vpn import 65001:300'"
        )

    def test_r3_prod_has_rd_vpn_export(self):
        """R3 PROD should have 'rd vpn export' for proper VPN operation."""
        config = self._read_config("r3")
        section = self._find_bgp_section(config, vrf="PROD")
        assert section, "Could not find PROD BGP section in R3"
        assert re.search(r"rd\s+vpn\s+export", section), (
            "R3 PROD should have 'rd vpn export'"
        )

    # --- R1 QUARANTINE VRF (newly designed) ---

    def test_r1_has_quarantine_vrf_definition(self):
        """R1 must define the QUARANTINE VRF."""
        config = self._read_config("r1")
        assert re.search(r"^vrf\s+QUARANTINE\s*$", config, re.MULTILINE), (
            "R1 corrected config must have 'vrf QUARANTINE' definition"
        )

    def test_r1_has_quarantine_bgp_section(self):
        """R1 must have a BGP section for QUARANTINE VRF."""
        config = self._read_config("r1")
        section = self._find_bgp_section(config, vrf="QUARANTINE")
        assert section, "R1 must have 'router bgp 65001 vrf QUARANTINE'"

    def test_r1_quarantine_has_export_vpn(self):
        """R1 QUARANTINE must use explicit export vpn."""
        config = self._read_config("r1")
        section = self._find_bgp_section(config, vrf="QUARANTINE")
        assert section, "Could not find QUARANTINE BGP section in R1"
        assert "export vpn" in section, "R1 QUARANTINE must have 'export vpn'"

    def test_r1_quarantine_has_import_vpn(self):
        """R1 QUARANTINE must use explicit import vpn."""
        config = self._read_config("r1")
        section = self._find_bgp_section(config, vrf="QUARANTINE")
        assert section, "Could not find QUARANTINE BGP section in R1"
        assert "import vpn" in section, "R1 QUARANTINE must have 'import vpn'"

    def test_r1_quarantine_no_import_vrf_shortcut(self):
        """R1 QUARANTINE must NOT use the import vrf shortcut."""
        config = self._read_config("r1")
        section = self._find_bgp_section(config, vrf="QUARANTINE")
        assert section, "Could not find QUARANTINE BGP section in R1"
        assert "import vrf" not in section.lower(), (
            "R1 QUARANTINE must use 'import vpn', not 'import vrf'"
        )

    def test_r1_quarantine_imports_mgmt_rt(self):
        """QUARANTINE must import RT 65001:200 (MGMT's export RT) to receive mgmt routes."""
        config = self._read_config("r1")
        section = self._find_bgp_section(config, vrf="QUARANTINE")
        assert section, "Could not find QUARANTINE BGP section in R1"
        import_rts = self._extract_import_rts(section)
        assert "65001:200" in import_rts, (
            f"QUARANTINE must import RT 65001:200 to receive MGMT routes, got: {import_rts}"
        )

    def test_r1_quarantine_export_rt_not_visible_to_cust(self):
        """QUARANTINE export RT must NOT match any RT that CUST imports (65001:100, 65001:200)."""
        config = self._read_config("r1")
        section = self._find_bgp_section(config, vrf="QUARANTINE")
        assert section, "Could not find QUARANTINE BGP section in R1"
        export_rts = self._extract_export_rts(section)
        assert len(export_rts) > 0, "QUARANTINE must have rt vpn export configured"
        forbidden = {"65001:100", "65001:200"}
        overlap = export_rts & forbidden
        assert len(overlap) == 0, (
            f"QUARANTINE export RTs {export_rts} overlap with CUST import RTs {forbidden} "
            f"— QUARANTINE routes would leak into CUST. Overlap: {overlap}"
        )

    def test_r1_quarantine_export_rt_not_leaking_to_mgmt(self):
        """QUARANTINE export RT must NOT match MGMT's import RT (65001:200)."""
        config = self._read_config("r1")
        section = self._find_bgp_section(config, vrf="QUARANTINE")
        assert section, "Could not find QUARANTINE BGP section in R1"
        export_rts = self._extract_export_rts(section)
        assert "65001:200" not in export_rts, (
            "QUARANTINE export RT must not be 65001:200 — would leak routes back to MGMT"
        )

    def test_r1_quarantine_has_rd_vpn_export(self):
        """QUARANTINE must have rd vpn export configured."""
        config = self._read_config("r1")
        section = self._find_bgp_section(config, vrf="QUARANTINE")
        assert section, "Could not find QUARANTINE BGP section in R1"
        assert re.search(r"rd\s+vpn\s+export", section), (
            "R1 QUARANTINE must have 'rd vpn export'"
        )

    # --- R2 MONITOR VRF (newly designed) ---

    def test_r2_has_monitor_vrf_definition(self):
        """R2 must define the MONITOR VRF."""
        config = self._read_config("r2")
        assert re.search(r"^vrf\s+MONITOR\s*$", config, re.MULTILINE), (
            "R2 corrected config must have 'vrf MONITOR' definition"
        )

    def test_r2_has_monitor_bgp_section(self):
        """R2 must have a BGP section for MONITOR VRF."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="MONITOR")
        assert section, "R2 must have 'router bgp 65001 vrf MONITOR'"

    def test_r2_monitor_has_export_vpn(self):
        """R2 MONITOR must use explicit export vpn."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="MONITOR")
        assert section, "Could not find MONITOR BGP section in R2"
        assert "export vpn" in section, "R2 MONITOR must have 'export vpn'"

    def test_r2_monitor_has_import_vpn(self):
        """R2 MONITOR must use explicit import vpn."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="MONITOR")
        assert section, "Could not find MONITOR BGP section in R2"
        assert "import vpn" in section, "R2 MONITOR must have 'import vpn'"

    def test_r2_monitor_no_import_vrf_shortcut(self):
        """R2 MONITOR must NOT use the import vrf shortcut."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="MONITOR")
        assert section, "Could not find MONITOR BGP section in R2"
        assert "import vrf" not in section.lower(), (
            "R2 MONITOR must use 'import vpn', not 'import vrf'"
        )

    def test_r2_monitor_imports_cust_rt(self):
        """MONITOR must import RT 65001:100 (CUST's export RT)."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="MONITOR")
        assert section, "Could not find MONITOR BGP section in R2"
        import_rts = self._extract_import_rts(section)
        assert "65001:100" in import_rts, (
            f"MONITOR must import RT 65001:100 to receive CUST routes, got: {import_rts}"
        )

    def test_r2_monitor_imports_internal_rt(self):
        """MONITOR must import RT 65001:250 (INTERNAL's export RT)."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="MONITOR")
        assert section, "Could not find MONITOR BGP section in R2"
        import_rts = self._extract_import_rts(section)
        assert "65001:250" in import_rts, (
            f"MONITOR must import RT 65001:250 to receive INTERNAL routes, got: {import_rts}"
        )

    def test_r2_monitor_export_rt_not_leaking_to_cust(self):
        """MONITOR export RT must NOT match CUST's import RT (65001:100)."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="MONITOR")
        assert section, "Could not find MONITOR BGP section in R2"
        export_rts = self._extract_export_rts(section)
        assert len(export_rts) > 0, "MONITOR must have rt vpn export configured"
        assert "65001:100" not in export_rts, (
            "MONITOR export RT must not be 65001:100 — would leak routes into CUST"
        )

    def test_r2_monitor_export_rt_not_leaking_to_internal(self):
        """MONITOR export RT must NOT match INTERNAL's import RT (65001:100)."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="MONITOR")
        assert section, "Could not find MONITOR BGP section in R2"
        export_rts = self._extract_export_rts(section)
        # INTERNAL imports 65001:100 — already checked above that MONITOR doesn't export it
        # Also verify MONITOR doesn't export 65001:250 (would be imported by no one currently
        # but is INTERNAL's own export RT and should stay separate)
        forbidden = {"65001:100", "65001:250"}
        overlap = export_rts & forbidden
        assert len(overlap) == 0, (
            f"MONITOR export RTs {export_rts} must not overlap with {forbidden} "
            f"to prevent route injection into CUST/INTERNAL. Overlap: {overlap}"
        )

    def test_r2_monitor_has_rd_vpn_export(self):
        """MONITOR must have rd vpn export configured."""
        config = self._read_config("r2")
        section = self._find_bgp_section(config, vrf="MONITOR")
        assert section, "Could not find MONITOR BGP section in R2"
        assert re.search(r"rd\s+vpn\s+export", section), (
            "R2 MONITOR must have 'rd vpn export'"
        )


class TestDesignEvaluation:
    """Verify the design evaluation document with RT scheme justification and security assessment."""

    @pytest.fixture(autouse=True)
    def load_design(self):
        path = os.path.join(OUTPUT_DIR, "design_evaluation.json")
        assert os.path.exists(path), (
            "design_evaluation.json not found at /app/output/"
        )
        with open(path) as f:
            self.design = json.load(f)

    def test_has_quarantine_design(self):
        assert "quarantine_design" in self.design, (
            "design_evaluation.json must have 'quarantine_design' key"
        )

    def test_has_monitor_design(self):
        assert "monitor_design" in self.design, (
            "design_evaluation.json must have 'monitor_design' key"
        )

    def test_has_security_assessment(self):
        assert "security_assessment" in self.design, (
            "design_evaluation.json must have 'security_assessment' key"
        )

    def test_quarantine_design_has_required_fields(self):
        qd = self.design["quarantine_design"]
        for field in ["rd", "rt_export", "rt_import", "justification", "isolation_properties"]:
            assert field in qd, f"quarantine_design missing '{field}'"

    def test_monitor_design_has_required_fields(self):
        md = self.design["monitor_design"]
        for field in ["rd", "rt_export", "rt_import", "justification", "isolation_properties"]:
            assert field in md, f"monitor_design missing '{field}'"

    def test_quarantine_rt_import_includes_mgmt(self):
        """QUARANTINE must import 65001:200 to receive MGMT routes."""
        rt_import = self.design["quarantine_design"]["rt_import"]
        assert "65001:200" in rt_import, (
            f"QUARANTINE rt_import must include 65001:200, got: {rt_import}"
        )

    def test_quarantine_rt_export_safe(self):
        """QUARANTINE rt_export must not include 65001:100 or 65001:200."""
        rt_export = self.design["quarantine_design"]["rt_export"]
        forbidden = {"65001:100", "65001:200"}
        for rt in rt_export:
            assert rt not in forbidden, (
                f"QUARANTINE rt_export {rt} would leak into CUST or MGMT"
            )

    def test_monitor_rt_import_includes_cust_and_internal(self):
        """MONITOR must import 65001:100 and 65001:250."""
        rt_import = self.design["monitor_design"]["rt_import"]
        assert "65001:100" in rt_import, (
            f"MONITOR rt_import must include 65001:100, got: {rt_import}"
        )
        assert "65001:250" in rt_import, (
            f"MONITOR rt_import must include 65001:250, got: {rt_import}"
        )

    def test_monitor_rt_export_safe(self):
        """MONITOR rt_export must not include 65001:100 or 65001:250."""
        rt_export = self.design["monitor_design"]["rt_export"]
        forbidden = {"65001:100", "65001:250"}
        for rt in rt_export:
            assert rt not in forbidden, (
                f"MONITOR rt_export {rt} would leak into CUST or INTERNAL"
            )

    def test_quarantine_justification_nonempty(self):
        j = self.design["quarantine_design"]["justification"]
        assert isinstance(j, str) and len(j) > 50, (
            "QUARANTINE justification must be a substantive string"
        )

    def test_monitor_justification_nonempty(self):
        j = self.design["monitor_design"]["justification"]
        assert isinstance(j, str) and len(j) > 50, (
            "MONITOR justification must be a substantive string"
        )

    def test_quarantine_isolation_imports(self):
        """QUARANTINE isolation_properties must show it imports from MGMT."""
        props = self.design["quarantine_design"]["isolation_properties"]
        imports = [v.upper() for v in props.get("imports_routes_from", [])]
        assert "MGMT" in imports, (
            f"QUARANTINE isolation shows imports_routes_from={imports}, expected MGMT"
        )

    def test_quarantine_isolation_no_export_to_cust(self):
        """QUARANTINE must not export to CUST."""
        props = self.design["quarantine_design"]["isolation_properties"]
        exports = [v.upper() for v in props.get("exports_routes_to", [])]
        assert "CUST" not in exports, "QUARANTINE must not export routes to CUST"

    def test_quarantine_isolation_no_leak_to_mgmt(self):
        """QUARANTINE must not leak back to MGMT."""
        props = self.design["quarantine_design"]["isolation_properties"]
        leaks = [v.upper() for v in props.get("leaks_back_to", [])]
        assert "MGMT" not in leaks, "QUARANTINE must not leak routes back to MGMT"

    def test_monitor_isolation_imports(self):
        """MONITOR isolation_properties must show it imports from CUST and INTERNAL."""
        props = self.design["monitor_design"]["isolation_properties"]
        imports = [v.upper() for v in props.get("imports_routes_from", [])]
        assert "CUST" in imports, f"MONITOR must import from CUST, got: {imports}"
        assert "INTERNAL" in imports, f"MONITOR must import from INTERNAL, got: {imports}"

    def test_monitor_isolation_no_export_to_cust_or_internal(self):
        """MONITOR must not export to CUST or INTERNAL."""
        props = self.design["monitor_design"]["isolation_properties"]
        exports = [v.upper() for v in props.get("exports_routes_to", [])]
        assert "CUST" not in exports, "MONITOR must not export routes to CUST"
        assert "INTERNAL" not in exports, "MONITOR must not export routes to INTERNAL"

    def test_security_assessment_has_findings(self):
        """Security assessment must have at least 2 findings."""
        sa = self.design["security_assessment"]
        assert isinstance(sa, list), "security_assessment must be a list"
        assert len(sa) >= 2, (
            f"security_assessment must have at least 2 findings, got {len(sa)}"
        )

    def test_security_assessment_fields(self):
        """Each finding must have finding, severity, recommendation."""
        sa = self.design["security_assessment"]
        for i, finding in enumerate(sa):
            assert "finding" in finding, f"Finding {i} missing 'finding'"
            assert "severity" in finding, f"Finding {i} missing 'severity'"
            assert finding["severity"] in ("high", "medium", "low"), (
                f"Finding {i} severity must be high/medium/low, got: {finding['severity']}"
            )
            assert "recommendation" in finding, f"Finding {i} missing 'recommendation'"
            assert len(finding["recommendation"]) > 10, (
                f"Finding {i} recommendation too short"
            )


class TestValidationReport:
    """Verify that validation was performed on corrected configs."""

    def test_validation_report_exists(self):
        """Validation report must be produced."""
        path = os.path.join(OUTPUT_DIR, "validation_report.txt")
        assert os.path.exists(path), "validation_report.txt not found at /app/output/"

    def test_validation_report_has_content(self):
        """Report must have substantive content."""
        path = os.path.join(OUTPUT_DIR, "validation_report.txt")
        with open(path) as f:
            content = f.read()
        assert len(content) > 200, (
            f"validation_report.txt is too short ({len(content)} chars)"
        )

    def test_validation_report_covers_all_routers(self):
        """Report must reference all three routers."""
        path = os.path.join(OUTPUT_DIR, "validation_report.txt")
        with open(path) as f:
            content = f.read().lower()
        for router in ["r1", "r2", "r3"]:
            assert router in content, (
                f"validation_report.txt must cover router {router}"
            )

    def test_validation_report_contains_frr_output(self):
        """Report must contain FRR/vtysh diagnostic output."""
        path = os.path.join(OUTPUT_DIR, "validation_report.txt")
        with open(path) as f:
            content = f.read().lower()
        indicators = [
            "router bgp",
            "address-family",
            "running-config",
            "show",
            "bgp",
            "vtysh",
            "vrf",
        ]
        found = sum(1 for ind in indicators if ind in content)
        assert found >= 3, (
            "validation_report.txt must contain FRR/vtysh diagnostic output "
            f"(found {found}/7 expected indicators)"
        )

    def test_validation_report_mentions_task_vrfs(self):
        """Report should reference the VRFs defined in the topology plus new ones."""
        path = os.path.join(OUTPUT_DIR, "validation_report.txt")
        with open(path) as f:
            content = f.read()
        vrfs = ["CUST", "MGMT", "INTERNAL", "SERVICES", "PROD", "QUARANTINE", "MONITOR"]
        found = sum(1 for v in vrfs if v in content)
        assert found >= 6, (
            f"validation_report.txt should mention task VRFs, found {found}/7"
        )
