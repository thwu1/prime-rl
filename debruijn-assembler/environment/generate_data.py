#!/usr/bin/env python3
"""Generate synthetic k-mer datasets for de Bruijn graph assembly testing."""
import random
import argparse
import sys


def generate_dataset(k, num_contigs, min_len, max_len, seed, kmers_file, contigs_file):
    random.seed(seed)

    all_kmers = {}
    seen_kmers = set()
    valid_contigs = []
    attempts = 0
    max_attempts = num_contigs * 10

    while len(valid_contigs) < num_contigs and attempts < max_attempts:
        attempts += 1
        length = random.randint(min_len, max_len)
        contig = ''.join(random.choice('ACGT') for _ in range(length))

        if length < k:
            continue

        contig_kmers = []
        valid = True
        for i in range(length - k + 1):
            kmer = contig[i:i+k]
            if kmer in seen_kmers:
                valid = False
                break
            contig_kmers.append(kmer)

        if not valid or len(set(contig_kmers)) != len(contig_kmers):
            continue

        seen_kmers.update(contig_kmers)
        valid_contigs.append(contig)

        for i, kmer in enumerate(contig_kmers):
            fwd = contig[i + k] if i + k < length else 'F'
            bwd = contig[i - 1] if i > 0 else 'F'
            all_kmers[kmer] = (fwd, bwd)

    if len(valid_contigs) < num_contigs:
        print(f"Warning: generated {len(valid_contigs)}/{num_contigs} contigs",
              file=sys.stderr)

    with open(kmers_file, 'w') as f:
        f.write(f"{k}\n")
        f.write(f"{len(all_kmers)}\n")
        for kmer, (fwd, bwd) in all_kmers.items():
            f.write(f"{kmer}\t{fwd}\t{bwd}\n")

    with open(contigs_file, 'w') as f:
        for contig in sorted(valid_contigs):
            f.write(f"{contig}\n")

    print(f"Generated {len(valid_contigs)} contigs, {len(all_kmers)} k-mers",
          file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Generate k-mer datasets')
    parser.add_argument('--k', type=int, required=True, help='K-mer length')
    parser.add_argument('--num-contigs', type=int, required=True)
    parser.add_argument('--min-len', type=int, required=True)
    parser.add_argument('--max-len', type=int, required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--kmers-file', required=True)
    parser.add_argument('--contigs-file', required=True)
    args = parser.parse_args()

    generate_dataset(args.k, args.num_contigs, args.min_len, args.max_len,
                     args.seed, args.kmers_file, args.contigs_file)


if __name__ == '__main__':
    main()
