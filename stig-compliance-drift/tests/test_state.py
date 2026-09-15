"""Tests for STIG compliance validation framework.

Verifies that all 8 STIG controls are in a genuinely compliant state
after remediation, that a valid compliance validator was created, and
that a risk assessment was produced.

"""

import json
import os
import re
import subprocess


def _read_file(path):
    with open(path, "r") as f:
        return f.read()


def _get_all_ssh_config_text():
    """Concatenate drop-in configs then main config (SSH first-match order)."""
    parts = []
    dropin_dir = "/etc/ssh/sshd_config.d/"
    if os.path.isdir(dropin_dir):
        for fname in sorted(os.listdir(dropin_dir)):
            if fname.endswith(".conf"):
                parts.append(_read_file(os.path.join(dropin_dir, fname)))
    parts.append(_read_file("/etc/ssh/sshd_config"))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# STIG-SSH-001: PermitRootLogin must be effectively disabled
# ---------------------------------------------------------------------------

class TestSSHPermitRootLogin:

    def test_main_config_has_permit_root_login_no(self):
        content = _read_file("/etc/ssh/sshd_config")
        assert re.search(
            r"^\s*PermitRootLogin\s+no\s*$", content, re.MULTILINE
        ), "sshd_config must contain 'PermitRootLogin no'"

    def test_no_dropin_overrides_permit_root_login(self):
        dropin_dir = "/etc/ssh/sshd_config.d/"
        if not os.path.isdir(dropin_dir):
            return
        for fname in os.listdir(dropin_dir):
            if not fname.endswith(".conf"):
                continue
            fpath = os.path.join(dropin_dir, fname)
            content = _read_file(fpath)
            match = re.search(
                r"^\s*PermitRootLogin\s+(\S+)", content, re.MULTILINE
            )
            if match:
                val = match.group(1).lower()
                assert val == "no", (
                    f"Drop-in {fname} sets PermitRootLogin to '{match.group(1)}'; "
                    "must be 'no' or absent"
                )


# ---------------------------------------------------------------------------
# STIG-SSH-002: SSH idle timeout must be functional
# ---------------------------------------------------------------------------

class TestSSHClientAlive:

    def test_client_alive_interval_set(self):
        config = _get_all_ssh_config_text()
        match = re.search(
            r"^\s*ClientAliveInterval\s+(\d+)", config, re.MULTILINE
        )
        assert match, "ClientAliveInterval must be set"
        interval = int(match.group(1))
        assert 0 < interval <= 600, (
            f"ClientAliveInterval must be between 1 and 600, got {interval}"
        )

    def test_client_alive_count_max_nonzero(self):
        config = _get_all_ssh_config_text()
        match = re.search(
            r"^\s*ClientAliveCountMax\s+(\d+)", config, re.MULTILINE
        )
        assert match, "ClientAliveCountMax must be set"
        count = int(match.group(1))
        assert count > 0, (
            f"ClientAliveCountMax is {count}; a value of 0 disables client "
            "alive messages entirely, making ClientAliveInterval ineffective"
        )


# ---------------------------------------------------------------------------
# STIG-PAM-001: Account lockout deny <= 3
# ---------------------------------------------------------------------------

class TestPAMFaillock:

    def test_faillock_conf_deny(self):
        content = _read_file("/etc/security/faillock.conf")
        match = re.search(r"^\s*deny\s*=\s*(\d+)", content, re.MULTILINE)
        assert match, "faillock.conf must have a 'deny' setting"
        deny = int(match.group(1))
        assert 0 < deny <= 3, (
            f"faillock.conf deny must be 1-3, got {deny}"
        )

    def test_no_inline_deny_override_in_pam(self):
        content = _read_file("/etc/pam.d/common-auth")
        for lineno, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or "pam_faillock.so" not in stripped:
                continue
            match = re.search(r"\bdeny=(\d+)", line)
            if match:
                inline_deny = int(match.group(1))
                assert inline_deny <= 3, (
                    f"common-auth line {lineno}: inline deny={inline_deny} "
                    "overrides faillock.conf; must be <= 3 or removed"
                )


