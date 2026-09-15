import subprocess
import os
import json
import pytest


BINARY = "/app/target/release/fst-engine"


@pytest.fixture(scope="session", autouse=True)
def build_project():
    """Build the Rust project before running tests."""
    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


def run_cmd(args, check=True):
    result = subprocess.run(
        [BINARY] + args,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check:
        assert result.returncode == 0, (
            f"Command failed: {args}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def create_input(entries, path):
    """Write tab-separated key\\tvalue entries to a file."""
    with open(path, "w") as f:
        for key, val in entries:
            f.write(f"{key}\t{val}\n")


def parse_output_lines(stdout):
    """Parse non-empty output lines."""
    return [l for l in stdout.strip().split("\n") if l]


# ========================= BUILD + CONTAINS =========================


class TestBuildAndContains:
    def test_basic_build(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("jul", 7), ("jun", 6), ("mar", 3), ("may", 5)], inp)
        run_cmd(["build", inp, fst])
        assert os.path.exists(fst)
        assert os.path.getsize(fst) > 0

    def test_contains_existing_keys(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("jul", 7), ("jun", 6), ("mar", 3), ("may", 5)], inp)
        run_cmd(["build", inp, fst])
        for key in ["jul", "jun", "mar", "may"]:
            r = run_cmd(["contains", fst, key])
            assert r.stdout.strip() == "true", f"contains({key}) should be true"

    def test_contains_missing_keys(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("jul", 7), ("jun", 6), ("mar", 3), ("may", 5)], inp)
        run_cmd(["build", inp, fst])
        for key in ["ju", "j", "july", "max", "april", "z", "m", "ma", "jun1"]:
            r = run_cmd(["contains", fst, key])
            assert r.stdout.strip() == "false", f"contains({key}) should be false"


# ========================= GET =========================


class TestGet:
    def test_get_values_basic(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("jul", 7), ("jun", 6), ("mar", 3), ("may", 5)], inp)
        run_cmd(["build", inp, fst])
        expected = {"jul": "7", "jun": "6", "mar": "3", "may": "5"}
        for key, val in expected.items():
            r = run_cmd(["get", fst, key])
            assert r.stdout.strip() == val, f"get({key}) = {r.stdout.strip()}, expected {val}"

    def test_get_not_found(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("jul", 7), ("jun", 6)], inp)
        run_cmd(["build", inp, fst])
        for key in ["jx", "julx", "j", "a", "zzz"]:
            r = run_cmd(["get", fst, key])
            assert r.stdout.strip() == "NOT_FOUND", f"get({key}) should be NOT_FOUND"

    def test_get_zero_values(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("aaa", 0), ("bbb", 0), ("ccc", 0)], inp)
        run_cmd(["build", inp, fst])
        for key in ["aaa", "bbb", "ccc"]:
            r = run_cmd(["get", fst, key])
            assert r.stdout.strip() == "0", f"get({key}) should be 0"


# ========================= OUTPUT ACCUMULATION =========================


