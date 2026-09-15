"""Tests for alignment identity audit task.

Independently computes correct NM values and identity metrics by comparing
read sequences against the reference genome, then verifies the agent's output.
"""

import json
import os
import re
import csv
import pytest
import pysam


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_cigar(cigar_str):
    """Parse CIGAR string into list of (op_len, op_char) tuples."""
    return [(int(x), y) for x, y in re.findall(r'(\d+)([MIDNSHP=X])', cigar_str)]


def compute_correct_nm(read_seq, ref_substr, cigar_ops):
    """Recompute NM from read sequence, reference substring, and CIGAR.

    Returns (correct_nm, mismatches, ins_bases, del_bases).
    """
    ref_pos = 0
    read_pos = 0
    mismatches = 0
    ins_bases = 0
    del_bases = 0

    for op_len, op_char in cigar_ops:
        if op_char in ('M', '=', 'X'):
            for i in range(op_len):
                if read_seq[read_pos + i].upper() != ref_substr[ref_pos + i].upper():
                    mismatches += 1
            read_pos += op_len
            ref_pos += op_len
        elif op_char == 'I':
            ins_bases += op_len
            read_pos += op_len
        elif op_char == 'D':
            del_bases += op_len
            ref_pos += op_len
        elif op_char == 'N':
            ref_pos += op_len
        elif op_char == 'S':
            read_pos += op_len
        elif op_char == 'H':
            pass
        elif op_char == 'P':
            pass

    return mismatches + ins_bases + del_bases, mismatches, ins_bases, del_bases


def compute_identities(correct_nm, cigar_ops):
    """Compute BLAST, gap-compressed, and gap-excluded identity.

    Returns (blast_id, gc_id, ge_id, alignment_length).
    """
    m_sum = sum(l for l, c in cigar_ops if c in ('M', '=', 'X'))
    i_sum = sum(l for l, c in cigar_ops if c == 'I')
    d_sum = sum(l for l, c in cigar_ops if c == 'D')
    i_count = sum(1 for _, c in cigar_ops if c == 'I')
    d_count = sum(1 for _, c in cigar_ops if c == 'D')

    gap_sum = i_sum + d_sum
    gap_opens = i_count + d_count
    alignment_length = m_sum + i_sum + d_sum
    mismatches = correct_nm - gap_sum

    blast_id = (alignment_length - correct_nm) / alignment_length if alignment_length > 0 else 0.0
    gc_id = 1.0 - (mismatches + gap_opens) / (m_sum + gap_opens) if (m_sum + gap_opens) > 0 else 0.0
    ge_id = (m_sum - mismatches) / m_sum if m_sum > 0 else 0.0

    return blast_id, gc_id, ge_id, alignment_length


# ---------------------------------------------------------------------------
# Fixture: independently computed ground truth
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def ground_truth():
    """Compute ground truth from reference + original SAM (no pre-computed data)."""
    ref = {}
    with pysam.FastaFile('/app/reference.fa') as fa:
        for name in fa.references:
            ref[name] = fa.fetch(name)

    results = {}

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

            ref_consumed = sum(l for l, c in cigar_ops if c in ('M', 'D', 'N', '=', 'X'))
            ref_substr = ref[chrom][pos0:pos0 + ref_consumed]

            correct_nm, mm, ins, dels = compute_correct_nm(read_seq, ref_substr, cigar_ops)
            blast_id, gc_id, ge_id, aln_len = compute_identities(correct_nm, cigar_ops)

            results[name] = {
                'correct_nm': correct_nm,
                'original_nm': original_nm,
                'nm_is_correct': correct_nm == original_nm,
                'blast_identity': blast_id,
                'gap_compressed_identity': gc_id,
                'gap_excluded_identity': ge_id,
                'alignment_length': aln_len,
                'passes_filter': gc_id >= 0.85,
            }

    return results


# ---------------------------------------------------------------------------
# identity_report.tsv
# ---------------------------------------------------------------------------

