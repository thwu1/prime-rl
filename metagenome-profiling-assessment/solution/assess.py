#!/usr/bin/env python3

"""
Metagenome profiling assessment tool.
Evaluates taxonomic profiling predictions against a gold standard
using the Bioboxes profiling format (v0.10.0).
"""

import argparse
import json
import math
import os
import sys


def parse_nodes_dmp(filepath):
    """Parse NCBI taxonomy nodes.dmp file.
    Returns dict mapping tax_id -> parent_tax_id.
    """
    parent_map = {}
    with open(filepath) as f:
        for line in f:
            parts = line.strip().rstrip('|').split('\t|\t')
            if len(parts) >= 2:
                tax_id = parts[0].strip()
                parent_id = parts[1].strip()
                parent_map[tax_id] = parent_id
    return parent_map


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
                    # New sample: save previous, reset
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
    total = 0.0
    for taxid in all_taxa:
        gs_val = gs_pcts.get(taxid, 0.0)
        pred_val = pred_pcts.get(taxid, 0.0)
        total += abs(gs_val - pred_val)
    return total / 100.0


def compute_bray_curtis(gs_pcts, pred_pcts):
    """Bray-Curtis distance over union of taxa."""
    all_taxa = set(gs_pcts.keys()) | set(pred_pcts.keys())
    sum_diff = 0.0
    sum_gs = 0.0
    sum_pred = 0.0
    for taxid in all_taxa:
        gs_val = gs_pcts.get(taxid, 0.0)
        pred_val = pred_pcts.get(taxid, 0.0)
        sum_diff += abs(gs_val - pred_val)
        sum_gs += gs_val
        sum_pred += pred_val
    denom = sum_gs + sum_pred
    if denom == 0.0:
        return 0.0
    return sum_diff / denom


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
    """Shannon diversity index for a profile at one rank."""
    total = 0.0
    for taxid, pct in pcts.items():
        if pct > 0:
            p = pct / 100.0
            total -= p * math.log(p)
    return total


def validate_profiles(profile_data, parent_map):
    """Validate profiles against taxonomy and check percentage sums.

    profile_data: list of (filepath, [(sample_id, ranks_list, rank_data, raw_entries)])
    parent_map: dict from nodes.dmp

    Returns list of warning dicts.
    """
    warnings = []

    for filepath, samples in profile_data:
        basename = os.path.basename(filepath)
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
                        "issue": f"percentage sum {total:.1f} deviates from 100.0"
                    })

            # Check TAXPATH consistency with nodes.dmp
            for taxid, rank, taxpath, pct in raw_entries:
                if pct <= 0:
                    continue
                path_ids = taxpath.split('|')
                if len(path_ids) >= 2:
                    child_id = path_ids[-1]
                    parent_in_path = path_ids[-2]
                    if child_id in parent_map:
                        actual_parent = parent_map[child_id]
                        if actual_parent != parent_in_path:
                            warnings.append({
                                "file": basename,
                                "sample": sample_id,
                                "rank": rank,
                                "issue": (f"TAXPATH for taxid {child_id} shows "
                                          f"parent {parent_in_path} but taxonomy "
                                          f"file shows parent {actual_parent}")
                            })

    return warnings


