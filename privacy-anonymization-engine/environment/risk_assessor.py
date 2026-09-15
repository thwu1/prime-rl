#!/usr/bin/env python3
"""Privacy Risk Assessment Tool - MDPS Compliance Checker v1.4.2

Assess privacy properties of anonymized datasets against the Medical Data
Privacy Standard (MDPS) compliance requirements.

Usage:
    risk_assessor.py assess  --dataset PATH --quasi-ids COLS --sensitive COL [options]
    risk_assessor.py validate --anonymized PATH --original PATH --quasi-ids COLS --sensitive COL --hierarchies-dir DIR [options]

Note: Distribution conformance check uses total variation distance.
"""

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict


def load_csv_data(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_hierarchy(path):
    """Load hierarchy CSV. Returns (dict: original_value -> [level_0, level_1, ...], max_level)."""
    h = {}
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            h[row[0]] = row
    return h, len(header) - 1


def get_equivalence_classes(data, qi_cols):
    ecs = defaultdict(list)
    for row in data:
        key = tuple(row[c] for c in qi_cols)
        ecs[key].append(row)
    return ecs


def assess_group_sizes(ecs, threshold):
    sizes = [len(recs) for recs in ecs.values()]
    violations = [(list(k), len(v)) for k, v in ecs.items() if len(v) < threshold]
    violations.sort(key=lambda x: x[1])
    return {
        "check": "group_size",
        "control": "RIC",
        "threshold": threshold,
        "total_groups": len(ecs),
        "min_size": min(sizes),
        "max_size": max(sizes),
        "avg_size": round(sum(sizes) / len(sizes), 4),
        "groups_below_threshold": len(violations),
        "passed": len(violations) == 0,
        "sample_violations": violations[:5]
    }


def assess_diversity(ecs, sensitive_col, threshold):
    min_entropy = float('inf')
    violations = 0
    worst_groups = []
    for key, recs in ecs.items():
        vals = [r[sensitive_col] for r in recs]
        counter = Counter(vals)
        n = len(vals)
        entropy = -sum((c / n) * math.log(c / n) for c in counter.values() if c > 0)
        if entropy < threshold:
            violations += 1
            if len(worst_groups) < 5:
                worst_groups.append({
                    "group": list(key),
                    "entropy": round(entropy, 6),
                    "distinct_values": len(counter),
                    "size": n
                })
        min_entropy = min(min_entropy, entropy)
    return {
        "check": "diversity",
        "control": "ADR",
        "metric": "shannon_entropy",
        "threshold": threshold,
        "min_entropy_observed": round(min_entropy, 6),
        "effective_l": round(math.exp(min_entropy), 4),
        "groups_below_threshold": violations,
        "passed": violations == 0,
        "sample_violations": worst_groups
    }


def assess_distribution(ecs, data, sensitive_col, threshold):
    """Distribution conformance using total variation distance (TVD)."""
    all_vals = [r[sensitive_col] for r in data]
    total = len(all_vals)
    overall = Counter(all_vals)
    cats = sorted(overall.keys())
    overall_dist = {c: n / total for c, n in overall.items()}

    max_tvd = 0.0
    violations = 0
    worst_groups = []
    for key, recs in ecs.items():
        vals = [r[sensitive_col] for r in recs]
        n = len(vals)
        ec_counter = Counter(vals)
        ec_dist = {c: ec_counter.get(c, 0) / n for c in cats}
        tvd = sum(abs(ec_dist.get(c, 0) - overall_dist.get(c, 0)) for c in cats) / 2.0
        if tvd > threshold:
            violations += 1
            if len(worst_groups) < 5:
                worst_groups.append({
                    "group": list(key),
                    "distance": round(tvd, 6),
                    "size": n
                })
        max_tvd = max(max_tvd, tvd)
    return {
        "check": "distribution",
        "control": "DCR",
        "metric": "total_variation_distance",
        "threshold": threshold,
        "max_distance_observed": round(max_tvd, 6),
        "groups_above_threshold": violations,
        "passed": violations == 0,
        "sample_violations": worst_groups
    }


def assess_utility(data_orig, data_anon, qi_cols, hier_dir):
    result = {"check": "utility", "control": "IPR", "attributes": {}}
    for col in qi_cols:
        hpath = os.path.join(hier_dir, col + ".csv")
        if not os.path.exists(hpath):
            result["attributes"][col] = {"error": "hierarchy file not found"}
            continue
        hierarchy, max_level = load_hierarchy(hpath)

        detected_levels = Counter()
        for orig_row, anon_row in zip(data_orig, data_anon):
            ov = orig_row[col]
            av = anon_row[col]
            if ov in hierarchy:
                chain = hierarchy[ov]
                found = False
                for lvl in range(len(chain)):
                    if chain[lvl] == av:
                        detected_levels[lvl] += 1
                        found = True
                        break
                if not found:
                    detected_levels[-1] += 1
            else:
                detected_levels[-1] += 1

        most_common_level = detected_levels.most_common(1)[0][0]
        consistent = len(detected_levels) == 1

        result["attributes"][col] = {
            "detected_level": most_common_level,
            "max_level": max_level,
            "consistent": consistent,
            "distinct_original": len(set(r[col] for r in data_orig)),
            "distinct_anonymized": len(set(r[col] for r in data_anon))
        }

    return result


def print_text_report(results):
    print("=" * 64)
    print("  PRIVACY RISK ASSESSMENT REPORT")
    print("=" * 64)
    print("  Dataset:              {}".format(results['dataset']))
    print("  Records:              {}".format(results['records']))
    print("  Equivalence classes:  {}".format(results['equivalence_classes']))
    print("-" * 64)

    for name, assessment in results.get('assessments', {}).items():
        passed = assessment.get('passed')
        if passed is True:
            status = "PASS"
        elif passed is False:
            status = "FAIL"
        else:
            status = "INFO"
        ctrl = assessment.get('control', '')
        print("\n  [{:4s}] {} ({})".format(status, name.upper().replace('_', ' '), ctrl))
        for k, v in assessment.items():
            if k in ('check', 'control', 'sample_violations'):
                continue
            print("    {}: {}".format(k, v))
        violations = assessment.get('sample_violations', [])
        if violations:
            print("    sample violations:")
            for viol in violations[:3]:
                print("      {}".format(viol))

    print("\n" + "=" * 64)
    overall = all(
        a.get('passed', True)
        for a in results.get('assessments', {}).values()
        if 'passed' in a
    )
    print("  OVERALL: {}".format("COMPLIANT" if overall else "NON-COMPLIANT"))
    print("=" * 64)


def run_assess(args):
    qi_cols = [c.strip() for c in args.quasi_ids.split(',')]
    data = load_csv_data(args.dataset)

    checks_requested = [c.strip() for c in args.checks.split(',')]
    if 'all' in checks_requested:
        checks_requested = ['group-size', 'diversity', 'distribution']
        if args.original and args.hierarchies_dir:
            checks_requested.append('utility')

    results = {
        "dataset": args.dataset,
        "records": len(data),
        "assessments": {}
    }
    ecs = get_equivalence_classes(data, qi_cols)
    results["equivalence_classes"] = len(ecs)

    # Load config thresholds if provided
    min_group = 5
    min_entropy = 1.0986
    max_distance = 0.2
    if args.config and os.path.exists(args.config):
        try:
            import yaml
            with open(args.config) as f:
                cfg = yaml.safe_load(f)
            controls = cfg.get('controls', {})
            if 'RIC' in controls:
                p = controls['RIC'].get('parameters', {})
                min_group = p.get('minimum_group_size', min_group)
            if 'ADR' in controls:
                p = controls['ADR'].get('parameters', {})
                min_entropy = p.get('minimum_entropy', min_entropy)
            if 'DCR' in controls:
                p = controls['DCR'].get('parameters', {})
                max_distance = p.get('maximum_distance', max_distance)
        except Exception as e:
            print("Warning: could not parse config: {}".format(e), file=sys.stderr)

    if 'group-size' in checks_requested:
        results['assessments']['group_size'] = assess_group_sizes(ecs, min_group)
    if 'diversity' in checks_requested:
        results['assessments']['diversity'] = assess_diversity(ecs, args.sensitive, min_entropy)
    if 'distribution' in checks_requested:
        results['assessments']['distribution'] = assess_distribution(ecs, data, args.sensitive, max_distance)
    if 'utility' in checks_requested and args.original and args.hierarchies_dir:
        orig = load_csv_data(args.original)
        results['assessments']['utility'] = assess_utility(orig, data, qi_cols, args.hierarchies_dir)

    if args.format == 'json':
        output = json.dumps(results, indent=2)
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            print("Results written to {}".format(args.output))
        else:
            print(output)
    else:
        print_text_report(results)


def run_validate(args):
    qi_cols = [c.strip() for c in args.quasi_ids.split(',')]
    orig = load_csv_data(args.original)
    anon = load_csv_data(args.anonymized)

    results = {"validation": {}}

    results['validation']['record_count'] = {
        "original": len(orig),
        "anonymized": len(anon),
        "match": len(orig) == len(anon)
    }

    orig_sens = [r[args.sensitive] for r in orig]
    anon_sens = [r[args.sensitive] for r in anon]
    results['validation']['sensitive_preserved'] = {
        "match": orig_sens == anon_sens
    }

    invalid_vals = {}
    for col in qi_cols:
        hpath = os.path.join(args.hierarchies_dir, col + ".csv")
        if os.path.exists(hpath):
            hier, _ = load_hierarchy(hpath)
            valid_vals = set()
            for vals in hier.values():
                valid_vals.update(vals)
            for i, r in enumerate(anon):
                if r[col] not in valid_vals:
                    if col not in invalid_vals:
                        invalid_vals[col] = []
                    if len(invalid_vals[col]) < 5:
                        invalid_vals[col].append({"row": i, "value": r[col]})

    results['validation']['hierarchy_compliance'] = {
        "valid": len(invalid_vals) == 0,
        "invalid_values": invalid_vals
    }

    consistency = {}
    for col in qi_cols:
        hpath = os.path.join(args.hierarchies_dir, col + ".csv")
        if not os.path.exists(hpath):
            continue
        hier, _ = load_hierarchy(hpath)
        mapping = {}
        consistent = True
        for orig_row, anon_row in zip(orig, anon):
            ov = orig_row[col]
            av = anon_row[col]
            if ov in mapping:
                if mapping[ov] != av:
                    consistent = False
                    break
            else:
                mapping[ov] = av
        consistency[col] = consistent

    results['validation']['global_consistency'] = {
        "consistent": all(consistency.values()),
        "per_attribute": consistency
    }

    output = json.dumps(results, indent=2)
    if args.format == 'text':
        print("=" * 64)
        print("  DATASET VALIDATION REPORT")
        print("=" * 64)
        for name, result in results['validation'].items():
            print("  {}: {}".format(name, json.dumps(result)))
        print("=" * 64)
    else:
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            print("Results written to {}".format(args.output))
        else:
            print(output)


def main():
    parser = argparse.ArgumentParser(
        prog='risk_assessor',
        description='Privacy Risk Assessment Tool - MDPS Compliance Checker v1.4.2',
        epilog='Use "risk_assessor.py <command> --help" for details on a specific command.'
    )
    subparsers = parser.add_subparsers(dest='command')

    # assess subcommand
    ap = subparsers.add_parser('assess',
        help='Run privacy risk assessment on a dataset')
    ap.add_argument('--dataset', required=True,
        help='Path to the dataset CSV file')
    ap.add_argument('--quasi-ids', required=True,
        help='Comma-separated quasi-identifier column names')
    ap.add_argument('--sensitive', required=True,
        help='Sensitive attribute column name')
    ap.add_argument('--original',
        help='Path to original (pre-anonymization) dataset (needed for utility check)')
    ap.add_argument('--hierarchies-dir',
        help='Directory containing hierarchy CSVs named <attribute>.csv')
    ap.add_argument('--checks', default='all',
        help='Comma-separated checks: group-size,diversity,distribution,utility,all (default: all)')
    ap.add_argument('--config',
        help='Path to compliance requirements YAML for threshold values')
    ap.add_argument('--format', choices=['json', 'text'], default='text',
        help='Output format (default: text)')
    ap.add_argument('--output',
        help='Write results to file instead of stdout')

    # validate subcommand
    vp = subparsers.add_parser('validate',
        help='Validate anonymized dataset against original')
    vp.add_argument('--anonymized', required=True,
        help='Path to anonymized dataset CSV')
    vp.add_argument('--original', required=True,
        help='Path to original dataset CSV')
    vp.add_argument('--quasi-ids', required=True,
        help='Comma-separated quasi-identifier column names')
    vp.add_argument('--sensitive', required=True,
        help='Sensitive attribute column name')
    vp.add_argument('--hierarchies-dir', required=True,
        help='Directory containing hierarchy CSVs named <attribute>.csv')
    vp.add_argument('--format', choices=['json', 'text'], default='text',
        help='Output format (default: text)')
    vp.add_argument('--output',
        help='Write results to file instead of stdout')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'assess':
        run_assess(args)
    elif args.command == 'validate':
        run_validate(args)


if __name__ == '__main__':
    main()
