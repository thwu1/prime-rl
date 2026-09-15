
"""Tests verifying correctness of AD threat evaluation answers."""

import json
import os
import sqlite3
import subprocess
import pytest


DB_PATH = "/app/ad_data/environment.db"


def load_answers():
    """Load the agent's answers from /app/answers.json."""
    answers_path = "/app/answers.json"
    assert os.path.exists(answers_path), (
        f"answers.json not found at {answers_path}"
    )
    with open(answers_path) as f:
        answers = json.load(f)
    return answers


def load_nodes():
    """Load node data from SQLite for cross-reference validation."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    nodes = []
    for row in c.execute('SELECT id, type, name, domain, properties FROM nodes'):
        nodes.append({
            "id": row[0], "type": row[1], "name": row[2],
            "domain": row[3], "properties": json.loads(row[4])
        })
    conn.close()
    return nodes


def load_edges():
    """Load edge data from SQLite for cross-reference validation."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    edges = []
    for row in c.execute('SELECT source, target, type, properties FROM edges'):
        edges.append({
            "source": row[0], "target": row[1],
            "type": row[2], "properties": json.loads(row[3])
        })
    conn.close()
    return edges


class TestAnswersStructure:
    """Verify answers.json has required structure."""

    def test_answers_file_exists(self):
        answers = load_answers()
        assert isinstance(answers, dict)

    def test_all_keys_present(self):
        answers = load_answers()
        required = {
            "shortest_attack_path",
            "kerberoastable_targets",
            "certificate_impersonation_templates",
            "sql_link_chain",
            "exploitable_delegation",
            "what_if_analysis",
            "most_effective_mitigation",
        }
        assert required.issubset(set(answers.keys())), (
            f"Missing keys: {required - set(answers.keys())}"
        )

    def test_answer_types(self):
        answers = load_answers()
        assert isinstance(answers["shortest_attack_path"], list)
        assert isinstance(answers["kerberoastable_targets"], list)
        assert isinstance(answers["certificate_impersonation_templates"], list)
        assert isinstance(answers["sql_link_chain"], list)
        assert isinstance(answers["exploitable_delegation"], dict)
        assert isinstance(answers["what_if_analysis"], dict)
        assert isinstance(answers["most_effective_mitigation"], str)


class TestShortestAttackPath:
    """Verify the shortest attack path answer."""

    def test_path_starts_with_helpdesk(self):
        answers = load_answers()
        path = answers["shortest_attack_path"]
        assert len(path) > 0
        assert path[0] == "svc_helpdesk@corp.local", (
            f"Path must start with svc_helpdesk@corp.local, got {path[0]}"
        )

    def test_path_ends_with_da_secure(self):
        answers = load_answers()
        path = answers["shortest_attack_path"]
        assert path[-1] == "Domain Admins@secure.local", (
            f"Path must end with Domain Admins@secure.local, got {path[-1]}"
        )

    def test_path_includes_cert_template(self):
        """The shortest path uses certificate impersonation via AdminWorkstation."""
        answers = load_answers()
        path = answers["shortest_attack_path"]
        assert "AdminWorkstation@corp.local" in path, (
            "Shortest path must exploit certificate impersonation via "
            "AdminWorkstation@corp.local template"
        )

    def test_path_includes_sql_chain_in_order(self):
        """Path must traverse SQL link chain in correct order."""
        answers = load_answers()
        path = answers["shortest_attack_path"]
        sql_servers = [
            "SQLSRV01.corp.local",
            "SQLSRV02.partner.local",
            "SQLSRV03.secure.local",
        ]
        for srv in sql_servers:
            assert srv in path, f"Path must include SQL server {srv}"

        indices = [path.index(s) for s in sql_servers]
        assert indices == sorted(indices), (
            "SQL servers must appear in order: "
            "SQLSRV01 -> SQLSRV02 -> SQLSRV03"
        )

    def test_path_length_optimal(self):
        """Certificate impersonation path should be <=10 steps (optimal is 8)."""
        answers = load_answers()
        path = answers["shortest_attack_path"]
        assert len(path) <= 10, (
            f"Path has {len(path)} steps; optimal path is 8 steps"
        )

    def test_path_excludes_disabled_accounts(self):
        """Disabled accounts must not appear in the path."""
        answers = load_answers()
        path = answers["shortest_attack_path"]
        assert "svc_monitor@corp.local" not in path, (
            "svc_monitor is disabled and cannot be part of the attack path"
        )

    def test_path_avoids_protected_users_for_credential_attacks(self):
        """Protected Users members cannot be used for delegation/cred attacks."""
        answers = load_answers()
        path = answers["shortest_attack_path"]
        assert "svc_deploy@corp.local" not in path, (
            "svc_deploy is in Protected Users group and cannot be leveraged "
            "for credential-based attacks"
        )

    def test_path_includes_admin_jones(self):
        """Certificate impersonation target should be admin_jones (DA)."""
        answers = load_answers()
        path = answers["shortest_attack_path"]
        assert "admin_jones@corp.local" in path, (
            "Certificate impersonation should target admin_jones@corp.local "
            "who is Domain Admin"
        )

    def test_path_includes_svc_sql(self):
        """Path should reach svc_sql@secure.local (DA via xp_cmdshell)."""
        answers = load_answers()
        path = answers["shortest_attack_path"]
        assert "svc_sql@secure.local" in path, (
            "Attack path should reach svc_sql@secure.local via SQL link "
            "chain xp_cmdshell execution"
        )


