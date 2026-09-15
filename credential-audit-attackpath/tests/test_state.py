
import json
import os
import pytest

FINDINGS_PATH = "/app/report/findings.json"

EXPECTED_CREDENTIALS = {
    "j.smith": "Helpdesk#2024",
    "m.johnson": "Humanres#2024",
    "a.williams": "Developer!2024",
    "s.davis": "Database!2024",
    "r.brown": "Networkadmin!",
    "k.taylor": "Summer24!",
    "e.wilson": "Budget24$",
    "svc_backup": "Backup!2024",
    "svc_sql": "Sqlserver#2024",
    "svc_web": "Webapp24!",
    "admin.t": "Serveradmin#2024",
    "p.martinez": "Blueteam!2024",
    "d.anderson": "Linux2024!",
    "l.jackson": "executive$2024",
    "b.lee": "Welcome2024!",
}

EXPECTED_TOO_SHORT = {"k.taylor", "e.wilson", "svc_backup", "svc_web", "d.anderson"}
EXPECTED_NO_DIGIT = {"r.brown"}
EXPECTED_NO_UPPERCASE = {"l.jackson"}

# Accounts that must appear in attack_paths (have viable paths to DA)
MUST_HAVE_PATHS = {"admin.t", "r.brown", "svc_backup", "svc_sql"}

# Accounts with 1-step paths
ONE_STEP_ACCOUNTS = {"admin.t", "r.brown", "svc_backup", "svc_sql"}


@pytest.fixture
def findings():
    assert os.path.exists(FINDINGS_PATH), f"Findings file not found at {FINDINGS_PATH}"
    with open(FINDINGS_PATH) as f:
        data = json.load(f)
    return data


class TestCredentialCracking:
    def test_findings_file_exists(self):
        assert os.path.exists(FINDINGS_PATH), "findings.json must exist at /app/report/findings.json"

    def test_cracked_credentials_present(self, findings):
        assert "cracked_credentials" in findings, "findings must contain 'cracked_credentials'"
        creds = findings["cracked_credentials"]
        assert isinstance(creds, dict), "cracked_credentials must be a dict"

    def test_minimum_cracked_count(self, findings):
        creds = findings["cracked_credentials"]
        assert len(creds) >= 13, f"Expected at least 13 cracked credentials, got {len(creds)}"

    def test_cracked_passwords_correct(self, findings):
        creds = findings["cracked_credentials"]
        correct = 0
        wrong = []
        for user, expected_pwd in EXPECTED_CREDENTIALS.items():
            if user in creds:
                if creds[user] == expected_pwd:
                    correct += 1
                else:
                    wrong.append(f"{user}: got '{creds[user]}', expected '{expected_pwd}'")
            else:
                wrong.append(f"{user}: missing from cracked_credentials")
        assert correct >= 13, (
            f"At least 13 passwords must be correctly cracked. Got {correct}/15 correct. "
            f"Issues: {'; '.join(wrong[:5])}"
        )

    def test_total_cracked(self, findings):
        assert "total_cracked" in findings, "findings must contain 'total_cracked'"
        creds = findings["cracked_credentials"]
        assert findings["total_cracked"] == len(creds), (
            "total_cracked must match len(cracked_credentials)"
        )

    def test_no_admin_accounts_cracked(self, findings):
        creds = findings["cracked_credentials"]
        for acct in ["Administrator", "krbtgt", "da_admin"]:
            if acct in creds:
                assert False, f"Account '{acct}' should not be crackable with provided wordlists"


