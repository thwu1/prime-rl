"""
Vitess-compatible VDiff implementation (complete).
Compares data between source and target shards to verify consistency.
"""
import sqlite3
from config import SOURCE_SHARDS, TARGET_SHARDS, TABLES, TABLE_PKS


class VDiffResult:
    """Result of a VDiff operation."""
    def __init__(self):
        self.consistent = False
        self.tables = {}
        self.errors = []


def run_vdiff(source_shards=None, target_shards=None):
    """
    Run VDiff to verify data consistency between source and target shards.

    Collects all rows from source and target shards keyed by primary key,
    then compares for missing, extra, or mismatched rows.
    """
    if source_shards is None:
        source_shards = SOURCE_SHARDS
    if target_shards is None:
        target_shards = TARGET_SHARDS

    result = VDiffResult()
    all_match = True

    for table in TABLES:
        pk = TABLE_PKS[table]

        # Get column metadata from first source shard
        first_src = next(iter(source_shards.values()))
        meta_conn = sqlite3.connect(first_src)
        cursor = meta_conn.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]
        pk_idx = columns.index(pk)
        meta_conn.close()

        # Collect all rows from source shards
        source_data = {}
        for db_path in source_shards.values():
            conn = sqlite3.connect(db_path)
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                source_data[row[pk_idx]] = tuple(row)
            conn.close()

        # Collect all rows from target shards
        target_data = {}
        for db_path in target_shards.values():
            conn = sqlite3.connect(db_path)
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                target_data[row[pk_idx]] = tuple(row)
            conn.close()

        # Compare
        table_result = {
            'source_count': len(source_data),
            'target_count': len(target_data),
            'missing_in_target': [],
            'extra_in_target': [],
            'mismatched': [],
        }

        # Check for missing or mismatched rows
        for pk_val, src_row in source_data.items():
            if pk_val not in target_data:
                table_result['missing_in_target'].append(pk_val)
                all_match = False
            elif src_row != target_data[pk_val]:
                table_result['mismatched'].append(pk_val)
                all_match = False

        # Check for extra rows in target
        for pk_val in target_data:
            if pk_val not in source_data:
                table_result['extra_in_target'].append(pk_val)
                all_match = False

        result.tables[table] = table_result

        if table_result['missing_in_target']:
            result.errors.append(
                f"Table {table}: {len(table_result['missing_in_target'])} rows missing in target"
            )
        if table_result['extra_in_target']:
            result.errors.append(
                f"Table {table}: {len(table_result['extra_in_target'])} extra rows in target"
            )
        if table_result['mismatched']:
            result.errors.append(
                f"Table {table}: {len(table_result['mismatched'])} rows with mismatched data"
            )

    result.consistent = all_match
    return result