# ---------------------------------------------------------------------------
# STIG-PAM-002: Password minimum length >= 15
# ---------------------------------------------------------------------------

class TestPAMPwquality:

    def test_pwquality_conf_minlen(self):
        content = _read_file("/etc/security/pwquality.conf")
        match = re.search(r"^\s*minlen\s*=\s*(\d+)", content, re.MULTILINE)
        assert match, "pwquality.conf must have a 'minlen' setting"
        minlen = int(match.group(1))
        assert minlen >= 15, (
            f"pwquality.conf minlen must be >= 15, got {minlen}"
        )

    def test_no_inline_minlen_override_in_pam(self):
        content = _read_file("/etc/pam.d/common-password")
        for lineno, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or "pam_pwquality.so" not in stripped:
                continue
            match = re.search(r"\bminlen=(\d+)", line)
            if match:
                inline_minlen = int(match.group(1))
                assert inline_minlen >= 15, (
                    f"common-password line {lineno}: inline minlen={inline_minlen} "
                    "overrides pwquality.conf; must be >= 15 or removed"
                )


# ---------------------------------------------------------------------------
# STIG-AUDIT-001: max_log_file_action must not be IGNORE
# ---------------------------------------------------------------------------

class TestAuditdMaxAction:

    def test_max_log_file_action_acceptable(self):
        content = _read_file("/etc/audit/auditd.conf")
        match = re.search(
            r"^\s*max_log_file_action\s*=\s*(\S+)", content, re.MULTILINE
        )
        assert match, "auditd.conf must have 'max_log_file_action'"
        action = match.group(1).upper()
        acceptable = {"ROTATE", "SYSLOG", "HALT"}
        assert action in acceptable, (
            f"max_log_file_action is '{action}'; must be one of {acceptable}"
        )


# ---------------------------------------------------------------------------
# STIG-AUDIT-002: Audit rules must use auid>=1000 (not legacy 500)
# ---------------------------------------------------------------------------

