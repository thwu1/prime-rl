"""
"""

import os
import json
import pytest
import pyarrow.parquet as pq

BASELINE = '/app/data/baseline.parquet'
OPTIMIZED = '/app/output/optimized.parquet'
ANALYSIS = '/app/output/analysis.json'


# ---------------------------------------------------------------------------
# 1. File existence & validity
# ---------------------------------------------------------------------------
class TestOptimizedFileExists:
    def test_file_exists(self):
        assert os.path.isfile(OPTIMIZED), \
            f"Optimized Parquet file not found at {OPTIMIZED}"

    def test_file_is_valid_parquet(self):
        pf = pq.ParquetFile(OPTIMIZED)
        assert pf.metadata.num_rows > 0, "Optimized file has zero rows"


class TestAnalysisFileExists:
    def test_file_exists(self):
        assert os.path.isfile(ANALYSIS), \
            f"Analysis JSON not found at {ANALYSIS}"

    def test_valid_json(self):
        with open(ANALYSIS) as f:
            data = json.load(f)
        assert isinstance(data, dict), "Analysis JSON root must be an object"


# ---------------------------------------------------------------------------
# 2. Data integrity
# ---------------------------------------------------------------------------
class TestDataIntegrity:
    def test_row_count_matches(self):
        import duckdb
        con = duckdb.connect()
        baseline_count = con.execute(
            "SELECT count(*) FROM read_parquet(?)", [BASELINE]
        ).fetchone()[0]
        optimized_count = con.execute(
            "SELECT count(*) FROM read_parquet(?)", [OPTIMIZED]
        ).fetchone()[0]
        assert baseline_count == optimized_count, \
            f"Row count mismatch: baseline={baseline_count}, optimized={optimized_count}"

    def test_column_names_match(self):
        baseline_schema = pq.read_schema(BASELINE)
        optimized_schema = pq.read_schema(OPTIMIZED)
        assert set(baseline_schema.names) == set(optimized_schema.names), \
            f"Column mismatch: baseline={sorted(baseline_schema.names)}, " \
            f"optimized={sorted(optimized_schema.names)}"

    def test_aggregate_checksums(self):
        """Verify data integrity via multiple aggregate comparisons."""
        import duckdb
        con = duckdb.connect()

        agg_query = """
            SELECT
                sum(record_id) AS sum_id,
                min(record_id) AS min_id,
                max(record_id) AS max_id,
                min(event_timestamp) AS min_ts,
                max(event_timestamp) AS max_ts,
                count(DISTINCT device_id) AS n_devices,
                count(DISTINCT sensor_type) AS n_types,
                sum(quality) AS sum_quality,
                count(*) FILTER (WHERE is_valid) AS n_valid,
                count(DISTINCT metadata_json) AS n_json
            FROM read_parquet(?)
        """

        baseline_aggs = con.execute(agg_query, [BASELINE]).fetchone()
        optimized_aggs = con.execute(agg_query, [OPTIMIZED]).fetchone()

        labels = [
            'sum(record_id)', 'min(record_id)', 'max(record_id)',
            'min(event_timestamp)', 'max(event_timestamp)',
            'count(DISTINCT device_id)', 'count(DISTINCT sensor_type)',
            'sum(quality)', 'count(is_valid=true)',
            'count(DISTINCT metadata_json)'
        ]

        for label, b, o in zip(labels, baseline_aggs, optimized_aggs):
            if isinstance(b, float):
                assert abs(b - o) < 1e-6, \
                    f"Aggregate '{label}' mismatch: baseline={b}, optimized={o}"
            else:
                assert b == o, \
                    f"Aggregate '{label}' mismatch: baseline={b}, optimized={o}"

    def test_reading_values_match(self):
        """Verify floating-point columns are preserved exactly."""
        import duckdb
        con = duckdb.connect()

        for col in ['reading', 'latitude', 'longitude']:
            baseline_hash = con.execute(
                f"SELECT sum(hash(CAST(\"{col}\" AS VARCHAR))) FROM read_parquet(?)",
                [BASELINE]
            ).fetchone()[0]
            optimized_hash = con.execute(
                f"SELECT sum(hash(CAST(\"{col}\" AS VARCHAR))) FROM read_parquet(?)",
                [OPTIMIZED]
            ).fetchone()[0]
            assert baseline_hash == optimized_hash, \
                f"Hash mismatch for column '{col}': data values differ"


