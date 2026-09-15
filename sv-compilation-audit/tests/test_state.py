
import json
import os
import re
import subprocess


class TestSlangCompilation:
    """Verify that slang compiles the design cleanly with the warning policy."""

    def test_build_file_exists(self):
        assert os.path.isfile("/app/build.f"), "Command file /app/build.f must exist"

    def test_warning_policy_exists(self):
        assert os.path.isfile("/app/warning_policy.f"), (
            "Warning policy file /app/warning_policy.f must exist"
        )

    def test_slang_compiles_cleanly_with_policy(self):
        result = subprocess.run(
            ["slang", "-f", "/app/build.f", "-f", "/app/warning_policy.f"],
            capture_output=True,
            text=True,
            cwd="/app",
            timeout=60,
        )
        assert result.returncode == 0, (
            f"slang must exit 0, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "0 errors" in combined, (
            f"Expected 0 errors, got:\n{combined}"
        )
        assert "0 warnings" in combined, (
            f"Expected 0 warnings, got:\n{combined}"
        )


class TestWarningPolicy:
    """Verify the warning policy file is properly constructed."""

    def test_policy_enables_weverything(self):
        with open("/app/warning_policy.f") as f:
            content = f.read()
        assert "-Weverything" in content, (
            "Warning policy must enable -Weverything for maximum coverage"
        )

    def test_policy_no_wnone(self):
        with open("/app/warning_policy.f") as f:
            content = f.read()
        assert "-Wnone" not in content, (
            "Warning policy must NOT use -Wnone (blanket suppression is not acceptable)"
        )

    def test_policy_has_selective_suppressions(self):
        with open("/app/warning_policy.f") as f:
            content = f.read()
        wno_flags = re.findall(r"-Wno-[\w-]+", content)
        assert len(wno_flags) >= 3, (
            f"Warning policy must have at least 3 selective -Wno-* suppressions, "
            f"found {len(wno_flags)}: {wno_flags}"
        )


class TestCompilationErrorFixes:
    """Verify the compilation errors in the SV source files are fixed."""

    def test_switch_has_package_import(self):
        with open("/app/design/rtl/xbar_switch.sv") as f:
            content = f.read()
        assert "import" in content and "xbar_pkg" in content, (
            "xbar_switch.sv must import xbar_pkg to access xbar_req_t/xbar_resp_t"
        )

    def test_top_no_address_typo(self):
        with open("/app/design/top/top_xbar.sv") as f:
            content = f.read()
        assert ".address" not in content, (
            "top_xbar.sv still contains '.address' (should be '.addr')"
        )
        assert ".addr" in content, (
            "top_xbar.sv must reference the struct field '.addr'"
        )


class TestSilentBugFixes:
    """Verify the silent semantic bugs are fixed."""

    def test_arbiter_no_implicit_net_typo(self):
        """The masked_requests typo creates an implicit net instead of erroring."""
        with open("/app/design/rtl/round_robin_arb.sv") as f:
            content = f.read()
        assert "masked_requests" not in content, (
            "round_robin_arb.sv still contains 'masked_requests' — this creates "
            "a dangling implicit net instead of connecting to the computed "
            "'masked_req' signal"
        )
        assert "masked_req" in content, (
            "round_robin_arb.sv must connect the 'masked_req' signal to the "
            "priority encoder"
        )

    def test_addr_decoder_parameterized(self):
        """The addr_decoder must use parameterized bit-slice, not hardcoded."""
        with open("/app/design/rtl/addr_decoder.sv") as f:
            content = f.read()
        # Check that hardcoded [15:14] is NOT present
        assert "[15:14]" not in content, (
            "addr_decoder.sv still uses hardcoded [15:14] bit-slice — "
            "must use parameterized expression per SPEC.md"
        )
        # Check that parameterized expressions ARE used
        has_param_ref = ("ADDR_W" in content or "SEL_W" in content)
        assert has_param_ref, (
            "addr_decoder.sv bit-slice must reference ADDR_W and/or SEL_W "
            "parameters for proper parameterization"
        )

    def test_addr_decoder_uses_sel_w_in_logic(self):
        """SEL_W localparam must actually be used in the assign logic."""
        with open("/app/design/rtl/addr_decoder.sv") as f:
            content = f.read()
        # Find the assign statement(s) for sel
        assign_lines = [
            line for line in content.split("\n")
            if "assign" in line and "sel" in line.split("//")[0]
            and "valid" not in line
        ]
        assert len(assign_lines) > 0, (
            "addr_decoder.sv must have an assign statement for 'sel'"
        )
        assign_text = " ".join(assign_lines)
        uses_param = (
            "ADDR_W" in assign_text or "SEL_W" in assign_text
            or "NUM_OUTPUTS" in assign_text
        )
        assert uses_param, (
            f"addr_decoder sel assignment must use parameters, "
            f"found: {assign_text}"
        )