class TestKerberoastableTargets:
    """Verify Kerberoastable targets identification."""

    def test_svc_backup_included(self):
        """svc_backup has SPN, weak password, and path to DA via LAPS."""
        answers = load_answers()
        targets = answers["kerberoastable_targets"]
        assert "svc_backup@corp.local" in targets, (
            "svc_backup@corp.local has SPN, weak password, and path to DA "
            "via Backup-Operators -> ReadLAPSPassword -> WEB01 -> "
            "admin_jones session"
        )

    def test_svc_sqlcorp_included(self):
        """svc_sqlcorp has SPN, medium password, and sysadmin on SQLSRV01."""
        answers = load_answers()
        targets = answers["kerberoastable_targets"]
        assert "svc_sqlcorp@corp.local" in targets, (
            "svc_sqlcorp@corp.local has SPN, medium password, and is "
            "sysadmin on SQLSRV01 with path to DA@secure.local via "
            "SQL link chain"
        )

    def test_strong_password_excluded(self):
        """Accounts with strong passwords must be excluded."""
        answers = load_answers()
        targets = set(answers["kerberoastable_targets"])
        strong_pw = {"svc_print@corp.local", "svc_sql@secure.local",
                     "p_svc_sql@partner.local", "svc_audit@secure.local"}
        overlap = targets & strong_pw
        assert len(overlap) == 0, (
            f"Accounts with strong passwords should be excluded: {overlap}"
        )

    def test_all_entries_valid(self):
        """All listed targets must have has_spn=true and weak/medium password."""
        answers = load_answers()
        targets = answers["kerberoastable_targets"]
        nodes = load_nodes()
        user_map = {n["name"]: n for n in nodes if n["type"] == "User"}

        for t in targets:
            assert t in user_map, f"Unknown user in kerberoastable_targets: {t}"
            props = user_map[t]["properties"]
            assert props["has_spn"] is True, (
                f"{t} does not have SPN set (has_spn={props['has_spn']})"
            )
            assert props["password_strength"] != "strong", (
                f"{t} has strong password and should be excluded"
            )
            assert props["enabled"] is True, (
                f"{t} is disabled and should be excluded"
            )

    def test_sorted_alphabetically(self):
        """Targets must be sorted alphabetically."""
        answers = load_answers()
        targets = answers["kerberoastable_targets"]
        assert targets == sorted(targets), "kerberoastable_targets must be sorted"