class TestIdentityReport:

    def test_file_exists(self):
        assert os.path.exists('/app/identity_report.tsv'), \
            'identity_report.tsv not found'

    def test_header(self):
        with open('/app/identity_report.tsv') as f:
            header = f.readline().strip().split('\t')
        expected = [
            'read_name', 'blast_identity', 'gap_compressed_identity',
            'gap_excluded_identity', 'original_nm', 'correct_nm', 'nm_is_correct',
        ]
        assert header == expected, f'Header mismatch: {header}'

    def test_row_count(self, ground_truth):
        with open('/app/identity_report.tsv') as f:
            reader = csv.DictReader(f, delimiter='\t')
            rows = list(reader)
        assert len(rows) == len(ground_truth), \
            f'Expected {len(ground_truth)} rows, got {len(rows)}'

    def test_sorted_by_name(self):
        with open('/app/identity_report.tsv') as f:
            reader = csv.DictReader(f, delimiter='\t')
            names = [row['read_name'] for row in reader]
        assert names == sorted(names), 'Rows not sorted by read_name'

    def test_correct_nm_values(self, ground_truth):
        with open('/app/identity_report.tsv') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                name = row['read_name']
                assert name in ground_truth, f'Unknown read: {name}'
                gt = ground_truth[name]
                assert int(row['correct_nm']) == gt['correct_nm'], \
                    f"Wrong correct_nm for {name}: got {row['correct_nm']}, expected {gt['correct_nm']}"

    def test_original_nm_values(self, ground_truth):
        with open('/app/identity_report.tsv') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                name = row['read_name']
                gt = ground_truth[name]
                assert int(row['original_nm']) == gt['original_nm'], \
                    f"Wrong original_nm for {name}: got {row['original_nm']}, expected {gt['original_nm']}"

    def test_nm_is_correct_flag(self, ground_truth):
        with open('/app/identity_report.tsv') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                name = row['read_name']
                gt = ground_truth[name]
                expected = 'true' if gt['nm_is_correct'] else 'false'
                assert row['nm_is_correct'].lower() == expected, \
                    f"Wrong nm_is_correct for {name}: got {row['nm_is_correct']}, expected {expected}"

    def test_blast_identity(self, ground_truth):
        with open('/app/identity_report.tsv') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                name = row['read_name']
                gt = ground_truth[name]
                got = float(row['blast_identity'])
                expected = gt['blast_identity']
                assert abs(got - expected) < 1e-4, \
                    f'Wrong blast_identity for {name}: got {got:.6f}, expected {expected:.6f}'

    def test_gap_compressed_identity(self, ground_truth):
        with open('/app/identity_report.tsv') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                name = row['read_name']
                gt = ground_truth[name]
                got = float(row['gap_compressed_identity'])
                expected = gt['gap_compressed_identity']
                assert abs(got - expected) < 1e-4, \
                    f'Wrong gap_compressed_identity for {name}: got {got:.6f}, expected {expected:.6f}'

    def test_gap_excluded_identity(self, ground_truth):
        with open('/app/identity_report.tsv') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                name = row['read_name']
                gt = ground_truth[name]
                got = float(row['gap_excluded_identity'])
                expected = gt['gap_excluded_identity']
                assert abs(got - expected) < 1e-4, \
                    f'Wrong gap_excluded_identity for {name}: got {got:.6f}, expected {expected:.6f}'


# ---------------------------------------------------------------------------
# corrected.bam
# ---------------------------------------------------------------------------

