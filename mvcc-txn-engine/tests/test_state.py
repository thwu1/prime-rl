"""
Tests for Persistent MVCC Key-Value Store with Socket Interface.
"""


import json
import os
import shutil
import socket as sock_mod
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, "/app")

import pytest
from mvcc_store import MVCCStore, Transaction, Watermark, CompactionFilter, ConflictError


class _DBTestBase:
    """Mixin providing a fresh temporary database path per test."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmpdir, "test.db")

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestBasicOperations(_DBTestBase):

    def test_basic_put_get(self):
        store = MVCCStore(self.db_path)
        txn = store.new_txn()
        txn.put("key1", "value1")
        assert txn.get("key1") == "value1"
        txn.commit()

        txn2 = store.new_txn()
        assert txn2.get("key1") == "value1"
        txn2.rollback()
        store.close()

    def test_delete(self):
        store = MVCCStore(self.db_path)

        txn1 = store.new_txn()
        txn1.put("key", "value")
        txn1.commit()

        snap = store.new_txn()

        txn2 = store.new_txn()
        txn2.delete("key")
        txn2.commit()

        assert snap.get("key") == "value"
        snap.rollback()

        txn3 = store.new_txn()
        assert txn3.get("key") is None
        txn3.rollback()
        store.close()

    def test_nonexistent_key(self):
        store = MVCCStore(self.db_path)
        txn = store.new_txn()
        assert txn.get("missing") is None
        txn.rollback()
        store.close()


class TestSnapshotIsolation(_DBTestBase):

    def test_snapshot_isolation(self):
        store = MVCCStore(self.db_path)

        txn_init = store.new_txn()
        txn_init.put("key1", "v1")
        txn_init.put("key2", "v2")
        txn_init.commit()

        txn1 = store.new_txn()

        txn2 = store.new_txn()
        txn2.put("key1", "v1_updated")
        txn2.commit()

        assert txn1.get("key1") == "v1"
        assert txn1.get("key2") == "v2"
        txn1.rollback()

        txn3 = store.new_txn()
        assert txn3.get("key1") == "v1_updated"
        txn3.rollback()
        store.close()

    def test_multiple_versions(self):
        store = MVCCStore(self.db_path)

        txn1 = store.new_txn()
        txn1.put("key", "v1")
        txn1.commit()

        snap1 = store.new_txn()

        txn2 = store.new_txn()
        txn2.put("key", "v2")
        txn2.commit()

        snap2 = store.new_txn()

        txn3 = store.new_txn()
        txn3.put("key", "v3")
        txn3.commit()

        snap3 = store.new_txn()

        assert snap1.get("key") == "v1"
        assert snap2.get("key") == "v2"
        assert snap3.get("key") == "v3"

        snap1.rollback()
        snap2.rollback()
        snap3.rollback()
        store.close()


class TestLocalWorkspace(_DBTestBase):

    def test_local_workspace(self):
        store = MVCCStore(self.db_path)

        txn1 = store.new_txn()
        txn1.put("key1", "val1")

        txn2 = store.new_txn()
        assert txn2.get("key1") is None
        txn2.rollback()

        assert txn1.get("key1") == "val1"
        txn1.commit()

        txn3 = store.new_txn()
        assert txn3.get("key1") == "val1"

        txn3.delete("key1")
        assert txn3.get("key1") is None
        txn3.rollback()

        txn4 = store.new_txn()
        assert txn4.get("key1") == "val1"
        txn4.rollback()
        store.close()


class TestScan(_DBTestBase):

    def test_scan_basic(self):
        store = MVCCStore(self.db_path)

        txn1 = store.new_txn()
        txn1.put("a", "1")
        txn1.put("b", "2")
        txn1.put("c", "3")
        txn1.put("d", "4")
        txn1.commit()

        txn2 = store.new_txn()
        results = txn2.scan("b", "d")
        assert results == [("b", "2"), ("c", "3")]
        txn2.rollback()
        store.close()

    def test_scan_versions(self):
        store = MVCCStore(self.db_path)

        txn1 = store.new_txn()
        txn1.put("a", "v1")
        txn1.put("b", "v1")
        txn1.put("c", "v1")
        txn1.commit()

        snap = store.new_txn()

        txn2 = store.new_txn()
        txn2.put("b", "v2")
        txn2.delete("c")
        txn2.commit()

        results = snap.scan("a", "z")
        assert results == [("a", "v1"), ("b", "v1"), ("c", "v1")]
        snap.rollback()

        txn3 = store.new_txn()
        results = txn3.scan("a", "z")
        assert results == [("a", "v1"), ("b", "v2")]
        txn3.rollback()
        store.close()

    def test_scan_local_workspace(self):
        store = MVCCStore(self.db_path)

        txn_init = store.new_txn()
        txn_init.put("a", "1")
        txn_init.put("b", "2")
        txn_init.put("c", "3")
        txn_init.commit()

        txn = store.new_txn()
        txn.put("b", "updated")
        txn.delete("c")
        txn.put("bb", "new")

        results = txn.scan("a", "d")
        assert results == [("a", "1"), ("b", "updated"), ("bb", "new")]
        txn.rollback()
        store.close()


class TestSSI(_DBTestBase):

    def test_write_skew_detection(self):
        store = MVCCStore(self.db_path, serializable=True)

        txn_init = store.new_txn()
        txn_init.put("key1", "1")
        txn_init.put("key2", "2")
        txn_init.commit()

        txn1 = store.new_txn()
        val2 = txn1.get("key2")
        txn1.put("key1", val2)

        txn2 = store.new_txn()
        val1 = txn2.get("key1")
        txn2.put("key2", val1)

        txn1.commit()

        with pytest.raises(ConflictError):
            txn2.commit()
        store.close()

    def test_no_false_conflict(self):
        store = MVCCStore(self.db_path, serializable=True)

        txn_init = store.new_txn()
        txn_init.put("key1", "1")
        txn_init.put("key2", "2")
        txn_init.commit()

        txn1 = store.new_txn()
        txn1.get("key1")
        txn1.put("key1", "updated1")

        txn2 = store.new_txn()
        txn2.get("key2")
        txn2.put("key2", "updated2")

        txn1.commit()
        txn2.commit()

        txn3 = store.new_txn()
        assert txn3.get("key1") == "updated1"
        assert txn3.get("key2") == "updated2"
        txn3.rollback()
        store.close()

    def test_read_only_txn(self):
        store = MVCCStore(self.db_path, serializable=True)

        txn1 = store.new_txn()
        txn1.put("key", "value")
        txn1.commit()

        txn_w = store.new_txn()
        txn_w.put("key", "new_value")

        txn_ro = store.new_txn()
        txn_ro.get("key")

        txn_w.commit()

        txn_ro.commit()
        store.close()

    def test_phantom_detection(self):
        store = MVCCStore(self.db_path, serializable=True)

        txn_init = store.new_txn()
        txn_init.put("a", "1")
        txn_init.put("c", "3")
        txn_init.commit()

        txn1 = store.new_txn()
        results = txn1.scan("a", "d")
        assert results == [("a", "1"), ("c", "3")]

        txn2 = store.new_txn()
        txn2.put("b", "2")
        txn2.commit()

        txn1.put("x", "val")

        with pytest.raises(ConflictError):
            txn1.commit()
        store.close()

    def test_non_serializable_allows_write_skew(self):
        store = MVCCStore(self.db_path, serializable=False)

        txn_init = store.new_txn()
        txn_init.put("key1", "1")
        txn_init.put("key2", "2")
        txn_init.commit()

        txn1 = store.new_txn()
        val2 = txn1.get("key2")
        txn1.put("key1", val2)

        txn2 = store.new_txn()
        val1 = txn2.get("key1")
        txn2.put("key2", val1)

        txn1.commit()
        txn2.commit()
        store.close()


class TestWatermark:

    def test_watermark(self):
        wm = Watermark()
        assert wm.watermark() is None

        wm.add_reader(5)
        assert wm.watermark() == 5

        wm.add_reader(3)
        assert wm.watermark() == 3

        wm.add_reader(7)
        assert wm.watermark() == 3

        wm.remove_reader(3)
        assert wm.watermark() == 5

        wm.add_reader(5)
        assert wm.watermark() == 5

        wm.remove_reader(5)
        assert wm.watermark() == 5

        wm.remove_reader(5)
        assert wm.watermark() == 7

        wm.remove_reader(7)
        assert wm.watermark() is None


class TestGarbageCollection(_DBTestBase):

    def test_gc_basic(self):
        store = MVCCStore(self.db_path)

        for i in range(1, 4):
            txn = store.new_txn()
            txn.put("key", f"v{i}")
            txn.commit()

        removed = store.gc()
        assert removed == 2

        txn = store.new_txn()
        assert txn.get("key") == "v3"
        txn.rollback()
        store.close()

    def test_gc_respects_watermark(self):
        store = MVCCStore(self.db_path)

        txn1 = store.new_txn()
        txn1.put("key", "v1")
        txn1.commit()

        snap = store.new_txn()

        txn2 = store.new_txn()
        txn2.put("key", "v2")
        txn2.commit()

        txn3 = store.new_txn()
        txn3.put("key", "v3")
        txn3.commit()

        removed = store.gc()
        assert removed == 0

        assert snap.get("key") == "v1"
        snap.rollback()

        removed = store.gc()
        assert removed == 2

        txn4 = store.new_txn()
        assert txn4.get("key") == "v3"
        txn4.rollback()
        store.close()

    def test_gc_tombstones(self):
        store = MVCCStore(self.db_path)

        txn1 = store.new_txn()
        txn1.put("key", "value")
        txn1.commit()

        txn2 = store.new_txn()
        txn2.delete("key")
        txn2.commit()

        removed = store.gc()
        assert removed == 2

        txn3 = store.new_txn()
        assert txn3.get("key") is None
        txn3.rollback()
        store.close()

    def test_compaction_filter(self):
        store = MVCCStore(self.db_path)

        class PrefixFilter(CompactionFilter):
            def __init__(self, prefix):
                self.prefix = prefix

            def filter(self, key):
                return key.startswith(self.prefix)

        txn1 = store.new_txn()
        txn1.put("tmp_data1", "val1")
        txn1.put("tmp_data2", "val2")
        txn1.put("perm_data1", "val3")
        txn1.commit()

        f = PrefixFilter("tmp_")
        store.add_compaction_filter(f)

        removed = store.gc()
        assert removed == 2

        txn2 = store.new_txn()
        assert txn2.get("tmp_data1") is None
        assert txn2.get("tmp_data2") is None
        assert txn2.get("perm_data1") == "val3"
        txn2.rollback()

        store.remove_compaction_filter(f)
        store.close()


class TestPersistence(_DBTestBase):
    """Verify data survives store close and reopen."""

    def test_persistence_across_restart(self):
        store = MVCCStore(self.db_path)
        txn = store.new_txn()
        txn.put("key1", "val1")
        txn.put("key2", "val2")
        txn.commit()
        store.close()

        store2 = MVCCStore(self.db_path)
        txn2 = store2.new_txn()
        assert txn2.get("key1") == "val1"
        assert txn2.get("key2") == "val2"
        txn2.rollback()
        store2.close()

    def test_delete_persists(self):
        store = MVCCStore(self.db_path)
        txn1 = store.new_txn()
        txn1.put("key", "val")
        txn1.commit()

        txn2 = store.new_txn()
        txn2.delete("key")
        txn2.commit()
        store.close()

        store2 = MVCCStore(self.db_path)
        txn3 = store2.new_txn()
        assert txn3.get("key") is None
        txn3.rollback()
        store2.close()

    def test_multiple_versions_persist(self):
        store = MVCCStore(self.db_path)
        for i in range(1, 4):
            txn = store.new_txn()
            txn.put("key", f"v{i}")
            txn.commit()
        store.close()

        store2 = MVCCStore(self.db_path)
        txn = store2.new_txn()
        assert txn.get("key") == "v3"
        txn.rollback()
        store2.close()

    def test_gc_persists(self):
        store = MVCCStore(self.db_path)
        for i in range(1, 5):
            txn = store.new_txn()
            txn.put("key", f"v{i}")
            txn.commit()

        removed = store.gc()
        assert removed == 3
        store.close()

        store2 = MVCCStore(self.db_path)
        txn = store2.new_txn()
        assert txn.get("key") == "v4"
        txn.rollback()
        store2.close()

    def test_serializable_state_across_restart(self):
        store = MVCCStore(self.db_path, serializable=True)
        txn_init = store.new_txn()
        txn_init.put("key1", "a")
        txn_init.put("key2", "b")
        txn_init.commit()

        txn1 = store.new_txn()
        txn1.get("key1")
        txn1.put("key1", "c")
        txn1.commit()
        store.close()

        store2 = MVCCStore(self.db_path, serializable=True)
        txn2 = store2.new_txn()
        assert txn2.get("key1") == "c"
        assert txn2.get("key2") == "b"
        txn2.rollback()
        store2.close()


class TestSQLiteInspection(_DBTestBase):
    """Verify the SQLite database is inspectable with CLI tools."""

    def test_versions_table_exists(self):
        store = MVCCStore(self.db_path)
        txn = store.new_txn()
        txn.put("key1", "val1")
        txn.commit()
        store.close()

        result = subprocess.run(
            ["sqlite3", self.db_path, ".tables"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "versions" in result.stdout

    def test_version_data_queryable(self):
        store = MVCCStore(self.db_path)

        txn1 = store.new_txn()
        txn1.put("alpha", "first")
        txn1.put("beta", "second")
        txn1.commit()

        txn2 = store.new_txn()
        txn2.put("alpha", "updated")
        txn2.commit()
        store.close()

        result = subprocess.run(
            ["sqlite3", self.db_path,
             "SELECT count(*) FROM versions WHERE key='alpha';"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "2"

    def test_gc_reflected_in_sqlite(self):
        store = MVCCStore(self.db_path)
        for i in range(1, 5):
            txn = store.new_txn()
            txn.put("key", f"v{i}")
            txn.commit()
        store.close()

        result = subprocess.run(
            ["sqlite3", self.db_path,
             "SELECT count(*) FROM versions WHERE key='key';"],
            capture_output=True, text=True
        )
        assert result.stdout.strip() == "4"

        store = MVCCStore(self.db_path)
        removed = store.gc()
        assert removed == 3
        store.close()

        result = subprocess.run(
            ["sqlite3", self.db_path,
             "SELECT count(*) FROM versions WHERE key='key';"],
            capture_output=True, text=True
        )
        assert result.stdout.strip() == "1"

    def test_json_inspection_with_jq(self):
        store = MVCCStore(self.db_path)
        txn1 = store.new_txn()
        txn1.put("alpha", "first")
        txn1.put("beta", "second")
        txn1.commit()

        txn2 = store.new_txn()
        txn2.put("alpha", "updated")
        txn2.commit()
        store.close()

        # Use sqlite3 -json output
        p1 = subprocess.run(
            ["sqlite3", "-json", self.db_path,
             "SELECT key, ts, value FROM versions ORDER BY key, ts;"],
            capture_output=True, text=True
        )
        assert p1.returncode == 0

        # Pipe through jq to count entries
        p2 = subprocess.run(
            ["jq", "length"],
            input=p1.stdout,
            capture_output=True, text=True
        )
        assert p2.returncode == 0
        assert p2.stdout.strip() == "3"

        # Use jq to filter by key
        p3 = subprocess.run(
            ["jq", '[.[] | select(.key == "alpha")] | length'],
            input=p1.stdout,
            capture_output=True, text=True
        )
        assert p3.returncode == 0
        assert p3.stdout.strip() == "2"

    def test_tombstone_visible_in_sqlite(self):
        store = MVCCStore(self.db_path)
        txn1 = store.new_txn()
        txn1.put("key", "val")
        txn1.commit()

        txn2 = store.new_txn()
        txn2.delete("key")
        txn2.commit()
        store.close()

        # The tombstone should show as NULL value in SQLite
        result = subprocess.run(
            ["sqlite3", self.db_path,
             "SELECT count(*) FROM versions WHERE key='key' AND value IS NULL;"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "1"

        # Total versions for key should be 2 (original + tombstone)
        result = subprocess.run(
            ["sqlite3", self.db_path,
             "SELECT count(*) FROM versions WHERE key='key';"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "2"


# ---------------------------------------------------------------------------
# Socket server tests
# ---------------------------------------------------------------------------

def _wait_for_socket(path, timeout=5):
    """Wait for a Unix domain socket to become connectable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            try:
                s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
                s.connect(path)
                s.close()
                return
            except (ConnectionRefusedError, OSError):
                pass
        time.sleep(0.1)
    raise RuntimeError(f"Server socket {path} not ready after {timeout}s")


