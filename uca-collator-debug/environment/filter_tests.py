#!/usr/bin/env python3
"""
Filter UCA conformance test files to remove data lines containing
code points not recognised by the current Python unicodedata module.

Python 3.12 ships Unicode 15.0.0.  The allkeys.txt and test files are
from Unicode 17.0.0.  Characters added after 15.0 have category 'Cn'
(unassigned) in Python's unicodedata, which means NFD normalisation
and combining-class lookups cannot handle them correctly.  Removing
these lines preserves the sorted-order invariant (removing elements
from a sorted sequence keeps it sorted) while ensuring the collator
can be tested reliably.
"""

import unicodedata
import sys


def filter_file(in_path, out_path):
    kept = 0
    removed = 0
    with open(in_path, "r", encoding="utf-8") as fin, \
         open(out_path, "w", encoding="utf-8") as fout:
        for line in fin:
            stripped = line.strip()
            # Preserve comments and blank lines
            if not stripped or stripped.startswith("#"):
                fout.write(line)
                continue

            hex_part = stripped.split(";")[0].strip() if ";" in stripped else stripped
            if not hex_part:
                fout.write(line)
                continue

            try:
                cps = [int(tok, 16) for tok in hex_part.split()]
            except ValueError:
                fout.write(line)
                continue

            skip = False
            for cp in cps:
                if 0xD800 <= cp <= 0xDFFF:
                    continue  # surrogates handled elsewhere
                try:
                    if unicodedata.category(chr(cp)) == "Cn":
                        skip = True
                        break
                except (ValueError, OverflowError):
                    skip = True
                    break

            if skip:
                removed += 1
            else:
                fout.write(line)
                kept += 1

    print(f"  {in_path} -> {out_path}: kept {kept}, removed {removed}")


if __name__ == "__main__":
    print("Filtering conformance test files for Unicode compatibility...")
    filter_file(
        "/app/data/CollationTest_NON_IGNORABLE_SHORT_raw.txt",
        "/app/data/CollationTest_NON_IGNORABLE_SHORT.txt",
    )
    filter_file(
        "/app/data/CollationTest_SHIFTED_SHORT_raw.txt",
        "/app/data/CollationTest_SHIFTED_SHORT.txt",
    )
    print("Done.")
