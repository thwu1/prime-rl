
"""
Tests for the SQLite WAL forensics tool.

Validates binary parsing, checksum computation, transaction identification,
database reconstruction, and corruption detection.
"""

import pytest
import sys
import os
import sqlite3
import shutil
import struct

sys.path.insert(0, '/app')

DB_PATH = '/app/forensic.db'
WAL_PATH = '/app/forensic.db-wal'

WAL_HEADER_SIZE = 32
FRAME_HEADER_SIZE = 24


# ---------------------------------------------------------------------------
# WAL header parsing
# ---------------------------------------------------------------------------

class TestWALHeaderParsing:

    def test_magic_number(self):
        from wal_forensics import parse_wal_header
        header = parse_wal_header(WAL_PATH)
        assert header['magic'] in (0x377f0682, 0x377f0683), \
            f"Invalid WAL magic: 0x{header['magic']:08x}"

    def test_version(self):
        from wal_forensics import parse_wal_header
        header = parse_wal_header(WAL_PATH)
        assert header['version'] == 3007000

    def test_page_size(self):
        from wal_forensics import parse_wal_header
        header = parse_wal_header(WAL_PATH)
        assert header['page_size'] == 4096

    def test_big_endian_flag_consistent(self):
        from wal_forensics import parse_wal_header
        header = parse_wal_header(WAL_PATH)
        expected = (header['magic'] == 0x377f0683)
        assert header['big_endian_checksums'] == expected

    def test_header_checksum_valid(self):
        from wal_forensics import parse_wal_header
        header = parse_wal_header(WAL_PATH)
        assert header['header_checksum_valid'] is True

    def test_salt_values_nonzero(self):
        from wal_forensics import parse_wal_header
        header = parse_wal_header(WAL_PATH)
        assert header['salt1'] != 0 or header['salt2'] != 0


# ---------------------------------------------------------------------------
# Frame parsing
# ---------------------------------------------------------------------------

class TestFrameParsing:

    def test_frame_count_minimum(self):
        """4 transactions produce at least 4 frames (one commit each)."""
        from wal_forensics import parse_frames
        frames = parse_frames(WAL_PATH)
        assert len(frames) >= 4, f"Expected >= 4 frames, got {len(frames)}"

    def test_frame_count_bounded(self):
        """Sanity: shouldn't have an absurd number of frames."""
        from wal_forensics import parse_frames
        frames = parse_frames(WAL_PATH)
        assert len(frames) <= 30

    def test_all_frames_have_valid_checksums(self):
        from wal_forensics import parse_frames
        frames = parse_frames(WAL_PATH)
        for f in frames:
            assert f['checksum_valid'] is True, \
                f"Frame {f['index']} has invalid checksum"

    def test_all_frames_have_valid_salt(self):
        from wal_forensics import parse_frames
        frames = parse_frames(WAL_PATH)
        for f in frames:
            assert f['salt_valid'] is True, \
                f"Frame {f['index']} has mismatched salt"

    def test_frame_page_numbers_positive(self):
        from wal_forensics import parse_frames
        frames = parse_frames(WAL_PATH)
        for f in frames:
            assert f['page_number'] > 0, \
                f"Frame {f['index']} has invalid page number {f['page_number']}"

    def test_commit_frames_exist(self):
        """There should be at least 4 commit frames (one per transaction)."""
        from wal_forensics import parse_frames
        frames = parse_frames(WAL_PATH)
        commits = [f for f in frames if f['is_commit']]
        assert len(commits) == 4, f"Expected 4 commit frames, got {len(commits)}"

    def test_stored_vs_computed_checksum_match(self):
        from wal_forensics import parse_frames
        frames = parse_frames(WAL_PATH)
        for f in frames:
            assert f['stored_checksum'] == f['computed_checksum'], \
                f"Frame {f['index']}: stored {f['stored_checksum']} != computed {f['computed_checksum']}"

    def test_frame_offsets_sequential(self):
        """Frame offsets should increase by (FRAME_HEADER + page_size)."""
        from wal_forensics import parse_frames, parse_wal_header
        header = parse_wal_header(WAL_PATH)
        ps = header['page_size']
        frames = parse_frames(WAL_PATH)
        for i in range(1, len(frames)):
            expected = frames[i-1]['offset'] + FRAME_HEADER_SIZE + ps
            assert frames[i]['offset'] == expected, \
                f"Frame {i} offset {frames[i]['offset']} != expected {expected}"


# ---------------------------------------------------------------------------
# Transaction identification
# ---------------------------------------------------------------------------