class TestCertImpersonationTemplates:
    """Verify certificate impersonation template identification."""

    def test_adminworkstation_identified(self):
        """AdminWorkstation meets all ESC1 criteria from LDIF analysis."""
        answers = load_answers()
        templates = answers["certificate_impersonation_templates"]
        assert "AdminWorkstation@corp.local" in templates, (
            "AdminWorkstation@corp.local allows identity impersonation: "
            "msPKI-Certificate-Name-Flag bit 0 set (ESS), Client Auth EKU, "
            "no manager approval (PEND_ALL_REQUESTS not set), "
            "msPKI-RA-Signature=0, IT-Support (non-admin) can enroll"
        )

    def test_uservpn_excluded(self):
        """UserVPN has CT_FLAG_PEND_ALL_REQUESTS set - not exploitable."""
        answers = load_answers()
        templates = answers["certificate_impersonation_templates"]
        assert "UserVPN@corp.local" not in templates, (
            "UserVPN has msPKI-Enrollment-Flag=66 (bit 1 set = "
            "CT_FLAG_PEND_ALL_REQUESTS) requiring manager approval"
        )

    def test_webserver_excluded(self):
        """WebServer has only Server Auth EKU - not usable for AD auth."""
        answers = load_answers()
        templates = answers["certificate_impersonation_templates"]
        assert "WebServer@corp.local" not in templates, (
            "WebServer only has pKIExtendedKeyUsage 1.3.6.1.5.5.7.3.1 "
            "(Server Authentication), not Client Authentication"
        )

    def test_smartcard_excluded(self):
        """SmartcardUser has CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT not set."""
        answers = load_answers()
        templates = answers["certificate_impersonation_templates"]
        assert "SmartcardUser@corp.local" not in templates, (
            "SmartcardUser has msPKI-Certificate-Name-Flag=256 (0x100): "
            "bit 0 is NOT set, so CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT is false. "
            "Bit 8 (CT_FLAG_OLD_CERT_SUPPLIES) is set but is a different flag"
        )

    def test_codesigning_excluded(self):
        """CodeSigning has msPKI-RA-Signature=1."""
        answers = load_answers()
        templates = answers["certificate_impersonation_templates"]
        assert "CodeSigning@corp.local" not in templates, (
            "CodeSigning has msPKI-RA-Signature=1 requiring 1 authorized "
            "signature"
        )

    def test_webauth_excluded(self):
        """WebAuthentication requires 2 authorized signatures."""
        answers = load_answers()
        templates = answers["certificate_impersonation_templates"]
        assert "WebAuthentication@corp.local" not in templates, (
            "WebAuthentication has msPKI-RA-Signature=2 requiring 2 "
            "authorized signatures"
        )

    def test_exactly_one_template(self):
        """Only AdminWorkstation should be identified as exploitable."""
        answers = load_answers()
        templates = answers["certificate_impersonation_templates"]
        assert templates == ["AdminWorkstation@corp.local"], (
            f"Expected exactly ['AdminWorkstation@corp.local'], got {templates}"
        )


class TestSQLLinkChain:
    """Verify SQL Server link chain identification."""

    def test_chain_correct(self):
        """Link chain from corp.local to secure.local."""
        answers = load_answers()
        chain = answers["sql_link_chain"]
        expected = [
            "SQLSRV01.corp.local",
            "SQLSRV02.partner.local",
            "SQLSRV03.secure.local",
        ]
        assert chain == expected, (
            f"SQL link chain should be {expected}, got {chain}"
        )

    def test_devdb_not_included(self):
        """DEVDB is a dead-end link, not part of cross-forest chain."""
        answers = load_answers()
        chain = answers["sql_link_chain"]
        assert "DEVDB.corp.local" not in chain, (
            "DEVDB.corp.local is a dead-end link (no outgoing links to "
            "other forests) and should not be in the cross-forest chain"
        )


