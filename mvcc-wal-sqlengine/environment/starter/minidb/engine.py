from .types import ResultSet
from .lexer import tokenize
from .parser import parse
from .storage import MemoryBackend
from .executor import Executor


class Database:
    """A minimal in-memory SQL database.

    Supports CREATE TABLE, INSERT, SELECT, UPDATE, DELETE.
    No transaction support, no durability.
    """

    def __init__(self, data_dir=None):
        self.storage = MemoryBackend()
        self.executor = Executor(self.storage)

    def execute(self, sql: str) -> ResultSet:
        sql = sql.strip().rstrip(';')
        tokens = tokenize(sql)
        stmt = parse(tokens)
        return self.executor.execute(stmt)
