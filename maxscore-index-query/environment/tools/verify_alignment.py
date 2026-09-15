#!/usr/bin/env python3
"""Verify .docs and .freqs posting list alignment."""
import struct
import sys


def count_sequences(path, skip_header=False):
    with open(path, 'rb') as fh:
        data = fh.read()
    vals = struct.unpack('<' + 'I' * (len(data) // 4), data)
    lengths = []
    i = 0
    if skip_header:
        hdr_len = vals[0]
        i = hdr_len + 1
    while i < len(vals):
        n = vals[i]
        i += 1 + n
        lengths.append(n)
    return lengths


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else '/app/index/collection'
    doc_counts = count_sequences(base + '.docs', skip_header=True)
    freq_counts = count_sequences(base + '.freqs', skip_header=False)
    print("Posting lists in .docs: %d" % len(doc_counts))
    print("Posting lists in .freqs: %d" % len(freq_counts))
    if len(doc_counts) != len(freq_counts):
        print("ERROR: Count mismatch!")
        return
    bad = sum(1 for a, b in zip(doc_counts, freq_counts) if a != b)
    if bad == 0:
        print("All posting lists are properly aligned.")
    else:
        print("%d misaligned posting lists!" % bad)


if __name__ == '__main__':
    main()
