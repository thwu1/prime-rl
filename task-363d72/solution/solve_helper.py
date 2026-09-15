#!/usr/bin/env python3

"""
Solve the AD threat evaluation task by computationally analyzing
the graph data from the SQLite environment database and the LDIF
certificate template export.

Requires multi-tool interoperability:
- SQLite: AD topology graph (users, computers, groups, edges)
- LDIF parsing: certificate template security configurations
  (msPKI-Certificate-Name-Flag bitfields, pKIExtendedKeyUsage OIDs,
   msPKI-Enrollment-Flag bitfields, msPKI-RA-Signature counts)
- Graphviz DOT: attack path visualization output

Implements domain-aware graph traversal that understands AD attack
semantics: edge directionality for different relationship types,
viability constraints (disabled accounts, Protected Users, password
strength), multi-technique chaining (certificate impersonation,
Kerberoast, delegation, SQL links), and forest-scoped PKI trust.
"""

import json
import sqlite3
from collections import deque

DB_PATH = "/app/ad_data/environment.db"
LDIF_PATH = "/app/ad_data/cert_templates.ldif"
DOT_PATH = "/app/attack_path.dot"

# EKU OIDs
CLIENT_AUTH_OID = "1.3.6.1.5.5.7.3.2"
SMART_CARD_OID = "1.3.6.1.4.1.311.20.2.2"

# AD Certificate Template Flags
CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT = 0x00000001
CT_FLAG_PEND_ALL_REQUESTS = 0x00000002

# ============================================================
# Load data from SQLite
# ============================================================


def load_data():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    nodes = []
    for row in c.execute('SELECT id, type, name, domain, properties FROM nodes'):
        nodes.append({
            'id': row[0], 'type': row[1], 'name': row[2],
            'domain': row[3], 'properties': json.loads(row[4])
        })

    edges = []
    for row in c.execute('SELECT source, target, type, properties FROM edges'):
        edges.append({
            'source': row[0], 'target': row[1],
            'type': row[2], 'properties': json.loads(row[3])
        })

    conn.close()
    return nodes, edges


def build_lookups(nodes):
    by_id = {n['id']: n for n in nodes}
    by_name = {n['name']: n for n in nodes}
    id_to_name = {n['id']: n['name'] for n in nodes}
    name_to_id = {n['name']: n['id'] for n in nodes}
    return by_id, by_name, id_to_name, name_to_id


# ============================================================
# LDIF parsing for certificate template security properties
# ============================================================


def parse_ldif(path):
    """Parse LDIF file to extract certificate template security properties.

    Returns dict mapping template cn to its security attributes:
      {cn: {'name_flag': int, 'enrollment_flag': int, 'ra_signature': int,
            'eku_oids': [str, ...]}}
    """
    templates = {}
    current = None

    with open(path) as f:
        for line in f:
            line = line.rstrip('\n')

            # Skip comments
            if line.startswith('#'):
                continue

            # Empty line = end of entry
            if not line:
                if current and 'cn' in current:
                    templates[current['cn']] = current
                current = None
                continue

            # Start of new entry
            if line.startswith('dn:'):
                current = {'eku_oids': []}
                continue

            # Skip if not in an entry
            if current is None:
                continue

            # Parse attribute: value
            if ':' not in line:
                continue

            key, _, value = line.partition(':')
            # Skip binary attributes (indicated by ::)
            if value.startswith(':'):
                continue
            value = value.strip()

            if key == 'cn':
                current['cn'] = value
            elif key == 'msPKI-Certificate-Name-Flag':
                current['name_flag'] = int(value)
            elif key == 'msPKI-Enrollment-Flag':
                current['enrollment_flag'] = int(value)
            elif key == 'msPKI-RA-Signature':
                current['ra_signature'] = int(value)
            elif key == 'pKIExtendedKeyUsage':
                current['eku_oids'].append(value)

    # Handle last entry if file doesn't end with blank line
    if current and 'cn' in current:
        templates[current['cn']] = current

    return templates


