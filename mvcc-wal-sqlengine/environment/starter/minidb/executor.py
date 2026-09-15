from .types import ResultSet
from .storage import MemoryBackend
from .parser import (CreateTableStmt, InsertStmt, SelectStmt,
                     UpdateStmt, DeleteStmt)


class Executor:
    def __init__(self, storage: MemoryBackend):
        self.storage = storage

    def execute(self, stmt) -> ResultSet:
        if isinstance(stmt, CreateTableStmt):
            self.storage.create_table(stmt.table_name, stmt.columns)
            return ResultSet(message=f"Table '{stmt.table_name}' created")
        elif isinstance(stmt, InsertStmt):
            self.storage.insert(stmt.table_name, stmt.columns, stmt.values)
            return ResultSet(message="1 row inserted")
        elif isinstance(stmt, SelectStmt):
            cols, rows = self.storage.select(
                stmt.table_name, stmt.columns, stmt.where
            )
            return ResultSet(columns=cols, rows=rows)
        elif isinstance(stmt, UpdateStmt):
            count = self.storage.update(
                stmt.table_name, stmt.assignments, stmt.where
            )
            return ResultSet(message=f"{count} row(s) updated")
        elif isinstance(stmt, DeleteStmt):
            count = self.storage.delete(stmt.table_name, stmt.where)
            return ResultSet(message=f"{count} row(s) deleted")
        else:
            raise RuntimeError(f"Unknown statement type: {type(stmt).__name__}")
