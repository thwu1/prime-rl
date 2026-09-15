"""Test CrowdSec detection pipeline for Nexus API Gateway logs.

Validates parser structure, scenario configuration, acquisition setup,
and end-to-end alert generation for three attack patterns.
"""


import glob
import json
import os
import subprocess
import time

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_parsers():
    """Find custom parser files referencing nexus."""
    results = []
    for pattern in [
        "/etc/crowdsec/parsers/s01-parse/**/*.yaml",
        "/etc/crowdsec/parsers/s01-parse/**/*.yml",
    ]:
        for p in glob.glob(pattern, recursive=True):
            try:
                with open(p) as f:
                    content = f.read()
                if "nexus" in content.lower():
                    results.append(p)
            except OSError:
                pass
    return results


def _find_scenarios():
    """Find custom scenario files referencing nexus."""
    results = []
    for pattern in [
        "/etc/crowdsec/scenarios/**/*.yaml",
        "/etc/crowdsec/scenarios/**/*.yml",
    ]:
        for p in glob.glob(pattern, recursive=True):
            try:
                with open(p) as f:
                    content = f.read()
                if "nexus" in content.lower():
                    results.append(p)
            except OSError:
                pass
    return results


def _get_alerts():
    """Fetch alerts from CrowdSec LAPI with retries."""
    for _ in range(8):
        try:
            r = subprocess.run(
                ["cscli", "alerts", "list", "-o", "json", "--limit", "200"],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip():
                data = json.loads(r.stdout)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except (json.JSONDecodeError, subprocess.TimeoutExpired):
            pass
        time.sleep(5)
    return []


def _alert_ips(alerts):
    ips = set()
    for a in alerts:
        if not isinstance(a, dict):
            continue
        src = a.get("source") or {}
        ip = src.get("ip") or src.get("value") or ""
        if ip:
            ips.add(ip)
    return ips


# ---------------------------------------------------------------------------
# Structural tests – no CrowdSec required
# ---------------------------------------------------------------------------

class TestParserConfiguration:

    def test_parser_file_exists(self):
        parsers = _find_parsers()
        assert len(parsers) >= 1, (
            "No parser YAML referencing 'nexus' found in "
            "/etc/crowdsec/parsers/s01-parse/"
        )

    def test_parser_valid_yaml(self):
        for p in _find_parsers():
            with open(p) as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{p}: not a YAML mapping"
            assert "name" in data, f"{p}: missing 'name'"

    def test_parser_has_filter_or_nodes(self):
        for p in _find_parsers():
            with open(p) as f:
                data = yaml.safe_load(f)
            assert "filter" in data or "nodes" in data, (
                f"{p}: must have 'filter' and/or 'nodes'"
            )


class TestScenarioConfiguration:

    def test_scenario_files_exist(self):
        scenarios = _find_scenarios()
        assert len(scenarios) >= 3, (
            f"Expected >= 3 scenario files referencing 'nexus', "
            f"found {len(scenarios)}. Need brute-force, credential-stuffing, "
            f"and API-scanning scenarios."
        )

    def test_scenarios_valid_yaml(self):
        for s in _find_scenarios():
            with open(s) as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{s}: not a YAML mapping"
            for key in ("type", "name", "filter"):
                assert key in data, f"{s}: missing '{key}'"

    def test_scenarios_have_bucket_params(self):
        for s in _find_scenarios():
            with open(s) as f:
                data = yaml.safe_load(f)
            assert "capacity" in data, f"{s}: missing 'capacity'"
            assert "leakspeed" in data, f"{s}: missing 'leakspeed'"

    def test_credential_stuffing_uses_distinct(self):
        """At least one scenario must use the 'distinct' field for
        credential-stuffing detection (counting unique usernames)."""
        found = False
        for s in _find_scenarios():
            with open(s) as f:
                data = yaml.safe_load(f)
            if "distinct" in data:
                found = True
                break
        assert found, (
            "No scenario uses 'distinct'. Credential-stuffing detection "
            "requires tracking distinct usernames per source IP."
        )


class TestAcquisitionConfiguration:

    def test_acquisition_references_log_file(self):
        found = False
        for pattern in ["/etc/crowdsec/acquis.d/*.yaml",
                        "/etc/crowdsec/acquis.d/*.yml"]:
            for f in glob.glob(pattern):
                with open(f) as fh:
                    if "gateway.log" in fh.read():
                        found = True
                        break
        if not found and os.path.exists("/etc/crowdsec/acquis.yaml"):
            with open("/etc/crowdsec/acquis.yaml") as fh:
                if "gateway.log" in fh.read():
                    found = True
        assert found, (
            "No acquisition config references /app/logs/gateway.log"
        )


# ---------------------------------------------------------------------------
# Functional tests – require CrowdSec running with processed logs
# ---------------------------------------------------------------------------

class TestAlertGeneration:

    @classmethod
    def setup_class(cls):
        cls.alerts = _get_alerts()
        cls.ips = _alert_ips(cls.alerts)

    def test_crowdsec_running(self):
        r = subprocess.run(["pgrep", "-x", "crowdsec"],
                           capture_output=True, text=True)
        assert r.returncode == 0, (
            "CrowdSec process not running. Check parser/scenario YAML validity."
        )

    def test_alerts_generated(self):
        assert len(self.alerts) > 0, (
            "No alerts generated. Verify:\n"
            "  1. Parser extracts fields correctly\n"
            "  2. Scenario filters match parser metadata\n"
            "  3. Acquisition config uses correct label type\n"
            "  4. CrowdSec had time to process the log file"
        )

    def test_brute_force_detected(self):
        assert "203.0.113.42" in self.ips, (
            f"No alert for brute-force IP 203.0.113.42. "
            f"Alerts found for: {sorted(self.ips)}"
        )

    def test_credential_stuffing_detected(self):
        assert "198.51.100.17" in self.ips, (
            f"No alert for credential-stuffing IP 198.51.100.17. "
            f"Alerts found for: {sorted(self.ips)}"
        )

    def test_api_scanning_detected(self):
        assert "192.0.2.99" in self.ips, (
            f"No alert for API-scanning IP 192.0.2.99. "
            f"Alerts found for: {sorted(self.ips)}"
        )

    def test_no_false_positives(self):
        normal = {"10.0.1.10", "10.0.1.11", "10.0.1.12",
                  "10.0.2.20", "10.0.2.21"}
        fp = self.ips & normal
        assert len(fp) == 0, (
            f"False-positive alerts for normal traffic IPs: {sorted(fp)}"
        )