class TestCorrectedBam:

    def test_bam_exists(self):
        assert os.path.exists('/app/corrected.bam'), 'corrected.bam not found'

    def test_bai_exists(self):
        assert os.path.exists('/app/corrected.bam.bai'), 'corrected.bam.bai not found'

    def test_is_coordinate_sorted(self):
        with pysam.AlignmentFile('/app/corrected.bam', 'rb') as bam:
            prev_tid = -1
            prev_pos = -1
            for read in bam:
                if read.reference_id > prev_tid:
                    prev_pos = -1
                elif read.reference_id == prev_tid:
                    assert read.reference_start >= prev_pos, \
                        f'BAM not sorted: {read.query_name} at pos {read.reference_start} after {prev_pos}'
                else:
                    pytest.fail(f'BAM not sorted: tid {read.reference_id} after {prev_tid}')
                prev_tid = read.reference_id
                prev_pos = read.reference_start

    def test_correct_read_count(self, ground_truth):
        expected_count = sum(1 for gt in ground_truth.values() if gt['passes_filter'])
        with pysam.AlignmentFile('/app/corrected.bam', 'rb') as bam:
            actual_count = sum(1 for _ in bam)
        assert actual_count == expected_count, \
            f'Expected {expected_count} reads in filtered BAM, got {actual_count}'

    def test_only_passing_reads(self, ground_truth):
        passing_names = {name for name, gt in ground_truth.items() if gt['passes_filter']}
        with pysam.AlignmentFile('/app/corrected.bam', 'rb') as bam:
            for read in bam:
                assert read.query_name in passing_names, \
                    f'Read {read.query_name} should not be in filtered BAM (gc < 0.85)'

    def test_corrected_nm_tags(self, ground_truth):
        with pysam.AlignmentFile('/app/corrected.bam', 'rb') as bam:
            for read in bam:
                name = read.query_name
                gt = ground_truth[name]
                nm = read.get_tag('NM')
                assert nm == gt['correct_nm'], \
                    f"NM tag not corrected for {name}: got {nm}, expected {gt['correct_nm']}"


# ---------------------------------------------------------------------------
# summary.json
# ---------------------------------------------------------------------------

class TestSummary:

    def test_file_exists(self):
        assert os.path.exists('/app/summary.json'), 'summary.json not found'

    def test_valid_json(self):
        with open('/app/summary.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_total_alignments(self, ground_truth):
        with open('/app/summary.json') as f:
            data = json.load(f)
        assert data['total_alignments'] == len(ground_truth)

    def test_incorrect_nm_count(self, ground_truth):
        expected = sum(1 for gt in ground_truth.values() if not gt['nm_is_correct'])
        with open('/app/summary.json') as f:
            data = json.load(f)
        assert data['alignments_with_incorrect_nm'] == expected, \
            f"Expected {expected}, got {data['alignments_with_incorrect_nm']}"

    def test_mean_blast_identity(self, ground_truth):
        expected = sum(gt['blast_identity'] for gt in ground_truth.values()) / len(ground_truth)
        with open('/app/summary.json') as f:
            data = json.load(f)
        assert abs(data['mean_blast_identity'] - expected) < 1e-4, \
            f"Expected {expected:.6f}, got {data['mean_blast_identity']}"

    def test_mean_gap_compressed_identity(self, ground_truth):
        expected = sum(gt['gap_compressed_identity'] for gt in ground_truth.values()) / len(ground_truth)
        with open('/app/summary.json') as f:
            data = json.load(f)
        assert abs(data['mean_gap_compressed_identity'] - expected) < 1e-4, \
            f"Expected {expected:.6f}, got {data['mean_gap_compressed_identity']}"

    def test_mean_gap_excluded_identity(self, ground_truth):
        expected = sum(gt['gap_excluded_identity'] for gt in ground_truth.values()) / len(ground_truth)
        with open('/app/summary.json') as f:
            data = json.load(f)
        assert abs(data['mean_gap_excluded_identity'] - expected) < 1e-4, \
            f"Expected {expected:.6f}, got {data['mean_gap_excluded_identity']}"

    def test_passing_filter_count(self, ground_truth):
        expected = sum(1 for gt in ground_truth.values() if gt['passes_filter'])
        with open('/app/summary.json') as f:
            data = json.load(f)
        assert data['alignments_passing_filter'] == expected, \
            f"Expected {expected}, got {data['alignments_passing_filter']}"

    def test_alignment_aun(self, ground_truth):
        passing = [gt for gt in ground_truth.values() if gt['passes_filter']]
        lengths = [gt['alignment_length'] for gt in passing]
        sum_l = sum(lengths)
        sum_l2 = sum(l * l for l in lengths)
        expected_aun = sum_l2 / sum_l if sum_l > 0 else 0.0

        with open('/app/summary.json') as f:
            data = json.load(f)
        assert abs(data['alignment_aun'] - expected_aun) < 0.1, \
            f"Expected auN {expected_aun:.6f}, got {data['alignment_aun']}"
