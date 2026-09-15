
import os
import subprocess
import tempfile
import shutil
import pytest

JAVA_CMD = ["java", "-cp", "/app/bin", "compaction.Main"]


def write_sstable(path, level, created_at, size_bytes, first_key, last_key,
                  read_hotness, entries):
    """Write an SSTable file.
    entries: list of (key, timestamp, type_char, value, ttl)
    """
    with open(path, "w") as f:
        f.write(f"#META level={level} created_at={created_at} "
                f"size_bytes={size_bytes} first_key={first_key} "
                f"last_key={last_key} read_hotness={read_hotness}\n")
        for key, ts, typ, val, ttl in entries:
            val_str = val if val is not None else ""
            f.write(f"{key}\t{ts}\t{typ}\t{val_str}\t{ttl}\n")


def write_config(path, **kwargs):
    with open(path, "w") as f:
        for k, v in kwargs.items():
            f.write(f"{k}={v}\n")


def read_output_entries(path):
    """Read entries from an output SSTable, skipping the metadata line."""
    entries = []
    with open(path, "r") as f:
        lines = f.readlines()
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", -1)
        entries.append({
            "key": parts[0],
            "timestamp": int(parts[1]),
            "type": parts[2],
            "value": parts[3] if parts[3] else None,
            "ttl": int(parts[4]),
        })
    return entries


