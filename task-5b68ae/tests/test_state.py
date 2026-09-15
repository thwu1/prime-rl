
"""
Tests for Vinaigrette signature forging task.
Verifies that /app/signature.txt contains a valid forged signature.
Uses embedded public key data for independent verification.
"""

import hashlib
import math
import os
import pytest


# Embedded scheme parameters (from deployment database)
_Q = 31
_N = 12
_M = 8
_O = 6
_K = 2
_MESSAGE = "Forge this Vinaigrette signature"

# Embedded public key matrices (from deployment, upper-triangular format)
_PUBKEY_RAW = """\
25 7 14 11 7 22 25 21 30 17 22 0
6 19 30 13 5 19 5 3 4 1 24
12 23 0 23 2 2 28 9 8 11
21 24 0 13 29 3 25 24 14
12 6 22 7 24 25 10 4
4 9 24 26 13 4 14
4 24 23 21 1 21
0 12 15 22 24
11 28 14 12
28 19 1
21 18
30

27 17 10 18 28 28 17 13 11 14 21 20
26 24 21 1 9 14 24 16 29 2 30
10 16 2 16 8 19 5 29 1 7
29 5 5 23 12 6 4 15 8
5 12 14 25 29 25 9 24
13 29 1 13 21 10 26
18 28 1 9 27 20
25 15 14 3 13
14 28 26 8
20 19 23
2 10
14

17 15 14 24 22 5 26 9 27 8 11 16
6 4 3 7 26 22 27 15 1 16 13
29 10 15 16 18 13 22 9 0 7
6 0 22 7 27 16 15 18 0
29 20 30 4 0 10 2 20
2 23 21 21 2 17 5
9 22 3 4 4 3
17 18 30 10 26
20 9 9 3
4 7 3
12 4
16

17 0 4 27 30 24 24 12 17 6 14 26
9 25 13 27 18 4 0 13 27 15 23
30 5 27 29 21 3 10 16 18 4
5 15 24 1 7 14 21 13 13
26 16 27 2 23 16 22 18
12 6 25 25 22 15 28
26 9 0 20 23 30
10 28 12 2 7
26 18 0 19
6 5 14
16 13
26

3 11 15 29 8 24 30 9 8 25 23 28
7 13 24 23 6 30 20 8 29 3 9
9 4 6 24 4 22 22 26 19 16
9 24 21 23 24 17 16 5 4
23 21 23 15 11 13 3 13
26 9 19 7 21 10 1
3 16 30 9 30 4
21 10 4 11 21
16 4 26 9
16 10 23
16 9
23

4 6 26 11 10 8 16 28 25 23 16 19
29 10 2 7 12 22 15 13 3 10 0
0 22 26 28 4 28 9 30 4 22
3 13 28 22 18 11 24 8 2
18 23 11 5 30 9 2 19
25 24 21 18 23 6 0
24 26 14 4 12 3
8 22 29 7 25
8 18 24 24
18 6 30
10 8
16

21 3 13 10 24 10 11 29 22 15 23 15
25 22 8 26 2 4 3 16 12 13 16
3 7 19 24 1 28 13 24 12 1
11 3 24 4 15 2 8 11 27
12 22 19 4 9 18 5 5
23 25 27 21 29 18 14
8 1 14 14 8 25
1 3 2 9 12
3 7 29 23
16 10 27
14 24
2

18 2 25 9 16 25 7 13 9 17 26 20
26 10 2 29 19 17 2 18 21 24 12
5 5 6 30 25 20 3 30 3 0
13 12 23 12 11 12 6 29 7
17 1 15 23 1 11 1 24
27 4 22 2 3 7 4
29 2 7 24 14 1
23 2 15 10 6
3 4 1 21
14 15 6
17 20
4"""


def modinv(a, p):
    return pow(a % p, p - 2, p)


def eval_quadratic(P, x, n, q):
    """Evaluate x^T P x where P is upper triangular."""
    val = 0
    for i in range(n):
        for j in range(i, n):
            val += P[i][j] * x[i] * x[j]
    return val % q


