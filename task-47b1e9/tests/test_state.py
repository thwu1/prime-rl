"""

Tests for the crash-safe free list KV store implementation.
Verifies: compilation, basic KV ops, free list page recycling,
data integrity, persistence across close/reopen, I/O protocol
report, and xxd meta page report.
"""

import os
import re
import subprocess
import textwrap
import pytest

APP_DIR = "/app"
TEST_FILE = os.path.join(APP_DIR, "kv_test.go")

GO_TEST_CODE = textwrap.dedent(r'''
package main

import (
    "fmt"
    "os"
    "path/filepath"
    "testing"
)

func TestBasicOperations(t *testing.T) {
    dir := t.TempDir()
    db := &KV{Path: filepath.Join(dir, "test.db")}
    if err := db.Open(); err != nil {
        t.Fatal(err)
    }
    defer db.Close()

    // Insert
    if err := db.Set([]byte("hello"), []byte("world")); err != nil {
        t.Fatal(err)
    }
    val, ok := db.Get([]byte("hello"))
    if !ok || string(val) != "world" {
        t.Fatalf("expected world, got %q (ok=%v)", string(val), ok)
    }

    // Update
    if err := db.Set([]byte("hello"), []byte("updated")); err != nil {
        t.Fatal(err)
    }
    val, ok = db.Get([]byte("hello"))
    if !ok || string(val) != "updated" {
        t.Fatalf("expected updated, got %q", string(val))
    }

    // Delete
    deleted, err := db.Del([]byte("hello"))
    if err != nil || !deleted {
        t.Fatalf("delete failed: err=%v, deleted=%v", err, deleted)
    }
    _, ok = db.Get([]byte("hello"))
    if ok {
        t.Fatal("key should not exist after delete")
    }

    // Delete non-existent
    deleted, err = db.Del([]byte("nonexistent"))
    if err != nil || deleted {
        t.Fatalf("expected not-deleted: err=%v, deleted=%v", err, deleted)
    }
}

func TestFreeListRecycling(t *testing.T) {
    dir := t.TempDir()
    dbPath := filepath.Join(dir, "test.db")
    db := &KV{Path: dbPath}
    if err := db.Open(); err != nil {
        t.Fatal(err)
    }
    defer db.Close()

    N := 500

    // Phase 1: insert N keys
    for i := 0; i < N; i++ {
        key := fmt.Sprintf("key-%06d", i)
        val := fmt.Sprintf("value-%06d", i)
        if err := db.Set([]byte(key), []byte(val)); err != nil {
            t.Fatalf("phase1 insert %d: %v", i, err)
        }
    }

    info1, err := os.Stat(dbPath)
    if err != nil {
        t.Fatal(err)
    }
    size1 := info1.Size()
    t.Logf("After inserting %d keys: %d bytes", N, size1)

    // Phase 2: delete all N keys
    for i := 0; i < N; i++ {
        key := fmt.Sprintf("key-%06d", i)
        if _, err := db.Del([]byte(key)); err != nil {
            t.Fatalf("phase2 delete %d: %v", i, err)
        }
    }

    // Phase 3: insert N new keys
    for i := N; i < 2*N; i++ {
        key := fmt.Sprintf("key-%06d", i)
        val := fmt.Sprintf("value-%06d", i)
        if err := db.Set([]byte(key), []byte(val)); err != nil {
            t.Fatalf("phase3 insert %d: %v", i, err)
        }
    }

    info3, err := os.Stat(dbPath)
    if err != nil {
        t.Fatal(err)
    }
    size3 := info3.Size()
    t.Logf("After delete+reinsert: %d bytes", size3)

    ratio := float64(size3) / float64(size1)
    t.Logf("Size ratio: %.2f", ratio)

    if ratio > 2.0 {
        t.Fatalf("file grew too much (ratio=%.2f > 2.0); free list is not recycling pages", ratio)
    }

    // Verify data integrity of new keys
    for i := N; i < 2*N; i++ {
        key := fmt.Sprintf("key-%06d", i)
        val, ok := db.Get([]byte(key))
        expected := fmt.Sprintf("value-%06d", i)
        if !ok || string(val) != expected {
            t.Fatalf("get %s: expected %q, got %q (ok=%v)", key, expected, string(val), ok)
        }
    }

    // Old keys must not exist
    for i := 0; i < N; i++ {
        key := fmt.Sprintf("key-%06d", i)
        if _, ok := db.Get([]byte(key)); ok {
            t.Fatalf("%s should not exist", key)
        }
    }
}

func TestPersistence(t *testing.T) {
    dir := t.TempDir()
    dbPath := filepath.Join(dir, "test.db")

    // Write data
    db := &KV{Path: dbPath}
    if err := db.Open(); err != nil {
        t.Fatal(err)
    }
    for i := 0; i < 100; i++ {
        key := fmt.Sprintf("persist-%04d", i)
        val := fmt.Sprintf("data-%04d", i)
        if err := db.Set([]byte(key), []byte(val)); err != nil {
            t.Fatal(err)
        }
    }
    db.Close()

    // Reopen and verify
    db2 := &KV{Path: dbPath}
    if err := db2.Open(); err != nil {
        t.Fatal(err)
    }
    for i := 0; i < 100; i++ {
        key := fmt.Sprintf("persist-%04d", i)
        val, ok := db2.Get([]byte(key))
        expected := fmt.Sprintf("data-%04d", i)
        if !ok || string(val) != expected {
            t.Fatalf("after reopen: get %s: expected %q, got %q", key, expected, string(val))
        }
    }

    // Delete some keys, close, reopen, verify
    for i := 0; i < 50; i++ {
        key := fmt.Sprintf("persist-%04d", i)
        if _, err := db2.Del([]byte(key)); err != nil {
            t.Fatal(err)
        }
    }
    db2.Close()

    db3 := &KV{Path: dbPath}
    if err := db3.Open(); err != nil {
        t.Fatal(err)
    }
    defer db3.Close()
    for i := 0; i < 50; i++ {
        key := fmt.Sprintf("persist-%04d", i)
        if _, ok := db3.Get([]byte(key)); ok {
            t.Fatalf("after reopen: %s should not exist", key)
        }
    }
    for i := 50; i < 100; i++ {
        key := fmt.Sprintf("persist-%04d", i)
        val, ok := db3.Get([]byte(key))
        expected := fmt.Sprintf("data-%04d", i)
        if !ok || string(val) != expected {
            t.Fatalf("after reopen: get %s: expected %q, got %q", key, expected, string(val))
        }
    }
}

func TestMultipleCycles(t *testing.T) {
    dir := t.TempDir()
    dbPath := filepath.Join(dir, "test.db")
    db := &KV{Path: dbPath}
    if err := db.Open(); err != nil {
        t.Fatal(err)
    }
    defer db.Close()

    // Run 3 cycles of insert-all / delete-all to stress the free list
    N := 200
    for cycle := 0; cycle < 3; cycle++ {
        base := cycle * N
        for i := 0; i < N; i++ {
            key := fmt.Sprintf("c%d-%06d", cycle, i)
            val := fmt.Sprintf("val-%d-%06d", cycle, i)
            if err := db.Set([]byte(key), []byte(val)); err != nil {
                t.Fatalf("cycle %d insert %d: %v", cycle, i, err)
            }
        }
        // Verify all current-cycle keys
        for i := 0; i < N; i++ {
            key := fmt.Sprintf("c%d-%06d", cycle, i)
            expected := fmt.Sprintf("val-%d-%06d", cycle, i)
            val, ok := db.Get([]byte(key))
            if !ok || string(val) != expected {
                t.Fatalf("cycle %d verify %d: expected %q, got %q", cycle, i, expected, string(val))
            }
        }
        // Delete all current-cycle keys
        for i := 0; i < N; i++ {
            key := fmt.Sprintf("c%d-%06d", cycle, i)
            deleted, err := db.Del([]byte(key))
            if err != nil {
                t.Fatalf("cycle %d delete %d: %v", cycle, i, err)
            }
            if !deleted {
                t.Fatalf("cycle %d delete %d: key not found", cycle, i)
            }
        }
        _ = base
    }

    // After 3 cycles, file size should be bounded
    info, _ := os.Stat(dbPath)
    t.Logf("After 3 insert/delete cycles of %d keys: %d bytes", N, info.Size())

    // Insert one final batch and verify
    for i := 0; i < N; i++ {
        key := fmt.Sprintf("final-%06d", i)
        val := fmt.Sprintf("finalval-%06d", i)
        if err := db.Set([]byte(key), []byte(val)); err != nil {
            t.Fatalf("final insert %d: %v", i, err)
        }
    }
    for i := 0; i < N; i++ {
        key := fmt.Sprintf("final-%06d", i)
        expected := fmt.Sprintf("finalval-%06d", i)
        val, ok := db.Get([]byte(key))
        if !ok || string(val) != expected {
            t.Fatalf("final verify %d: expected %q, got %q", i, expected, string(val))
        }
    }
}
''')