class _ServerTestBase(_DBTestBase):
    """Base class for socket server tests."""

    _server_serializable = False

    def setup_method(self):
        super().setup_method()
        self.sock_path = os.path.join(self._tmpdir, "mvcc.sock")
        cmd = ["python3", "/app/mvcc_server.py", self.sock_path, self.db_path]
        if self._server_serializable:
            cmd.append("--serializable")
        self.server_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        _wait_for_socket(self.sock_path)

    def teardown_method(self):
        if hasattr(self, "server_proc") and self.server_proc.poll() is None:
            self.server_proc.terminate()
            self.server_proc.wait(timeout=5)
        super().teardown_method()

    def _socat(self, commands, timeout=10):
        """Send commands via socat, appending QUIT for clean shutdown."""
        cmds = list(commands) + ["QUIT"]
        input_text = "\n".join(cmds) + "\n"
        result = subprocess.run(
            ["socat", "-", f"UNIX-CONNECT:{self.sock_path}"],
            input=input_text, capture_output=True, text=True, timeout=timeout,
        )
        return [l for l in result.stdout.strip().split("\n") if l]

    def _connect(self):
        """Open a raw socket connection, returns (socket, reader_file, writer_file)."""
        s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
        s.connect(self.sock_path)
        s.settimeout(5)
        rf = s.makefile("r")
        wf = s.makefile("w")
        return s, rf, wf

    def _exchange(self, wf, rf, cmd):
        """Send one command and read one response line."""
        wf.write(cmd + "\n")
        wf.flush()
        return rf.readline().strip()

    def _close_conn(self, s, wf, rf):
        try:
            wf.write("QUIT\n")
            wf.flush()
        except Exception:
            pass
        try:
            rf.close()
        except Exception:
            pass
        try:
            wf.close()
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass


