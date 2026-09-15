
"""
Verify a forged Vinaigrette signature.
Checks that the submitted signature satisfies the verification equation:
  sum_{i=1}^{k} p_j(s_i) == H(lambda)_j  (mod q)  for all j
"""

import json
import hashlib
import os
import pytest


def load_params():
    with open('/app/params.json', 'r') as f:
        return json.load(f)


def load_public_key(params):
    """Load m matrices of size n x n from the public key file."""
    q = params['q']
    n = params['n']
    m = params['m']
    matrices = []
    with open('/app/public_key.txt', 'r') as f:
        content = f.read().strip()
    blocks = content.split('\n\n')
    assert len(blocks) == m, f"Expected {m} matrices, got {len(blocks)}"
    for block in blocks:
        rows = block.strip().split('\n')
        assert len(rows) == n, f"Expected {n} rows, got {len(rows)}"
        mat = []
        for row in rows:
            vals = [int(x) % q for x in row.split()]
            assert len(vals) == n, f"Expected {n} cols, got {len(vals)}"
            mat.append(vals)
        matrices.append(mat)
    return matrices


def compute_hash(message, q, m):
    """Compute H(lambda) using SHAKE256 with 5-bit extraction."""
    bits_per_elem = 5
    total_bytes = (bits_per_elem * m + 7) // 8
    shake = hashlib.shake_256(message.encode('utf-8')).digest(total_bytes)
    bits = ''.join(format(b, '08b') for b in shake)
    result = []
    for i in range(m):
        val = int(bits[i * 5:(i + 1) * 5], 2) % q
        result.append(val)
    return result


def eval_quadratic(P, x, n, q):
    """Evaluate x^T P x mod q."""
    result = 0
    for i in range(n):
        for r in range(n):
            result += P[i][r] * x[i] * x[r]
    return result % q


def load_signature(params):
    """Load the forged signature from /app/signature.txt."""
    n = params['n']
    k = params['k']
    with open('/app/signature.txt', 'r') as f:
        content = f.read().strip()
    vals = [int(x) for x in content.split()]
    assert len(vals) == k * n, f"Expected {k * n} values, got {len(vals)}"
    sig = []
    for i in range(k):
        vec = vals[i * n:(i + 1) * n]
        sig.append(vec)
    return sig


class TestVinaigrette:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.params = load_params()
        self.pk = load_public_key(self.params)
        self.target = compute_hash(
            self.params['message'],
            self.params['q'],
            self.params['m']
        )

    def test_signature_file_exists(self):
        assert os.path.isfile('/app/signature.txt'), \
            "Signature file /app/signature.txt not found"

    def test_signature_format(self):
        params = self.params
        sig = load_signature(params)
        q = params['q']
        n = params['n']
        k = params['k']
        assert len(sig) == k, f"Expected {k} signature vectors"
        for i, vec in enumerate(sig):
            assert len(vec) == n, f"Vector {i} has length {len(vec)}, expected {n}"
            for j, v in enumerate(vec):
                assert 0 <= v < q, \
                    f"Value {v} at position ({i},{j}) out of range [0,{q-1}]"

    def test_signature_verifies(self):
        params = self.params
        q = params['q']
        n = params['n']
        m = params['m']
        sig = load_signature(params)
        pk = self.pk
        target = self.target

        for j in range(m):
            total = 0
            for s_i in sig:
                total += eval_quadratic(pk[j], s_i, n, q)
            total = total % q
            assert total == target[j], \
                f"Verification failed for polynomial {j}: " \
                f"got {total}, expected {target[j]}"

    def test_hash_target_consistency(self):
        """Verify the precomputed hash target matches our computation."""
        with open('/app/hash_target.txt', 'r') as f:
            stored = [int(x) for x in f.read().strip().split()]
        assert stored == self.target, \
            "Stored hash target doesn't match computed hash"

    def test_signature_nontrivial(self):
        """Ensure the signature is not all zeros."""
        sig = load_signature(self.params)
        all_zero = all(v == 0 for vec in sig for v in vec)
        assert not all_zero, "Signature is trivially all zeros"
