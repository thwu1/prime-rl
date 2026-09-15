#!/usr/bin/env python3
"""Tests for AD attack path forensic assessment task."""

import json
import os

import pytest

RESULTS_PATH = "/app/results.json"

REQUIRED_CRACKED = {
    "jsmith": "Summer2024!",
    "svc_backup": "Backup#Service99",
    "da_johnson": "J0hn$on@dmin2024",
}

ALL_EXPECTED = {
    "jsmith": "Summer2024!",
    "bwilson": "Welcome1!",
    "agarcia": "Acme2024Spring",
    "svc_backup": "Backup#Service99",
    "svc_web": "WebApp2024$ecure",
    "da_johnson": "J0hn$on@dmin2024",
    "Administrator": "Adm!n#Pr0tect3d",
    "mhenderson": "P@ssw0rd2024",
    "svc_exchange": "Exch@nge$vc2024",
}

EXPECTED_FLAG = "ACME{d0m41n_c0mpr0m1s3d_v14_cr3d_ch41n_2024}"


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} not found"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ── Structure ──────────────────────────────────────────────


class TestStructure:
    def test_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_all_credentials(self, results):
        assert "all_credentials" in results
        assert isinstance(results["all_credentials"], dict)

    def test_has_attack_chain(self, results):
        assert "attack_chain" in results
        assert isinstance(results["attack_chain"], list)

    def test_has_domain_admin(self, results):
        assert "domain_admin" in results
        assert isinstance(results["domain_admin"], dict)

    def test_has_objective(self, results):
        assert "objective" in results
        assert isinstance(results["objective"], str)

    def test_has_vulnerability_assessment(self, results):
        assert "vulnerability_assessment" in results
        assert isinstance(results["vulnerability_assessment"], list)

    def test_has_remediation_plan(self, results):
        assert "remediation_plan" in results
        assert isinstance(results["remediation_plan"], list)

    def test_has_selected_hypothesis(self, results):
        assert "selected_hypothesis" in results

    def test_has_hypothesis_justification(self, results):
        assert "hypothesis_justification" in results
        assert isinstance(results["hypothesis_justification"], str)
        assert len(results["hypothesis_justification"]) >= 50, (
            "Justification too short — must reference specific evidence"
        )


# ── Credentials ────────────────────────────────────────────


class TestCredentials:
    def test_required_creds(self, results):
        creds = results["all_credentials"]
        for user, pwd in REQUIRED_CRACKED.items():
            assert user in creds, f"Missing required credential: {user}"
            assert creds[user] == pwd, (
                f"Wrong password for {user}: got {creds[user]!r}"
            )

    def test_breadth(self, results):
        creds = results["all_credentials"]
        correct = sum(
            1
            for u, p in ALL_EXPECTED.items()
            if creds.get(u) == p
        )
        assert correct >= 6, (
            f"Only {correct}/9 expected credentials correct (need >= 6)"
        )


# ── Hypothesis Selection (Evaluate) ──────────────────────


class TestHypothesisEvaluation:
    def test_correct_hypothesis_selected(self, results):
        selected = str(results["selected_hypothesis"]).upper().strip()
        assert selected == "A", (
            f"Wrong hypothesis selected: {selected!r} — "
            "event log evidence supports Hypothesis A (LLMNR Poisoning Chain)"
        )

    def test_justification_references_evidence(self, results):
        justification = results["hypothesis_justification"].lower()
        evidence_keywords = [
            "event", "log", "4776", "4769", "4662", "4624",
            "ntlm", "kerbero", "llmnr", "responder", "10.10.10.50",
            "replication", "dcsync", "rc4", "0x17",
        ]
        found = sum(1 for kw in evidence_keywords if kw in justification)
        assert found >= 3, (
            f"Justification references only {found} evidence indicators "
            "(need >= 3) — must cite specific event log entries"
        )

    def test_justification_distinguishes_scanner(self, results):
        """Expert should recognize 10.10.10.100 traffic as scanner, not attacker."""
        justification = results["hypothesis_justification"].lower()
        scanner_indicators = ["scanner", "10.10.10.100", "brute", "generic",
                              "automated", "non-existent", "invalid user"]
        found = any(kw in justification for kw in scanner_indicators)
        assert found, (
            "Justification should address why 10.10.10.100 activity is "
            "not the attacker (scanner/automated probe traffic)"
        )


# ── Attack Chain ───────────────────────────────────────────


