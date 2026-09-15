#!/usr/bin/env python3
"""Solution: adds MVCC, protobuf WAL, sessions, transactions, and Makefile to minidb."""

import os

MINIDB = "/app/minidb"
APP = "/app"


def write_file(name, content, base=MINIDB):
    path = os.path.join(base, name)
    with open(path, "w") as f:
        f.write(content)
    print(f"Wrote {path}")


# ---------- 0. Makefile ----------
write_file("Makefile", """.PHONY: proto clean

proto: minidb/wal_pb2.py

minidb/wal_pb2.py: minidb/wal.proto
\tprotoc --python_out=. minidb/wal.proto

clean:
\trm -f minidb/wal_pb2.py
""", base=APP)


# ---------- 1. Transaction manager ----------
write_file("txn.py", r'''
import threading


class TransactionConflict(Exception):
    pass


TXN_COMMITTED = "committed"
TXN_ABORTED = "aborted"
TXN_ACTIVE = "active"


class TransactionManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._next_txn_id = 1
        self._status = {}       # txn_id -> status
        self._snapshots = {}    # txn_id -> frozenset of active txn_ids at begin

    def begin(self):
        with self._lock:
            txn_id = self._next_txn_id
            self._next_txn_id += 1
            self._status[txn_id] = TXN_ACTIVE
            active = frozenset(
                tid for tid, st in self._status.items() if st == TXN_ACTIVE and tid != txn_id
            )
            # Snapshot is (active_txn_ids, snapshot_boundary)
            # Any txn with id >= snapshot_boundary started after us and is invisible
            self._snapshots[txn_id] = (active, txn_id)
            return txn_id

    def commit(self, txn_id):
        with self._lock:
            self._status[txn_id] = TXN_COMMITTED

    def abort(self, txn_id):
        with self._lock:
            self._status[txn_id] = TXN_ABORTED

    def is_committed(self, txn_id):
        return self._status.get(txn_id) == TXN_COMMITTED

    def is_aborted(self, txn_id):
        return self._status.get(txn_id) == TXN_ABORTED

    def get_snapshot(self, txn_id):
        return self._snapshots.get(txn_id, (frozenset(), txn_id))

    def get_status(self, txn_id):
        return self._status.get(txn_id, TXN_ACTIVE)

    @property
    def next_txn_id(self):
        return self._next_txn_id

    def restore_state(self, next_id, committed_ids):
        """Restore txn manager state after recovery."""
        with self._lock:
            self._next_txn_id = next_id
            for tid in committed_ids:
                self._status[tid] = TXN_COMMITTED
''')