class TestTriageReport:
    """Verify the diagnostic triage report."""

    def test_report_exists(self):
        assert os.path.isfile("/app/triage_report.json"), (
            "/app/triage_report.json must exist"
        )

    def test_report_valid_json(self):
        with open("/app/triage_report.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "Triage report must be a JSON object"

    def test_report_has_compilation_errors(self):
        with open("/app/triage_report.json") as f:
            data = json.load(f)
        assert "compilation_errors" in data, (
            "Triage report must have 'compilation_errors' key"
        )
        errors = data["compilation_errors"]
        assert isinstance(errors, list), "'compilation_errors' must be a list"
        assert len(errors) >= 2, (
            f"Expected at least 2 compilation error entries, got {len(errors)}"
        )
        for err in errors:
            assert "file" in err, f"Compilation error entry missing 'file': {err}"
            assert "description" in err, (
                f"Compilation error entry missing 'description': {err}"
            )
            assert "root_cause" in err, (
                f"Compilation error entry missing 'root_cause': {err}"
            )

    def test_report_has_silent_bugs(self):
        with open("/app/triage_report.json") as f:
            data = json.load(f)
        assert "silent_bugs" in data, (
            "Triage report must have 'silent_bugs' key"
        )
        bugs = data["silent_bugs"]
        assert isinstance(bugs, list), "'silent_bugs' must be a list"
        assert len(bugs) >= 2, (
            f"Expected at least 2 silent bug entries, got {len(bugs)}"
        )
        for bug in bugs:
            assert "file" in bug, f"Silent bug entry missing 'file': {bug}"
            assert "description" in bug, (
                f"Silent bug entry missing 'description': {bug}"
            )
            assert "how_detected" in bug, (
                f"Silent bug entry missing 'how_detected': {bug}"
            )

    def test_report_has_false_positives(self):
        with open("/app/triage_report.json") as f:
            data = json.load(f)
        assert "false_positives" in data, (
            "Triage report must have 'false_positives' key"
        )
        fps = data["false_positives"]
        assert isinstance(fps, list), "'false_positives' must be a list"
        assert len(fps) >= 3, (
            f"Expected at least 3 false positive entries, got {len(fps)}"
        )
        for fp in fps:
            assert "warning_flag" in fp, (
                f"False positive entry missing 'warning_flag': {fp}"
            )
            assert "reason_suppressed" in fp, (
                f"False positive entry missing 'reason_suppressed': {fp}"
            )

    def test_report_mentions_key_files(self):
        with open("/app/triage_report.json") as f:
            data = json.load(f)
        all_text = json.dumps(data).lower()
        assert "xbar_switch" in all_text, (
            "Triage report should mention xbar_switch.sv"
        )
        assert "addr_decoder" in all_text, (
            "Triage report should mention addr_decoder.sv"
        )
        assert "round_robin_arb" in all_text, (
            "Triage report should mention round_robin_arb.sv"
        )


class TestHierarchyReport:
    """Verify the extracted hierarchy report."""

    def test_report_exists(self):
        assert os.path.isfile("/app/hierarchy_report.json"), (
            "/app/hierarchy_report.json must exist"
        )

    def test_report_valid_json(self):
        with open("/app/hierarchy_report.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "Report must be a JSON object"
        assert "modules" in data, "Report must have a 'modules' key"
        assert isinstance(data["modules"], list), "'modules' must be a list"

    def test_report_has_all_modules(self):
        with open("/app/hierarchy_report.json") as f:
            data = json.load(f)
        module_names = {m["name"] for m in data["modules"]}
        expected = {
            "top_xbar", "round_robin_arb", "xbar_switch",
            "priority_enc", "addr_decoder",
        }
        assert expected.issubset(module_names), (
            f"Missing modules: {expected - module_names}. "
            f"Found: {module_names}"
        )

    def test_report_module_structure(self):
        with open("/app/hierarchy_report.json") as f:
            data = json.load(f)
        for mod in data["modules"]:
            assert "name" in mod, f"Module entry missing 'name': {mod}"
            assert "ports" in mod, f"Module '{mod['name']}' missing 'ports'"
            assert "parameters" in mod, (
                f"Module '{mod['name']}' missing 'parameters'"
            )
            assert isinstance(mod["ports"], list), (
                f"Module '{mod['name']}' ports must be a list"
            )
            assert isinstance(mod["parameters"], list), (
                f"Module '{mod['name']}' parameters must be a list"
            )

    def test_top_xbar_ports(self):
        with open("/app/hierarchy_report.json") as f:
            data = json.load(f)
        top = next(
            (m for m in data["modules"] if m["name"] == "top_xbar"), None
        )
        assert top is not None, "top_xbar not found in report"
        port_names = {p["name"] for p in top["ports"]}
        expected_ports = {
            "clk", "rst_n", "mst_req", "mst_resp", "slv_req", "slv_resp",
        }
        assert expected_ports.issubset(port_names), (
            f"top_xbar missing ports: {expected_ports - port_names}. "
            f"Found: {port_names}"
        )
        for p in top["ports"]:
            assert "direction" in p, f"Port '{p['name']}' missing 'direction'"

    def test_top_xbar_parameters(self):
        with open("/app/hierarchy_report.json") as f:
            data = json.load(f)
        top = next(
            (m for m in data["modules"] if m["name"] == "top_xbar"), None
        )
        assert top is not None, "top_xbar not found in report"
        param_names = {p["name"] for p in top["parameters"]}
        assert "N_MASTERS" in param_names, (
            "top_xbar missing parameter N_MASTERS"
        )
        assert "N_SLAVES" in param_names, (
            "top_xbar missing parameter N_SLAVES"
        )
        for p in top["parameters"]:
            assert "value" in p, f"Parameter '{p['name']}' missing 'value'"

    def test_addr_decoder_ports(self):
        with open("/app/hierarchy_report.json") as f:
            data = json.load(f)
        dec = next(
            (m for m in data["modules"] if m["name"] == "addr_decoder"), None
        )
        assert dec is not None, "addr_decoder not found in report"
        port_names = {p["name"] for p in dec["ports"]}
        expected_ports = {"addr", "sel", "valid"}
        assert expected_ports.issubset(port_names), (
            f"addr_decoder missing ports: {expected_ports - port_names}"
        )

    def test_priority_enc_ports(self):
        with open("/app/hierarchy_report.json") as f:
            data = json.load(f)
        penc = next(
            (m for m in data["modules"] if m["name"] == "priority_enc"), None
        )
        assert penc is not None, "priority_enc not found in report"
        port_names = {p["name"] for p in penc["ports"]}
        expected_ports = {"req", "idx", "valid"}
        assert expected_ports.issubset(port_names), (
            f"priority_enc missing ports: {expected_ports - port_names}"
        )

    def test_port_directions_valid(self):
        with open("/app/hierarchy_report.json") as f:
            data = json.load(f)
        valid_directions = {"In", "Out", "InOut", "input", "output", "inout"}
        for mod in data["modules"]:
            for p in mod["ports"]:
                assert p.get("direction") in valid_directions, (
                    f"Port '{p['name']}' in '{mod['name']}' has invalid "
                    f"direction: {p.get('direction')}"
                )