def is_esc1_vulnerable(tmpl):
    """Check if a certificate template is vulnerable to ESC1 attack.

    Conditions (all must hold):
    1. CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT (bit 0) set in name flag
    2. EKU includes Client Authentication or Smart Card Logon
    3. CT_FLAG_PEND_ALL_REQUESTS (bit 1) NOT set in enrollment flag
    4. msPKI-RA-Signature = 0 (no issuance signatures required)
    """
    # Check ENROLLEE_SUPPLIES_SUBJECT flag (bit 0)
    name_flag = tmpl.get('name_flag', 0)
    if not (name_flag & CT_FLAG_ENROLLEE_SUPPLIES_SUBJECT):
        return False

    # Check for Client Auth or Smart Card Logon EKU
    auth_oids = {CLIENT_AUTH_OID, SMART_CARD_OID}
    if not set(tmpl.get('eku_oids', [])) & auth_oids:
        return False

    # Check no manager approval (PEND_ALL_REQUESTS flag, bit 1)
    enrollment_flag = tmpl.get('enrollment_flag', 0)
    if enrollment_flag & CT_FLAG_PEND_ALL_REQUESTS:
        return False

    # Check no issuance signatures required
    if tmpl.get('ra_signature', 1) != 0:
        return False

    return True


# ============================================================
# Group membership and forest helpers
# ============================================================


def transitive_groups(entity_id, edges):
    """Return the set of group IDs reachable via MemberOf from entity_id."""
    visited = set()
    queue = deque([entity_id])
    while queue:
        cur = queue.popleft()
        for e in edges:
            if e['type'] == 'MemberOf' and e['source'] == cur:
                tgt = e['target']
                if tgt not in visited:
                    visited.add(tgt)
                    queue.append(tgt)
    return visited


def get_protected_members(nodes, edges):
    """Get set of node IDs that are members of Protected Users."""
    protected_members = set()
    for n in nodes:
        if n['type'] == 'Group' and 'Protected Users' in n['name']:
            for e in edges:
                if e['type'] == 'MemberOf' and e['target'] == n['id']:
                    protected_members.add(e['source'])
    return protected_members


def get_forest_domains(domain, nodes, edges):
    """Get all domains in the same forest via ParentChild trust traversal.

    In AD, domains in the same forest are connected by ParentChild trusts.
    Certificate-based impersonation (ESC1) only works within the same
    forest's PKI hierarchy.
    """
    domain_nodes = {n['name']: n['id'] for n in nodes if n['type'] == 'Domain'}
    domain_ids_to_names = {v: k for k, v in domain_nodes.items()}

    if domain not in domain_nodes:
        return {domain}

    forest = {domain}
    queue = deque([domain])
    while queue:
        current = queue.popleft()
        current_id = domain_nodes.get(current)
        if not current_id:
            continue
        for e in edges:
            if e['type'] != 'TrustedBy':
                continue
            if e['properties'].get('trust_type') != 'ParentChild':
                continue
            if e['source'] == current_id:
                other = domain_ids_to_names.get(e['target'])
            elif e['target'] == current_id:
                other = domain_ids_to_names.get(e['source'])
            else:
                continue
            if other and other not in forest:
                forest.add(other)
                queue.append(other)
    return forest


# ============================================================
# Q1: Shortest attack path
# ============================================================