# ---------------------------------------------------------------------------
# 3. Compression constraints
# ---------------------------------------------------------------------------
class TestCompression:
    def test_file_size_target(self):
        baseline_size = os.path.getsize(BASELINE)
        optimized_size = os.path.getsize(OPTIMIZED)
        ratio = optimized_size / baseline_size
        assert ratio <= 0.20, \
            f"Compression ratio {ratio:.4f} ({ratio:.1%}) exceeds 20% target. " \
            f"Baseline: {baseline_size:,} bytes, Optimized: {optimized_size:,} bytes"

    def test_zstd_compression_codec(self):
        """Every column in every row group must use ZSTD compression."""
        pf = pq.ParquetFile(OPTIMIZED)
        meta = pf.metadata
        for i in range(meta.num_row_groups):
            rg = meta.row_group(i)
            for j in range(rg.num_columns):
                col = rg.column(j)
                assert str(col.compression).upper() == 'ZSTD', \
                    f"Row group {i}, column '{col.path_in_schema}' uses " \
                    f"{col.compression}, expected ZSTD"


# ---------------------------------------------------------------------------
# 4. Row group layout
# ---------------------------------------------------------------------------
class TestRowGroups:
    def test_exactly_four_row_groups(self):
        pf = pq.ParquetFile(OPTIMIZED)
        assert pf.metadata.num_row_groups == 4, \
            f"Expected 4 row groups, found {pf.metadata.num_row_groups}"

    def test_each_row_group_has_250k_rows(self):
        pf = pq.ParquetFile(OPTIMIZED)
        meta = pf.metadata
        for i in range(meta.num_row_groups):
            rg = meta.row_group(i)
            assert rg.num_rows == 250_000, \
                f"Row group {i} has {rg.num_rows:,} rows, expected 250,000"


# ---------------------------------------------------------------------------
# 5. Sort order & non-overlapping timestamp ranges
# ---------------------------------------------------------------------------
class TestSortOrder:
    def _get_timestamp_ranges(self):
        pf = pq.ParquetFile(OPTIMIZED)
        meta = pf.metadata
        ranges = []
        for i in range(meta.num_row_groups):
            rg = meta.row_group(i)
            for j in range(rg.num_columns):
                col = rg.column(j)
                if col.path_in_schema == 'event_timestamp':
                    stats = col.statistics
                    assert stats is not None, \
                        f"Row group {i}: event_timestamp has no statistics"
                    assert stats.has_min_max, \
                        f"Row group {i}: event_timestamp stats lack min/max"
                    ranges.append((stats.min, stats.max))
                    break
        return ranges

    def test_non_overlapping_timestamp_ranges(self):
        ranges = self._get_timestamp_ranges()
        assert len(ranges) == 4, f"Expected 4 timestamp ranges, got {len(ranges)}"
        for i in range(len(ranges) - 1):
            assert ranges[i][1] < ranges[i + 1][0], \
                f"Timestamp ranges overlap between row group {i} " \
                f"(max={ranges[i][1]}) and row group {i + 1} " \
                f"(min={ranges[i + 1][0]})"

    def test_timestamp_ranges_monotonically_increasing(self):
        ranges = self._get_timestamp_ranges()
        for i in range(len(ranges)):
            assert ranges[i][0] <= ranges[i][1], \
                f"Row group {i}: min ({ranges[i][0]}) > max ({ranges[i][1]})"


# ---------------------------------------------------------------------------
# 6. Column statistics
# ---------------------------------------------------------------------------
class TestColumnStatistics:
    def test_record_id_statistics_present(self):
        pf = pq.ParquetFile(OPTIMIZED)
        meta = pf.metadata
        for i in range(meta.num_row_groups):
            rg = meta.row_group(i)
            for j in range(rg.num_columns):
                col = rg.column(j)
                if col.path_in_schema == 'record_id':
                    stats = col.statistics
                    assert stats is not None, \
                        f"Row group {i}: record_id has no statistics"
                    assert stats.has_min_max, \
                        f"Row group {i}: record_id stats lack min/max"
                    break

    def test_event_timestamp_statistics_present(self):
        pf = pq.ParquetFile(OPTIMIZED)
        meta = pf.metadata
        for i in range(meta.num_row_groups):
            rg = meta.row_group(i)
            for j in range(rg.num_columns):
                col = rg.column(j)
                if col.path_in_schema == 'event_timestamp':
                    stats = col.statistics
                    assert stats is not None, \
                        f"Row group {i}: event_timestamp has no statistics"
                    assert stats.has_min_max, \
                        f"Row group {i}: event_timestamp stats lack min/max"
                    break

    def test_record_id_ranges_non_overlapping(self):
        """Since data is sorted by timestamp (which correlates with record_id),
        record_id ranges should also be non-overlapping."""
        pf = pq.ParquetFile(OPTIMIZED)
        meta = pf.metadata
        ranges = []
        for i in range(meta.num_row_groups):
            rg = meta.row_group(i)
            for j in range(rg.num_columns):
                col = rg.column(j)
                if col.path_in_schema == 'record_id':
                    stats = col.statistics
                    ranges.append((stats.min, stats.max))
                    break
        for i in range(len(ranges) - 1):
            assert ranges[i][1] < ranges[i + 1][0], \
                f"record_id ranges overlap between row group {i} and {i + 1}"


