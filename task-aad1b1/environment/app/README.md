# Persistent Map Store

Immutable hash map implementation for versioned data management.

## Module layout

- `store/persistent_map.py` — core persistent map implementation
- `store/__init__.py` — package exports
- `issues/` — reported defect tickets and feature requests
- `benchmarks/run_bench.py` — diagnostic and benchmark suite

## Quick start

    make smoke          # basic insert/lookup sanity check
    make bench          # run diagnostic checks
    make profile        # memory profiling with tracemalloc
    make profile-merge  # merge performance with cProfile
    make check-all      # run all checks and profiles

## API

The `PersistentMap` class supports:

- `insert(key, value) -> PersistentMap`
- `delete(key) -> PersistentMap` (raises `KeyError` if absent)
- `get(key, default=None)`, `__getitem__`, `__contains__`
- `__len__`, `__iter__` (yields keys)
- `items()`, `keys()`, `values()`
- `from_dict(d)`, `to_dict()`
- `diff(other) -> set` — keys that differ between two maps
- `merge(other, conflict_fn=None) -> PersistentMap` — merge two maps (see issue 004)
- `_root_node()` — exposes internal trie root for diagnostics
