"""GF(2^8) Galois Field Arithmetic.

"""


class GF256:
    """GF(2^8) with irreducible polynomial 0x11B."""

    MODULUS = 0x11B
    GENERATOR = 3

    def __init__(self):
        self._exp = [0] * 512
        self._log = [0] * 256
        self._build_tables()

    def _build_tables(self):
        x = 1
        for i in range(255):
            self._exp[i] = x
            self._log[x] = i
            x2 = (x << 1) ^ (self.MODULUS if x & 0x80 else 0)
            x = (x2 ^ x) & 0xFF
        for i in range(255, 512):
            self._exp[i] = self._exp[i - 255]
        self._log[0] = -1

    def add(self, a, b):
        return a ^ b

    def sub(self, a, b):
        return a ^ b

    def mul(self, a, b):
        if a == 0 or b == 0:
            return 0
        return self._exp[(self._log[a] + self._log[b]) % 255]

    def div(self, a, b):
        if b == 0:
            raise ZeroDivisionError("division by zero in GF(2^8)")
        if a == 0:
            return 0
        return self._exp[(self._log[a] - self._log[b]) % 255]

    def inv(self, a):
        if a == 0:
            raise ZeroDivisionError("zero has no inverse in GF(2^8)")
        return self._exp[255 - self._log[a]]

    def power(self, a, n):
        if n == 0:
            return 1
        if a == 0:
            return 0
        return self._exp[(self._log[a] * n) % 255]


gf = GF256()


def gf_matrix_mul(A, B):
    """Multiply matrices over GF(2^8)."""
    r1 = len(A)
    c1 = len(A[0])
    c2 = len(B[0])
    C = [[0] * c2 for _ in range(r1)]
    for i in range(r1):
        for j in range(c2):
            v = 0
            for k in range(c1):
                v ^= gf.mul(A[i][k], B[k][j])
            C[i][j] = v
    return C


def gf_matrix_inv(matrix):
    """Invert a square matrix over GF(2^8) via Gauss-Jordan."""
    n = len(matrix)
    aug = [row[:] + [1 if i == j else 0 for j in range(n)]
           for i, row in enumerate(matrix)]

    for col in range(n):
        pivot = -1
        for row in range(col, n):
            if aug[row][col] != 0:
                pivot = row
                break
        if pivot == -1:
            raise ValueError("singular matrix in GF(2^8)")
        aug[col], aug[pivot] = aug[pivot], aug[col]

        scale = gf.inv(aug[col][col])
        for j in range(2 * n):
            aug[col][j] = gf.mul(aug[col][j], scale)

        for row in range(n):
            if row != col and aug[row][col] != 0:
                factor = aug[row][col]
                for j in range(2 * n):
                    aug[row][j] ^= gf.mul(factor, aug[col][j])

    return [row[n:] for row in aug]
