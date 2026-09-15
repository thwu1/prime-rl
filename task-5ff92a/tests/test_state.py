
import ctypes
import json
import os
import subprocess
import pytest

P256 = 2**256 - 2**224 + 2**192 + 2**96 - 1
R = 2**256
MASK64 = (1 << 64) - 1


# ========================================================================
# Toolchain Tests
# ========================================================================

class TestBuildToolchain:
    """Verify the build system and toolchain outputs."""

    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_shared_library_exists(self):
        assert os.path.exists("/app/libp256mont.so"), "Shared library libp256mont.so not found"

    def test_static_library_exists(self):
        assert os.path.exists("/app/libp256mont.a"), "Static library libp256mont.a not found"

    def test_static_library_is_archive(self):
        if not os.path.exists("/app/libp256mont.a"):
            pytest.skip("Static library not built")
        result = subprocess.run(["ar", "t", "/app/libp256mont.a"],
                                capture_output=True, text=True)
        assert result.returncode == 0, "libp256mont.a is not a valid ar archive"
        assert "p256_mont" in result.stdout, "Archive does not contain p256_mont object"

    def test_symbol_manifest_exists(self):
        assert os.path.exists("/app/symbol_manifest.txt"), "symbol_manifest.txt not found"

    def test_symbol_manifest_content(self):
        with open("/app/symbol_manifest.txt") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        expected = sorted([
            "p256_frommont", "p256_inv", "p256_montadd",
            "p256_montmul", "p256_montsqr", "p256_montsub",
            "p256_tomont"
        ])
        assert lines == expected, (
            f"Symbol manifest mismatch.\n"
            f"Expected: {expected}\n"
            f"Got:      {lines}"
        )

    def test_build_analysis_exists(self):
        assert os.path.exists("/app/build_analysis.json"), "build_analysis.json not found"

    def test_build_analysis_valid_json(self):
        with open("/app/build_analysis.json") as f:
            data = json.load(f)
        required_keys = [
            "montmul_instruction_count", "text_size", "data_size", "bss_size"
        ]
        for key in required_keys:
            assert key in data, f"Missing key '{key}' in build_analysis.json"
            assert isinstance(data[key], int), (
                f"Key '{key}' must be int, got {type(data[key]).__name__}"
            )
        assert data["montmul_instruction_count"] > 0, \
            "montmul_instruction_count must be positive"
        assert data["text_size"] > 0, "text_size must be positive"
        assert data["data_size"] >= 0, "data_size must be non-negative"
        assert data["bss_size"] >= 0, "bss_size must be non-negative"

    def test_prime_verification_exists(self):
        assert os.path.exists("/app/prime_verification.txt"), \
            "prime_verification.txt not found"

    def test_prime_verification_match(self):
        with open("/app/prime_verification.txt") as f:
            content = f.read().strip()
        assert content == "MATCH", f"Expected 'MATCH', got '{content}'"

    def test_nm_dynamic_symbols_independently(self):
        """Independently verify nm -D shows the expected p256_* symbols."""
        if not os.path.exists("/app/libp256mont.so"):
            pytest.skip("Shared library not built")
        result = subprocess.run(
            ["nm", "-D", "/app/libp256mont.so"],
            capture_output=True, text=True
        )
        output = result.stdout
        expected_symbols = [
            "p256_frommont", "p256_inv", "p256_montadd",
            "p256_montmul", "p256_montsqr", "p256_montsub",
            "p256_tomont"
        ]
        for sym in expected_symbols:
            assert f" T {sym}" in output, (
                f"Symbol '{sym}' not found as text symbol in nm -D output"
            )

    def test_objdump_has_montmul(self):
        """Verify objdump -d shows the p256_montmul function."""
        if not os.path.exists("/app/libp256mont.so"):
            pytest.skip("Shared library not built")
        result = subprocess.run(
            ["objdump", "-d", "/app/libp256mont.so"],
            capture_output=True, text=True
        )
        assert "<p256_montmul>" in result.stdout, \
            "p256_montmul not found in objdump disassembly"


