#!/usr/bin/env python3
"""Dump the header and first posting lists from a .docs binary file."""
import struct
import sys


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/app/index/collection.docs'
    with open(path, 'rb') as fh:
        data = fh.read()
    vals = struct.unpack('<' + 'I' * (len(data) // 4), data)
    print("File: %s (%d bytes, %d uint32 values)" % (path, len(data), len(vals)))
    print("Header: [%d, %d] -> doc_count=%d" % (vals[0], vals[1], vals[1]))
    i = 2
    for t in range(min(5, len(vals))):
        if i >= len(vals):
            break
        n = vals[i]
        i += 1
        docs = list(vals[i:i + n])
        i += n
        preview = str(docs[:8])
        if n > 8:
            preview = preview[:-1] + ', ...]'
        print("  Term %d: %d postings -> %s" % (t, n, preview))


if __name__ == '__main__':
    main()