# ---------- 2. MVCC storage ----------
write_file("mvcc_storage.py", r'''
import copy
from .types import ColumnType, ColumnDef
from .storage import StorageError, TableSchema


class RowVersion:
    __slots__ = ("data", "xmin", "xmax")

    def __init__(self, data, xmin, xmax=None):
        self.data = data
        self.xmin = xmin
        self.xmax = xmax


class MVCCBackend:
    def __init__(self, txn_manager):
        self.txn_manager = txn_manager
        self.schemas = {}           # table_name -> TableSchema
        self.tables = {}            # table_name -> list[RowVersion]
        self._row_locks = {}        # (table, row_index) -> txn_id

    def _is_visible(self, version, txn_id):
        """Check if a row version is visible to the given transaction."""
        tm = self.txn_manager
        active_set, snap_boundary = tm.get_snapshot(txn_id)

        # xmin must be committed (or be our own txn)
        xmin = version.xmin
        if xmin == txn_id:
            # Our own write - visible unless we deleted it
            if version.xmax is not None and version.xmax == txn_id:
                return False
            return True

        # xmin must be committed
        if not tm.is_committed(xmin):
            return False

        # xmin must have started before our snapshot
        if xmin >= snap_boundary:
            return False

        # xmin must not have been active when we took our snapshot
        if xmin in active_set:
            return False

        # If xmax is set, check if the delete/update is visible to us
        xmax = version.xmax
        if xmax is not None:
            if xmax == txn_id:
                # We deleted it
                return False
            # Delete is visible only if xmax is committed, within our boundary, and not in our active set
            if tm.is_committed(xmax) and xmax < snap_boundary and xmax not in active_set:
                return False

        return True

    def create_table(self, name, columns, txn_id=None):
        if name in self.schemas:
            raise StorageError(f"Table '{name}' already exists")
        self.schemas[name] = TableSchema(name, columns)
        self.tables[name] = []

    def _check_table(self, name):
        if name not in self.schemas:
            raise StorageError(f"Table '{name}' does not exist")

    def insert(self, table, columns, values, txn_id):
        self._check_table(table)
        schema = self.schemas[table]
        if columns is None:
            columns = schema.col_names
        if len(columns) != len(values):
            raise StorageError(
                f"Column count mismatch: {len(columns)} columns, {len(values)} values"
            )
        row = {}
        for col_name, val in zip(columns, values):
            if col_name not in schema.col_types:
                raise StorageError(f"Unknown column '{col_name}' in table '{table}'")
            row[col_name] = self._cast(val, schema.col_types[col_name])
        for col_name in schema.col_names:
            if col_name not in row:
                row[col_name] = None
        self.tables[table].append(RowVersion(row, xmin=txn_id))

    def select(self, table, columns, where, txn_id):
        self._check_table(table)
        schema = self.schemas[table]
        if columns == ['*']:
            columns = list(schema.col_names)
        visible_rows = []
        for v in self.tables[table]:
            if self._is_visible(v, txn_id):
                visible_rows.append(v.data)
        if where is not None:
            visible_rows = [r for r in visible_rows if self._eval_where(r, where)]
        result = []
        for r in visible_rows:
            result.append([r.get(c) for c in columns])
        return columns, result

    def update(self, table, assignments, where, txn_id):
        from .txn import TransactionConflict
        self._check_table(table)
        schema = self.schemas[table]
        count = 0
        new_versions = []
        for i, v in enumerate(self.tables[table]):
            if not self._is_visible(v, txn_id):
                continue
            if where is not None and not self._eval_where(v.data, where):
                continue
            # Check for write-write conflict
            self._check_write_conflict(table, i, txn_id)
            # Mark old version as deleted
            v.xmax = txn_id
            # Create new version with updated data
            new_data = dict(v.data)
            for col, val in assignments:
                if col not in schema.col_types:
                    raise StorageError(f"Unknown column '{col}' in table '{table}'")
                new_data[col] = self._cast(val, schema.col_types[col])
            new_versions.append(RowVersion(new_data, xmin=txn_id))
            count += 1
        self.tables[table].extend(new_versions)
        return count

    def delete(self, table, where, txn_id):
        from .txn import TransactionConflict
        self._check_table(table)
        count = 0
        for i, v in enumerate(self.tables[table]):
            if not self._is_visible(v, txn_id):
                continue
            if where is not None and not self._eval_where(v.data, where):
                continue
            self._check_write_conflict(table, i, txn_id)
            v.xmax = txn_id
            count += 1
        return count

    def _check_write_conflict(self, table, row_idx, txn_id):
        from .txn import TransactionConflict
        lock_key = (table, row_idx)
        existing = self._row_locks.get(lock_key)
        if existing is not None and existing != txn_id:
            tm = self.txn_manager
            status = tm.get_status(existing)
            if status == "active":
                raise TransactionConflict(
                    f"Write conflict on {table} row {row_idx}: "
                    f"locked by txn {existing}"
                )
        self._row_locks[lock_key] = txn_id

    def release_locks(self, txn_id):
        to_remove = [k for k, v in self._row_locks.items() if v == txn_id]
        for k in to_remove:
            del self._row_locks[k]

    def rollback_txn(self, txn_id):
        """Remove all versions created by txn_id and undo xmax marks."""
        for table_name in list(self.tables.keys()):
            # Remove versions created by this txn
            self.tables[table_name] = [
                v for v in self.tables[table_name] if v.xmin != txn_id
            ]
            # Undo xmax marks set by this txn
            for v in self.tables[table_name]:
                if v.xmax == txn_id:
                    v.xmax = None
        self.release_locks(txn_id)

    def get_snapshot_data(self):
        """Return a serializable snapshot of all committed data."""
        snapshot = {"schemas": {}, "tables": {}}
        for name, schema in self.schemas.items():
            snapshot["schemas"][name] = [
                {"name": c.name, "type": c.col_type.value} for c in schema.columns
            ]
        for name in self.schemas:
            rows = []
            for v in self.tables[name]:
                if self.txn_manager.is_committed(v.xmin) and v.xmax is None:
                    rows.append(dict(v.data))
                elif self.txn_manager.is_committed(v.xmin) and v.xmax is not None:
                    if not self.txn_manager.is_committed(v.xmax):
                        rows.append(dict(v.data))
            snapshot["tables"][name] = rows
        return snapshot

    def load_snapshot_data(self, snapshot, base_txn_id):
        """Load data from a snapshot. All rows get xmin=base_txn_id."""
        from .types import ColumnDef, ColumnType
        type_map = {"int": ColumnType.INTEGER, "text": ColumnType.TEXT,
                     "boolean": ColumnType.BOOLEAN}
        for name, col_defs in snapshot["schemas"].items():
            columns = [ColumnDef(c["name"], type_map[c["type"]]) for c in col_defs]
            self.schemas[name] = TableSchema(name, columns)
            self.tables[name] = []
            for row_data in snapshot["tables"].get(name, []):
                self.tables[name].append(RowVersion(row_data, xmin=base_txn_id))

    def _eval_where(self, row, expr):
        from .parser import BinaryExpr, LogicalExpr
        if isinstance(expr, BinaryExpr):
            left = row.get(expr.column)
            right = expr.value
            op = expr.op
            if left is None or right is None:
                return op == '=' and left is right
            if op == '=': return left == right
            elif op == '!=': return left != right
            elif op == '<': return left < right
            elif op == '>': return left > right
            elif op == '<=': return left <= right
            elif op == '>=': return left >= right
            return False
        elif isinstance(expr, LogicalExpr):
            left_val = self._eval_where(row, expr.left)
            if expr.op == 'AND':
                return left_val and self._eval_where(row, expr.right)
            elif expr.op == 'OR':
                return left_val or self._eval_where(row, expr.right)
        return False

    def _cast(self, value, col_type):
        if value is None:
            return None
        if col_type == ColumnType.INTEGER:
            return int(value)
        elif col_type == ColumnType.TEXT:
            return str(value)
        elif col_type == ColumnType.BOOLEAN:
            return bool(value)
        return value
''')


