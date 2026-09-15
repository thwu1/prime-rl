
"""
Tests for Vulnerability Assessment Pipeline Forensics and SSVC Triage.
Verifies that all pipeline bugs have been identified and fixed,
and that SSVC triage decisions are correctly evaluated from corrected output.
"""

import json
import os
import sqlite3
import subprocess
import pytest


# ============================================================
# Expected correct values (after all bugs are fixed)
# ============================================================

EXPECTED_BASE_SCORES = {
    "CVE-2021-44228": 10.0,
    "CVE-2021-45046": 9.0,
    "CVE-2014-6271": 9.8,
    "CVE-2021-23214": 8.1,
    "CVE-2014-0160": 7.5,
    "CVE-2021-41773": 7.5,
    "CVE-2016-5195": 7.0,
    "CVE-2020-11022": 6.1,
    "CVE-2021-3156": 7.8,
    "CVE-2020-14882": 9.8,
}

EXPECTED_AFFECTED = {
    "CVE-2021-44228": ["INV-001"],
    "CVE-2021-45046": ["INV-001"],
    "CVE-2014-6271": ["INV-003"],
    "CVE-2021-23214": ["INV-006"],
    "CVE-2014-0160": ["INV-002"],
    "CVE-2021-41773": ["INV-005"],
    "CVE-2016-5195": ["INV-004"],
    "CVE-2020-11022": ["INV-010"],
}

EXPECTED_NOT_AFFECTED = ["CVE-2021-3156", "CVE-2020-14882"]

EXPECTED_ENV_SCORES = {
    "CVE-2021-44228": 9.1,
    "CVE-2021-45046": 9.1,
    "CVE-2014-6271": 8.1,
    "CVE-2021-23214": 8.1,
    "CVE-2014-0160": 7.7,
    "CVE-2021-41773": 7.7,
    "CVE-2016-5195": 7.0,
    "CVE-2020-11022": 5.4,
}

# After fixing traffic analysis: actively exploited CVEs sorted first
EXPECTED_RANKING = [
    "CVE-2021-44228",   # active=True, env=9.1, base=10.0
    "CVE-2014-6271",    # active=True, env=8.1, base=9.8
    "CVE-2021-41773",   # active=True, env=7.7, base=7.5
    "CVE-2021-45046",   # active=False, env=9.1, base=9.0
    "CVE-2021-23214",   # active=False, env=8.1, base=8.1
    "CVE-2014-0160",    # active=False, env=7.7, base=7.5
    "CVE-2016-5195",    # active=False, env=7.0, base=7.0
    "CVE-2020-11022",   # active=False, env=5.4, base=6.1
]

EXPECTED_ACTIVE_CVES = {"CVE-2014-6271", "CVE-2021-44228", "CVE-2021-41773"}

EXPECTED_SSVC_DECISIONS = {
    "CVE-2021-44228": {"exploitation": "active", "automatable": "yes", "technical_impact": "total", "mission_prevalence": "high", "decision": "Act"},
    "CVE-2014-6271": {"exploitation": "active", "automatable": "yes", "technical_impact": "total", "mission_prevalence": "high", "decision": "Act"},
    "CVE-2021-41773": {"exploitation": "active", "automatable": "yes", "technical_impact": "partial", "mission_prevalence": "medium", "decision": "Act"},
    "CVE-2021-45046": {"exploitation": "none", "automatable": "no", "technical_impact": "total", "mission_prevalence": "high", "decision": "Attend"},
    "CVE-2014-0160": {"exploitation": "none", "automatable": "yes", "technical_impact": "partial", "mission_prevalence": "high", "decision": "Attend"},
    "CVE-2016-5195": {"exploitation": "none", "automatable": "no", "technical_impact": "total", "mission_prevalence": "high", "decision": "Attend"},
    "CVE-2021-23214": {"exploitation": "none", "automatable": "no", "technical_impact": "total", "mission_prevalence": "medium", "decision": "Track*"},
    "CVE-2020-11022": {"exploitation": "none", "automatable": "no", "technical_impact": "partial", "mission_prevalence": "low", "decision": "Track"},
}

EXPECTED_SSVC_ORDER = [
    "CVE-2014-6271", "CVE-2021-41773", "CVE-2021-44228",
    "CVE-2014-0160", "CVE-2016-5195", "CVE-2021-45046",
    "CVE-2021-23214",
    "CVE-2020-11022",
]


# ============================================================
# Fixture: re-run the full pipeline to generate fresh output
# ============================================================