class TestAuditRulesAuid:

    def test_no_legacy_auid_threshold(self):
        rules_dir = "/etc/audit/rules.d/"
        assert os.path.isdir(rules_dir), "Audit rules directory must exist"
        for fname in os.listdir(rules_dir):
            if not fname.endswith(".rules"):
                continue
            fpath = os.path.join(rules_dir, fname)
            content = _read_file(fpath)
            for lineno, line in enumerate(content.splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                for m in re.finditer(r"auid>=(\d+)", line):
                    uid = int(m.group(1))
                    assert uid >= 1000, (
                        f"{fname}:{lineno} uses auid>={uid}; modern Linux "
                        "requires auid>=1000"
                    )


# ---------------------------------------------------------------------------
# STIG-SESS-001: TMOUT must be effective (not overridden)
# ---------------------------------------------------------------------------

class TestTMOUT:

    def test_tmout_is_set(self):
        """TMOUT must be set in at least one profile script."""
        found = False
        for search_dir in ["/etc/profile.d"]:
            if not os.path.isdir(search_dir):
                continue
            for fname in sorted(os.listdir(search_dir)):
                if not fname.endswith(".sh"):
                    continue
                content = _read_file(os.path.join(search_dir, fname))
                if re.search(
                    r"^\s*(?:export\s+)?TMOUT=\d+", content, re.MULTILINE
                ):
                    found = True
                    break
        if not found:
            if os.path.isfile("/etc/profile"):
                content = _read_file("/etc/profile")
                if re.search(
                    r"^\s*(?:export\s+)?TMOUT=\d+", content, re.MULTILINE
                ):
                    found = True
        assert found, "TMOUT must be set in /etc/profile or /etc/profile.d/"

    def test_tmout_not_unset_by_later_script(self):
        """No profile script should unset or zero-out TMOUT."""
        profiled = "/etc/profile.d/"
        if not os.path.isdir(profiled):
            return
        for fname in os.listdir(profiled):
            if not fname.endswith(".sh"):
                continue
            fpath = os.path.join(profiled, fname)
            content = _read_file(fpath)
            for lineno, line in enumerate(content.splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                assert "unset TMOUT" not in line, (
                    f"{fname}:{lineno} unsets TMOUT, overriding session timeout"
                )
                if re.search(r"\bTMOUT\s*=\s*0\b", line):
                    assert False, (
                        f"{fname}:{lineno} sets TMOUT=0, disabling session timeout"
                    )


# ---------------------------------------------------------------------------
# STIG-KERN-001: kernel.randomize_va_space must be effectively 2
# ---------------------------------------------------------------------------

class TestKernelASLR:

    def test_sysctl_d_no_aslr_override(self):
        """No sysctl.d drop-in should set ASLR to anything other than 2."""
        sysctl_d = "/etc/sysctl.d/"
        if not os.path.isdir(sysctl_d):
            return
        for fname in os.listdir(sysctl_d):
            if not fname.endswith(".conf"):
                continue
            fpath = os.path.join(sysctl_d, fname)
            content = _read_file(fpath)
            match = re.search(
                r"^\s*kernel\.randomize_va_space\s*=\s*(\d+)",
                content,
                re.MULTILINE,
            )
            if match:
                val = int(match.group(1))
                assert val == 2, (
                    f"{fname} sets kernel.randomize_va_space={val}; must be 2"
                )

    def test_main_sysctl_aslr(self):
        """Main sysctl.conf must have ASLR enabled if it specifies it."""
        content = _read_file("/etc/sysctl.conf")
        match = re.search(
            r"^\s*kernel\.randomize_va_space\s*=\s*(\d+)",
            content,
            re.MULTILINE,
        )
        if match:
            val = int(match.group(1))
            assert val == 2, (
                f"sysctl.conf sets kernel.randomize_va_space={val}; must be 2"
            )


# ---------------------------------------------------------------------------
# Remediation report validation
# ---------------------------------------------------------------------------

class TestRemediationReport:

    EXPECTED_IDS = {
        "STIG-SSH-001",
        "STIG-SSH-002",
        "STIG-PAM-001",
        "STIG-PAM-002",
        "STIG-AUDIT-001",
        "STIG-AUDIT-002",
        "STIG-SESS-001",
        "STIG-KERN-001",
    }

    def test_report_exists(self):
        assert os.path.exists("/app/remediation_report.json"), (
            "Remediation report must be written to /app/remediation_report.json"
        )

    def test_report_is_valid_json_array(self):
        report = json.loads(_read_file("/app/remediation_report.json"))
        assert isinstance(report, list), "Report must be a JSON array"
        assert len(report) == 8, f"Report must have 8 entries, got {len(report)}"

    def test_report_covers_all_controls(self):
        report = json.loads(_read_file("/app/remediation_report.json"))
        actual_ids = {entry["id"] for entry in report}
        missing = self.EXPECTED_IDS - actual_ids
        assert not missing, f"Report missing controls: {missing}"

    def test_report_entry_structure(self):
        report = json.loads(_read_file("/app/remediation_report.json"))
        for entry in report:
            cid = entry.get("id", "<missing id>")
            assert "id" in entry, f"Entry missing 'id'"
            assert "root_cause" in entry, f"{cid}: missing 'root_cause'"
            assert "files_modified" in entry, f"{cid}: missing 'files_modified'"
            assert "fixed" in entry, f"{cid}: missing 'fixed'"

            assert entry["fixed"] is True, f"{cid}: must be marked as fixed"
            assert isinstance(entry["files_modified"], list), (
                f"{cid}: 'files_modified' must be a list"
            )
            assert len(entry["files_modified"]) > 0, (
                f"{cid}: 'files_modified' must not be empty"
            )
            assert len(entry["root_cause"]) >= 20, (
                f"{cid}: 'root_cause' must be descriptive (>= 20 chars)"
            )


# ---------------------------------------------------------------------------
# Compliance validator tests
# ---------------------------------------------------------------------------

class TestComplianceValidator:

    def _run_validator(self):
        return subprocess.run(
            ["python3", "/app/validator.py"],
            capture_output=True, text=True, timeout=30
        )

    def _read_results(self):
        return json.loads(_read_file("/app/validator_results.json"))

    def test_validator_exists(self):
        assert os.path.isfile("/app/validator.py"), (
            "Compliance validator must exist at /app/validator.py"
        )

    def test_validator_runs_successfully(self):
        result = self._run_validator()
        assert result.returncode == 0, (
            f"Validator returned exit code {result.returncode}: {result.stderr}"
        )

    def test_validator_output_exists(self):
        self._run_validator()
        assert os.path.isfile("/app/validator_results.json"), (
            "Validator must write results to /app/validator_results.json"
        )

    def test_validator_output_structure(self):
        self._run_validator()
        results = self._read_results()
        assert isinstance(results, list), "Results must be a JSON array"
        assert len(results) == 8, f"Expected 8 entries, got {len(results)}"

        expected_ids = {
            "STIG-SSH-001", "STIG-SSH-002", "STIG-PAM-001", "STIG-PAM-002",
            "STIG-AUDIT-001", "STIG-AUDIT-002", "STIG-SESS-001", "STIG-KERN-001",
        }
        actual_ids = {e["id"] for e in results}
        missing = expected_ids - actual_ids
        assert not missing, f"Missing control IDs in validator output: {missing}"

        for entry in results:
            cid = entry.get("id", "<missing>")
            assert "status" in entry, f"{cid}: missing 'status'"
            assert entry["status"] in ("PASS", "FAIL"), (
                f"{cid}: status must be PASS or FAIL, got '{entry['status']}'"
            )
            assert "effective_value" in entry, f"{cid}: missing 'effective_value'"
            assert "expected_value" in entry, f"{cid}: missing 'expected_value'"
            assert "explanation" in entry, f"{cid}: missing 'explanation'"
            assert len(str(entry["explanation"])) >= 30, (
                f"{cid}: explanation must be >= 30 chars"
            )

    def test_all_controls_pass_on_remediated_system(self):
        self._run_validator()
        results = self._read_results()
        for entry in results:
            assert entry["status"] == "PASS", (
                f"{entry['id']}: expected PASS but got FAIL -- "
                f"{entry.get('explanation', 'no explanation')}"
            )

    def test_detects_ssh_dropin_override(self):
        """Validator must detect a newly introduced SSH drop-in that
        overrides PermitRootLogin via Include first-match semantics."""
        defect_path = "/etc/ssh/sshd_config.d/00-test-defect.conf"
        try:
            with open(defect_path, "w") as f:
                f.write("PermitRootLogin yes\n")
            self._run_validator()
            results = self._read_results()
            ssh001 = next(e for e in results if e["id"] == "STIG-SSH-001")
            assert ssh001["status"] == "FAIL", (
                "Validator must detect that a new drop-in file in sshd_config.d/ "
                "overrides PermitRootLogin via SSH first-match semantics"
            )
        finally:
            if os.path.exists(defect_path):
                os.remove(defect_path)
            self._run_validator()

    def test_detects_sysctl_override(self):
        """Validator must detect a sysctl.d drop-in overriding ASLR
        via lexicographic precedence."""
        defect_path = "/etc/sysctl.d/zz-test-defect.conf"
        try:
            with open(defect_path, "w") as f:
                f.write("kernel.randomize_va_space = 0\n")
            self._run_validator()
            results = self._read_results()
            kern001 = next(e for e in results if e["id"] == "STIG-KERN-001")
            assert kern001["status"] == "FAIL", (
                "Validator must detect that a sysctl.d drop-in with higher "
                "lexicographic name overrides kernel.randomize_va_space"
            )
        finally:
            if os.path.exists(defect_path):
                os.remove(defect_path)
            self._run_validator()


# ---------------------------------------------------------------------------
# Risk assessment tests
# ---------------------------------------------------------------------------

class TestRiskAssessment:

    EXPECTED_IDS = {
        "STIG-SSH-001", "STIG-SSH-002", "STIG-PAM-001", "STIG-PAM-002",
        "STIG-AUDIT-001", "STIG-AUDIT-002", "STIG-SESS-001", "STIG-KERN-001",
    }

    def _load(self):
        return json.loads(_read_file("/app/risk_assessment.json"))

    def test_exists(self):
        assert os.path.isfile("/app/risk_assessment.json"), (
            "Risk assessment must exist at /app/risk_assessment.json"
        )

    def test_valid_json_array(self):
        data = self._load()
        assert isinstance(data, list), "Must be a JSON array"
        assert len(data) == 8, f"Expected 8 entries, got {len(data)}"

    def test_covers_all_controls(self):
        data = self._load()
        actual_ids = {e["id"] for e in data}
        missing = self.EXPECTED_IDS - actual_ids
        assert not missing, f"Missing controls in risk assessment: {missing}"

    def test_entry_structure(self):
        data = self._load()
        for entry in data:
            cid = entry.get("id", "<missing>")
            assert "severity_score" in entry, f"{cid}: missing severity_score"
            assert "attack_scenario" in entry, f"{cid}: missing attack_scenario"
            assert "cascading_impacts" in entry, f"{cid}: missing cascading_impacts"
            assert "remediation_priority" in entry, f"{cid}: missing remediation_priority"
            assert "justification" in entry, f"{cid}: missing justification"

    def test_severity_scores_valid(self):
        data = self._load()
        for entry in data:
            score = entry["severity_score"]
            assert isinstance(score, (int, float)), (
                f"{entry['id']}: severity_score must be numeric, got {type(score)}"
            )
            assert 1 <= score <= 10, (
                f"{entry['id']}: severity_score must be 1-10, got {score}"
            )

    def test_priorities_unique_and_complete(self):
        data = self._load()
        priorities = sorted([e["remediation_priority"] for e in data])
        assert priorities == list(range(1, 9)), (
            f"Priorities must be unique integers 1-8, got {priorities}"
        )

    def test_cat1_control_has_priority_one(self):
        """STIG-KERN-001 is the sole CAT I finding and must have priority 1."""
        data = self._load()
        kern = next(e for e in data if e["id"] == "STIG-KERN-001")
        assert kern["remediation_priority"] == 1, (
            f"STIG-KERN-001 (CAT I) must have remediation_priority 1, "
            f"got {kern['remediation_priority']}"
        )

    def test_highest_severity_has_priority_one(self):
        """The control with the highest severity score must have priority 1."""
        data = self._load()
        max_score = max(e["severity_score"] for e in data)
        top_entries = [e for e in data if e["severity_score"] == max_score]
        priorities_of_top = [e["remediation_priority"] for e in top_entries]
        assert 1 in priorities_of_top, (
            f"Control(s) with highest severity ({max_score}) must include "
            f"priority 1, but got priorities {priorities_of_top}"
        )

    def test_justifications_substantive(self):
        data = self._load()
        for entry in data:
            cid = entry["id"]
            assert len(str(entry["justification"])) >= 50, (
                f"{cid}: justification must be >= 50 chars"
            )
            assert len(str(entry["attack_scenario"])) >= 50, (
                f"{cid}: attack_scenario must be >= 50 chars"
            )

    def test_cascading_impacts_nonempty(self):
        data = self._load()
        for entry in data:
            cid = entry["id"]
            assert isinstance(entry["cascading_impacts"], list), (
                f"{cid}: cascading_impacts must be a list"
            )
            assert len(entry["cascading_impacts"]) >= 1, (
                f"{cid}: cascading_impacts must have at least one entry"
            )
