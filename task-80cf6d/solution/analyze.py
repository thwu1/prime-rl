#!/usr/bin/env python3
"""Alignment identity audit — solution.

Parses every alignment in the input SAM, recomputes the correct NM tag by
comparing read bases to the reference through the CIGAR, computes three
identity metrics, and produces the required output files.
"""

import json
import os
import re
import pysam


def parse_cigar(cigar_str):
    return [(int(x), y) for x, y in re.findall(r'(\d+)([MIDNSHP=X])', cigar_str)]


def main():
    # Load reference
    ref = {}
    with pysam.FastaFile('/app/reference.fa') as fa:
        for name in fa.references:
            ref[name] = fa.fetch(name)

    results = []

    with pysam.AlignmentFile('/app/alignments.sam', 'r') as sam:
        for read in sam:
            if read.is_unmapped:
                continue

            name = read.query_name
            chrom = read.reference_name
            pos0 = read.reference_start
            cigar_ops = parse_cigar(read.cigarstring)
            read_seq = read.query_sequence
            original_nm = read.get_tag('NM')

            # Extract reference region consumed by this alignment
            ref_consumed = sum(l for l, c in cigar_ops if c in ('M', 'D', 'N', '=', 'X'))
            ref_substr = ref[chrom][pos0:pos0 + ref_consumed]

            # Walk through CIGAR to recompute NM
            ref_pos = 0
            read_pos = 0
            mismatches = 0
            ins_bases = 0
            del_bases = 0
            m_sum = 0
            i_sum = 0
            d_sum = 0
            i_count = 0
            d_count = 0

            for op_len, op_char in cigar_ops:
                if op_char in ('M', '=', 'X'):
                    for i in range(op_len):
                        if read_seq[read_pos + i].upper() != ref_substr[ref_pos + i].upper():
                            mismatches += 1
                    read_pos += op_len
                    ref_pos += op_len
                    m_sum += op_len
                elif op_char == 'I':
                    ins_bases += op_len
                    read_pos += op_len
                    i_sum += op_len
                    i_count += 1
                elif op_char == 'D':
                    del_bases += op_len
                    ref_pos += op_len
                    d_sum += op_len
                    d_count += 1
                elif op_char == 'N':
                    ref_pos += op_len
                elif op_char == 'S':
                    read_pos += op_len
                elif op_char == 'H':
                    pass

            correct_nm = mismatches + ins_bases + del_bases

            # Identity metrics
            gap_sum = i_sum + d_sum
            gap_opens = i_count + d_count
            alignment_length = m_sum + i_sum + d_sum

            blast_id = (alignment_length - correct_nm) / alignment_length if alignment_length > 0 else 0.0
            gc_id = (1.0 - (mismatches + gap_opens) / (m_sum + gap_opens)) if (m_sum + gap_opens) > 0 else 0.0
            ge_id = (m_sum - mismatches) / m_sum if m_sum > 0 else 0.0

            results.append({
                'read_name': name,
                'blast_identity': blast_id,
                'gap_compressed_identity': gc_id,
                'gap_excluded_identity': ge_id,
                'original_nm': original_nm,
                'correct_nm': correct_nm,
                'nm_is_correct': correct_nm == original_nm,
                'alignment_length': alignment_length,
                'passes_filter': gc_id >= 0.85,
            })

    # Sort by read_name
    results.sort(key=lambda r: r['read_name'])

    # ---- identity_report.tsv ----
    with open('/app/identity_report.tsv', 'w') as f:
        f.write('read_name\tblast_identity\tgap_compressed_identity\t'
                'gap_excluded_identity\toriginal_nm\tcorrect_nm\tnm_is_correct\n')
        for r in results:
            f.write(
                f"{r['read_name']}\t"
                f"{r['blast_identity']:.6f}\t"
                f"{r['gap_compressed_identity']:.6f}\t"
                f"{r['gap_excluded_identity']:.6f}\t"
                f"{r['original_nm']}\t"
                f"{r['correct_nm']}\t"
                f"{'true' if r['nm_is_correct'] else 'false'}\n"
            )

    # ---- corrected.bam ----
    passing = {r['read_name']: r for r in results if r['passes_filter']}

    with pysam.AlignmentFile('/app/alignments.sam', 'r') as sam_in:
        header = sam_in.header.to_dict()
        header['HD']['SO'] = 'unsorted'

        tmp_bam = '/app/_corrected_unsorted.bam'
        with pysam.AlignmentFile(tmp_bam, 'wb', header=header) as bam_out:
            for read in sam_in:
                if read.query_name in passing:
                    read.set_tag('NM', passing[read.query_name]['correct_nm'], 'i')
                    bam_out.write(read)

    pysam.sort('-o', '/app/corrected.bam', tmp_bam)
    pysam.index('/app/corrected.bam')
    os.remove(tmp_bam)

    # ---- summary.json ----
    n_total = len(results)
    n_incorrect = sum(1 for r in results if not r['nm_is_correct'])
    n_passing = sum(1 for r in results if r['passes_filter'])

    mean_blast = sum(r['blast_identity'] for r in results) / n_total
    mean_gc = sum(r['gap_compressed_identity'] for r in results) / n_total
    mean_ge = sum(r['gap_excluded_identity'] for r in results) / n_total

    passing_lengths = [r['alignment_length'] for r in results if r['passes_filter']]
    sum_l = sum(passing_lengths)
    sum_l2 = sum(l * l for l in passing_lengths)
    aun = sum_l2 / sum_l if sum_l > 0 else 0.0

    summary = {
        'total_alignments': n_total,
        'alignments_with_incorrect_nm': n_incorrect,
        'mean_blast_identity': round(mean_blast, 6),
        'mean_gap_compressed_identity': round(mean_gc, 6),
        'mean_gap_excluded_identity': round(mean_ge, 6),
        'alignments_passing_filter': n_passing,
        'alignment_aun': round(aun, 6),
    }

    with open('/app/summary.json', 'w') as f:
        json.dump(summary, f, indent=2)

    print(f'Analyzed {n_total} alignments')
    print(f'Incorrect NM tags: {n_incorrect}')
    print(f'Passing gc>=0.85 filter: {n_passing}')
    print(f'auN of passing alignments: {aun:.6f}')


if __name__ == '__main__':
    main()