# ---------------------------------------------------------------------------
# 7. Per-column encoding verification
# ---------------------------------------------------------------------------
class TestPerColumnEncodings:
    def _get_column_encodings(self):
        """Return dict mapping column name -> set of encoding strings (from RG 0)."""
        pf = pq.ParquetFile(OPTIMIZED)
        rg = pf.metadata.row_group(0)
        result = {}
        for j in range(rg.num_columns):
            col = rg.column(j)
            result[col.path_in_schema] = {str(e) for e in col.encodings}
        return result

    def test_record_id_uses_delta_binary_packed(self):
        encs = self._get_column_encodings()
        assert 'DELTA_BINARY_PACKED' in encs.get('record_id', set()), \
            f"record_id should use DELTA_BINARY_PACKED, found {encs.get('record_id')}"

    def test_event_timestamp_uses_delta_binary_packed(self):
        encs = self._get_column_encodings()
        assert 'DELTA_BINARY_PACKED' in encs.get('event_timestamp', set()), \
            f"event_timestamp should use DELTA_BINARY_PACKED, found {encs.get('event_timestamp')}"

    def test_reading_uses_byte_stream_split(self):
        encs = self._get_column_encodings()
        assert 'BYTE_STREAM_SPLIT' in encs.get('reading', set()), \
            f"reading should use BYTE_STREAM_SPLIT, found {encs.get('reading')}"

    def test_latitude_uses_byte_stream_split(self):
        encs = self._get_column_encodings()
        assert 'BYTE_STREAM_SPLIT' in encs.get('latitude', set()), \
            f"latitude should use BYTE_STREAM_SPLIT, found {encs.get('latitude')}"

    def test_longitude_uses_byte_stream_split(self):
        encs = self._get_column_encodings()
        assert 'BYTE_STREAM_SPLIT' in encs.get('longitude', set()), \
            f"longitude should use BYTE_STREAM_SPLIT, found {encs.get('longitude')}"

    def test_device_id_uses_dictionary(self):
        encs = self._get_column_encodings()
        device_encs = encs.get('device_id', set())
        has_dict = 'RLE_DICTIONARY' in device_encs or 'PLAIN_DICTIONARY' in device_encs
        assert has_dict, \
            f"device_id should use RLE_DICTIONARY, found {device_encs}"

    def test_sensor_type_uses_dictionary(self):
        encs = self._get_column_encodings()
        sensor_encs = encs.get('sensor_type', set())
        has_dict = 'RLE_DICTIONARY' in sensor_encs or 'PLAIN_DICTIONARY' in sensor_encs
        assert has_dict, \
            f"sensor_type should use RLE_DICTIONARY, found {sensor_encs}"


# ---------------------------------------------------------------------------
# 8. File-level Parquet metadata
# ---------------------------------------------------------------------------
class TestFileLevelMetadata:
    def test_optimization_config_key_exists(self):
        pf = pq.ParquetFile(OPTIMIZED)
        kv_meta = pf.schema_arrow.metadata
        assert kv_meta is not None, "Parquet schema metadata is None"
        assert b'optimization_config' in kv_meta, \
            f"Missing 'optimization_config' key in Parquet schema metadata. " \
            f"Keys present: {list(kv_meta.keys())}"

    def test_optimization_config_is_valid_json(self):
        pf = pq.ParquetFile(OPTIMIZED)
        raw = pf.schema_arrow.metadata[b'optimization_config']
        config = json.loads(raw)
        assert isinstance(config, dict), \
            "optimization_config must be a JSON object"

    def test_optimization_config_has_all_columns(self):
        pf = pq.ParquetFile(OPTIMIZED)
        raw = pf.schema_arrow.metadata[b'optimization_config']
        config = json.loads(raw)
        expected_cols = {
            'record_id', 'event_timestamp', 'device_id', 'sensor_type',
            'reading', 'quality', 'is_valid', 'latitude', 'longitude',
            'metadata_json'
        }
        missing = expected_cols - set(config.keys())
        assert not missing, \
            f"optimization_config missing columns: {missing}"

    def test_optimization_config_values_are_strings(self):
        pf = pq.ParquetFile(OPTIMIZED)
        raw = pf.schema_arrow.metadata[b'optimization_config']
        config = json.loads(raw)
        for col, enc in config.items():
            assert isinstance(enc, str) and len(enc) > 0, \
                f"optimization_config['{col}'] must be a non-empty string, got {enc!r}"