# ========================================================================
# Helper Functions for Functional Tests
# ========================================================================

def limbs_to_int(arr):
    """Convert 4 x uint64 little-endian limbs to Python int."""
    val = 0
    for i in range(4):
        val |= arr[i] << (64 * i)
    return val


def int_to_limbs(val):
    """Convert Python int to 4 x uint64 ctypes array."""
    arr = (ctypes.c_uint64 * 4)()
    for i in range(4):
        arr[i] = (val >> (64 * i)) & MASK64
    return arr


@pytest.fixture(scope="module")
def lib():
    lib_path = "/app/libp256mont.so"
    assert os.path.exists(lib_path), f"Library not found at {lib_path}"
    lib = ctypes.CDLL(lib_path)

    u64_4 = ctypes.c_uint64 * 4

    for fname in ["p256_montmul", "p256_montadd", "p256_montsub"]:
        fn = getattr(lib, fname)
        fn.argtypes = [u64_4, u64_4, u64_4]
        fn.restype = None

    for fname in ["p256_montsqr", "p256_tomont", "p256_frommont", "p256_inv"]:
        fn = getattr(lib, fname)
        fn.argtypes = [u64_4, u64_4]
        fn.restype = None

    return lib


def call_binary(lib, fname, a_int, b_int):
    x = int_to_limbs(a_int)
    y = int_to_limbs(b_int)
    z = (ctypes.c_uint64 * 4)()
    getattr(lib, fname)(z, x, y)
    return limbs_to_int(z)


def call_unary(lib, fname, a_int):
    x = int_to_limbs(a_int)
    z = (ctypes.c_uint64 * 4)()
    getattr(lib, fname)(z, x)
    return limbs_to_int(z)


# ========================================================================
# Test Values
# ========================================================================

TEST_VALUES = [
    0,
    1,
    2,
    0xDEADBEEFCAFEBABE0123456789ABCDEF0FEDCBA9876543210011223344556677 % P256,
    0xAAAABBBBCCCCDDDD1111222233334444555566667777888899990000AAAA1111 % P256,
    P256 - 1,
    P256 - 2,
    (2**128 + 7) % P256,
    (2**192 - 3) % P256,
    0x1 << 96,
    42,
]


# ========================================================================
# Functional Tests: Montgomery Domain Conversions
# ========================================================================

class TestToFromMont:

    def test_tomont_zero(self, lib):
        result = call_unary(lib, "p256_tomont", 0)
        assert result == 0, f"tomont(0) should be 0, got {hex(result)}"

    def test_tomont_one(self, lib):
        result = call_unary(lib, "p256_tomont", 1)
        expected = R % P256
        assert result == expected, f"tomont(1) = {hex(result)}, expected {hex(expected)}"

    def test_frommont_of_tomont_one(self, lib):
        mont_one = call_unary(lib, "p256_tomont", 1)
        result = call_unary(lib, "p256_frommont", mont_one)
        assert result == 1, f"frommont(tomont(1)) = {result}, expected 1"

    @pytest.mark.parametrize("a", TEST_VALUES)
    def test_roundtrip(self, lib, a):
        mont_a = call_unary(lib, "p256_tomont", a)
        result = call_unary(lib, "p256_frommont", mont_a)
        assert result == a

    @pytest.mark.parametrize("a", TEST_VALUES)
    def test_tomont_value(self, lib, a):
        result = call_unary(lib, "p256_tomont", a)
        expected = (a * R) % P256
        assert result == expected

    @pytest.mark.parametrize("a", TEST_VALUES)
    def test_result_reduced(self, lib, a):
        result = call_unary(lib, "p256_tomont", a)
        assert result < P256


# ========================================================================
# Functional Tests: Montgomery Multiplication
# ========================================================================

