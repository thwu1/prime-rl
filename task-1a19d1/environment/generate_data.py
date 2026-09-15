#!/usr/bin/env python3
"""Generate k-mer dataset with strand orientation, coverage-based error k-mers,
and three heterogeneous storage formats (SQLite, AES-encrypted packed binary,
Apache Parquet).

Creates synthetic genome contigs, extracts k-mers with forward/backward
extensions, injects low-coverage error k-mers, randomly stores some records
in reverse-complement orientation, and distributes across three file formats.
The binary overflow file is encrypted with AES-256-CBC using openssl.
"""
import random
import os
import sys
import sqlite3
import struct
import subprocess

random.seed(42)

K = 31
BASES = 'ACGT'
COMPLEMENT = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C', 'F': 'F'}
COVERAGE_THRESHOLD = 5

# Deterministic encryption parameters
ENC_CIPHER = 'aes-256-cbc'
ENC_KEY = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2'
ENC_IV = '1234567890abcdef1234567890abcdef'


def reverse_complement(seq):
    return ''.join(COMPLEMENT[b] for b in reversed(seq))


def rc_extensions(fwd, bwd):
    return COMPLEMENT[bwd], COMPLEMENT[fwd]


# --- Generate contigs ---
contig_specs = []
for _ in range(500):
    contig_specs.append(random.randint(150, 800))
for _ in range(25):
    contig_specs.append(K)
for _ in range(15):
    contig_specs.append(K + 1)
for _ in range(10):
    contig_specs.append(random.randint(1500, 4000))

random.shuffle(contig_specs)

os.makedirs('/app/data', exist_ok=True)

real_kmers = {}
contig_count = 0
skipped = 0

for length in contig_specs:
    seq = ''.join(random.choice(BASES) for _ in range(length))
    n_kmers = length - K + 1

    kmers_in_seq = []
    valid = True
    for i in range(n_kmers):
        kmer = seq[i:i + K]
        rc = reverse_complement(kmer)
        if kmer in real_kmers or rc in real_kmers:
            valid = False
            break
        kmers_in_seq.append(kmer)

    if not valid:
        skipped += 1
        continue
    if len(set(kmers_in_seq)) != len(kmers_in_seq):
        skipped += 1
        continue

    for i in range(n_kmers):
        kmer = seq[i:i + K]
        fwd = seq[i + K] if i + K < length else 'F'
        bwd = seq[i - 1] if i > 0 else 'F'
        coverage = random.randint(10, 50)
        real_kmers[kmer] = (fwd, bwd, coverage)

    contig_count += 1

# --- Generate error k-mers (low coverage) ---
all_kmers = dict(real_kmers)
error_count = 0
target_errors = 600
attempts = 0
while error_count < target_errors and attempts < target_errors * 20:
    kmer = ''.join(random.choice(BASES) for _ in range(K))
    rc = reverse_complement(kmer)
    if kmer not in all_kmers and rc not in all_kmers:
        fwd = random.choice('ACGTF')
        bwd = random.choice('ACGTF')
        coverage = random.randint(1, COVERAGE_THRESHOLD - 1)
        all_kmers[kmer] = (fwd, bwd, coverage)
        error_count += 1
    attempts += 1

# --- Prepare records with random strand orientation ---
items = list(all_kmers.items())
random.shuffle(items)

records = []
for kmer, (fwd, bwd, cov) in items:
    if random.random() < 0.35:
        rc_kmer = reverse_complement(kmer)
        rc_fwd, rc_bwd = rc_extensions(fwd, bwd)
        records.append((rc_kmer, rc_fwd, rc_bwd, cov, '-'))
    else:
        records.append((kmer, fwd, bwd, cov, '+'))

# --- Split into 3 data sources ---
random.shuffle(records)
split1 = int(len(records) * 0.50)
split2 = int(len(records) * 0.80)
db_records = records[:split1]
bin_records = records[split1:split2]
pq_records = records[split2:]

# ---- Write SQLite database ----
db_path = '/app/data/kmers.db'
if os.path.exists(db_path):
    os.remove(db_path)
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute('''CREATE TABLE pipeline_params (
    param_name TEXT PRIMARY KEY,
    param_value TEXT
)''')
params = [
    ('pipeline_version', '4.1.0'),
    ('organism', 'synthetic_isolate'),
    ('read_length', '150'),
    ('sequencing_platform', 'illumina_novaseq'),
    ('timestamp', '2024-12-03T14:22:00Z'),
    ('k', str(K)),
    ('num_sources', '3'),
    ('min_reliable_coverage', str(COVERAGE_THRESHOLD)),
    ('error_correction_status', 'incomplete'),
    ('overflow_encryption_cipher', ENC_CIPHER),
    ('overflow_encryption_key', ENC_KEY),
    ('overflow_encryption_iv', ENC_IV),
]
c.executemany('INSERT INTO pipeline_params VALUES (?, ?)', params)

c.execute('''CREATE TABLE kmer_observations (
    obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence TEXT NOT NULL,
    fwd_ext CHAR(1) NOT NULL,
    bwd_ext CHAR(1) NOT NULL,
    strand CHAR(1) NOT NULL DEFAULT '+',
    depth INTEGER NOT NULL,
    batch_label TEXT DEFAULT 'primary'
)''')
c.execute('CREATE INDEX idx_kmer_seq ON kmer_observations(sequence)')