# ---------------------------------------------------------------------------
# 9. Analysis JSON content
# ---------------------------------------------------------------------------
class TestAnalysisContent:
    @pytest.fixture
    def analysis(self):
        with open(ANALYSIS) as f:
            return json.load(f)

    def test_required_top_level_keys(self, analysis):
        required = [
            'baseline_size_bytes', 'optimized_size_bytes',
            'compression_ratio', 'num_row_groups', 'compression_codec',
            'row_group_boundaries', 'columns'
        ]
        for key in required:
            assert key in analysis, f"Missing top-level key: '{key}'"

    def test_baseline_size_accurate(self, analysis):
        actual_size = os.path.getsize(BASELINE)
        reported_size = analysis['baseline_size_bytes']
        assert abs(reported_size - actual_size) / actual_size < 0.01, \
            f"Reported baseline size {reported_size:,} doesn't match " \
            f"actual {actual_size:,}"

    def test_optimized_size_accurate(self, analysis):
        actual_size = os.path.getsize(OPTIMIZED)
        reported_size = analysis['optimized_size_bytes']
        assert abs(reported_size - actual_size) / actual_size < 0.01, \
            f"Reported optimized size {reported_size:,} doesn't match " \
            f"actual {actual_size:,}"

    def test_compression_ratio_correct(self, analysis):
        expected = analysis['optimized_size_bytes'] / analysis['baseline_size_bytes']
        reported = analysis['compression_ratio']
        assert abs(reported - expected) < 0.01, \
            f"Compression ratio {reported:.6f} doesn't match " \
            f"computed {expected:.6f}"

    def test_num_row_groups_matches(self, analysis):
        assert analysis['num_row_groups'] == 4, \
            f"num_row_groups should be 4, got {analysis['num_row_groups']}"

    def test_compression_codec_is_zstd(self, analysis):
        assert analysis['compression_codec'].upper() == 'ZSTD', \
            f"compression_codec should be ZSTD, got {analysis['compression_codec']}"

    def test_row_group_boundaries_count(self, analysis):
        assert len(analysis['row_group_boundaries']) == 4, \
            f"Expected 4 row group boundaries, got {len(analysis['row_group_boundaries'])}"

    def test_row_group_boundary_fields(self, analysis):
        required_fields = [
            'row_group_index', 'num_rows', 'min_record_id',
            'max_record_id', 'min_timestamp', 'max_timestamp'
        ]
        for rg in analysis['row_group_boundaries']:
            for field in required_fields:
                assert field in rg, \
                    f"Row group boundary missing field '{field}'"

    def test_row_group_boundary_row_counts(self, analysis):
        for rg in analysis['row_group_boundaries']:
            assert rg['num_rows'] == 250_000, \
                f"Row group {rg.get('row_group_index')}: num_rows should be " \
                f"250000, got {rg['num_rows']}"

    def test_all_columns_documented(self, analysis):
        expected_columns = {
            'record_id', 'event_timestamp', 'device_id', 'sensor_type',
            'reading', 'quality', 'is_valid', 'latitude', 'longitude',
            'metadata_json'
        }
        documented = set(analysis['columns'].keys())
        missing = expected_columns - documented
        assert not missing, f"Missing columns in analysis: {missing}"

    def test_column_detail_fields(self, analysis):
        required_fields = [
            'physical_type', 'encoding', 'cardinality', 'rationale'
        ]
        for col_name, col_info in analysis['columns'].items():
            for field in required_fields:
                assert field in col_info, \
                    f"Column '{col_name}' missing field '{field}'"

    def test_known_cardinalities(self, analysis):
        cols = analysis['columns']

        assert cols['device_id']['cardinality'] == 200, \
            f"device_id cardinality should be 200, " \
            f"got {cols['device_id']['cardinality']}"

        assert cols['sensor_type']['cardinality'] == 8, \
            f"sensor_type cardinality should be 8, " \
            f"got {cols['sensor_type']['cardinality']}"

        assert cols['is_valid']['cardinality'] == 2, \
            f"is_valid cardinality should be 2, " \
            f"got {cols['is_valid']['cardinality']}"

    def test_encoding_rationale_nonempty(self, analysis):
        for col_name, col_info in analysis['columns'].items():
            rationale = col_info.get('rationale', '')
            assert len(rationale) >= 10, \
                f"Column '{col_name}' rationale too short: '{rationale}'"