class TestAttackChain:
    def test_minimum_stages(self, results):
        assert len(results["attack_chain"]) >= 3

    def test_ordering(self, results):
        chain = results["attack_chain"]
        accts = []
        for s in chain:
            a = s.get("account", s.get("target", "")).lower()
            if a:
                accts.append(a)

        if "jsmith" in accts and "svc_backup" in accts:
            assert accts.index("jsmith") < accts.index("svc_backup"), (
                "jsmith must precede svc_backup in the chain"
            )
        if "svc_backup" in accts and "da_johnson" in accts:
            assert accts.index("svc_backup") < accts.index("da_johnson"), (
                "svc_backup must precede da_johnson in the chain"
            )

    def test_techniques_mentioned(self, results):
        text = json.dumps(results["attack_chain"]).lower()
        found = 0
        for group in [
            ["llmnr", "nbt-ns", "nbns", "responder", "poisoning"],
            ["kerberoast", "tgs", "service ticket", "spn"],
            ["ntds", "dcsync", "secretsdump", "hash dump", "replication"],
        ]:
            if any(t in text for t in group):
                found += 1
        assert found >= 2, f"Only {found}/3 technique categories identified"

    def test_chain_has_evidence_field(self, results):
        """Attack chain stages should reference supporting evidence."""
        chain = results["attack_chain"]
        stages_with_evidence = sum(
            1 for s in chain
            if s.get("evidence") and len(str(s["evidence"])) > 10
        )
        assert stages_with_evidence >= 2, (
            "Attack chain stages should include evidence references "
            "(event IDs, log entries, artifact filenames)"
        )


# ── Vulnerability Assessment (Create) ─────────────────────


class TestVulnerabilityAssessment:
    def test_minimum_vulnerabilities(self, results):
        vulns = results["vulnerability_assessment"]
        assert len(vulns) >= 5, (
            f"Only {len(vulns)} vulnerabilities identified (need >= 5)"
        )

    def test_vuln_structure(self, results):
        for v in results["vulnerability_assessment"]:
            assert "id" in v, "Vulnerability missing 'id' field"
            assert "severity" in v, f"Vulnerability {v.get('id')} missing 'severity'"
            assert "cvss_base_score" in v, f"Vulnerability {v.get('id')} missing 'cvss_base_score'"

    def test_cvss_scores_valid(self, results):
        for v in results["vulnerability_assessment"]:
            score = v["cvss_base_score"]
            assert isinstance(score, (int, float)), (
                f"{v['id']}: cvss_base_score must be numeric, got {type(score)}"
            )
            assert 0.0 <= score <= 10.0, (
                f"{v['id']}: CVSS score {score} out of range [0.0, 10.0]"
            )

    def test_severity_cvss_consistency(self, results):
        """CVSS scores must be roughly consistent with severity labels."""
        for v in results["vulnerability_assessment"]:
            score = float(v["cvss_base_score"])
            sev = v["severity"].lower()
            if sev == "critical":
                assert score >= 8.5, (
                    f"{v['id']}: critical severity but CVSS={score} (expect >= 8.5)"
                )
            elif sev == "high":
                assert score >= 6.5, (
                    f"{v['id']}: high severity but CVSS={score} (expect >= 6.5)"
                )
            elif sev == "medium":
                assert score >= 3.5, (
                    f"{v['id']}: medium severity but CVSS={score} (expect >= 3.5)"
                )

    def test_llmnr_vulnerability_identified(self, results):
        """Must identify LLMNR/NBT-NS as a vulnerability."""
        vulns_text = json.dumps(results["vulnerability_assessment"]).lower()
        llmnr_keywords = ["llmnr", "nbt-ns", "nbns", "name resolution",
                          "multicast dns", "link-local", "poisoning"]
        assert any(kw in vulns_text for kw in llmnr_keywords), (
            "Must identify LLMNR/NBT-NS enabled as a vulnerability"
        )

    def test_kerberos_rc4_vulnerability_identified(self, results):
        """Must identify RC4 for Kerberos as enabling Kerberoasting."""
        vulns_text = json.dumps(results["vulnerability_assessment"]).lower()
        rc4_keywords = ["rc4", "kerberoast", "weak encryption",
                        "etype 23", "rc4-hmac", "service ticket"]
        assert any(kw in vulns_text for kw in rc4_keywords), (
            "Must identify RC4 Kerberos encryption as a vulnerability"
        )

    def test_privilege_vulnerability_identified(self, results):
        """Must identify excessive service account privileges."""
        vulns_text = json.dumps(results["vulnerability_assessment"]).lower()
        priv_keywords = ["backup operator", "excessive privilege",
                         "overprivileged", "replication", "dcsync",
                         "svc_backup", "backup operators"]
        assert any(kw in vulns_text for kw in priv_keywords), (
            "Must identify excessive privileges on svc_backup"
        )

    def test_admin_protection_vulnerability(self, results):
        """Must identify lack of DA protection (Protected Users, tiered admin, etc.)."""
        vulns_text = json.dumps(results["vulnerability_assessment"]).lower()
        admin_keywords = ["protected users", "tiered admin", "privileged access",
                          "paw", "admin workstation", "da_johnson",
                          "logon restriction", "unrestricted"]
        assert any(kw in vulns_text for kw in admin_keywords), (
            "Must identify inadequate domain admin protection"
        )

    def test_high_severity_for_critical_issues(self, results):
        """LLMNR and privilege issues must be rated high or critical."""
        vulns = results["vulnerability_assessment"]
        high_or_critical_count = sum(
            1 for v in vulns
            if v.get("severity", "").lower() in ("high", "critical")
        )
        assert high_or_critical_count >= 3, (
            f"Only {high_or_critical_count} high/critical vulns "
            "(expect >= 3 for LLMNR, RC4, privilege, admin issues)"
        )


