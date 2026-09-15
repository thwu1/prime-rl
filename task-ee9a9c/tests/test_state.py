
"""
Verification tests for the credential forensics audit task.
Validates cracked credentials, pattern inference, identity mapping,
cross-system reuse analysis, and flag recovery.
"""

import json
import os
import pytest

REPORT_PATH = "/app/results/report.json"

# -- Expected values --

EXPECTED_CREDENTIALS = {
    "linux:svc_backup": "Backup2024!",
    "linux:admin_web": "Webmaster2024#",
    "linux:dev_ops": "Pipeline2024!",
    "linux:jorge.m": "Backup2024!",
    "linux:tina.c": "Pipeline2024!",
    "domain:j.martinez": "Backup2024!",
    "domain:svc_sql": "Database2024!",
    "domain:admin.dc": "Control2024#",
    "domain:k.wilson": "Winter2024!",
    "domain:t.chen": "Pipeline2024!",
    "webapp:jmartinez": "Backup2024!",
    "webapp:kwilson": "Security2023@",
    "webapp:tchen": "Pipeline2024!",
    "webapp:webapp_admin": "Fortress2023@",
}

EXPECTED_PATTERN_YEARS = {"2023", "2024"}
EXPECTED_PATTERN_SYMBOLS = {"!", "#", "@"}

EXPECTED_IDENTITY_GROUPS = {
    "jorge martinez": {"linux:jorge.m", "domain:j.martinez", "webapp:jmartinez"},
    "tina chen": {"linux:tina.c", "domain:t.chen", "webapp:tchen"},
    "kyle wilson": {"domain:k.wilson", "webapp:kwilson"},
}

EXPECTED_REUSE = {
    "Backup2024!": {"linux:svc_backup", "linux:jorge.m", "domain:j.martinez", "webapp:jmartinez"},
    "Pipeline2024!": {"linux:dev_ops", "linux:tina.c", "domain:t.chen", "webapp:tchen"},
}

EXPECTED_FLAG = "FLAG-7b2c9f4e8a1d3c5b6e0f2a4d8c1b3e5a"


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# =============================================
# Report Structure
# =============================================

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), "Report not found at /app/results/report.json"

    def test_report_valid_json(self):
        data = load_report()
        assert isinstance(data, dict)

    def test_report_has_required_keys(self):
        data = load_report()
        required = {"cracked_credentials", "password_pattern", "identity_groups",
                     "cross_system_reuse", "decrypted_flag"}
        missing = required - set(data.keys())
        assert not missing, f"Missing keys: {missing}"


# =============================================
# Cracked Credentials (14 accounts, 3 systems)
# =============================================

class TestCrackedCredentials:
    def test_credential_count(self):
        data = load_report()
        creds = data.get("cracked_credentials", {})
        assert len(creds) >= len(EXPECTED_CREDENTIALS), (
            f"Expected at least {len(EXPECTED_CREDENTIALS)} credentials, got {len(creds)}"
        )

    @pytest.mark.parametrize("account,password", list(EXPECTED_CREDENTIALS.items()))
    def test_credential(self, account, password):
        data = load_report()
        creds = data.get("cracked_credentials", {})
        assert account in creds, f"Missing credential: {account}"
        assert creds[account] == password, (
            f"Wrong password for {account}: expected {password}, got {creds[account]}"
        )


# =============================================
# Password Pattern Inference
# =============================================

class TestPasswordPattern:
    def test_pattern_has_years(self):
        data = load_report()
        pattern = data.get("password_pattern", {})
        assert "years" in pattern, "Missing 'years' in password_pattern"

    def test_pattern_years_correct(self):
        data = load_report()
        years = set(data["password_pattern"].get("years", []))
        assert EXPECTED_PATTERN_YEARS.issubset(years), (
            f"Pattern years must include {EXPECTED_PATTERN_YEARS}, got {years}"
        )

    def test_pattern_has_symbols(self):
        data = load_report()
        pattern = data.get("password_pattern", {})
        assert "symbols" in pattern, "Missing 'symbols' in password_pattern"

    def test_pattern_symbols_correct(self):
        data = load_report()
        symbols = set(data["password_pattern"].get("symbols", []))
        assert EXPECTED_PATTERN_SYMBOLS.issubset(symbols), (
            f"Pattern symbols must include {EXPECTED_PATTERN_SYMBOLS}, got {symbols}"
        )

    def test_pattern_has_description(self):
        data = load_report()
        desc = data.get("password_pattern", {}).get("description", "")
        assert len(desc) > 10, "Pattern description is missing or too short"


# =============================================
# Identity Groups (3 named personnel)
# =============================================

class TestIdentityGroups:
    def test_identity_group_count(self):
        data = load_report()
        groups = data.get("identity_groups", [])
        assert len(groups) >= len(EXPECTED_IDENTITY_GROUPS), (
            f"Expected at least {len(EXPECTED_IDENTITY_GROUPS)} identity groups, got {len(groups)}"
        )

    def _find_group_by_name(self, groups, target_name):
        target_lower = target_name.lower()
        for g in groups:
            if g.get("person", "").lower() == target_lower:
                return g
        return None

    @pytest.mark.parametrize("person_name,expected_accounts",
                             list(EXPECTED_IDENTITY_GROUPS.items()))
    def test_identity_group(self, person_name, expected_accounts):
        data = load_report()
        groups = data.get("identity_groups", [])
        group = self._find_group_by_name(groups, person_name)
        assert group is not None, (
            f"Missing identity group for: {person_name}"
        )
        reported = set(group.get("accounts", []))
        assert expected_accounts == reported, (
            f"Wrong accounts for {person_name}: expected {expected_accounts}, got {reported}"
        )


# =============================================
# Cross-System Password Reuse
# =============================================

class TestCrossSystemReuse:
    def test_reuse_count(self):
        data = load_report()
        reuse = data.get("cross_system_reuse", [])
        assert len(reuse) >= len(EXPECTED_REUSE), (
            f"Expected at least {len(EXPECTED_REUSE)} reuse entries, got {len(reuse)}"
        )

    def _find_reuse_by_password(self, reuse_list, password):
        for entry in reuse_list:
            if entry.get("password") == password:
                return entry
        return None

    @pytest.mark.parametrize("password,expected_accounts",
                             list(EXPECTED_REUSE.items()))
    def test_reuse_entry(self, password, expected_accounts):
        data = load_report()
        reuse = data.get("cross_system_reuse", [])
        entry = self._find_reuse_by_password(reuse, password)
        assert entry is not None, f"Missing reuse entry for password: {password}"
        reported = set(entry.get("accounts", []))
        assert expected_accounts == reported, (
            f"Wrong accounts for {password} reuse: expected {expected_accounts}, got {reported}"
        )

    @pytest.mark.parametrize("password", list(EXPECTED_REUSE.keys()))
    def test_reuse_risk_level_critical(self, password):
        data = load_report()
        reuse = data.get("cross_system_reuse", [])
        entry = self._find_reuse_by_password(reuse, password)
        assert entry is not None, f"Missing reuse entry for: {password}"
        assert entry.get("risk_level") == "critical", (
            f"Expected critical risk for {password}, got {entry.get('risk_level')}"
        )


# =============================================
# Decrypted Flag
# =============================================

class TestDecryptedFlag:
    def test_flag_present(self):
        data = load_report()
        assert "decrypted_flag" in data, "Missing decrypted_flag in report"

    def test_flag_correct(self):
        data = load_report()
        assert data.get("decrypted_flag") == EXPECTED_FLAG, (
            f"Wrong flag: expected {EXPECTED_FLAG}, got {data.get('decrypted_flag')}"
        )
