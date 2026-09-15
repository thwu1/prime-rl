#!/usr/bin/env python3

"""
SAST Tool Scorecard Engine

Parses expected results, config, and five tool result files in different formats.
Computes per-category and overall confusion matrix metrics, ranks tools by
Youden's J, and detects FPR anomalies.
"""

import json
import csv
import os
import re
import statistics
import xml.etree.ElementTree as ET


def load_expected_results(path='/app/expected_results.csv'):
    """Parse expected results CSV into {test_name: {category, is_vuln, cwe}}."""
    results = {}
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [p.strip() for p in line.split(',')]
            name = parts[0]
            category = parts[1]
            is_vuln = parts[2] == 'true'
            cwe = int(parts[3])
            results[name] = {
                'category': category,
                'is_vuln': is_vuln,
                'cwe': cwe,
            }
    return results


def load_config(path='/app/config.json'):
    with open(path) as f:
        return json.load(f)


def parse_sarif(path):
    """Parse SARIF 2.1.0 JSON format (tool_alpha)."""
    with open(path) as f:
        data = json.load(f)
    findings = {}
    for run in data.get('runs', []):
        for result in run.get('results', []):
            rule_id = result.get('ruleId', '')
            # Extract CWE number from ruleId like "CWE-78"
            cwe_match = re.search(r'CWE-(\d+)', rule_id)
            if not cwe_match:
                continue
            cwe = int(cwe_match.group(1))
            for loc in result.get('locations', []):
                phys = loc.get('physicalLocation', {})
                artifact = phys.get('artifactLocation', {})
                uri = artifact.get('uri', '')
                # Extract test case name from file path
                basename = os.path.splitext(os.path.basename(uri))[0]
                findings.setdefault(basename, set()).add(cwe)
    return {k: list(v) for k, v in findings.items()}


def parse_csv_results(path):
    """Parse CSV format (tool_beta)."""
    findings = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            test_name = row['test_case']
            cwe = int(row['cwe_id'])
            findings.setdefault(test_name, set()).add(cwe)
    return {k: list(v) for k, v in findings.items()}


def parse_xml_results(path):
    """Parse XML format (tool_gamma)."""
    findings = {}
    tree = ET.parse(path)
    root = tree.getroot()
    for finding_elem in root.iter('finding'):
        test_name = finding_elem.get('test-case')
        cwe = int(finding_elem.get('cwe'))
        findings.setdefault(test_name, set()).add(cwe)
    return {k: list(v) for k, v in findings.items()}


def parse_ndjson(path):
    """Parse newline-delimited JSON format (tool_delta), deduplicate."""
    findings = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            test_name = record['testCase']
            cwe = record['cwe']
            findings.setdefault(test_name, set()).add(cwe)
    return {k: list(v) for k, v in findings.items()}


def parse_log(path):
    """Parse custom log format (tool_epsilon) with BOM and mixed line endings."""
    with open(path, 'rb') as f:
        content = f.read()
    # Remove UTF-8 BOM if present
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
            test_name = m.group(1)
            cwe = int(m.group(2))
            findings.setdefault(test_name, set()).add(cwe)
    return {k: list(v) for k, v in findings.items()}


def cwe_matches(reported_cwe, expected_cwe, aliases):
    """Check if reported CWE matches expected CWE, considering aliases."""
    if reported_cwe == expected_cwe:
        return True
    accepted = aliases.get(str(expected_cwe), [])
    return reported_cwe in accepted