class TestTransactionIdentification:

    def test_transaction_count(self):
        from wal_forensics import identify_transactions
        txns = identify_transactions(WAL_PATH)
        assert len(txns) == 4, f"Expected 4 transactions, got {len(txns)}"

    def test_each_transaction_ends_with_commit(self):
        from wal_forensics import identify_transactions
        txns = identify_transactions(WAL_PATH)
        for txn in txns:
            last = txn['frames'][-1]
            assert last['is_commit'] is True, \
                f"Txn {txn['index']} last frame not a commit"

    def test_transaction_indices(self):
        from wal_forensics import identify_transactions
        txns = identify_transactions(WAL_PATH)
        for i, txn in enumerate(txns):
            assert txn['index'] == i

    def test_pages_modified_nonempty(self):
        from wal_forensics import identify_transactions
        txns = identify_transactions(WAL_PATH)
        for txn in txns:
            assert len(txn['pages_modified']) > 0

    def test_frame_count_matches_frames_list(self):
        from wal_forensics import identify_transactions
        txns = identify_transactions(WAL_PATH)
        for txn in txns:
            assert txn['frame_count'] == len(txn['frames'])

    def test_total_frames_match(self):
        """Sum of transaction frame counts should equal total valid frames."""
        from wal_forensics import identify_transactions, parse_frames
        txns = identify_transactions(WAL_PATH)
        frames = parse_frames(WAL_PATH)
        total = sum(t['frame_count'] for t in txns)
        assert total == len(frames)


# ---------------------------------------------------------------------------
# Database reconstruction
# ---------------------------------------------------------------------------

class TestReconstruction:

    def test_reconstruct_txn0_row_count(self):
        """After txn 0: 3 sensor rows."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn0.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 0, out)
        conn = sqlite3.connect(out)
        count = conn.execute('SELECT COUNT(*) FROM sensors').fetchone()[0]
        conn.close()
        assert count == 3

    def test_reconstruct_txn0_exact_data(self):
        """Verify exact data at transaction 0."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn0_data.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 0, out)
        conn = sqlite3.connect(out)
        rows = conn.execute(
            'SELECT id, name, value, status FROM sensors ORDER BY id'
        ).fetchall()
        conn.close()
        assert rows == [
            (1, 'temp_north', 22.5, 'active'),
            (2, 'temp_south', 24.1, 'active'),
            (3, 'humidity', 65.0, 'active'),
        ]

    def test_reconstruct_txn1_row_count(self):
        """After txn 1: 4 sensors."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn1.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 1, out)
        conn = sqlite3.connect(out)
        count = conn.execute('SELECT COUNT(*) FROM sensors').fetchone()[0]
        conn.close()
        assert count == 4

    def test_reconstruct_txn1_updated_values(self):
        """After txn 1: sensor 1 value updated, sensor 4 added."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn1_vals.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 1, out)
        conn = sqlite3.connect(out)
        v1 = conn.execute('SELECT value FROM sensors WHERE id=1').fetchone()[0]
        assert abs(v1 - 23.1) < 0.01
        v2 = conn.execute('SELECT value FROM sensors WHERE id=2').fetchone()[0]
        assert abs(v2 - 25.0) < 0.01
        v4 = conn.execute('SELECT value FROM sensors WHERE id=4').fetchone()[0]
        assert abs(v4 - 1013.25) < 0.01
        conn.close()

    def test_reconstruct_txn2_row_count(self):
        """After txn 2: 5 sensors."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn2.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 2, out)
        conn = sqlite3.connect(out)
        count = conn.execute('SELECT COUNT(*) FROM sensors').fetchone()[0]
        conn.close()
        assert count == 5

    def test_reconstruct_txn2_sensor3_failed(self):
        """After txn 2: sensor 3 status is 'failed'."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn2_s3.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 2, out)
        conn = sqlite3.connect(out)
        status = conn.execute('SELECT status FROM sensors WHERE id=3').fetchone()[0]
        assert status == 'failed'
        value = conn.execute('SELECT value FROM sensors WHERE id=3').fetchone()[0]
        assert abs(value - (-1.0)) < 0.01
        conn.close()

    def test_reconstruct_txn2_sensor1_updated(self):
        """After txn 2: sensor 1 value re-updated to 22.8."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn2_s1.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 2, out)
        conn = sqlite3.connect(out)
        v = conn.execute('SELECT value FROM sensors WHERE id=1').fetchone()[0]
        conn.close()
        assert abs(v - 22.8) < 0.01

    def test_reconstruct_txn3_row_count(self):
        """After txn 3: 6 sensors (one deleted, two added)."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn3.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 3, out)
        conn = sqlite3.connect(out)
        count = conn.execute('SELECT COUNT(*) FROM sensors').fetchone()[0]
        conn.close()
        assert count == 6

    def test_reconstruct_txn3_sensor5_deleted(self):
        """After txn 3: sensor 5 was deleted."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn3_del.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 3, out)
        conn = sqlite3.connect(out)
        r = conn.execute('SELECT COUNT(*) FROM sensors WHERE id=5').fetchone()[0]
        conn.close()
        assert r == 0

    def test_reconstruct_txn3_sensor3_recovered(self):
        """After txn 3: sensor 3 status is 'recovered'."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn3_rec.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 3, out)
        conn = sqlite3.connect(out)
        row = conn.execute(
            'SELECT value, status FROM sensors WHERE id=3'
        ).fetchone()
        conn.close()
        assert abs(row[0] - 67.0) < 0.01
        assert row[1] == 'recovered'

    def test_reconstruct_txn3_new_sensors(self):
        """After txn 3: sensors 6 and 7 exist."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn3_new.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 3, out)
        conn = sqlite3.connect(out)
        s6 = conn.execute(
            'SELECT name, value, status FROM sensors WHERE id=6'
        ).fetchone()
        s7 = conn.execute(
            'SELECT name, value, status FROM sensors WHERE id=7'
        ).fetchone()
        conn.close()
        assert s6 == ('co2', 412.5, 'active')
        assert s7 == ('light', 850.0, 'active')

    def test_reconstruct_txn3_full_snapshot(self):
        """Full value snapshot at final transaction."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_txn3_full.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 3, out)
        conn = sqlite3.connect(out)
        data = dict(conn.execute('SELECT id, value FROM sensors').fetchall())
        ids = set(conn.execute('SELECT id FROM sensors').fetchall())
        conn.close()
        assert abs(data[1] - 22.8) < 0.01
        assert abs(data[2] - 24.5) < 0.01
        assert abs(data[3] - 67.0) < 0.01
        assert abs(data[4] - 1013.25) < 0.01
        assert 5 not in data
        assert abs(data[6] - 412.5) < 0.01
        assert abs(data[7] - 850.0) < 0.01

    def test_reconstructed_db_no_wal_needed(self):
        """Reconstructed database must be openable without a WAL file."""
        from wal_forensics import reconstruct_at_transaction
        out = '/tmp/test_standalone.db'
        reconstruct_at_transaction(DB_PATH, WAL_PATH, 3, out)
        # Ensure no WAL/SHM files exist for the output
        assert not os.path.exists(out + '-wal')
        assert not os.path.exists(out + '-shm')
        # Verify database opens and is usable
        conn = sqlite3.connect(out)
        conn.execute('SELECT * FROM sensors')
        conn.close()