class TestMontMul:

    def test_mul_identity(self, lib):
        a = 0xDEADBEEFCAFEBABE0123456789ABCDEF0FEDCBA9876543210011223344556677 % P256
        mont_a = call_unary(lib, "p256_tomont", a)
        mont_one = call_unary(lib, "p256_tomont", 1)
        result = call_binary(lib, "p256_montmul", mont_a, mont_one)
        assert result == mont_a

    def test_mul_zero(self, lib):
        a = 12345678 % P256
        mont_a = call_unary(lib, "p256_tomont", a)
        result = call_binary(lib, "p256_montmul", mont_a, 0)
        assert result == 0

    @pytest.mark.parametrize("a,b", [
        (3, 7),
        (TEST_VALUES[3], TEST_VALUES[4]),
        (P256 - 1, P256 - 1),
        (1, P256 - 1),
        (2**128 + 7, 2**192 - 3),
    ])
    def test_mul_correctness(self, lib, a, b):
        a, b = a % P256, b % P256
        mont_a = call_unary(lib, "p256_tomont", a)
        mont_b = call_unary(lib, "p256_tomont", b)
        mont_result = call_binary(lib, "p256_montmul", mont_a, mont_b)
        result = call_unary(lib, "p256_frommont", mont_result)
        expected = (a * b) % P256
        assert result == expected

    def test_mul_commutativity(self, lib):
        a, b = TEST_VALUES[3], TEST_VALUES[4]
        mont_a = call_unary(lib, "p256_tomont", a)
        mont_b = call_unary(lib, "p256_tomont", b)
        ab = call_binary(lib, "p256_montmul", mont_a, mont_b)
        ba = call_binary(lib, "p256_montmul", mont_b, mont_a)
        assert ab == ba

    def test_mul_associativity(self, lib):
        a, b, c = TEST_VALUES[3], TEST_VALUES[4], TEST_VALUES[6]
        ma = call_unary(lib, "p256_tomont", a)
        mb = call_unary(lib, "p256_tomont", b)
        mc = call_unary(lib, "p256_tomont", c)
        ab = call_binary(lib, "p256_montmul", ma, mb)
        ab_c = call_binary(lib, "p256_montmul", ab, mc)
        bc = call_binary(lib, "p256_montmul", mb, mc)
        a_bc = call_binary(lib, "p256_montmul", ma, bc)
        assert ab_c == a_bc

    @pytest.mark.parametrize("a,b", [
        (TEST_VALUES[3], TEST_VALUES[4]),
        (P256 - 1, 2),
    ])
    def test_mul_result_reduced(self, lib, a, b):
        a, b = a % P256, b % P256
        mont_a = call_unary(lib, "p256_tomont", a)
        mont_b = call_unary(lib, "p256_tomont", b)
        result = call_binary(lib, "p256_montmul", mont_a, mont_b)
        assert result < P256


# ========================================================================
# Functional Tests: Montgomery Squaring
# ========================================================================

class TestMontSqr:

    @pytest.mark.parametrize("a", TEST_VALUES)
    def test_sqr_equals_mul(self, lib, a):
        mont_a = call_unary(lib, "p256_tomont", a)
        sqr_result = call_unary(lib, "p256_montsqr", mont_a)
        mul_result = call_binary(lib, "p256_montmul", mont_a, mont_a)
        assert sqr_result == mul_result

    @pytest.mark.parametrize("a", [3, 7, TEST_VALUES[3], P256 - 1])
    def test_sqr_correctness(self, lib, a):
        a = a % P256
        mont_a = call_unary(lib, "p256_tomont", a)
        mont_sq = call_unary(lib, "p256_montsqr", mont_a)
        result = call_unary(lib, "p256_frommont", mont_sq)
        expected = (a * a) % P256
        assert result == expected


# ========================================================================
# Functional Tests: Modular Addition
# ========================================================================

