import subprocess
import shutil
import os
import pytest



def run_go_test(test_name=None):
    """Copy Go test file to /app/ and run go test."""
    shutil.copy("/tests/mvcc_test.go", "/app/mvcc_test.go")
    try:
        cmd = ["go", "test", "-v", "-count=1", "-timeout=60s"]
        if test_name:
            cmd.extend(["-run", test_name])
        result = subprocess.run(
            cmd,
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result
    finally:
        if os.path.exists("/app/mvcc_test.go"):
            os.remove("/app/mvcc_test.go")


def test_read_uncommitted():
    result = run_go_test("TestReadUncommitted")
    assert result.returncode == 0, f"TestReadUncommitted failed:\n{result.stdout}\n{result.stderr}"


def test_read_committed_basic():
    result = run_go_test("TestReadCommittedBasic")
    assert result.returncode == 0, f"TestReadCommittedBasic failed:\n{result.stdout}\n{result.stderr}"


def test_read_committed_aborted_delete():
    result = run_go_test("TestReadCommittedAbortedDelete")
    assert result.returncode == 0, f"TestReadCommittedAbortedDelete failed:\n{result.stdout}\n{result.stderr}"


def test_read_committed_inprogress_delete():
    result = run_go_test("TestReadCommittedInProgressDelete")
    assert result.returncode == 0, f"TestReadCommittedInProgressDelete failed:\n{result.stdout}\n{result.stderr}"


def test_repeatable_read_basic():
    result = run_go_test("TestRepeatableReadBasic")
    assert result.returncode == 0, f"TestRepeatableReadBasic failed:\n{result.stdout}\n{result.stderr}"


def test_repeatable_read_concurrent_delete():
    result = run_go_test("TestRepeatableReadConcurrentDelete")
    assert result.returncode == 0, f"TestRepeatableReadConcurrentDelete failed:\n{result.stdout}\n{result.stderr}"


def test_repeatable_read_concurrent_update():
    result = run_go_test("TestRepeatableReadConcurrentUpdate")
    assert result.returncode == 0, f"TestRepeatableReadConcurrentUpdate failed:\n{result.stdout}\n{result.stderr}"


def test_snapshot_isolation_write_write_conflict():
    result = run_go_test("TestSnapshotIsolationWriteWriteConflict")
    assert result.returncode == 0, f"TestSnapshotIsolationWriteWriteConflict failed:\n{result.stdout}\n{result.stderr}"


def test_serializable_read_write_conflict():
    result = run_go_test("TestSerializableReadWriteConflict")
    assert result.returncode == 0, f"TestSerializableReadWriteConflict failed:\n{result.stdout}\n{result.stderr}"


def test_serializable_write_read_conflict():
    result = run_go_test("TestSerializableWriteReadConflict")
    assert result.returncode == 0, f"TestSerializableWriteReadConflict failed:\n{result.stdout}\n{result.stderr}"


def test_vacuum_basic():
    result = run_go_test("TestVacuumBasic")
    assert result.returncode == 0, f"TestVacuumBasic failed:\n{result.stdout}\n{result.stderr}"


def test_vacuum_preserves_active_transactions():
    result = run_go_test("TestVacuumPreservesActiveTransactionVersions")
    assert result.returncode == 0, f"TestVacuumPreservesActiveTransactionVersions failed:\n{result.stdout}\n{result.stderr}"


def test_vacuum_cleans_aborted():
    result = run_go_test("TestVacuumCleansAbortedVersions")
    assert result.returncode == 0, f"TestVacuumCleansAbortedVersions failed:\n{result.stdout}\n{result.stderr}"


def test_vacuum_deleted_key():
    result = run_go_test("TestVacuumDeletedKey")
    assert result.returncode == 0, f"TestVacuumDeletedKey failed:\n{result.stdout}\n{result.stderr}"


def test_all_tests_pass():
    """Run all Go tests at once to verify no cross-test interference."""
    result = run_go_test()
    assert result.returncode == 0, f"Some tests failed:\n{result.stdout}\n{result.stderr}"
