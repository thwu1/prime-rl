#!/usr/bin/env python3
"""Generate synthetic data for the SAST Compliance Audit Pipeline task."""
import random
import json
import csv
import os
import datetime

random.seed(42)

# ============ Categories ============
CATEGORIES = [
    ('cmdi', 78),
    ('crypto', 327),
    ('hash', 328),
    ('pathtraver', 22),
    ('sqli', 89),
    ('xss', 79),
    ('weakrand', 330),
    ('ldapi', 90),
]

# ============ CWE Hierarchy Tree ============
CWE_TREE = {
    20: {
        'name': 'Improper Input Validation',
        'children': {
            74: {
                'name': 'Injection',
                'children': {
                    77: {
                        'name': 'Command Injection',
                        'children': {
                            78: {'name': 'OS Command Injection', 'children': {}}
                        }
                    },
                    79: {'name': 'Cross-site Scripting', 'children': {}},
                    89: {
                        'name': 'SQL Injection',
                        'children': {
                            564: {'name': 'SQL Injection Hibernate', 'children': {}},
                            943: {'name': 'Improper Neutralization in Data Query Logic', 'children': {}}
                        }
                    },
                    90: {'name': 'LDAP Injection', 'children': {}},
                    91: {
                        'name': 'XML Injection',
                        'children': {
                            643: {'name': 'XPath Injection', 'children': {}}
                        }
                    }
                }
            },
            22: {
                'name': 'Path Traversal',
                'children': {
                    23: {'name': 'Relative Path Traversal', 'children': {}},
                    36: {'name': 'Absolute Path Traversal', 'children': {}}
                }
            }
        }
    },
    310: {
        'name': 'Cryptographic Issues',
        'children': {
            326: {'name': 'Inadequate Encryption Strength', 'children': {}},
            327: {
                'name': 'Use of Broken or Risky Cryptographic Algorithm',
                'children': {
                    328: {'name': 'Use of Weak Hash', 'children': {}},
                    780: {'name': 'Use of RSA Algorithm without OAEP', 'children': {}}
                }
            },
            330: {
                'name': 'Use of Insufficiently Random Values',
                'children': {
                    338: {'name': 'Use of Cryptographically Weak PRNG', 'children': {}},
                    340: {'name': 'Generation of Predictable Numbers or Identifiers', 'children': {}}
                }
            }
        }
    }
}


def write_cwe_hierarchy_xml(tree, filepath):
    """Write CWE hierarchy as namespace-qualified XML."""
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<cwe_catalog xmlns="urn:mitre:cwe:hierarchy:1.0" version="4.13">')

    def write_node(cwe_id, node, indent=2):
        spaces = ' ' * indent
        name_esc = node['name'].replace('&', '&amp;').replace('"', '&quot;')
        children = node.get('children', {})
        if children:
            lines.append(f'{spaces}<cwe id="{cwe_id}" name="{name_esc}">')
            lines.append(f'{spaces}  <children>')
            for child_id in sorted(children.keys()):
                write_node(child_id, children[child_id], indent + 4)
            lines.append(f'{spaces}  </children>')
            lines.append(f'{spaces}</cwe>')
        else:
            lines.append(f'{spaces}<cwe id="{cwe_id}" name="{name_esc}"/>')

    for root_id in sorted(tree.keys()):
        write_node(root_id, tree[root_id])

    lines.append('</cwe_catalog>')
    with open(filepath, 'w') as f:
        f.write('\n'.join(lines) + '\n')


# ============ Generate test cases ============
test_cases = []
tc_id = 1
for cat_name, cwe in CATEGORIES:
    for is_vuln in [True, False]:
        count = 30 if is_vuln else 28
        for _ in range(count):
            test_cases.append({
                'name': f'TestCase{tc_id:05d}',
                'category': cat_name,
                'is_vuln': is_vuln,
                'cwe': cwe,
            })
            tc_id += 1

random.shuffle(test_cases)

# ============ Tool profiles ============
# Wrong-CWE noise uses CWEs from opposite branch so hierarchy never matches
UNRELATED_CWES = {
    78:  [327, 328, 330],
    327: [78, 79, 89],
    328: [78, 79, 89],
    22:  [327, 328, 330],
    89:  [327, 328, 330],
    79:  [327, 328, 330],
    330: [78, 79, 89],
    90:  [327, 328, 330],
}