@pytest.fixture(scope="session", autouse=True)
def regenerate_outputs():
    """Delete existing outputs and re-run the full assessment pipeline."""
    for fname in ["score_validation.json", "affected_inventory.json",
                   "remediation_report.json", "active_threats.json"]:
        path = f"/app/{fname}"
        if os.path.exists(path):
            os.remove(path)

    # Step 1: Run traffic analyzer (tshark-based)
    r1 = subprocess.run(
        ["bash", "/app/traffic_analyzer.sh"],
        capture_output=True, text=True, cwd="/app", timeout=60
    )
    assert r1.returncode == 0, (
        f"traffic_analyzer.sh failed with exit code {r1.returncode}:\n"
        f"STDOUT: {r1.stdout}\nSTDERR: {r1.stderr}"
    )

    # Step 2: Run vulnerability assessment
    r2 = subprocess.run(
        ["python3", "/app/vuln_assess.py"],
        capture_output=True, text=True, cwd="/app", timeout=60
    )
    assert r2.returncode == 0, (
        f"vuln_assess.py failed with exit code {r2.returncode}:\n"
        f"STDOUT: {r2.stdout}\nSTDERR: {r2.stderr}"
    )


# ============================================================
# Database integrity tests
# ============================================================

class TestDatabaseIntegrity:
    """Verify that database-level issues have been corrected."""

    def test_log4shell_vector_attack_complexity(self):
        """CVE-2021-44228 must have AC:L (low complexity, easily exploitable RCE)."""
        db = sqlite3.connect('/app/vulndb.sqlite')
        row = db.execute(
            "SELECT cvss_vector FROM cves WHERE cve_id='CVE-2021-44228'"
        ).fetchone()
        db.close()
        assert row is not None, "CVE-2021-44228 not found in database"
        assert 'AC:L' in row[0], (
            f"CVE-2021-44228 should have AC:L (Low attack complexity), "
            f"got vector: {row[0]}"
        )

    def test_log4j_followup_vector_attack_complexity(self):
        """CVE-2021-45046 must have AC:H (high complexity, non-default config)."""
        db = sqlite3.connect('/app/vulndb.sqlite')
        row = db.execute(
            "SELECT cvss_vector FROM cves WHERE cve_id='CVE-2021-45046'"
        ).fetchone()
        db.close()
        assert row is not None, "CVE-2021-45046 not found in database"
        assert 'AC:H' in row[0], (
            f"CVE-2021-45046 should have AC:H (High attack complexity), "
            f"got vector: {row[0]}"
        )

    def test_heartbleed_vulnerable_flag(self):
        """CVE-2014-0160 CPE match for OpenSSL must have vulnerable=1."""
        db = sqlite3.connect('/app/vulndb.sqlite')
        row = db.execute("""
            SELECT cm.vulnerable FROM cpe_matches cm
            JOIN cpe_configurations cc ON cm.config_id = cc.id
            WHERE cc.cve_id = 'CVE-2014-0160'
            AND cm.criteria LIKE '%openssl%'
        """).fetchone()
        db.close()
        assert row is not None, "No CPE match found for CVE-2014-0160 with openssl"
        assert row[0] == 1, (
            f"CVE-2014-0160 OpenSSL CPE match must have vulnerable=1, got {row[0]}"
        )


# ============================================================
# Configuration integrity tests
# ============================================================

class TestConfigIntegrity:
    """Verify that configuration issues have been corrected."""

    def test_confidentiality_requirement_key_exists(self):
        """Config must have correctly spelled 'confidentiality_requirement' key."""
        with open('/app/env_config.json') as f:
            config = json.load(f)
        assert 'confidentiality_requirement' in config, (
            "Config missing 'confidentiality_requirement' key "
            f"(found keys: {list(config.keys())})"
        )

    def test_confidentiality_requirement_value(self):
        """Confidentiality requirement must be HIGH."""
        with open('/app/env_config.json') as f:
            config = json.load(f)
        assert config.get('confidentiality_requirement') == 'HIGH', (
            f"Expected confidentiality_requirement=HIGH, "
            f"got {config.get('confidentiality_requirement')}"
        )

    def test_no_misspelled_keys(self):
        """No misspelled confidentiality requirement key variants should remain."""
        with open('/app/env_config.json') as f:
            config = json.load(f)
        valid_keys = {'confidentiality_requirement', 'modified_confidentiality'}
        for key in config:
            if 'confidential' in key.lower() and key not in valid_keys:
                pytest.fail(
                    f"Found potentially misspelled key '{key}' — "
                    "should be 'confidentiality_requirement'"
                )


