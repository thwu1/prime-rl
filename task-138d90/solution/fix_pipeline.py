#!/usr/bin/env python3
"""Fix all 7 bugs in the evaluation pipeline and generate audit report.

Bugs are fixed via targeted string replacements in the pipeline source files.
Commit SHAs are extracted from the git repository history using git log.
An audit report documenting each bug with its introducing commit and
severity assessment is written to /app/audit_report.json.
"""


import json
import math
import subprocess


def fix_file(path, replacements):
    """Apply a list of (old, new) string replacements to a file."""
    with open(path, 'r') as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)


def get_commit_sha(grep_pattern):
    """Get the short SHA of the commit whose message matches the pattern."""
    result = subprocess.run(
        ['git', 'log', '--oneline', '--all', f'--grep={grep_pattern}'],
        capture_output=True, text=True, cwd='/app')
    lines = result.stdout.strip().split('\n')
    if lines and lines[0]:
        return lines[0].split()[0]
    return "unknown"


def main():
    bugs = []

    # Look up commit SHAs from the git history
    sha_config = get_commit_sha("config system")
    sha_preprocessing = get_commit_sha("range filtering")
    sha_assignment = get_commit_sha("greedy assignment")
    sha_metrics = get_commit_sha("AP computation")
    sha_makefile = get_commit_sha("Makefile for pipeline")

    # ── Bug 1: Range filter uses L-inf instead of L2 norm ──
    fix_file('/app/pipeline/preprocessing.py', [(
        "dist = max(abs(entry['tx']), abs(entry['ty']), abs(entry['tz']))",
        "dist = (entry['tx']**2 + entry['ty']**2 + entry['tz']**2) ** 0.5"
    )])
    bugs.append({
        "file": "/app/pipeline/preprocessing.py",
        "bug": "Range filtering uses L-infinity norm max(|tx|,|ty|,|tz|) instead of Euclidean L2 norm sqrt(tx^2+ty^2+tz^2). This incorrectly includes objects on diagonals where each coordinate is within range but the actual 3D distance exceeds max_range.",
        "commit_sha": sha_preprocessing,
        "severity": "major",
        "severity_justification": "Affects objects near the range boundary on diagonals. For this dataset, a handful of boundary objects are incorrectly included/excluded, causing moderate CDS distortion in categories with objects near max_range."
    })

    # ── Bug 2: YAML override clobbers tp_threshold_m from 2.0 to 4.0 ──
    fix_file('/app/config/overrides.yaml', [(
        'tp_threshold_m: 4.0',
        'tp_threshold_m: 2.0'
    )])
    bugs.append({
        "file": "/app/config/overrides.yaml",
        "bug": "The YAML overrides file sets tp_threshold_m to 4.0, overriding the correct TOML value of 2.0. This changes which detections count as true positives for error metrics, inflating the number of TPs and distorting ATE/ASE/AOE averages.",
        "commit_sha": sha_config,
        "severity": "major",
        "severity_justification": "Doubles the TP matching distance from 2.0m to 4.0m, allowing distant matches to count as TPs. This dilutes TP error metrics (ATE, ASE, AOE) with low-quality matches, distorting the CDS quality factor across all categories."
    })

    # ── Bug 3: Greedy assignment sorts ascending instead of descending ──
    fix_file('/app/pipeline/assignment.py', [(
        "dt_indices = sorted(range(len(sweep_dts)),\n                        key=lambda i: sweep_dts[i]['score'])",
        "dt_indices = sorted(range(len(sweep_dts)),\n                        key=lambda i: sweep_dts[i]['score'], reverse=True)"
    )])
    bugs.append({
        "file": "/app/pipeline/assignment.py",
        "bug": "Detections are sorted in ascending score order instead of descending. Low-confidence detections claim ground truth matches before high-confidence ones, corrupting the precision-recall curve and producing incorrect AP values.",
        "commit_sha": sha_assignment,
        "severity": "critical",
        "severity_justification": "Fundamentally corrupts the precision-recall curve for every category by allowing low-confidence detections to claim GT matches first. This directly corrupts AP (the primary component of CDS) across the entire evaluation."
    })

    # ── Bug 4: VOC envelope applied forward instead of reverse ──
    fix_file('/app/pipeline/metrics.py', [(
        'precision = np.maximum.accumulate(precision)',
        'precision = np.maximum.accumulate(precision[::-1])[::-1]'
    )])
    bugs.append({
        "file": "/app/pipeline/metrics.py",
        "bug": "VOC monotonic precision envelope is applied via forward accumulate instead of reverse-then-forward. This fails to ensure precision is non-increasing with recall, producing incorrect AP values.",
        "commit_sha": sha_metrics,
        "severity": "critical",
        "severity_justification": "Breaks the VOC precision interpolation for all categories. The forward envelope fails to propagate high-precision values backward, systematically deflating AP and therefore CDS across the entire evaluation."
    })

    # ── Bug 5: Orientation error lacks circular angle wrapping ──
    fix_file('/app/pipeline/metrics.py', [(
        'return abs(yaw_dt - yaw_gt)',
        'diff = yaw_dt - yaw_gt\n    return abs(math.atan2(math.sin(diff), math.cos(diff)))'
    )])
    bugs.append({
        "file": "/app/pipeline/metrics.py",
        "bug": "Orientation error uses raw abs(yaw_dt - yaw_gt) without circular angle wrapping. Headings near +pi and -pi produce errors of ~2*pi instead of the correct small angular difference.",
        "commit_sha": sha_metrics,
        "severity": "major",
        "severity_justification": "Produces grossly inflated AOE for objects with headings near ±π, which propagates into CDS via the AOM quality factor. Impact is significant for affected objects but limited to near-boundary heading angles."
    })

    # ── Bug 6: CDS uses sum of TP measures instead of mean ──
    fix_file('/app/pipeline/metrics.py', [(
        'tp_score = atm + asm + aom',
        'tp_score = (atm + asm + aom) / 3.0'
    )])
    bugs.append({
        "file": "/app/pipeline/metrics.py",
        "bug": "CDS formula uses sum of TP measures (ATM + ASM + AOM) instead of their arithmetic mean. This causes CDS to exceed 1.0, violating the [0,1] range constraint and rendering CDS values meaningless.",
        "commit_sha": sha_metrics,
        "severity": "critical",
        "severity_justification": "CDS is the primary ranking metric. Using sum instead of mean inflates CDS by up to 3x, producing values > 1.0 that violate the metric's definition. This completely invalidates all CDS results and cross-category comparisons."
    })

    # ── Bug 7: Makefile exports wrong EVAL_NUM_RECALL_SAMPLES ──
    fix_file('/app/Makefile', [(
        'export EVAL_NUM_RECALL_SAMPLES := 11',
        'export EVAL_NUM_RECALL_SAMPLES := 101'
    )])
    bugs.append({
        "file": "/app/Makefile",
        "bug": "Makefile exports EVAL_NUM_RECALL_SAMPLES=11 instead of the spec-mandated 101. This overrides the TOML config via the env var support in the config loader, computing AP with 11 recall samples instead of 101.",
        "commit_sha": sha_makefile,
        "severity": "critical",
        "severity_justification": "Silently overrides the config via environment variable propagation, reducing recall sampling from 101 to 11 points. This coarsens the AP interpolation for all categories, systematically biasing the primary AP metric and all downstream CDS values."
    })

    # Write audit report
    with open('/app/audit_report.json', 'w') as f:
        json.dump(bugs, f, indent=2)
    print(f"Audit report written with {len(bugs)} bugs documented.")


if __name__ == '__main__':
    main()