def compute_hash(message, m, q):
    """Compute hash target H(message) in F_q^m using SHAKE256."""
    bits_per_element = math.ceil(math.log2(q))
    num_bytes = -(-bits_per_element * m // 8)
    shake = hashlib.shake_256(message.encode())
    hash_bytes = shake.digest(num_bytes)
    bits = int.from_bytes(hash_bytes, 'big')
    target = []
    for i in range(m):
        val = (bits >> (bits_per_element * (m - 1 - i))) & ((1 << bits_per_element) - 1)
        target.append(val % q)
    return target


def parse_public_key_text(text, n, m):
    """Parse public key from text content."""
    blocks = text.strip().split('\n\n')
    matrices = []
    for block in blocks:
        lines = block.strip().split('\n')
        P = [[0] * n for _ in range(n)]
        for i, line in enumerate(lines):
            vals = list(map(int, line.split()))
            for j, val in enumerate(vals):
                P[i][i + j] = val
        matrices.append(P)
    return matrices


@pytest.fixture
def params():
    return {'q': _Q, 'n': _N, 'm': _M, 'o': _O, 'k': _K}


@pytest.fixture
def public_keys():
    return parse_public_key_text(_PUBKEY_RAW, _N, _M)


@pytest.fixture
def message():
    return _MESSAGE


class TestKeyDecryption:
    """Verify the agent successfully decrypted the public key."""

    def test_public_key_file_exists(self):
        assert os.path.exists('/app/public_key.txt'), \
            "Public key not decrypted: /app/public_key.txt not found. " \
            "Use openssl with the TLS certificate to decrypt /app/pubkey.enc"

    def test_public_key_has_correct_structure(self):
        if not os.path.exists('/app/public_key.txt'):
            pytest.skip("Public key not decrypted yet")
        with open('/app/public_key.txt') as f:
            content = f.read().strip()
        blocks = content.split('\n\n')
        assert len(blocks) == _M, \
            f"Decrypted key has {len(blocks)} matrix blocks, expected {_M}"


class TestSignatureExists:
    def test_signature_file_exists(self):
        assert os.path.exists('/app/signature.txt'), \
            "Signature file /app/signature.txt does not exist"

    def test_signature_not_empty(self):
        with open('/app/signature.txt') as f:
            content = f.read().strip()
        assert len(content) > 0, "Signature file is empty"


class TestSignatureFormat:
    def test_correct_element_count(self, params):
        with open('/app/signature.txt') as f:
            vals = list(map(int, f.read().strip().split()))
        expected = params['k'] * params['n']
        assert len(vals) == expected, \
            f"Signature has {len(vals)} elements, expected {expected}"

    def test_elements_in_range(self, params):
        q = params['q']
        with open('/app/signature.txt') as f:
            vals = list(map(int, f.read().strip().split()))
        for i, v in enumerate(vals):
            assert 0 <= v < q, \
                f"Element {i} = {v} is out of range [0, {q})"


class TestSignatureValidity:
    def test_signature_verifies(self, params, public_keys, message):
        """Core test: the forged signature must be mathematically valid."""
        q = params['q']
        n = params['n']
        m = params['m']
        k = params['k']

        with open('/app/signature.txt') as f:
            vals = list(map(int, f.read().strip().split()))
        assert len(vals) == k * n

        signature = []
        for i in range(k):
            signature.append(vals[i * n: (i + 1) * n])

        target = compute_hash(message, m, q)

        # Verify: P*(s) = P(s_1) + ... + P(s_k) should equal target
        total = [0] * m
        for si in signature:
            for j in range(m):
                total[j] = (total[j] + eval_quadratic(public_keys[j], si, n, q)) % q

        assert total == target, \
            f"Signature verification failed:\n  P*(s) = {total}\n  H(m)  = {target}"

    def test_signature_not_trivial(self, params):
        """Ensure signature is not all zeros (trivial non-solution)."""
        with open('/app/signature.txt') as f:
            vals = list(map(int, f.read().strip().split()))
        assert any(v != 0 for v in vals), "Signature is all zeros"