# ── Remediation Plan (Create) ─────────────────────────────


class TestRemediationPlan:
    def test_minimum_actions(self, results):
        plan = results["remediation_plan"]
        assert len(plan) >= 4, (
            f"Only {len(plan)} remediation actions (need >= 4)"
        )

    def test_plan_structure(self, results):
        for item in results["remediation_plan"]:
            assert "priority" in item, "Remediation item missing 'priority'"
            assert "action" in item, "Remediation item missing 'action'"
            assert "addresses" in item, "Remediation item missing 'addresses'"

    def test_llmnr_remediation_present(self, results):
        plan_text = json.dumps(results["remediation_plan"]).lower()
        llmnr_keywords = ["llmnr", "nbt-ns", "name resolution",
                          "multicast", "disable llmnr", "gpo"]
        assert any(kw in plan_text for kw in llmnr_keywords), (
            "Remediation plan must include disabling LLMNR/NBT-NS"
        )

    def test_credential_rotation_present(self, results):
        plan_text = json.dumps(results["remediation_plan"]).lower()
        cred_keywords = ["rotat", "reset password", "credential",
                         "change password", "password reset", "re-key"]
        assert any(kw in plan_text for kw in cred_keywords), (
            "Remediation plan must include credential rotation"
        )

    def test_service_account_hardening_present(self, results):
        plan_text = json.dumps(results["remediation_plan"]).lower()
        svc_keywords = ["gmsa", "managed service", "service account",
                        "spn", "kerberos encryption", "aes",
                        "remove rc4", "disable rc4"]
        assert any(kw in plan_text for kw in svc_keywords), (
            "Remediation plan must include service account hardening"
        )

    def test_addresses_multiple_vulns(self, results):
        """Plan items must collectively address at least 3 distinct vulnerability IDs."""
        all_addressed = set()
        for item in results["remediation_plan"]:
            for vid in item.get("addresses", []):
                all_addressed.add(vid)
        assert len(all_addressed) >= 3, (
            f"Plan addresses only {len(all_addressed)} distinct vulnerabilities "
            "(need >= 3)"
        )

    def test_dependency_awareness(self, results):
        """At least one remediation item should declare a dependency."""
        plan = results["remediation_plan"]
        has_deps = any(
            item.get("depends_on") and len(item["depends_on"]) > 0
            for item in plan
        )
        assert has_deps, (
            "Remediation plan must include at least one dependency "
            "(e.g., credential rotation depends on identifying all compromised accounts)"
        )


# ── Domain Admin ───────────────────────────────────────────


class TestDomainAdmin:
    def test_username(self, results):
        assert results["domain_admin"].get("username", "").lower() == "da_johnson"

    def test_password(self, results):
        assert results["domain_admin"].get("password") == "J0hn$on@dmin2024"

    def test_ntlm_format(self, results):
        h = results["domain_admin"].get("ntlm_hash", "")
        assert len(h) == 32 and all(c in "0123456789abcdef" for c in h.lower()), (
            f"ntlm_hash not 32-char hex: {h!r}"
        )

    def test_ntlm_matches_password(self, results):
        from Crypto.Hash import MD4

        pwd = results["domain_admin"]["password"]
        expected = MD4.new(pwd.encode("utf-16-le")).hexdigest()
        actual = results["domain_admin"]["ntlm_hash"].lower()
        assert actual == expected, "NTLM hash does not match password"


# ── Objective ──────────────────────────────────────────────


class TestObjective:
    def test_flag_present(self, results):
        assert EXPECTED_FLAG in results["objective"], "Flag not found in objective"

    def test_full_content(self, results):
        assert "AKIAIOSFODNN7EXAMPLE" in results["objective"], (
            "Objective content appears incomplete"
        )