class TestExploitableDelegation:
    """Verify exploitable delegation identification."""

    def test_svc_web_included(self):
        """svc_web has constrained delegation with protocol transition."""
        answers = load_answers()
        deleg = answers["exploitable_delegation"]
        assert "svc_web@corp.local" in deleg, (
            "svc_web@corp.local has constrained delegation with protocol "
            "transition to MSSQLSvc/SQLSRV01.corp.local:1433"
        )
        services = deleg["svc_web@corp.local"]
        assert "MSSQLSvc/SQLSRV01.corp.local:1433" in services, (
            "svc_web delegates to MSSQLSvc/SQLSRV01.corp.local:1433"
        )

    def test_svc_monitor_excluded(self):
        """svc_monitor is disabled - must be excluded."""
        answers = load_answers()
        deleg = answers["exploitable_delegation"]
        assert "svc_monitor@corp.local" not in deleg, (
            "svc_monitor is disabled and must be excluded from exploitable "
            "delegation"
        )

    def test_svc_deploy_excluded(self):
        """svc_deploy is in Protected Users - must be excluded."""
        answers = load_answers()
        deleg = answers["exploitable_delegation"]
        assert "svc_deploy@corp.local" not in deleg, (
            "svc_deploy is in Protected Users group and cannot be used for "
            "delegation-based attacks"
        )

    def test_dcs_excluded(self):
        """Domain Controllers' unconstrained delegation is expected/default."""
        answers = load_answers()
        deleg = answers["exploitable_delegation"]
        dc_names = [
            "DC01.corp.local", "DC02.us.corp.local",
            "DC03.partner.local", "DC04.secure.local",
        ]
        for dc in dc_names:
            assert dc not in deleg, (
                f"{dc} is a DC - unconstrained delegation on DCs is "
                "expected and should not be listed"
            )

    def test_no_invalid_entries(self):
        """All listed entities must have delegation edges and be exploitable."""
        answers = load_answers()
        deleg = answers["exploitable_delegation"]
        nodes = load_nodes()
        edges = load_edges()

        node_map = {n["name"]: n for n in nodes}
        id_to_name = {n["id"]: n["name"] for n in nodes}

        entities_with_delegation = set()
        for e in edges:
            if e["type"] == "AllowedToDelegate":
                src_name = id_to_name.get(e["source"], e["source"])
                entities_with_delegation.add(src_name)

        for n in nodes:
            if n["type"] == "User":
                if n["properties"].get("delegation_type") == "unconstrained":
                    entities_with_delegation.add(n["name"])
            if n["type"] == "Computer":
                if n["properties"].get("unconstrained_delegation"):
                    entities_with_delegation.add(n["name"])

        for entity_name in deleg:
            assert entity_name in entities_with_delegation, (
                f"{entity_name} does not have delegation configured"
            )


class TestWhatIfAnalysis:
    """Verify what-if mitigation scenario evaluation."""

    def test_all_scenario_keys_present(self):
        answers = load_answers()
        wif = answers["what_if_analysis"]
        required = {
            "scenario_remove_cert_enrollment",
            "scenario_remove_sql_links",
            "scenario_disable_admin_jones",
        }
        assert required.issubset(set(wif.keys())), (
            f"Missing what_if keys: {required - set(wif.keys())}"
        )

    def test_all_values_are_boolean(self):
        answers = load_answers()
        wif = answers["what_if_analysis"]
        for key, val in wif.items():
            assert isinstance(val, bool), (
                f"what_if_analysis['{key}'] must be boolean, got {type(val)}"
            )

    def test_scenario_remove_cert_enrollment(self):
        """Removing cert enrollment still leaves alternative attack paths.

        Without certificate impersonation via AdminWorkstation, an attacker
        can still reach DA@secure.local by compromising service accounts
        with SPNs and weak passwords to gain access to the SQL link chain.
        """
        answers = load_answers()
        wif = answers["what_if_analysis"]
        assert wif["scenario_remove_cert_enrollment"] is True, (
            "Removing IT-Support enrollment on AdminWorkstation should NOT "
            "fully mitigate the threat - alternative credential compromise "
            "paths to the SQL link chain still exist"
        )

    def test_scenario_remove_sql_links(self):
        """Removing SQL links eliminates all paths to secure.local.

        The SQL Server database link chain is the only traversal mechanism
        from corp.local/partner.local forests into secure.local. Without it,
        no viable attack path exists.
        """
        answers = load_answers()
        wif = answers["what_if_analysis"]
        assert wif["scenario_remove_sql_links"] is False, (
            "Removing all SQL links should fully mitigate the threat - "
            "the SQL chain is the only path to secure.local"
        )

    def test_scenario_disable_admin_jones(self):
        """Disabling admin_jones still leaves alternative attack paths.

        Even with admin_jones disabled, alternative paths exist through
        other user account compromises and delegation chains that reach
        the SQL Server infrastructure without requiring admin_jones.
        """
        answers = load_answers()
        wif = answers["what_if_analysis"]
        assert wif["scenario_disable_admin_jones"] is True, (
            "Disabling admin_jones should NOT fully mitigate the threat - "
            "alternative attack paths exist through other account "
            "compromise techniques and delegation chains"
        )


