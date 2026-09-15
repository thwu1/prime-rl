
"""
Tests for optimized secp256k1 scalar multiplication.
Validates correctness of the endomorphism, scalar decomposition, and fast
multiplication against naive point_mul and BIP340 test vectors.
"""

import json
import sys
import os

sys.path.insert(0, '/app')


# ============================================================================
# Module structure tests
# ============================================================================

class TestModuleStructure:
    """Verify the fast_mul module exists with required exports."""

    def test_module_importable(self):
        """fast_mul module must be importable from /app."""
        import fast_mul

    def test_exports_beta(self):
        import fast_mul
        assert hasattr(fast_mul, 'BETA'), "fast_mul.BETA not found"
        assert isinstance(fast_mul.BETA, int), "fast_mul.BETA must be an integer"

    def test_exports_lambda(self):
        import fast_mul
        assert hasattr(fast_mul, 'LAMBDA'), "fast_mul.LAMBDA not found"
        assert isinstance(fast_mul.LAMBDA, int), "fast_mul.LAMBDA must be an integer"

    def test_exports_endomorphism(self):
        import fast_mul
        assert callable(getattr(fast_mul, 'endomorphism', None)), \
            "fast_mul.endomorphism must be a callable"

    def test_exports_decompose_scalar(self):
        import fast_mul
        assert callable(getattr(fast_mul, 'decompose_scalar', None)), \
            "fast_mul.decompose_scalar must be a callable"

    def test_exports_fast_mul(self):
        import fast_mul
        assert callable(getattr(fast_mul, 'fast_mul', None)), \
            "fast_mul.fast_mul must be a callable"


# ============================================================================
# Constants validation
# ============================================================================

class TestConstants:
    """Verify BETA and LAMBDA are mathematically correct."""

    def test_beta_matches_rust_source(self):
        """BETA must match ENDOMORPHISM_BETA from k256_projective.rs."""
        import fast_mul
        # Reconstructed from the byte array in k256_projective.rs:
        # [0x7a, 0xe9, 0x6a, 0x2b, 0x65, 0x7c, 0x07, 0x10,
        #  0x6e, 0x64, 0x47, 0x9e, 0xac, 0x34, 0x34, 0xe9,
        #  0x9c, 0xf0, 0x49, 0x75, 0x12, 0xf5, 0x89, 0x95,
        #  0xc1, 0x39, 0x6c, 0x28, 0x71, 0x95, 0x01, 0xee]
        expected = 0x7ae96a2b657c07106e64479eac3434e99cf0497512f58995c1396c28719501ee
        assert fast_mul.BETA == expected, (
            f"BETA mismatch\n  expected: {hex(expected)}\n  got:      {hex(fast_mul.BETA)}"
        )

    def test_beta_is_cube_root_in_field(self):
        import fast_mul
        from secp256k1 import P
        assert fast_mul.BETA != 1, "BETA must be a non-trivial cube root"
        assert pow(fast_mul.BETA, 3, P) == 1, "BETA^3 must equal 1 mod p"

    def test_lambda_is_cube_root_in_scalar_field(self):
        import fast_mul
        from secp256k1 import N
        assert fast_mul.LAMBDA != 1, "LAMBDA must be a non-trivial cube root"
        assert pow(fast_mul.LAMBDA, 3, N) == 1, "LAMBDA^3 must equal 1 mod n"

    def test_lambda_is_eigenvalue(self):
        """endomorphism(G) must equal point_mul(LAMBDA, G)."""
        import fast_mul
        from secp256k1 import G, point_mul
        endo_G = fast_mul.endomorphism(G)
        lambda_G = point_mul(fast_mul.LAMBDA, G)
        assert endo_G is not None, "endomorphism(G) must not be None"
        assert lambda_G is not None, "point_mul(LAMBDA, G) must not be None"
        assert endo_G[0] == lambda_G[0] and endo_G[1] == lambda_G[1], (
            f"Eigenvalue mismatch: endomorphism(G) != LAMBDA*G\n"
            f"  endomorphism(G) = ({hex(endo_G[0])}, {hex(endo_G[1])})\n"
            f"  LAMBDA*G        = ({hex(lambda_G[0])}, {hex(lambda_G[1])})"
        )


# ============================================================================
# Endomorphism function tests
# ============================================================================