# ============================================================
# Traffic analysis tests
# ============================================================

class TestTrafficAnalysis:
    """Verify tshark-based traffic analysis detects all exploit signatures."""

    @pytest.fixture(autouse=True)
    def load_threats(self):
        path = "/app/active_threats.json"
        assert os.path.exists(path), f"Missing output: {path}"
        with open(path) as f:
            self.threats = json.load(f)

    def test_three_exploits_detected(self):
        """All 3 exploit signatures in the PCAP must be identified."""
        assert len(self.threats["active_exploits"]) == 3, (
            f"Expected 3 active exploits, got {len(self.threats['active_exploits'])}: "
            f"{[e['cve_id'] for e in self.threats['active_exploits']]}"
        )

    def test_shellshock_detected(self):
        """Shellshock (CVE-2014-6271) exploit traffic must be detected."""
        cve_ids = {e["cve_id"] for e in self.threats["active_exploits"]}
        assert "CVE-2014-6271" in cve_ids, (
            f"Shellshock not detected. Found: {cve_ids}"
        )

    def test_log4shell_detected(self):
        """Log4Shell (CVE-2021-44228) exploit traffic must be detected."""
        cve_ids = {e["cve_id"] for e in self.threats["active_exploits"]}
        assert "CVE-2021-44228" in cve_ids, (
            f"Log4Shell not detected. Found: {cve_ids}"
        )

    def test_path_traversal_detected(self):
        """Path traversal (CVE-2021-41773) exploit traffic must be detected."""
        cve_ids = {e["cve_id"] for e in self.threats["active_exploits"]}
        assert "CVE-2021-41773" in cve_ids, (
            f"Path traversal not detected. Found: {cve_ids}"
        )

    def test_source_ip_consistent(self):
        """All exploit traffic should originate from the attacker IP."""
        source_ips = {e["source_ip"] for e in self.threats["active_exploits"]}
        assert source_ips == {"10.0.1.100"}, (
            f"Expected all exploits from 10.0.1.100, got sources: {source_ips}"
        )

    def test_exploit_entries_have_evidence(self):
        """Each exploit entry must have source_ip and evidence_frame."""
        for entry in self.threats["active_exploits"]:
            assert "source_ip" in entry, f"Missing source_ip in {entry}"
            assert "evidence_frame" in entry, f"Missing evidence_frame in {entry}"
            assert entry["evidence_frame"] is not None, (
                f"evidence_frame is None for {entry['cve_id']}"
            )


# ============================================================
# Base score tests
# ============================================================

class TestBaseScores:
    """Verify CVSS v3.1 base score computation from corrected data."""

    @pytest.fixture(autouse=True)
    def load_scores(self):
        path = "/app/score_validation.json"
        assert os.path.exists(path), f"Missing output: {path}"
        with open(path) as f:
            self.scores = json.load(f)

    def test_all_cves_present(self):
        for cve_id in EXPECTED_BASE_SCORES:
            assert cve_id in self.scores, f"Missing score for {cve_id}"

    def test_base_score_accuracy(self):
        for cve_id, expected in EXPECTED_BASE_SCORES.items():
            computed = self.scores[cve_id]
            assert abs(computed - expected) < 0.05, (
                f"{cve_id}: expected base {expected}, got {computed}"
            )

    def test_log4shell_is_10(self):
        """Log4Shell must score 10.0 (not 9.0 from the swapped vector)."""
        assert abs(self.scores["CVE-2021-44228"] - 10.0) < 0.05

    def test_log4j_followup_is_9(self):
        """CVE-2021-45046 must score 9.0 (not 10.0 from the swapped vector)."""
        assert abs(self.scores["CVE-2021-45046"] - 9.0) < 0.05


# ============================================================
# CPE matching tests
# ============================================================