TOOL_PROFILES = {
    'scanner_a': {
        'tpr': 0.80, 'fpr': 0.12,
        'fpr_overrides': {'weakrand': 0.42},
        'cwe_mutations': {
            78: [(77, 0.15)],
            89: [(564, 0.20)],
            328: [(327, 0.10)],
        }
    },
    'scanner_b': {
        'tpr': 0.65, 'fpr': 0.22,
        'fpr_overrides': {'xss': 0.54},
        'cwe_mutations': {
            89: [(74, 0.12)],
            328: [(327, 0.30)],
        }
    },
    'scanner_c': {
        'tpr': 0.90, 'fpr': 0.08,
        'fpr_overrides': {},
        'cwe_mutations': {
            328: [(327, 0.25)],
            89: [(943, 0.08)],
        }
    },
    'scanner_d': {
        'tpr': 0.72, 'fpr': 0.18,
        'fpr_overrides': {},
        'cwe_mutations': {
            78: [(77, 0.10)],
            330: [(338, 0.15)],
        }
    },
    'scanner_e': {
        'tpr': 0.58, 'fpr': 0.28,
        'fpr_overrides': {},
        'cwe_mutations': {
            89: [(564, 0.35)],
            328: [(327, 0.40)],
            22: [(23, 0.18)],
        }
    },
}


def generate_findings(tool_name, test_cases, profile):
    """Generate findings for a tool based on its detection profile."""
    findings = []
    for tc in test_cases:
        if tc['is_vuln']:
            detected = random.random() < profile['tpr']
        else:
            fpr = profile.get('fpr_overrides', {}).get(tc['category'], profile['fpr'])
            detected = random.random() < fpr

        if detected:
            reported_cwe = tc['cwe']

            # Apply CWE mutations (hierarchy-based reporting)
            mutations = profile.get('cwe_mutations', {}).get(tc['cwe'], [])
            for mutated_cwe, prob in mutations:
                if random.random() < prob:
                    reported_cwe = mutated_cwe
                    break

            findings.append({
                'test_name': tc['name'],
                'cwe': reported_cwe,
                'category': tc['category'],
            })

            # scanner_d: ~10% duplicate findings
            if tool_name == 'scanner_d' and random.random() < 0.10:
                findings.append({
                    'test_name': tc['name'],
                    'cwe': reported_cwe,
                    'category': tc['category'],
                })

            # scanner_d: ~5% wrong-CWE noise from unrelated branch
            if tool_name == 'scanner_d' and random.random() < 0.05:
                unrelated = UNRELATED_CWES.get(tc['cwe'], [])
                if unrelated:
                    wrong_cwe = random.choice(unrelated)
                    findings.append({
                        'test_name': tc['name'],
                        'cwe': wrong_cwe,
                        'category': tc['category'],
                    })

    return findings


# Generate all findings
all_findings = {}
for tool_name, profile in TOOL_PROFILES.items():
    all_findings[tool_name] = generate_findings(tool_name, test_cases, profile)

# Create output directories
os.makedirs('/app/tool_results', exist_ok=True)

# ============ Write expected_results.csv ============
with open('/app/expected_results.csv', 'w', newline='') as f:
    f.write('# test name, category, real vulnerability, cwe\n')
    for tc in test_cases:
        f.write(f"{tc['name']},{tc['category']},{str(tc['is_vuln']).lower()},{tc['cwe']}\n")

# ============ Write CWE hierarchy XML ============
write_cwe_hierarchy_xml(CWE_TREE, '/app/cwe_hierarchy.xml')

# ============ Write policy.yaml ============
policy_yaml = """matching:
  max_ancestor_depth: 2
  max_descendant_depth: 1

tiers:
  critical:
    categories:
      - sqli
      - cmdi
      - xss
      - pathtraver
    min_tpr: 0.70
    max_fpr: 0.25
  standard:
    categories:
      - crypto
      - hash
      - weakrand
      - ldapi
    min_tpr: 0.50
    max_fpr: 0.35

overall_min_youdens_j: 0.30
"""
with open('/app/policy.yaml', 'w') as f:
    f.write(policy_yaml)

# ============ Scanner A: Multi-run SARIF 2.1.0 ============
findings_a = all_findings['scanner_a']
run0_findings = []
run1_findings = []
for f_item in findings_a:
    in_run0 = random.random() < 0.7
    in_run1 = random.random() < 0.7
    if not in_run0 and not in_run1:
        if random.random() < 0.5:
            in_run0 = True
        else:
            in_run1 = True
    if in_run0:
        run0_findings.append(f_item)
    if in_run1:
        run1_findings.append(f_item)


def make_sarif_results(findings_list):
    results = []
    for f_item in findings_list:
        results.append({
            "ruleId": f"CWE-{f_item['cwe']}",
            "level": random.choice(["error", "warning"]),
            "message": {"text": f"Potential vulnerability CWE-{f_item['cwe']} detected"},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": f"src/main/java/org/benchmark/testcode/{f_item['test_name']}.java",
                        "uriBaseId": "%SRCROOT%"
                    },
                    "region": {
                        "startLine": random.randint(10, 250),
                        "startColumn": random.randint(1, 40),
                        "endLine": random.randint(10, 250)
                    }
                }
            }]
        })
    return results


