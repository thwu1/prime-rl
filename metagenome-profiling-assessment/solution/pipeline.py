#!/usr/bin/env python3

"""
Metagenome profiling assessment pipeline.
Sub-commands: taxonomy, metrics, validate
"""

import argparse
import json
import math
import os
import sqlite3
import sys


def parse_nodes_dmp(filepath):
    """Parse NCBI taxonomy nodes.dmp file.
    Returns list of (tax_id, parent_id, rank) tuples.
    """
    nodes = []
    with open(filepath) as f:
        for line in f:
            parts = line.strip().rstrip('|').split('\t|\t')
            if len(parts) >= 3:
                tax_id = int(parts[0].strip())
                parent_id = int(parts[1].strip())
                rank = parts[2].strip()
                nodes.append((tax_id, parent_id, rank))
    return nodes


def create_taxonomy_db(manifest_path, output_dir):
    """Create SQLite taxonomy database from nodes.dmp."""
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    with open(manifest_path) as f:
        manifest = json.load(f)

    taxonomy_path = os.path.join(manifest_dir, manifest['taxonomy'])
    nodes = parse_nodes_dmp(taxonomy_path)

    db_path = os.path.join(output_dir, 'taxonomy.db')
    os.makedirs(output_dir, exist_ok=True)

    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        'CREATE TABLE nodes ('
        'tax_id INTEGER PRIMARY KEY, '
        'parent_id INTEGER, '
        'rank TEXT)'
    )
    conn.executemany('INSERT INTO nodes VALUES (?, ?, ?)', nodes)
    conn.commit()
    conn.close()


def parse_profile(filepath):
    """Parse a Bioboxes profiling format file.

    Returns a list of tuples:
        (sample_id, ranks_list, rank_to_taxid_to_pct, raw_entries)
    where rank_to_taxid_to_pct is {rank: {taxid: percentage}} (merged, filtered),
    and raw_entries is a list of (taxid, rank, taxpath, pct) for validation.
    """
    samples = []
    header = {}
    column_name_to_index = {}
    rank_to_taxid_to_pct = {}
    raw_entries = []
    reading_data = False
    got_columns = False

    with open(filepath) as f:
        for line in f:
            line = line.rstrip('\n')
            stripped = line.strip()

            # Skip empty lines and comments
            if len(stripped) == 0 or stripped.startswith('#'):
                continue

            # Column definition line
            if stripped.startswith('@@'):
                cols = stripped[2:].split('\t')
                column_name_to_index = {name: i for i, name in enumerate(cols)}
                got_columns = True
                reading_data = False
                continue

            # Header line
            if stripped.startswith('@'):
                # If we were reading data, save the current sample
                if reading_data and got_columns:
                    ranks_list = header.get('RANKS', '').split('|')
                    samples.append((header['SAMPLEID'], ranks_list,
                                    rank_to_taxid_to_pct, raw_entries))
                    rank_to_taxid_to_pct = {}
                    raw_entries = []
                    got_columns = False

                if not got_columns:
                    key, value = stripped[1:].split(':', 1)
                    header[key.upper()] = value.strip()
                else:
                    if rank_to_taxid_to_pct:
                        ranks_list = header.get('RANKS', '').split('|')
                        samples.append((header['SAMPLEID'], ranks_list,
                                        rank_to_taxid_to_pct, raw_entries))
                    header = {}
                    rank_to_taxid_to_pct = {}
                    raw_entries = []
                    got_columns = False
                    key, value = stripped[1:].split(':', 1)
                    header[key.upper()] = value.strip()

                reading_data = False
                continue

            # Data line
            if got_columns:
                reading_data = True
                fields = stripped.split('\t')
                taxid = fields[column_name_to_index['TAXID']]
                rank = fields[column_name_to_index['RANK']].lower()
                taxpath = fields[column_name_to_index['TAXPATH']]
                pct = float(fields[column_name_to_index['PERCENTAGE']])

                # Store raw entry for validation (including zero entries)
                raw_entries.append((taxid, rank, taxpath, pct))

                # Filter zero-abundance entries for metric computation
                if pct <= 0.0:
                    continue

                if rank not in rank_to_taxid_to_pct:
                    rank_to_taxid_to_pct[rank] = {}

                # Merge duplicate taxid entries by summing
                if taxid in rank_to_taxid_to_pct[rank]:
                    rank_to_taxid_to_pct[rank][taxid] += pct
                else:
                    rank_to_taxid_to_pct[rank][taxid] = pct

    # Save the last sample
    if got_columns and reading_data:
        ranks_list = header.get('RANKS', '').split('|')
        samples.append((header['SAMPLEID'], ranks_list,
                        rank_to_taxid_to_pct, raw_entries))

    return samples