class TestServerProtocol(_ServerTestBase):
    """Verify server protocol via socat and multi-tool pipelines."""

    _server_serializable = False

    def test_put_get_via_socat(self):
        resp = self._socat(["BEGIN", "PUT k1 v1", "GET k1", "COMMIT"])
        assert resp[0] == "OK"
        assert resp[1] == "OK"
        assert resp[2] == "VALUE v1"
        assert resp[3].startswith("COMMITTED")

    def test_scan_via_socat(self):
        self._socat(["BEGIN", "PUT a 1", "PUT b 2", "PUT c 3", "PUT d 4", "COMMIT"])
        resp = self._socat(["BEGIN", "SCAN b d", "ROLLBACK"])
        assert resp[0] == "OK"       # BEGIN
        assert resp[1] == "ITEM b 2"
        assert resp[2] == "ITEM c 3"
        assert resp[3] == "END"
        assert resp[4] == "OK"       # ROLLBACK

    def test_gc_via_socat(self):
        self._socat(["BEGIN", "PUT key v1", "COMMIT"])
        self._socat(["BEGIN", "PUT key v2", "COMMIT"])
        self._socat(["BEGIN", "PUT key v3", "COMMIT"])
        resp = self._socat(["GC"])
        assert resp[0] == "REMOVED 2"

    def test_cross_connection_persistence(self):
        self._socat(["BEGIN", "PUT mykey myval", "COMMIT"])
        resp = self._socat(["BEGIN", "GET mykey", "ROLLBACK"])
        assert resp[0] == "OK"        # BEGIN
        assert resp[1] == "VALUE myval"

    def test_data_inspection_pipeline(self):
        """Write data via socket server, verify via sqlite3 + jq pipeline."""
        self._socat(["BEGIN", "PUT alpha first", "COMMIT"])
        self._socat(["BEGIN", "PUT alpha updated", "COMMIT"])

        # sqlite3 -json piped through jq
        p1 = subprocess.run(
            ["sqlite3", "-json", self.db_path,
             "SELECT key, ts, value FROM versions WHERE key='alpha' ORDER BY ts;"],
            capture_output=True, text=True,
        )
        assert p1.returncode == 0
        p2 = subprocess.run(
            ["jq", "length"], input=p1.stdout,
            capture_output=True, text=True,
        )
        assert p2.returncode == 0
        assert p2.stdout.strip() == "2"

        # Filter with jq to verify values
        p3 = subprocess.run(
            ["jq", "-r", ".[1].value"], input=p1.stdout,
            capture_output=True, text=True,
        )
        assert p3.returncode == 0
        assert p3.stdout.strip() == "updated"

    def test_snapshot_isolation_concurrent(self):
        """Verify snapshot isolation across concurrent socket connections."""
        # Write initial data
        self._socat(["BEGIN", "PUT key1 original", "COMMIT"])

        # Open a long-lived connection that reads key1
        s1, rf1, wf1 = self._connect()
        assert self._exchange(wf1, rf1, "BEGIN") == "OK"
        assert self._exchange(wf1, rf1, "GET key1") == "VALUE original"

        # A separate connection updates key1 and commits
        self._socat(["BEGIN", "PUT key1 modified", "COMMIT"])

        # The long-lived connection must still see the old value
        assert self._exchange(wf1, rf1, "GET key1") == "VALUE original"

        self._close_conn(s1, wf1, rf1)