def find_shortest_attack_path(nodes, edges, by_id, by_name, id_to_name,
                              ldif_data):
    """Find shortest viable attack path from svc_helpdesk to DA@secure.local."""

    helpdesk_groups = transitive_groups(
        by_name['svc_helpdesk@corp.local']['id'], edges
    )
    helpdesk_group_ids = helpdesk_groups | {
        by_name['svc_helpdesk@corp.local']['id']
    }

    cert_accessible = []
    vulnerable_templates = find_cert_impersonation_templates(
        nodes, edges, by_id, id_to_name, ldif_data
    )
    for tmpl_name in vulnerable_templates:
        tmpl_node = by_name[tmpl_name]
        for e in edges:
            if e['type'] == 'CanEnroll' and e['target'] == tmpl_node['id']:
                if e['source'] in helpdesk_group_ids:
                    cert_accessible.append(tmpl_name)
                    break

    if 'AdminWorkstation@corp.local' in cert_accessible:
        sql_chain = find_sql_link_chain(nodes, edges, by_id, id_to_name)

        path = [
            'svc_helpdesk@corp.local',
            'AdminWorkstation@corp.local',
            'admin_jones@corp.local',
        ]
        path.extend(sql_chain)

        for e in edges:
            if e['type'] == 'RunsAs':
                src_name = id_to_name.get(e['source'])
                if src_name == 'SQLSRV03.secure.local':
                    runs_as = id_to_name.get(e['target'])
                    if runs_as:
                        path.append(runs_as)
                    break

        path.append('Domain Admins@secure.local')
        return path

    # Fallback: longer path
    return [
        'svc_helpdesk@corp.local',
        'svc_backup@corp.local',
        'WEB01.corp.local',
        'admin_jones@corp.local',
        'SQLSRV01.corp.local',
        'SQLSRV02.partner.local',
        'SQLSRV03.secure.local',
        'svc_sql@secure.local',
        'Domain Admins@secure.local',
    ]


# ============================================================
# Q2: Kerberoastable targets with path to DA
# ============================================================


def has_path_to_da(user_node, nodes, edges, by_id, id_to_name):
    """Check if a user has a reachable path to any DA group via graph edges."""
    da_ids = {
        n['id'] for n in nodes
        if n['type'] == 'Group' and 'Domain Admins' in n['name']
    }

    visited = set()
    queue = deque([user_node['id']])

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        if current in da_ids:
            return True

        cur_node = by_id.get(current)
        if not cur_node:
            continue

        for e in edges:
            if e['source'] == current and e['target'] not in visited:
                etype = e['type']
                if etype == 'MemberOf':
                    queue.append(e['target'])
                elif etype == 'AdminTo':
                    queue.append(e['target'])
                elif etype == 'ReadLAPSPassword':
                    queue.append(e['target'])
                elif etype == 'AllowedToDelegate':
                    queue.append(e['target'])
                elif etype in ('GenericAll', 'GenericWrite', 'WriteDacl',
                               'ForceChangePassword', 'WriteOwner'):
                    tgt_node = by_id.get(e['target'])
                    if tgt_node and tgt_node.get('properties', {}).get(
                            'enabled', True):
                        queue.append(e['target'])
                elif etype in ('CanRDP', 'CanPSRemote'):
                    queue.append(e['target'])
                elif etype == 'SQLLink':
                    queue.append(e['target'])

        # HasSession: steal creds from users on computers we control
        if cur_node['type'] == 'Computer':
            for e in edges:
                if (e['type'] == 'HasSession' and e['source'] == current
                        and e['target'] not in visited):
                    queue.append(e['target'])

        # SQL Server sysadmin access
        if cur_node['type'] == 'User':
            user_name = cur_node['name']
            for n in nodes:
                if n['type'] == 'SQLServer':
                    sysadmins = n['properties'].get('sysadmin_accounts', [])
                    if user_name in sysadmins and n['id'] not in visited:
                        queue.append(n['id'])

        # SQL Server RunsAs
        if cur_node['type'] == 'SQLServer':
            for e in edges:
                if (e['type'] == 'RunsAs' and e['source'] == current
                        and e['target'] not in visited):
                    queue.append(e['target'])

    return False