sarif = {
    "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/Schemata/sarif-schema-2.1.0.json",
    "version": "2.1.0",
    "runs": [
        {
            "tool": {
                "driver": {
                    "name": "ScannerA-CoreRules",
                    "version": "3.2.1",
                    "semanticVersion": "3.2.1",
                    "rules": [
                        {
                            "id": f"CWE-{cwe}",
                            "shortDescription": {"text": f"CWE-{cwe} core detection rule"},
                            "defaultConfiguration": {"level": "error"}
                        }
                        for _, cwe in CATEGORIES
                    ]
                }
            },
            "results": make_sarif_results(run0_findings)
        },
        {
            "tool": {
                "driver": {
                    "name": "ScannerA-ExtendedRules",
                    "version": "3.2.1-ext",
                    "semanticVersion": "3.2.1",
                    "rules": [
                        {
                            "id": f"CWE-{cwe}",
                            "shortDescription": {"text": f"Extended CWE-{cwe} detection"},
                            "defaultConfiguration": {"level": "warning"}
                        }
                        for _, cwe in CATEGORIES
                    ]
                }
            },
            "results": make_sarif_results(run1_findings)
        }
    ]
}
with open('/app/tool_results/scanner_a.sarif', 'w') as f:
    json.dump(sarif, f, indent=2)

# ============ Scanner B: CSV format ============
with open('/app/tool_results/scanner_b.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['finding_id', 'test_case', 'cwe_id', 'confidence', 'severity', 'description'])
    for i, f_item in enumerate(all_findings['scanner_b'], 1):
        conf = random.choice(['HIGH', 'MEDIUM', 'LOW'])
        sev = random.choice(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'])
        desc = f"CWE-{f_item['cwe']} found in {f_item['test_name']}"
        writer.writerow([i, f_item['test_name'], f_item['cwe'], conf, sev, desc])

# ============ Scanner C: XML with namespace prefix ============
xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
xml_lines.append('<sc:report xmlns:sc="urn:scanner-c:findings:v2" xmlns:meta="urn:scanner-c:meta:v1">')
xml_lines.append('  <meta:scan-info tool="ScannerC" version="5.1.0" timestamp="2024-03-15T14:30:00Z"/>')
xml_lines.append('  <sc:findings>')
for i, f_item in enumerate(all_findings['scanner_c'], 1):
    sev = random.choice(['critical', 'high', 'medium', 'low'])
    xml_lines.append(f'    <sc:finding id="{i}" test-case="{f_item["test_name"]}" cwe="{f_item["cwe"]}" severity="{sev}">')
    xml_lines.append(f'      <sc:description>CWE-{f_item["cwe"]} vulnerability detected</sc:description>')
    xml_lines.append(f'      <sc:location file="src/{f_item["test_name"]}.java" line="{random.randint(1, 300)}"/>')
    xml_lines.append(f'    </sc:finding>')
xml_lines.append('  </sc:findings>')
xml_lines.append('</sc:report>')
with open('/app/tool_results/scanner_c.xml', 'w') as f:
    f.write('\n'.join(xml_lines) + '\n')

# ============ Scanner D: NDJSON (with duplicates and noise) ============
with open('/app/tool_results/scanner_d.ndjson', 'w') as f:
    for i, f_item in enumerate(all_findings['scanner_d'], 1):
        record = {
            "id": i,
            "testCase": f_item['test_name'],
            "cwe": f_item['cwe'],
            "severity": random.choice(["CRITICAL", "HIGH", "MEDIUM"]),
            "confidence": round(random.uniform(0.5, 1.0), 3),
            "message": f"Detected CWE-{f_item['cwe']} in {f_item['test_name']}"
        }
        f.write(json.dumps(record) + '\n')

# ============ Scanner E: Custom log (BOM + mixed line endings) ============
log_lines = []
base_ts = 1705312800
for i, f_item in enumerate(all_findings['scanner_e']):
    ts = base_ts + i * 3
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    ts_str = dt.strftime('%Y-%m-%d %H:%M:%S')
    severity = random.choice(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'])
    line = f'[{ts_str}] FINDING: {f_item["test_name"]} | CWE-{f_item["cwe"]} | {severity} | Vulnerability in source code'
    log_lines.append(line)

with open('/app/tool_results/scanner_e.log', 'wb') as f:
    f.write(b'\xef\xbb\xbf')
    for i, line in enumerate(log_lines):
        if i % 3 == 0:
            f.write(line.encode('utf-8') + b'\r\n')
        else:
            f.write(line.encode('utf-8') + b'\n')

print(f"Generated {len(test_cases)} test cases across {len(CATEGORIES)} categories")
for tool_name, findings in all_findings.items():
    print(f"  {tool_name}: {len(findings)} findings")
print("Data generation complete.")