@pytest.fixture(autouse=True)
def setup_go_test():
    """Write the Go test file before tests and clean up after."""
    with open(TEST_FILE, "w") as f:
        f.write(GO_TEST_CODE)
    yield
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)


def run_go_test(test_name, timeout=120):
    """Run a specific Go test and return the result."""
    result = subprocess.run(
        ["go", "test", "-v", "-count=1", "-timeout", f"{timeout}s",
         "-run", test_name, "."],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=timeout + 30,
    )
    return result


def test_compilation():
    """The Go code must compile without errors."""
    result = subprocess.run(
        ["go", "build", "-o", "/dev/null", "."],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Compilation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_basic_operations():
    """Basic insert, get, update, delete must work."""
    result = run_go_test("TestBasicOperations")
    assert result.returncode == 0, (
        f"TestBasicOperations failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_freelist_recycling():
    """After insert/delete/reinsert, file size must be bounded (free list working)."""
    result = run_go_test("TestFreeListRecycling", timeout=180)
    assert result.returncode == 0, (
        f"TestFreeListRecycling failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_persistence():
    """Data must survive close/reopen cycles."""
    result = run_go_test("TestPersistence")
    assert result.returncode == 0, (
        f"TestPersistence failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_multiple_cycles():
    """Free list must handle multiple insert/delete cycles correctly."""
    result = run_go_test("TestMultipleCycles", timeout=180)
    assert result.returncode == 0, (
        f"TestMultipleCycles failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_io_protocol_report():
    """I/O protocol report must exist and demonstrate two-phase update protocol."""
    report_path = "/app/io_protocol_report.txt"
    assert os.path.exists(report_path), (
        "io_protocol_report.txt not found at /app/ — "
        "instrument file I/O operations and produce the report"
    )
    with open(report_path) as f:
        content = f.read()
    assert len(content) > 100, "io_protocol_report.txt is too short to contain meaningful analysis"
    # Must reference fsync/sync operations
    assert re.search(r'fsync|sync', content, re.IGNORECASE), (
        "I/O protocol report must reference fsync/sync operations"
    )
    # Must reference write operations
    assert re.search(r'write', content, re.IGNORECASE), (
        "I/O protocol report must reference write operations"
    )
    # Must contain analysis annotations about the update protocol
    assert re.search(
        r'phase|two.phase|protocol|meta.?page|data.?page',
        content, re.IGNORECASE
    ), (
        "I/O protocol report must contain annotations analyzing the "
        "two-phase update protocol (e.g., data page vs meta page writes)"
    )


def test_meta_page_report():
    """Meta page hex dump report must exist with annotated fields."""
    report_path = "/app/meta_page_report.txt"
    assert os.path.exists(report_path), (
        "meta_page_report.txt not found at /app/ — "
        "use xxd to hex-dump the meta page and annotate it"
    )
    with open(report_path) as f:
        content = f.read()
    assert len(content) > 100, "meta_page_report.txt is too short to contain meaningful analysis"
    # Must contain hex dump content (xxd-style: hex address followed by hex bytes)
    assert re.search(r'[0-9a-fA-F]{6,8}:?\s+[0-9a-fA-F]{2}', content), (
        "meta page report must contain hex dump output (xxd format)"
    )
    # Must annotate the signature field
    assert re.search(r'sig(nature)?', content, re.IGNORECASE), (
        "meta page report must annotate the database signature field"
    )
    # Must annotate the root pointer
    assert re.search(r'root', content, re.IGNORECASE), (
        "meta page report must annotate the root pointer field"
    )
    # Must include byte offset or range annotations
    assert re.search(r'byte|offset|\d+\s*[-:]\s*\d+', content, re.IGNORECASE), (
        "meta page report must include byte offset/range information for fields"
    )
