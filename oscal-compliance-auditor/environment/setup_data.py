#!/usr/bin/env python3
"""Generate OSCAL data files for cross-layer compliance reconciliation task."""
import json
import os
import hashlib
import xml.etree.ElementTree as ET

NS = "http://csrc.nist.gov/ns/oscal/1.0"
ET.register_namespace('', NS)


def n(tag):
    return f"{{{NS}}}{tag}"


def det_uuid(seed):
    h = hashlib.md5(seed.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-8{h[17:20]}-{h[20:32]}"


# ═══════════════════════════════════════════════════════════════════════════
# Control definitions: (id, title, params, statement_labels, nested, enhancements)
# ═══════════════════════════════════════════════════════════════════════════

def ctrl(cid, title, params=None, stmts=None, nested=None, enhancements=None):
    return {"id": cid, "title": title, "params": params or [],
            "stmts": stmts or ["a"], "nested": nested or {}, "enh": enhancements or []}


AC = [
    ctrl("ac-1", "Policy and Procedures",
         params=[("ac-1_prm_1", "organization-defined personnel or roles"),
                 ("ac-1_prm_2", "organization-defined frequency")],
         stmts=["a", "b"], nested={"a": ["1", "2"]}),
    ctrl("ac-2", "Account Management", stmts=["a", "b", "c", "d"],
         enhancements=[
             ctrl("ac-2.1", "Automated System Account Management"),
             ctrl("ac-2.2", "Automated Temporary and Emergency Account Management"),
             ctrl("ac-2.3", "Disable Accounts"),
             ctrl("ac-2.4", "Automated Audit Actions"),
             ctrl("ac-2.5", "Inactivity Logout"),
         ]),
    ctrl("ac-3", "Access Enforcement",
         enhancements=[ctrl("ac-3.1", "Restricted Access to Privileged Functions")]),
    ctrl("ac-4", "Information Flow Enforcement"),
    ctrl("ac-5", "Separation of Duties", stmts=["a", "b"]),
    ctrl("ac-6", "Least Privilege", stmts=["a", "b"],
         enhancements=[
             ctrl("ac-6.1", "Authorize Access to Security Functions"),
             ctrl("ac-6.2", "Non-privileged Access for Nonsecurity Functions"),
         ]),
    ctrl("ac-7", "Unsuccessful Logon Attempts",
         params=[("ac-7_prm_1", "number of consecutive invalid logon attempts"),
                 ("ac-7_prm_2", "time period for lockout duration or delay")],
         stmts=["a", "b"]),
    ctrl("ac-8", "System Use Notification"),
]

AU = [
    ctrl("au-1", "Policy and Procedures",
         params=[("au-1_prm_1", "organization-defined personnel or roles"),
                 ("au-1_prm_2", "organization-defined frequency for policy review"),
                 ("au-1_prm_3", "organization-defined frequency for procedure review")],
         stmts=["a", "b"], nested={"a": ["1", "2"]}),
    ctrl("au-2", "Event Logging",
         params=[("au-2_prm_1", "organization-defined event types")],
         stmts=["a", "b"]),
    ctrl("au-3", "Content of Audit Records",
         enhancements=[ctrl("au-3.1", "Additional Audit Information")]),
    ctrl("au-4", "Audit Log Storage Capacity"),
    ctrl("au-5", "Response to Audit Logging Process Failures",
         params=[("au-5_prm_1", "organization-defined actions upon audit failure")],
         stmts=["a", "b"]),
    ctrl("au-6", "Audit Record Review, Analysis, and Reporting",
         params=[("au-6_prm_1", "organization-defined frequency for review"),
                 ("au-6_prm_2", "organization-defined personnel for reporting")],
         stmts=["a", "b"],
         enhancements=[
             ctrl("au-6.1", "Automated Process Integration"),
             ctrl("au-6.3", "Correlate Audit Record Repositories"),
         ]),
]

SI = [
    ctrl("si-1", "Policy and Procedures", stmts=["a", "b"]),
    ctrl("si-2", "Flaw Remediation", stmts=["a", "b"],
         enhancements=[
             ctrl("si-2.1", "Central Management"),
             ctrl("si-2.2", "Automated Flaw Remediation Status"),
         ]),
    ctrl("si-3", "Malicious Code Protection", stmts=["a", "b"],
         enhancements=[ctrl("si-3.1", "Central Management of Protection Mechanisms")]),
    ctrl("si-4", "System Monitoring", stmts=["a", "b", "c"],
         enhancements=[
             ctrl("si-4.1", "System-wide Intrusion Detection System"),
             ctrl("si-4.2", "Automated Tools and Mechanisms for Real-time Analysis"),
             ctrl("si-4.4", "Inbound and Outbound Communications Traffic"),
             ctrl("si-4.5", "System-generated Alerts"),
         ]),
    ctrl("si-5", "Security Alerts, Advisories, and Directives", stmts=["a", "b"]),
]

FAMILIES = [
    ("ac", "Access Control", "AC", AC),
    ("au", "Audit and Accountability", "AU", AU),
    ("si", "System and Information Integrity", "SI", SI),
]

CATALOG_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"


# ═══════════════════════════════════════════════════════════════════════════
# Generate catalog.xml
# ═══════════════════════════════════════════════════════════════════════════

def add_xml_control(parent, c):
    """Add a control element to an XML parent."""
    cel = ET.SubElement(parent, n('control'), {'id': c['id'], 'class': 'SP800-53'})
    ET.SubElement(cel, n('title')).text = c['title']
    ET.SubElement(cel, n('prop'), {'name': 'label', 'value': c['id'].upper()})
    ET.SubElement(cel, n('prop'), {'name': 'sort-id', 'value': c['id']})

    for pid, plabel in c['params']:
        param = ET.SubElement(cel, n('param'), {'id': pid})
        ET.SubElement(param, n('label')).text = plabel

    stmt = ET.SubElement(cel, n('part'), {'id': f"{c['id']}_smt", 'name': 'statement'})
    for lbl in c['stmts']:
        part_id = f"{c['id']}_smt.{lbl}"
        part = ET.SubElement(stmt, n('part'), {'id': part_id, 'name': 'item'})
        ET.SubElement(part, n('prop'), {'name': 'label', 'value': f'{lbl}.'})
        ET.SubElement(part, n('p')).text = f"[Statement {lbl} for {c['id']}]"
        if lbl in c['nested']:
            for sub in c['nested'][lbl]:
                sub_id = f"{c['id']}_smt.{lbl}.{sub}"
                sp = ET.SubElement(part, n('part'), {'id': sub_id, 'name': 'item'})
                ET.SubElement(sp, n('prop'), {'name': 'label', 'value': f'{sub}.'})
                ET.SubElement(sp, n('p')).text = f"[Statement {lbl}.{sub} for {c['id']}]"

    for enh in c['enh']:
        add_xml_control(cel, enh)


def generate_catalog_xml():
    root = ET.Element(n('catalog'), {'uuid': CATALOG_UUID})
    meta = ET.SubElement(root, n('metadata'))
    ET.SubElement(meta, n('title')).text = \
        "Custom Security Controls Catalog Based on NIST SP 800-53 Rev 5"
    ET.SubElement(meta, n('last-modified')).text = "2025-09-15T10:00:00.000000-04:00"
    ET.SubElement(meta, n('version')).text = "1.0.0"
    ET.SubElement(meta, n('oscal-version')).text = "1.1.3"

    for fam_id, fam_title, fam_label, controls in FAMILIES:
        group = ET.SubElement(root, n('group'), {'id': fam_id, 'class': 'family'})
        ET.SubElement(group, n('title')).text = fam_title
        ET.SubElement(group, n('prop'), {'name': 'label', 'value': fam_label})
        for c in controls:
            add_xml_control(group, c)

    ET.indent(ET.ElementTree(root), space="  ")
    return ET.ElementTree(root)


# ═══════════════════════════════════════════════════════════════════════════
# Generate profile_low.json — selects base controls from catalog
# ═══════════════════════════════════════════════════════════════════════════

LOW_PROFILE_UUID = "1a2b3c4d-5e6f-4a7b-8c9d-aabbccddeeff"

LOW_CONTROLS = [
    "ac-1", "ac-2", "ac-3", "ac-7",
    "au-1", "au-2", "au-3", "au-4",
    "si-1", "si-2", "si-5",
]

profile_low = {
    "profile": {
        "uuid": LOW_PROFILE_UUID,
        "metadata": {
            "title": "Custom Low Impact Baseline Security Profile",
            "last-modified": "2025-09-20T09:00:00.000000-04:00",
            "version": "1.0.0",
            "oscal-version": "1.1.3"
        },
        "imports": [{
            "href": "catalog.xml",
            "include-controls": [{"with-ids": LOW_CONTROLS}]
        }],
        "merge": {"as-is": True}
    }
}


# ═══════════════════════════════════════════════════════════════════════════
# Generate profile_moderate.json — imports Low + adds controls from catalog
# ═══════════════════════════════════════════════════════════════════════════

MOD_PROFILE_UUID = "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e"

profile_moderate = {
    "profile": {
        "uuid": MOD_PROFILE_UUID,
        "metadata": {
            "title": "Custom Moderate Impact Baseline Security Profile",
            "last-modified": "2025-10-01T14:00:00.000000-04:00",
            "version": "1.0.0",
            "oscal-version": "1.1.3"
        },
        "imports": [
            {
                "href": "profile_low.json",
                "include-all": {}
            },
            {
                "href": "catalog.xml",
                "include-controls": [
                    {
                        "with-ids": [
                            "ac-2.1", "ac-2.3", "ac-2.4", "ac-4", "ac-5",
                            "ac-6", "ac-6.1", "ac-8",
                            "au-3.1", "au-5", "au-6", "au-6.1",
                            "si-2.1", "si-3", "si-3.1", "si-5"
                        ]
                    },
                    {
                        "matching": [{"pattern": "si-4*"}]
                    }
                ],
                "exclude-controls": [{
                    "with-ids": ["si-4.1", "si-4.5"]
                }]
            }
        ],
        "merge": {"as-is": True},
        "modify": {
            "set-parameters": [
                {"param-id": "ac-1_prm_1",
                 "values": ["all organizational personnel"]},
                {"param-id": "ac-1_prm_2",
                 "values": ["at least annually"]},
                {"param-id": "ac-7_prm_1",
                 "values": ["3"]},
                {"param-id": "ac-7_prm_2",
                 "values": ["30 minutes"]},
                {"param-id": "au-1_prm_1",
                 "values": ["all organizational personnel"]},
                {"param-id": "au-1_prm_2",
                 "values": ["at least annually"]},
                {"param-id": "au-1_prm_3",
                 "values": ["at least annually"]},
                {"param-id": "au-2_prm_1",
                 "values": ["account logon events, policy changes, privilege usage"]},
                {"param-id": "au-5_prm_1",
                 "values": ["overwrite oldest audit records"]},
                {"param-id": "au-6_prm_1",
                 "values": ["weekly"]},
                {"param-id": "au-6_prm_2",
                 "values": ["system administrator"]},
            ]
        }
    }
}


# ═══════════════════════════════════════════════════════════════════════════
# Generate ssp.json
# ═══════════════════════════════════════════════════════════════════════════

COMP_AUTH = "11111111-0000-4000-8000-000000000001"
COMP_AUDIT = "11111111-0000-4000-8000-000000000002"
COMP_POLICY = "11111111-0000-4000-8000-000000000003"
COMP_EPP = "11111111-0000-4000-8000-000000000004"
COMP_NETMON = "11111111-0000-4000-8000-000000000005"
COMP_GHOST1 = "99999999-0000-4000-8000-000000000001"
COMP_GHOST2 = "99999999-0000-4000-8000-000000000002"


def bc(comp_uuid, desc):
    return {
        "component-uuid": comp_uuid,
        "uuid": det_uuid(f"bc-{comp_uuid}-{desc[:30]}"),
        "description": desc
    }


def stmt(stmt_id, by_components):
    return {
        "statement-id": stmt_id,
        "uuid": det_uuid(f"stmt-{stmt_id}"),
        "by-components": by_components
    }


impl_reqs = []


def add_impl(cid, statements, params=None):
    req = {
        "uuid": det_uuid(f"impl-{cid}"),
        "control-id": cid,
    }
    if params:
        req["set-parameters"] = params
    req["statements"] = statements
    impl_reqs.append(req)


# ac-1
add_impl("ac-1", [
    stmt("ac-1_smt.a", [bc(COMP_POLICY, "Security Policy Framework defines access control policy.")]),
    stmt("ac-1_smt.b", [bc(COMP_POLICY, "Security Policy Framework designates the CISO.")]),
], params=[
    {"param-id": "ac-1_prm_1", "values": ["all organizational personnel"]},
    {"param-id": "ac-1_prm_2", "values": ["at least annually"]}
])

# ac-2: broken component ref in statement c
add_impl("ac-2", [
    stmt("ac-2_smt.a", [bc(COMP_AUTH, "Authentication Service manages account types.")]),
    stmt("ac-2_smt.b", [bc(COMP_AUTH, "Authentication Service assigns account managers.")]),
    stmt("ac-2_smt.c", [bc(COMP_GHOST1, "Automated provisioning enforces prerequisites.")]),
    stmt("ac-2_smt.d", [bc(COMP_AUTH, "Authentication Service manages groups and roles.")]),
])

add_impl("ac-2.1", [stmt("ac-2.1_smt.a", [bc(COMP_AUTH, "Automated account management.")])])
# ac-2.2: ORPHAN
add_impl("ac-2.2", [stmt("ac-2.2_smt.a", [bc(COMP_AUTH, "Temporary and emergency accounts.")])])
add_impl("ac-2.3", [stmt("ac-2.3_smt.a", [bc(COMP_AUTH, "Disables inactive accounts.")])])
add_impl("ac-2.4", [stmt("ac-2.4_smt.a", [bc(COMP_AUDIT, "Logs account management actions.")])])
add_impl("ac-3", [stmt("ac-3_smt.a", [bc(COMP_AUTH, "Enforces approved authorizations.")])])
add_impl("ac-4", [stmt("ac-4_smt.a", [bc(COMP_NETMON, "Enforces information flow control.")])])
# ac-5: NOT IMPLEMENTED — GAP
add_impl("ac-6", [
    stmt("ac-6_smt.a", [bc(COMP_AUTH, "Enforces least privilege.")]),
    stmt("ac-6_smt.b", [bc(COMP_AUTH, "Restricts privileged access.")]),
])
add_impl("ac-6.1", [stmt("ac-6.1_smt.a", [bc(COMP_AUTH, "Authorizes security function access.")])])
add_impl("ac-7", [
    stmt("ac-7_smt.a", [bc(COMP_AUTH, "Limits unsuccessful logon attempts.")]),
    stmt("ac-7_smt.b", [bc(COMP_AUTH, "Enforces account lockout.")]),
], params=[
    {"param-id": "ac-7_prm_1", "values": ["3"]},
    {"param-id": "ac-7_prm_2", "values": ["30 minutes"]}
])
add_impl("ac-8", [stmt("ac-8_smt.a", [bc(COMP_AUTH, "Displays system use notification.")])])

# au-1: MISSING statement b → statement coverage gap
add_impl("au-1", [
    stmt("au-1_smt.a", [
        bc(COMP_POLICY, "Defines audit and accountability policy."),
        bc(COMP_AUDIT, "Implements audit procedures.")
    ]),
], params=[
    {"param-id": "au-1_prm_1", "values": ["all organizational personnel"]},
    {"param-id": "au-1_prm_2", "values": ["at least annually"]},
    {"param-id": "au-1_prm_3", "values": ["at least annually"]}
])

add_impl("au-2", [
    stmt("au-2_smt.a", [bc(COMP_AUDIT, "Identifies event types for logging.")]),
    stmt("au-2_smt.b", [bc(COMP_AUDIT, "Coordinates event logging.")]),
], params=[{"param-id": "au-2_prm_1",
            "values": ["account logon events, policy changes, privilege usage"]}])

add_impl("au-3", [stmt("au-3_smt.a", [bc(COMP_AUDIT, "Generates audit records.")])])
# au-3.1: NOT IMPLEMENTED — GAP

add_impl("au-4", [stmt("au-4_smt.a", [bc(COMP_AUDIT, "Allocates log storage.")])])

# au-5: MISSING set-parameter au-5_prm_1 → parameter gap
add_impl("au-5", [
    stmt("au-5_smt.a", [bc(COMP_AUDIT, "Alerts on audit failures.")]),
    stmt("au-5_smt.b", [bc(COMP_AUDIT, "Takes action on failures.")]),
])

# au-6: MISSING set-parameter au-6_prm_2 → parameter gap
add_impl("au-6", [
    stmt("au-6_smt.a", [bc(COMP_AUDIT, "Reviews and analyzes audit records.")]),
    stmt("au-6_smt.b", [bc(COMP_AUDIT, "Reports findings to authorized personnel.")]),
], params=[{"param-id": "au-6_prm_1", "values": ["weekly"]}])

# au-6.1: NOT IMPLEMENTED — GAP
# au-6.3: ORPHAN
add_impl("au-6.3", [stmt("au-6.3_smt.a", [bc(COMP_AUDIT, "Correlates audit repositories.")])])

add_impl("si-1", [
    stmt("si-1_smt.a", [bc(COMP_POLICY, "Defines system integrity policy.")]),
    stmt("si-1_smt.b", [bc(COMP_POLICY, "Manages system integrity procedures.")]),
])
add_impl("si-2", [
    stmt("si-2_smt.a", [bc(COMP_EPP, "Identifies and remediates flaws.")]),
    stmt("si-2_smt.b", [bc(COMP_EPP, "Tests flaw remediation updates.")]),
])
add_impl("si-2.1", [stmt("si-2.1_smt.a", [bc(COMP_EPP, "Centralized flaw remediation.")])])

# si-3: broken component ref
add_impl("si-3", [
    stmt("si-3_smt.a", [bc(COMP_GHOST2, "Anti-malware integration.")]),
    stmt("si-3_smt.b", [bc(COMP_EPP, "Updates malware definitions.")]),
])
add_impl("si-3.1", [stmt("si-3.1_smt.a", [bc(COMP_EPP, "Central malware management.")])])

add_impl("si-4", [
    stmt("si-4_smt.a", [bc(COMP_NETMON, "Monitors for attacks.")]),
    stmt("si-4_smt.b", [bc(COMP_NETMON, "Identifies unauthorized use.")]),
    stmt("si-4_smt.c", [bc(COMP_NETMON, "Deploys monitoring at strategic points.")]),
])

# si-4.1: ORPHAN (excluded from profile)
add_impl("si-4.1", [stmt("si-4.1_smt.a", [bc(COMP_NETMON, "System-wide intrusion detection.")])])
add_impl("si-4.2", [stmt("si-4.2_smt.a", [bc(COMP_NETMON, "Automated real-time analysis.")])])
# si-4.4: NOT IMPLEMENTED — GAP

add_impl("si-5", [
    stmt("si-5_smt.a", [bc(COMP_NETMON, "Receives security alerts.")]),
    stmt("si-5_smt.b", [bc(COMP_NETMON, "Disseminates security advisories.")]),
])

ssp = {
    "system-security-plan": {
        "uuid": "c3d4e5f6-a7b8-4c9d-0e1f-2a3b4c5d6e7f",
        "metadata": {
            "title": "Enterprise Security Platform System Security Plan",
            "last-modified": "2025-10-15T09:00:00.000000-04:00",
            "version": "1.0.0",
            "oscal-version": "1.1.3",
            "roles": [
                {"id": "system-owner", "title": "System Owner"},
                {"id": "admin", "title": "System Administrator"},
                {"id": "ciso", "title": "Chief Information Security Officer"}
            ],
            "parties": [
                {"uuid": "aaaa0000-0000-4000-8000-000000000001",
                 "type": "organization", "name": "IT Security Division"},
                {"uuid": "aaaa0000-0000-4000-8000-000000000002",
                 "type": "organization", "name": "Compliance Team"}
            ]
        },
        "import-profile": {"href": "profile_moderate.json"},
        "system-characteristics": {
            "system-ids": [{"identifier-type": "https://ietf.org/rfc/rfc4122",
                            "id": "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a"}],
            "system-name": "Enterprise Security Platform",
            "description": "A comprehensive security platform.",
            "security-sensitivity-level": "moderate",
            "system-information": {
                "information-types": [{
                    "uuid": "e5f6a7b8-c9d0-4e1f-2a3b-4c5d6e7f8a9b",
                    "title": "Security Management Information",
                    "description": "Security posture management information.",
                    "confidentiality-impact": {"base": "fips-199-moderate"},
                    "integrity-impact": {"base": "fips-199-moderate"},
                    "availability-impact": {"base": "fips-199-low"}
                }]
            },
            "security-impact-level": {
                "security-objective-confidentiality": "fips-199-moderate",
                "security-objective-integrity": "fips-199-moderate",
                "security-objective-availability": "fips-199-low"
            },
            "status": {"state": "operational"},
            "authorization-boundary": {
                "description": "Enterprise security platform authorization boundary."
            }
        },
        "system-implementation": {
            "users": [
                {"uuid": "bbbb0000-0000-4000-8000-000000000001",
                 "title": "System Administrator", "role-ids": ["admin"]},
                {"uuid": "bbbb0000-0000-4000-8000-000000000002",
                 "title": "CISO", "role-ids": ["ciso"]},
                {"uuid": "bbbb0000-0000-4000-8000-000000000003",
                 "title": "System Owner", "role-ids": ["system-owner"]}
            ],
            "components": [
                {"uuid": COMP_AUTH, "type": "software",
                 "title": "Authentication Service",
                 "description": "Centralized authentication and authorization.",
                 "status": {"state": "operational"}},
                {"uuid": COMP_AUDIT, "type": "software",
                 "title": "Audit Logging Platform",
                 "description": "Enterprise audit logging and analysis.",
                 "status": {"state": "operational"}},
                {"uuid": COMP_POLICY, "type": "policy",
                 "title": "Security Policy Framework",
                 "description": "Organizational security policies.",
                 "status": {"state": "operational"}},
                {"uuid": COMP_EPP, "type": "software",
                 "title": "Endpoint Protection Suite",
                 "description": "Anti-malware and EDR.",
                 "status": {"state": "operational"}},
                {"uuid": COMP_NETMON, "type": "software",
                 "title": "Network Monitoring System",
                 "description": "Network IDS and monitoring.",
                 "status": {"state": "operational"}}
            ]
        },
        "control-implementation": {
            "description": "Control implementations for the Enterprise Security Platform.",
            "implemented-requirements": impl_reqs
        }
    }
}


# ═══════════════════════════════════════════════════════════════════════════
# Generate assessment_results.json
# ═══════════════════════════════════════════════════════════════════════════

FINDING_1 = "f1000001-0000-4000-8000-000000000001"
FINDING_2 = "f2000002-0000-4000-8000-000000000002"
FINDING_3 = "f3000003-0000-4000-8000-000000000003"
FINDING_4 = "f4000004-0000-4000-8000-000000000004"

RISK_1 = "d1000001-0000-4000-8000-000000000001"
RISK_2 = "d2000002-0000-4000-8000-000000000002"
RISK_3 = "d3000003-0000-4000-8000-000000000003"

OBS_1 = "b1000001-0000-4000-8000-000000000001"
OBS_2 = "b2000002-0000-4000-8000-000000000002"
OBS_3 = "b3000003-0000-4000-8000-000000000003"
OBS_4 = "b4000004-0000-4000-8000-000000000004"

assessment_results = {
    "assessment-results": {
        "uuid": "ec0dad37-54e0-40fd-a925-6d0bdea94c0d",
        "metadata": {
            "title": "Enterprise Security Platform Assessment Results",
            "last-modified": "2025-11-01T09:00:00.000000-04:00",
            "version": "1.0.0",
            "oscal-version": "1.1.3",
            "roles": [{"id": "assessor", "title": "Security Assessor"}],
            "parties": [{
                "uuid": "e7730080-71ce-4b20-bec4-84f33136fd58",
                "type": "person", "name": "Lead Assessor"
            }]
        },
        "import-ap": {"href": "#assessment-plan-ref"},
        "results": [{
            "uuid": "a1d20136-37e0-42aa-9834-4e9d8c36d798",
            "title": "Assessment Cycle Q4 2025",
            "description": "Quarterly continuous monitoring assessment results.",
            "start": "2025-10-01T08:00:00-04:00",
            "end": "2025-10-15T17:00:00-04:00",
            "reviewed-controls": {
                "control-selections": [{
                    "include-controls": [
                        {"control-id": "ac-2"},
                        {"control-id": "ac-6.1"},
                        {"control-id": "au-5"},
                        {"control-id": "si-3"},
                    ]
                }]
            },
            "observations": [
                {
                    "uuid": OBS_1,
                    "title": "AC-6.1 Least Privilege Authorization Test",
                    "description": "Tested authorization controls for security functions.",
                    "methods": ["TEST"],
                    "types": ["finding"],
                    "subjects": [{"subject-uuid": COMP_AUTH, "type": "component"}],
                    "collected": "2025-10-05T10:00:00-04:00",
                    "remarks": "System engineer role permits unauthorized security function access."
                },
                {
                    "uuid": OBS_2,
                    "title": "AU-5 Audit Failure Response Test",
                    "description": "Tested audit logging failure response mechanisms.",
                    "methods": ["TEST"],
                    "types": ["finding"],
                    "subjects": [{"subject-uuid": COMP_AUDIT, "type": "component"}],
                    "collected": "2025-10-06T11:00:00-04:00",
                    "remarks": "Audit failure alerts are not configured for all failure modes."
                },
                {
                    "uuid": OBS_3,
                    "title": "SI-3 Malicious Code Protection Test",
                    "description": "Tested malicious code protection mechanisms.",
                    "methods": ["TEST"],
                    "types": ["finding"],
                    "subjects": [{"subject-uuid": COMP_EPP, "type": "component"}],
                    "collected": "2025-10-07T14:00:00-04:00",
                    "remarks": "Anti-malware component references invalid system component."
                },
                {
                    "uuid": OBS_4,
                    "title": "AC-2 Account Management Examination",
                    "description": "Examined account management procedures.",
                    "methods": ["EXAMINE"],
                    "types": ["control-objective"],
                    "subjects": [{"subject-uuid": COMP_AUTH, "type": "component"}],
                    "collected": "2025-10-08T09:00:00-04:00",
                    "remarks": "Account management processes are properly implemented."
                }
            ],
            "risks": [
                {
                    "uuid": RISK_1,
                    "title": "Unauthorized Security Function Access",
                    "description": "System engineers can access security functions beyond their role.",
                    "statement": "Over-privileged access to security functions increases insider threat risk.",
                    "status": "open",
                    "characterizations": [{
                        "origin": {"actors": [{"type": "party",
                                               "actor-uuid": "e7730080-71ce-4b20-bec4-84f33136fd58"}]},
                        "facets": [
                            {"name": "likelihood", "system": "https://example.gov/risk",
                             "value": "moderate"},
                            {"name": "impact", "system": "https://example.gov/risk",
                             "value": "high"}
                        ]
                    }],
                    "related-observations": [{"observation-uuid": OBS_1}]
                },
                {
                    "uuid": RISK_2,
                    "title": "Incomplete Audit Failure Alerting",
                    "description": "Not all audit failure modes trigger alerts.",
                    "statement": "Incomplete alerting could mask security incidents.",
                    "status": "open",
                    "characterizations": [{
                        "origin": {"actors": [{"type": "party",
                                               "actor-uuid": "e7730080-71ce-4b20-bec4-84f33136fd58"}]},
                        "facets": [
                            {"name": "likelihood", "system": "https://example.gov/risk",
                             "value": "moderate"},
                            {"name": "impact", "system": "https://example.gov/risk",
                             "value": "moderate"}
                        ]
                    }],
                    "related-observations": [{"observation-uuid": OBS_2}]
                },
                {
                    "uuid": RISK_3,
                    "title": "Invalid Component Reference in Malware Protection",
                    "description": "SI-3 implementation references non-existent component.",
                    "statement": "Invalid component reference may indicate misconfigured protection.",
                    "status": "investigating",
                    "characterizations": [{
                        "origin": {"actors": [{"type": "party",
                                               "actor-uuid": "e7730080-71ce-4b20-bec4-84f33136fd58"}]},
                        "facets": [
                            {"name": "likelihood", "system": "https://example.gov/risk",
                             "value": "high"},
                            {"name": "impact", "system": "https://example.gov/risk",
                             "value": "high"}
                        ]
                    }],
                    "related-observations": [{"observation-uuid": OBS_3}]
                }
            ],
            "findings": [
                {
                    "uuid": FINDING_1,
                    "title": "AC-6.1 Authorization of Security Functions Deficiency",
                    "description": "System engineer role has unauthorized access to security functions.",
                    "target": {
                        "type": "objective-id",
                        "target-id": "ac-6.1_obj",
                        "title": "Authorize Access to Security Functions",
                        "status": {"state": "not-satisfied"}
                    },
                    "related-observations": [{"observation-uuid": OBS_1}],
                    "related-risks": [{"risk-uuid": RISK_1}]
                },
                {
                    "uuid": FINDING_2,
                    "title": "AU-5 Audit Failure Response Deficiency",
                    "description": "Audit failure alerts are incomplete.",
                    "target": {
                        "type": "objective-id",
                        "target-id": "au-5_obj",
                        "title": "Response to Audit Logging Process Failures",
                        "status": {"state": "not-satisfied"}
                    },
                    "related-observations": [{"observation-uuid": OBS_2}],
                    "related-risks": [{"risk-uuid": RISK_2}]
                },
                {
                    "uuid": FINDING_3,
                    "title": "SI-3 Malicious Code Protection Configuration Issue",
                    "description": "Anti-malware component references invalid system component.",
                    "target": {
                        "type": "objective-id",
                        "target-id": "si-3_obj",
                        "title": "Malicious Code Protection",
                        "status": {"state": "not-satisfied"}
                    },
                    "related-observations": [{"observation-uuid": OBS_3}],
                    "related-risks": [{"risk-uuid": RISK_3}]
                },
                {
                    "uuid": FINDING_4,
                    "title": "AC-2 Account Management Satisfactory",
                    "description": "Account management procedures are properly implemented.",
                    "target": {
                        "type": "objective-id",
                        "target-id": "ac-2_obj",
                        "title": "Account Management",
                        "status": {"state": "satisfied"}
                    },
                    "related-observations": [{"observation-uuid": OBS_4}]
                }
            ]
        }]
    }
}


# ═══════════════════════════════════════════════════════════════════════════
# Generate poam.json
# ═══════════════════════════════════════════════════════════════════════════

POAM_1 = "e1000001-0000-4000-8000-000000000001"
POAM_2 = "e2000002-0000-4000-8000-000000000002"
POAM_3 = "e3000003-0000-4000-8000-000000000003"
GHOST_RISK = "d9000099-0000-4000-8000-000000000099"

poam = {
    "plan-of-action-and-milestones": {
        "uuid": "4a202b62-38e0-40ac-9bf0-d595d5df7c28",
        "metadata": {
            "title": "Enterprise Security Platform POA&M",
            "last-modified": "2025-11-15T10:00:00.000000-04:00",
            "version": "1.0.0",
            "oscal-version": "1.1.3"
        },
        "import-ssp": {"href": "ssp.json"},
        "system-id": {
            "identifier-type": "https://ietf.org/rfc/rfc4122",
            "id": "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a"
        },
        "poam-items": [
            {
                "uuid": POAM_1,
                "title": "Remediate Unauthorized Security Function Access (AC-6.1)",
                "description": "Restrict system engineer role to remove unauthorized "
                               "security function access per AC-6.1 requirements.",
                "props": [
                    {"name": "status", "value": "open"}
                ],
                "related-observations": [{"observation-uuid": OBS_1}],
                "related-risks": [{"risk-uuid": RISK_1}]
            },
            {
                "uuid": POAM_2,
                "title": "Fix Invalid Component Reference in SI-3 Implementation",
                "description": "Update SI-3 implementation to reference valid system "
                               "component for malicious code protection.",
                "props": [
                    {"name": "status", "value": "investigating"}
                ],
                "related-observations": [{"observation-uuid": OBS_3}],
                "related-risks": [{"risk-uuid": RISK_3}]
            },
            {
                "uuid": POAM_3,
                "title": "Legacy Remediation Item from Previous Assessment",
                "description": "Carried forward from previous assessment cycle. "
                               "References findings no longer in current results.",
                "props": [
                    {"name": "status", "value": "open"}
                ],
                "related-risks": [{"risk-uuid": GHOST_RISK}]
            }
        ]
    }
}


# ═══════════════════════════════════════════════════════════════════════════
# Write all files
# ═══════════════════════════════════════════════════════════════════════════

os.makedirs("/app", exist_ok=True)

# Write XML catalog
tree = generate_catalog_xml()
tree.write("/app/catalog.xml", encoding="unicode", xml_declaration=True)

# Write JSON files
for name, data in [
    ("profile_low.json", profile_low),
    ("profile_moderate.json", profile_moderate),
    ("ssp.json", ssp),
    ("assessment_results.json", assessment_results),
    ("poam.json", poam),
]:
    with open(f"/app/{name}", "w") as f:
        json.dump(data, f, indent=2)

print("Generated: catalog.xml, profile_low.json, profile_moderate.json, "
      "ssp.json, assessment_results.json, poam.json in /app/")