class TestMontAdd:

    @pytest.mark.parametrize("a,b", [
        (0, 0),
        (0, 1),
        (1, 1),
        (P256 - 1, 1),
        (P256 - 1, P256 - 1),
        (TEST_VALUES[3], TEST_VALUES[4]),
        (2**128, 2**128),
    ])
    def test_add_correctness(self, lib, a, b):
        a, b = a % P256, b % P256
        result = call_binary(lib, "p256_montadd", a, b)
        expected = (a + b) % P256
        assert result == expected

    def test_add_identity(self, lib):
        a = TEST_VALUES[3]
        result = call_binary(lib, "p256_montadd", a, 0)
        assert result == a

    def test_add_commutativity(self, lib):
        a, b = TEST_VALUES[3], TEST_VALUES[4]
        ab = call_binary(lib, "p256_montadd", a, b)
        ba = call_binary(lib, "p256_montadd", b, a)
        assert ab == ba

    @pytest.mark.parametrize("a,b", [
        (P256 - 1, 1),
        (P256 - 1, P256 - 1),
        (TEST_VALUES[3], TEST_VALUES[4]),
    ])
    def test_add_result_reduced(self, lib, a, b):
        a, b = a % P256, b % P256
        result = call_binary(lib, "p256_montadd", a, b)
        assert result < P256


# ========================================================================
# Functional Tests: Modular Subtraction
# ========================================================================

class TestMontSub:

    @pytest.mark.parametrize("a,b", [
        (0, 0),
        (1, 0),
        (0, 1),
        (1, 1),
        (P256 - 1, P256 - 1),
        (TEST_VALUES[3], TEST_VALUES[4]),
        (TEST_VALUES[4], TEST_VALUES[3]),
    ])
    def test_sub_correctness(self, lib, a, b):
        a, b = a % P256, b % P256
        result = call_binary(lib, "p256_montsub", a, b)
        expected = (a - b) % P256
        assert result == expected

    def test_sub_self_is_zero(self, lib):
        a = TEST_VALUES[3]
        result = call_binary(lib, "p256_montsub", a, a)
        assert result == 0

    def test_add_sub_inverse(self, lib):
        a, b = TEST_VALUES[3], TEST_VALUES[4]
        s = call_binary(lib, "p256_montadd", a, b)
        result = call_binary(lib, "p256_montsub", s, b)
        assert result == a

    @pytest.mark.parametrize("a,b", [
        (0, 1),
        (0, P256 - 1),
    ])
    def test_sub_result_reduced(self, lib, a, b):
        a, b = a % P256, b % P256
        result = call_binary(lib, "p256_montsub", a, b)
        assert result < P256


# ========================================================================
# Functional Tests: Modular Inverse
# ========================================================================

class TestInverse:

    @pytest.mark.parametrize("a", [1, 2, 3, 7, 42, TEST_VALUES[3], TEST_VALUES[4], P256 - 1])
    def test_inv_correctness(self, lib, a):
        a = a % P256
        if a == 0:
            return
        mont_a = call_unary(lib, "p256_tomont", a)
        mont_inv = call_unary(lib, "p256_inv", mont_a)
        inv_val = call_unary(lib, "p256_frommont", mont_inv)
        expected = pow(a, P256 - 2, P256)
        assert inv_val == expected

    @pytest.mark.parametrize("a", [1, 2, 7, TEST_VALUES[3], P256 - 1])
    def test_inv_times_x_is_one(self, lib, a):
        a = a % P256
        if a == 0:
            return
        mont_a = call_unary(lib, "p256_tomont", a)
        mont_inv = call_unary(lib, "p256_inv", mont_a)
        mont_prod = call_binary(lib, "p256_montmul", mont_a, mont_inv)
        mont_one = call_unary(lib, "p256_tomont", 1)
        assert mont_prod == mont_one

    def test_inv_result_reduced(self, lib):
        a = TEST_VALUES[3]
        mont_a = call_unary(lib, "p256_tomont", a)
        result = call_unary(lib, "p256_inv", mont_a)
        assert result < P256


# ========================================================================
# Functional Tests: Aliasing
# ========================================================================