def run_assessment(manifest_path, output_dir):
    """Main assessment logic."""
    os.makedirs(output_dir, exist_ok=True)

    # Load manifest
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    with open(manifest_path) as f:
        manifest = json.load(f)

    gs_path = os.path.join(manifest_dir, manifest['gold_standard'])
    taxonomy_path = os.path.join(manifest_dir, manifest['taxonomy'])

    # Parse taxonomy
    parent_map = parse_nodes_dmp(taxonomy_path)

    # Parse gold standard
    gs_samples = parse_profile(gs_path)
    gs_by_sample = {}
    gs_rank_order = None
    for sample_id, ranks_list, rank_data, raw_entries in gs_samples:
        gs_by_sample[sample_id] = rank_data
        if gs_rank_order is None:
            gs_rank_order = ranks_list

    # Parse each prediction
    pred_data = []  # for validation
    pred_by_label = {}
    for pred_info in manifest['predictions']:
        pred_path = os.path.join(manifest_dir, pred_info['file'])
        label = pred_info['label']
        pred_samples = parse_profile(pred_path)
        pred_by_sample = {}
        for sample_id, ranks_list, rank_data, raw_entries in pred_samples:
            pred_by_sample[sample_id] = rank_data
        pred_by_label[label] = pred_by_sample
        pred_data.append((pred_path, pred_samples))

    # Validate all profiles
    all_profile_data = [(gs_path, gs_samples)] + pred_data
    validation_warnings = validate_profiles(all_profile_data, parent_map)

    # Write validation.json
    validation_path = os.path.join(output_dir, 'validation.json')
    with open(validation_path, 'w') as f:
        json.dump({"warnings": validation_warnings}, f, indent=2)

    # Compute metrics
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
                    'tool': label,
                    'sample': sample_id,
                    'rank': rank,
                    'l1_norm': l1,
                    'bray_curtis': bc,
                    'precision': prec,
                    'recall': rec,
                    'f1': f1,
                    'jaccard': jacc,
                    'shannon_diversity': shannon,
                })

    # Write results.tsv
    results_path = os.path.join(output_dir, 'results.tsv')
    with open(results_path, 'w') as f:
        header_cols = ['tool', 'sample', 'rank', 'l1_norm', 'bray_curtis',
                       'precision', 'recall', 'f1', 'jaccard',
                       'shannon_diversity']
        f.write('\t'.join(header_cols) + '\n')
        for row in results:
            line_parts = [
                row['tool'],
                row['sample'],
                row['rank'],
                f"{row['l1_norm']:.6f}",
                f"{row['bray_curtis']:.6f}",
                f"{row['precision']:.6f}",
                f"{row['recall']:.6f}",
                f"{row['f1']:.6f}",
                f"{row['jaccard']:.6f}",
                f"{row['shannon_diversity']:.6f}",
            ]
            f.write('\t'.join(line_parts) + '\n')

    # Compute rankings
    tool_metrics = {}
    for row in results:
        label = row['tool']
        if label not in tool_metrics:
            tool_metrics[label] = []
        tool_metrics[label].append(row)

    rankings = []
    for label, rows in tool_metrics.items():
        n = len(rows)
        avg_l1 = sum(r['l1_norm'] for r in rows) / n
        avg_bc = sum(r['bray_curtis'] for r in rows) / n
        avg_p = sum(r['precision'] for r in rows) / n
        avg_r = sum(r['recall'] for r in rows) / n
        avg_f1 = sum(r['f1'] for r in rows) / n
        avg_j = sum(r['jaccard'] for r in rows) / n

        composite = (avg_p + avg_r + avg_f1 + avg_j +
                     (1 - avg_l1 / 2) + (1 - avg_bc)) / 6.0

        rankings.append({
            'tool': label,
            'avg_l1_norm': avg_l1,
            'avg_bray_curtis': avg_bc,
            'avg_precision': avg_p,
            'avg_recall': avg_r,
            'avg_f1': avg_f1,
            'avg_jaccard': avg_j,
            'composite_score': composite,
        })

    # Sort by composite_score descending
    rankings.sort(key=lambda x: x['composite_score'], reverse=True)

    # Write rankings.tsv
    rankings_path = os.path.join(output_dir, 'rankings.tsv')
    with open(rankings_path, 'w') as f:
        header_cols = ['tool', 'avg_l1_norm', 'avg_bray_curtis',
                       'avg_precision', 'avg_recall', 'avg_f1',
                       'avg_jaccard', 'composite_score']
        f.write('\t'.join(header_cols) + '\n')
        for row in rankings:
            line_parts = [
                row['tool'],
                f"{row['avg_l1_norm']:.6f}",
                f"{row['avg_bray_curtis']:.6f}",
                f"{row['avg_precision']:.6f}",
                f"{row['avg_recall']:.6f}",
                f"{row['avg_f1']:.6f}",
                f"{row['avg_jaccard']:.6f}",
                f"{row['composite_score']:.6f}",
            ]
            f.write('\t'.join(line_parts) + '\n')


def main():
    parser = argparse.ArgumentParser(
        description='Metagenome profiling assessment tool')
    parser.add_argument('-m', '--manifest', required=True,
                        help='Manifest JSON file')
    parser.add_argument('-o', '--output-dir', required=True,
                        help='Output directory')
    args = parser.parse_args()

    run_assessment(args.manifest, args.output_dir)


if __name__ == '__main__':
    main()
