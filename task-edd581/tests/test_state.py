
"""
Tests for the SAST Tool Evaluation Audit.

Verifies /app/audit_report.json by independently computing expected values
from the raw data files, CWE hierarchy, and compliance policy.
"""

import json
import csv
import os
import re
import statistics
import xml.etree.ElementTree as ET

import yaml
import pytest


# ============================================================
# Reference implementation
# ============================================================

def _load_expected_results():
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


def _load_cwe_hierarchy():
    """Parse CWE hierarchy XML and build parent/child maps."""
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


def _get_ancestors(cwe_id, parent_map, max_depth):
    ancestors = []
    current = cwe_id
    for _ in range(max_depth):
        parent = parent_map.get(current)
        if parent is None:
            break
        ancestors.append(parent)
        current = parent
    return ancestors


def _get_descendants(cwe_id, children_map, max_depth):
    if max_depth <= 0:
        return []
    descendants = []
    direct_children = children_map.get(cwe_id, [])
    descendants.extend(direct_children)
    if max_depth > 1:
        for child in direct_children:
            descendants.extend(_get_descendants(child, children_map, max_depth - 1))
    return descendants


def _load_policy():
    with open('/app/policy.yaml') as f:
        return yaml.safe_load(f)


def _cwe_match_type(reported_cwe, expected_cwe, parent_map, children_map,
                    max_anc, max_desc):
    """Return match type or None."""
    if reported_cwe == expected_cwe:
        return 'direct'
    descendants = _get_descendants(expected_cwe, children_map, max_desc)
    if reported_cwe in descendants:
        return 'descendant'
    ancestors = _get_ancestors(expected_cwe, parent_map, max_anc)
    if reported_cwe in ancestors:
        return 'ancestor'
    return None


# ---- Tool parsers ----

def _parse_scanner_a():
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


