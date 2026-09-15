from .types import ColumnDef, ColumnType


class StorageError(Exception):
    pass


class TableSchema:
    def __init__(self, name: str, columns: list):
        self.name = name
        self.columns = columns
        self.col_names = [c.name for c in columns]
        self.col_types = {c.name: c.col_type for c in columns}


class MemoryBackend:
    def __init__(self):
        self.schemas = {}
        self.tables = {}

    def create_table(self, name: str, columns: list):
        if name in self.schemas:
            raise StorageError(f"Table '{name}' already exists")
        self.schemas[name] = TableSchema(name, columns)
        self.tables[name] = []

    def _check_table(self, name: str):
        if name not in self.schemas:
            raise StorageError(f"Table '{name}' does not exist")

    def insert(self, table: str, columns: list, values: list):
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
                raise StorageError(
                    f"Unknown column '{col_name}' in table '{table}'"
                )
            row[col_name] = self._cast(val, schema.col_types[col_name])
        for col_name in schema.col_names:
            if col_name not in row:
                row[col_name] = None
        self.tables[table].append(row)

    def select(self, table: str, columns: list, where=None):
        self._check_table(table)
        schema = self.schemas[table]
        if columns == ['*']:
            columns = schema.col_names
        rows = self.tables[table]
        if where is not None:
            rows = [r for r in rows if self._eval_where(r, where)]
        result = []
        for r in rows:
            result.append([r.get(c) for c in columns])
        return columns, result

    def update(self, table: str, assignments: list, where=None):
        self._check_table(table)
        schema = self.schemas[table]
        count = 0
        for row in self.tables[table]:
            if where is None or self._eval_where(row, where):
                for col, val in assignments:
                    if col not in schema.col_types:
                        raise StorageError(
                            f"Unknown column '{col}' in table '{table}'"
                        )
                    row[col] = self._cast(val, schema.col_types[col])
                count += 1
        return count

    def delete(self, table: str, where=None):
        self._check_table(table)
        original_len = len(self.tables[table])
        if where is None:
            self.tables[table] = []
        else:
            self.tables[table] = [
                r for r in self.tables[table]
                if not self._eval_where(r, where)
            ]
        return original_len - len(self.tables[table])

    def _eval_where(self, row, expr):
        from .parser import BinaryExpr, LogicalExpr
        if isinstance(expr, BinaryExpr):
            left = row.get(expr.column)
            right = expr.value
            op = expr.op
            if left is None or right is None:
                return op == '=' and left is right
            if op == '=':
                return left == right
            elif op == '!=':
                return left != right
            elif op == '<':
                return left < right
            elif op == '>':
                return left > right
            elif op == '<=':
                return left <= right
            elif op == '>=':
                return left >= right
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