class TestAffectedInventory:
    """Verify CPE configuration matching against software inventory."""

    @pytest.fixture(autouse=True)
    def load_affected(self):
        path = "/app/affected_inventory.json"
        assert os.path.exists(path), f"Missing output: {path}"
        with open(path) as f:
            self.affected = json.load(f)

    def test_eight_cves_match(self):
        """Exactly 8 CVEs should match inventory items."""
        for cve_id in EXPECTED_AFFECTED:
            assert cve_id in self.affected, (
                f"{cve_id} should match inventory but is missing"
            )

    def test_matching_inventory_items(self):
        for cve_id, expected_items in EXPECTED_AFFECTED.items():
            actual = self.affected.get(cve_id, [])
            assert set(actual) == set(expected_items), (
                f"{cve_id}: expected {expected_items}, got {actual}"
            )

    def test_non_matching_cves_absent(self):
        for cve_id in EXPECTED_NOT_AFFECTED:
            if cve_id in self.affected:
                assert self.affected[cve_id] == [], (
                    f"{cve_id} should NOT match, but matched: {self.affected[cve_id]}"
                )

    def test_heartbleed_now_detected(self):
        """Heartbleed must now match INV-002 (OpenSSL 1.0.1f) after fix."""
        assert "CVE-2014-0160" in self.affected
        assert "INV-002" in self.affected["CVE-2014-0160"]

    def test_version_range_matching(self):
        assert "INV-001" in self.affected.get("CVE-2021-44228", [])
        assert "INV-004" in self.affected.get("CVE-2016-5195", [])
        assert "INV-006" in self.affected.get("CVE-2021-23214", [])

    def test_exact_version_matching(self):
        assert "INV-005" in self.affected.get("CVE-2021-41773", [])


# ============================================================
# Remediation report tests
# ============================================================

