# Sparse Matrix Input Format

The pipeline reads matrices in CSR (Compressed Sparse Row) format from a directory
containing four raw files.

## row.raw
Row pointer array.  First line: number of entries (dim + 1).
Remaining lines: one integer per line, 0-indexed.

## col.raw
Column index array.  First line: number of entries (nnz).
Remaining lines: one integer per line, 0-indexed.

## data.raw
Non-zero values.  First line: number of entries (nnz).
Remaining lines: one floating-point value per line (scientific notation).

## vec.raw
Input vector for SpMV.  First line: number of entries (dim).
Remaining lines: one floating-point value per line (scientific notation).

## Example

For a 3x3 matrix  [[1,2,0],[0,3,4],[5,0,6]]:

- row.raw: 4 entries -> [0, 2, 4, 6]
- col.raw: 6 entries -> [0, 1, 1, 2, 0, 2]
- data.raw: 6 entries -> [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
