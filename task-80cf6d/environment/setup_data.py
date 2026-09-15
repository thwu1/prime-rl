#!/usr/bin/env python3
"""Generate synthetic reference, SAM file, configuration, and documentation
for the alignment QC audit task.

Creates a deterministic reference genome and a SAM file with 25 alignments.
Eight alignments have deliberately corrupted NM tags. Four alignments have
low gap-compressed identity (< 0.85) for filtering tests.
Also creates a pipeline configuration YAML and metric documentation that
the solver must discover and interpret.
"""
import random
import os
import subprocess

SEED = 42
BASES = 'ACGT'


def gen_seq(length, rng):
    return ''.join(rng.choice(BASES) for _ in range(length))


def mutate(base, rng):
    others = [b for b in BASES if b != base]
    return rng.choice(others)


def write_pipeline_config():
    """Write the pipeline configuration YAML that specifies the audit."""
    config = """\
# Alignment QC Audit Pipeline - Configuration
#
# Metric definitions: see docs/identity_metrics.md
# auN metric: see docs/aun_metric.md

inputs:
  reference: reference.fa
  alignments: alignments.sam

validation:
  # Recompute NM (edit distance) tags by walking each alignment's CIGAR
  # against the reference sequence. Flag any alignment whose original NM
  # tag disagrees with the recomputed value.
  recompute_nm: true

metrics:
  # Compute the following identity metrics for every alignment.
  # Mathematical definitions are in docs/identity_metrics.md.
  # All metrics MUST use the recomputed (correct) NM, not the original tag.
  compute:
    - blast_identity
    - gap_compressed_identity
    - gap_excluded_identity

filter:
  # Retain only alignments meeting this quality threshold.
  metric: gap_compressed_identity
  min_value: 0.85

outputs:
  report:
    path: identity_report.tsv
    format: tab-separated with header row
    columns:
      - read_name
      - blast_identity
      - gap_compressed_identity
      - gap_excluded_identity
      - original_nm
      - correct_nm
      - nm_is_correct
    sorting: lexicographic by read_name
    float_decimals: 6
    boolean_values: true/false

  filtered_bam:
    path: corrected.bam
    index_path: corrected.bam.bai
    description: >
      Coordinate-sorted BAM containing only alignments that pass the
      quality filter, with every NM tag replaced by the recomputed value.

  summary:
    path: summary.json
    format: JSON object
    fields:
      total_alignments: count of all input alignments
      alignments_with_incorrect_nm: count where original NM != recomputed NM
      mean_blast_identity: arithmetic mean over all alignments, 6 decimal places
      mean_gap_compressed_identity: arithmetic mean over all alignments, 6 decimal places
      mean_gap_excluded_identity: arithmetic mean over all alignments, 6 decimal places
      alignments_passing_filter: count of alignments passing the quality filter
      alignment_aun: auN computed on aligned lengths of passing alignments only (see docs/aun_metric.md)
"""
    with open('/app/pipeline_config.yaml', 'w') as f:
        f.write(config)


def write_identity_metrics_doc():
    """Write identity metric definitions that the solver must find and read."""
    doc = """\
# Sequence Identity Metrics

Three identity metrics are used for alignment quality assessment.
All computations derive from the alignment CIGAR string and the
edit distance (NM).

## Notation

Given an alignment's CIGAR string, define:

| Symbol           | Definition                                            |
|------------------|-------------------------------------------------------|
| M_sum            | Total bases in M, =, or X CIGAR operations            |
| I_sum            | Total bases in I (insertion) operations               |
| D_sum            | Total bases in D (deletion) operations                |
| I_count          | Number of distinct I operations in the CIGAR          |
| D_count          | Number of distinct D operations in the CIGAR          |
| gap_opens        | I_count + D_count                                     |
| alignment_length | M_sum + I_sum + D_sum                                 |
| NM               | Edit distance = mismatches + I_sum + D_sum            |
| mismatches       | NM - I_sum - D_sum  (substitution-only differences)   |

Soft-clipped (S) and hard-clipped (H) bases do not contribute to
alignment length, NM, or any identity computation.

## BLAST Identity

    blast_identity = (alignment_length - NM) / alignment_length

Standard definition used by BLAST.  Every inserted or deleted base
is counted as an individual difference.

## Gap-Compressed Identity

    gap_compressed_identity = 1 - (mismatches + gap_opens) / (M_sum + gap_opens)

Each contiguous gap (a single run of I or D operations) is counted as
one difference event regardless of its length.  This metric is more
appropriate when alignments contain long indels, because a single
biological event (e.g. a transposon insertion) should not dominate
the identity score.

## Gap-Excluded Identity

    gap_excluded_identity = (M_sum - mismatches) / M_sum

Gaps are ignored entirely; only substitutions within matched/mismatched
blocks are considered.
"""
    os.makedirs('/app/docs', exist_ok=True)
    with open('/app/docs/identity_metrics.md', 'w') as f:
        f.write(doc)


