"""Core DataFrame implementation"""

import csv
import json


class DataFrame:
    """Simple DataFrame implementation for data manipulation."""

    def __init__(self, data=None, columns=None):
        self._data = data or []
        self._columns = columns or []

    @classmethod
    def from_csv(cls, filepath, delimiter=','):
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            columns = reader.fieldnames or []
            data = list(reader)
        return cls(data, columns)

    @classmethod
    def from_json(cls, filepath):
        with open(filepath, 'r') as f:
            data = json.load(f)
        if isinstance(data, list) and len(data) > 0:
            columns = list(data[0].keys())
        else:
            columns = []
        return cls(data, columns)

    @property
    def shape(self):
        return (len(self._data), len(self._columns))

    @property
    def columns(self):
        return self._columns

    def head(self, n=5):
        return DataFrame(self._data[:n], self._columns)

    def tail(self, n=5):
        return DataFrame(self._data[-n:], self._columns)

    def select(self, columns):
        data = [{k: row.get(k) for k in columns} for row in self._data]
        return DataFrame(data, columns)

    def filter(self, predicate):
        data = [row for row in self._data if predicate(row)]
        return DataFrame(data, self._columns)

    def to_dict(self):
        return self._data

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return f"DataFrame(rows={len(self._data)}, columns={self._columns})"
