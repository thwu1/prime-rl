
import subprocess
import json
import pytest

BINARY = "/app/target/release/vma_mgr"


def build():
    """Build the Rust project."""
    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"


@pytest.fixture(scope="session", autouse=True)
def ensure_built():
    build()


def run_ops(ops):
    """Run operations through the vma_mgr binary and return parsed results."""
    input_str = "\n".join(json.dumps(op) for op in ops) + "\n"
    result = subprocess.run(
        [BINARY],
        input=input_str,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Binary crashed:\n{result.stderr}"
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    assert len(lines) == len(ops), (
        f"Expected {len(ops)} output lines, got {len(lines)}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return [json.loads(l) for l in lines]


def vma(start, end, prot, map_type="private"):
    """Helper to build expected VMA dicts."""
    return {"start": start, "end": end, "prot": prot, "map_type": map_type}


# ── Basic mmap & query ──────────────────────────────────────────────


class TestBasicMmap:
    def test_basic_mmap_query(self):
        """Non-fixed mmap allocates at lowest gap; query returns VMA or null."""
        ops = [
            {"op": "mmap", "addr": None, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": False},
            {"op": "query", "addr": 4096},
            {"op": "query", "addr": 8192},
        ]
        results = run_ops(ops)
        assert results[0]["ok"]["addr"] == 4096
        assert results[1]["ok"]["vma"] == vma(4096, 8192, "rw-")
        assert results[2]["ok"]["vma"] is None

    def test_gap_finding_sequential(self):
        """Sequential non-fixed mmaps fill from the bottom."""
        ops = [
            {"op": "mmap", "addr": None, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": False},
            {"op": "mmap", "addr": None, "len": 4096, "prot": "r--",
             "map_type": "private", "fixed": False},
            {"op": "mmap", "addr": None, "len": 8192, "prot": "rwx",
             "map_type": "private", "fixed": False},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[0]["ok"]["addr"] == 4096
        assert results[1]["ok"]["addr"] == 8192
        assert results[2]["ok"]["addr"] == 12288
        assert results[3]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-"),
            vma(8192, 12288, "r--"),
            vma(12288, 20480, "rwx"),
        ]

    def test_gap_finding_skips_occupied(self):
        """Non-fixed mmap finds the first gap between existing VMAs."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 16384, "len": 4096, "prot": "r-x",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": None, "len": 4096, "prot": "r--",
             "map_type": "private", "fixed": False},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        # Gap between [4096,8192) and [16384,20480) starts at 8192
        assert results[2]["ok"]["addr"] == 8192
        assert results[3]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-"),
            vma(8192, 12288, "r--"),
            vma(16384, 20480, "r-x"),
        ]


# ── VMA merging ─────────────────────────────────────────────────────


class TestMerge:
    def test_merge_adjacent_same_attrs(self):
        """Adjacent VMAs with identical attrs are coalesced."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 8192, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[2]["ok"]["vmas"] == [vma(4096, 12288, "rw-")]

    def test_three_way_merge(self):
        """Filling a gap between two compatible VMAs triggers three-way merge."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 12288, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "dump"},
            {"op": "mmap", "addr": 8192, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        # Before: two separate VMAs with gap
        assert len(results[2]["ok"]["vmas"]) == 2
        # After: single merged VMA
        assert results[4]["ok"]["vmas"] == [vma(4096, 16384, "rw-")]

    def test_no_merge_different_prot(self):
        """Adjacent VMAs with different protection do not merge."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 8192, "len": 4096, "prot": "r--",
             "map_type": "private", "fixed": True},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[2]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-"),
            vma(8192, 12288, "r--"),
        ]

    def test_no_merge_different_maptype(self):
        """Adjacent VMAs with different map_type do not merge."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 8192, "len": 4096, "prot": "rw-",
             "map_type": "shared", "fixed": True},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[2]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-", "private"),
            vma(8192, 12288, "rw-", "shared"),
        ]


# ── MAP_FIXED ───────────────────────────────────────────────────────


class TestFixedMmap:
    def test_fixed_replaces_existing(self):
        """MAP_FIXED unmaps the target range, splitting the original VMA."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 12288, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 8192, "len": 4096, "prot": "r-x",
             "map_type": "private", "fixed": True},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[2]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-"),
            vma(8192, 12288, "r-x"),
            vma(12288, 16384, "rw-"),
        ]

    def test_fixed_partial_overlap_edges(self):
        """MAP_FIXED overlapping edges of two VMAs splits both."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 8192, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 16384, "len": 8192, "prot": "r--",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 8192, "len": 12288, "prot": "r-x",
             "map_type": "shared", "fixed": True},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        # First VMA trimmed to [4096,8192), second to [20480,24576)
        assert results[3]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-", "private"),
            vma(8192, 20480, "r-x", "shared"),
            vma(20480, 24576, "r--", "private"),
        ]


# ── munmap ──────────────────────────────────────────────────────────


class TestMunmap:
    def test_munmap_middle_split(self):
        """Unmapping the middle of a VMA splits it into two."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 12288, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "munmap", "addr": 8192, "len": 4096},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[2]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-"),
            vma(12288, 16384, "rw-"),
        ]

    def test_munmap_start_trim(self):
        """Unmapping the start of a VMA trims it."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 12288, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "munmap", "addr": 4096, "len": 4096},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[2]["ok"]["vmas"] == [vma(8192, 16384, "rw-")]

    def test_munmap_end_trim(self):
        """Unmapping the end of a VMA trims it."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 12288, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "munmap", "addr": 12288, "len": 4096},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[2]["ok"]["vmas"] == [vma(4096, 12288, "rw-")]

    def test_munmap_spanning_multiple(self):
        """Unmapping a range spanning multiple VMAs with partial overlaps."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 8192, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 16384, "len": 8192, "prot": "r--",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 28672, "len": 8192, "prot": "rwx",
             "map_type": "private", "fixed": True},
            {"op": "munmap", "addr": 8192, "len": 24576},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        # First trimmed to [4096,8192), second fully removed,
        # third trimmed to [32768,36864)
        assert results[4]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-"),
            vma(32768, 36864, "rwx"),
        ]

    def test_munmap_unmapped_succeeds(self):
        """Unmapping an already-unmapped range silently succeeds."""
        ops = [
            {"op": "munmap", "addr": 4096, "len": 4096},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert "ok" in results[0]
        assert results[1]["ok"]["vmas"] == []


# ── mprotect ────────────────────────────────────────────────────────


class TestMprotect:
    def test_mprotect_subrange_split(self):
        """Changing protection on a subrange splits the VMA."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 12288, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mprotect", "addr": 8192, "len": 4096, "prot": "r--"},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[2]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-"),
            vma(8192, 12288, "r--"),
            vma(12288, 16384, "rw-"),
        ]

    def test_mprotect_merge_back(self):
        """Restoring original protection re-merges all three pieces."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 12288, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mprotect", "addr": 8192, "len": 4096, "prot": "r--"},
            {"op": "mprotect", "addr": 8192, "len": 4096, "prot": "rw-"},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        assert results[3]["ok"]["vmas"] == [vma(4096, 16384, "rw-")]

    def test_mprotect_unmapped_error(self):
        """mprotect on a range with an unmapped gap returns error."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 12288, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mprotect", "addr": 4096, "len": 12288, "prot": "r--"},
        ]
        results = run_ops(ops)
        assert "error" in results[2]
        assert results[2]["error"] == "not_mapped"

    def test_mprotect_spanning_multiple(self):
        """mprotect across multiple VMAs unifies protection and merges."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 8192, "len": 4096, "prot": "r--",
             "map_type": "private", "fixed": True},
            {"op": "mmap", "addr": 12288, "len": 4096, "prot": "rwx",
             "map_type": "private", "fixed": True},
            {"op": "mprotect", "addr": 4096, "len": 12288, "prot": "r-x"},
            {"op": "dump"},
        ]
        results = run_ops(ops)
        # All three VMAs become r-x/private and merge into one
        assert results[4]["ok"]["vmas"] == [vma(4096, 16384, "r-x")]


# ── Error handling ──────────────────────────────────────────────────


class TestErrors:
    def test_mmap_misaligned_addr(self):
        """MAP_FIXED with non-page-aligned address errors."""
        ops = [
            {"op": "mmap", "addr": 4097, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},
        ]
        results = run_ops(ops)
        assert "error" in results[0]

    def test_mmap_zero_length(self):
        """mmap with len=0 errors."""
        ops = [
            {"op": "mmap", "addr": None, "len": 0, "prot": "rw-",
             "map_type": "private", "fixed": False},
        ]
        results = run_ops(ops)
        assert "error" in results[0]

    def test_munmap_misaligned(self):
        """munmap with non-page-aligned address errors."""
        ops = [
            {"op": "munmap", "addr": 4097, "len": 4096},
        ]
        results = run_ops(ops)
        assert "error" in results[0]

    def test_mprotect_misaligned_len(self):
        """mprotect with non-page-aligned length errors."""
        ops = [
            {"op": "mmap", "addr": 4096, "len": 8192, "prot": "rw-",
             "map_type": "private", "fixed": True},
            {"op": "mprotect", "addr": 4096, "len": 100, "prot": "r--"},
        ]
        results = run_ops(ops)
        assert "error" in results[1]


# ── Complex integration ────────────────────────────────────────────


class TestComplex:
    def test_interleaved_operations(self):
        """Complex scenario: hole-punch, mprotect split, gap fill, cascade merge."""
        ops = [
            # Phase 1: Build address space via non-fixed mmap
            {"op": "mmap", "addr": None, "len": 16384, "prot": "rw-",
             "map_type": "private", "fixed": False},                     # 0
            {"op": "mmap", "addr": None, "len": 8192, "prot": "r-x",
             "map_type": "private", "fixed": False},                     # 1
            {"op": "mmap", "addr": None, "len": 4096, "prot": "rw-",
             "map_type": "shared", "fixed": False},                      # 2

            # Phase 2: Punch hole in first region
            {"op": "munmap", "addr": 8192, "len": 4096},                # 3
            {"op": "dump"},                                               # 4

            # Phase 3: mprotect fragment
            {"op": "mprotect", "addr": 12288, "len": 4096, "prot": "r-x"},  # 5
            {"op": "dump"},                                               # 6

            # Phase 4: Fill hole via MAP_FIXED, trigger merge
            {"op": "mmap", "addr": 8192, "len": 4096, "prot": "rw-",
             "map_type": "private", "fixed": True},                       # 7
            {"op": "dump"},                                               # 8

            # Phase 5: Wide mprotect triggers cascade merge
            {"op": "mprotect", "addr": 12288, "len": 16384, "prot": "rw-"},  # 9
            {"op": "dump"},                                               # 10

            # Phase 6: Verify via query
            {"op": "query", "addr": 20480},                              # 11
            {"op": "query", "addr": 28672},                              # 12
        ]
        results = run_ops(ops)

        # Phase 1: addresses
        assert results[0]["ok"]["addr"] == 4096     # [4096, 20480)
        assert results[1]["ok"]["addr"] == 20480    # [20480, 28672)
        assert results[2]["ok"]["addr"] == 28672    # [28672, 32768)

        # Phase 2: after hole-punch at [8192,12288)
        assert results[4]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-", "private"),
            vma(12288, 20480, "rw-", "private"),
            vma(20480, 28672, "r-x", "private"),
            vma(28672, 32768, "rw-", "shared"),
        ]

        # Phase 3: mprotect [12288,16384) to r-x splits [12288,20480)
        assert results[6]["ok"]["vmas"] == [
            vma(4096, 8192, "rw-", "private"),
            vma(12288, 16384, "r-x", "private"),
            vma(16384, 20480, "rw-", "private"),
            vma(20480, 28672, "r-x", "private"),
            vma(28672, 32768, "rw-", "shared"),
        ]

        # Phase 4: fill hole merges [4096,8192)+[8192,12288) → [4096,12288)
        assert results[8]["ok"]["vmas"] == [
            vma(4096, 12288, "rw-", "private"),
            vma(12288, 16384, "r-x", "private"),
            vma(16384, 20480, "rw-", "private"),
            vma(20480, 28672, "r-x", "private"),
            vma(28672, 32768, "rw-", "shared"),
        ]

        # Phase 5: mprotect [12288,28672) to rw- → cascade merge
        assert results[10]["ok"]["vmas"] == [
            vma(4096, 28672, "rw-", "private"),
            vma(28672, 32768, "rw-", "shared"),
        ]

        # Phase 6: queries
        assert results[11]["ok"]["vma"] == vma(4096, 28672, "rw-", "private")
        assert results[12]["ok"]["vma"] == vma(28672, 32768, "rw-", "shared")