def run_engine(command, config_path):
    result = subprocess.run(
        JAVA_CMD + [command, config_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Engine failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp(prefix="lsm_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ============================================================
# MERGE TESTS
# ============================================================

class TestMergeLatestWins:
    """When two SSTables have the same key, highest timestamp wins."""

    def test_latest_timestamp_wins(self, tmpdir):
        sst_a = os.path.join(tmpdir, "a.sst")
        sst_b = os.path.join(tmpdir, "b.sst")
        out = os.path.join(tmpdir, "out.sst")
        cfg = os.path.join(tmpdir, "cfg.properties")

        write_sstable(sst_a, 0, 100, 100, "key1", "key2", 0.0, [
            ("key1", 100, "V", "old_value", 0),
            ("key2", 200, "V", "stays_a", 0),
        ])
        write_sstable(sst_b, 0, 200, 100, "key1", "key3", 0.0, [
            ("key1", 200, "V", "new_value", 0),
            ("key3", 300, "V", "only_b", 0),
        ])
        write_config(cfg,
                     sstables=f"{sst_a},{sst_b}",
                     all_sstables=f"{sst_a},{sst_b}",
                     gc_grace_seconds=100000,
                     current_time=500,
                     output=out)

        run_engine("merge", cfg)
        entries = read_output_entries(out)

        keys = {e["key"]: e for e in entries}
        assert "key1" in keys
        assert keys["key1"]["value"] == "new_value", \
            "key1 should have newest value (ts=200)"
        assert keys["key1"]["timestamp"] == 200
        assert "key2" in keys
        assert keys["key2"]["value"] == "stays_a"
        assert "key3" in keys
        assert keys["key3"]["value"] == "only_b"
        assert len(entries) == 3


class TestMergeTombstoneRetained:
    """Tombstone younger than gc_grace must be retained in output."""

    def test_tombstone_not_purged_when_young(self, tmpdir):
        sst_a = os.path.join(tmpdir, "a.sst")
        sst_b = os.path.join(tmpdir, "b.sst")
        out = os.path.join(tmpdir, "out.sst")
        cfg = os.path.join(tmpdir, "cfg.properties")

        write_sstable(sst_a, 0, 100, 100, "key1", "key1", 0.0, [
            ("key1", 100, "V", "hello", 0),
        ])
        write_sstable(sst_b, 0, 200, 100, "key1", "key1", 0.0, [
            ("key1", 200, "D", None, 0),
        ])
        # gc_grace=10000, tombstone age=300 < 10000 => NOT purgeable
        write_config(cfg,
                     sstables=f"{sst_a},{sst_b}",
                     all_sstables=f"{sst_a},{sst_b}",
                     gc_grace_seconds=10000,
                     current_time=500,
                     output=out)

        run_engine("merge", cfg)
        entries = read_output_entries(out)

        assert len(entries) == 1, \
            "Tombstone should be retained (gc_grace not elapsed)"
        assert entries[0]["key"] == "key1"
        assert entries[0]["type"] == "D"
        assert entries[0]["timestamp"] == 200


class TestMergeGcGracePurge:
    """Tombstone older than gc_grace is purged when all SSTables included."""

    def test_tombstone_purged(self, tmpdir):
        sst_a = os.path.join(tmpdir, "a.sst")
        sst_b = os.path.join(tmpdir, "b.sst")
        out = os.path.join(tmpdir, "out.sst")
        cfg = os.path.join(tmpdir, "cfg.properties")

        write_sstable(sst_a, 0, 100, 100, "key1", "key1", 0.0, [
            ("key1", 100, "V", "hello", 0),
        ])
        write_sstable(sst_b, 0, 200, 100, "key1", "key1", 0.0, [
            ("key1", 200, "D", None, 0),
        ])
        # gc_grace=100, tombstone age=300 >= 100, all SSTables merged
        write_config(cfg,
                     sstables=f"{sst_a},{sst_b}",
                     all_sstables=f"{sst_a},{sst_b}",
                     gc_grace_seconds=100,
                     current_time=500,
                     output=out)

        run_engine("merge", cfg)
        entries = read_output_entries(out)

        assert len(entries) == 0, \
            "Tombstone + shadowed value should both be purged"


class TestMergeNonPurgeableOverlap:
    """Tombstone NOT purged when an unmerged SSTable overlaps the key."""

    def test_tombstone_kept_due_to_overlap(self, tmpdir):
        sst_a = os.path.join(tmpdir, "a.sst")
        sst_b = os.path.join(tmpdir, "b.sst")
        sst_c = os.path.join(tmpdir, "c.sst")
        out = os.path.join(tmpdir, "out.sst")
        cfg = os.path.join(tmpdir, "cfg.properties")

        # SSTable A is NOT in the merge set but overlaps key1
        write_sstable(sst_a, 0, 50, 100, "key1", "key2", 0.0, [
            ("key1", 50, "V", "ancient_value", 0),
            ("key2", 50, "V", "other", 0),
        ])
        # SSTable B has tombstone for key1
        write_sstable(sst_b, 0, 200, 100, "key1", "key1", 0.0, [
            ("key1", 200, "D", None, 0),
        ])
        # SSTable C has unrelated data
        write_sstable(sst_c, 0, 300, 100, "key3", "key3", 0.0, [
            ("key3", 300, "V", "new_value", 0),
        ])

        # Merge B and C only; A is excluded from merge but in all_sstables
        # gc_grace=100, tombstone age=300 >= 100, BUT A overlaps key1
        write_config(cfg,
                     sstables=f"{sst_b},{sst_c}",
                     all_sstables=f"{sst_a},{sst_b},{sst_c}",
                     gc_grace_seconds=100,
                     current_time=500,
                     output=out)

        run_engine("merge", cfg)
        entries = read_output_entries(out)

        keys = {e["key"]: e for e in entries}
        assert "key1" in keys, \
            "Tombstone must be retained (unmerged SSTable A overlaps key1)"
        assert keys["key1"]["type"] == "D"
        assert "key3" in keys
        assert keys["key3"]["value"] == "new_value"


class TestMergeTtlExpiry:
    """Expired TTL entry becomes implicit tombstone."""

    def test_expired_ttl_becomes_tombstone(self, tmpdir):
        sst_a = os.path.join(tmpdir, "a.sst")
        sst_b = os.path.join(tmpdir, "b.sst")
        out = os.path.join(tmpdir, "out.sst")
        cfg = os.path.join(tmpdir, "cfg.properties")

        write_sstable(sst_a, 0, 100, 100, "key1", "key1", 0.0, [
            ("key1", 100, "V", "old_value", 0),
        ])
        # TTL entry: timestamp=200, ttl=100 => expires at 300
        write_sstable(sst_b, 0, 200, 100, "key1", "key1", 0.0, [
            ("key1", 200, "T", "ttl_value", 100),
        ])
        # current_time=500, expired at 300 => becomes DELETE@300
        # DELETE@300 vs VALUE@100 => DELETE wins
        # tombstone age = 500-300 = 200, gc_grace=10000 => NOT purgeable
        write_config(cfg,
                     sstables=f"{sst_a},{sst_b}",
                     all_sstables=f"{sst_a},{sst_b}",
                     gc_grace_seconds=10000,
                     current_time=500,
                     output=out)

        run_engine("merge", cfg)
        entries = read_output_entries(out)

        assert len(entries) == 1, \
            "Expired TTL should produce one tombstone entry"
        assert entries[0]["key"] == "key1"
        assert entries[0]["type"] == "D"
        assert entries[0]["timestamp"] == 300, \
            "Implicit tombstone timestamp should be timestamp+ttl=300"


class TestMergeTtlNotExpired:
    """Non-expired TTL entry is preserved as-is."""

    def test_ttl_preserved_when_not_expired(self, tmpdir):
        sst_a = os.path.join(tmpdir, "a.sst")
        sst_b = os.path.join(tmpdir, "b.sst")
        out = os.path.join(tmpdir, "out.sst")
        cfg = os.path.join(tmpdir, "cfg.properties")

        write_sstable(sst_a, 0, 100, 100, "key1", "key1", 0.0, [
            ("key1", 100, "V", "old_value", 0),
        ])
        # TTL entry: timestamp=200, ttl=500 => expires at 700
        write_sstable(sst_b, 0, 200, 100, "key1", "key1", 0.0, [
            ("key1", 200, "T", "ttl_value", 500),
        ])
        # current_time=300, NOT expired (700 > 300)
        # TTL@200 vs VALUE@100 => TTL wins (higher timestamp)
        write_config(cfg,
                     sstables=f"{sst_a},{sst_b}",
                     all_sstables=f"{sst_a},{sst_b}",
                     gc_grace_seconds=10000,
                     current_time=300,
                     output=out)

        run_engine("merge", cfg)
        entries = read_output_entries(out)

        assert len(entries) == 1
        assert entries[0]["key"] == "key1"
        assert entries[0]["type"] == "T"
        assert entries[0]["value"] == "ttl_value"
        assert entries[0]["timestamp"] == 200
        assert entries[0]["ttl"] == 500


# ============================================================
# STCS TESTS
# ============================================================

class TestSTCSSelection:
    """STCS: correct bucketing, hottest bucket selection, trim to max."""

    def test_selects_hottest_bucket(self, tmpdir):
        # Group A: sizes ~100, low hotness
        # Group B: sizes ~1000, high hotness
        # Solo: size 50000, very high hotness (but alone, below min_threshold)
        sst_paths = []

        for i, (size, hotness, prefix) in enumerate([
            (100, 1.0, "a"), (110, 1.0, "a"), (120, 1.0, "a"), (130, 1.0, "a"),
            (1000, 10.0, "b"), (1100, 10.0, "b"), (1200, 10.0, "b"),
            (1300, 10.0, "b"),
            (50000, 100.0, "s"),
        ]):
            p = os.path.join(tmpdir, f"{prefix}_{i}.sst")
            write_sstable(p, 0, i * 100, size, "a", "z", hotness, [])
            sst_paths.append(p)

        cfg = os.path.join(tmpdir, "cfg.properties")
        write_config(cfg,
                     all_sstables=",".join(sst_paths),
                     **{"stcs.bucket_high": "1.5",
                        "stcs.bucket_low": "0.5",
                        "stcs.min_sstable_size": "50",
                        "stcs.min_threshold": "4",
                        "stcs.max_threshold": "4"})

        stdout = run_engine("select-stcs", cfg)
        selected = [s.strip() for s in stdout.strip().split("\n") if s.strip()]

        # Solo SSTable should NOT be selected (bucket too small)
        solo_path = sst_paths[8]
        assert solo_path not in selected, \
            f"Solo SSTable should not be selected (bucket size < min_threshold)"

        # Group B should be selected (hottest qualifying bucket)
        group_b_paths = set(sst_paths[4:8])
        selected_set = set(selected)
        assert selected_set == group_b_paths, \
            f"Should select group B (hottest). Got {selected_set}, expected {group_b_paths}"


class TestSTCSSmallSSTables:
    """STCS: SSTables below min_sstable_size are grouped together."""

    def test_small_sstables_group(self, tmpdir):
        # 4 small SSTables (sizes vary widely but all < min_sstable_size)
        # 1 large SSTable
        sst_paths = []
        for i, (size, hotness) in enumerate([
            (5, 2.0), (15, 2.0), (45, 2.0), (135, 2.0),
            (500, 0.1),
        ]):
            p = os.path.join(tmpdir, f"sst_{i}.sst")
            write_sstable(p, 0, i * 100, size, "a", "z", hotness, [])
            sst_paths.append(p)

        cfg = os.path.join(tmpdir, "cfg.properties")
        write_config(cfg,
                     all_sstables=",".join(sst_paths),
                     **{"stcs.bucket_high": "1.5",
                        "stcs.bucket_low": "0.5",
                        "stcs.min_sstable_size": "200",
                        "stcs.min_threshold": "4",
                        "stcs.max_threshold": "10"})

        stdout = run_engine("select-stcs", cfg)
        selected = [s.strip() for s in stdout.strip().split("\n") if s.strip()]

        # Small SSTables should group and be selected
        small_paths = set(sst_paths[:4])
        large_path = sst_paths[4]
        selected_set = set(selected)

        assert small_paths.issubset(selected_set), \
            f"All 4 small SSTables should be selected. Got {selected_set}"
        assert large_path not in selected_set, \
            "Large SSTable should not be in the small-SSTable bucket"


# ============================================================
# LCS TESTS
# ============================================================

class TestLCSFormula:
    """LCS: correct exponential capacity formula for level scoring."""

    def test_level_score_with_exponential_formula(self, tmpdir):
        # L1: 11 SSTables x 1MB = 11MB
        # With correct formula: max(1) = 10^1 * 1MB = 10MB, score=1.1 > 1.001
        # With buggy formula: max(1) = (10+1)*1MB = 11MB, score=1.0 <= 1.001
        sst_paths = []
        one_mb = 1024 * 1024
        for i in range(11):
            p = os.path.join(tmpdir, f"l1_{i}.sst")
            fk = chr(ord('a') + i)
            lk = chr(ord('a') + i)
            write_sstable(p, 1, i * 100, one_mb, fk, lk, 0.0, [])
            sst_paths.append(p)

        # L2: 2 SSTables (to have overlap targets)
        for i in range(2):
            p = os.path.join(tmpdir, f"l2_{i}.sst")
            fk = chr(ord('a') + i * 6)
            lk = chr(ord('a') + i * 6 + 5)
            write_sstable(p, 2, 2000 + i * 100, one_mb, fk, lk, 0.0, [])
            sst_paths.append(p)

        cfg = os.path.join(tmpdir, "cfg.properties")
        write_config(cfg,
                     all_sstables=",".join(sst_paths),
                     **{"lcs.max_sstable_size_mb": "1",
                        "lcs.fanout_size": "10"})

        stdout = run_engine("select-lcs", cfg)
        selected = [s.strip() for s in stdout.strip().split("\n") if s.strip()]

        assert len(selected) > 0, \
            "L1 is over-full (11MB > 10MB max); should select SSTables"


class TestLCSDirection:
    """LCS: selects from highest over-full level, not lowest."""

    def test_highest_overfull_level_first(self, tmpdir):
        one_mb = 1024 * 1024
        sst_paths = []

        # L1: 2 SSTables x 3MB = 6MB, max(1)=4*1MB=4MB, score=1.5
        for i in range(2):
            p = os.path.join(tmpdir, f"l1_{i}.sst")
            fk = chr(ord('a') + i * 13)
            lk = chr(ord('a') + i * 13 + 12) if i == 0 else 'z'
            write_sstable(p, 1, 100 + i, 3 * one_mb, fk, lk, 0.0, [])
            sst_paths.append(p)

        # L2: 2 SSTables x 10MB = 20MB, max(2)=4^2*1MB=16MB, score=1.25
        for i in range(2):
            p = os.path.join(tmpdir, f"l2_{i}.sst")
            fk = chr(ord('a') + i * 13)
            lk = chr(ord('a') + i * 13 + 12) if i == 0 else 'z'
            write_sstable(p, 2, 200 + i, 10 * one_mb, fk, lk, 0.0, [])
            sst_paths.append(p)

        # L3: empty (so L2 overlap targets are empty)

        cfg = os.path.join(tmpdir, "cfg.properties")
        write_config(cfg,
                     all_sstables=",".join(sst_paths),
                     **{"lcs.max_sstable_size_mb": "1",
                        "lcs.fanout_size": "4"})

        stdout = run_engine("select-lcs", cfg)
        selected = [s.strip() for s in stdout.strip().split("\n") if s.strip()]

        # Should pick from L2 (highest over-full), not L1
        l2_paths = {os.path.join(tmpdir, f"l2_{i}.sst") for i in range(2)}
        l1_paths = {os.path.join(tmpdir, f"l1_{i}.sst") for i in range(2)}

        assert any(p in l2_paths for p in selected), \
            f"Should select from L2 (highest over-full). Selected: {selected}"
        assert not any(p in l1_paths for p in selected), \
            f"Should NOT select from L1 when L2 is also over-full. Selected: {selected}"


class TestLCSOverlap:
    """LCS: includes overlapping SSTables from the next level."""

    def test_overlap_detection(self, tmpdir):
        one_mb = 1024 * 1024
        sst_paths = []

        # L1: 3 SSTables, each 4MB = 12MB, max(1)=10MB
        ranges_l1 = [("a", "d"), ("e", "h"), ("i", "l")]
        for i, (fk, lk) in enumerate(ranges_l1):
            p = os.path.join(tmpdir, f"l1_{i}.sst")
            write_sstable(p, 1, 100 + i, 4 * one_mb, fk, lk, 0.0, [])
            sst_paths.append(p)

        # L2: 2 SSTables
        ranges_l2 = [("a", "f"), ("g", "l")]
        for i, (fk, lk) in enumerate(ranges_l2):
            p = os.path.join(tmpdir, f"l2_{i}.sst")
            write_sstable(p, 2, 200 + i, one_mb, fk, lk, 0.0, [])
            sst_paths.append(p)

        cfg = os.path.join(tmpdir, "cfg.properties")
        write_config(cfg,
                     all_sstables=",".join(sst_paths),
                     **{"lcs.max_sstable_size_mb": "1",
                        "lcs.fanout_size": "10"})

        stdout = run_engine("select-lcs", cfg)
        selected = [s.strip() for s in stdout.strip().split("\n") if s.strip()]

        # Should pick L1 SSTable "a-d" + overlapping L2 SSTable "a-f"
        l1_0 = os.path.join(tmpdir, "l1_0.sst")  # a-d
        l2_0 = os.path.join(tmpdir, "l2_0.sst")  # a-f (overlaps a-d)

        assert l1_0 in selected, \
            f"L1 SSTable (a-d) should be selected. Got: {selected}"
        assert l2_0 in selected, \
            f"Overlapping L2 SSTable (a-f) must be included. Got: {selected}"
        assert len(selected) == 2, \
            f"Should select exactly 2 SSTables (1 from L1 + 1 overlap from L2). Got {len(selected)}"
