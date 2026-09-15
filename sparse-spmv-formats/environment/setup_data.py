#!/usr/bin/env python3
"""Set up sparse matrix test data in both CSR text format and Matrix Market format."""
import os


def write_lines(path, values):
    with open(path, "w") as f:
        for v in values:
            f.write(f"{v}\n")


def write_text(path, text):
    with open(path, "w") as f:
        f.write(text)


# ============================================================
# CSR text-format matrices in /app/data/
# ============================================================

# --- Matrix 1: 8x8, 21 nnz, irregular sparsity ---
# Row 0: (0,1.0) (3,2.0)
# Row 1: (1,3.0) (2,4.0) (5,5.0)
# Row 2: (0,6.0) (2,7.0) (4,8.0) (6,9.0) (7,10.0)
# Row 3: (3,11.0)
# Row 4: (1,12.0) (4,13.0) (7,14.0)
# Row 5: (0,15.0) (2,16.0) (5,17.0) (6,18.0)
# Row 6: (6,19.0)
# Row 7: (1,20.0) (3,21.0)
os.makedirs("/app/data/matrix1", exist_ok=True)
write_text("/app/data/matrix1/info.txt", "8 8 21\n")
write_lines("/app/data/matrix1/row_ptr.txt",
            [0, 2, 5, 10, 11, 14, 18, 19, 21])
write_lines("/app/data/matrix1/col_idx.txt",
            [0, 3, 1, 2, 5, 0, 2, 4, 6, 7, 3, 1, 4, 7, 0, 2, 5, 6, 6, 1, 3])
write_lines("/app/data/matrix1/data.txt",
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
             11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0,
             20.0, 21.0])

# --- Matrix 2: 3x3, 3 nnz, has empty row (row 1) ---
# Row 0: (0,1.0) (2,2.0)
# Row 1: (empty)
# Row 2: (1,3.0)
os.makedirs("/app/data/matrix2", exist_ok=True)
write_text("/app/data/matrix2/info.txt", "3 3 3\n")
write_lines("/app/data/matrix2/row_ptr.txt", [0, 2, 2, 3])
write_lines("/app/data/matrix2/col_idx.txt", [0, 2, 1])
write_lines("/app/data/matrix2/data.txt", [1.0, 2.0, 3.0])

# --- Matrix 3: 4x6, 10 nnz, non-square ---
# Row 0: (0,1.0) (5,2.0)
# Row 1: (1,3.0) (2,4.0) (4,5.0)
# Row 2: (3,6.0)
# Row 3: (0,7.0) (2,8.0) (3,9.0) (5,10.0)
os.makedirs("/app/data/matrix3", exist_ok=True)
write_text("/app/data/matrix3/info.txt", "4 6 10\n")
write_lines("/app/data/matrix3/row_ptr.txt", [0, 2, 5, 6, 10])
write_lines("/app/data/matrix3/col_idx.txt",
            [0, 5, 1, 2, 4, 3, 0, 2, 3, 5])
write_lines("/app/data/matrix3/data.txt",
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])

# --- Matrix 4: 4x4 diagonal (all rows NNZ=1, tie-breaking test) ---
# Row 0: (0,2.0)  Row 1: (1,3.0)  Row 2: (2,5.0)  Row 3: (3,7.0)
os.makedirs("/app/data/matrix4", exist_ok=True)
write_text("/app/data/matrix4/info.txt", "4 4 4\n")
write_lines("/app/data/matrix4/row_ptr.txt", [0, 1, 2, 3, 4])
write_lines("/app/data/matrix4/col_idx.txt", [0, 1, 2, 3])
write_lines("/app/data/matrix4/data.txt", [2.0, 3.0, 5.0, 7.0])

# --- Format specification ---
write_text("/app/data/FORMAT.txt", """Sparse Matrix CSR Format
========================
Each matrix directory contains:
  info.txt    - Single line: num_rows num_cols nnz
  row_ptr.txt - (num_rows+1) integers, one per line
                row_ptr[i] to row_ptr[i+1] defines the index range
                in col_idx/data for row i's non-zero entries
  col_idx.txt - nnz integers, one per line (column indices, 0-based)
  data.txt    - nnz floats, one per line (non-zero values)

Example: A 3x3 identity matrix has:
  info.txt:    3 3 3
  row_ptr.txt: 0 1 2 3
  col_idx.txt: 0 1 2
  data.txt:    1.0 1.0 1.0
""")


# ============================================================
# Matrix Market format matrix in /app/matrices/
# ============================================================

# Circuit simulation matrix (5x5, 8 nnz)
# Dense:
# [4.0   0   -1.0   0     0  ]
# [0    5.0   0    -2.0   0  ]
# [-1.0  0    6.0   0     0  ]
# [0     0    0     3.0   0  ]
# [0   -1.0   0     0     0  ]
write_text("/app/matrices/circuit.mtx", """%%MatrixMarket matrix coordinate real general
% Circuit simulation test matrix
% 5x5 with 8 nonzero entries
5 5 8
1 1 4.0
1 3 -1.0
2 2 5.0
2 4 -2.0
3 1 -1.0
3 3 6.0
4 4 3.0
5 2 -1.0
""")