def compute_l1_norm(gs_pcts, pred_pcts):
    """L1 norm over union of taxa, divided by 100."""
    all_taxa = set(gs_pcts.keys()) | set(pred_pcts.keys())
    total = sum(abs(gs_pcts.get(t, 0.0) - pred_pcts.get(t, 0.0))
                for t in all_taxa)
    return total / 100.0


def compute_bray_curtis(gs_pcts, pred_pcts):
    """Bray-Curtis distance over union of taxa."""
    all_taxa = set(gs_pcts.keys()) | set(pred_pcts.keys())
    sum_diff = sum(abs(gs_pcts.get(t, 0.0) - pred_pcts.get(t, 0.0))
                   for t in all_taxa)
    denom = sum(gs_pcts.values()) + sum(pred_pcts.values())
    return sum_diff / denom if denom > 0 else 0.0


def compute_binary_metrics(gs_pcts, pred_pcts):
    """Compute precision, recall, F1, Jaccard based on presence/absence."""
    gs_taxa = {t for t, v in gs_pcts.items() if v > 0}
    pred_taxa = {t for t, v in pred_pcts.items() if v > 0}

    tp = len(gs_taxa & pred_taxa)
    fp = len(pred_taxa - gs_taxa)
    fn = len(gs_taxa - pred_taxa)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) > 0 else 0.0)
    jaccard = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0

    return precision, recall, f1, jaccard


def compute_shannon(pcts):
    """Shannon diversity index using raw percentage/100 (not renormalized)."""
    total = 0.0
    for pct in pcts.values():
        if pct > 0:
            p = pct / 100.0
            total -= p * math.log(p)
    return total


def compute_metrics(manifest_path, output_dir):
    """Compute per-(tool, sample, rank) metrics and rankings."""
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Parse gold standard
    gs_path = os.path.join(manifest_dir, manifest['gold_standard'])
    gs_samples = parse_profile(gs_path)
    gs_by_sample = {}
    gs_rank_order = None
    for sample_id, ranks_list, rank_data, _ in gs_samples:
        gs_by_sample[sample_id] = rank_data
        if gs_rank_order is None:
            gs_rank_order = ranks_list

    # Parse predictions
    pred_by_label = {}
    for pred_info in manifest['predictions']:
        pred_path = os.path.join(manifest_dir, pred_info['file'])
        label = pred_info['label']
        pred_samples = parse_profile(pred_path)
        pred_by_sample = {}
        for sample_id, ranks_list, rank_data, _ in pred_samples:
            pred_by_sample[sample_id] = rank_data
        pred_by_label[label] = pred_by_sample

    # Compute per-(tool, sample, rank) metrics
    results = []
    for label in sorted(pred_by_label.keys()):
        pred_by_sample = pred_by_label[label]
        for sample_id in sorted(gs_by_sample.keys()):
            gs_ranks = gs_by_sample[sample_id]
            pred_ranks = pred_by_sample.get(sample_id, {})

            for rank in gs_rank_order:
                gs_pcts = gs_ranks.get(rank, {})
                pred_pcts = pred_ranks.get(rank, {})

                l1 = compute_l1_norm(gs_pcts, pred_pcts)
                bc = compute_bray_curtis(gs_pcts, pred_pcts)
                prec, rec, f1, jacc = compute_binary_metrics(gs_pcts, pred_pcts)
                shannon = compute_shannon(pred_pcts)

                results.append({
                    'tool': label, 'sample': sample_id, 'rank': rank,
                    'l1_norm': l1, 'bray_curtis': bc,
                    'precision': prec, 'recall': rec, 'f1': f1,
                    'jaccard': jacc, 'shannon_diversity': shannon,
                })

    # Write results.tsv
    cols = ['tool', 'sample', 'rank', 'l1_norm', 'bray_curtis',
            'precision', 'recall', 'f1', 'jaccard', 'shannon_diversity']
    results_path = os.path.join(output_dir, 'results.tsv')
    with open(results_path, 'w') as f:
        f.write('\t'.join(cols) + '\n')
        for row in results:
            parts = [row['tool'], row['sample'], row['rank']]
            parts += [f"{row[c]:.6f}" for c in cols[3:]]
            f.write('\t'.join(parts) + '\n')

    # Compute and write rankings
    tool_metrics = {}
    for row in results:
        tool_metrics.setdefault(row['tool'], []).append(row)

    rankings = []
    for label, rows in tool_metrics.items():
        n = len(rows)
        avgs = {m: sum(r[m] for r in rows) / n for m in
                ['l1_norm', 'bray_curtis', 'precision', 'recall', 'f1', 'jaccard']}

        composite = (avgs['precision'] + avgs['recall'] + avgs['f1'] +
                     avgs['jaccard'] + (1 - avgs['l1_norm'] / 2) +
                     (1 - avgs['bray_curtis'])) / 6.0

        entry = {'tool': label, 'composite_score': composite}
        for k, v in avgs.items():
            entry[f'avg_{k}'] = v
        rankings.append(entry)

    rankings.sort(key=lambda x: x['composite_score'], reverse=True)

    rcols = ['tool', 'avg_l1_norm', 'avg_bray_curtis', 'avg_precision',
             'avg_recall', 'avg_f1', 'avg_jaccard', 'composite_score']
    rankings_path = os.path.join(output_dir, 'rankings.tsv')
    with open(rankings_path, 'w') as f:
        f.write('\t'.join(rcols) + '\n')
        for row in rankings:
            parts = [row['tool']]
            parts += [f"{row[c]:.6f}" for c in rcols[1:]]
            f.write('\t'.join(parts) + '\n')


