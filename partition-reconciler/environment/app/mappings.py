"""Partition mapping classes for cross-granularity partition resolution."""

from partitions import MultiPartitionKey
from datetime import datetime, timedelta


class PartitionMapping:
    """Maps partition keys between two partition definitions."""
    def get_downstream_keys(self, upstream_key):
        raise NotImplementedError

    def get_upstream_keys(self, downstream_key):
        raise NotImplementedError


class IdentityMapping(PartitionMapping):
    """One-to-one mapping between identical partition schemes."""
    def get_downstream_keys(self, upstream_key):
        return [upstream_key]

    def get_upstream_keys(self, downstream_key):
        return [downstream_key]


class HourlyToDailyMapping(PartitionMapping):
    """Maps hourly upstream partitions to daily downstream partitions."""
    def __init__(self, hourly_def, daily_def):
        self.hourly_def = hourly_def
        self.daily_def = daily_def

    def get_downstream_keys(self, upstream_key):
        dt = datetime.strptime(upstream_key, "%Y-%m-%dT%H:%M")
        daily_key = dt.strftime("%Y-%m-%d")
        if daily_key in self.daily_def.get_keys():
            return [daily_key]
        return []

    def get_upstream_keys(self, downstream_key):
        day = datetime.strptime(downstream_key, "%Y-%m-%d")
        keys = []
        all_hourly = set(self.hourly_def.get_keys())
        for h in range(24):
            hourly_key = (day + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
            if hourly_key in all_hourly:
                keys.append(hourly_key)
        return keys


class MultiToDailyMapping(PartitionMapping):
    """Maps multi-partitioned upstream (with a time dimension) to daily downstream.

    The multi-partition has a time dimension (DailyPartitionDef) and one or more
    static dimensions. This mapping projects onto the time dimension, so each
    daily downstream partition maps to all multi-partition keys for that day
    across the Cartesian product of all static dimensions.
    """
    def __init__(self, multi_def, daily_def, time_dimension="day"):
        self.multi_def = multi_def
        self.daily_def = daily_def
        self.time_dimension = time_dimension

    def get_downstream_keys(self, upstream_key):
        mpk = MultiPartitionKey.from_str(upstream_key)
        daily_key = mpk.keys_by_dimension[self.time_dimension]
        if daily_key in self.daily_def.get_keys():
            return [daily_key]
        return []

    def get_upstream_keys(self, downstream_key):
        """Given a daily key, return all multi-partition keys for that day.

        Must produce the Cartesian product of all non-time dimensions
        combined with the given day for the time dimension.
        """
        non_time_dims = {
            name: defn.get_keys()
            for name, defn in self.multi_def.dimensions.items()
            if name != self.time_dimension
        }

        keys = []
        for dim_name, dim_keys in non_time_dims.items():
            for dim_val in dim_keys:
                key_dict = {self.time_dimension: downstream_key, dim_name: dim_val}
                keys.append(str(MultiPartitionKey(key_dict)))
        return keys