class TestPolicyViolations:
    def test_policy_violations_present(self, findings):
        assert "policy_violations" in findings, "findings must contain 'policy_violations'"
        pv = findings["policy_violations"]
        assert "too_short" in pv, "policy_violations must contain 'too_short'"
        assert "no_digit" in pv, "policy_violations must contain 'no_digit'"
        assert "no_uppercase" in pv, "policy_violations must contain 'no_uppercase'"

    def test_too_short_violations(self, findings):
        too_short = set(findings["policy_violations"]["too_short"])
        assert EXPECTED_TOO_SHORT.issubset(too_short), (
            f"Expected too_short to include {EXPECTED_TOO_SHORT}, got {too_short}. "
            f"Missing: {EXPECTED_TOO_SHORT - too_short}"
        )

    def test_no_digit_violations(self, findings):
        no_digit = set(findings["policy_violations"]["no_digit"])
        assert EXPECTED_NO_DIGIT.issubset(no_digit), (
            f"Expected no_digit to include {EXPECTED_NO_DIGIT}, got {no_digit}"
        )

    def test_no_uppercase_violations(self, findings):
        no_upper = set(findings["policy_violations"]["no_uppercase"])
        assert EXPECTED_NO_UPPERCASE.issubset(no_upper), (
            f"Expected no_uppercase to include {EXPECTED_NO_UPPERCASE}, got {no_upper}"
        )

    def test_total_policy_violations(self, findings):
        assert "total_policy_violations" in findings
        assert findings["total_policy_violations"] >= 7, (
            f"Expected at least 7 accounts with policy violations, got {findings['total_policy_violations']}"
        )


class TestAttackPaths:
    def test_attack_paths_present(self, findings):
        assert "attack_paths" in findings, "findings must contain 'attack_paths'"
        assert isinstance(findings["attack_paths"], list), "attack_paths must be a list"
        assert len(findings["attack_paths"]) >= 4, (
            f"Expected at least 4 attack paths, got {len(findings['attack_paths'])}"
        )

    def test_required_accounts_have_paths(self, findings):
        path_starts = {p["start_account"] for p in findings["attack_paths"]}
        missing = MUST_HAVE_PATHS - path_starts
        assert not missing, (
            f"Missing attack paths from required accounts: {missing}. "
            f"Found paths from: {path_starts}"
        )

    def test_one_step_paths_exist(self, findings):
        one_step = {
            p["start_account"]
            for p in findings["attack_paths"]
            if p.get("total_steps", len(p.get("path_steps", []))) == 1
        }
        expected_one_step = ONE_STEP_ACCOUNTS
        found = expected_one_step & one_step
        assert len(found) >= 3, (
            f"Expected at least 3 accounts with 1-step paths from {expected_one_step}, "
            f"found: {found}"
        )

    def test_attack_path_structure(self, findings):
        for path in findings["attack_paths"]:
            assert "start_account" in path, "Each attack path must have 'start_account'"
            assert "path_steps" in path, "Each attack path must have 'path_steps'"
            assert isinstance(path["path_steps"], list), "path_steps must be a list"
            for step in path["path_steps"]:
                assert "from" in step, "Each step must have 'from'"
                assert "to" in step, "Each step must have 'to'"
                assert "technique" in step, "Each step must have 'technique'"


class TestMostDangerousAccount:
    def test_most_dangerous_present(self, findings):
        assert "most_dangerous_account" in findings, (
            "findings must contain 'most_dangerous_account'"
        )

    def test_most_dangerous_is_svc_backup(self, findings):
        mda = findings["most_dangerous_account"]
        assert mda == "svc_backup", (
            f"Expected most_dangerous_account='svc_backup' (1-step path via "
            f"SeBackupPrivilege + too-short password), got '{mda}'"
        )


class TestRiskSummary:
    def test_risk_summary_present(self, findings):
        assert "risk_summary" in findings, "findings must contain 'risk_summary'"
        rs = findings["risk_summary"]
        assert "accounts_with_da_path" in rs
        assert "shortest_path_steps" in rs
        assert "critical_misconfigurations" in rs

    def test_shortest_path_is_one(self, findings):
        rs = findings["risk_summary"]
        assert rs["shortest_path_steps"] == 1, (
            f"Expected shortest_path_steps=1, got {rs['shortest_path_steps']}"
        )

    def test_accounts_with_da_path_count(self, findings):
        rs = findings["risk_summary"]
        assert rs["accounts_with_da_path"] >= 4, (
            f"Expected at least 4 accounts with DA paths, got {rs['accounts_with_da_path']}"
        )

    def test_critical_misconfigurations_mentioned(self, findings):
        rs = findings["risk_summary"]
        misconfigs = " ".join(rs["critical_misconfigurations"]).lower()
        assert "svc_web" in misconfigs or "genericall" in misconfigs or "server admins" in misconfigs, (
            "Critical misconfigurations should mention the svc_web GenericAll on Server Admins issue"
        )