class TestMostEffectiveMitigation:
    """Verify the agent correctly evaluates which mitigation is most effective."""

    def test_value_is_string(self):
        answers = load_answers()
        assert isinstance(answers["most_effective_mitigation"], str), (
            "most_effective_mitigation must be a string"
        )

    def test_correct_mitigation_selected(self):
        """The most effective single mitigation is removing SQL links.

        SQL links are the only cross-forest traversal mechanism to
        secure.local. Removing them is the only scenario that fully
        eliminates all viable attack paths to the target.
        """
        answers = load_answers()
        assert answers["most_effective_mitigation"] == "scenario_remove_sql_links", (
            "The most effective mitigation is removing SQL links - it is "
            "the only change that fully eliminates all viable attack paths "
            "to secure.local"
        )

    def test_consistent_with_what_if(self):
        """Selected mitigation must be the one that fully mitigates."""
        answers = load_answers()
        wif = answers["what_if_analysis"]
        selected = answers["most_effective_mitigation"]
        assert selected in wif, (
            f"Selected mitigation '{selected}' not found in what_if_analysis"
        )
        assert wif[selected] is False, (
            f"Selected mitigation '{selected}' must be the scenario that "
            "fully mitigates (what_if value = false), but its value is true"
        )


class TestAttackPathVisualization:
    """Verify Graphviz DOT attack path visualization."""

    def test_dot_file_exists(self):
        """DOT visualization file must exist."""
        assert os.path.exists("/app/attack_path.dot"), (
            "attack_path.dot not found at /app/attack_path.dot"
        )

    def test_dot_is_valid_digraph(self):
        """DOT file must contain a valid directed graph."""
        with open("/app/attack_path.dot") as f:
            content = f.read()
        assert "digraph" in content, (
            "DOT file must contain a 'digraph' declaration"
        )
        assert "->" in content, (
            "DOT file must contain directed edges (->)"
        )

    def test_dot_contains_start_node(self):
        """DOT file must include the attack chain start node."""
        with open("/app/attack_path.dot") as f:
            content = f.read()
        assert "svc_helpdesk@corp.local" in content, (
            "DOT file must include start node svc_helpdesk@corp.local"
        )

    def test_dot_contains_target_node(self):
        """DOT file must include the attack chain target node."""
        with open("/app/attack_path.dot") as f:
            content = f.read()
        assert "Domain Admins@secure.local" in content, (
            "DOT file must include target node Domain Admins@secure.local"
        )

    def test_dot_contains_sql_servers(self):
        """DOT file must include all SQL servers in the attack chain."""
        with open("/app/attack_path.dot") as f:
            content = f.read()
        for srv in ["SQLSRV01.corp.local", "SQLSRV02.partner.local",
                     "SQLSRV03.secure.local"]:
            assert srv in content, (
                f"DOT file must include SQL server {srv}"
            )

    def test_dot_contains_cert_template(self):
        """DOT file must include the exploited certificate template."""
        with open("/app/attack_path.dot") as f:
            content = f.read()
        assert "AdminWorkstation" in content, (
            "DOT file must include AdminWorkstation certificate template "
            "as part of the attack path visualization"
        )

    def test_dot_compiles_with_graphviz(self):
        """DOT file must be valid Graphviz syntax (compilable by dot)."""
        result = subprocess.run(
            ["dot", "-Tcanon", "/app/attack_path.dot"],
            capture_output=True, timeout=30
        )
        assert result.returncode == 0, (
            f"DOT file failed Graphviz compilation: "
            f"{result.stderr.decode().strip()}"
        )