class TestEndomorphism:
    """Verify the endomorphism function."""

    def test_generator_x_coordinate(self):
        import fast_mul
        from secp256k1 import G, P
        result = fast_mul.endomorphism(G)
        assert result is not None
        assert result[0] == (fast_mul.BETA * G[0]) % P
        assert result[1] == G[1]

    def test_identity_handling(self):
        import fast_mul
        assert fast_mul.endomorphism(None) is None

    def test_preserves_y_coordinate(self):
        import fast_mul
        from secp256k1 import G, point_mul
        for k in [2, 5, 17, 0xdeadbeef]:
            pt = point_mul(k, G)
            endo = fast_mul.endomorphism(pt)
            assert endo[1] == pt[1], f"y-coordinate changed for k={k}"

    def test_eigenvalue_on_arbitrary_points(self):
        import fast_mul
        from secp256k1 import G, point_mul
        for k in [2, 7, 42, 0xcafebabe]:
            pt = point_mul(k, G)
            endo_pt = fast_mul.endomorphism(pt)
            lambda_pt = point_mul(fast_mul.LAMBDA, pt)
            assert endo_pt[0] == lambda_pt[0] and endo_pt[1] == lambda_pt[1], (
                f"Eigenvalue property failed for k={hex(k)}: "
                f"endomorphism(k*G) != LAMBDA*(k*G)"
            )

    def test_endomorphism_order_3(self):
        import fast_mul
        from secp256k1 import G, point_mul
        pt = point_mul(13, G)
        pt1 = fast_mul.endomorphism(pt)
        pt2 = fast_mul.endomorphism(pt1)
        pt3 = fast_mul.endomorphism(pt2)
        assert pt3[0] == pt[0] and pt3[1] == pt[1], \
            "endo^3(P) must equal P (endomorphism has order 3)"


# ============================================================================
# Scalar decomposition tests
# ============================================================================

class TestDecomposeScalar:
    """Verify decompose_scalar produces valid, bounded decompositions."""

    def _check_decomposition(self, k):
        import fast_mul
        from secp256k1 import N
        k1, k2 = fast_mul.decompose_scalar(k)
        # Verify reconstruction
        reconstructed = (k1 + k2 * fast_mul.LAMBDA) % N
        assert reconstructed == k % N, (
            f"Decomposition invalid for k={hex(k)}: "
            f"k1 + k2*LAMBDA mod n = {hex(reconstructed)}, expected {hex(k % N)}"
        )
        # Verify sub-scalars are bounded
        assert abs(k1) < (1 << 129), (
            f"|k1| too large for k={hex(k)}: |k1|={abs(k1).bit_length()} bits"
        )
        assert abs(k2) < (1 << 129), (
            f"|k2| too large for k={hex(k)}: |k2|={abs(k2).bit_length()} bits"
        )
        return k1, k2

    def test_small_scalars(self):
        for k in [1, 2, 3, 7, 255]:
            self._check_decomposition(k)

    def test_bip340_private_keys(self):
        bip340_keys = [
            0x03,
            0xB7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF,
            0xC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B14E5C9,
            0x0B432B2677937381AEF05BB02A66ECD012773062CF3FA2549E44F58ED2401710,
        ]
        for k in bip340_keys:
            self._check_decomposition(k)

    def test_edge_scalars(self):
        import fast_mul
        from secp256k1 import N
        edge_cases = [
            N - 1,
            N - 2,
            fast_mul.LAMBDA,
            fast_mul.LAMBDA + 1,
            fast_mul.LAMBDA - 1,
            (1 << 128),
            (1 << 255),
        ]
        for k in edge_cases:
            self._check_decomposition(k)

    def test_lambda_decomposition_is_efficient(self):
        import fast_mul
        k1, k2 = fast_mul.decompose_scalar(fast_mul.LAMBDA)
        assert abs(k1) < (1 << 129) and abs(k2) < (1 << 129)
        total_bits = max(abs(k1).bit_length(), abs(k2).bit_length())
        assert total_bits < 130, (
            f"Decomposition of LAMBDA is not efficient: max sub-scalar is {total_bits} bits"
        )


# ============================================================================
# Fast scalar multiplication correctness tests
# ============================================================================

class TestFastMul:
    """Verify fast_mul matches naive point_mul for all cases."""

    def test_generator_small_scalars(self):
        import fast_mul
        from secp256k1 import G, point_mul
        for k in [1, 2, 3, 5, 7, 15, 100, 255, 1024]:
            expected = point_mul(k, G)
            actual = fast_mul.fast_mul(k, G)
            assert actual == expected, f"Mismatch for k={k}"

    def test_generator_large_scalars(self):
        import fast_mul
        from secp256k1 import G, point_mul
        large_scalars = [
            0xB7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF,
            0xC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B14E5C9,
            0x0B432B2677937381AEF05BB02A66ECD012773062CF3FA2549E44F58ED2401710,
            0xdeadbeefcafebabe1234567890abcdef0fedcba0987654321ebadcafedeadbeef,
        ]
        for k in large_scalars:
            expected = point_mul(k, G)
            actual = fast_mul.fast_mul(k, G)
            assert actual == expected, f"Mismatch for k=0x{k:064x}"

    def test_non_generator_points(self):
        import fast_mul
        from secp256k1 import G, point_mul
        base_points = [point_mul(7, G), point_mul(13, G), point_mul(9999, G)]
        for base in base_points:
            for k in [1, 2, 42, 0xdeadbeef, 0xa5a5a5a5b6b6b6b6c7c7c7c7d8d8d8d8]:
                expected = point_mul(k, base)
                actual = fast_mul.fast_mul(k, base)
                assert actual == expected, (
                    f"Mismatch for k={hex(k)} on non-generator point"
                )

    def test_zero_scalar(self):
        import fast_mul
        from secp256k1 import G
        assert fast_mul.fast_mul(0, G) is None

    def test_order_scalar(self):
        import fast_mul
        from secp256k1 import G, N
        assert fast_mul.fast_mul(N, G) is None

    def test_order_minus_one(self):
        import fast_mul
        from secp256k1 import G, N, point_mul
        expected = point_mul(N - 1, G)
        actual = fast_mul.fast_mul(N - 1, G)
        assert actual == expected, "Mismatch for k = n-1"

    def test_identity_point(self):
        import fast_mul
        assert fast_mul.fast_mul(42, None) is None