def write_aun_doc():
    """Write auN metric documentation."""
    doc = """\
# Area Under the Nx Curve (auN)

The auN statistic measures the contiguity of a set of lengths as the
area under the Nx curve.

## Definition

Given lengths L_1, L_2, ..., L_n:

    auN = sum(L_i ^ 2) / sum(L_i)

Intuitively, auN equals the expected length of the segment that
contains a randomly chosen base.

## Usage in this pipeline

Compute auN over the **aligned lengths** of alignments that pass the
quality filter.  The aligned length of a single alignment is its
alignment_length (= M_sum + I_sum + D_sum) as defined in
identity_metrics.md.
"""
    with open('/app/docs/aun_metric.md', 'w') as f:
        f.write(doc)


def main():
    rng = random.Random(SEED)

    chroms = {
        'chr1': gen_seq(3000, rng),
        'chr2': gen_seq(2000, rng),
        'chr3': gen_seq(1500, rng),
    }

    os.makedirs('/app', exist_ok=True)

    # Write reference FASTA
    with open('/app/reference.fa', 'w') as f:
        for name in ['chr1', 'chr2', 'chr3']:
            f.write(f'>{name}\n')
            seq = chroms[name]
            for i in range(0, len(seq), 80):
                f.write(seq[i:i + 80] + '\n')

    # ------------------------------------------------------------------
    # Alignment specifications
    # (name, chrom, 0-based pos, ops_list, nm_corruption)
    #
    # ops_list items:
    #   ('M', length, [mismatch_offsets])   match/mismatch block
    #   ('I', length)                       insertion
    #   ('D', length)                       deletion
    #   ('S', length)                       soft clip
    # ------------------------------------------------------------------
    specs = [
        # ---- Perfect matches (5) ----
        ('read_pm_01', 'chr1', 100,
         [('M', 150, [])], 0),
        ('read_pm_02', 'chr1', 300,
         [('M', 200, [])], 0),
        ('read_pm_03', 'chr1', 600,
         [('M', 180, [])], 2),                          # CORRUPT +2
        ('read_pm_04', 'chr2', 100,
         [('M', 160, [])], 1),                          # CORRUPT +1
        ('read_pm_05', 'chr3', 100,
         [('M', 140, [])], 0),

        # ---- Mismatches only (5) ----
        ('read_mm_01', 'chr1', 850,
         [('M', 120, [5, 45])], 0),
        ('read_mm_02', 'chr2', 300,
         [('M', 130, [10, 30, 55, 80, 110])], 0),
        ('read_mm_03', 'chr1', 1000,
         [('M', 100, [8, 22, 37, 51, 65, 72, 88, 95])], -2),   # CORRUPT -2
        ('read_mm_04', 'chr2', 500,
         [('M', 110, [3, 10, 18, 25, 33, 40, 48, 55,
                       63, 70, 78, 85, 93, 100, 107])], 0),
        ('read_mm_05', 'chr3', 300,
         [('M', 80, [2, 6, 10, 14, 18, 22, 26, 30,
                      34, 38, 42, 46, 50, 54, 58, 62,
                      66, 70, 74, 78])], 3),             # CORRUPT +3

        # ---- Simple indels (3) ----
        ('read_del_01', 'chr1', 1200,
         [('M', 50, []), ('D', 5), ('M', 50, [])], 0),
        ('read_ins_01', 'chr1', 1350,
         [('M', 60, []), ('I', 8), ('M', 60, [])], -3),  # CORRUPT -3
        ('read_del_02', 'chr2', 700,
         [('M', 40, [12, 28]), ('D', 20), ('M', 40, [15, 35])], 0),

        # ---- Complex indels (4) ----
        ('read_cx_01', 'chr1', 1500,
         [('M', 30, [7]), ('I', 3), ('M', 20, []),
          ('D', 4), ('M', 25, [])], 2),                  # CORRUPT +2
        ('read_cx_02', 'chr2', 850,
         [('M', 25, [3, 18]), ('I', 5), ('M', 30, [10]),
          ('D', 3), ('M', 20, [8, 14]), ('I', 2),
          ('M', 15, [])], 0),
        ('read_cx_03', 'chr1', 1700,
         [('M', 35, [5, 22]), ('D', 2), ('M', 15, []),
          ('I', 6), ('M', 40, [8, 25, 33]), ('D', 8),
          ('M', 20, [3])], -4),                           # CORRUPT -4
        ('read_cx_04', 'chr3', 500,
         [('M', 20, [9]), ('I', 10), ('M', 25, [5, 18]),
          ('D', 15), ('M', 30, []), ('I', 5),
          ('M', 20, [])], 0),

        # ---- Soft-clipped (2) ----
        ('read_sc_01', 'chr3', 700,
         [('S', 15), ('M', 80, [5, 30, 55, 70]),
          ('S', 10)], 1),                                 # CORRUPT +1
        ('read_sc_02', 'chr1', 1900,
         [('S', 20), ('M', 100, [12, 28, 45, 63, 78, 90, 95])], 0),

        # ---- Low quality — will fail gc >= 0.85 filter (4) ----
        ('read_lq_01', 'chr1', 2100,
         [('M', 60, [2, 6, 10, 14, 18, 22, 26, 30,
                      34, 38, 42, 46, 50, 54, 58])], 0),
        ('read_lq_02', 'chr2', 1100,
         [('M', 30, [3, 7, 12, 16, 20, 24, 27, 29]),
          ('D', 15), ('M', 20, [4, 9, 13, 17])], 0),
        ('read_lq_03', 'chr3', 1000,
         [('M', 25, [3, 8, 15, 22]), ('I', 3),
          ('M', 15, [4, 9, 12]), ('D', 2),
          ('M', 20, [5, 11, 16]), ('I', 4),
          ('M', 10, [2, 7])], 0),
        ('read_lq_04', 'chr1', 2300,
         [('M', 40, [1, 5, 9, 13, 17, 21, 25, 29, 33, 37])], 0),

        # ---- Other (2) ----
        ('read_oth_01', 'chr2', 1300,
         [('M', 50, [20]), ('I', 1), ('M', 50, [])], 0),
        ('read_oth_02', 'chr1', 2500,
         [('M', 45, [10, 30]), ('D', 3), ('M', 30, []),
          ('I', 2), ('M', 25, [15])], 0),
    ]

    # ------------------------------------------------------------------
    # Build SAM
    # ------------------------------------------------------------------
    sam_lines = ['@HD\tVN:1.6\tSO:unsorted']
    for name in ['chr1', 'chr2', 'chr3']:
        sam_lines.append(f'@SQ\tSN:{name}\tLN:{len(chroms[name])}')

    for spec in specs:
        read_name, chrom, pos0, ops, nm_corrupt = spec

        read_seq = ''
        cigar = ''
        ref_pos = pos0
        correct_nm = 0

        for op in ops:
            op_type = op[0]
            op_len = op[1]

            if op_type == 'M':
                mm_offsets = op[2] if len(op) > 2 else []
                ref_substr = chroms[chrom][ref_pos:ref_pos + op_len]
                bases = list(ref_substr)
                for offset in mm_offsets:
                    bases[offset] = mutate(bases[offset], rng)
                read_seq += ''.join(bases)
                cigar += f'{op_len}M'
                ref_pos += op_len
                correct_nm += len(mm_offsets)
            elif op_type == 'I':
                ins_bases = gen_seq(op_len, rng)
                read_seq += ins_bases
                cigar += f'{op_len}I'
                correct_nm += op_len
            elif op_type == 'D':
                cigar += f'{op_len}D'
                ref_pos += op_len
                correct_nm += op_len
            elif op_type == 'S':
                clip_bases = gen_seq(op_len, rng)
                read_seq += clip_bases
                cigar += f'{op_len}S'

        given_nm = max(0, correct_nm + nm_corrupt)
        qual = 'I' * len(read_seq)

        sam_line = (
            f'{read_name}\t0\t{chrom}\t{pos0 + 1}\t60\t{cigar}'
            f'\t*\t0\t0\t{read_seq}\t{qual}\tNM:i:{given_nm}'
        )
        sam_lines.append(sam_line)

    with open('/app/alignments.sam', 'w') as f:
        f.write('\n'.join(sam_lines) + '\n')

    # Index reference for downstream tools
    subprocess.run(['samtools', 'faidx', '/app/reference.fa'], check=True)

    # ------------------------------------------------------------------
    # Write pipeline configuration and documentation
    # ------------------------------------------------------------------
    write_pipeline_config()
    write_identity_metrics_doc()
    write_aun_doc()


if __name__ == '__main__':
    main()
