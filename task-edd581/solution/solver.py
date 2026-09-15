#!/usr/bin/env python3

"""
Solution for SAST Tool Evaluation Audit.

Parses CWE hierarchy XML, five tool output formats, and YAML policy to produce
a comprehensive audit report with hierarchy-aware CWE matching, tiered
compliance evaluation, and anomaly detection.
"""

import json
import csv
import os
import re
import statistics
import xml.etree.ElementTree as ET
import yaml


def load_expected_results():
    results = {}
    with open('/app/expected_results.csv', 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [p.strip() for p in line.split(',')]
            results[parts[0]] = {
                'category': parts[1],
                'is_vuln': parts[2] == 'true',
                'cwe': int(parts[3]),
            }
    return results


def load_cwe_hierarchy():
    """Parse namespace-qualified CWE hierarchy XML into parent/child maps."""
    tree = ET.parse('/app/cwe_hierarchy.xml')
    root = tree.getroot()

    ns = ''
    if root.tag.startswith('{'):
        ns = root.tag.split('}')[0] + '}'

    parent_map = {}
    children_map = {}

    def parse_node(elem, parent_id=None):
        cwe_id = int(elem.get('id'))
        if parent_id is not None:
            parent_map[cwe_id] = parent_id
            children_map.setdefault(parent_id, []).append(cwe_id)
        children_elem = elem.find(f'{ns}children')
        if children_elem is not None:
            for child_elem in children_elem.findall(f'{ns}cwe'):
                parse_node(child_elem, cwe_id)

    for cwe_elem in root.findall(f'{ns}cwe'):
        parse_node(cwe_elem)

    return parent_map, children_map


def get_ancestors(cwe_id, parent_map, max_depth):
    ancestors = []
    current = cwe_id
    for _ in range(max_depth):
        parent = parent_map.get(current)
        if parent is None:
            break
        ancestors.append(parent)
        current = parent
    return ancestors


def get_descendants(cwe_id, children_map, max_depth):
    if max_depth <= 0:
        return []
    descendants = []
    direct_children = children_map.get(cwe_id, [])
    descendants.extend(direct_children)
    if max_depth > 1:
        for child in direct_children:
            descendants.extend(get_descendants(child, children_map, max_depth - 1))
    return descendants


def cwe_match_type(reported_cwe, expected_cwe, parent_map, children_map,
                   max_anc, max_desc):
    """Determine match type: 'direct', 'descendant', 'ancestor', or None."""
    if reported_cwe == expected_cwe:
        return 'direct'
    descendants = get_descendants(expected_cwe, children_map, max_desc)
    if reported_cwe in descendants:
        return 'descendant'
    ancestors = get_ancestors(expected_cwe, parent_map, max_anc)
    if reported_cwe in ancestors:
        return 'ancestor'
    return None


# ---- Format parsers ----

def parse_scanner_a():
    """Parse multi-run SARIF 2.1.0 with cross-run deduplication."""
    with open('/app/tool_results/scanner_a.sarif') as f:
        data = json.load(f)
    findings = {}
    for run in data.get('runs', []):
        for result in run.get('results', []):
            rule_id = result.get('ruleId', '')
            cwe_m = re.search(r'CWE-(\d+)', rule_id)
            if not cwe_m:
                continue
            cwe = int(cwe_m.group(1))
            for loc in result.get('locations', []):
                uri = loc['physicalLocation']['artifactLocation']['uri']
                test_name = os.path.splitext(os.path.basename(uri))[0]
                findings.setdefault(test_name, set()).add(cwe)
    return {k: list(v) for k, v in findings.items()}


def parse_scanner_b():
    """Parse CSV format."""
    findings = {}
    with open('/app/tool_results/scanner_b.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            findings.setdefault(row['test_case'], set()).add(int(row['cwe_id']))
    return {k: list(v) for k, v in findings.items()}


def parse_scanner_c():
    """Parse namespace-prefixed XML."""
    tree = ET.parse('/app/tool_results/scanner_c.xml')
    root = tree.getroot()
    ns = {'sc': 'urn:scanner-c:findings:v2'}
    findings = {}
    for elem in root.findall('.//sc:finding', ns):
        test_name = elem.get('test-case')
        cwe = int(elem.get('cwe'))
        findings.setdefault(test_name, set()).add(cwe)
    return {k: list(v) for k, v in findings.items()}


def parse_scanner_d():
    """Parse NDJSON with set-based deduplication."""
    findings = {}
    with open('/app/tool_results/scanner_d.ndjson') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            findings.setdefault(record['testCase'], set()).add(record['cwe'])
    return {k: list(v) for k, v in findings.items()}


def parse_scanner_e():
    """Parse custom log format with BOM removal and mixed line endings."""
    with open('/app/tool_results/scanner_e.log', 'rb') as f:
        content = f.read()
    if content.startswith(b'\xef\xbb\xbf'):
        content = content[3:]
    text = content.decode('utf-8')
    findings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'\[.*?\]\s+FINDING:\s+(\S+)\s+\|\s+CWE-(\d+)\s+\|', line)
        if m:
            findings.setdefault(m.group(1), set()).add(int(m.group(2)))
    return {k: list(v) for k, v in findings.items()}


def main():
    expected = load_expected_results()
    parent_map, children_map = load_cwe_hierarchy()

    with open('/app/policy.yaml') as f:
        policy = yaml.safe_load(f)

    max_anc = policy['matching']['max_ancestor_depth']
    max_desc = policy['matching']['max_descendant_depth']

    tool_parsers = {
        'scanner_a': parse_scanner_a,
        'scanner_b': parse_scanner_b,
        'scanner_c': parse_scanner_c,
        'scanner_d': parse_scanner_d,
        'scanner_e': parse_scanner_e,
    }

    report = {
        'tools': {},
        'rankings': {},
        'anomalies': [],
        'compliance': {},
        'hierarchy_match_stats': {},
    }
    tool_youdens = {}
    total_direct = total_ancestor = total_descendant = 0

    for tool_name, parser in sorted(tool_parsers.items()):
        tool_findings = parser()
        categories = sorted(set(tc['category'] for tc in expected.values()))
        cat_counts = {cat: {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0} for cat in categories}

        unrounded = {}

        for test_name, tc in expected.items():
            cat = tc['category']
            expected_cwe = tc['cwe']
            is_vuln = tc['is_vuln']
            reported_cwes = tool_findings.get(test_name, [])

            best_match = None
            for rc in reported_cwes:
                mt = cwe_match_type(rc, expected_cwe, parent_map, children_map,
                                    max_anc, max_desc)
                if mt is not None:
                    if mt == 'direct':
                        best_match = 'direct'
                        break
                    elif mt == 'descendant':
                        if best_match != 'direct':
                            best_match = 'descendant'
                    elif mt == 'ancestor':
                        if best_match is None:
                            best_match = 'ancestor'

            matched = best_match is not None

            if matched:
                if best_match == 'direct':
                    total_direct += 1
                elif best_match == 'ancestor':
                    total_ancestor += 1
                elif best_match == 'descendant':
                    total_descendant += 1

            if is_vuln:
                if matched:
                    cat_counts[cat]['tp'] += 1
                else:
                    cat_counts[cat]['fn'] += 1
            else:
                if matched:
                    cat_counts[cat]['fp'] += 1
                else:
                    cat_counts[cat]['tn'] += 1

        tool_data = {'categories': {}, 'overall': {}}
        total_tp = total_fp = total_tn = total_fn = 0
        tprs, fprs = [], []

        for cat in categories:
            c = cat_counts[cat]
            tp, fp, tn, fn = c['tp'], c['fp'], c['tn'], c['fn']
            tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            youdens_j = tpr - fpr

            unrounded[cat] = {'tpr': tpr, 'fpr': fpr}

            tool_data['categories'][cat] = {
                'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
                'tpr': round(tpr, 6), 'fpr': round(fpr, 6),
                'precision': round(precision, 6), 'youdens_j': round(youdens_j, 6),
            }

            total_tp += tp; total_fp += fp; total_tn += tn; total_fn += fn
            tprs.append(tpr); fprs.append(fpr)

        avg_tpr = sum(tprs) / len(tprs) if tprs else 0.0
        avg_fpr = sum(fprs) / len(fprs) if fprs else 0.0
        total_prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        overall_youdens = avg_tpr - avg_fpr

        tool_data['overall'] = {
            'tp': total_tp, 'fp': total_fp, 'tn': total_tn, 'fn': total_fn,
            'tpr': round(avg_tpr, 6), 'fpr': round(avg_fpr, 6),
            'precision': round(total_prec, 6), 'youdens_j': round(overall_youdens, 6),
        }

        report['tools'][tool_name] = tool_data
        tool_youdens[tool_name] = overall_youdens

        # Anomaly detection per tool
        if len(fprs) >= 2:
            mean_fpr = statistics.mean(fprs)
            std_fpr = statistics.stdev(fprs)
            if std_fpr > 0:
                for cat in categories:
                    cat_fpr = unrounded[cat]['fpr']
                    if cat_fpr > mean_fpr + 2 * std_fpr:
                        report['anomalies'].append({
                            'tool': tool_name,
                            'category': cat,
                            'reason': 'FPR exceeds tool mean by >2 standard deviations',
                            'category_fpr': round(cat_fpr, 6),
                            'tool_mean_fpr': round(mean_fpr, 6),
                            'tool_std_fpr': round(std_fpr, 6),
                        })

        # Compliance evaluation
        failing_categories = []
        has_critical_failure = False
        has_any_failure = False

        for tier_name, tier_config in policy['tiers'].items():
            tier_cats = tier_config['categories']
            min_tpr = tier_config['min_tpr']
            max_fpr = tier_config['max_fpr']

            for cat in tier_cats:
                if cat not in unrounded:
                    continue
                cat_m = unrounded[cat]

                if cat_m['tpr'] < min_tpr:
                    failing_categories.append({
                        'category': cat,
                        'tier': tier_name,
                        'metric': 'tpr',
                        'value': round(cat_m['tpr'], 6),
                        'threshold': min_tpr,
                    })
                    has_any_failure = True
                    if tier_name == 'critical':
                        has_critical_failure = True

                if cat_m['fpr'] > max_fpr:
                    failing_categories.append({
                        'category': cat,
                        'tier': tier_name,
                        'metric': 'fpr',
                        'value': round(cat_m['fpr'], 6),
                        'threshold': max_fpr,
                    })
                    has_any_failure = True
                    if tier_name == 'critical':
                        has_critical_failure = True

        if has_critical_failure:
            verdict = 'fail'
        elif has_any_failure:
            verdict = 'conditional'
        else:
            verdict = 'pass'

        report['compliance'][tool_name] = {
            'verdict': verdict,
            'failing_categories': failing_categories,
        }

    # Rankings
    report['rankings']['by_youdens_j'] = sorted(
        tool_youdens.keys(), key=lambda t: tool_youdens[t], reverse=True
    )

    # Hierarchy stats
    report['hierarchy_match_stats'] = {
        'direct_matches': total_direct,
        'ancestor_matches': total_ancestor,
        'descendant_matches': total_descendant,
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Audit report written to /app/audit_report.json")
    print(f"\nHierarchy matches - Direct: {total_direct}, "
          f"Ancestor: {total_ancestor}, Descendant: {total_descendant}")
    print(f"\nRankings: {report['rankings']['by_youdens_j']}")
    for tool_name in sorted(report['compliance']):
        c = report['compliance'][tool_name]
        print(f"  {tool_name}: {c['verdict']} "
              f"({len(c['failing_categories'])} failures)")


if __name__ == '__main__':
    main()