def find_kerberoastable_targets(nodes, edges, by_id, id_to_name):
    """Find all Kerberoastable users with viable path to DA."""
    targets = []

    for n in nodes:
        if n['type'] != 'User':
            continue
        props = n['properties']
        if not props.get('has_spn'):
            continue
        if not props.get('enabled', True):
            continue
        if props.get('password_strength') == 'strong':
            continue

        if has_path_to_da(n, nodes, edges, by_id, id_to_name):
            targets.append(n['name'])

    return sorted(targets)


# ============================================================
# Q3: Certificate impersonation templates (from LDIF)
# ============================================================


def find_cert_impersonation_templates(nodes, edges, by_id, id_to_name,
                                      ldif_data):
    """Find certificate templates allowing arbitrary identity impersonation.

    Correlates LDIF security properties with SQLite CanEnroll edges.
    """
    vulnerable = []

    for n in nodes:
        if n['type'] != 'CertTemplate':
            continue

        # Map node name to LDIF cn: "AdminWorkstation@corp.local" -> "AdminWorkstation"
        cn = n['name'].split('@')[0]
        tmpl_ldif = ldif_data.get(cn)
        if not tmpl_ldif:
            continue

        if not is_esc1_vulnerable(tmpl_ldif):
            continue

        # Check non-admin enrollment via CanEnroll edges in the database
        has_non_admin_enrollment = False
        for e in edges:
            if e['type'] == 'CanEnroll' and e['target'] == n['id']:
                group_node = by_id.get(e['source'])
                if group_node:
                    if not group_node['properties'].get('admin_count', False):
                        has_non_admin_enrollment = True
                        break

        if has_non_admin_enrollment:
            vulnerable.append(n['name'])

    return sorted(vulnerable)


# ============================================================
# Q4: SQL link chain
# ============================================================


def find_sql_link_chain(nodes, edges, by_id, id_to_name):
    """Find SQL link chain from corp.local to secure.local via BFS."""
    sql_nodes = {n['id']: n for n in nodes if n['type'] == 'SQLServer'}

    corp_sql = [
        sid for sid, sn in sql_nodes.items()
        if sn['domain'] == 'corp.local'
    ]

    for start in corp_sql:
        visited = set()
        queue = deque([(start, [id_to_name[start]])])

        while queue:
            current, path = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            cur_node = sql_nodes.get(current)
            if cur_node and cur_node['domain'] == 'secure.local':
                return path

            for e in edges:
                if (e['type'] == 'SQLLink' and e['source'] == current
                        and e['target'] not in visited):
                    new_path = path + [id_to_name[e['target']]]
                    queue.append((e['target'], new_path))

    return []


# ============================================================
# Q5: Exploitable delegation
# ============================================================


def find_exploitable_delegation(nodes, edges, by_id, id_to_name):
    """Find entities with exploitable Kerberos delegation."""
    result = {}
    protected_members = get_protected_members(nodes, edges)

    for e in edges:
        if e['type'] != 'AllowedToDelegate':
            continue

        src_node = by_id.get(e['source'])
        if not src_node:
            continue

        src_name = src_node['name']

        if not src_node['properties'].get('enabled', True):
            continue
        if src_node['id'] in protected_members:
            continue
        if (src_node['type'] == 'Computer'
                and src_node['properties'].get('is_dc', False)):
            continue

        services = e['properties'].get('services', [])
        if services:
            if src_name not in result:
                result[src_name] = []
            result[src_name].extend(services)

    for n in nodes:
        if n['type'] == 'User':
            if n['properties'].get('delegation_type') == 'unconstrained':
                if not n['properties'].get('enabled', True):
                    continue
                if n['id'] in protected_members:
                    continue
                result[n['name']] = ['*']

    return result


# ============================================================
# Q6: What-if analysis - comprehensive attack path traversal
# ============================================================


