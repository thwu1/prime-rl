
import subprocess
import tempfile
import os
import pytest

BINARY = "/app/target/release/fst-tool"


def run(*args):
    result = subprocess.run(
        [BINARY] + list(args),
        capture_output=True, text=True, timeout=30
    )
    return result


def write_input(entries):
    """entries: list of (key, value) tuples, must already be sorted by key."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False)
    for key, value in entries:
        f.write(f"{key}\t{value}\n")
    f.close()
    return f.name


def build_fst(entries):
    inp = write_input(entries)
    out = tempfile.NamedTemporaryFile(suffix=".fst", delete=False).name
    r = run("build", inp, out)
    assert r.returncode == 0, f"build failed: {r.stderr}"
    os.unlink(inp)
    return out


# ----- small reference dataset -----
SMALL_DATA = [
    ("a", 1),
    ("ab", 5),
    ("abc", 13),
    ("abd", 21),
    ("b", 34),
    ("bcd", 55),
]


@pytest.fixture(scope="module")
def small_fst():
    path = build_fst(SMALL_DATA)
    yield path
    os.unlink(path)


# ----- state sharing dataset (all end in "x") -----
SHARED_SUFFIX_DATA = [
    ("ax", 10),
    ("bx", 20),
    ("cx", 30),
    ("dx", 40),
    ("ex", 50),
    ("fx", 60),
    ("gx", 70),
]


@pytest.fixture(scope="module")
def shared_fst():
    path = build_fst(SHARED_SUFFIX_DATA)
    yield path
    os.unlink(path)


# ==================== Basic operations ====================


class TestContains:
    def test_existing_keys(self, small_fst):
        for key, _ in SMALL_DATA:
            r = run("contains", small_fst, key)
            assert r.returncode == 0
            assert r.stdout.strip() == "true", f"contains({key!r}) should be true"

    def test_missing_keys(self, small_fst):
        for key in ["c", "ac", "abcd", "z", "ba", "abx"]:
            r = run("contains", small_fst, key)
            assert r.returncode == 0
            assert r.stdout.strip() == "false", f"contains({key!r}) should be false"


class TestGet:
    def test_existing_keys(self, small_fst):
        for key, val in SMALL_DATA:
            r = run("get", small_fst, key)
            assert r.returncode == 0
            assert r.stdout.strip() == str(val), \
                f"get({key!r}) expected {val}, got {r.stdout.strip()!r}"

    def test_not_found(self, small_fst):
        r = run("get", small_fst, "missing")
        assert r.returncode == 0
        assert r.stdout.strip() == "NOT_FOUND"


# ==================== Key enumeration ====================


class TestKeys:
    def test_all_keys(self, small_fst):
        r = run("keys", small_fst)
        assert r.returncode == 0
        lines = [l for l in r.stdout.strip().split("\n") if l]
        expected = [f"{k}\t{v}" for k, v in SMALL_DATA]
        assert lines == expected

    def test_prefix(self, small_fst):
        r = run("keys", small_fst, "--prefix", "ab")
        lines = [l for l in r.stdout.strip().split("\n") if l]
        expected = [f"{k}\t{v}" for k, v in SMALL_DATA if k.startswith("ab")]
        assert lines == expected

    def test_range_ge_le(self, small_fst):
        r = run("keys", small_fst, "--ge", "ab", "--le", "b")
        lines = [l for l in r.stdout.strip().split("\n") if l]
        expected = [f"{k}\t{v}" for k, v in SMALL_DATA if "ab" <= k <= "b"]
        assert lines == expected

    def test_combined_prefix_ge(self, small_fst):
        r = run("keys", small_fst, "--prefix", "a", "--ge", "ab")
        lines = [l for l in r.stdout.strip().split("\n") if l]
        expected = [f"{k}\t{v}" for k, v in SMALL_DATA
                    if k.startswith("a") and k >= "ab"]
        assert lines == expected


# ==================== Info & state sharing ====================


class TestInfo:
    def test_small_info(self, small_fst):
        r = run("info", small_fst)
        assert r.returncode == 0
        lines = r.stdout.strip().split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("keys:")
        assert lines[1].startswith("nodes:")
        assert int(lines[0].split(":")[1].strip()) == len(SMALL_DATA)

    def test_state_sharing_small(self, small_fst):
        """Node count must be below trie-equivalent for this dataset."""
        r = run("info", small_fst)
        node_count = int(r.stdout.strip().split("\n")[1].split(":")[1].strip())
        assert node_count < 8, \
            f"Expected fewer than 8 nodes, got {node_count}"

    def test_state_sharing_dramatic(self, shared_fst):
        """Keys ax..gx must share structure aggressively."""
        r = run("info", shared_fst)
        lines = r.stdout.strip().split("\n")
        keys_n = int(lines[0].split(":")[1].strip())
        nodes_n = int(lines[1].split(":")[1].strip())
        assert keys_n == len(SHARED_SUFFIX_DATA)
        assert nodes_n <= 3, \
            f"Expected at most 3 nodes for shared suffix data, got {nodes_n}"

    def test_shared_suffix_values(self, shared_fst):
        """Verify values are still correct despite aggressive sharing."""
        for key, val in SHARED_SUFFIX_DATA:
            r = run("get", shared_fst, key)
            assert r.stdout.strip() == str(val), \
                f"get({key!r}) expected {val}, got {r.stdout.strip()!r}"


# ==================== Fuzzy search ====================


def parse_fuzzy(stdout):
    """Parse fuzzy output into list of (key, value, distance) tuples."""
    results = []
    for line in stdout.split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            results.append((parts[0], int(parts[1]), int(parts[2])))
    return results


class TestFuzzy:
    def test_distance_0(self, small_fst):
        r = run("fuzzy", small_fst, "abc", "0")
        assert r.returncode == 0
        results = parse_fuzzy(r.stdout)
        assert len(results) == 1
        assert results[0] == ("abc", 13, 0)

    def test_distance_1(self, small_fst):
        r = run("fuzzy", small_fst, "ab", "1")
        assert r.returncode == 0
        results = parse_fuzzy(r.stdout)
        keys = {k for k, _, _ in results}
        expected_keys = {"a", "ab", "abc", "abd", "b"}
        assert keys == expected_keys, f"Expected {expected_keys}, got {keys}"
        for k, v, d in results:
            if k == "ab":
                assert d == 0
            else:
                assert d == 1

    def test_distance_2(self, small_fst):
        r = run("fuzzy", small_fst, "bce", "2")
        assert r.returncode == 0
        results = parse_fuzzy(r.stdout)
        keys = {k for k, _, _ in results}
        assert "bcd" in keys
        bcd_entry = [x for x in results if x[0] == "bcd"][0]
        assert bcd_entry[2] == 1

    def test_no_match(self, small_fst):
        r = run("fuzzy", small_fst, "zzzzz", "1")
        assert r.returncode == 0
        assert r.stdout.strip() == ""

    def test_fuzzy_sorted_output(self, small_fst):
        r = run("fuzzy", small_fst, "ab", "2")
        assert r.returncode == 0
        results = parse_fuzzy(r.stdout)
        keys = [k for k, _, _ in results]
        assert keys == sorted(keys), "Fuzzy results must be sorted by key"

    def test_fuzzy_values_correct(self, small_fst):
        """Fuzzy results must carry correct stored values."""
        r = run("fuzzy", small_fst, "ab", "1")
        results = parse_fuzzy(r.stdout)
        value_map = {k: v for k, v, _ in results}
        for key, val in SMALL_DATA:
            if key in value_map:
                assert value_map[key] == val, \
                    f"fuzzy value for {key!r} should be {val}, got {value_map[key]}"


# ==================== Edge cases ====================


class TestEdgeCases:
    def test_empty_key(self):
        data = [("", 42), ("a", 10), ("ab", 20)]
        fst_path = build_fst(data)
        try:
            assert run("contains", fst_path, "").stdout.strip() == "true"
            assert run("contains", fst_path, "a").stdout.strip() == "true"
            assert run("get", fst_path, "").stdout.strip() == "42"
            assert run("get", fst_path, "a").stdout.strip() == "10"
            assert run("get", fst_path, "ab").stdout.strip() == "20"
            r = run("keys", fst_path)
            lines = [l for l in r.stdout.split("\n") if l]
            assert lines[0] == "\t42"
            r = run("fuzzy", fst_path, "", "1")
            results = parse_fuzzy(r.stdout)
            keys = {k for k, _, _ in results}
            assert "" in keys
            assert "a" in keys
        finally:
            os.unlink(fst_path)

    def test_prefix_keys(self):
        """Keys that are prefixes of each other: a, ab, abc, abcd."""
        data = [("a", 100), ("ab", 200), ("abc", 300), ("abcd", 400)]
        fst_path = build_fst(data)
        try:
            for key, val in data:
                assert run("get", fst_path, key).stdout.strip() == str(val), \
                    f"get({key!r}) should be {val}"
            r = run("keys", fst_path)
            lines = [l for l in r.stdout.strip().split("\n") if l]
            assert len(lines) == 4
        finally:
            os.unlink(fst_path)

    def test_zero_values(self):
        data = [("alpha", 0), ("beta", 0), ("gamma", 0)]
        fst_path = build_fst(data)
        try:
            for key, val in data:
                assert run("get", fst_path, key).stdout.strip() == "0"
        finally:
            os.unlink(fst_path)

    def test_large_values(self):
        big = 2**63 - 1
        data = [("x", big), ("y", big - 1), ("z", 0)]
        fst_path = build_fst(data)
        try:
            assert run("get", fst_path, "x").stdout.strip() == str(big)
            assert run("get", fst_path, "y").stdout.strip() == str(big - 1)
            assert run("get", fst_path, "z").stdout.strip() == "0"
        finally:
            os.unlink(fst_path)

    def test_single_key(self):
        data = [("hello", 99)]
        fst_path = build_fst(data)
        try:
            assert run("get", fst_path, "hello").stdout.strip() == "99"
            assert run("contains", fst_path, "hello").stdout.strip() == "true"
            assert run("contains", fst_path, "hell").stdout.strip() == "false"
            r = run("info", fst_path)
            keys_n = int(r.stdout.strip().split("\n")[0].split(":")[1].strip())
            assert keys_n == 1
        finally:
            os.unlink(fst_path)


# ==================== Stress test ====================


class TestStress:
    def test_large_dataset(self):
        """Build from 1000+ generated keys and spot-check."""
        import random
        random.seed(42)
        keys = sorted(set(
            "".join(random.choices("abcdefghij", k=random.randint(1, 8)))
            for _ in range(2000)
        ))
        data = [(k, i * 7 + 3) for i, k in enumerate(keys)]
        fst_path = build_fst(data)
        try:
            for i in range(0, len(data), max(1, len(data) // 50)):
                key, val = data[i]
                assert run("get", fst_path, key).stdout.strip() == str(val), \
                    f"get({key!r}) should be {val}"
            r = run("info", fst_path)
            keys_n = int(r.stdout.strip().split("\n")[0].split(":")[1].strip())
            assert keys_n == len(data)
            nodes_n = int(r.stdout.strip().split("\n")[1].split(":")[1].strip())
            assert nodes_n < len(data) * 3, \
                f"Node count {nodes_n} seems too high for {len(data)} keys"
            test_key = data[len(data) // 2][0]
            r = run("fuzzy", fst_path, test_key, "1")
            assert r.returncode == 0
            results = parse_fuzzy(r.stdout)
            exact = [x for x in results if x[0] == test_key]
            assert len(exact) == 1 and exact[0][2] == 0
        finally:
            os.unlink(fst_path)


# ==================== Output-pushing algebra ====================


class TestOutputAlgebra:
    def test_output_pushing_shared_prefix(self):
        """Values must remain correct when keys share prefixes
        with different values."""
        data = [
            ("mon", 2),
            ("thurs", 4),
            ("tues", 5),
        ]
        fst_path = build_fst(data)
        try:
            for key, val in data:
                got = run("get", fst_path, key).stdout.strip()
                assert got == str(val), \
                    f"get({key!r}): expected {val}, got {got}"
        finally:
            os.unlink(fst_path)

    def test_decreasing_values_shared_prefix(self):
        """Values decrease along shared prefix."""
        data = [
            ("ab", 10),
            ("ac", 3),
            ("ad", 7),
            ("ae", 1),
        ]
        fst_path = build_fst(data)
        try:
            for key, val in data:
                got = run("get", fst_path, key).stdout.strip()
                assert got == str(val), \
                    f"get({key!r}): expected {val}, got {got}"
        finally:
            os.unlink(fst_path)

    def test_prefix_key_with_extensions(self):
        """Key 'a' is a prefix of 'ab' — tests intermediate accepting states."""
        data = [("a", 5), ("ab", 3)]
        fst_path = build_fst(data)
        try:
            assert run("get", fst_path, "a").stdout.strip() == "5"
            assert run("get", fst_path, "ab").stdout.strip() == "3"
        finally:
            os.unlink(fst_path)


# ==================== Deeper compression verification ====================


class TestCompressionDiscovery:
    """Verify structural compression meets tight bounds."""

    def test_many_shared_suffix(self):
        """20 three-character keys with shared two-byte suffix."""
        import string
        keys = [(f"{c}yz", i * 10)
                for i, c in enumerate(string.ascii_lowercase[:20])]
        fst_path = build_fst(keys)
        try:
            r = run("info", fst_path)
            nodes = int(r.stdout.strip().split("\n")[1].split(":")[1].strip())
            assert nodes <= 4, \
                f"20 keys sharing suffix 'yz' should compress to <=4 nodes, got {nodes}"
            for key, val in keys:
                got = run("get", fst_path, key).stdout.strip()
                assert got == str(val), f"get({key!r}): expected {val}, got {got}"
        finally:
            os.unlink(fst_path)

    def test_identical_suffix_chains(self):
        """Keys with identical multi-byte suffixes must share those nodes."""
        data = [
            ("aXYZ", 100),
            ("bXYZ", 200),
            ("cXYZ", 300),
        ]
        fst_path = build_fst(data)
        try:
            r = run("info", fst_path)
            nodes = int(r.stdout.strip().split("\n")[1].split(":")[1].strip())
            assert nodes <= 5, \
                f"3 keys sharing 3-byte suffix should compress to <=5 nodes, got {nodes}"
            for key, val in data:
                got = run("get", fst_path, key).stdout.strip()
                assert got == str(val), f"get({key!r}): expected {val}, got {got}"
        finally:
            os.unlink(fst_path)

    def test_mixed_sharing_patterns(self):
        """Dataset with both prefix and suffix sharing opportunities."""
        data = [
            ("cat", 1),
            ("cut", 2),
            ("mat", 3),
            ("mut", 4),
        ]
        fst_path = build_fst(data)
        try:
            r = run("info", fst_path)
            nodes = int(r.stdout.strip().split("\n")[1].split(":")[1].strip())
            # These keys share suffix 'at' (cat/mat) and 'ut' (cut/mut),
            # and 't' across all four. A trie would need 9 nodes.
            assert nodes < 9, \
                f"Expected compression below trie-equivalent 9 nodes, got {nodes}"
            for key, val in data:
                got = run("get", fst_path, key).stdout.strip()
                assert got == str(val), f"get({key!r}): expected {val}, got {got}"
        finally:
            os.unlink(fst_path)


# ==================== Deep value recovery ====================


class TestValueRecoveryDiscovery:
    """Test value recovery with challenging compression patterns."""

    def test_deep_shared_prefix_large_values(self):
        """Long shared prefix with wildly different large u64 values."""
        data = [
            ("abcdefg", 1000000),
            ("abcdefh", 1),
            ("abcdefi", 500000),
        ]
        fst_path = build_fst(data)
        try:
            for key, val in data:
                got = run("get", fst_path, key).stdout.strip()
                assert got == str(val), f"get({key!r}): expected {val}, got {got}"
        finally:
            os.unlink(fst_path)

    def test_many_shared_prefix_varying_values(self):
        """Many keys sharing a long prefix with diverse values."""
        data = [
            ("prefix_a", 7),
            ("prefix_b", 9999999),
            ("prefix_c", 0),
            ("prefix_d", 42),
            ("prefix_e", 1),
            ("prefix_f", 8888888),
        ]
        fst_path = build_fst(data)
        try:
            for key, val in data:
                got = run("get", fst_path, key).stdout.strip()
                assert got == str(val), f"get({key!r}): expected {val}, got {got}"
        finally:
            os.unlink(fst_path)

    def test_nested_prefix_keys_with_values(self):
        """Chain of prefix keys: each is a prefix of the next."""
        data = [
            ("x", 10),
            ("xy", 20),
            ("xyz", 30),
            ("xyzw", 40),
            ("xyzwv", 50),
        ]
        fst_path = build_fst(data)
        try:
            for key, val in data:
                got = run("get", fst_path, key).stdout.strip()
                assert got == str(val), f"get({key!r}): expected {val}, got {got}"
            # Also verify fuzzy distance-0 returns each with correct value
            for key, val in data:
                r = run("fuzzy", fst_path, key, "0")
                results = parse_fuzzy(r.stdout)
                assert len(results) == 1
                assert results[0] == (key, val, 0)
        finally:
            os.unlink(fst_path)

    def test_fuzzy_on_compressed_values(self):
        """Fuzzy search must return correct values from compressed structure."""
        data = [
            ("ab", 10),
            ("ac", 3),
            ("ad", 7),
            ("ae", 1),
        ]
        fst_path = build_fst(data)
        try:
            r = run("fuzzy", fst_path, "ab", "1")
            results = parse_fuzzy(r.stdout)
            value_map = {k: v for k, v, _ in results}
            for key, val in data:
                if key in value_map:
                    assert value_map[key] == val, \
                        f"fuzzy value for {key!r}: expected {val}, got {value_map[key]}"
            # ab (dist 0), ac/ad/ae (dist 1 via substitution), a (dist 1 via deletion)
            keys_found = {k for k, _, _ in results}
            assert "ab" in keys_found
            assert "ac" in keys_found
            assert "ad" in keys_found
            assert "ae" in keys_found
        finally:
            os.unlink(fst_path)
