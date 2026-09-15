Implement a genome assembler as a compiled C or C++ binary. Given a dataset of k-mers (DNA subsequences of length k) with adjacency annotations, reconstruct and output the assembled contigs (maximal contiguous DNA sequences).

## Input

Text file (path passed as first CLI argument):

- Line 1: integer `k` (k-mer length, 3 <= k <= 63)
- Line 2: integer `n` (number of k-mers)
- Remaining `n` lines: tab-separated `<kmer> <fwd_ext> <bwd_ext>`

Extensions are single characters from `{A, C, G, T, F}`. A base extension indicates the nucleotide immediately adjacent to that k-mer in the original genome in that direction. `F` indicates no neighbor (chain terminus). Each k-mer appears exactly once and has at most one neighbor in each direction.

## Output

Print all assembled contigs to stdout, one per line, sorted lexicographically.

## Build System

- The project must use **CMake**. Provide a `CMakeLists.txt` in `/app/`.
- Must build correctly via `cmake -B /app/build -S /app && cmake --build /app/build`.
- The final binary must be accessible at `/app/assembler`.

## Memory Safety and Efficiency

- The binary must pass **Valgrind memcheck** with zero errors and zero definite memory leaks.
- Peak heap usage must not exceed **40 MB** on datasets of ~800K k-mers at k=31, as measured by **Valgrind massif**.
- Must handle datasets with up to 2 million k-mers.
- Must correctly handle k values from 3 to 63.

## Files

- `/app/generate_data.py` -- generates synthetic k-mer datasets with known ground-truth contigs
- `/app/data/small.kmers` -- small reference input (k=3, 11 k-mers, 3 contigs)
- `/app/data/small.contigs` -- expected output for the small input