class TestAliasing:

    def test_montmul_alias_z_x(self, lib):
        a, b = TEST_VALUES[3], TEST_VALUES[4]
        mont_a = call_unary(lib, "p256_tomont", a)
        mont_b = call_unary(lib, "p256_tomont", b)
        expected = call_binary(lib, "p256_montmul", mont_a, mont_b)
        buf = int_to_limbs(mont_a)
        y = int_to_limbs(mont_b)
        lib.p256_montmul(buf, buf, y)
        result = limbs_to_int(buf)
        assert result == expected

    def test_montmul_alias_z_y(self, lib):
        a, b = TEST_VALUES[3], TEST_VALUES[4]
        mont_a = call_unary(lib, "p256_tomont", a)
        mont_b = call_unary(lib, "p256_tomont", b)
        expected = call_binary(lib, "p256_montmul", mont_a, mont_b)
        x = int_to_limbs(mont_a)
        buf = int_to_limbs(mont_b)
        lib.p256_montmul(buf, x, buf)
        result = limbs_to_int(buf)
        assert result == expected

    def test_montsqr_alias(self, lib):
        a = TEST_VALUES[3]
        mont_a = call_unary(lib, "p256_tomont", a)
        expected = call_unary(lib, "p256_montsqr", mont_a)
        buf = int_to_limbs(mont_a)
        lib.p256_montsqr(buf, buf)
        result = limbs_to_int(buf)
        assert result == expected

    def test_tomont_alias(self, lib):
        a = TEST_VALUES[3]
        expected = call_unary(lib, "p256_tomont", a)
        buf = int_to_limbs(a)
        lib.p256_tomont(buf, buf)
        result = limbs_to_int(buf)
        assert result == expected

    def test_frommont_alias(self, lib):
        a = TEST_VALUES[3]
        mont_a = call_unary(lib, "p256_tomont", a)
        expected = call_unary(lib, "p256_frommont", mont_a)
        buf = int_to_limbs(mont_a)
        lib.p256_frommont(buf, buf)
        result = limbs_to_int(buf)
        assert result == expected

    def test_montadd_alias(self, lib):
        a, b = TEST_VALUES[3], TEST_VALUES[4]
        expected = call_binary(lib, "p256_montadd", a, b)
        buf = int_to_limbs(a)
        y = int_to_limbs(b)
        lib.p256_montadd(buf, buf, y)
        result = limbs_to_int(buf)
        assert result == expected

    def test_montsub_alias(self, lib):
        a, b = TEST_VALUES[3], TEST_VALUES[4]
        expected = call_binary(lib, "p256_montsub", a, b)
        buf = int_to_limbs(a)
        y = int_to_limbs(b)
        lib.p256_montsub(buf, buf, y)
        result = limbs_to_int(buf)
        assert result == expected


# ========================================================================
# Functional Tests: Algebraic Properties
# ========================================================================

class TestDistributivity:

    def test_mul_distributes_over_add(self, lib):
        a, b, c = TEST_VALUES[3], TEST_VALUES[4], TEST_VALUES[6]
        ma = call_unary(lib, "p256_tomont", a)
        mb = call_unary(lib, "p256_tomont", b)
        mc = call_unary(lib, "p256_tomont", c)

        bc_sum = call_binary(lib, "p256_montadd", mb, mc)
        lhs = call_binary(lib, "p256_montmul", ma, bc_sum)

        ab = call_binary(lib, "p256_montmul", ma, mb)
        ac = call_binary(lib, "p256_montmul", ma, mc)
        rhs = call_binary(lib, "p256_montadd", ab, ac)

        assert lhs == rhs

    def test_sub_then_add_roundtrip(self, lib):
        a, b = TEST_VALUES[3], TEST_VALUES[4]
        diff = call_binary(lib, "p256_montsub", a, b)
        result = call_binary(lib, "p256_montadd", diff, b)
        assert result == a

    def test_double_via_add_vs_mul(self, lib):
        a = TEST_VALUES[3]
        ma = call_unary(lib, "p256_tomont", a)
        m2 = call_unary(lib, "p256_tomont", 2)
        via_add = call_binary(lib, "p256_montadd", ma, ma)
        via_mul = call_binary(lib, "p256_montmul", ma, m2)
        assert via_add == via_mul
