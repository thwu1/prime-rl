
"""Verification tests for genome assembly from heterogeneous k-mer data
with AES-encrypted binary partition, Apache Parquet source, strand
normalization, and coverage-based error filtering."""

import os
import json
import sqlite3
import struct
import subprocess
import tempfile
import pytest


COMPLEMENT = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C', 'F': 'F'}


def reverse_complement(seq):
    return ''.join(COMPLEMENT[b] for b in reversed(seq))


def normalize_record(seq, fwd, bwd, strand):
    """Convert a record from its stored strand to forward orientation."""
    if strand == '-':
        seq = reverse_complement(seq)
        fwd, bwd = COMPLEMENT[bwd], COMPLEMENT[fwd]
    return seq, fwd, bwd


def load_all_data():
    """Load raw k-mer records from all three data sources.

    Returns (records, coverage_threshold, k) where records is a list of
    (sequence, fwd_ext, bwd_ext, strand, coverage) tuples.
    """
    import pyarrow.parquet as pq

    conn = sqlite3.connect('/app/data/kmers.db')
    c = conn.cursor()
    c.execute(
        "SELECT param_value FROM pipeline_params "
        "WHERE param_name='min_reliable_coverage'"
    )
    threshold = int(c.fetchone()[0])
    c.execute(
        "SELECT param_value FROM pipeline_params WHERE param_name='k'"
    )
    k = int(c.fetchone()[0])
    c.execute(
        "SELECT param_value FROM pipeline_params "
        "WHERE param_name='overflow_encryption_cipher'"
    )
    cipher = c.fetchone()[0]
    c.execute(
        "SELECT param_value FROM pipeline_params "
        "WHERE param_name='overflow_encryption_key'"
    )
    enc_key = c.fetchone()[0]
    c.execute(
        "SELECT param_value FROM pipeline_params "
        "WHERE param_name='overflow_encryption_iv'"
    )
    enc_iv = c.fetchone()[0]

    records = []
    c.execute(
        'SELECT sequence, fwd_ext, bwd_ext, strand, depth '
        'FROM kmer_observations'
    )
    for row in c.fetchall():
        records.append(row)
    conn.close()

    # Decrypt and read binary overflow file
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.bin')
    os.close(tmp_fd)
    try:
        subprocess.run([
            'openssl', 'enc', '-d', '-{}'.format(cipher),
            '-K', enc_key, '-iv', enc_iv,
            '-in', '/app/data/overflow.bin.enc', '-out', tmp_path,
        ], check=True, capture_output=True)

        with open(tmp_path, 'rb') as f:
            magic = f.read(4)
            assert magic == b'KMOV', 'Bad binary magic'
            count = struct.unpack('<I', f.read(4))[0]
            file_k = struct.unpack('<I', f.read(4))[0]
            _version = struct.unpack('<I', f.read(4))[0]
            for _ in range(count):
                seq = f.read(file_k).decode('ascii')
                fwd = f.read(1).decode('ascii')
                bwd = f.read(1).decode('ascii')
                flags = struct.unpack('B', f.read(1))[0]
                cov = struct.unpack('<I', f.read(4))[0]
                strand = '-' if (flags & 1) else '+'
                records.append((seq, fwd, bwd, strand, cov))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Read Parquet supplementary file
    table = pq.read_table('/app/data/supplementary.parquet')
    d = table.to_pydict()
    for i in range(len(d['kmer_sequence'])):
        records.append((
            d['kmer_sequence'][i],
            d['forward_extension'][i],
            d['backward_extension'][i],
            d['strand_orientation'][i],
            d['coverage_depth'][i],
        ))

    return records, threshold, k


def compute_reference():
    """Build reference contigs and statistics from raw data."""
    records, threshold, k = load_all_data()

    kmers = {}
    start_nodes = []

    for seq, fwd, bwd, strand, cov in records:
        if cov < threshold:
            continue
        seq, fwd, bwd = normalize_record(seq, fwd, bwd, strand)
        kmers[seq] = (fwd, bwd)
        if bwd == 'F':
            start_nodes.append(seq)

    contigs = []
    for start_kmer in start_nodes:
        chars = list(start_kmer)
        fwd_ext = kmers[start_kmer][0]
        visited = {start_kmer}
        while fwd_ext != 'F':
            chars.append(fwd_ext)
            next_kmer = ''.join(chars[-k:])
            if next_kmer not in kmers or next_kmer in visited:
                break
            visited.add(next_kmer)
            fwd_ext = kmers[next_kmer][0]
        contigs.append(''.join(chars))

    contigs.sort()

    lengths = [len(c) for c in contigs]
    total = sum(lengths)
    sorted_lens = sorted(lengths, reverse=True)
    cumulative = 0
    n50 = 0
    for length in sorted_lens:
        cumulative += length
        if cumulative >= total / 2:
            n50 = length
            break

    stats = {
        'num_contigs': len(contigs),
        'total_bases': total,
        'largest_contig': max(lengths) if lengths else 0,
        'n50': n50,
    }

    return contigs, stats


