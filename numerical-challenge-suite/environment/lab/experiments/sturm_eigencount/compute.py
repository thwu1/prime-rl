"""Count eigenvalues of the N x N symmetric tridiagonal matrix T
in the open interval (0.2, 0.8), where:
    T_{ii} = 2 + 0.3 * sin(2*pi*i/N),  i = 1, ..., N
    T_{i,i+1} = T_{i+1,i} = -1
    N = 5000
Uses Sturm sequence (LDLT pivots) for exact counting.
"""
import math


def compute():
    N = 5000
    diag = [2.0 + 0.3 * math.sin(2.0 * math.pi * i / N)
            for i in range(1, N + 1)]

    def count_eigs_below(sigma):
        neg_count = 0
        q = diag[0] - sigma
        if q < 0:
            neg_count += 1
        for k in range(1, N):
            if abs(q) < 1e-300:
                q = 1e-300 if q >= 0 else -1e-300
            q = (diag[k] - sigma) - 1.0 / q
            if q < 0:
                neg_count += 1
        return neg_count

    count_upper = count_eigs_below(0.8)
    count_lower = count_eigs_below(0.2)
    return count_upper - count_lower


if __name__ == "__main__":
    result = compute()
    print(f"Eigenvalue count in (0.2, 0.8): {result}")
    print(f"RESULT: {result}")