def _parse_scanner_b():
    findings = {}
    with open('/app/tool_results/scanner_b.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            findings.setdefault(row['test_case'], set()).add(int(row['cwe_id']))
    return {k: list(v) for k, v in findings.items()}


def _parse_scanner_c():
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


def _parse_scanner_d():
    findings = {}
    with open('/app/tool_results/scanner_d.ndjson') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            findings.setdefault(record['testCase'], set()).add(record['cwe'])
    return {k: list(v) for k, v in findings.items()}


def _parse_scanner_e():
    """Parse custom log with BOM and mixed line endings."""
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


_TOOL_PARSERS = {
    'scanner_a': _parse_scanner_a,
    'scanner_b': _parse_scanner_b,
    'scanner_c': _parse_scanner_c,
    'scanner_d': _parse_scanner_d,
    'scanner_e': _parse_scanner_e,
}


def _compute_reference():
    """Compute the full reference audit report from raw data."""
    expected = _load_expected_results()
    parent_map, children_map = _load_cwe_hierarchy()
    policy = _load_policy()

    max_anc = policy['matching']['max_ancestor_depth']
    max_desc = policy['matching']['max_descendant_depth']

    ref = {}
    tool_youdens = {}
    total_direct = 0
    total_ancestor = 0
    total_descendant = 0

    for tool_name, parser in _TOOL_PARSERS.items():
        tool_findings = parser()
        categories = sorted(set(tc['category'] for tc in expected.values()))
        cat_counts = {cat: {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0} for cat in categories}

        for test_name, tc in expected.items():
            cat = tc['category']
            expected_cwe = tc['cwe']
            is_vuln = tc['is_vuln']
            reported_cwes = tool_findings.get(test_name, [])

            best_match = None
            for rc in reported_cwes:
                mt = _cwe_match_type(rc, expected_cwe, parent_map, children_map,
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

            tool_data['categories'][cat] = {
                'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
                'tpr': tpr, 'fpr': fpr,
                'precision': precision, 'youdens_j': youdens_j,
            }

            total_tp += tp; total_fp += fp; total_tn += tn; total_fn += fn
            tprs.append(tpr); fprs.append(fpr)

        avg_tpr = sum(tprs) / len(tprs) if tprs else 0.0
        avg_fpr = sum(fprs) / len(fprs) if fprs else 0.0
        total_prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0

        tool_data['overall'] = {
            'tp': total_tp, 'fp': total_fp, 'tn': total_tn, 'fn': total_fn,
            'tpr': avg_tpr, 'fpr': avg_fpr,
            'precision': total_prec,
            'youdens_j': avg_tpr - avg_fpr,
        }

        ref[tool_name] = tool_data
        tool_youdens[tool_name] = avg_tpr - avg_fpr

    # Rankings
    ranking = sorted(tool_youdens.keys(), key=lambda t: tool_youdens[t], reverse=True)

    # Anomaly detection
    anomalies = []
    for tool_name, tool_data in ref.items():
        cat_fprs = [tool_data['categories'][cat]['fpr']
                    for cat in sorted(tool_data['categories'].keys())]
        if len(cat_fprs) < 2:
            continue
        mean_fpr = statistics.mean(cat_fprs)
        std_fpr = statistics.stdev(cat_fprs)
        if std_fpr == 0:
            continue
        for cat in sorted(tool_data['categories'].keys()):
            cat_fpr = tool_data['categories'][cat]['fpr']
            if cat_fpr > mean_fpr + 2 * std_fpr:
                anomalies.append((tool_name, cat))

    # Compliance evaluation
    compliance = {}
    for tool_name, tool_data in ref.items():
        failing_categories = []
        has_critical_failure = False
        has_any_failure = False

        for tier_name, tier_config in policy['tiers'].items():
            tier_cats = tier_config['categories']
            min_tpr = tier_config['min_tpr']
            max_fpr = tier_config['max_fpr']

            for cat in tier_cats:
                if cat not in tool_data['categories']:
                    continue
                cat_m = tool_data['categories'][cat]

                if cat_m['tpr'] < min_tpr:
                    failing_categories.append({
                        'category': cat,
                        'tier': tier_name,
                        'metric': 'tpr',
                        'value': cat_m['tpr'],
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
                        'value': cat_m['fpr'],
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

        compliance[tool_name] = {
            'verdict': verdict,
            'failing_categories': failing_categories,
        }

    hierarchy_stats = {
        'direct_matches': total_direct,
        'ancestor_matches': total_ancestor,
        'descendant_matches': total_descendant,
    }

    return ref, ranking, anomalies, compliance, hierarchy_stats


_REF_CACHE = {}

def _get_reference():
    if 'data' not in _REF_CACHE:
        _REF_CACHE['data'] = _compute_reference()
    return _REF_CACHE['data']


def _load_agent_report():
    with open('/app/audit_report.json') as f:
        return json.load(f)


# ============================================================
# Tests
# ============================================================

class TestReportStructure:
    """Verify audit_report.json exists with correct structure."""

    def test_report_exists(self):
        assert os.path.exists('/app/audit_report.json'), \
            "/app/audit_report.json does not exist"

    def test_has_tools(self):
        r = _load_agent_report()
        assert 'tools' in r, "report missing 'tools' key"

    def test_all_tools_present(self):
        r = _load_agent_report()
        expected = {'scanner_a', 'scanner_b', 'scanner_c', 'scanner_d', 'scanner_e'}
        for tool in expected:
            assert tool in r['tools'], f"tool '{tool}' missing from report"

    def test_all_categories_present(self):
        r = _load_agent_report()
        expected_cats = {'cmdi', 'crypto', 'hash', 'pathtraver',
                         'sqli', 'xss', 'weakrand', 'ldapi'}
        for tool_name, tool_data in r['tools'].items():
            assert 'categories' in tool_data, \
                f"'{tool_name}' missing 'categories'"
            for cat in expected_cats:
                assert cat in tool_data['categories'], \
                    f"'{tool_name}' missing category '{cat}'"

    def test_has_overall(self):
        r = _load_agent_report()
        for tool_name, tool_data in r['tools'].items():
            assert 'overall' in tool_data, \
                f"'{tool_name}' missing 'overall'"
            for key in ['tp', 'fp', 'tn', 'fn', 'tpr', 'fpr',
                        'precision', 'youdens_j']:
                assert key in tool_data['overall'], \
                    f"'{tool_name}' overall missing '{key}'"

    def test_has_rankings(self):
        r = _load_agent_report()
        assert 'rankings' in r, "report missing 'rankings'"
        assert 'by_youdens_j' in r['rankings']

    def test_has_anomalies(self):
        r = _load_agent_report()
        assert 'anomalies' in r, "report missing 'anomalies'"

    def test_has_compliance(self):
        r = _load_agent_report()
        assert 'compliance' in r, "report missing 'compliance'"
        expected = {'scanner_a', 'scanner_b', 'scanner_c', 'scanner_d', 'scanner_e'}
        for tool in expected:
            assert tool in r['compliance'], \
                f"compliance missing '{tool}'"
            assert 'verdict' in r['compliance'][tool]
            assert r['compliance'][tool]['verdict'] in ('pass', 'fail', 'conditional'), \
                f"{tool} verdict '{r['compliance'][tool]['verdict']}' invalid"
            assert 'failing_categories' in r['compliance'][tool]

    def test_has_hierarchy_stats(self):
        r = _load_agent_report()
        assert 'hierarchy_match_stats' in r, \
            "report missing 'hierarchy_match_stats'"
        for key in ['direct_matches', 'ancestor_matches', 'descendant_matches']:
            assert key in r['hierarchy_match_stats'], \
                f"hierarchy_match_stats missing '{key}'"


class TestConfusionMatrixCounts:
    """Verify exact TP/FP/TN/FN counts."""

    def test_per_category_counts(self):
        ref, _, _, _, _ = _get_reference()
        r = _load_agent_report()

        for tool_name in ref:
            for cat in ref[tool_name]['categories']:
                rc = ref[tool_name]['categories'][cat]
                ac = r['tools'][tool_name]['categories'][cat]
                assert ac['tp'] == rc['tp'], \
                    f"{tool_name}/{cat} TP: {ac['tp']} != {rc['tp']}"
                assert ac['fp'] == rc['fp'], \
                    f"{tool_name}/{cat} FP: {ac['fp']} != {rc['fp']}"
                assert ac['tn'] == rc['tn'], \
                    f"{tool_name}/{cat} TN: {ac['tn']} != {rc['tn']}"
                assert ac['fn'] == rc['fn'], \
                    f"{tool_name}/{cat} FN: {ac['fn']} != {rc['fn']}"

    def test_overall_counts(self):
        ref, _, _, _, _ = _get_reference()
        r = _load_agent_report()

        for tool_name in ref:
            rc = ref[tool_name]['overall']
            ac = r['tools'][tool_name]['overall']
            assert ac['tp'] == rc['tp'], \
                f"{tool_name} overall TP: {ac['tp']} != {rc['tp']}"
            assert ac['fp'] == rc['fp'], \
                f"{tool_name} overall FP: {ac['fp']} != {rc['fp']}"
            assert ac['tn'] == rc['tn'], \
                f"{tool_name} overall TN: {ac['tn']} != {rc['tn']}"
            assert ac['fn'] == rc['fn'], \
                f"{tool_name} overall FN: {ac['fn']} != {rc['fn']}"


class TestDerivedMetrics:
    """Verify TPR, FPR, Precision, Youden's J within tolerance."""

    TOLERANCE = 0.01

    def test_per_category_rates(self):
        ref, _, _, _, _ = _get_reference()
        r = _load_agent_report()

        for tool_name in ref:
            for cat in ref[tool_name]['categories']:
                rc = ref[tool_name]['categories'][cat]
                ac = r['tools'][tool_name]['categories'][cat]
                assert abs(ac['tpr'] - rc['tpr']) < self.TOLERANCE, \
                    f"{tool_name}/{cat} TPR: {ac['tpr']:.6f} != {rc['tpr']:.6f}"
                assert abs(ac['fpr'] - rc['fpr']) < self.TOLERANCE, \
                    f"{tool_name}/{cat} FPR: {ac['fpr']:.6f} != {rc['fpr']:.6f}"
                assert abs(ac['precision'] - rc['precision']) < self.TOLERANCE, \
                    f"{tool_name}/{cat} Precision: {ac['precision']:.6f} != {rc['precision']:.6f}"
                assert abs(ac['youdens_j'] - rc['youdens_j']) < 2 * self.TOLERANCE, \
                    f"{tool_name}/{cat} Youden's J: {ac['youdens_j']:.6f} != {rc['youdens_j']:.6f}"

    def test_overall_rates(self):
        ref, _, _, _, _ = _get_reference()
        r = _load_agent_report()

        for tool_name in ref:
            rc = ref[tool_name]['overall']
            ac = r['tools'][tool_name]['overall']
            assert abs(ac['tpr'] - rc['tpr']) < self.TOLERANCE, \
                f"{tool_name} overall TPR: {ac['tpr']:.6f} != {rc['tpr']:.6f}"
            assert abs(ac['fpr'] - rc['fpr']) < self.TOLERANCE, \
                f"{tool_name} overall FPR: {ac['fpr']:.6f} != {rc['fpr']:.6f}"
            assert abs(ac['youdens_j'] - rc['youdens_j']) < 2 * self.TOLERANCE, \
                f"{tool_name} overall Youden's J: {ac['youdens_j']:.6f} != {rc['youdens_j']:.6f}"


class TestRankings:
    """Verify tools are ranked correctly by Youden's J."""

    def test_ranking_order(self):
        _, ref_ranking, _, _, _ = _get_reference()
        r = _load_agent_report()
        agent_ranking = r['rankings']['by_youdens_j']
        assert agent_ranking == ref_ranking, \
            f"Ranking mismatch: got {agent_ranking}, expected {ref_ranking}"

    def test_ranking_all_tools(self):
        r = _load_agent_report()
        ranking = r['rankings']['by_youdens_j']
        expected = {'scanner_a', 'scanner_b', 'scanner_c', 'scanner_d', 'scanner_e'}
        assert set(ranking) == expected


class TestAnomalyDetection:
    """Verify anomaly detection results."""

    def test_expected_anomalies(self):
        _, _, ref_anomalies, _, _ = _get_reference()
        r = _load_agent_report()
        agent_anomalies = {(a['tool'], a['category']) for a in r['anomalies']}
        for tool, cat in ref_anomalies:
            assert (tool, cat) in agent_anomalies, \
                f"Expected anomaly ({tool}, {cat}) not found"

    def test_no_false_anomalies(self):
        _, _, ref_anomalies, _, _ = _get_reference()
        ref_set = set(ref_anomalies)
        r = _load_agent_report()
        agent_anomalies = {(a['tool'], a['category']) for a in r['anomalies']}
        for tool, cat in agent_anomalies:
            assert (tool, cat) in ref_set, \
                f"Unexpected anomaly ({tool}, {cat})"

    def test_anomaly_fields(self):
        r = _load_agent_report()
        for a in r['anomalies']:
            assert 'tool' in a
            assert 'category' in a
            assert 'reason' in a
            assert 'category_fpr' in a
            assert 'tool_mean_fpr' in a
            assert 'tool_std_fpr' in a


class TestCompliance:
    """Verify compliance evaluation."""

    def test_compliance_verdicts(self):
        _, _, _, ref_compliance, _ = _get_reference()
        r = _load_agent_report()
        for tool_name, ref_comp in ref_compliance.items():
            agent_comp = r['compliance'][tool_name]
            assert agent_comp['verdict'] == ref_comp['verdict'], \
                f"{tool_name} verdict: got '{agent_comp['verdict']}', " \
                f"expected '{ref_comp['verdict']}'"

    def test_failing_categories_match(self):
        _, _, _, ref_compliance, _ = _get_reference()
        r = _load_agent_report()
        for tool_name, ref_comp in ref_compliance.items():
            agent_comp = r['compliance'][tool_name]
            ref_failing = {(fc['category'], fc['tier'], fc['metric'])
                          for fc in ref_comp['failing_categories']}
            agent_failing = {(fc['category'], fc['tier'], fc['metric'])
                            for fc in agent_comp['failing_categories']}
            assert ref_failing == agent_failing, \
                f"{tool_name} failing categories mismatch:\n" \
                f"  Expected: {sorted(ref_failing)}\n" \
                f"  Got:      {sorted(agent_failing)}"


class TestHierarchyStats:
    """Verify CWE hierarchy match type statistics."""

    def test_match_counts(self):
        _, _, _, _, ref_stats = _get_reference()
        r = _load_agent_report()
        s = r['hierarchy_match_stats']
        assert s['direct_matches'] == ref_stats['direct_matches'], \
            f"Direct: {s['direct_matches']} != {ref_stats['direct_matches']}"
        assert s['ancestor_matches'] == ref_stats['ancestor_matches'], \
            f"Ancestor: {s['ancestor_matches']} != {ref_stats['ancestor_matches']}"
        assert s['descendant_matches'] == ref_stats['descendant_matches'], \
            f"Descendant: {s['descendant_matches']} != {ref_stats['descendant_matches']}"

    def test_total_matches_equals_tp_plus_fp(self):
        """Total hierarchy matches must equal sum of all TP+FP across tools."""
        r = _load_agent_report()
        total_matches = (r['hierarchy_match_stats']['direct_matches'] +
                        r['hierarchy_match_stats']['ancestor_matches'] +
                        r['hierarchy_match_stats']['descendant_matches'])
        total_tp_fp = sum(
            r['tools'][t]['overall']['tp'] + r['tools'][t]['overall']['fp']
            for t in r['tools']
        )
        assert total_matches == total_tp_fp, \
            f"Total matches ({total_matches}) != Total TP+FP ({total_tp_fp})"