@pytest.fixture(scope='module')
def reference():
    return compute_reference()


@pytest.fixture(scope='module')
def ref_contigs(reference):
    return reference[0]


@pytest.fixture(scope='module')
def ref_stats(reference):
    return reference[1]


@pytest.fixture(scope='module')
def output_contigs():
    path = '/app/output/contigs.txt'
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


@pytest.fixture(scope='module')
def output_stats():
    path = '/app/output/stats.json'
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


class TestOutputFiles:
    def test_contigs_file_exists(self):
        assert os.path.exists('/app/output/contigs.txt'), \
            'Missing /app/output/contigs.txt'

    def test_stats_file_exists(self):
        assert os.path.exists('/app/output/stats.json'), \
            'Missing /app/output/stats.json'

    def test_contigs_not_empty(self, output_contigs):
        assert output_contigs is not None and len(output_contigs) > 0, \
            'Contigs file is empty or missing'

    def test_stats_is_valid_json(self, output_stats):
        assert output_stats is not None, \
            'stats.json is missing or invalid JSON'


class TestContigFormat:
    def test_all_valid_dna(self, output_contigs):
        """Every contig must contain only A, C, G, T."""
        assert output_contigs is not None
        for i, contig in enumerate(output_contigs):
            assert all(c in 'ACGT' for c in contig), \
                'Contig {} contains invalid characters: {}...'.format(
                    i, contig[:50])

    def test_minimum_contig_length(self, output_contigs):
        """Every contig must be at least k bases long."""
        assert output_contigs is not None
        _, _, k = load_all_data()
        for i, contig in enumerate(output_contigs):
            assert len(contig) >= k, \
                'Contig {} has length {} < k={}'.format(i, len(contig), k)

    def test_lexicographic_sort(self, output_contigs):
        """Output must be sorted lexicographically."""
        assert output_contigs is not None
        for i in range(len(output_contigs) - 1):
            assert output_contigs[i] <= output_contigs[i + 1], \
                'Contigs not sorted at position {}'.format(i)

    def test_no_duplicate_contigs(self, output_contigs):
        """No duplicate contigs in output."""
        assert output_contigs is not None
        assert len(output_contigs) == len(set(output_contigs)), \
            'Output contains duplicate contigs'


class TestCorrectness:
    def test_contig_count(self, output_contigs, ref_contigs):
        """Number of contigs must match reference."""
        assert output_contigs is not None
        assert len(output_contigs) == len(ref_contigs), \
            'Expected {} contigs, got {}'.format(
                len(ref_contigs), len(output_contigs))

    def test_all_contigs_match(self, output_contigs, ref_contigs):
        """Sorted contig sets must be identical."""
        assert output_contigs is not None
        output_sorted = sorted(output_contigs)
        assert output_sorted == ref_contigs, \
            _diff_message(output_sorted, ref_contigs)

    def test_total_assembly_length(self, output_contigs, ref_contigs):
        """Total bases assembled must match reference."""
        assert output_contigs is not None
        out_total = sum(len(c) for c in output_contigs)
        ref_total = sum(len(c) for c in ref_contigs)
        assert out_total == ref_total, \
            'Total assembly length {} != expected {}'.format(
                out_total, ref_total)


class TestStatistics:
    def test_num_contigs(self, output_stats, ref_stats):
        assert output_stats is not None
        assert output_stats['num_contigs'] == ref_stats['num_contigs'], \
            'num_contigs: {} != {}'.format(
                output_stats['num_contigs'], ref_stats['num_contigs'])

    def test_total_bases(self, output_stats, ref_stats):
        assert output_stats is not None
        assert output_stats['total_bases'] == ref_stats['total_bases'], \
            'total_bases: {} != {}'.format(
                output_stats['total_bases'], ref_stats['total_bases'])

    def test_largest_contig(self, output_stats, ref_stats):
        assert output_stats is not None
        assert output_stats['largest_contig'] == ref_stats['largest_contig'], \
            'largest_contig: {} != {}'.format(
                output_stats['largest_contig'], ref_stats['largest_contig'])

    def test_n50(self, output_stats, ref_stats):
        assert output_stats is not None
        assert output_stats['n50'] == ref_stats['n50'], \
            'n50: {} != {}'.format(output_stats['n50'], ref_stats['n50'])


def _diff_message(output, reference):
    missing = set(reference) - set(output)
    extra = set(output) - set(reference)
    parts = ['Contig mismatch.']
    if missing:
        sample = list(missing)[:3]
        parts.append('{} missing contigs (e.g. {}...)'.format(
            len(missing), sample[0][:40]))
    if extra:
        sample = list(extra)[:3]
        parts.append('{} extra contigs (e.g. {}...)'.format(
            len(extra), sample[0][:40]))
    return ' '.join(parts)
