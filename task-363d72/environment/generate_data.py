#!/usr/bin/env python3
"""Generate synthetic Active Directory environment data for attack path analysis.

Creates a multi-forest AD environment graph with realistic attack paths,
red herrings, and misconfigurations. Outputs topology to a SQLite database
and certificate template security configurations to LDIF format.
"""

import json
import os
import sqlite3


def generate():
    nodes = []
    edges = []

    # ==================== DOMAINS ====================
    nodes.extend([
        {
            "id": "domain_corp", "type": "Domain", "name": "corp.local",
            "domain": "corp.local",
            "properties": {"forest_root": True, "functional_level": "2016",
                           "domain_sid": "S-1-5-21-3623811015-3361044348-30300820"}
        },
        {
            "id": "domain_uscorp", "type": "Domain", "name": "us.corp.local",
            "domain": "us.corp.local",
            "properties": {"forest_root": False, "functional_level": "2016",
                           "domain_sid": "S-1-5-21-2127521184-1604012920-1887927527"}
        },
        {
            "id": "domain_partner", "type": "Domain", "name": "partner.local",
            "domain": "partner.local",
            "properties": {"forest_root": True, "functional_level": "2016",
                           "domain_sid": "S-1-5-21-4089647105-3330503540-820488511"}
        },
        {
            "id": "domain_secure", "type": "Domain", "name": "secure.local",
            "domain": "secure.local",
            "properties": {"forest_root": True, "functional_level": "2022",
                           "domain_sid": "S-1-5-21-1935655697-2742078379-3647216581"}
        },
    ])

    # Trust relationships
    edges.extend([
        {"source": "domain_uscorp", "target": "domain_corp", "type": "TrustedBy",
         "properties": {"trust_type": "ParentChild", "direction": "Bidirectional",
                        "sid_filtering": False, "transitive": True}},
        {"source": "domain_corp", "target": "domain_uscorp", "type": "TrustedBy",
         "properties": {"trust_type": "ParentChild", "direction": "Bidirectional",
                        "sid_filtering": False, "transitive": True}},
        {"source": "domain_corp", "target": "domain_partner", "type": "TrustedBy",
         "properties": {"trust_type": "External", "direction": "Bidirectional",
                        "sid_filtering": True, "transitive": False}},
        {"source": "domain_partner", "target": "domain_corp", "type": "TrustedBy",
         "properties": {"trust_type": "External", "direction": "Bidirectional",
                        "sid_filtering": True, "transitive": False}},
        {"source": "domain_partner", "target": "domain_secure", "type": "TrustedBy",
         "properties": {"trust_type": "Forest", "direction": "Inbound",
                        "sid_filtering": True, "transitive": True}},
    ])

    # ==================== USERS ====================
    users = [
        # --- corp.local ---
        {"id": "user_helpdesk", "name": "svc_helpdesk@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "medium", "admin_count": False,
         "description": "Help desk service account - Tier 2 support"},
        {"id": "user_backup", "name": "svc_backup@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": True,
         "spn": "MSSQLSvc/backup01.corp.local:1433",
         "dont_req_preauth": False, "password_strength": "weak",
         "admin_count": False,
         "description": "Backup service account for nightly SQL backups"},
        {"id": "user_web", "name": "svc_web@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "medium", "admin_count": False,
         "description": "IIS application pool identity",
         "allowed_to_delegate": ["MSSQLSvc/SQLSRV01.corp.local:1433"],
         "delegation_type": "constrained_w_protocol_transition"},
        {"id": "user_monitor", "name": "svc_monitor@corp.local",
         "domain": "corp.local", "enabled": False, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "medium", "admin_count": False,
         "description": "DECOMMISSIONED - Legacy monitoring agent (do not enable)",
         "delegation_type": "unconstrained"},
        {"id": "user_deploy", "name": "svc_deploy@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "strong", "admin_count": True,
         "description": "SCCM deployment service account",
         "allowed_to_delegate": ["LDAP/DC01.corp.local"],
         "delegation_type": "constrained"},
        {"id": "user_print", "name": "svc_print@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": True,
         "spn": "HTTP/print.corp.local:80", "dont_req_preauth": False,
         "password_strength": "strong", "admin_count": False,
         "description": "Print spooler web management interface"},
        {"id": "user_adminjones", "name": "admin_jones@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "strong", "admin_count": True,
         "description": "Senior Systems Administrator - R. Jones"},
        {"id": "user_jdoe", "name": "jdoe@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "medium", "admin_count": False,
         "description": "John Doe - HR Business Partner"},
        {"id": "user_mwilson", "name": "mwilson@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": True,
         "password_strength": "weak", "admin_count": False,
         "description": "Mary Wilson - Marketing Coordinator"},
        {"id": "user_kpatel", "name": "kpatel@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "medium", "admin_count": False,
         "description": "Kiran Patel - Help Desk Analyst"},
        {"id": "user_hsarah", "name": "helpdesk_sarah@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "medium", "admin_count": False,
         "description": "Sarah Chen - Help Desk Lead"},
        {"id": "user_devlead", "name": "dev_team_lead@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "medium", "admin_count": False,
         "description": "Dev Team Lead - Platform Engineering"},
        {"id": "user_intern", "name": "intern_bob@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "weak", "admin_count": False,
         "description": "Summer intern - Bob Martinez"},
        {"id": "user_sqlcorp", "name": "svc_sqlcorp@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": True,
         "spn": "MSSQLSvc/SQLSRV01.corp.local:1433",
         "dont_req_preauth": False, "password_strength": "medium",
         "admin_count": False,
         "description": "SQL Server service account - corp production instance"},
        {"id": "user_netadmin", "name": "net_admin@corp.local",
         "domain": "corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "strong", "admin_count": False,
         "description": "Network infrastructure administrator"},
        # --- us.corp.local ---
        {"id": "user_usapp", "name": "us_svc_app@us.corp.local",
         "domain": "us.corp.local", "enabled": True, "has_spn": True,
         "spn": "HTTP/app.us.corp.local:443", "dont_req_preauth": False,
         "password_strength": "medium", "admin_count": False,
         "description": "US regional application service"},
        {"id": "user_usadmin", "name": "us_admin@us.corp.local",
         "domain": "us.corp.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "strong", "admin_count": True,
         "description": "US domain administrator"},
        # --- partner.local ---
        {"id": "user_psql", "name": "p_svc_sql@partner.local",
         "domain": "partner.local", "enabled": True, "has_spn": True,
         "spn": "MSSQLSvc/SQLSRV02.partner.local:1433",
         "dont_req_preauth": False, "password_strength": "strong",
         "admin_count": False,
         "description": "Partner SQL Server service account"},
        {"id": "user_padmin", "name": "p_admin@partner.local",
         "domain": "partner.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "strong", "admin_count": True,
         "description": "Partner domain administrator"},
        {"id": "user_pdev", "name": "p_developer@partner.local",
         "domain": "partner.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": True,
         "password_strength": "weak", "admin_count": False,
         "description": "Partner app developer"},
        # --- secure.local ---
        {"id": "user_secsql", "name": "svc_sql@secure.local",
         "domain": "secure.local", "enabled": True, "has_spn": True,
         "spn": "MSSQLSvc/SQLSRV03.secure.local:1433",
         "dont_req_preauth": False, "password_strength": "strong",
         "admin_count": True,
         "description": "Production SQL Server service account - HIGH PRIVILEGE"},
        {"id": "user_secadmin", "name": "sec_admin@secure.local",
         "domain": "secure.local", "enabled": True, "has_spn": False,
         "spn": None, "dont_req_preauth": False,
         "password_strength": "strong", "admin_count": True,
         "description": "Security environment administrator"},
        {"id": "user_secaudit", "name": "svc_audit@secure.local",
         "domain": "secure.local", "enabled": True, "has_spn": True,
         "spn": "HTTP/audit.secure.local:8443",
         "dont_req_preauth": False, "password_strength": "strong",
         "admin_count": False,
         "description": "Audit logging service account"},
    ]

    for u in users:
        node_props = {k: v for k, v in u.items()
                      if k not in ("id", "name", "domain", "type")}
        nodes.append({
            "id": u["id"], "type": "User", "name": u["name"],
            "domain": u["domain"], "properties": node_props
        })

    # ==================== COMPUTERS ====================
    computers = [
        {"id": "comp_dc01", "name": "DC01.corp.local",
         "domain": "corp.local", "enabled": True,
         "os": "Windows Server 2022 Datacenter", "is_dc": True,
         "unconstrained_delegation": True, "has_laps": False},
        {"id": "comp_web01", "name": "WEB01.corp.local",
         "domain": "corp.local", "enabled": True,
         "os": "Windows Server 2022 Standard", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": True},
        {"id": "comp_sql01", "name": "SQLSRV01.corp.local",
         "domain": "corp.local", "enabled": True,
         "os": "Windows Server 2022 Standard", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": False},
        {"id": "comp_ws01", "name": "WS01.corp.local",
         "domain": "corp.local", "enabled": True,
         "os": "Windows 11 Enterprise 23H2", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": True},
        {"id": "comp_file01", "name": "FILE01.corp.local",
         "domain": "corp.local", "enabled": True,
         "os": "Windows Server 2019 Standard", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": False},
        {"id": "comp_dev01", "name": "DEV01.corp.local",
         "domain": "corp.local", "enabled": True,
         "os": "Windows 11 Enterprise 23H2", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": True},
        {"id": "comp_hr01", "name": "HR-PC01.corp.local",
         "domain": "corp.local", "enabled": True,
         "os": "Windows 11 Enterprise 23H2", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": True},
        {"id": "comp_app01", "name": "APP01.corp.local",
         "domain": "corp.local", "enabled": True,
         "os": "Windows Server 2022 Standard", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": False},
        {"id": "comp_dc02", "name": "DC02.us.corp.local",
         "domain": "us.corp.local", "enabled": True,
         "os": "Windows Server 2022 Datacenter", "is_dc": True,
         "unconstrained_delegation": True, "has_laps": False},
        {"id": "comp_usapp01", "name": "USAPP01.us.corp.local",
         "domain": "us.corp.local", "enabled": True,
         "os": "Windows Server 2019 Standard", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": False},
        {"id": "comp_sql02", "name": "SQLSRV02.partner.local",
         "domain": "partner.local", "enabled": True,
         "os": "Windows Server 2019 Standard", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": False},
        {"id": "comp_dc03", "name": "DC03.partner.local",
         "domain": "partner.local", "enabled": True,
         "os": "Windows Server 2019 Datacenter", "is_dc": True,
         "unconstrained_delegation": True, "has_laps": False},
        {"id": "comp_pweb01", "name": "PWEB01.partner.local",
         "domain": "partner.local", "enabled": True,
         "os": "Windows Server 2019 Standard", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": False},
        {"id": "comp_sql03", "name": "SQLSRV03.secure.local",
         "domain": "secure.local", "enabled": True,
         "os": "Windows Server 2025 Datacenter", "is_dc": False,
         "unconstrained_delegation": False, "has_laps": True},
        {"id": "comp_dc04", "name": "DC04.secure.local",
         "domain": "secure.local", "enabled": True,
         "os": "Windows Server 2025 Datacenter", "is_dc": True,
         "unconstrained_delegation": True, "has_laps": False},
    ]

    for c in computers:
        node_props = {k: v for k, v in c.items()
                      if k not in ("id", "name", "domain", "type")}
        nodes.append({
            "id": c["id"], "type": "Computer", "name": c["name"],
            "domain": c["domain"], "properties": node_props
        })

    # ==================== GROUPS ====================
    groups = [
        {"id": "group_da_corp", "name": "Domain Admins@corp.local",
         "domain": "corp.local", "admin_count": True,
         "description": "Designated administrators of the domain"},
        {"id": "group_ea_corp", "name": "Enterprise Admins@corp.local",
         "domain": "corp.local", "admin_count": True,
         "description": "Forest-wide administrators"},
        {"id": "group_it", "name": "IT-Support@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "IT support staff - help desk and tier 2"},
        {"id": "group_backup", "name": "Backup-Operators@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "Backup operator privileges for scheduled tasks"},
        {"id": "group_protected", "name": "Protected Users@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "Members receive additional credential protections"},
        {"id": "group_print", "name": "Print-Operators@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "Print server management group"},
        {"id": "group_du_corp", "name": "Domain Users@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "All domain user accounts"},
        {"id": "group_au_corp", "name": "Authenticated Users@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "All authenticated identities"},
        {"id": "group_dev", "name": "Developers@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "Software development team"},
        {"id": "group_hr", "name": "HR-Users@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "Human Resources department"},
        {"id": "group_vpn", "name": "VPN-Users@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "Remote VPN access group"},
        {"id": "group_serverops", "name": "Server-Operators@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "Server maintenance and operations"},
        {"id": "group_netadmins", "name": "Network-Admins@corp.local",
         "domain": "corp.local", "admin_count": False,
         "description": "Network infrastructure team"},
        {"id": "group_da_us", "name": "Domain Admins@us.corp.local",
         "domain": "us.corp.local", "admin_count": True,
         "description": "US child domain administrators"},
        {"id": "group_du_us", "name": "Domain Users@us.corp.local",
         "domain": "us.corp.local", "admin_count": False,
         "description": "US domain user accounts"},
        {"id": "group_da_partner", "name": "Domain Admins@partner.local",
         "domain": "partner.local", "admin_count": True,
         "description": "Partner domain administrators"},
        {"id": "group_sqladmin", "name": "SQL-Admins@partner.local",
         "domain": "partner.local", "admin_count": False,
         "description": "Partner SQL Server administration"},
        {"id": "group_du_partner", "name": "Domain Users@partner.local",
         "domain": "partner.local", "admin_count": False,
         "description": "Partner domain users"},
        {"id": "group_da_secure", "name": "Domain Admins@secure.local",
         "domain": "secure.local", "admin_count": True,
         "description": "Secure environment domain administrators"},
        {"id": "group_du_secure", "name": "Domain Users@secure.local",
         "domain": "secure.local", "admin_count": False,
         "description": "Secure domain user accounts"},
    ]

    for g in groups:
        nodes.append({
            "id": g["id"], "type": "Group", "name": g["name"],
            "domain": g["domain"],
            "properties": {"admin_count": g["admin_count"],
                           "description": g["description"]}
        })

    # ==================== CERTIFICATE TEMPLATES ====================
    # Security-relevant properties (name_flag, enrollment_flag, ra_signature,
    # eku_oids) are stored ONLY in the LDIF export, NOT in the database.
    # The database stores only name, domain, description, and validity_period.
    cert_templates = [
        {"id": "cert_uservpn", "name": "UserVPN@corp.local",
         "cn": "UserVPN", "domain": "corp.local",
         "description": "VPN user authentication certificate",
         "validity_period": "1 year",
         "template_oid": "1.3.6.1.4.1.311.21.8.11489019.14294623.5588661.594850.9477891.123.3245801.1",
         "name_flag": 1,
         "enrollment_flag": 66,
         "ra_signature": 0,
         "eku_oids": ["1.3.6.1.5.5.7.3.2", "1.3.6.1.5.5.7.3.4"],
         "schema_version": 2, "revision": 100},
        {"id": "cert_webserver", "name": "WebServer@corp.local",
         "cn": "WebServer", "domain": "corp.local",
         "description": "Internal web server TLS certificate",
         "validity_period": "2 years",
         "template_oid": "1.3.6.1.4.1.311.21.8.11489019.14294623.5588661.594850.9477891.123.7291044.2",
         "name_flag": 1,
         "enrollment_flag": 0,
         "ra_signature": 0,
         "eku_oids": ["1.3.6.1.5.5.7.3.1"],
         "schema_version": 2, "revision": 104},
        {"id": "cert_smartcard", "name": "SmartcardUser@corp.local",
         "cn": "SmartcardUser", "domain": "corp.local",
         "description": "Physical smart card logon certificate",
         "validity_period": "1 year",
         "template_oid": "1.3.6.1.4.1.311.21.8.11489019.14294623.5588661.594850.9477891.123.5018293.3",
         "name_flag": 256,
         "enrollment_flag": 4,
         "ra_signature": 1,
         "eku_oids": ["1.3.6.1.4.1.311.20.2.2", "1.3.6.1.5.5.7.3.2"],
         "schema_version": 2, "revision": 107},
        {"id": "cert_adminws", "name": "AdminWorkstation@corp.local",
         "cn": "AdminWorkstation", "domain": "corp.local",
         "description": "Privileged access workstation authentication",
         "validity_period": "1 year",
         "template_oid": "1.3.6.1.4.1.311.21.8.11489019.14294623.5588661.594850.9477891.123.8392381.4",
         "name_flag": 9,
         "enrollment_flag": 64,
         "ra_signature": 0,
         "eku_oids": ["1.3.6.1.5.5.7.3.2"],
         "schema_version": 2, "revision": 112},
        {"id": "cert_codesign", "name": "CodeSigning@corp.local",
         "cn": "CodeSigning", "domain": "corp.local",
         "description": "Internal code signing certificate",
         "validity_period": "3 years",
         "template_oid": "1.3.6.1.4.1.311.21.8.11489019.14294623.5588661.594850.9477891.123.1029374.5",
         "name_flag": 17,
         "enrollment_flag": 0,
         "ra_signature": 1,
         "eku_oids": ["1.3.6.1.5.5.7.3.3"],
         "schema_version": 2, "revision": 98},
        {"id": "cert_webauth", "name": "WebAuthentication@corp.local",
         "cn": "WebAuthentication", "domain": "corp.local",
         "description": "Mutual TLS authentication certificate",
         "validity_period": "1 year",
         "template_oid": "1.3.6.1.4.1.311.21.8.11489019.14294623.5588661.594850.9477891.123.6504821.6",
         "name_flag": 1,
         "enrollment_flag": 0,
         "ra_signature": 2,
         "eku_oids": ["1.3.6.1.5.5.7.3.2", "1.3.6.1.5.5.7.3.1"],
         "schema_version": 2, "revision": 115},
    ]

    # Database stores only non-security metadata for cert templates
    for ct in cert_templates:
        nodes.append({
            "id": ct["id"], "type": "CertTemplate", "name": ct["name"],
            "domain": ct["domain"],
            "properties": {
                "description": ct["description"],
                "validity_period": ct["validity_period"],
            }
        })

    # ==================== SQL SERVERS ====================
    sql_servers = [
        {"id": "sql_inst01", "name": "SQLSRV01.corp.local",
         "domain": "corp.local", "instance": "SQLSRV01\\MSSQLSERVER",
         "xp_cmdshell": False,
         "sysadmin_accounts": ["admin_jones@corp.local",
                               "svc_sqlcorp@corp.local"],
         "version": "SQL Server 2022"},
        {"id": "sql_inst02", "name": "SQLSRV02.partner.local",
         "domain": "partner.local", "instance": "SQLSRV02\\MSSQLSERVER",
         "xp_cmdshell": False,
         "sysadmin_accounts": ["p_svc_sql@partner.local",
                               "p_admin@partner.local"],
         "version": "SQL Server 2019"},
        {"id": "sql_inst03", "name": "SQLSRV03.secure.local",
         "domain": "secure.local", "instance": "SQLSRV03\\MSSQLSERVER",
         "xp_cmdshell": True,
         "sysadmin_accounts": ["svc_sql@secure.local",
                               "sec_admin@secure.local"],
         "version": "SQL Server 2025"},
        {"id": "sql_inst04", "name": "DEVDB.corp.local",
         "domain": "corp.local", "instance": "DEVDB\\SQLEXPRESS",
         "xp_cmdshell": True,
         "sysadmin_accounts": ["dev_team_lead@corp.local"],
         "version": "SQL Server 2019 Express"},
    ]

    for s in sql_servers:
        node_props = {k: v for k, v in s.items()
                      if k not in ("id", "name", "domain", "type")}
        nodes.append({
            "id": s["id"], "type": "SQLServer", "name": s["name"],
            "domain": s["domain"], "properties": node_props
        })

    # ==================== EDGES ====================

    # --- Group Memberships (MemberOf) ---
    memberships = [
        ("user_helpdesk", "group_it"),
        ("user_helpdesk", "group_du_corp"),
        ("user_backup", "group_backup"),
        ("user_backup", "group_du_corp"),
        ("user_web", "group_du_corp"),
        ("user_monitor", "group_du_corp"),
        ("user_deploy", "group_protected"),
        ("user_deploy", "group_du_corp"),
        ("user_deploy", "group_serverops"),
        ("user_print", "group_print"),
        ("user_print", "group_du_corp"),
        ("user_adminjones", "group_da_corp"),
        ("user_adminjones", "group_du_corp"),
        ("user_jdoe", "group_hr"),
        ("user_jdoe", "group_du_corp"),
        ("user_mwilson", "group_vpn"),
        ("user_mwilson", "group_du_corp"),
        ("user_kpatel", "group_it"),
        ("user_kpatel", "group_du_corp"),
        ("user_hsarah", "group_it"),
        ("user_hsarah", "group_du_corp"),
        ("user_devlead", "group_dev"),
        ("user_devlead", "group_du_corp"),
        ("user_intern", "group_dev"),
        ("user_intern", "group_du_corp"),
        ("user_sqlcorp", "group_du_corp"),
        ("user_netadmin", "group_netadmins"),
        ("user_netadmin", "group_du_corp"),
        ("group_du_corp", "group_au_corp"),
        ("user_usapp", "group_du_us"),
        ("user_usadmin", "group_da_us"),
        ("user_usadmin", "group_du_us"),
        ("user_psql", "group_sqladmin"),
        ("user_psql", "group_du_partner"),
        ("user_padmin", "group_da_partner"),
        ("user_padmin", "group_du_partner"),
        ("user_pdev", "group_du_partner"),
        ("user_secsql", "group_da_secure"),
        ("user_secsql", "group_du_secure"),
        ("user_secadmin", "group_da_secure"),
        ("user_secadmin", "group_du_secure"),
        ("user_secaudit", "group_du_secure"),
    ]

    for src, tgt in memberships:
        edges.append({"source": src, "target": tgt,
                      "type": "MemberOf", "properties": {}})

    # --- ACL Edges ---
    acl_edges = [
        ("group_it", "user_backup", "GenericWrite",
         {"info": "IT-Support can modify svc_backup properties including SPNs"}),
        ("user_deploy", "comp_dc01", "GenericAll",
         {"info": "svc_deploy has full control on DC01"}),
        ("user_print", "user_adminjones", "ForceChangePassword",
         {"info": "svc_print can reset admin_jones password"}),
        ("group_dev", "comp_dev01", "GenericAll",
         {"info": "Developers have full control on DEV01"}),
        ("group_serverops", "comp_file01", "GenericAll",
         {"info": "Server-Operators can manage FILE01"}),
        ("group_serverops", "comp_app01", "GenericAll",
         {"info": "Server-Operators can manage APP01"}),
        ("user_intern", "group_dev", "WriteDacl",
         {"info": "Misconfigured - intern can modify Developers group DACL"}),
        ("group_netadmins", "comp_app01", "GenericWrite",
         {"info": "Network admins can modify APP01 properties"}),
        ("user_devlead", "user_usapp", "GenericAll",
         {"info": "Dev lead has full control over US app service account"}),
    ]

    for src, tgt, rel_type, props in acl_edges:
        edges.append({"source": src, "target": tgt,
                      "type": rel_type, "properties": props})

    # --- AdminTo Edges ---
    admin_edges = [
        ("group_da_corp", "comp_dc01"),
        ("group_da_corp", "comp_web01"),
        ("group_da_corp", "comp_sql01"),
        ("group_da_corp", "comp_ws01"),
        ("group_da_corp", "comp_file01"),
        ("group_da_corp", "comp_dev01"),
        ("group_da_corp", "comp_hr01"),
        ("group_da_corp", "comp_app01"),
        ("group_print", "comp_ws01"),
        ("group_da_us", "comp_dc02"),
        ("group_da_us", "comp_usapp01"),
        ("group_da_partner", "comp_dc03"),
        ("group_da_partner", "comp_sql02"),
        ("group_da_partner", "comp_pweb01"),
        ("group_sqladmin", "comp_sql02"),
        ("group_da_secure", "comp_dc04"),
        ("group_da_secure", "comp_sql03"),
    ]

    for src, tgt in admin_edges:
        edges.append({"source": src, "target": tgt,
                      "type": "AdminTo", "properties": {}})

    # --- HasSession Edges (Computer -> User) ---
    session_edges = [
        ("comp_web01", "user_adminjones"),
        ("comp_ws01", "user_kpatel"),
        ("comp_sql01", "user_sqlcorp"),
        ("comp_dev01", "user_devlead"),
        ("comp_hr01", "user_jdoe"),
        ("comp_app01", "user_web"),
        ("comp_usapp01", "user_usapp"),
        ("comp_dc03", "user_padmin"),
    ]

    for src, tgt in session_edges:
        edges.append({"source": src, "target": tgt,
                      "type": "HasSession", "properties": {}})

    # --- ReadLAPSPassword ---
    edges.append({"source": "group_backup", "target": "comp_web01",
                  "type": "ReadLAPSPassword", "properties": {}})
    edges.append({"source": "group_hr", "target": "comp_hr01",
                  "type": "ReadLAPSPassword", "properties": {}})

    # --- Delegation ---
    edges.append({
        "source": "user_web", "target": "comp_sql01",
        "type": "AllowedToDelegate",
        "properties": {"services": ["MSSQLSvc/SQLSRV01.corp.local:1433"],
                       "protocol_transition": True}
    })
    edges.append({
        "source": "user_deploy", "target": "comp_dc01",
        "type": "AllowedToDelegate",
        "properties": {"services": ["LDAP/DC01.corp.local"],
                       "protocol_transition": False}
    })

    # --- CanRDP / CanPSRemote ---
    edges.append({"source": "group_dev", "target": "comp_dev01",
                  "type": "CanRDP", "properties": {}})
    edges.append({"source": "group_hr", "target": "comp_hr01",
                  "type": "CanRDP", "properties": {}})
    edges.append({"source": "group_it", "target": "comp_ws01",
                  "type": "CanPSRemote", "properties": {}})
    edges.append({"source": "group_vpn", "target": "comp_app01",
                  "type": "CanRDP", "properties": {}})

    # --- SQL Server Topology ---
    edges.append({"source": "sql_inst01", "target": "comp_sql01",
                  "type": "RunsOn", "properties": {}})
    edges.append({"source": "sql_inst02", "target": "comp_sql02",
                  "type": "RunsOn", "properties": {}})
    edges.append({"source": "sql_inst03", "target": "comp_sql03",
                  "type": "RunsOn", "properties": {}})
    edges.append({"source": "sql_inst04", "target": "comp_dev01",
                  "type": "RunsOn", "properties": {}})

    edges.append({"source": "sql_inst01", "target": "user_sqlcorp",
                  "type": "RunsAs", "properties": {}})
    edges.append({"source": "sql_inst02", "target": "user_psql",
                  "type": "RunsAs", "properties": {}})
    edges.append({"source": "sql_inst03", "target": "user_secsql",
                  "type": "RunsAs", "properties": {}})
    edges.append({"source": "sql_inst04", "target": "user_devlead",
                  "type": "RunsAs", "properties": {}})

    edges.append({
        "source": "sql_inst01", "target": "sql_inst02",
        "type": "SQLLink",
        "properties": {"link_name": "PARTNER_SQL",
                       "link_auth_account": "p_svc_sql@partner.local",
                       "link_sysadmin": True,
                       "rpc_out_enabled": True}
    })
    edges.append({
        "source": "sql_inst02", "target": "sql_inst03",
        "type": "SQLLink",
        "properties": {"link_name": "SECURE_PROD_SQL",
                       "link_auth_account": "svc_sql@secure.local",
                       "link_sysadmin": True,
                       "rpc_out_enabled": True}
    })
    edges.append({
        "source": "sql_inst01", "target": "sql_inst04",
        "type": "SQLLink",
        "properties": {"link_name": "DEV_DB",
                       "link_auth_account": "dev_team_lead@corp.local",
                       "link_sysadmin": True,
                       "rpc_out_enabled": False}
    })

    # --- Certificate Template Enrollment Rights ---
    enrollment_edges = [
        ("group_du_corp", "cert_uservpn"),
        ("group_du_corp", "cert_webserver"),
        ("group_du_corp", "cert_smartcard"),
        ("group_it", "cert_adminws"),
        ("group_du_corp", "cert_codesign"),
        ("group_da_corp", "cert_webauth"),
    ]

    for src, tgt in enrollment_edges:
        edges.append({"source": src, "target": tgt,
                      "type": "CanEnroll", "properties": {}})

    # ==================== WRITE TO SQLITE ====================
    os.makedirs("/app/ad_data", exist_ok=True)
    db_path = "/app/ad_data/environment.db"

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE nodes (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        domain TEXT NOT NULL,
        properties TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE edges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        target TEXT NOT NULL,
        type TEXT NOT NULL,
        properties TEXT NOT NULL,
        FOREIGN KEY (source) REFERENCES nodes(id),
        FOREIGN KEY (target) REFERENCES nodes(id)
    )''')

    c.execute('CREATE INDEX idx_edges_source ON edges(source)')
    c.execute('CREATE INDEX idx_edges_target ON edges(target)')
    c.execute('CREATE INDEX idx_edges_type ON edges(type)')
    c.execute('CREATE INDEX idx_nodes_type ON nodes(type)')
    c.execute('CREATE INDEX idx_nodes_domain ON nodes(domain)')

    for n in nodes:
        c.execute('INSERT INTO nodes VALUES (?, ?, ?, ?, ?)',
                  (n['id'], n['type'], n['name'], n['domain'],
                   json.dumps(n['properties'])))

    for e in edges:
        c.execute(
            'INSERT INTO edges (source, target, type, properties) VALUES (?, ?, ?, ?)',
            (e['source'], e['target'], e['type'], json.dumps(e['properties']))
        )

    conn.commit()

    # Print summary
    c.execute('SELECT type, COUNT(*) FROM nodes GROUP BY type')
    print("Generated database at", db_path)
    for row in c.fetchall():
        print(f"  {row[0]}: {row[1]}")
    c.execute('SELECT COUNT(*) FROM edges')
    print(f"  Edges: {c.fetchone()[0]}")

    conn.close()

    # ==================== WRITE LDIF ====================
    write_cert_template_ldif(cert_templates, "/app/ad_data/cert_templates.ldif")


def write_cert_template_ldif(templates, path):
    """Write certificate template security configurations in LDIF format.

    This is the authoritative source for certificate template security
    properties. The SQLite database stores only name/domain metadata.
    """
    lines = []
    lines.append("# LDAP Data Interchange Format (LDIF)")
    lines.append("# Exported from: DC01.corp.local")
    lines.append("# Base DN: CN=Certificate Templates,CN=Public Key Services,"
                 "CN=Services,CN=Configuration,DC=corp,DC=local")
    lines.append("# Export timestamp: 20260115T083000Z")
    lines.append("# Filter: (objectClass=pKICertificateTemplate)")
    lines.append("# Scope: subtree")
    lines.append("")

    for t in templates:
        cn = t["cn"]
        domain_parts = t["domain"].split(".")
        dc_string = ",".join(f"DC={p}" for p in domain_parts)
        base_dn = (f"CN={cn},CN=Certificate Templates,CN=Public Key Services,"
                   f"CN=Services,CN=Configuration,{dc_string}")

        lines.append(f"dn: {base_dn}")
        lines.append("objectClass: top")
        lines.append("objectClass: pKICertificateTemplate")
        lines.append(f"cn: {cn}")
        lines.append(f"displayName: {t['description']}")
        lines.append(f"distinguishedName: {base_dn}")
        lines.append("flags: 131168")
        lines.append("instanceType: 4")
        lines.append(f"msPKI-Cert-Template-OID: {t['template_oid']}")
        for oid in t["eku_oids"]:
            lines.append(f"msPKI-Certificate-Application-Policy: {oid}")
        lines.append(f"msPKI-Certificate-Name-Flag: {t['name_flag']}")
        lines.append(f"msPKI-Enrollment-Flag: {t['enrollment_flag']}")
        lines.append(f"msPKI-Minimal-Key-Size: 2048")
        lines.append("msPKI-Private-Key-Flag: 16842768")
        lines.append(f"msPKI-RA-Signature: {t['ra_signature']}")
        lines.append("msPKI-Template-Minor-Revision: 3")
        lines.append(f"msPKI-Template-Schema-Version: {t['schema_version']}")
        lines.append(f"name: {cn}")
        lines.append("objectCategory: CN=PKI-Certificate-Template,CN=Schema,"
                     f"CN=Configuration,{dc_string}")
        lines.append("pKIDefaultCSPs: 1,Microsoft RSA SChannel Cryptographic Provider")
        lines.append("pKIDefaultKeySpec: 1")
        for oid in t["eku_oids"]:
            lines.append(f"pKIExtendedKeyUsage: {oid}")
        lines.append("pKIMaxIssuingDepth: 0")
        lines.append(f"revision: {t['revision']}")
        lines.append("showInAdvancedViewOnly: TRUE")
        lines.append("")

    with open(path, 'w') as f:
        f.write('\n'.join(lines))

    print(f"Generated LDIF at {path} ({len(templates)} templates)")


if __name__ == "__main__":
    generate()
