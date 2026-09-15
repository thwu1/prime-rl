#!/usr/bin/env python3

"""
Genome assembler: reads k-mer observations from three heterogeneous data
sources (SQLite, AES-encrypted packed binary, Apache Parquet), applies
coverage-based error filtering, normalizes reverse-complement strand records,
constructs a de Bruijn graph, traverses it to produce contigs, and computes
assembly quality statistics including N50.
"""

import sqlite3
import struct
import subprocess
import tempfile
import json
import os
import sys

import pyarrow.parquet as pq

COMPLEMENT = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C', 'F': 'F'}


def reverse_complement(seq):
    return ''.join(COMPLEMENT[b] for b in reversed(seq))


def normalize_record(seq, fwd, bwd, strand):
    if strand == '-':
        seq = reverse_complement(seq)
        fwd, bwd = COMPLEMENT[bwd], COMPLEMENT[fwd]
    return seq, fwd, bwd


def read_sqlite(db_path):
    conn = sqlite3.connect(db_path)
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

    c.execute(
        'SELECT sequence, fwd_ext, bwd_ext, strand, depth '
        'FROM kmer_observations'
    )
    records = c.fetchall()
    conn.close()
    return records, threshold, k, cipher, enc_key, enc_iv


def read_encrypted_binary(enc_path, k, cipher, enc_key, enc_iv):
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.bin')
    os.close(tmp_fd)
    try:
        subprocess.run([
            'openssl', 'enc', '-d', '-{}'.format(cipher),
            '-K', enc_key, '-iv', enc_iv,
            '-in', enc_path, '-out', tmp_path,
        ], check=True, capture_output=True)

        records = []
        with open(tmp_path, 'rb') as f:
            magic = f.read(4)
            if magic != b'KMOV':
                raise ValueError('Bad magic: {}'.format(magic))
            count = struct.unpack('<I', f.read(4))[0]
            file_k = struct.unpack('<I', f.read(4))[0]
            _version = struct.unpack('<I', f.read(4))[0]
            for _ in range(count):
                seq = f.read(k).decode('ascii')
                fwd = f.read(1).decode('ascii')
                bwd = f.read(1).decode('ascii')
                flags = struct.unpack('B', f.read(1))[0]
                cov = struct.unpack('<I', f.read(4))[0]
                strand = '-' if (flags & 1) else '+'
                records.append((seq, fwd, bwd, strand, cov))
        return records
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def read_parquet(pq_path):
    table = pq.read_table(pq_path)
    d = table.to_pydict()
    records = []
    for i in range(len(d['kmer_sequence'])):
        records.append((
            d['kmer_sequence'][i],
            d['forward_extension'][i],
            d['backward_extension'][i],
            d['strand_orientation'][i],
            d['coverage_depth'][i],
        ))
    return records


def compute_n50(contig_lengths):
    sorted_lengths = sorted(contig_lengths, reverse=True)
    total = sum(sorted_lengths)
    cumulative = 0
    for length in sorted_lengths:
        cumulative += length
        if cumulative >= total / 2:
            return length
    return 0


def main():
    db_records, threshold, k, cipher, enc_key, enc_iv = read_sqlite(
        '/app/data/kmers.db')
    bin_records = read_encrypted_binary(
        '/app/data/overflow.bin.enc', k, cipher, enc_key, enc_iv)
    pq_records = read_parquet('/app/data/supplementary.parquet')

    all_records = list(db_records) + bin_records + pq_records
    print('Loaded {} total records ({} SQLite, {} binary, {} parquet)'.format(
        len(all_records), len(db_records), len(bin_records), len(pq_records)),
        file=sys.stderr)
    print('Coverage threshold: {}'.format(threshold), file=sys.stderr)

    kmers = {}
    start_nodes = []
    filtered_count = 0

    for seq, fwd, bwd, strand, cov in all_records:
        if cov < threshold:
            filtered_count += 1
            continue
        seq, fwd, bwd = normalize_record(seq, fwd, bwd, strand)
        kmers[seq] = (fwd, bwd)
        if bwd == 'F':
            start_nodes.append(seq)

    print('After filtering: {} k-mers ({} removed as errors)'.format(
        len(kmers), filtered_count), file=sys.stderr)
    print('Start nodes: {}'.format(len(start_nodes)), file=sys.stderr)

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
    print('Assembled {} contigs'.format(len(contigs)), file=sys.stderr)

    lengths = [len(c) for c in contigs]
    stats = {
        'num_contigs': len(contigs),
        'total_bases': sum(lengths),
        'largest_contig': max(lengths) if lengths else 0,
        'n50': compute_n50(lengths),
    }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/contigs.txt', 'w') as f:
        for contig in contigs:
            f.write(contig + '\n')

    with open('/app/output/stats.json', 'w') as f:
        json.dump(stats, f, indent=2)

    print('Stats: {}'.format(stats), file=sys.stderr)


if __name__ == '__main__':
    main()
