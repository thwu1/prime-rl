
import pytest
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc
import pyarrow.dataset as ds
import json
import os
from datetime import datetime, timezone

COMPACTED_PATH = '/app/output/compacted'
QUARANTINE_PATH = '/app/output/quarantine.parquet'
MANIFEST_PATH = '/app/output/manifest.json'
STAGING_PATH = '/app/staging'


class TestCompactedDataset:
    """Verify the compacted partitioned Parquet dataset."""

    @pytest.fixture(autouse=True)
    def setup(self):
        assert os.path.isdir(COMPACTED_PATH), \
            f"Compacted output directory not found: {COMPACTED_PATH}"
        self.dataset = ds.dataset(
            COMPACTED_PATH, format='parquet', partitioning='hive')
        self.table = self.dataset.to_table()

    def test_total_output_rows(self):
        """Total rows after dedup and quarantine: 3240."""
        assert len(self.table) == 3240

    def test_three_partitions_exist(self):
        """Exactly 3 Hive partitions: 2024-01, 2024-02, 2024-03."""
        partitions = sorted([
            d for d in os.listdir(COMPACTED_PATH)
            if os.path.isdir(os.path.join(COMPACTED_PATH, d))
        ])
        expected = ['year_month=2024-01', 'year_month=2024-02', 'year_month=2024-03']
        assert partitions == expected, f"Expected {expected}, got {partitions}"

    def test_partition_2024_01_row_count(self):
        """Partition 2024-01: 500 (file 1) + 520 (file 3 v2) = 1020 rows."""
        part_path = os.path.join(COMPACTED_PATH, 'year_month=2024-01')
        t = ds.dataset(part_path, format='parquet').to_table()
        assert len(t) == 1020, f"Expected 1020, got {len(t)}"

    def test_partition_2024_02_row_count(self):
        """Partition 2024-02: 600 (file 4) - 5 quarantined + 600 (file 5) = 1195 rows."""
        part_path = os.path.join(COMPACTED_PATH, 'year_month=2024-02')
        t = ds.dataset(part_path, format='parquet').to_table()
        assert len(t) == 1195, f"Expected 1195, got {len(t)}"

    def test_partition_2024_03_row_count(self):
        """Partition 2024-03: 500 (file 6) - 3 quarantined + 530 (file 8 v2) - 2 quarantined = 1025."""
        part_path = os.path.join(COMPACTED_PATH, 'year_month=2024-03')
        t = ds.dataset(part_path, format='parquet').to_table()
        assert len(t) == 1025, f"Expected 1025, got {len(t)}"

    def test_physical_schema_columns(self):
        """Partition files have exactly 9 data columns (no year_month in data)."""
        fragments = list(self.dataset.get_fragments())
        schema = fragments[0].physical_schema
        expected_cols = {
            'event_id', 'timestamp', 'amount', 'user_id', 'category',
            'status', 'region', 'channel', 'risk_score'
        }
        actual_cols = set(schema.names)
        assert expected_cols == actual_cols, \
            f"Missing: {expected_cols - actual_cols}, Extra: {actual_cols - expected_cols}"

    def test_schema_type_event_id(self):
        fragments = list(self.dataset.get_fragments())
        assert fragments[0].physical_schema.field('event_id').type == pa.int64()

    def test_schema_type_timestamp(self):
        fragments = list(self.dataset.get_fragments())
        assert fragments[0].physical_schema.field('timestamp').type == pa.timestamp('us', tz='UTC')

    def test_schema_type_amount(self):
        fragments = list(self.dataset.get_fragments())
        assert fragments[0].physical_schema.field('amount').type == pa.float64()

    def test_schema_type_user_id(self):
        fragments = list(self.dataset.get_fragments())
        assert fragments[0].physical_schema.field('user_id').type == pa.int64()

    def test_schema_type_risk_score(self):
        fragments = list(self.dataset.get_fragments())
        assert fragments[0].physical_schema.field('risk_score').type == pa.float64()

    def test_no_null_event_ids_in_output(self):
        """All output event_ids must be non-null."""
        assert self.table.column('event_id').null_count == 0

    def test_no_negative_amounts_in_output(self):
        """All output amounts must be non-negative."""
        amounts = self.table.column('amount')
        min_amount = pc.min(amounts).as_py()
        assert min_amount >= 0, f"Found negative amount: {min_amount}"

    def test_no_future_timestamps_in_output(self):
        """All output timestamps must be before 2025-01-01 UTC."""
        timestamps = self.table.column('timestamp')
        max_ts = pc.max(timestamps).as_py()
        cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert max_ts < cutoff, f"Found future timestamp: {max_ts}"

    def test_dedup_jan_prefers_v2_file(self):
        """For overlapping event_id 10500, amount must come from batch_2024_01_b_v2."""
        v2 = pq.read_table(os.path.join(STAGING_PATH, 'batch_2024_01_b_v2.parquet'))
        v2_amount = float(v2.column('amount')[0].as_py())

        orig = pq.read_table(os.path.join(STAGING_PATH, 'batch_2024_01_b.parquet'))
        orig_amount = float(orig.column('amount')[0].as_py())

        # Sanity: v2 and original should differ (different RNG seeds)
        assert abs(v2_amount - orig_amount) > 0.001, \
            "v2 and original amounts unexpectedly identical"

        # Output must match v2
        mask = pc.equal(self.table.column('event_id'), 10500)
        filtered = self.table.filter(mask)
        assert len(filtered) == 1, f"Expected 1 row for event_id=10500, got {len(filtered)}"
        output_amount = filtered.column('amount')[0].as_py()
        assert abs(output_amount - v2_amount) < 0.01, \
            f"Expected v2 amount {v2_amount}, got {output_amount}"

    def test_dedup_mar_prefers_v2_file(self):
        """For overlapping event_id 30500, amount must come from batch_2024_03_b_v2."""
        v2 = pq.read_table(os.path.join(STAGING_PATH, 'batch_2024_03_b_v2.parquet'))
        v2_amount = float(v2.column('amount')[0].as_py())

        orig = pq.read_table(os.path.join(STAGING_PATH, 'batch_2024_03_b.parquet'))
        orig_amount = float(orig.column('amount')[0].as_py())

        assert abs(v2_amount - orig_amount) > 0.001, \
            "v2 and original amounts unexpectedly identical"

        mask = pc.equal(self.table.column('event_id'), 30500)
        filtered = self.table.filter(mask)
        assert len(filtered) == 1
        output_amount = filtered.column('amount')[0].as_py()
        assert abs(output_amount - v2_amount) < 0.01, \
            f"Expected v2 amount {v2_amount}, got {output_amount}"

    def test_epoch1_missing_columns_are_null(self):
        """Epoch 1 records (event_id 10000-11019) lack region, channel, risk_score."""
        mask = pc.and_(
            pc.greater_equal(self.table.column('event_id'), 10000),
            pc.less(self.table.column('event_id'), 11020)
        )
        epoch1 = self.table.filter(mask)
        assert len(epoch1) == 1020, f"Expected 1020 epoch-1 rows, got {len(epoch1)}"
        assert epoch1.column('region').null_count == len(epoch1), \
            "Epoch-1 records should have null region"
        assert epoch1.column('channel').null_count == len(epoch1), \
            "Epoch-1 records should have null channel"
        assert epoch1.column('risk_score').null_count == len(epoch1), \
            "Epoch-1 records should have null risk_score"

    def test_epoch2_risk_score_null_region_present(self):
        """Epoch 2 records (event_id 20000-30499) have region but lack risk_score."""
        mask = pc.and_(
            pc.greater_equal(self.table.column('event_id'), 20000),
            pc.less(self.table.column('event_id'), 30500)
        )
        epoch2 = self.table.filter(mask)
        assert epoch2.column('risk_score').null_count == len(epoch2), \
            "Epoch-2 records should have null risk_score"
        assert epoch2.column('region').null_count == 0, \
            "Epoch-2 records should have non-null region"

    def test_all_timestamps_utc_microseconds(self):
        """Every partition file has timestamp[us, tz=UTC]."""
        for frag in self.dataset.get_fragments():
            ts_type = frag.physical_schema.field('timestamp').type
            assert ts_type == pa.timestamp('us', tz='UTC'), \
                f"Expected timestamp[us, tz=UTC], got {ts_type}"

    def test_compression_zstd(self):
        """All output Parquet files use ZSTD compression."""
        for part_dir in sorted(os.listdir(COMPACTED_PATH)):
            part_path = os.path.join(COMPACTED_PATH, part_dir)
            if not os.path.isdir(part_path):
                continue
            for fname in os.listdir(part_path):
                if not fname.endswith('.parquet'):
                    continue
                pf = pq.ParquetFile(os.path.join(part_path, fname))
                comp = pf.metadata.row_group(0).column(0).compression.upper()
                assert comp in ('ZSTD', 'ZSTANDARD'), \
                    f"Expected ZSTD, got {comp} in {part_dir}/{fname}"

    def test_sorted_within_partitions(self):
        """Timestamps are sorted ascending within each partition file."""
        for part_dir in sorted(os.listdir(COMPACTED_PATH)):
            part_path = os.path.join(COMPACTED_PATH, part_dir)
            if not os.path.isdir(part_path):
                continue
            for fname in sorted(os.listdir(part_path)):
                if not fname.endswith('.parquet'):
                    continue
                t = pq.read_table(os.path.join(part_path, fname))
                timestamps = t.column('timestamp').to_pylist()
                assert timestamps == sorted(timestamps), \
                    f"Timestamps not sorted in {part_dir}/{fname}"

    def test_new_ids_from_retry_files_present(self):
        """New IDs added by retry files (11000-11019, 31000-31029) are in output."""
        # Check a few new IDs from batch_2024_01_b_v2
        for eid in [11000, 11010, 11019]:
            mask = pc.equal(self.table.column('event_id'), eid)
            filtered = self.table.filter(mask)
            assert len(filtered) == 1, f"New event_id {eid} from v2 file not found"

        # Check a few new IDs from batch_2024_03_b_v2 (excluding quarantined 31010, 31020)
        for eid in [31000, 31005, 31029]:
            mask = pc.equal(self.table.column('event_id'), eid)
            filtered = self.table.filter(mask)
            assert len(filtered) == 1, f"New event_id {eid} from v2 file not found"


