
import json
import os
import subprocess

# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_report():
    with open("/app/vulnerability_report.json") as f:
        return json.load(f)


def _find_entry(report, pkg_name):
    """Find a report entry by package name (tolerates common variants)."""
    variants = {pkg_name, pkg_name.replace("-", "_"), pkg_name.replace("_", "-")}
    for entry in report:
        name = entry.get("package", entry.get("name", ""))
        if name in variants:
            return entry
    return None


def _json_upper(entry):
    """Dump entry as uppercase JSON for case-insensitive substring checks."""
    return json.dumps(entry).upper()


# ── Vulnerability Report Tests ───────────────────────────────────────────────

class TestVulnerabilityReport:

    def test_report_exists_and_valid_json(self):
        assert os.path.exists("/app/vulnerability_report.json"), "Report file missing"
        report = _load_report()
        assert isinstance(report, list), "Report must be a JSON array"

    def test_report_identifies_all_four_packages(self):
        report = _load_report()
        found = {
            (e.get("package", e.get("name", ""))).replace("_", "-")
            for e in report
        }
        for pkg in ("flat", "tar", "nth-check", "js-yaml"):
            assert pkg in found, f"Report is missing entry for {pkg}"

    # ── flat ──────────────────────────────────────────────────────────────

    def test_flat_version(self):
        entry = _find_entry(_load_report(), "flat")
        assert entry is not None
        v = entry.get("installed_version", entry.get("version", ""))
        assert v == "5.0.0"

    def test_flat_cve_or_ghsa(self):
        entry = _find_entry(_load_report(), "flat")
        blob = _json_upper(entry)
        assert "CVE-2020-36632" in blob or "GHSA-2J2X-2GPW-G8FM" in blob

    def test_flat_cwe(self):
        entry = _find_entry(_load_report(), "flat")
        blob = _json_upper(entry)
        assert "1321" in blob, "Expected CWE-1321 for flat"

    def test_flat_patched(self):
        entry = _find_entry(_load_report(), "flat")
        assert "5.0.1" in json.dumps(entry)

    # ── tar ──────────────────────────────────────────────────────────────

    def test_tar_version(self):
        entry = _find_entry(_load_report(), "tar")
        assert entry is not None
        v = entry.get("installed_version", entry.get("version", ""))
        assert v == "6.1.1"

    def test_tar_cve_or_ghsa(self):
        entry = _find_entry(_load_report(), "tar")
        blob = _json_upper(entry)
        ok = (
            "CVE-2021-32803" in blob
            or "CVE-2021-32804" in blob
            or "GHSA-R628-MHMH-QJHW" in blob
            or "GHSA-9R2W-394V-53QC" in blob
        )
        assert ok, "Expected a known tar CVE/GHSA"

    def test_tar_cwe(self):
        entry = _find_entry(_load_report(), "tar")
        blob = _json_upper(entry)
        assert "22" in blob or "23" in blob or "59" in blob, \
            "Expected CWE-22, CWE-23, or CWE-59 for tar"

    def test_tar_patched(self):
        entry = _find_entry(_load_report(), "tar")
        assert "6.1.2" in json.dumps(entry)

    # ── nth-check ────────────────────────────────────────────────────────

    def test_nthcheck_version(self):
        entry = _find_entry(_load_report(), "nth-check")
        assert entry is not None
        v = entry.get("installed_version", entry.get("version", ""))
        assert v == "2.0.0"

    def test_nthcheck_cve_or_ghsa(self):
        entry = _find_entry(_load_report(), "nth-check")
        blob = _json_upper(entry)
        assert "CVE-2021-3803" in blob or "GHSA-RP65-9CF3-CJXR" in blob

    def test_nthcheck_cwe(self):
        entry = _find_entry(_load_report(), "nth-check")
        blob = _json_upper(entry)
        assert "1333" in blob or "400" in blob, \
            "Expected CWE-1333 or CWE-400 for nth-check"

    def test_nthcheck_patched(self):
        entry = _find_entry(_load_report(), "nth-check")
        assert "2.0.1" in json.dumps(entry)

    # ── js-yaml ──────────────────────────────────────────────────────────

    def test_jsyaml_version(self):
        entry = _find_entry(_load_report(), "js-yaml")
        assert entry is not None
        v = entry.get("installed_version", entry.get("version", ""))
        assert v == "3.13.0"

    def test_jsyaml_ghsa(self):
        entry = _find_entry(_load_report(), "js-yaml")
        blob = _json_upper(entry)
        assert "GHSA-8J8C-7JFH-H6HX" in blob

    def test_jsyaml_cwe(self):
        entry = _find_entry(_load_report(), "js-yaml")
        blob = _json_upper(entry)
        assert "94" in blob, "Expected CWE-94 for js-yaml"

    def test_jsyaml_patched(self):
        entry = _find_entry(_load_report(), "js-yaml")
        assert "3.13.1" in json.dumps(entry)


# ── Exploit Tests ────────────────────────────────────────────────────────────

class TestExploits:

    def test_prototype_pollution_exploit(self):
        r = subprocess.run(
            ["node", "/app/exploits/prototype_pollution.js"],
            capture_output=True, text=True, timeout=30, cwd="/app",
        )
        assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
        assert "VULN_CONFIRMED" in r.stdout, f"stdout={r.stdout}"

    def test_path_traversal_exploit(self):
        r = subprocess.run(
            ["node", "/app/exploits/path_traversal.js"],
            capture_output=True, text=True, timeout=60, cwd="/app",
        )
        assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
        assert "VULN_CONFIRMED" in r.stdout, f"stdout={r.stdout}"

    def test_redos_exploit(self):
        r = subprocess.run(
            ["node", "/app/exploits/redos.js"],
            capture_output=True, text=True, timeout=120, cwd="/app",
        )
        assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
        assert "VULN_CONFIRMED" in r.stdout, f"stdout={r.stdout}"

    def test_code_injection_exploit(self):
        r = subprocess.run(
            ["node", "/app/exploits/code_injection.js"],
            capture_output=True, text=True, timeout=30, cwd="/app",
        )
        assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
        assert "VULN_CONFIRMED" in r.stdout, f"stdout={r.stdout}"


# ── Mitigation Tests ─────────────────────────────────────────────────────────

class TestMitigations:

    def test_prototype_pollution_mitigated(self):
        r = subprocess.run(
            ["node", "/app/mitigations/prototype_pollution_safe.js"],
            capture_output=True, text=True, timeout=30, cwd="/app",
        )
        assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
        assert "MITIGATED" in r.stdout, f"stdout={r.stdout}"

    def test_path_traversal_mitigated(self):
        r = subprocess.run(
            ["node", "/app/mitigations/path_traversal_safe.js"],
            capture_output=True, text=True, timeout=60, cwd="/app",
        )
        assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
        assert "MITIGATED" in r.stdout, f"stdout={r.stdout}"

    def test_redos_mitigated(self):
        r = subprocess.run(
            ["node", "/app/mitigations/redos_safe.js"],
            capture_output=True, text=True, timeout=30, cwd="/app",
        )
        assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
        assert "MITIGATED" in r.stdout, f"stdout={r.stdout}"

    def test_code_injection_mitigated(self):
        r = subprocess.run(
            ["node", "/app/mitigations/code_injection_safe.js"],
            capture_output=True, text=True, timeout=30, cwd="/app",
        )
        assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
        assert "MITIGATED" in r.stdout, f"stdout={r.stdout}"