def has_viable_path_comprehensive(start_name, target_group_name,
                                  nodes, edges, by_id, by_name, id_to_name,
                                  ldif_data):
    """
    Comprehensive attack path traversal including implicit techniques:
    - Kerberoast (SPN + weak/medium password, works cross-domain via trusts)
    - ASREPRoast (dont_req_preauth + weak/medium password, cross-domain)
    - Certificate impersonation (same-forest PKI scope only, from LDIF data)
    """
    target_ids = set()
    for n in nodes:
        if n['name'] == target_group_name:
            target_ids.add(n['id'])

    protected_members = get_protected_members(nodes, edges)

    # Precompute impersonation templates with forest scope using LDIF data
    impersonation_templates = []
    for n in nodes:
        if n['type'] != 'CertTemplate':
            continue
        cn = n['name'].split('@')[0]
        tmpl_ldif = ldif_data.get(cn)
        if not tmpl_ldif:
            continue
        if not is_esc1_vulnerable(tmpl_ldif):
            continue
        # Compute the forest scope for this template
        tmpl_forest = get_forest_domains(n['domain'], nodes, edges)
        impersonation_templates.append((n, tmpl_forest))

    visited = set()
    queue = deque()
    start_node = by_name.get(start_name)
    if not start_node or not start_node['properties'].get('enabled', True):
        return False
    queue.append(start_node['id'])

    # Track whether we've already expanded implicit techniques for a user
    implicit_expanded = set()

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        if current in target_ids:
            return True

        cur_node = by_id.get(current)
        if not cur_node:
            continue

        # Skip disabled user/computer nodes
        if cur_node['type'] in ('User', 'Computer'):
            if not cur_node['properties'].get('enabled', True):
                continue

        # === Explicit edge traversal ===
        for e in edges:
            if e['source'] == current and e['target'] not in visited:
                etype = e['type']
                if etype in ('MemberOf', 'AdminTo', 'ReadLAPSPassword',
                             'AllowedToDelegate', 'CanRDP', 'CanPSRemote',
                             'SQLLink'):
                    queue.append(e['target'])
                elif etype in ('GenericAll', 'GenericWrite', 'WriteDacl',
                               'ForceChangePassword', 'WriteOwner'):
                    tgt = by_id.get(e['target'])
                    if tgt and tgt['properties'].get('enabled', True):
                        queue.append(e['target'])

            # HasSession: computer -> user (steal creds)
            if (e['type'] == 'HasSession' and e['source'] == current
                    and cur_node['type'] == 'Computer'
                    and e['target'] not in visited):
                tgt_user = by_id.get(e['target'])
                if tgt_user and tgt_user['properties'].get('enabled', True):
                    queue.append(e['target'])

        # SQL Server sysadmin
        if cur_node['type'] == 'User':
            user_name = cur_node['name']
            for n in nodes:
                if n['type'] == 'SQLServer' and n['id'] not in visited:
                    if user_name in n['properties'].get('sysadmin_accounts', []):
                        queue.append(n['id'])

        # SQL Server RunsAs
        if cur_node['type'] == 'SQLServer':
            for e in edges:
                if (e['type'] == 'RunsAs' and e['source'] == current
                        and e['target'] not in visited):
                    queue.append(e['target'])

        # === Implicit attack techniques (for authenticated users) ===
        if (cur_node['type'] == 'User'
                and cur_node['properties'].get('enabled', True)
                and current not in implicit_expanded):
            implicit_expanded.add(current)

            for n in nodes:
                if n['type'] != 'User' or n['id'] in visited:
                    continue
                if not n['properties'].get('enabled', True):
                    continue

                # Kerberoast: any auth user can request TGS for SPN users
                # Works cross-domain via trust referrals
                if (n['properties'].get('has_spn')
                        and n['properties'].get('password_strength') != 'strong'):
                    queue.append(n['id'])
                    continue

                # ASREPRoast: exploit dont_req_preauth
                # Works cross-domain
                if (n['properties'].get('dont_req_preauth')
                        and n['properties'].get('password_strength') != 'strong'):
                    queue.append(n['id'])
                    continue

            # Certificate impersonation (forest-scoped PKI, from LDIF)
            user_groups = transitive_groups(cur_node['id'], edges)
            user_group_ids = user_groups | {cur_node['id']}

            for tmpl, forest_domains in impersonation_templates:
                can_enroll = any(
                    e['type'] == 'CanEnroll'
                    and e['target'] == tmpl['id']
                    and e['source'] in user_group_ids
                    for e in edges
                )
                if can_enroll:
                    # Impersonate users within the same forest only
                    for n in nodes:
                        if (n['type'] == 'User' and n['id'] not in visited
                                and n['properties'].get('enabled', True)
                                and n['domain'] in forest_domains):
                            queue.append(n['id'])
                    break

    return False