# ---------- 3. Protobuf-based WAL ----------
write_file("wal.py", r'''
import os
import struct
from . import wal_pb2


class WAL:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.wal_path = os.path.join(data_dir, "wal.bin")
        self.checkpoint_path = os.path.join(data_dir, "checkpoint.bin")
        self._fd = None

    def open(self):
        os.makedirs(self.data_dir, exist_ok=True)
        self._fd = open(self.wal_path, "ab")

    def close(self):
        if self._fd:
            self._fd.flush()
            os.fsync(self._fd.fileno())
            self._fd.close()
            self._fd = None

    def append(self, entry_dict):
        """Append a WAL record as a length-prefixed protobuf message."""
        if self._fd is None:
            return
        record = self._dict_to_proto(entry_dict)
        data = record.SerializeToString()
        length = struct.pack(">I", len(data))
        self._fd.write(length + data)
        self._fd.flush()
        os.fsync(self._fd.fileno())

    def read_entries(self):
        """Read all WAL entries, deserializing protobuf records to dicts."""
        if not os.path.exists(self.wal_path):
            return []
        records = []
        with open(self.wal_path, "rb") as f:
            while True:
                length_bytes = f.read(4)
                if len(length_bytes) < 4:
                    break
                length = struct.unpack(">I", length_bytes)[0]
                data = f.read(length)
                if len(data) < length:
                    break
                record = wal_pb2.WalRecord()
                record.ParseFromString(data)
                records.append(self._proto_to_dict(record))
        return records

    def write_checkpoint(self, snapshot_data):
        """Write checkpoint as a single CheckpointData protobuf message."""
        ckpt = wal_pb2.CheckpointData()
        ckpt.next_txn_id = snapshot_data.get("next_txn_id", 0)

        for name, col_defs in snapshot_data.get("schemas", {}).items():
            table = ckpt.tables.add()
            table.name = name
            for c in col_defs:
                col = table.schema_columns.add()
                col.name = c["name"]
                col.col_type = c["type"]
            for row_data in snapshot_data.get("tables", {}).get(name, []):
                row = table.rows.add()
                for k, v in row_data.items():
                    field = row.fields.add()
                    field.name = k
                    self._set_sql_value(field.value, v)

        data = ckpt.SerializeToString()
        tmp = self.checkpoint_path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.checkpoint_path)

        # Truncate WAL
        if self._fd:
            self._fd.close()
        with open(self.wal_path, "wb") as f:
            pass
        self._fd = open(self.wal_path, "ab")

    def load_checkpoint(self):
        """Load checkpoint from a CheckpointData protobuf message."""
        if not os.path.exists(self.checkpoint_path):
            return None
        with open(self.checkpoint_path, "rb") as f:
            data = f.read()
        ckpt = wal_pb2.CheckpointData()
        ckpt.ParseFromString(data)

        result = {"schemas": {}, "tables": {}, "next_txn_id": ckpt.next_txn_id}
        for table in ckpt.tables:
            cols = [{"name": c.name, "type": c.col_type} for c in table.schema_columns]
            result["schemas"][table.name] = cols
            rows = []
            for row in table.rows:
                row_dict = {}
                for field in row.fields:
                    row_dict[field.name] = self._get_sql_value(field.value)
                rows.append(row_dict)
            result["tables"][table.name] = rows
        return result

    # --- Protobuf conversion helpers ---

    def _dict_to_proto(self, d):
        record = wal_pb2.WalRecord()
        record.txn_id = d.get("txn_id", 0)
        record.entry_type = d.get("type", "")
        record.table_name = d.get("table", "")
        entry_type = d.get("type", "")

        if entry_type == "CREATE_TABLE":
            for c in d.get("columns", []):
                col = record.columns.add()
                col.name = c["name"]
                col.col_type = c["type"]

        elif entry_type == "INSERT":
            for name in d.get("columns", []):
                record.col_names.append(name)
            for v in d.get("values", []):
                sv = record.col_values.add()
                self._set_sql_value(sv, v)

        elif entry_type == "UPDATE":
            for a in d.get("assignments", []):
                assign = record.assignments.add()
                assign.column = a[0]
                self._set_sql_value(assign.value, a[1])
            where = d.get("where")
            if where:
                self._set_predicate(record.where_clause, where)

        elif entry_type == "DELETE":
            where = d.get("where")
            if where:
                self._set_predicate(record.where_clause, where)

        # COMMIT and ROLLBACK have no extra payload
        return record

    def _proto_to_dict(self, record):
        d = {
            "txn_id": record.txn_id,
            "type": record.entry_type,
        }
        if record.table_name:
            d["table"] = record.table_name

        if record.entry_type == "CREATE_TABLE":
            d["columns"] = [{"name": c.name, "type": c.col_type}
                            for c in record.columns]

        elif record.entry_type == "INSERT":
            d["columns"] = list(record.col_names)
            d["values"] = [self._get_sql_value(v) for v in record.col_values]

        elif record.entry_type == "UPDATE":
            d["assignments"] = [[a.column, self._get_sql_value(a.value)]
                                for a in record.assignments]
            if record.HasField("where_clause"):
                d["where"] = self._get_predicate(record.where_clause)

        elif record.entry_type == "DELETE":
            if record.HasField("where_clause"):
                d["where"] = self._get_predicate(record.where_clause)

        return d

    def _set_sql_value(self, sv, value):
        if value is None:
            sv.is_null = True
        elif isinstance(value, bool):
            sv.bool_val = value
        elif isinstance(value, int):
            sv.int_val = value
        elif isinstance(value, str):
            sv.str_val = value

    def _get_sql_value(self, sv):
        if sv.is_null:
            return None
        which = sv.WhichOneof("val")
        if which == "int_val":
            return sv.int_val
        elif which == "str_val":
            return sv.str_val
        elif which == "bool_val":
            return sv.bool_val
        return None

    def _set_predicate(self, pred, where_dict):
        if where_dict is None:
            return
        if where_dict["kind"] == "binary":
            comp = pred.comparison
            comp.column = where_dict["column"]
            comp.op = where_dict["op"]
            self._set_sql_value(comp.value, where_dict["value"])
        elif where_dict["kind"] == "logical":
            logical = pred.logical_op
            logical.op = where_dict["op"]
            self._set_predicate(logical.left, where_dict["left"])
            self._set_predicate(logical.right, where_dict["right"])

    def _get_predicate(self, pred):
        which = pred.WhichOneof("predicate")
        if which == "comparison":
            comp = pred.comparison
            return {
                "kind": "binary",
                "column": comp.column,
                "op": comp.op,
                "value": self._get_sql_value(comp.value),
            }
        elif which == "logical_op":
            logical = pred.logical_op
            return {
                "kind": "logical",
                "op": logical.op,
                "left": self._get_predicate(logical.left),
                "right": self._get_predicate(logical.right),
            }
        return None
''')