class TestOutputAccumulation:
    def test_prefix_key_values(self, tmp_path):
        """One key is a prefix of another; values must accumulate correctly."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("a", 3), ("ab", 7), ("abc", 15)], inp)
        run_cmd(["build", inp, fst])
        assert run_cmd(["get", fst, "a"]).stdout.strip() == "3"
        assert run_cmd(["get", fst, "ab"]).stdout.strip() == "7"
        assert run_cmd(["get", fst, "abc"]).stdout.strip() == "15"

    def test_decreasing_values_with_shared_prefix(self, tmp_path):
        """Second value smaller than first with shared prefix."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("ba", 100), ("bb", 50)], inp)
        run_cmd(["build", inp, fst])
        assert run_cmd(["get", fst, "ba"]).stdout.strip() == "100"
        assert run_cmd(["get", fst, "bb"]).stdout.strip() == "50"

    def test_prefix_key_larger_value(self, tmp_path):
        """Prefix key has larger value than longer key."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("fo", 100), ("foo", 50)], inp)
        run_cmd(["build", inp, fst])
        assert run_cmd(["get", fst, "fo"]).stdout.strip() == "100"
        assert run_cmd(["get", fst, "foo"]).stdout.strip() == "50"

    def test_large_values(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input(
            [("alpha", 1000000), ("beta", 2000000), ("gamma", 3000000)], inp
        )
        run_cmd(["build", inp, fst])
        assert run_cmd(["get", fst, "alpha"]).stdout.strip() == "1000000"
        assert run_cmd(["get", fst, "beta"]).stdout.strip() == "2000000"
        assert run_cmd(["get", fst, "gamma"]).stdout.strip() == "3000000"

    def test_many_shared_prefix_values(self, tmp_path):
        """Multiple keys sharing a long prefix with various values."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        entries = [
            ("prefix_aa", 10),
            ("prefix_ab", 20),
            ("prefix_ac", 30),
            ("prefix_ba", 40),
            ("prefix_bb", 50),
        ]
        create_input(entries, inp)
        run_cmd(["build", inp, fst])
        for key, val in entries:
            r = run_cmd(["get", fst, key])
            assert r.stdout.strip() == str(val), f"get({key}) = {r.stdout.strip()}, expected {val}"

    def test_deep_prefix_chain(self, tmp_path):
        """Chain of prefix keys with non-monotonic values."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        entries = [
            ("x", 100),
            ("xy", 50),
            ("xyz", 200),
            ("xyzw", 75),
        ]
        create_input(entries, inp)
        run_cmd(["build", inp, fst])
        for key, val in entries:
            r = run_cmd(["get", fst, key])
            assert r.stdout.strip() == str(val), f"get({key}) = {r.stdout.strip()}, expected {val}"


# ========================= STATE SHARING =========================


class TestStateSharing:
    def test_suffix_sharing_jul_jun_mar_may(self, tmp_path):
        """The canonical example: 4 keys must produce <= 8 states via suffix sharing."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("jul", 7), ("jun", 6), ("mar", 3), ("may", 5)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["stats", fst])
        stats = json.loads(r.stdout.strip())
        assert stats["num_keys"] == 4
        assert stats["num_states"] <= 8, (
            f"Expected <= 8 states for jul/jun/mar/may, got {stats['num_states']}"
        )

    def test_shared_leaf_states(self, tmp_path):
        """26 single-char keys should share one final state."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        entries = [(chr(ord("a") + i), i + 1) for i in range(26)]
        create_input(entries, inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["stats", fst])
        stats = json.loads(r.stdout.strip())
        assert stats["num_keys"] == 26
        assert stats["num_states"] <= 3, (
            f"Expected <= 3 states for 26 single-char keys, got {stats['num_states']}"
        )

    def test_many_keys_fewer_states_than_trie(self, tmp_path):
        """With suffix sharing, state count must be less than key count."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        entries = [
            (f"prefix_{chr(ord('a') + i)}_{chr(ord('a') + j)}", i * 26 + j)
            for i in range(26)
            for j in range(26)
        ]
        entries.sort()
        create_input(entries, inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["stats", fst])
        stats = json.loads(r.stdout.strip())
        assert stats["num_keys"] == 676
        assert stats["num_states"] < 676, (
            f"State deduplication should produce fewer states than keys"
        )

    def test_identical_suffixes_collapse(self, tmp_path):
        """Keys with identical suffix structure should share states."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        entries = [(f"{c}at", 0) for c in "bcfhmprs"]
        entries.sort()
        create_input(entries, inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["stats", fst])
        stats = json.loads(r.stdout.strip())
        # root -> {b,c,f,h,m,p,r,s} -> shared 'a' -> shared 't' -> shared final
        # = 4 states max (root, a-state, t-state, final)
        assert stats["num_states"] <= 4, (
            f"8 keys ?at with same suffix structure should share, got {stats['num_states']} states"
        )


# ========================= RANGE QUERIES =========================


class TestRange:
    def test_full_range_all_entries(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input(
            [("apple", 1), ("banana", 2), ("cherry", 3), ("date", 4)], inp
        )
        run_cmd(["build", inp, fst])
        r = run_cmd(["range", fst])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 4
        assert lines[0] == "apple\t1"
        assert lines[1] == "banana\t2"
        assert lines[2] == "cherry\t3"
        assert lines[3] == "date\t4"

    def test_range_ge_and_le(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input(
            [("apple", 1), ("banana", 2), ("cherry", 3), ("date", 4)], inp
        )
        run_cmd(["build", inp, fst])
        r = run_cmd(["range", fst, "--ge", "banana", "--le", "cherry"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 2
        assert lines[0] == "banana\t2"
        assert lines[1] == "cherry\t3"

    def test_range_ge_only(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input(
            [("apple", 1), ("banana", 2), ("cherry", 3), ("date", 4)], inp
        )
        run_cmd(["build", inp, fst])
        r = run_cmd(["range", fst, "--ge", "cherry"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 2
        assert lines[0] == "cherry\t3"
        assert lines[1] == "date\t4"

    def test_range_le_only(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input(
            [("apple", 1), ("banana", 2), ("cherry", 3), ("date", 4)], inp
        )
        run_cmd(["build", inp, fst])
        r = run_cmd(["range", fst, "--le", "banana"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 2
        assert lines[0] == "apple\t1"
        assert lines[1] == "banana\t2"

    def test_range_empty_result(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("apple", 1), ("banana", 2)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["range", fst, "--ge", "cat", "--le", "dog"])
        assert r.stdout.strip() == ""

    def test_range_output_sorted(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input(
            [("cat", 1), ("cow", 2), ("cup", 3), ("dog", 4), ("elk", 5)], inp
        )
        run_cmd(["build", inp, fst])
        r = run_cmd(["range", fst])
        lines = parse_output_lines(r.stdout)
        keys = [l.split("\t")[0] for l in lines]
        assert keys == sorted(keys), "Range output must be in sorted order"


# ========================= FUZZY SEARCH =========================


class TestFuzzy:
    def test_exact_match_distance_0(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("bar", 2), ("baz", 3), ("foo", 1)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["fuzzy", fst, "foo", "0"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 1
        assert lines[0] == "foo\t1"

    def test_distance_1_classic_example(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        keys = [
            ("fa", 1),
            ("fo", 2),
            ("fob", 3),
            ("focus", 4),
            ("foo", 5),
            ("food", 6),
            ("foul", 7),
        ]
        create_input(keys, inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["fuzzy", fst, "foo", "1"])
        lines = parse_output_lines(r.stdout)
        result_keys = [l.split("\t")[0] for l in lines]
        assert "fo" in result_keys, "fo should be within distance 1"
        assert "fob" in result_keys, "fob should be within distance 1"
        assert "foo" in result_keys, "foo should be within distance 0"
        assert "food" in result_keys, "food should be within distance 1"
        assert "fa" not in result_keys, "fa is distance 2"
        assert "focus" not in result_keys, "focus is distance 3"
        assert "foul" not in result_keys, "foul is distance 2"

    def test_distance_2(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        keys = [
            ("fa", 1),
            ("fo", 2),
            ("fob", 3),
            ("focus", 4),
            ("foo", 5),
            ("food", 6),
            ("foul", 7),
        ]
        create_input(keys, inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["fuzzy", fst, "foo", "2"])
        lines = parse_output_lines(r.stdout)
        result_keys = [l.split("\t")[0] for l in lines]
        for k in ["fa", "fo", "fob", "foo", "food", "foul"]:
            assert k in result_keys, f"{k} should be within distance 2 of foo"
        assert "focus" not in result_keys, "focus is distance 3"

    def test_fuzzy_no_match(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("apple", 1), ("banana", 2)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["fuzzy", fst, "xyz", "1"])
        assert r.stdout.strip() == ""

    def test_fuzzy_output_sorted(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input(
            [("bar", 1), ("bat", 2), ("car", 3), ("cat", 4), ("far", 5)], inp
        )
        run_cmd(["build", inp, fst])
        r = run_cmd(["fuzzy", fst, "bar", "1"])
        lines = parse_output_lines(r.stdout)
        keys = [l.split("\t")[0] for l in lines]
        assert keys == sorted(keys), "Fuzzy output must be in sorted order"

    def test_fuzzy_values_correct(self, tmp_path):
        """Verify that fuzzy search returns correct associated values."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        keys = [
            ("fo", 2),
            ("fob", 3),
            ("foo", 5),
            ("food", 6),
        ]
        create_input(keys, inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["fuzzy", fst, "foo", "1"])
        lines = parse_output_lines(r.stdout)
        result_map = {}
        for l in lines:
            parts = l.split("\t")
            result_map[parts[0]] = int(parts[1])
        assert result_map.get("fo") == 2
        assert result_map.get("fob") == 3
        assert result_map.get("foo") == 5
        assert result_map.get("food") == 6