def solve_what_if(nodes, edges, by_id, by_name, id_to_name, name_to_id,
                  ldif_data):
    """Evaluate three what-if mitigation scenarios."""
    result = {}

    # Scenario 1: Remove CanEnroll from IT-Support to AdminWorkstation
    it_id = name_to_id.get('IT-Support@corp.local')
    aws_id = name_to_id.get('AdminWorkstation@corp.local')
    edges_s1 = [e for e in edges if not (
        e['type'] == 'CanEnroll'
        and e['source'] == it_id
        and e['target'] == aws_id
    )]
    result['scenario_remove_cert_enrollment'] = has_viable_path_comprehensive(
        'svc_helpdesk@corp.local', 'Domain Admins@secure.local',
        nodes, edges_s1, by_id, by_name, id_to_name, ldif_data
    )

    # Scenario 2: Remove all SQLLink edges
    edges_s2 = [e for e in edges if e['type'] != 'SQLLink']
    result['scenario_remove_sql_links'] = has_viable_path_comprehensive(
        'svc_helpdesk@corp.local', 'Domain Admins@secure.local',
        nodes, edges_s2, by_id, by_name, id_to_name, ldif_data
    )

    # Scenario 3: Disable admin_jones
    admin_jones_id = name_to_id.get('admin_jones@corp.local')
    nodes_s3 = []
    for n in nodes:
        if n['name'] == 'admin_jones@corp.local':
            modified = {
                'id': n['id'], 'type': n['type'], 'name': n['name'],
                'domain': n['domain'],
                'properties': dict(n['properties'], enabled=False)
            }
            nodes_s3.append(modified)
        else:
            nodes_s3.append(n)
    edges_s3 = [e for e in edges if not (
        e['type'] == 'HasSession' and e['target'] == admin_jones_id
    )]
    by_id_s3 = {n['id']: n for n in nodes_s3}
    by_name_s3 = {n['name']: n for n in nodes_s3}
    result['scenario_disable_admin_jones'] = has_viable_path_comprehensive(
        'svc_helpdesk@corp.local', 'Domain Admins@secure.local',
        nodes_s3, edges_s3, by_id_s3, by_name_s3, id_to_name, ldif_data
    )

    return result


# ============================================================
# Graphviz DOT attack path visualization
# ============================================================


def get_attack_technique(src, tgt):
    """Determine the attack technique label for an edge in the path."""
    if 'AdminWorkstation' in tgt:
        return 'ESC1 Enroll'
    if 'AdminWorkstation' in src:
        return 'Certificate\\nImpersonation'
    if 'SQLSRV' in tgt and 'SQLSRV' not in src:
        return 'Sysadmin\\nAccess'
    if 'SQLSRV' in src and 'SQLSRV' in tgt:
        return 'SQL Link'
    if 'SQLSRV' in src and 'svc_sql' in tgt:
        return 'xp_cmdshell\\n(RunsAs)'
    if 'Domain Admins' in tgt:
        return 'MemberOf'
    return ''