def compute_scorecard(expected, tool_findings_map, aliases):
    """Compute full scorecard with metrics, rankings, and anomalies."""
    scorecard = {'tools': {}, 'rankings': {}, 'anomalies': []}
    tool_youdens = {}

    for tool_name, tool_findings in sorted(tool_findings_map.items()):
        categories = sorted(set(tc['category'] for tc in expected.values()))
        cat_counts = {cat: {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0}
                      for cat in categories}

        for test_name, tc in expected.items():
            cat = tc['category']
            expected_cwe = tc['cwe']
            is_vuln = tc['is_vuln']
            reported_cwes = tool_findings.get(test_name, [])

            matched = any(
                cwe_matches(rc, expected_cwe, aliases)
                for rc in reported_cwes
            )

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

        # Compute per-category derived metrics
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

            tool_data['categories'][cat] = {
                'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
                'tpr': round(tpr, 6),
                'fpr': round(fpr, 6),
                'precision': round(precision, 6),
                'youdens_j': round(youdens_j, 6),
            }

            total_tp += tp
            total_fp += fp
            total_tn += tn
            total_fn += fn
            tprs.append(tpr)
            fprs.append(fpr)

        # Overall metrics (macro-averaged rates, summed counts)
        avg_tpr = sum(tprs) / len(tprs) if tprs else 0.0
        avg_fpr = sum(fprs) / len(fprs) if fprs else 0.0
        total_precision = (total_tp / (total_tp + total_fp)
                           if (total_tp + total_fp) > 0 else 0.0)
        overall_youdens = avg_tpr - avg_fpr

        tool_data['overall'] = {
            'tp': total_tp, 'fp': total_fp,
            'tn': total_tn, 'fn': total_fn,
            'tpr': round(avg_tpr, 6),
            'fpr': round(avg_fpr, 6),
            'precision': round(total_precision, 6),
            'youdens_j': round(overall_youdens, 6),
        }

        scorecard['tools'][tool_name] = tool_data
        tool_youdens[tool_name] = overall_youdens

        # Anomaly detection: FPR > mean + 2*stdev
        if len(fprs) >= 2:
            mean_fpr = statistics.mean(fprs)
            std_fpr = statistics.stdev(fprs)
            if std_fpr > 0:
                for cat in categories:
                    cat_fpr = tool_data['categories'][cat]['fpr']
                    if cat_fpr > mean_fpr + 2 * std_fpr:
                        scorecard['anomalies'].append({
                            'tool': tool_name,
                            'category': cat,
                            'reason': ('FPR exceeds tool mean by '
                                       '>2 standard deviations'),
                            'category_fpr': round(cat_fpr, 6),
                            'tool_mean_fpr': round(mean_fpr, 6),
                            'tool_std_fpr': round(std_fpr, 6),
                        })

    # Rankings by overall Youden's J descending
    scorecard['rankings']['by_youdens_j'] = sorted(
        tool_youdens.keys(),
        key=lambda t: tool_youdens[t],
        reverse=True,
    )

    return scorecard


def main():
    expected = load_expected_results()
    config = load_config()
    aliases = config['cwe_aliases']

    # Parse all tool results
    tool_findings = {
        'tool_alpha': parse_sarif('/app/tool_results/tool_alpha.sarif.json'),
        'tool_beta': parse_csv_results('/app/tool_results/tool_beta.csv'),
        'tool_gamma': parse_xml_results('/app/tool_results/tool_gamma.xml'),
        'tool_delta': parse_ndjson('/app/tool_results/tool_delta.ndjson'),
        'tool_epsilon': parse_log('/app/tool_results/tool_epsilon.log'),
    }

    scorecard = compute_scorecard(expected, tool_findings, aliases)

    with open('/app/scorecard.json', 'w') as f:
        json.dump(scorecard, f, indent=2)

    print("Scorecard written to /app/scorecard.json")

    # Print summary
    print("\n=== Tool Rankings (by Youden's J) ===")
    for i, tool in enumerate(scorecard['rankings']['by_youdens_j'], 1):
        ov = scorecard['tools'][tool]['overall']
        print(f"  {i}. {tool}: J={ov['youdens_j']:.4f} "
              f"(TPR={ov['tpr']:.4f}, FPR={ov['fpr']:.4f})")

    if scorecard['anomalies']:
        print(f"\n=== Anomalies ({len(scorecard['anomalies'])}) ===")
        for a in scorecard['anomalies']:
            print(f"  {a['tool']}/{a['category']}: "
                  f"FPR={a['category_fpr']:.4f} "
                  f"(mean={a['tool_mean_fpr']:.4f}, "
                  f"std={a['tool_std_fpr']:.4f})")
    else:
        print("\nNo anomalies detected.")


if __name__ == '__main__':
    main()
