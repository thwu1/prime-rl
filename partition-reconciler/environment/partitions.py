"""Partition definition classes for the reconciliation engine."""

from datetime import datetime, timedelta
from itertools import product


class PartitionDef:
    """Base class for partition definitions."""
    def get_keys(self):
        raise NotImplementedError


class DailyPartitionDef(PartitionDef):
    """Generates daily partition keys between start and end dates (inclusive)."""
    def __init__(self, start, end):
        self.start = datetime.strptime(start, "%Y-%m-%d")
        self.end = datetime.strptime(end, "%Y-%m-%d")

    def get_keys(self):
        keys = []
        current = self.start
        while current <= self.end:
            keys.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return keys


class HourlyPartitionDef(PartitionDef):
    """Generates hourly partition keys between start and end times (inclusive)."""
    def __init__(self, start, end):
        self.start = datetime.strptime(start, "%Y-%m-%dT%H:%M")
        self.end = datetime.strptime(end, "%Y-%m-%dT%H:%M")

    def get_keys(self):
        keys = []
        current = self.start
        while current <= self.end:
            keys.append(current.strftime("%Y-%m-%dT%H:%M"))
            current += timedelta(hours=1)
        return keys


class StaticPartitionDef(PartitionDef):
    """A fixed list of partition keys."""
    def __init__(self, keys):
        self._keys = list(keys)

    def get_keys(self):
        return list(self._keys)


class MultiPartitionKey:
    """A key into a multi-dimensional partition space."""
    def __init__(self, keys_by_dimension):
        self.keys_by_dimension = dict(keys_by_dimension)

    def __str__(self):
        parts = sorted(self.keys_by_dimension.items())
        return "|".join(f"{k}={v}" for k, v in parts)

    def __repr__(self):
        return f"MultiPartitionKey({self.keys_by_dimension})"

    def __eq__(self, other):
        if isinstance(other, MultiPartitionKey):
            return self.keys_by_dimension == other.keys_by_dimension
        return False

    def __hash__(self):
        return hash(tuple(sorted(self.keys_by_dimension.items())))

    @staticmethod
    def from_str(s):
        """Parse 'dim1=val1|dim2=val2' into a MultiPartitionKey."""
        parts = s.split("|")
        keys = {}
        for part in parts:
            k, v = part.split("=", 1)
            keys[k] = v
        return MultiPartitionKey(keys)


class MultiPartitionDef(PartitionDef):
    """Multi-dimensional partitions (Cartesian product of dimensions)."""
    def __init__(self, dimensions):
        self.dimensions = dimensions

    def get_keys(self):
        dim_names = sorted(self.dimensions.keys())
        dim_keys = [self.dimensions[name].get_keys() for name in dim_names]
        keys = []
        for combo in product(*dim_keys):
            mpk = MultiPartitionKey(dict(zip(dim_names, combo)))
            keys.append(str(mpk))
        return keys

    def get_dimension(self, name):
        return self.dimensions[name]

    def get_dimension_names(self):
        return sorted(self.dimensions.keys())