def validate_profiles(manifest_path, output_dir):
    """Validate profiles against taxonomy DB and check percentage sums."""
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    with open(manifest_path) as f:
        manifest = json.load(f)

    db_path = os.path.join(output_dir, 'taxonomy.db')
    conn = sqlite3.connect(db_path)

    warnings = []

    # Collect all profiles to check (gold standard + predictions)
    profiles_to_check = [
        os.path.join(manifest_dir, manifest['gold_standard'])
    ]
    for pred_info in manifest['predictions']:
        profiles_to_check.append(
            os.path.join(manifest_dir, pred_info['file']))

    for filepath in profiles_to_check:
        basename = os.path.basename(filepath)
        samples = parse_profile(filepath)

        for sample_id, ranks_list, rank_data, raw_entries in samples:
            # Check percentage sums per rank
            rank_sums = {}
            for taxid, rank, taxpath, pct in raw_entries:
                if pct > 0:
                    rank_sums.setdefault(rank, 0.0)
                    rank_sums[rank] += pct

            for rank, total in rank_sums.items():
                if abs(total - 100.0) > 0.1:
                    warnings.append({
                        "file": basename,
                        "sample": sample_id,
                        "rank": rank,
                        "issue": (f"percentage sum {total:.1f} deviates "
                                  f"from 100.0")
                    })

            # Check TAXPATH consistency via SQL
            for taxid, rank, taxpath, pct in raw_entries:
                if pct <= 0:
                    continue
                path_ids = taxpath.split('|')
                if len(path_ids) >= 2:
                    child_id = int(path_ids[-1])
                    parent_in_path = int(path_ids[-2])
                    cursor = conn.execute(
                        "SELECT parent_id FROM nodes WHERE tax_id = ?",
                        (child_id,))
                    row = cursor.fetchone()
                    if row is not None and row[0] != parent_in_path:
                        warnings.append({
                            "file": basename,
                            "sample": sample_id,
                            "rank": rank,
                            "issue": (f"TAXPATH for taxid {child_id} shows "
                                      f"parent {parent_in_path} but taxonomy "
                                      f"file shows parent {row[0]}")
                        })

    conn.close()

    validation_path = os.path.join(output_dir, 'validation.json')
    with open(validation_path, 'w') as f:
        json.dump({"warnings": warnings}, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description='Metagenome profiling assessment pipeline')
    parser.add_argument('command', choices=['taxonomy', 'metrics', 'validate'],
                        help='Pipeline sub-command')
    parser.add_argument('manifest', help='Manifest JSON file path')
    parser.add_argument('output_dir', help='Output directory path')
    args = parser.parse_args()

    if args.command == 'taxonomy':
        create_taxonomy_db(args.manifest, args.output_dir)
    elif args.command == 'metrics':
        compute_metrics(args.manifest, args.output_dir)
    elif args.command == 'validate':
        validate_profiles(args.manifest, args.output_dir)


if __name__ == '__main__':
    main()
