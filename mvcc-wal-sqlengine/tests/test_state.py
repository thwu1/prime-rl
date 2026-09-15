
import os
import sys
import struct
import shutil
import tempfile
import subprocess

import pytest

sys.path.insert(0, "/app")
from minidb import Database


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ============================================================
# Build pipeline tests
# ============================================================


class TestBuildSystem:
    """Makefile must exist with proto and clean targets."""

    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile must exist at /app/Makefile"

    def test_makefile_has_proto_target(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert "proto" in content, "Makefile must have a proto target"
        assert "protoc" in content, "Makefile proto target must invoke protoc"

    def test_makefile_has_clean_target(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert "clean" in content, "Makefile must have a clean target"

    def test_make_proto_succeeds(self):
        result = subprocess.run(
            ["make", "proto"], cwd="/app", capture_output=True, text=True
        )
        assert result.returncode == 0, f"make proto failed: {result.stderr}"


# ============================================================
# Protobuf persistence format tests
# ============================================================


class TestProtobufFormat:
    """Persistence log must use Protocol Buffers binary format with length-prefixed records."""

    @staticmethod
    def _read_wal_records(path):
        from minidb.wal_pb2 import WalRecord

        records = []
        with open(path, "rb") as f:
            while True:
                length_bytes = f.read(4)
                if len(length_bytes) < 4:
                    break
                length = struct.unpack(">I", length_bytes)[0]
                data = f.read(length)
                if len(data) < length:
                    break
                record = WalRecord()
                record.ParseFromString(data)
                records.append(record)
        return records

    def test_log_is_binary_protobuf(self, tmpdir):
        db = Database(data_dir=tmpdir)
        s = db.session()
        s.execute("CREATE TABLE t (id int, name text)")
        s.execute("INSERT INTO t VALUES (1, 'hello')")
        db.close()

        wal_path = os.path.join(tmpdir, "wal.bin")
        assert os.path.exists(wal_path), "Log file wal.bin must exist in data_dir"

        records = self._read_wal_records(wal_path)
        assert len(records) >= 2, "Log must contain at least CREATE_TABLE and INSERT records"

        entry_types = [r.entry_type for r in records]
        assert "CREATE_TABLE" in entry_types, "Log must contain CREATE_TABLE entry"
        assert "INSERT" in entry_types, "Log must contain INSERT entry"
        assert "COMMIT" in entry_types, "Log must contain COMMIT entry"

    def test_log_not_text_format(self, tmpdir):
        db = Database(data_dir=tmpdir)
        s = db.session()
        s.execute("CREATE TABLE t (id int)")
        s.execute("INSERT INTO t VALUES (1)")
        db.close()

        wal_path = os.path.join(tmpdir, "wal.bin")
        with open(wal_path, "rb") as f:
            raw = f.read(20)
        assert raw[0:1] != b"{", "Log must be binary protobuf, not JSON"
        assert raw[0:1] != b"[", "Log must be binary protobuf, not JSON array"

    def test_checkpoint_is_protobuf(self, tmpdir):
        db = Database(data_dir=tmpdir)
        s = db.session()
        s.execute("CREATE TABLE t (id int, v text)")
        for i in range(10):
            s.execute(f"INSERT INTO t VALUES ({i}, 'val{i}')")
        db.checkpoint()
        db.close()

        ckpt_path = os.path.join(tmpdir, "checkpoint.bin")
        assert os.path.exists(ckpt_path), "Checkpoint file checkpoint.bin must exist"

        from minidb.wal_pb2 import CheckpointData

        with open(ckpt_path, "rb") as f:
            data = f.read()
        ckpt = CheckpointData()
        ckpt.ParseFromString(data)

        table_names = [t.name for t in ckpt.tables]
        assert "t" in table_names, "Checkpoint must contain table 't'"
        t_state = next(t for t in ckpt.tables if t.name == "t")
        assert len(t_state.rows) == 10, "Checkpoint must contain all 10 rows"

    def test_log_insert_values_preserved(self, tmpdir):
        """Protobuf log must faithfully preserve inserted values."""
        db = Database(data_dir=tmpdir)
        s = db.session()
        s.execute("CREATE TABLE t (id int, name text)")
        s.execute("INSERT INTO t VALUES (42, 'world')")
        db.close()

        records = self._read_wal_records(os.path.join(tmpdir, "wal.bin"))
        insert_records = [r for r in records if r.entry_type == "INSERT"]
        assert len(insert_records) >= 1

        rec = insert_records[0]
        # Verify values are preserved in protobuf
        found_42 = False
        found_world = False
        for v in rec.col_values:
            if v.HasField("val") and v.WhichOneof("val") == "int_val" and v.int_val == 42:
                found_42 = True
            if v.HasField("val") and v.WhichOneof("val") == "str_val" and v.str_val == "world":
                found_world = True
        assert found_42, "Protobuf log must preserve integer value 42"
        assert found_world, "Protobuf log must preserve string value 'world'"


# ============================================================
# Crash recovery tests
# ============================================================


class TestCrashRecovery:
    """Persistence log must durably persist committed data across restarts."""

    def test_basic_recovery(self, tmpdir):
        db = Database(data_dir=tmpdir)
        s = db.session()
        s.execute("CREATE TABLE users (id int, name text)")
        s.execute("INSERT INTO users VALUES (1, 'alice')")
        s.execute("INSERT INTO users VALUES (2, 'bob')")
        db.close()

        db2 = Database(data_dir=tmpdir)
        s2 = db2.session()
        r = s2.execute("SELECT * FROM users")
        assert len(r.rows) == 2
        names = sorted([row[1] for row in r.rows])
        assert names == ["alice", "bob"]
        db2.close()

    def test_recovery_ignores_uncommitted(self, tmpdir):
        db = Database(data_dir=tmpdir)
        s = db.session()
        s.execute("CREATE TABLE t (id int, v int)")
        s.execute("INSERT INTO t VALUES (1, 10)")

        s2 = db.session()
        s2.execute("BEGIN")
        s2.execute("INSERT INTO t VALUES (2, 20)")
        # s2 never commits — crash simulation
        db.close()

        db2 = Database(data_dir=tmpdir)
        s3 = db2.session()
        r = s3.execute("SELECT * FROM t")
        assert len(r.rows) == 1
        assert r.rows[0][0] == 1
        db2.close()


# ============================================================
# Transaction isolation tests
# ============================================================


class TestTransactionIsolation:
    """Uncommitted writes must be invisible to other sessions."""

    def test_read_uncommitted_invisible(self):
        db = Database()
        s1 = db.session()
        s1.execute("CREATE TABLE items (id int, qty int)")
        s1.execute("INSERT INTO items VALUES (1, 100)")

        s2 = db.session()
        s2.execute("BEGIN")
        s2.execute("INSERT INTO items VALUES (2, 200)")
        # s2 has not committed

        s3 = db.session()
        r = s3.execute("SELECT * FROM items")
        assert len(r.rows) == 1
        assert r.rows[0][0] == 1

        s2.execute("COMMIT")

        r2 = s3.execute("SELECT * FROM items")
        assert len(r2.rows) == 2

    def test_update_invisible_before_commit(self):
        db = Database()
        s = db.session()
        s.execute("CREATE TABLE t (id int, v int)")
        s.execute("INSERT INTO t VALUES (1, 10)")

        s1 = db.session()
        s1.execute("BEGIN")
        s1.execute("UPDATE t SET v = 99 WHERE id = 1")

        s2 = db.session()
        r = s2.execute("SELECT v FROM t WHERE id = 1")
        assert r.rows[0][0] == 10

        s1.execute("COMMIT")

        r2 = s2.execute("SELECT v FROM t WHERE id = 1")
        assert r2.rows[0][0] == 99


# ============================================================
# Snapshot consistency tests
# ============================================================


class TestSnapshotConsistency:
    """A transaction's view is fixed at BEGIN time."""

    def test_view_fixed_at_begin(self):
        db = Database()
        s0 = db.session()
        s0.execute("CREATE TABLE t (id int, v int)")
        s0.execute("INSERT INTO t VALUES (1, 10)")

        s1 = db.session()
        s1.execute("BEGIN")
        # s1's view is taken now

        s2 = db.session()
        s2.execute("BEGIN")
        s2.execute("UPDATE t SET v = 20 WHERE id = 1")
        s2.execute("COMMIT")

        # s1 should still see old value
        r = s1.execute("SELECT v FROM t WHERE id = 1")
        assert r.rows[0][0] == 10

        s1.execute("COMMIT")

        # New session sees committed update
        s3 = db.session()
        r2 = s3.execute("SELECT v FROM t WHERE id = 1")
        assert r2.rows[0][0] == 20

    def test_view_does_not_see_later_inserts(self):
        db = Database()
        s0 = db.session()
        s0.execute("CREATE TABLE t (id int)")
        s0.execute("INSERT INTO t VALUES (1)")

        s1 = db.session()
        s1.execute("BEGIN")

        s2 = db.session()
        s2.execute("INSERT INTO t VALUES (2)")

        r = s1.execute("SELECT * FROM t")
        assert len(r.rows) == 1
        assert r.rows[0][0] == 1

        s1.execute("COMMIT")


# ============================================================
# Write-write conflict tests
# ============================================================


class TestWriteWriteConflict:
    """Concurrent writes to the same row must cause a conflict."""

    def test_update_conflict(self):
        from minidb import TransactionConflict

        db = Database()
        s0 = db.session()
        s0.execute("CREATE TABLE accts (id int, balance int)")
        s0.execute("INSERT INTO accts VALUES (1, 1000)")

        s1 = db.session()
        s2 = db.session()
        s1.execute("BEGIN")
        s2.execute("BEGIN")

        s1.execute("UPDATE accts SET balance = 900 WHERE id = 1")

        conflict_on_write = False
        try:
            s2.execute("UPDATE accts SET balance = 800 WHERE id = 1")
        except TransactionConflict:
            conflict_on_write = True

        if not conflict_on_write:
            with pytest.raises(TransactionConflict):
                s2.execute("COMMIT")

        s1.execute("COMMIT")

        s3 = db.session()
        r = s3.execute("SELECT balance FROM accts WHERE id = 1")
        assert r.rows[0][0] == 900

    def test_delete_conflict(self):
        from minidb import TransactionConflict

        db = Database()
        s0 = db.session()
        s0.execute("CREATE TABLE t (id int)")
        s0.execute("INSERT INTO t VALUES (1)")

        s1 = db.session()
        s2 = db.session()
        s1.execute("BEGIN")
        s2.execute("BEGIN")

        s1.execute("DELETE FROM t WHERE id = 1")

        conflict_raised = False
        try:
            s2.execute("UPDATE t SET id = 2 WHERE id = 1")
        except TransactionConflict:
            conflict_raised = True

        if not conflict_raised:
            try:
                s2.execute("COMMIT")
            except TransactionConflict:
                conflict_raised = True

        assert conflict_raised


# ============================================================
# Rollback tests
# ============================================================


class TestRollback:
    """ROLLBACK must discard all changes within the transaction."""

    def test_rollback_insert(self):
        db = Database()
        s = db.session()
        s.execute("CREATE TABLE t (id int, v text)")
        s.execute("INSERT INTO t VALUES (1, 'kept')")

        s.execute("BEGIN")
        s.execute("INSERT INTO t VALUES (2, 'discarded')")
        r = s.execute("SELECT * FROM t")
        assert len(r.rows) == 2  # own writes visible
        s.execute("ROLLBACK")

        r2 = s.execute("SELECT * FROM t")
        assert len(r2.rows) == 1
        assert r2.rows[0][1] == "kept"

    def test_rollback_update(self):
        db = Database()
        s = db.session()
        s.execute("CREATE TABLE t (id int, v int)")
        s.execute("INSERT INTO t VALUES (1, 100)")

        s.execute("BEGIN")
        s.execute("UPDATE t SET v = 999 WHERE id = 1")
        s.execute("ROLLBACK")

        r = s.execute("SELECT v FROM t WHERE id = 1")
        assert r.rows[0][0] == 100


# ============================================================
# Checkpoint recovery tests
# ============================================================


class TestCheckpointRecovery:
    """Checkpoint must capture full state; recovery uses checkpoint plus log."""

    def test_checkpoint_and_recover(self, tmpdir):
        db = Database(data_dir=tmpdir)
        s = db.session()
        s.execute("CREATE TABLE log (id int, msg text)")
        for i in range(50):
            s.execute(f"INSERT INTO log VALUES ({i}, 'msg{i}')")

        db.checkpoint()

        for i in range(50, 80):
            s.execute(f"INSERT INTO log VALUES ({i}, 'msg{i}')")

        db.close()

        db2 = Database(data_dir=tmpdir)
        s2 = db2.session()
        r = s2.execute("SELECT * FROM log")
        assert len(r.rows) == 80
        db2.close()


# ============================================================
# Auto-commit tests
# ============================================================


class TestAutoCommit:
    """Statements outside explicit transactions auto-commit."""

    def test_auto_commit_visible_immediately(self):
        db = Database()
        s1 = db.session()
        s2 = db.session()

        s1.execute("CREATE TABLE t (id int)")
        s1.execute("INSERT INTO t VALUES (1)")

        r = s2.execute("SELECT * FROM t")
        assert len(r.rows) == 1

    def test_db_execute_convenience(self):
        db = Database()
        db.execute("CREATE TABLE t (id int, v text)")
        db.execute("INSERT INTO t VALUES (1, 'hello')")
        r = db.execute("SELECT * FROM t")
        assert len(r.rows) == 1
        assert r.rows[0] == [1, "hello"]


# ============================================================
# Complex multi-table recovery tests
# ============================================================


class TestComplexRecovery:
    """Multi-table interleaved transaction recovery."""

    def test_interleaved_multi_table(self, tmpdir):
        db = Database(data_dir=tmpdir)
        s = db.session()

        s.execute("CREATE TABLE orders (id int, product text, qty int)")
        s.execute("CREATE TABLE inventory (product text, stock int)")
        s.execute("INSERT INTO inventory VALUES ('widget', 100)")
        s.execute("INSERT INTO inventory VALUES ('gadget', 50)")

        s.execute("BEGIN")
        s.execute("INSERT INTO orders VALUES (1, 'widget', 5)")
        s.execute("UPDATE inventory SET stock = 95 WHERE product = 'widget'")
        s.execute("COMMIT")

        s.execute("BEGIN")
        s.execute("INSERT INTO orders VALUES (2, 'gadget', 3)")
        s.execute("UPDATE inventory SET stock = 47 WHERE product = 'gadget'")
        s.execute("COMMIT")

        # Uncommitted transaction
        s2 = db.session()
        s2.execute("BEGIN")
        s2.execute("INSERT INTO orders VALUES (3, 'widget', 999)")
        s2.execute("UPDATE inventory SET stock = 0 WHERE product = 'widget'")
        # intentionally not committed

        db.close()

        db2 = Database(data_dir=tmpdir)
        s3 = db2.session()

        r_orders = s3.execute("SELECT * FROM orders")
        assert len(r_orders.rows) == 2

        r_inv = s3.execute("SELECT stock FROM inventory WHERE product = 'widget'")
        assert r_inv.rows[0][0] == 95

        r_inv2 = s3.execute("SELECT stock FROM inventory WHERE product = 'gadget'")
        assert r_inv2.rows[0][0] == 47

        db2.close()

    def test_read_own_writes_in_transaction(self):
        db = Database()
        s = db.session()
        s.execute("CREATE TABLE t (id int, v int)")

        s.execute("BEGIN")
        s.execute("INSERT INTO t VALUES (1, 10)")
        r = s.execute("SELECT * FROM t")
        assert len(r.rows) == 1
        assert r.rows[0] == [1, 10]

        s.execute("UPDATE t SET v = 20 WHERE id = 1")
        r2 = s.execute("SELECT v FROM t WHERE id = 1")
        assert r2.rows[0][0] == 20
        s.execute("COMMIT")

        s2 = db.session()
        r3 = s2.execute("SELECT v FROM t WHERE id = 1")
        assert r3.rows[0][0] == 20