class TestServerSerializable(_ServerTestBase):
    """Verify serializable conflict detection via concurrent socket connections."""

    _server_serializable = True

    def test_write_skew_via_server(self):
        """Detect write-skew through concurrent socket connections."""
        # Setup initial data
        self._socat(["BEGIN", "PUT key1 1", "PUT key2 2", "COMMIT"])

        # Open two concurrent connections
        s1, rf1, wf1 = self._connect()
        s2, rf2, wf2 = self._connect()

        # txn1: read key2
        assert self._exchange(wf1, rf1, "BEGIN") == "OK"
        assert self._exchange(wf1, rf1, "GET key2") == "VALUE 2"

        # txn2: read key1
        assert self._exchange(wf2, rf2, "BEGIN") == "OK"
        assert self._exchange(wf2, rf2, "GET key1") == "VALUE 1"

        # txn1: write key1 and commit successfully
        assert self._exchange(wf1, rf1, "PUT key1 2") == "OK"
        resp1 = self._exchange(wf1, rf1, "COMMIT")
        assert resp1.startswith("COMMITTED")

        # txn2: write key2 and commit — must detect conflict
        assert self._exchange(wf2, rf2, "PUT key2 1") == "OK"
        resp2 = self._exchange(wf2, rf2, "COMMIT")
        assert resp2.startswith("CONFLICT")

        self._close_conn(s1, wf1, rf1)
        self._close_conn(s2, wf2, rf2)
