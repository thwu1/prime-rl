#!/usr/bin/env python3
"""Multi-system log parsing benchmarking pipeline using drain3."""

import os
import sys
import json
import re

import pandas as pd
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

sys.path.insert(0, '/app/evaluation')
from evaluate import compute_ga_fga, compute_pa, compute_fta
from post_process import correct_template

# Per-system Drain parameters tuned for accuracy on Loghub-2.0 2k samples
MINING_PARAMS = {
    'HDFS': {'depth': 4, 'sim_th': 0.5},
    'Apache': {'depth': 4, 'sim_th': 0.5},
    'Linux': {'depth': 6, 'sim_th': 0.39},
}


def generate_logformat_regex(logformat):
    """Convert a Loghub format string into a compiled regex with named groups.

    Format strings use <FieldName> for named capture groups. Surrounding
    characters (including regex escapes like \\[) are used as-is.
    """
    headers = []
    splitters = re.split(r'(<[^<>]+>)', logformat)
    regex_parts = []
    for part in splitters:
        if part.startswith('<') and part.endswith('>'):
            header = part.strip('<>')
            headers.append(header)
            regex_parts.append(f'(?P<{header}>.*?)')
        else:
            regex_parts.append(part)
    return re.compile('^' + ''.join(regex_parts) + '$'), headers


def parse_raw_logs(log_file, log_format):
    """Parse raw log file and extract the Content field."""
    regex, _ = generate_logformat_regex(log_format)
    records = []
    with open(log_file) as f:
        for line_id, line in enumerate(f, 1):
            line = line.strip()
            m = regex.match(line)
            content = m.group('Content') if m else line
            records.append({'LineId': line_id, 'Content': content})
    return records


def run_drain3_pipeline(records, masking_patterns, depth, sim_th):
    """Run drain3 streaming template mining with regex preprocessing."""
    config = TemplateMinerConfig()
    config.drain_depth = depth
    config.drain_sim_th = sim_th
    config.profiling_enabled = False

    template_miner = TemplateMiner(config=config)

    results = []
    for record in records:
        content = record['Content']
        # Apply regex masking before drain3
        for pattern in masking_patterns:
            content = re.sub(pattern, '<*>', content)

        result = template_miner.add_log_message(content)
        results.append({
            'LineId': record['LineId'],
            'Content': record['Content'],
            'EventId': f"E{result['cluster_id']}",
            'EventTemplate': result['template_mined'],
        })
    return results


def evaluate_metrics(gt_csv, parsed_df, apply_correction=False):
    """Compute all four Loghub-2.0 metrics."""
    gt_df = pd.read_csv(gt_csv)
    mask = gt_df['EventTemplate'].notna()
    gt_s = gt_df.loc[mask, 'EventTemplate'].reset_index(drop=True)
    pa_s = parsed_df.loc[mask, 'EventTemplate'].reset_index(drop=True)

    if apply_correction:
        gt_s = gt_s.apply(correct_template)
        pa_s = pa_s.apply(correct_template)

    GA, FGA = compute_ga_fga(gt_s, pa_s)
    PA = compute_pa(gt_s, pa_s)
    FTA = compute_fta(gt_s, pa_s)
    return GA, FGA, PA, FTA


def main():
    with open('/app/config/systems.json') as f:
        systems = json.load(f)

    os.makedirs('/app/results', exist_ok=True)

    raw_metrics = []
    corr_metrics = []

    for name, cfg in systems.items():
        print(f"\n=== {name} ===")

        # Parse raw logs to extract Content
        records = parse_raw_logs(
            f'/app/logs/{name}.log', cfg['log_format'])
        print(f"  Parsed {len(records)} log lines")

        # Select per-system mining parameters
        params = MINING_PARAMS.get(name, {'depth': 4, 'sim_th': 0.5})

        # Run template mining
        parsed = run_drain3_pipeline(
            records,
            cfg['masking_patterns'],
            params['depth'],
            params['sim_th'],
        )
        parsed_df = pd.DataFrame(parsed)
        parsed_df.to_csv(f'/app/results/parsed_{name}.csv', index=False)
        n_templates = parsed_df['EventTemplate'].nunique()
        print(f"  Extracted {n_templates} unique templates")

        # Evaluate raw (before correction)
        GA, FGA, PA, FTA = evaluate_metrics(
            f'/app/ground_truth/{name}.csv', parsed_df)
        raw_metrics.append(dict(
            System=name,
            GA=round(GA, 4), FGA=round(FGA, 4),
            PA=round(PA, 4), FTA=round(FTA, 4),
        ))
        print(f"  Raw:       GA={GA:.4f}  FGA={FGA:.4f}  "
              f"PA={PA:.4f}  FTA={FTA:.4f}")

        # Evaluate corrected (post-processing on both sides)
        GAc, FGAc, PAc, FTAc = evaluate_metrics(
            f'/app/ground_truth/{name}.csv', parsed_df,
            apply_correction=True)
        corr_metrics.append(dict(
            System=name,
            GA=round(GAc, 4), FGA=round(FGAc, 4),
            PA=round(PAc, 4), FTA=round(FTAc, 4),
        ))
        print(f"  Corrected: GA={GAc:.4f}  FGA={FGAc:.4f}  "
              f"PA={PAc:.4f}  FTA={FTAc:.4f}")

    # Write metrics
    pd.DataFrame(raw_metrics).to_csv(
        '/app/results/metrics_raw.csv', index=False)
    pd.DataFrame(corr_metrics).to_csv(
        '/app/results/metrics_corrected.csv', index=False)

    # Compute and write improvement deltas
    improvements = []
    for r, c in zip(raw_metrics, corr_metrics):
        improvements.append({
            'System': r['System'],
            'GA_delta': round(c['GA'] - r['GA'], 4),
            'FGA_delta': round(c['FGA'] - r['FGA'], 4),
            'PA_delta': round(c['PA'] - r['PA'], 4),
            'FTA_delta': round(c['FTA'] - r['FTA'], 4),
        })
    pd.DataFrame(improvements).to_csv(
        '/app/results/improvement.csv', index=False)

    print("\n=== Pipeline complete ===")


if __name__ == '__main__':
    main()
