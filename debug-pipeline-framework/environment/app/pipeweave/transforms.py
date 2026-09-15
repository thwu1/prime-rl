"""Built-in data transformation functions for pipeline stages.

All transforms operate on lists of record dicts and return new lists.
"""
from collections import defaultdict
import copy


class TransformError(Exception):
    pass


class TransformRegistry:
    """Named registry of transform functions."""

    _transforms = {}

    @classmethod
    def register(cls, name):
        def decorator(fn):
            cls._transforms[name] = fn
            return fn
        return decorator

    @classmethod
    def get(cls, name):
        if name not in cls._transforms:
            raise TransformError(f"Unknown transform: {name}")
        return cls._transforms[name]

    @classmethod
    def list_transforms(cls):
        return list(cls._transforms.keys())


def filter_records(records, predicate):
    """Keep only records satisfying *predicate*."""
    return [r for r in records if predicate(r)]


def map_fields(records, field_map):
    """Rename fields according to *field_map* ``{old: new}``."""
    result = []
    for record in records:
        new_record = {}
        for key, value in record.items():
            new_record[field_map.get(key, key)] = value
        result.append(new_record)
    return result


def add_computed_field(records, field_name, compute_fn):
    """Add a new field whose value is ``compute_fn(record)``."""
    result = []
    for record in records:
        new_record = dict(record)
        new_record[field_name] = compute_fn(record)
        result.append(new_record)
    return result


def group_by(records, key_field, agg_fn=None):
    """Group by *key_field*; optionally aggregate each group."""
    groups = defaultdict(list)
    for record in records:
        groups[record.get(key_field)].append(record)
    if agg_fn:
        return {k: agg_fn(v) for k, v in groups.items()}
    return dict(groups)


def sort_records(records, key_field, reverse=False):
    """Sort records by *key_field* (None-safe)."""
    return sorted(
        records,
        key=lambda r: (r.get(key_field) is None, r.get(key_field, '')),
        reverse=reverse,
    )


def merge_records(left, right, on, how='inner'):
    """Merge two record lists on a common key field.

    *how* controls join semantics:

    - ``'inner'``: only matching keys
    - ``'left'``: all left records; right fields are ``None`` when unmatched
    - ``'outer'``: all records from both sides; missing fields are ``None``

    For outer joins, unmatched records from *either* side must carry
    all fields from the other side (set to ``None``) **plus** all of
    their own fields.
    """
    right_index = defaultdict(list)
    right_matched = set()

    for i, record in enumerate(right):
        right_index[record.get(on)].append((i, record))

    # Collect field names from each side
    left_fields = set()
    right_fields = set()
    for r in left:
        left_fields.update(r.keys())
    for r in right:
        right_fields.update(r.keys())

    result = []

    for left_record in left:
        left_key = left_record.get(on)
        matches = right_index.get(left_key, [])

        if matches:
            for idx, right_record in matches:
                result.append({**left_record, **right_record})
                right_matched.add(idx)
        elif how in ('left', 'outer'):
            padded = dict(left_record)
            for field in right_fields:
                if field not in padded:
                    padded[field] = None
            result.append(padded)

    # Unmatched right records (outer join only)
    if how == 'outer':
        for i, record in enumerate(right):
            if i not in right_matched:
                padded = {}
                for field in left_fields:
                    padded[field] = None
                for field in left_fields:
                    if field in record:
                        padded[field] = record[field]
                result.append(padded)

    return result


def deduplicate(records, key_field, keep='first'):
    """Remove duplicates by *key_field*; keep ``'first'`` or ``'last'``."""
    seen = {}
    for record in records:
        key = record.get(key_field)
        if keep == 'first':
            if key not in seen:
                seen[key] = record
        else:
            seen[key] = record
    return list(seen.values())


def flatten_nested(records, nested_field, prefix=None):
    """Flatten a nested dict field into dotted keys on the parent record.

    ``{'name': 'x', 'meta': {'a': 1}}`` becomes ``{'name': 'x', 'meta.a': 1}``
    """
    prefix = prefix or nested_field
    result = []
    for record in records:
        new_record = {}
        for key, value in record.items():
            if key == nested_field and isinstance(value, dict):
                for nk, nv in value.items():
                    new_record[f"{prefix}.{nk}"] = nv
            else:
                new_record[key] = value
        result.append(new_record)
    return result
