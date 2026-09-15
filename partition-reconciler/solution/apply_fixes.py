#!/usr/bin/env python3
"""Apply all fixes to the partition reconciliation system.


Fixes span three layers:

Code layer (reconciler.py, mappings.py, io_manager.py, db_store.py):
  1. reconciler.py topo_sort: pre-order DFS -> post-order DFS
  2. reconciler.py _is_stale: comparison inverted (< -> >)
  3. reconciler.py _is_stale: no transitive staleness propagation
  4. reconciler.py _is_stale: staleness_mode "all" not implemented
  5. mappings.py get_upstream_keys: independent iteration -> Cartesian product
  6. io_manager.py write: raw partition key path -> encoded path via get_path()
  7. db_store.py get_record: missing ORDER BY timestamp DESC for duplicates
  8. db_store.py get_record: no millisecond timestamp normalization

Config layer (pipeline.yaml):
  9. time_dimension value "date" -> "day" to match the actual dimension name
"""

import shutil


def fix_reconciler():
    """Replace reconciler.py with corrected version."""
    shutil.copy("/solution/reconciler_fixed.py", "/app/reconciler.py")
    print("Fixed reconciler.py: topo_sort, staleness comparison, "
          "transitive propagation, staleness_mode support")


def fix_db_store():
    """Replace db_store.py with corrected version."""
    shutil.copy("/solution/db_store_fixed.py", "/app/db_store.py")
    print("Fixed db_store.py: duplicate handling (ORDER BY DESC), "
          "timestamp normalization (ms -> s)")


def fix_mappings():
    """Fix Cartesian product in MultiToDailyMapping.get_upstream_keys."""
    with open("/app/mappings.py", "r") as f:
        content = f.read()

    old = (
        "        keys = []\n"
        "        for dim_name, dim_keys in non_time_dims.items():\n"
        "            for dim_val in dim_keys:\n"
        "                key_dict = {self.time_dimension: downstream_key, dim_name: dim_val}\n"
        "                keys.append(str(MultiPartitionKey(key_dict)))\n"
        "        return keys"
    )

    new = (
        "        from itertools import product as _product\n"
        "        dim_names = sorted(non_time_dims.keys())\n"
        "        dim_key_lists = [non_time_dims[n] for n in dim_names]\n"
        "        keys = []\n"
        "        for combo in _product(*dim_key_lists):\n"
        "            key_dict = {self.time_dimension: downstream_key}\n"
        "            for name, val in zip(dim_names, combo):\n"
        "                key_dict[name] = val\n"
        "            keys.append(str(MultiPartitionKey(key_dict)))\n"
        "        return keys"
    )

    content = content.replace(old, new)

    with open("/app/mappings.py", "w") as f:
        f.write(content)
    print("Fixed mappings.py: Cartesian product for multi-dimension upstream keys")


def fix_io_manager():
    """Fix write() to use the same path encoding as read()."""
    with open("/app/io_manager.py", "r") as f:
        content = f.read()

    content = content.replace(
        '        path = os.path.join(self.base_path, asset_key, partition_key, "data.json")',
        "        path = self.get_path(asset_key, partition_key)",
    )

    with open("/app/io_manager.py", "w") as f:
        f.write(content)
    print("Fixed io_manager.py: write() now uses same path encoding as read()")


def fix_pipeline_config():
    """Fix time_dimension in pipeline.yaml."""
    with open("/app/pipeline.yaml", "r") as f:
        content = f.read()

    content = content.replace(
        "time_dimension: date",
        "time_dimension: day",
    )

    with open("/app/pipeline.yaml", "w") as f:
        f.write(content)
    print("Fixed pipeline.yaml: time_dimension 'date' -> 'day'")


if __name__ == "__main__":
    fix_reconciler()
    fix_db_store()
    fix_mappings()
    fix_io_manager()
    fix_pipeline_config()
    print("\nAll fixes applied successfully.")