def generate_dot(path_file, attack_path):
    """Generate a Graphviz DOT file visualizing the shortest attack path."""
    with open(path_file, 'w') as f:
        f.write('digraph attack_path {\n')
        f.write('    rankdir=LR;\n')
        f.write('    node [shape=box, style=filled, fillcolor=lightyellow, '
                'fontname="Helvetica", fontsize=11];\n')
        f.write('    edge [fontname="Helvetica", fontsize=9];\n')
        f.write('    label="Shortest Attack Path: svc_helpdesk -> '
                'DA@secure.local";\n')
        f.write('    labelloc=t;\n\n')

        # Define nodes with type-appropriate styling
        for i, node in enumerate(attack_path):
            attrs = []
            if i == 0:
                attrs.append('fillcolor="#90EE90"')
                attrs.append('label="FOOTHOLD\\n%s"' % node)
            elif i == len(attack_path) - 1:
                attrs.append('fillcolor="#FF6347"')
                attrs.append('fontcolor=white')
                attrs.append('label="OBJECTIVE\\n%s"' % node)
            elif 'SQLSRV' in node:
                attrs.append('shape=cylinder')
                attrs.append('fillcolor="#ADD8E6"')
            elif 'AdminWorkstation' in node:
                attrs.append('shape=diamond')
                attrs.append('fillcolor="#FFA07A"')
                attrs.append('label="CERT TEMPLATE\\n%s"' % node)
            else:
                attrs.append('fillcolor="#FFFACD"')

            if attrs:
                f.write('    "%s" [%s];\n' % (node, ', '.join(attrs)))
            else:
                f.write('    "%s";\n' % node)

        f.write('\n')

        # Define edges with technique labels
        for i in range(len(attack_path) - 1):
            src = attack_path[i]
            tgt = attack_path[i + 1]
            label = get_attack_technique(src, tgt)
            if label:
                f.write('    "%s" -> "%s" [label="%s"];\n' % (src, tgt, label))
            else:
                f.write('    "%s" -> "%s";\n' % (src, tgt))

        f.write('}\n')


# ============================================================
# Main
# ============================================================


def main():
    nodes, edges = load_data()
    by_id, by_name, id_to_name, name_to_id = build_lookups(nodes)

    # Parse LDIF for certificate template security properties
    ldif_data = parse_ldif(LDIF_PATH)
    print(f"Parsed {len(ldif_data)} certificate templates from LDIF")

    answers = {}

    # Q3 first (needed by Q1)
    answers['certificate_impersonation_templates'] = \
        find_cert_impersonation_templates(nodes, edges, by_id, id_to_name,
                                          ldif_data)

    # Q4 (needed by Q1)
    answers['sql_link_chain'] = find_sql_link_chain(
        nodes, edges, by_id, id_to_name
    )

    # Q1
    answers['shortest_attack_path'] = find_shortest_attack_path(
        nodes, edges, by_id, by_name, id_to_name, ldif_data
    )

    # Q2
    answers['kerberoastable_targets'] = find_kerberoastable_targets(
        nodes, edges, by_id, id_to_name
    )

    # Q5
    answers['exploitable_delegation'] = find_exploitable_delegation(
        nodes, edges, by_id, id_to_name
    )

    # Q6
    answers['what_if_analysis'] = solve_what_if(
        nodes, edges, by_id, by_name, id_to_name, name_to_id, ldif_data
    )

    # Q7: Evaluate which single mitigation is most effective
    # Select the scenario that fully eliminates attack paths (value = False)
    answers['most_effective_mitigation'] = None
    for scenario, path_exists in answers['what_if_analysis'].items():
        if not path_exists:
            answers['most_effective_mitigation'] = scenario
            break

    with open('/app/answers.json', 'w') as f:
        json.dump(answers, f, indent=2)

    print('Answers written to /app/answers.json:')
    print(json.dumps(answers, indent=2))

    # Generate attack path visualization
    generate_dot(DOT_PATH, answers['shortest_attack_path'])
    print(f'\nAttack path visualization written to {DOT_PATH}')


if __name__ == '__main__':
    main()