for i, (seq, fwd, bwd, cov, strand) in enumerate(db_records):
    batch = 'batch_{}'.format(i % 12)
    c.execute(
        'INSERT INTO kmer_observations (sequence, fwd_ext, bwd_ext, strand, depth, batch_label) VALUES (?, ?, ?, ?, ?, ?)',
        (seq, fwd, bwd, strand, cov, batch)
    )

conn.commit()
conn.close()

# ---- Write binary overflow file then encrypt with openssl ----
bin_path = '/app/data/overflow.bin'
enc_path = '/app/data/overflow.bin.enc'
with open(bin_path, 'wb') as f:
    f.write(b'KMOV')
    f.write(struct.pack('<I', len(bin_records)))
    f.write(struct.pack('<I', K))
    f.write(struct.pack('<I', 2))
    for seq, fwd, bwd, cov, strand in bin_records:
        f.write(seq.encode('ascii'))
        f.write(fwd.encode('ascii'))
        f.write(bwd.encode('ascii'))
        flags = 1 if strand == '-' else 0
        f.write(struct.pack('B', flags))
        f.write(struct.pack('<I', cov))

subprocess.run([
    'openssl', 'enc', '-' + ENC_CIPHER,
    '-K', ENC_KEY, '-iv', ENC_IV,
    '-in', bin_path, '-out', enc_path,
], check=True)
os.remove(bin_path)

# ---- Write Apache Parquet file ----
import pyarrow as pa
import pyarrow.parquet as pq

table = pa.table({
    'kmer_sequence': [r[0] for r in pq_records],
    'forward_extension': [r[1] for r in pq_records],
    'backward_extension': [r[2] for r in pq_records],
    'coverage_depth': [r[3] for r in pq_records],
    'strand_orientation': [r[4] for r in pq_records],
})
pq.write_table(table, '/app/data/supplementary.parquet', compression='snappy')

# ---- Write dataset manifest ----
manifest_text = """# Dataset Manifest - Genome K-mer Observations
# Generated by sequencing pipeline v4.1.0

dataset:
  name: synthetic_isolate_exp078
  k_value: {k}
  description: >
    K-mer observations extracted from Illumina paired-end sequencing reads
    of a synthetic isolate genome. Each k-mer is a DNA subsequence of length k.
    Overlapping k-mers (sharing k-1 bases) originate from the same genomic
    region. Each observation records the k-mer sequence, the single-base
    forward and backward extensions in the genome (or 'F' for a terminal
    position), the strand of origin, and the observed sequencing depth
    (coverage). Records are stored in the strand orientation in which they
    were observed; negative-strand observations represent the reverse
    complement of the genomic sequence.

  notes: >
    WARNING: The upstream error-correction module did not complete. The dataset
    therefore contains both genuine genomic k-mers (typically at higher depth)
    and spurious k-mers arising from uncorrected sequencing errors. Consult
    the pipeline parameters for the reliability threshold. Only k-mers meeting
    the reliability criterion should be used for assembly.

sources:
  - name: primary_observations
    type: sqlite3
    path: kmers.db
    notes: >
      Contains the majority of k-mer observations. Use the sqlite3 CLI
      or a programmatic driver to explore the schema. Pipeline parameters
      including the coverage reliability threshold are stored in a
      separate metadata table. Encryption parameters for the overflow
      partition are also stored here.

  - name: overflow_partition
    type: encrypted_binary
    path: overflow.bin.enc
    notes: >
      K-mer records that overflowed the primary store during pipeline
      execution. This file is encrypted at rest. The encryption parameters
      (cipher, key, initialization vector) are stored in the pipeline
      parameters metadata table. After decryption, the plaintext is a
      packed binary format with a fixed header followed by fixed-size
      records. Each record includes a flags byte encoding strand
      orientation (bit 0: 0 = forward, 1 = reverse complement).

  - name: supplementary
    type: apache_parquet
    path: supplementary.parquet
    notes: >
      Late-arriving k-mer observations stored in Apache Parquet columnar
      format with Snappy compression. Column names follow a verbose naming
      convention that differs from the other sources. Strand and coverage
      information included.

output:
  contigs:
    path: /app/output/contigs.txt
    format: one assembled contig per line, sorted lexicographically
  statistics:
    path: /app/output/stats.json
    format: >
      JSON object with assembly quality metrics: num_contigs (integer),
      total_bases (integer), largest_contig (integer, length of longest
      contig), n50 (integer, standard N50 metric)
""".format(k=K)

with open('/app/data/manifest.yaml', 'w') as f:
    f.write(manifest_text)

print('Generated {} total k-mers (K={}, contigs={}, errors={}, skipped={})'.format(
    len(all_kmers), K, contig_count, error_count, skipped), file=sys.stderr)
print('  SQLite: {} records'.format(len(db_records)), file=sys.stderr)
print('  Binary (encrypted): {} records'.format(len(bin_records)), file=sys.stderr)
print('  Parquet: {} records'.format(len(pq_records)), file=sys.stderr)
