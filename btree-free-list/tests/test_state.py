
import os
import subprocess
import pytest

KVTOOL = "/app/kvtool"


@pytest.fixture(scope="session", autouse=True)
def build_binary():
    """Build the Go binary once before all tests."""
    result = subprocess.run(
        ["go", "build", "-o", KVTOOL, "."],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"


@pytest.fixture
def db_path(tmp_path):
    """Provide a unique database path for each test."""
    return str(tmp_path / "test.db")


def kv_run(db_path, *args):
    """Run kvtool with a single command."""
    result = subprocess.run(
        [KVTOOL, db_path] + list(args),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip(), result.returncode


def kv_batch(db_path, commands):
    """Run kvtool in batch mode with multiple commands via stdin."""
    input_text = "\n".join(commands) + "\n"
    result = subprocess.run(
        [KVTOOL, db_path],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=120,
    )
    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return lines, result.returncode


def test_basic_set_get(db_path):
    """Set a key and get it back across process restarts."""
    kv_run(db_path, "set", "hello", "world")
    out, rc = kv_run(db_path, "get", "hello")
    assert rc == 0
    assert out == "world"


def test_basic_delete(db_path):
    """Delete a key and verify it is gone."""
    kv_run(db_path, "set", "foo", "bar")
    out, _ = kv_run(db_path, "del", "foo")
    assert out == "DELETED"
    out, _ = kv_run(db_path, "get", "foo")
    assert out == "NOT_FOUND"


def test_delete_nonexistent(db_path):
    """Deleting a nonexistent key returns NOT_FOUND."""
    out, _ = kv_run(db_path, "del", "nosuchkey")
    assert out == "NOT_FOUND"


def test_update_value(db_path):
    """Updating an existing key replaces the value."""
    kv_run(db_path, "set", "key", "val1")
    kv_run(db_path, "set", "key", "val2")
    out, _ = kv_run(db_path, "get", "key")
    assert out == "val2"


def test_batch_persistence(db_path):
    """Batch-inserted data persists across process restarts."""
    cmds = [f"set key{i:04d} value{i}" for i in range(50)]
    kv_batch(db_path, cmds)

    # Verify each key in a separate process invocation
    for i in range(50):
        out, _ = kv_run(db_path, "get", f"key{i:04d}")
        assert out == f"value{i}", f"key{i:04d} lost after restart"


def test_delete_persistence(db_path):
    """Deletions survive across process restarts."""
    kv_batch(db_path, [
        "set alpha bravo",
        "set charlie delta",
        "del alpha",
    ])
    out, _ = kv_run(db_path, "get", "alpha")
    assert out == "NOT_FOUND"
    out, _ = kv_run(db_path, "get", "charlie")
    assert out == "delta"


def test_scan_sorted(db_path):
    """Scan returns all keys in sorted order."""
    kv_batch(db_path, [
        "set cherry 3",
        "set apple 1",
        "set banana 2",
    ])
    out, _ = kv_run(db_path, "scan")
    lines = out.strip().split("\n")
    assert lines == ["apple=1", "banana=2", "cherry=3"]


def test_space_reclamation(db_path):
    """Deleted pages must be reclaimed so the file doesn't grow unboundedly.

    Without reclamation, the file would be ~3x larger after delete+reinsert.
    With reclamation, it should be roughly the same size (< 1.5x).
    """
    # Phase 1: Insert 200 keys
    cmds = [f"set k{i:04d} {'x' * 100}" for i in range(200)]
    kv_batch(db_path, cmds)
    size_after_insert = os.path.getsize(db_path)

    # Phase 2: Delete all 200 keys
    cmds = [f"del k{i:04d}" for i in range(200)]
    kv_batch(db_path, cmds)

    # Phase 3: Re-insert 200 different keys
    cmds = [f"set n{i:04d} {'y' * 100}" for i in range(200)]
    kv_batch(db_path, cmds)
    size_after_reinsert = os.path.getsize(db_path)

    ratio = size_after_reinsert / size_after_insert
    assert ratio < 1.5, (
        f"File grew from {size_after_insert} to {size_after_reinsert} "
        f"({ratio:.2f}x). Reclamation should keep growth under 1.5x."
    )


def test_bounded_growth_cycles(db_path):
    """Multiple insert/delete cycles should not cause unbounded file growth."""
    for cycle in range(5):
        cmds = [f"set c{cycle}k{i:03d} {'v' * 50}" for i in range(100)]
        kv_batch(db_path, cmds)
        cmds = [f"del c{cycle}k{i:03d}" for i in range(100)]
        kv_batch(db_path, cmds)

    final_size = os.path.getsize(db_path)
    max_expected = 2 * 1024 * 1024  # 2MB
    assert final_size < max_expected, (
        f"File size {final_size} exceeds {max_expected} after 5 insert/delete cycles. "
        f"Orphaned pages should be reclaimed."
    )


def test_mixed_operations_correctness(db_path):
    """Data integrity after mixed insert/delete/update operations."""
    expected = {}

    # Insert 100 keys
    cmds = []
    for i in range(100):
        key = f"m{i:04d}"
        val = f"val{i}"
        cmds.append(f"set {key} {val}")
        expected[key] = val
    kv_batch(db_path, cmds)

    # Delete even-indexed keys
    cmds = []
    for i in range(0, 100, 2):
        key = f"m{i:04d}"
        cmds.append(f"del {key}")
        del expected[key]
    kv_batch(db_path, cmds)

    # Update remaining (odd-indexed) keys
    cmds = []
    for i in range(1, 100, 2):
        key = f"m{i:04d}"
        val = f"updated{i}"
        cmds.append(f"set {key} {val}")
        expected[key] = val
    kv_batch(db_path, cmds)

    # Verify expected keys exist with correct values (in new process)
    for key, val in expected.items():
        out, _ = kv_run(db_path, "get", key)
        assert out == val, f"Expected {key}={val}, got {out}"

    # Verify deleted keys are gone
    for i in range(0, 100, 2):
        key = f"m{i:04d}"
        out, _ = kv_run(db_path, "get", key)
        assert out == "NOT_FOUND", f"Key {key} should be deleted"


def test_update_bounded_growth(db_path):
    """Updating existing keys repeatedly must not cause unbounded file growth.

    Each update replaces B+tree nodes; without reclamation the file grows
    proportionally to the number of update cycles.
    """
    # Insert 100 keys
    cmds = [f"set u{i:04d} {'a' * 50}" for i in range(100)]
    kv_batch(db_path, cmds)
    size_after_insert = os.path.getsize(db_path)

    # Update all 100 keys 10 times with different values
    for cycle in range(10):
        val_char = chr(ord("b") + cycle)
        cmds = [f"set u{i:04d} {val_char * 50}" for i in range(100)]
        kv_batch(db_path, cmds)

    size_after_updates = os.path.getsize(db_path)

    ratio = size_after_updates / size_after_insert
    assert ratio < 2.0, (
        f"File grew from {size_after_insert} to {size_after_updates} "
        f"({ratio:.2f}x) after 10 update cycles. "
        f"Replaced B+tree pages should be reclaimed."
    )

    # Verify data correctness — last cycle value
    expected_char = chr(ord("b") + 9)
    for i in range(100):
        out, _ = kv_run(db_path, "get", f"u{i:04d}")
        assert out == expected_char * 50, f"u{i:04d} has wrong value after updates"


def test_reclamation_survives_restart(db_path):
    """Reclamation metadata must persist so freed space is reused after restart."""
    # Insert 100 keys
    cmds = [f"set p{i:04d} {'z' * 80}" for i in range(100)]
    kv_batch(db_path, cmds)
    size_with_100_keys = os.path.getsize(db_path)

    # Delete all 100 keys (populates reclamation structures)
    cmds = [f"del p{i:04d}" for i in range(100)]
    kv_batch(db_path, cmds)

    # In a new process, insert 50 new keys — they should reuse freed space
    cmds = [f"set q{i:04d} {'w' * 80}" for i in range(50)]
    kv_batch(db_path, cmds)
    size_after_reinsert = os.path.getsize(db_path)

    # With 50 keys (half the original), the file should not exceed the
    # size it was with 100 keys, allowing modest overhead
    assert size_after_reinsert <= size_with_100_keys * 1.2, (
        f"File size {size_after_reinsert} exceeds expected bound "
        f"({size_with_100_keys * 1.2:.0f}) after restart+reinsert. "
        f"Reclamation metadata may not persist across restarts."
    )

    # Verify the new keys are correct
    for i in range(50):
        out, _ = kv_run(db_path, "get", f"q{i:04d}")
        assert out == "w" * 80, f"q{i:04d} not found or wrong value after restart"
