"""
Compressed Sparse Row (CSR) matrix implementation.

This module is provided as part of the task framework.
Do NOT modify this file.
"""


class SparseMatrix:
    """CSR format sparse matrix for numerical linear algebra."""

    def __init__(self, n):
        """Create an empty n x n sparse matrix."""
        self.n = n
        self.row_ptr = [0] * (n + 1)
        self.col_idx = []
        self.values = []

    @classmethod
    def from_entries(cls, n, entries):
        """
        Build a CSR matrix from a list of (row, col, value) triples.

        Entries are sorted by (row, col). Duplicate (row, col) pairs
        are not supported and will produce incorrect results.
        """
        entries.sort(key=lambda e: (e[0], e[1]))
        mat = cls(n)
        mat.col_idx = [e[1] for e in entries]
        mat.values = [e[2] for e in entries]
        mat.row_ptr = [0] * (n + 1)
        for r, c, v in entries:
            mat.row_ptr[r + 1] += 1
        for i in range(n):
            mat.row_ptr[i + 1] += mat.row_ptr[i]
        return mat

    def matvec(self, x):
        """Compute y = A @ x and return y as a list."""
        y = [0.0] * self.n
        for i in range(self.n):
            s = 0.0
            for idx in range(self.row_ptr[i], self.row_ptr[i + 1]):
                s += self.values[idx] * x[self.col_idx[idx]]
            y[i] = s
        return y

    def diagonal(self):
        """Extract the main diagonal entries as a list."""
        diag = [0.0] * self.n
        for i in range(self.n):
            for idx in range(self.row_ptr[i], self.row_ptr[i + 1]):
                if self.col_idx[idx] == i:
                    diag[i] = self.values[idx]
                    break
        return diag

    def get(self, i, j):
        """Get element A[i][j]. Returns 0.0 if entry is not stored."""
        for idx in range(self.row_ptr[i], self.row_ptr[i + 1]):
            if self.col_idx[idx] == j:
                return self.values[idx]
        return 0.0

    def lower_triangle_entries(self):
        """Yield (row, col, value) for all entries where col <= row."""
        for i in range(self.n):
            for idx in range(self.row_ptr[i], self.row_ptr[i + 1]):
                j = self.col_idx[idx]
                if j <= i:
                    yield (i, j, self.values[idx])

    def nnz(self):
        """Return the number of stored (non-zero) entries."""
        return len(self.values)