class TestQuarantineFile:
    """Verify the quarantine output."""

    @pytest.fixture(autouse=True)
    def setup(self):
        assert os.path.exists(QUARANTINE_PATH), \
            f"Quarantine file not found: {QUARANTINE_PATH}"
        self.table = pq.read_table(QUARANTINE_PATH)

    def test_quarantine_row_count(self):
        """Exactly 10 records quarantined: 5 null_id + 3 neg_amount + 2 future_ts."""
        assert len(self.table) == 10

    def test_quarantine_has_reason_column(self):
        assert 'quarantine_reason' in self.table.column_names

    def test_quarantine_null_event_id_count(self):
        """5 quarantined records have null event_id."""
        assert self.table.column('event_id').null_count == 5

    def test_quarantine_negative_amount_count(self):
        """3 quarantined records have negative amounts."""
        amounts = self.table.column('amount').to_pylist()
        neg_count = sum(1 for a in amounts if a is not None and a < 0)
        assert neg_count == 3

    def test_quarantine_future_timestamp_count(self):
        """2 quarantined records have timestamps in 2025."""
        timestamps = self.table.column('timestamp').to_pylist()
        future_count = sum(
            1 for t in timestamps if t is not None and t.year >= 2025)
        assert future_count == 2


class TestManifest:
    """Verify the compaction manifest."""

    @pytest.fixture(autouse=True)
    def setup(self):
        assert os.path.exists(MANIFEST_PATH), \
            f"Manifest not found: {MANIFEST_PATH}"
        with open(MANIFEST_PATH) as f:
            self.manifest = json.load(f)

    def test_total_input_rows(self):
        assert self.manifest['total_input_rows'] == 4250

    def test_total_output_rows(self):
        assert self.manifest['total_output_rows'] == 3240

    def test_total_quarantined(self):
        assert self.manifest['total_quarantined'] == 10

    def test_duplicates_removed(self):
        assert self.manifest['duplicates_removed'] == 1000

    def test_files_processed(self):
        assert self.manifest['files_processed'] == 8

    def test_partition_counts(self):
        partitions = self.manifest['partitions']
        parts_dict = {p['year_month']: p['row_count'] for p in partitions}
        assert parts_dict == {
            '2024-01': 1020,
            '2024-02': 1195,
            '2024-03': 1025
        }, f"Partition counts mismatch: {parts_dict}"