# ---------- 4. Session ----------
write_file("session.py", r'''
from .types import ResultSet
from .lexer import tokenize
from .parser import parse, CreateTableStmt, InsertStmt, SelectStmt, UpdateStmt, DeleteStmt
from .txn import TransactionConflict


class BeginStmt:
    pass

class CommitStmt:
    pass

class RollbackStmt:
    pass


def parse_sql(sql):
    sql = sql.strip().rstrip(";")
    upper = sql.upper().strip()
    if upper == "BEGIN":
        return BeginStmt()
    elif upper == "COMMIT":
        return CommitStmt()
    elif upper == "ROLLBACK":
        return RollbackStmt()
    tokens = tokenize(sql)
    return parse(tokens)


class Session:
    def __init__(self, database):
        self._db = database
        self._txn_id = None
        self._in_explicit_txn = False

    def execute(self, sql):
        stmt = parse_sql(sql)
        if isinstance(stmt, BeginStmt):
            return self._begin()
        elif isinstance(stmt, CommitStmt):
            return self._commit()
        elif isinstance(stmt, RollbackStmt):
            return self._rollback()
        else:
            return self._execute_stmt(stmt)

    def _begin(self):
        if self._in_explicit_txn:
            raise RuntimeError("Already in a transaction")
        self._txn_id = self._db.txn_manager.begin()
        self._in_explicit_txn = True
        return ResultSet(message="BEGIN")

    def _commit(self):
        if not self._in_explicit_txn:
            raise RuntimeError("No active transaction")
        self._db.txn_manager.commit(self._txn_id)
        self._db.storage.release_locks(self._txn_id)
        if self._db.wal:
            self._db.wal.append({"type": "COMMIT", "txn_id": self._txn_id})
        self._txn_id = None
        self._in_explicit_txn = False
        return ResultSet(message="COMMIT")

    def _rollback(self):
        if not self._in_explicit_txn:
            raise RuntimeError("No active transaction")
        self._db.txn_manager.abort(self._txn_id)
        self._db.storage.rollback_txn(self._txn_id)
        if self._db.wal:
            self._db.wal.append({"type": "ROLLBACK", "txn_id": self._txn_id})
        self._txn_id = None
        self._in_explicit_txn = False
        return ResultSet(message="ROLLBACK")

    def _execute_stmt(self, stmt):
        auto_commit = not self._in_explicit_txn
        if auto_commit:
            self._txn_id = self._db.txn_manager.begin()

        try:
            result = self._dispatch(stmt)
            if auto_commit:
                self._db.txn_manager.commit(self._txn_id)
                self._db.storage.release_locks(self._txn_id)
                if self._db.wal:
                    self._db.wal.append({"type": "COMMIT", "txn_id": self._txn_id})
                self._txn_id = None
            return result
        except Exception:
            if auto_commit:
                self._db.txn_manager.abort(self._txn_id)
                self._db.storage.rollback_txn(self._txn_id)
                self._txn_id = None
            raise

    def _dispatch(self, stmt):
        storage = self._db.storage
        txn_id = self._txn_id

        if isinstance(stmt, CreateTableStmt):
            storage.create_table(stmt.table_name, stmt.columns, txn_id)
            if self._db.wal:
                cols = [{"name": c.name, "type": c.col_type.value} for c in stmt.columns]
                self._db.wal.append({
                    "type": "CREATE_TABLE", "txn_id": txn_id,
                    "table": stmt.table_name, "columns": cols
                })
            return ResultSet(message=f"Table '{stmt.table_name}' created")

        elif isinstance(stmt, InsertStmt):
            storage.insert(stmt.table_name, stmt.columns, stmt.values, txn_id)
            if self._db.wal:
                schema = storage.schemas[stmt.table_name]
                cols = stmt.columns if stmt.columns else schema.col_names
                self._db.wal.append({
                    "type": "INSERT", "txn_id": txn_id,
                    "table": stmt.table_name,
                    "columns": list(cols), "values": list(stmt.values)
                })
            return ResultSet(message="1 row inserted")

        elif isinstance(stmt, SelectStmt):
            cols, rows = storage.select(
                stmt.table_name, stmt.columns, stmt.where, txn_id
            )
            return ResultSet(columns=cols, rows=rows)

        elif isinstance(stmt, UpdateStmt):
            count = storage.update(
                stmt.table_name, stmt.assignments, stmt.where, txn_id
            )
            if self._db.wal:
                assigns = [[c, v] for c, v in stmt.assignments]
                where_ser = self._serialize_where(stmt.where) if stmt.where else None
                self._db.wal.append({
                    "type": "UPDATE", "txn_id": txn_id,
                    "table": stmt.table_name,
                    "assignments": assigns, "where": where_ser
                })
            return ResultSet(message=f"{count} row(s) updated")

        elif isinstance(stmt, DeleteStmt):
            count = storage.delete(
                stmt.table_name, stmt.where, txn_id
            )
            if self._db.wal:
                where_ser = self._serialize_where(stmt.where) if stmt.where else None
                self._db.wal.append({
                    "type": "DELETE", "txn_id": txn_id,
                    "table": stmt.table_name, "where": where_ser
                })
            return ResultSet(message=f"{count} row(s) deleted")
        else:
            raise RuntimeError(f"Unknown statement: {type(stmt).__name__}")

    def _serialize_where(self, expr):
        from .parser import BinaryExpr, LogicalExpr
        if expr is None:
            return None
        if isinstance(expr, BinaryExpr):
            return {"kind": "binary", "column": expr.column,
                    "op": expr.op, "value": expr.value}
        elif isinstance(expr, LogicalExpr):
            return {"kind": "logical", "op": expr.op,
                    "left": self._serialize_where(expr.left),
                    "right": self._serialize_where(expr.right)}
        return None
''')