# ---------------------------------------------------------------------------
# Checksum validation
# ---------------------------------------------------------------------------

class TestChecksumValidation:

    def test_validate_all_valid(self):
        from wal_forensics import validate_checksums
        result = validate_checksums(WAL_PATH)
        assert result['header_valid'] is True
        for f in result['frames']:
            assert f['valid'] is True, \
                f"Frame {f['index']} reported as invalid"

    def test_detect_corruption(self):
        """Flipping a byte in page data must cause checksum failure."""
        corrupted_path = '/tmp/corrupted_test.db-wal'
        shutil.copy2(WAL_PATH, corrupted_path)

        # Corrupt a byte in the first frame's page data
        # First frame: offset WAL_HEADER_SIZE(32) + FRAME_HEADER(24) + 4 = 60
        with open(corrupted_path, 'r+b') as f:
            f.seek(60)
            b = f.read(1)
            f.seek(60)
            f.write(bytes([(b[0] ^ 0xFF)]))

        from wal_forensics import validate_checksums
        result = validate_checksums(corrupted_path)
        # Header should still be valid
        assert result['header_valid'] is True
        # First frame must be invalid
        assert len(result['frames']) > 0
        assert result['frames'][0]['valid'] is False

    def test_detect_corruption_breaks_chain(self):
        """Corrupting frame N should prevent parsing valid frames after N."""
        from wal_forensics import parse_wal_header, parse_frames

        header = parse_wal_header(WAL_PATH)
        page_size = header['page_size']
        frame_size = FRAME_HEADER_SIZE + page_size

        # Count original valid frames
        original_frames = parse_frames(WAL_PATH)
        original_count = len(original_frames)
        assert original_count >= 4

        # Corrupt second frame's page data
        corrupted_path = '/tmp/chain_test.db-wal'
        shutil.copy2(WAL_PATH, corrupted_path)

        second_frame_offset = WAL_HEADER_SIZE + frame_size + FRAME_HEADER_SIZE + 10
        with open(corrupted_path, 'r+b') as f:
            f.seek(second_frame_offset)
            b = f.read(1)
            f.seek(second_frame_offset)
            f.write(bytes([(b[0] ^ 0xFF)]))

        corrupted_frames = parse_frames(corrupted_path)
        # First frame should still be valid
        assert corrupted_frames[0]['checksum_valid'] is True
        # Second frame should be invalid
        assert len(corrupted_frames) >= 2
        assert corrupted_frames[1]['checksum_valid'] is False
        # Parsing should stop - fewer frames than original
        assert len(corrupted_frames) < original_count