# ========================= PREFIX SEARCH =========================


class TestPrefix:
    def test_basic_prefix(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input(
            [("apple", 1), ("application", 2), ("banana", 3), ("band", 4)], inp
        )
        run_cmd(["build", inp, fst])
        r = run_cmd(["prefix", fst, "app"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 2
        assert lines[0] == "apple\t1"
        assert lines[1] == "application\t2"

    def test_prefix_empty_returns_all(self, tmp_path):
        """Empty prefix returns all entries."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("a", 1), ("b", 2), ("c", 3)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["prefix", fst, ""])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 3
        assert lines[0] == "a\t1"
        assert lines[1] == "b\t2"
        assert lines[2] == "c\t3"

    def test_prefix_no_match(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("apple", 1), ("banana", 2)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["prefix", fst, "cherry"])
        assert r.stdout.strip() == ""

    def test_prefix_exact_key_with_extensions(self, tmp_path):
        """Prefix is an exact key that also has longer extensions."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("a", 3), ("ab", 7), ("abc", 15)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["prefix", fst, "a"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 3
        assert lines[0] == "a\t3"
        assert lines[1] == "ab\t7"
        assert lines[2] == "abc\t15"

    def test_prefix_sorted_output(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("za", 1), ("zb", 2), ("zc", 3), ("zd", 4)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["prefix", fst, "z"])
        lines = parse_output_lines(r.stdout)
        keys = [l.split("\t")[0] for l in lines]
        assert keys == sorted(keys)
        assert len(lines) == 4

    def test_prefix_with_values(self, tmp_path):
        """Verify correct value retrieval in prefix results."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("pre", 100), ("prefix", 200), ("prevent", 300), ("zoo", 400)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["prefix", fst, "pre"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 3
        result_map = {}
        for l in lines:
            parts = l.split("\t")
            result_map[parts[0]] = int(parts[1])
        assert result_map["pre"] == 100
        assert result_map["prefix"] == 200
        assert result_map["prevent"] == 300


# ========================= MERGE =========================


class TestMerge:
    def test_merge_disjoint(self, tmp_path):
        """Merging two FSTs with no common keys."""
        inp1 = str(tmp_path / "a.tsv")
        inp2 = str(tmp_path / "b.tsv")
        fst1 = str(tmp_path / "a.fst")
        fst2 = str(tmp_path / "b.fst")
        merged = str(tmp_path / "merged.fst")

        create_input([("apple", 10), ("banana", 20)], inp1)
        create_input([("cherry", 30), ("date", 40)], inp2)
        run_cmd(["build", inp1, fst1])
        run_cmd(["build", inp2, fst2])
        run_cmd(["merge", fst1, fst2, merged])

        assert run_cmd(["get", merged, "apple"]).stdout.strip() == "10"
        assert run_cmd(["get", merged, "banana"]).stdout.strip() == "20"
        assert run_cmd(["get", merged, "cherry"]).stdout.strip() == "30"
        assert run_cmd(["get", merged, "date"]).stdout.strip() == "40"

        stats = json.loads(run_cmd(["stats", merged]).stdout.strip())
        assert stats["num_keys"] == 4

    def test_merge_overlapping_sums_values(self, tmp_path):
        """Overlapping keys should have summed values."""
        inp1 = str(tmp_path / "a.tsv")
        inp2 = str(tmp_path / "b.tsv")
        fst1 = str(tmp_path / "a.fst")
        fst2 = str(tmp_path / "b.fst")
        merged = str(tmp_path / "merged.fst")

        create_input([("apple", 10), ("banana", 20), ("cherry", 30)], inp1)
        create_input([("banana", 5), ("cherry", 15), ("date", 25)], inp2)
        run_cmd(["build", inp1, fst1])
        run_cmd(["build", inp2, fst2])
        run_cmd(["merge", fst1, fst2, merged])

        assert run_cmd(["get", merged, "apple"]).stdout.strip() == "10"
        assert run_cmd(["get", merged, "banana"]).stdout.strip() == "25"
        assert run_cmd(["get", merged, "cherry"]).stdout.strip() == "45"
        assert run_cmd(["get", merged, "date"]).stdout.strip() == "25"

    def test_merge_identical_keys(self, tmp_path):
        """All keys overlap."""
        inp1 = str(tmp_path / "a.tsv")
        inp2 = str(tmp_path / "b.tsv")
        fst1 = str(tmp_path / "a.fst")
        fst2 = str(tmp_path / "b.fst")
        merged = str(tmp_path / "merged.fst")

        create_input([("x", 10), ("y", 20), ("z", 30)], inp1)
        create_input([("x", 1), ("y", 2), ("z", 3)], inp2)
        run_cmd(["build", inp1, fst1])
        run_cmd(["build", inp2, fst2])
        run_cmd(["merge", fst1, fst2, merged])

        assert run_cmd(["get", merged, "x"]).stdout.strip() == "11"
        assert run_cmd(["get", merged, "y"]).stdout.strip() == "22"
        assert run_cmd(["get", merged, "z"]).stdout.strip() == "33"

        stats = json.loads(run_cmd(["stats", merged]).stdout.strip())
        assert stats["num_keys"] == 3

    def test_merge_with_empty(self, tmp_path):
        """Merging with an empty FST."""
        inp1 = str(tmp_path / "a.tsv")
        inp2 = str(tmp_path / "empty.tsv")
        fst1 = str(tmp_path / "a.fst")
        fst2 = str(tmp_path / "empty.fst")
        merged = str(tmp_path / "merged.fst")

        create_input([("hello", 42)], inp1)
        create_input([], inp2)
        run_cmd(["build", inp1, fst1])
        run_cmd(["build", inp2, fst2])
        run_cmd(["merge", fst1, fst2, merged])

        assert run_cmd(["get", merged, "hello"]).stdout.strip() == "42"
        stats = json.loads(run_cmd(["stats", merged]).stdout.strip())
        assert stats["num_keys"] == 1

    def test_merge_structural_compaction(self, tmp_path):
        """Merged result should have same compaction as fresh build."""
        inp1 = str(tmp_path / "a.tsv")
        inp2 = str(tmp_path / "b.tsv")
        fst1 = str(tmp_path / "a.fst")
        fst2 = str(tmp_path / "b.fst")
        merged_fst = str(tmp_path / "merged.fst")
        fresh_inp = str(tmp_path / "fresh.tsv")
        fresh_fst = str(tmp_path / "fresh.fst")

        create_input([("jul", 7), ("mar", 3)], inp1)
        create_input([("jun", 6), ("may", 5)], inp2)
        run_cmd(["build", inp1, fst1])
        run_cmd(["build", inp2, fst2])
        run_cmd(["merge", fst1, fst2, merged_fst])

        create_input([("jul", 7), ("jun", 6), ("mar", 3), ("may", 5)], fresh_inp)
        run_cmd(["build", fresh_inp, fresh_fst])

        merged_stats = json.loads(run_cmd(["stats", merged_fst]).stdout.strip())
        fresh_stats = json.loads(run_cmd(["stats", fresh_fst]).stdout.strip())

        assert merged_stats["num_keys"] == fresh_stats["num_keys"]
        assert merged_stats["num_states"] == fresh_stats["num_states"], (
            f"Merged has {merged_stats['num_states']} states vs fresh {fresh_stats['num_states']}"
        )

    def test_merge_range_query(self, tmp_path):
        """Range query on merged FST works correctly."""
        inp1 = str(tmp_path / "a.tsv")
        inp2 = str(tmp_path / "b.tsv")
        fst1 = str(tmp_path / "a.fst")
        fst2 = str(tmp_path / "b.fst")
        merged = str(tmp_path / "merged.fst")

        create_input([("apple", 10), ("cherry", 30)], inp1)
        create_input([("banana", 20), ("date", 40)], inp2)
        run_cmd(["build", inp1, fst1])
        run_cmd(["build", inp2, fst2])
        run_cmd(["merge", fst1, fst2, merged])

        r = run_cmd(["range", merged, "--ge", "banana", "--le", "cherry"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 2
        assert lines[0] == "banana\t20"
        assert lines[1] == "cherry\t30"


# ========================= ERROR HANDLING =========================


class TestErrors:
    def test_unsorted_input_rejected(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("banana", 2), ("apple", 1)], inp)
        r = run_cmd(["build", inp, fst], check=False)
        assert r.returncode != 0, "Unsorted input should cause exit code != 0"

    def test_duplicate_keys_rejected(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("apple", 1), ("apple", 2)], inp)
        r = run_cmd(["build", inp, fst], check=False)
        assert r.returncode != 0, "Duplicate keys should cause exit code != 0"


# ========================= EDGE CASES =========================


class TestEdgeCases:
    def test_empty_input(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([], inp)
        run_cmd(["build", inp, fst])
        assert run_cmd(["contains", fst, "anything"]).stdout.strip() == "false"
        assert run_cmd(["get", fst, "anything"]).stdout.strip() == "NOT_FOUND"
        r = run_cmd(["stats", fst])
        stats = json.loads(r.stdout.strip())
        assert stats["num_keys"] == 0

    def test_single_key(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("hello", 42)], inp)
        run_cmd(["build", inp, fst])
        assert run_cmd(["contains", fst, "hello"]).stdout.strip() == "true"
        assert run_cmd(["get", fst, "hello"]).stdout.strip() == "42"
        assert run_cmd(["contains", fst, "hell"]).stdout.strip() == "false"
        assert run_cmd(["get", fst, "helloo"]).stdout.strip() == "NOT_FOUND"


# ========================= STATS =========================


class TestStats:
    def test_stats_fields_present(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("a", 1), ("b", 2), ("c", 3)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["stats", fst])
        stats = json.loads(r.stdout.strip())
        for field in ["num_keys", "num_states", "num_transitions", "fst_size_bytes"]:
            assert field in stats, f"stats missing field: {field}"
            assert isinstance(stats[field], int), f"stats[{field}] should be int"
        assert stats["num_keys"] == 3
        assert stats["fst_size_bytes"] > 0

    def test_stats_transitions_count(self, tmp_path):
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        create_input([("jul", 7), ("jun", 6), ("mar", 3), ("may", 5)], inp)
        run_cmd(["build", inp, fst])
        r = run_cmd(["stats", fst])
        stats = json.loads(r.stdout.strip())
        assert stats["num_transitions"] >= 4, "Need at least some transitions"


# ========================= CONFORMANCE =========================


class TestConformance:
    """Verify behavior against reference datasets in /app/data/."""

    def test_months_from_reference(self, tmp_path):
        fst = str(tmp_path / "months.fst")
        run_cmd(["build", "/app/data/months.tsv", fst])

        with open("/app/data/reference.json") as f:
            ref_data = json.load(f)

        months = ref_data["months"]
        for key, expected_val in months["expected_gets"].items():
            actual = run_cmd(["get", fst, key]).stdout.strip()
            assert actual == str(expected_val), f"get({key}) = {actual}, expected {expected_val}"

        for key in months["expected_missing"]:
            actual = run_cmd(["get", fst, key]).stdout.strip()
            assert actual == "NOT_FOUND", f"get({key}) should be NOT_FOUND, got {actual}"

        stats = json.loads(run_cmd(["stats", fst]).stdout.strip())
        assert stats["num_states"] <= months["expected_stats"]["max_states"]

    def test_prefix_keys_from_reference(self, tmp_path):
        fst = str(tmp_path / "prefixes.fst")
        run_cmd(["build", "/app/data/prefixes.tsv", fst])

        with open("/app/data/reference.json") as f:
            ref_data = json.load(f)

        prefixes = ref_data["prefixes"]
        for key, expected_val in prefixes["expected_gets"].items():
            actual = run_cmd(["get", fst, key]).stdout.strip()
            assert actual == str(expected_val), f"get({key}) = {actual}, expected {expected_val}"

    def test_merge_from_reference(self, tmp_path):
        fst_a = str(tmp_path / "a.fst")
        fst_b = str(tmp_path / "b.fst")
        merged = str(tmp_path / "merged.fst")

        run_cmd(["build", "/app/data/words_a.tsv", fst_a])
        run_cmd(["build", "/app/data/words_b.tsv", fst_b])
        run_cmd(["merge", fst_a, fst_b, merged])

        with open("/app/data/reference.json") as f:
            ref_data = json.load(f)

        for key, expected_val in ref_data["merge"]["expected_merged_gets"].items():
            actual = run_cmd(["get", merged, key]).stdout.strip()
            assert actual == str(expected_val), f"merged get({key}) = {actual}, expected {expected_val}"

    def test_months_prefix_from_reference(self, tmp_path):
        """Prefix queries against months dataset."""
        fst = str(tmp_path / "months.fst")
        run_cmd(["build", "/app/data/months.tsv", fst])

        with open("/app/data/reference.json") as f:
            ref_data = json.load(f)

        expected_ju = ref_data["months"]["expected_prefix_ju"]
        r = run_cmd(["prefix", fst, "ju"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == len(expected_ju)
        for line, (ek, ev) in zip(lines, expected_ju):
            assert line == f"{ek}\t{ev}"

        expected_ma = ref_data["months"]["expected_prefix_ma"]
        r = run_cmd(["prefix", fst, "ma"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == len(expected_ma)
        for line, (ek, ev) in zip(lines, expected_ma):
            assert line == f"{ek}\t{ev}"

    def test_single_char_compaction_from_reference(self, tmp_path):
        """Verify the 26-char compaction target from reference."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        entries = [(chr(ord("a") + i), i + 1) for i in range(26)]
        create_input(entries, inp)
        run_cmd(["build", inp, fst])

        with open("/app/data/reference.json") as f:
            ref_data = json.load(f)

        max_states = ref_data["single_char_26"]["expected_max_states"]
        stats = json.loads(run_cmd(["stats", fst]).stdout.strip())
        assert stats["num_states"] <= max_states, (
            f"Reference says max {max_states} states for 26 single-char keys, got {stats['num_states']}"
        )


# ========================= LARGE DATASET =========================


class TestLargeDataset:
    def test_thousand_keys_all_correct(self, tmp_path):
        """Build FST with 1000 keys and verify spot-checked lookups."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        entries = [(f"key{i:05d}", i * 7) for i in range(1000)]
        create_input(entries, inp)
        run_cmd(["build", inp, fst])

        for i in [0, 1, 42, 123, 500, 777, 999]:
            key = f"key{i:05d}"
            expected = str(i * 7)
            actual = run_cmd(["get", fst, key]).stdout.strip()
            assert actual == expected, f"get({key}) = {actual}, expected {expected}"

        assert run_cmd(["get", fst, "key01000"]).stdout.strip() == "NOT_FOUND"

    def test_thousand_keys_range(self, tmp_path):
        """Range query on large dataset."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        entries = [(f"key{i:05d}", i) for i in range(1000)]
        create_input(entries, inp)
        run_cmd(["build", inp, fst])

        r = run_cmd(["range", fst, "--ge", "key00500", "--le", "key00509"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 10
        keys = [l.split("\t")[0] for l in lines]
        assert keys[0] == "key00500"
        assert keys[-1] == "key00509"

    def test_thousand_keys_prefix(self, tmp_path):
        """Prefix query on large dataset."""
        inp = str(tmp_path / "input.tsv")
        fst = str(tmp_path / "out.fst")
        entries = [(f"key{i:05d}", i) for i in range(1000)]
        create_input(entries, inp)
        run_cmd(["build", inp, fst])

        r = run_cmd(["prefix", fst, "key005"])
        lines = parse_output_lines(r.stdout)
        assert len(lines) == 100  # key00500 through key00599
        assert lines[0].startswith("key00500\t")
        assert lines[-1].startswith("key00599\t")

    def test_thousand_keys_merge(self, tmp_path):
        """Merge two large FSTs and verify."""
        inp1 = str(tmp_path / "a.tsv")
        inp2 = str(tmp_path / "b.tsv")
        fst1 = str(tmp_path / "a.fst")
        fst2 = str(tmp_path / "b.fst")
        merged = str(tmp_path / "merged.fst")

        entries1 = [(f"key{i:05d}", i) for i in range(500)]
        entries2 = [(f"key{i:05d}", i * 2) for i in range(250, 750)]
        create_input(entries1, inp1)
        create_input(entries2, inp2)
        run_cmd(["build", inp1, fst1])
        run_cmd(["build", inp2, fst2])
        run_cmd(["merge", fst1, fst2, merged])

        stats = json.loads(run_cmd(["stats", merged]).stdout.strip())
        assert stats["num_keys"] == 750  # 0..499 union 250..749

        # Unique to fst1: key00000 -> 0
        assert run_cmd(["get", merged, "key00000"]).stdout.strip() == "0"
        # Overlap: key00250 -> 250 + 500 = 750
        assert run_cmd(["get", merged, "key00250"]).stdout.strip() == "750"
        # Unique to fst2: key00600 -> 1200
        assert run_cmd(["get", merged, "key00600"]).stdout.strip() == "1200"