# ============================================================================
# BIP340 integration tests
# ============================================================================

class TestBIP340Integration:
    """Verify optimized mul produces correct BIP340 public keys and signatures."""

    def setup_method(self):
        with open('/app/test_vectors.json', 'r') as f:
            self.vectors = json.load(f)

    def test_public_key_derivation(self):
        import fast_mul
        from secp256k1 import G, point_mul
        for v in self.vectors['signing_vectors']:
            sk = int(v['secret_key'], 16)
            expected_pk = point_mul(sk, G)
            fast_pk = fast_mul.fast_mul(sk, G)
            assert fast_pk == expected_pk, (
                f"Public key mismatch for vector {v['index']}: "
                f"fast_mul gives different result than point_mul"
            )

    def test_public_key_x_matches_vector(self):
        import fast_mul
        from secp256k1 import G
        for v in self.vectors['signing_vectors']:
            sk = int(v['secret_key'], 16)
            pk = fast_mul.fast_mul(sk, G)
            expected_x = int(v['public_key'], 16)
            assert pk[0] == expected_x, (
                f"Vector {v['index']}: x-coordinate mismatch\n"
                f"  expected: {v['public_key']}\n"
                f"  got:      {hex(pk[0])[2:].upper()}"
            )


# ============================================================================
# Results file validation
# ============================================================================

class TestResultsFile:
    """Verify results.json exists and contains valid data."""

    def test_file_exists(self):
        assert os.path.isfile('/app/results.json'), \
            "results.json not found at /app/results.json"

    def test_valid_json(self):
        with open('/app/results.json', 'r') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_contains_required_fields(self):
        with open('/app/results.json', 'r') as f:
            data = json.load(f)
        required = ['lambda_hex', 'beta_hex', 'bip340_vectors_pass', 'benchmark']
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_constants_match(self):
        import fast_mul
        with open('/app/results.json', 'r') as f:
            data = json.load(f)
        assert int(data['lambda_hex'], 16) == fast_mul.LAMBDA, \
            "lambda_hex in results.json doesn't match fast_mul.LAMBDA"
        assert int(data['beta_hex'], 16) == fast_mul.BETA, \
            "beta_hex in results.json doesn't match fast_mul.BETA"

    def test_bip340_pass(self):
        with open('/app/results.json', 'r') as f:
            data = json.load(f)
        assert data['bip340_vectors_pass'] is True, \
            "bip340_vectors_pass must be true"

    def test_benchmark_data(self):
        with open('/app/results.json', 'r') as f:
            data = json.load(f)
        bench = data['benchmark']
        assert 'naive_mul_avg_ms' in bench
        assert 'fast_mul_avg_ms' in bench
        assert 'speedup_ratio' in bench
        assert isinstance(bench['naive_mul_avg_ms'], (int, float))
        assert isinstance(bench['fast_mul_avg_ms'], (int, float))
        assert isinstance(bench['speedup_ratio'], (int, float))
        assert bench['naive_mul_avg_ms'] > 0
        assert bench['fast_mul_avg_ms'] > 0
        assert bench['speedup_ratio'] > 0.8, \
            f"Optimization should not be drastically slower: speedup={bench['speedup_ratio']}"

    def test_decomposition_examples(self):
        import fast_mul
        from secp256k1 import N
        with open('/app/results.json', 'r') as f:
            data = json.load(f)
        assert 'decomposition_examples' in data
        examples = data['decomposition_examples']
        assert len(examples) >= 1, "Need at least one decomposition example"
        for ex in examples:
            k = int(ex['k'], 16)
            k1 = ex['k1']
            k2 = ex['k2']
            assert (k1 + k2 * fast_mul.LAMBDA) % N == k % N, (
                f"Invalid decomposition example for k={ex['k']}"
            )