class TestRemediationReport:
    """Verify environmental score computation, active exploitation flags, and priority ranking."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        path = "/app/remediation_report.json"
        assert os.path.exists(path), f"Missing output: {path}"
        with open(path) as f:
            self.report = json.load(f)

    def test_report_length(self):
        assert len(self.report) == 8, f"Expected 8 entries, got {len(self.report)}"

    def test_report_entry_fields(self):
        for entry in self.report:
            for field in ["cve_id", "base_score", "environmental_score",
                          "actively_exploited", "affected_items"]:
                assert field in entry, f"Missing field '{field}' in entry {entry}"

    def test_environmental_scores(self):
        report_map = {e["cve_id"]: e for e in self.report}
        for cve_id, expected_env in EXPECTED_ENV_SCORES.items():
            assert cve_id in report_map, f"Missing {cve_id} in report"
            actual = report_map[cve_id]["environmental_score"]
            assert abs(actual - expected_env) < 0.1, (
                f"{cve_id}: expected env score {expected_env}, got {actual}"
            )

    def test_actively_exploited_flags(self):
        """Verify actively_exploited field matches traffic analysis results."""
        report_map = {e["cve_id"]: e for e in self.report}
        for cve_id in EXPECTED_ACTIVE_CVES:
            assert report_map[cve_id]["actively_exploited"] is True, (
                f"{cve_id} should be actively_exploited=True"
            )
        for entry in self.report:
            if entry["cve_id"] not in EXPECTED_ACTIVE_CVES:
                assert entry["actively_exploited"] is False, (
                    f"{entry['cve_id']} should be actively_exploited=False"
                )

    def test_ranking_order(self):
        """Actively exploited CVEs must rank first, then by environmental score."""
        actual_order = [e["cve_id"] for e in self.report]
        assert actual_order == EXPECTED_RANKING, (
            f"Ranking mismatch:\n  expected: {EXPECTED_RANKING}\n"
            f"  actual:   {actual_order}"
        )

    def test_active_before_inactive(self):
        """All actively exploited entries must appear before non-active entries."""
        switched_to_inactive = False
        for entry in self.report:
            if not entry["actively_exploited"]:
                switched_to_inactive = True
            elif switched_to_inactive:
                pytest.fail(
                    f"Active CVE {entry['cve_id']} appears after inactive entries"
                )

    def test_env_score_differs_from_base_heartbleed(self):
        """Heartbleed env score should exceed base (CR=HIGH boosts conf-only vuln)."""
        report_map = {e["cve_id"]: e for e in self.report}
        entry = report_map["CVE-2014-0160"]
        assert entry["environmental_score"] > entry["base_score"], (
            f"CVE-2014-0160 env ({entry['environmental_score']}) should exceed "
            f"base ({entry['base_score']}) due to CR=HIGH"
        )

    def test_env_score_differs_from_base_log4shell(self):
        """Log4Shell env score should be below base (MAC=HIGH reduces exploitability)."""
        report_map = {e["cve_id"]: e for e in self.report}
        entry = report_map["CVE-2021-44228"]
        assert entry["environmental_score"] < entry["base_score"], (
            f"CVE-2021-44228 env ({entry['environmental_score']}) should be below "
            f"base ({entry['base_score']}) due to MAC=HIGH"
        )

    def test_no_unmatched_cves_in_report(self):
        cve_ids_in_report = {e["cve_id"] for e in self.report}
        for cve_id in EXPECTED_NOT_AFFECTED:
            assert cve_id not in cve_ids_in_report, (
                f"{cve_id} should not be in remediation report"
            )


# ============================================================
# SSVC triage decision tests
# ============================================================

class TestSSVCDecisions:
    """Verify SSVC triage evaluation against corrected pipeline output."""

    @pytest.fixture(autouse=True)
    def load_decisions(self):
        path = "/app/ssvc_decisions.json"
        assert os.path.exists(path), f"Missing output: {path}"
        with open(path) as f:
            self.decisions = json.load(f)

    def test_eight_decisions(self):
        """Each affected CVE must have an SSVC decision."""
        assert len(self.decisions) == 8, (
            f"Expected 8 SSVC decisions, got {len(self.decisions)}"
        )

    def test_required_fields(self):
        """Each entry must have all SSVC decision point fields."""
        for entry in self.decisions:
            for field in ["cve_id", "exploitation", "automatable",
                          "technical_impact", "mission_prevalence", "decision"]:
                assert field in entry, (
                    f"Missing '{field}' in SSVC entry for "
                    f"{entry.get('cve_id', 'unknown')}"
                )

    def test_act_decisions(self):
        """Actively exploited + automatable CVEs must be Act."""
        dm = {e["cve_id"]: e for e in self.decisions}
        for cve_id in ["CVE-2021-44228", "CVE-2014-6271", "CVE-2021-41773"]:
            assert cve_id in dm, f"{cve_id} missing from SSVC decisions"
            assert dm[cve_id]["decision"] == "Act", (
                f"{cve_id} should be Act, got {dm[cve_id]['decision']}"
            )

    def test_attend_decisions(self):
        """Non-exploited CVEs with high mission impact must be Attend."""
        dm = {e["cve_id"]: e for e in self.decisions}
        for cve_id in ["CVE-2021-45046", "CVE-2014-0160", "CVE-2016-5195"]:
            assert cve_id in dm, f"{cve_id} missing from SSVC decisions"
            assert dm[cve_id]["decision"] == "Attend", (
                f"{cve_id} should be Attend, got {dm[cve_id]['decision']}"
            )

    def test_track_star_decisions(self):
        """Non-exploited CVEs with medium mission impact must be Track*."""
        dm = {e["cve_id"]: e for e in self.decisions}
        assert "CVE-2021-23214" in dm
        assert dm["CVE-2021-23214"]["decision"] == "Track*", (
            f"CVE-2021-23214 should be Track*, got {dm['CVE-2021-23214']['decision']}"
        )

    def test_track_decisions(self):
        """Low-impact, non-exploited, non-automatable CVEs must be Track."""
        dm = {e["cve_id"]: e for e in self.decisions}
        assert "CVE-2020-11022" in dm
        assert dm["CVE-2020-11022"]["decision"] == "Track", (
            f"CVE-2020-11022 should be Track, got {dm['CVE-2020-11022']['decision']}"
        )

    def test_exploitation_matches_traffic_analysis(self):
        """SSVC exploitation status must be consistent with regenerated traffic analysis."""
        with open('/app/active_threats.json') as f:
            threats = json.load(f)
        active_cves = {e['cve_id'] for e in threats.get('active_exploits', [])}

        dm = {e["cve_id"]: e for e in self.decisions}
        for cve_id, entry in dm.items():
            if cve_id in active_cves:
                assert entry["exploitation"] == "active", (
                    f"{cve_id} has traffic evidence but exploitation != 'active'"
                )
            else:
                assert entry["exploitation"] == "none", (
                    f"{cve_id} has no traffic evidence but exploitation != 'none'"
                )

    def test_automatable_determination(self):
        """Automatable must be correctly derived from corrected CVSS vectors."""
        dm = {e["cve_id"]: e for e in self.decisions}
        # AV:N + AC:L + UI:N → automatable
        for cve_id in ["CVE-2021-44228", "CVE-2014-6271",
                        "CVE-2021-41773", "CVE-2014-0160"]:
            assert dm[cve_id]["automatable"] == "yes", (
                f"{cve_id} should be automatable=yes (AV:N, AC:L, UI:N)"
            )
        # One or more conditions not met → not automatable
        for cve_id in ["CVE-2021-45046", "CVE-2021-23214",
                        "CVE-2016-5195", "CVE-2020-11022"]:
            assert dm[cve_id]["automatable"] == "no", (
                f"{cve_id} should be automatable=no"
            )

    def test_log4shell_automatable_requires_vector_fix(self):
        """Log4Shell automatable=yes requires the CVSS vector to be corrected (AC:L, not AC:H)."""
        dm = {e["cve_id"]: e for e in self.decisions}
        assert dm["CVE-2021-44228"]["automatable"] == "yes", (
            "CVE-2021-44228 should be automatable (AC:L) — "
            "CVSS vector may not be corrected"
        )

    def test_heartbleed_present_requires_cpe_fix(self):
        """Heartbleed must appear in SSVC decisions (requires CPE vulnerable=1 fix)."""
        cve_ids = {e["cve_id"] for e in self.decisions}
        assert "CVE-2014-0160" in cve_ids, (
            "CVE-2014-0160 missing from SSVC decisions — "
            "CPE vulnerable flag may not be corrected"
        )

    def test_technical_impact(self):
        """Technical impact must be correctly derived from CVSS CIA metrics."""
        dm = {e["cve_id"]: e for e in self.decisions}
        # All three CIA are HIGH → total
        for cve_id in ["CVE-2021-44228", "CVE-2021-45046", "CVE-2014-6271",
                        "CVE-2021-23214", "CVE-2016-5195"]:
            assert dm[cve_id]["technical_impact"] == "total", (
                f"{cve_id} should have technical_impact=total (C:H,I:H,A:H)"
            )
        # At least one CIA not HIGH → partial
        for cve_id in ["CVE-2014-0160", "CVE-2021-41773", "CVE-2020-11022"]:
            assert dm[cve_id]["technical_impact"] == "partial", (
                f"{cve_id} should have technical_impact=partial"
            )

    def test_mission_prevalence(self):
        """Mission prevalence must match mission_impact.json for affected items."""
        dm = {e["cve_id"]: e for e in self.decisions}
        expected_mission = {
            "CVE-2021-44228": "high",   # INV-001
            "CVE-2021-45046": "high",   # INV-001
            "CVE-2014-6271": "high",    # INV-003
            "CVE-2021-23214": "medium", # INV-006
            "CVE-2014-0160": "high",    # INV-002
            "CVE-2021-41773": "medium", # INV-005
            "CVE-2016-5195": "high",    # INV-004
            "CVE-2020-11022": "low",    # INV-010
        }
        for cve_id, expected in expected_mission.items():
            assert dm[cve_id]["mission_prevalence"] == expected, (
                f"{cve_id} mission_prevalence should be {expected}, "
                f"got {dm[cve_id]['mission_prevalence']}"
            )

    def test_priority_ordering(self):
        """Decisions must be ordered: Act, Attend, Track*, Track; CVE ascending within."""
        priority_order = {"Act": 0, "Attend": 1, "Track*": 2, "Track": 3}
        for i in range(len(self.decisions) - 1):
            curr = self.decisions[i]
            nxt = self.decisions[i + 1]
            curr_p = priority_order[curr["decision"]]
            nxt_p = priority_order[nxt["decision"]]
            if curr_p == nxt_p:
                assert curr["cve_id"] < nxt["cve_id"], (
                    f"Within {curr['decision']}: {curr['cve_id']} should come "
                    f"before {nxt['cve_id']}"
                )
            else:
                assert curr_p < nxt_p, (
                    f"{curr['cve_id']} ({curr['decision']}) should come before "
                    f"{nxt['cve_id']} ({nxt['decision']})"
                )

    def test_unmatched_cves_absent(self):
        """CVEs with no inventory matches should not appear in SSVC decisions."""
        cve_ids = {e["cve_id"] for e in self.decisions}
        for cve_id in EXPECTED_NOT_AFFECTED:
            assert cve_id not in cve_ids, (
                f"{cve_id} should not be in SSVC decisions (no inventory match)"
            )

    def test_covers_all_affected(self):
        """SSVC decisions must cover exactly the CVEs in affected_inventory.json."""
        with open('/app/affected_inventory.json') as f:
            affected = json.load(f)
        ssvc_cves = {e["cve_id"] for e in self.decisions}
        affected_cves = set(affected.keys())
        assert ssvc_cves == affected_cves, (
            f"SSVC CVEs {ssvc_cves} must match affected CVEs {affected_cves}"
        )