# ---------- 5. Updated engine ----------
write_file("engine.py", r'''
from .types import ResultSet, ColumnDef, ColumnType
from .txn import TransactionManager
from .mvcc_storage import MVCCBackend
from .wal import WAL
from .session import Session
from .parser import BinaryExpr, LogicalExpr


class Database:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir
        self.txn_manager = TransactionManager()
        self.storage = MVCCBackend(self.txn_manager)
        self.wal = None
        self._internal_session = None

        if data_dir:
            self.wal = WAL(data_dir)
            self.wal.open()
            self._recover()

    def session(self):
        return Session(self)

    def execute(self, sql):
        if self._internal_session is None:
            self._internal_session = self.session()
        return self._internal_session.execute(sql)

    def checkpoint(self):
        if self.wal is None:
            return
        snapshot = self.storage.get_snapshot_data()
        snapshot["next_txn_id"] = self.txn_manager.next_txn_id
        self.wal.write_checkpoint(snapshot)

    def close(self):
        if self.wal:
            self.wal.close()

    def _recover(self):
        # Load checkpoint if available
        ckpt = self.wal.load_checkpoint()
        committed_ids = set()
        if ckpt:
            base_txn = self.txn_manager.begin()
            self.txn_manager.commit(base_txn)
            committed_ids.add(base_txn)
            self.storage.load_snapshot_data(ckpt, base_txn)
            next_id = ckpt.get("next_txn_id", base_txn + 1)
            self.txn_manager.restore_state(next_id, committed_ids)

        # Replay WAL
        entries = self.wal.read_entries()
        if not entries:
            return

        # First pass: find which transactions committed
        committed_txns = set()
        for entry in entries:
            if entry["type"] == "COMMIT":
                committed_txns.add(entry["txn_id"])

        # Second pass: replay only committed transactions
        type_map = {"int": ColumnType.INTEGER, "text": ColumnType.TEXT,
                     "boolean": ColumnType.BOOLEAN}

        # We need to assign new txn IDs for replay
        replay_txn = self.txn_manager.begin()
        self.txn_manager.commit(replay_txn)
        committed_ids.add(replay_txn)

        for entry in entries:
            etype = entry["type"]
            orig_txn = entry.get("txn_id")

            if orig_txn is not None and orig_txn not in committed_txns:
                continue
            if etype in ("COMMIT", "ROLLBACK"):
                continue

            if etype == "CREATE_TABLE":
                cols = [ColumnDef(c["name"], type_map[c["type"]])
                        for c in entry["columns"]]
                if entry["table"] not in self.storage.schemas:
                    self.storage.create_table(entry["table"], cols, replay_txn)

            elif etype == "INSERT":
                self.storage.insert(
                    entry["table"], entry["columns"], entry["values"], replay_txn
                )

            elif etype == "UPDATE":
                where = self._deserialize_where(entry.get("where"))
                self.storage.update(
                    entry["table"], [tuple(a) for a in entry["assignments"]],
                    where, replay_txn
                )

            elif etype == "DELETE":
                where = self._deserialize_where(entry.get("where"))
                self.storage.delete(entry["table"], where, replay_txn)

        # Update txn manager to avoid ID collisions
        max_txn = max(
            (e.get("txn_id", 0) for e in entries), default=0
        )
        new_next = max(max_txn + 1, self.txn_manager.next_txn_id, replay_txn + 1)
        self.txn_manager.restore_state(new_next, committed_ids)

    def _deserialize_where(self, w):
        if w is None:
            return None
        if w["kind"] == "binary":
            return BinaryExpr(w["column"], w["op"], w["value"])
        elif w["kind"] == "logical":
            return LogicalExpr(
                self._deserialize_where(w["left"]),
                w["op"],
                self._deserialize_where(w["right"])
            )
        return None
''')


# ---------- 6. Updated __init__.py ----------
write_file("__init__.py", r'''
from .engine import Database
from .types import ResultSet, ColumnType, ColumnDef
from .txn import TransactionConflict
''')


print("Solution applied successfully.")
