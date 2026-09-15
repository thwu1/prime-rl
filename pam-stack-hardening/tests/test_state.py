"""
PAM Breach Forensics and Remediation — Verification Tests

"""

import json
import subprocess
import re
import os
import time

import pytest


PAM_TEST_BIN = "/usr/local/bin/pam_test"
SERVICE = "test-auth"
ASSESSMENT_PATH = "/app/vulnerability_assessment.json"


def pam_auth(username, password):
    """Test PAM authentication using compiled C helper."""
    try:
        result = subprocess.run(
            [PAM_TEST_BIN, SERVICE, username, password],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def reset_faillock(username=None):
    """Reset faillock counters."""
    cmd = ["faillock", "--reset"]
    if username:
        cmd = ["faillock", "--user", username, "--reset"]
    subprocess.run(cmd, capture_output=True, timeout=5)


# ---------------------------------------------------------------------------
# Authentication bypass tests (functional)
# ---------------------------------------------------------------------------

class TestAuthenticationBypass:
    """Verify the authentication bypass vulnerability is fixed."""

    def setup_method(self):
        reset_faillock()

    def teardown_method(self):
        reset_faillock()

    def test_correct_password_admin1(self):
        assert pam_auth("admin1", "Admin1Pass"), \
            "admin1 should authenticate with correct password"

    def test_correct_password_dev1(self):
        assert pam_auth("dev1", "Dev1Pass"), \
            "dev1 should authenticate with correct password"

    def test_wrong_password_rejected(self):
        assert not pam_auth("admin1", "wrongpassword"), \
            "Wrong password must be rejected"

    def test_empty_password_rejected(self):
        assert not pam_auth("admin1", ""), \
            "Empty password must be rejected - auth bypass still present"

    def test_random_password_rejected(self):
        assert not pam_auth("dev1", "not_the_real_password"), \
            "Arbitrary password must be rejected"


# ---------------------------------------------------------------------------
# common-auth structure tests
# ---------------------------------------------------------------------------

class TestCommonAuthStructure:
    """Verify common-auth PAM stack is correctly structured."""

    def _read_active_lines(self, path):
        with open(path) as f:
            return [l.strip() for l in f
                    if l.strip() and not l.strip().startswith("#")]

    def test_no_pam_permit_sufficient_before_unix(self):
        lines = self._read_active_lines("/etc/pam.d/common-auth")
        for line in lines:
            if "pam_unix.so" in line:
                break
            if "pam_permit.so" in line:
                before_module = line.split("pam_permit.so")[0]
                assert "sufficient" not in before_module, \
                    "pam_permit.so must not be sufficient before pam_unix.so"

    def test_no_default_ignore_with_permit_fallback(self):
        lines = self._read_active_lines("/etc/pam.d/common-auth")
        unix_idx = None
        unix_has_default_ignore = False
        for i, line in enumerate(lines):
            if "pam_unix.so" in line:
                unix_idx = i
                unix_has_default_ignore = "default=ignore" in line
                break
        if unix_idx is not None and unix_has_default_ignore:
            for line in lines[unix_idx + 1:]:
                if "pam_permit.so" in line:
                    before = line.split("pam_permit.so")[0]
                    assert "sufficient" not in before, \
                        "pam_unix default=ignore + pam_permit sufficient = auth bypass"

    def test_pam_deny_present(self):
        with open("/etc/pam.d/common-auth") as f:
            content = f.read()
        assert "pam_deny.so" in content, \
            "pam_deny.so must be present in common-auth"


# ---------------------------------------------------------------------------
# Account lockout tests (pam_faillock)
# ---------------------------------------------------------------------------

class TestFaillock:
    """Verify account lockout is properly configured."""

    def setup_method(self):
        reset_faillock()

    def teardown_method(self):
        reset_faillock()

    def test_faillock_deny_nonzero(self):
        with open("/etc/security/faillock.conf") as f:
            content = f.read()
        match = re.search(r"^\s*deny\s*=\s*(\d+)", content, re.MULTILINE)
        assert match, "deny setting not found in faillock.conf"
        assert int(match.group(1)) > 0, f"deny must be > 0"

    def test_faillock_unlock_time_nonzero(self):
        with open("/etc/security/faillock.conf") as f:
            content = f.read()
        match = re.search(r"^\s*unlock_time\s*=\s*(\d+)", content, re.MULTILINE)
        assert match, "unlock_time setting not found in faillock.conf"
        assert int(match.group(1)) > 0, f"unlock_time must be > 0"

    def test_faillock_in_auth_stack(self):
        with open("/etc/pam.d/common-auth") as f:
            content = f.read()
        assert "pam_faillock.so" in content

    def test_faillock_preauth_in_auth(self):
        with open("/etc/pam.d/common-auth") as f:
            content = f.read()
        assert re.search(r"pam_faillock\.so.*preauth", content)

    def test_faillock_authfail_in_auth(self):
        with open("/etc/pam.d/common-auth") as f:
            content = f.read()
        assert re.search(r"pam_faillock\.so.*authfail", content)

    def test_faillock_in_account_stack(self):
        with open("/etc/pam.d/common-account") as f:
            content = f.read()
        assert "pam_faillock.so" in content

    def test_account_lockout_functional(self):
        reset_faillock("dev1")
        time.sleep(0.5)
        with open("/etc/security/faillock.conf") as f:
            content = f.read()
        match = re.search(r"^\s*deny\s*=\s*(\d+)", content, re.MULTILINE)
        deny = int(match.group(1)) if match else 5
        for _ in range(deny + 2):
            pam_auth("dev1", "wrongpassword")
            time.sleep(0.1)
        locked = not pam_auth("dev1", "Dev1Pass")
        reset_faillock("dev1")
        assert locked, f"Account must be locked after {deny} failed attempts"


# ---------------------------------------------------------------------------
# su restriction tests (pam_wheel)
# ---------------------------------------------------------------------------

class TestSuRestriction:
    """Verify su is restricted to wheel group members."""

    def test_pam_wheel_in_su(self):
        with open("/etc/pam.d/su") as f:
            content = f.read()
        found = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "pam_wheel.so" in stripped and "auth" in stripped:
                ctrl = stripped.split("pam_wheel.so")[0]
                if "required" in ctrl or "requisite" in ctrl:
                    found = True
                    break
        assert found, "pam_wheel.so must be required/requisite in su auth stack"

    def test_pam_wheel_use_uid(self):
        with open("/etc/pam.d/su") as f:
            content = f.read()
        for line in content.split("\n"):
            if "pam_wheel.so" in line and not line.strip().startswith("#"):
                assert "use_uid" in line, "pam_wheel.so must have use_uid option"
                return
        pytest.fail("pam_wheel.so not found in su config")


# ---------------------------------------------------------------------------
# Access control tests (pam_access)
# ---------------------------------------------------------------------------

class TestAccessControl:
    """Verify access control configuration."""

    def test_pam_access_in_account_stack(self):
        with open("/etc/pam.d/common-account") as f:
            content = f.read()
        assert "pam_access.so" in content

    def test_access_conf_has_deny_rules(self):
        with open("/etc/security/access.conf") as f:
            lines = [l.strip() for l in f
                     if l.strip() and not l.strip().startswith("#")]
        assert any(l.startswith("-") for l in lines), \
            "access.conf must have deny rules"

    def test_restricted_group_denied(self):
        with open("/etc/security/access.conf") as f:
            content = f.read()
        non_comment = [l for l in content.split("\n")
                       if l.strip() and not l.strip().startswith("#")]
        assert any(l.strip().startswith("-") and "restricted" in l
                   for l in non_comment), \
            "access.conf must deny the restricted group from non-LOCAL origins"

    def test_svcaccounts_denied(self):
        with open("/etc/security/access.conf") as f:
            content = f.read()
        non_comment = [l for l in content.split("\n")
                       if l.strip() and not l.strip().startswith("#")]
        assert any(l.strip().startswith("-") and "svcaccount" in l
                   for l in non_comment), \
            "access.conf must deny svcaccounts group"


# ---------------------------------------------------------------------------
# Password quality tests (pam_pwquality)
# ---------------------------------------------------------------------------

class TestPasswordQuality:

    def test_pwquality_minlen(self):
        with open("/etc/security/pwquality.conf") as f:
            content = f.read()
        match = re.search(r"^\s*minlen\s*=\s*(\d+)", content, re.MULTILINE)
        assert match, "minlen not found in pwquality.conf"
        assert int(match.group(1)) >= 12

    def test_pwquality_character_classes(self):
        with open("/etc/security/pwquality.conf") as f:
            content = f.read()
        minclass_match = re.search(
            r"^\s*minclass\s*=\s*(\d+)", content, re.MULTILINE)
        has_all_credits = all(
            re.search(rf"^\s*{c}credit\s*=\s*-\d+", content, re.MULTILINE)
            for c in ["d", "u", "l", "o"]
        )
        ok = has_all_credits
        if minclass_match:
            ok = ok or int(minclass_match.group(1)) >= 4
        assert ok, "Must require 4 character classes"

    def test_pwquality_in_password_stack(self):
        with open("/etc/pam.d/common-password") as f:
            content = f.read()
        assert "pam_pwquality.so" in content


# ---------------------------------------------------------------------------
# Resource limits tests (pam_limits)
# ---------------------------------------------------------------------------

class TestResourceLimits:

    def test_limits_has_entries(self):
        with open("/etc/security/limits.conf") as f:
            lines = [l.strip() for l in f
                     if l.strip() and not l.strip().startswith("#")]
        assert len(lines) > 0

    def test_limits_has_nproc(self):
        with open("/etc/security/limits.conf") as f:
            content = f.read()
        non_comment = [l for l in content.split("\n")
                       if l.strip() and not l.strip().startswith("#")]
        assert any("nproc" in l for l in non_comment)

    def test_limits_has_nofile(self):
        with open("/etc/security/limits.conf") as f:
            content = f.read()
        non_comment = [l for l in content.split("\n")
                       if l.strip() and not l.strip().startswith("#")]
        assert any("nofile" in l for l in non_comment)

    def test_pam_limits_in_session_stack(self):
        with open("/etc/pam.d/common-session") as f:
            content = f.read()
        assert "pam_limits.so" in content

    def test_admin_group_limits(self):
        with open("/etc/security/limits.conf") as f:
            content = f.read()
        non_comment = [l for l in content.split("\n")
                       if l.strip() and not l.strip().startswith("#")]
        assert any("admin" in l.lower() for l in non_comment)


# ---------------------------------------------------------------------------
# Vulnerability assessment tests
# ---------------------------------------------------------------------------

class TestVulnerabilityAssessment:
    """Verify the vulnerability assessment is correct and complete."""

    def _load(self):
        with open(ASSESSMENT_PATH) as f:
            return json.load(f)

    def test_assessment_file_exists(self):
        assert os.path.exists(ASSESSMENT_PATH), \
            "vulnerability_assessment.json not found at /app/"

    def test_assessment_valid_json(self):
        data = self._load()
        assert isinstance(data, dict)

    def test_has_required_top_level_fields(self):
        data = self._load()
        for field in ("vulnerabilities", "attack_chain", "overall_risk_rating"):
            assert field in data, f"Missing top-level field: {field}"

    def test_minimum_vulnerability_count(self):
        data = self._load()
        assert len(data["vulnerabilities"]) >= 5, \
            f"Expected >= 5 vulnerabilities, found {len(data['vulnerabilities'])}"

    def test_vulnerability_required_fields(self):
        data = self._load()
        required = {"id", "title", "affected_file", "severity", "exploited_in_breach"}
        for vuln in data["vulnerabilities"]:
            missing = required - set(vuln.keys())
            assert not missing, \
                f"Vulnerability {vuln.get('id', '?')} missing: {missing}"

    def test_valid_severity_values(self):
        data = self._load()
        valid = {"critical", "high", "medium", "low"}
        for vuln in data["vulnerabilities"]:
            assert vuln["severity"] in valid, \
                f"Invalid severity '{vuln['severity']}' for {vuln['id']}"

    def test_auth_bypass_identified_critical_exploited(self):
        """The auth bypass in common-auth must be identified as critical and exploited."""
        data = self._load()
        auth_vulns = [
            v for v in data["vulnerabilities"]
            if "common-auth" in v.get("affected_file", "")
            and v.get("exploited_in_breach") is True
        ]
        assert len(auth_vulns) >= 1, \
            "Must identify an exploited vulnerability in common-auth"
        assert any(v["severity"] == "critical" for v in auth_vulns), \
            "Auth bypass in common-auth must be rated critical"

    def test_lockout_failure_identified_as_exploited(self):
        """Account lockout failure must be identified as exploited."""
        data = self._load()
        lockout_vulns = [
            v for v in data["vulnerabilities"]
            if v.get("exploited_in_breach") is True
            and (
                "faillock" in v.get("affected_file", "").lower()
                or "faillock" in v.get("title", "").lower()
                or "lockout" in v.get("title", "").lower()
                or "brute" in v.get("title", "").lower()
                or "lock" in v.get("id", "").lower()
                or "brute" in v.get("id", "").lower()
                or "faillock" in v.get("id", "").lower()
                or (v.get("affected_file", "") == "/etc/security/faillock.conf")
            )
        ]
        assert len(lockout_vulns) >= 1, \
            "Must identify account lockout failure as exploited"

    def test_su_unrestricted_identified_critical_exploited(self):
        """Unrestricted su must be identified as critical and exploited."""
        data = self._load()
        su_vulns = [
            v for v in data["vulnerabilities"]
            if v.get("exploited_in_breach") is True
            and (
                "/etc/pam.d/su" in v.get("affected_file", "")
                or "su" == os.path.basename(v.get("affected_file", ""))
                or "privilege" in v.get("title", "").lower()
                or "escalat" in v.get("title", "").lower()
                or "wheel" in v.get("title", "").lower()
            )
        ]
        assert len(su_vulns) >= 1, \
            "Must identify unrestricted su as exploited"
        assert any(v["severity"] == "critical" for v in su_vulns), \
            "Unrestricted su must be rated critical"

    def test_access_control_identified_as_exploited(self):
        """Permissive access control must be identified as exploited."""
        data = self._load()
        access_vulns = [
            v for v in data["vulnerabilities"]
            if v.get("exploited_in_breach") is True
            and (
                "access" in v.get("affected_file", "").lower()
                or "access" in v.get("title", "").lower()
                or "svcaccount" in v.get("title", "").lower()
                or "service" in v.get("title", "").lower()
            )
        ]
        assert len(access_vulns) >= 1, \
            "Must identify permissive access control as exploited"

    def test_has_latent_vulnerabilities(self):
        """Must identify at least one non-exploited (latent) vulnerability."""
        data = self._load()
        latent = [v for v in data["vulnerabilities"]
                  if v.get("exploited_in_breach") is False]
        assert len(latent) >= 1, \
            "Must identify at least one latent (non-exploited) vulnerability"

    def test_attack_chain_minimum_length(self):
        data = self._load()
        assert len(data["attack_chain"]) >= 2, \
            "Attack chain must have at least 2 steps"

    def test_attack_chain_references_valid_vulns(self):
        data = self._load()
        vuln_ids = {v["id"] for v in data["vulnerabilities"]}
        for chain_id in data["attack_chain"]:
            assert chain_id in vuln_ids, \
                f"Attack chain references unknown vulnerability: {chain_id}"

    def test_attack_chain_entries_are_exploited(self):
        data = self._load()
        vuln_map = {v["id"]: v for v in data["vulnerabilities"]}
        for chain_id in data["attack_chain"]:
            vuln = vuln_map.get(chain_id)
            assert vuln and vuln.get("exploited_in_breach") is True, \
                f"Attack chain entry {chain_id} must be marked exploited"

    def test_attack_chain_includes_auth_bypass(self):
        data = self._load()
        vuln_map = {v["id"]: v for v in data["vulnerabilities"]}
        chain_vulns = [vuln_map[cid] for cid in data["attack_chain"]
                       if cid in vuln_map]
        has_auth = any(
            "common-auth" in v.get("affected_file", "")
            for v in chain_vulns
        )
        assert has_auth, "Attack chain must include the authentication bypass"

    def test_attack_chain_includes_privilege_escalation(self):
        data = self._load()
        vuln_map = {v["id"]: v for v in data["vulnerabilities"]}
        chain_vulns = [vuln_map[cid] for cid in data["attack_chain"]
                       if cid in vuln_map]
        has_priv_esc = any(
            "/etc/pam.d/su" in v.get("affected_file", "")
            or "su" == os.path.basename(v.get("affected_file", ""))
            or "privilege" in v.get("title", "").lower()
            or "escalat" in v.get("title", "").lower()
            for v in chain_vulns
        )
        assert has_priv_esc, \
            "Attack chain must include privilege escalation step"

    def test_attack_chain_ordering(self):
        """Auth bypass must precede privilege escalation in the chain."""
        data = self._load()
        vuln_map = {v["id"]: v for v in data["vulnerabilities"]}

        auth_idx = None
        priv_idx = None

        for i, cid in enumerate(data["attack_chain"]):
            v = vuln_map.get(cid, {})
            if "common-auth" in v.get("affected_file", ""):
                if auth_idx is None:
                    auth_idx = i
            if ("/etc/pam.d/su" in v.get("affected_file", "")
                    or "su" == os.path.basename(v.get("affected_file", ""))
                    or "privilege" in v.get("title", "").lower()
                    or "escalat" in v.get("title", "").lower()):
                priv_idx = i

        if auth_idx is not None and priv_idx is not None:
            assert auth_idx < priv_idx, \
                "Auth bypass must precede privilege escalation in attack chain"

    def test_overall_risk_rating_critical(self):
        data = self._load()
        assert data["overall_risk_rating"] == "critical", \
            f"Overall risk must be 'critical', got '{data.get('overall_risk_rating')}'"
